import os
os.environ.setdefault('VAULT_PATH', '/tmp/pachimind-association-tests-unused')
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.core.vault_index import vault_index
from app.core.meeting_capture import serialize
from app.core.id_utils import path_to_id
from app.core.people import relation_key, save
from app.middleware.auth import get_scope
from app.routers.associations import router


class AssociationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous = settings.vault_path, vault_index._notes, vault_index._vault_root
        settings.vault_path = str(self.root)
        vault_index.build(self.root)
        self.scope = 'personal'
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_scope] = lambda: self.scope
        self.client = TestClient(app)

    def tearDown(self):
        settings.vault_path, vault_index._notes, vault_index._vault_root = self.previous
        self.tmp.cleanup()

    def note(self, name, body='', **extra):
        p = self.root / (name + '.md'); p.parent.mkdir(parents=True, exist_ok=True)
        meta = dict(titulo=Path(name).name, tipo='nota', estado='activo', ia_permiso='allow', ia_indexar=True)
        meta.update(extra); p.write_text(serialize(meta, body or '# ' + meta['titulo']))
        vault_index.rebuild_file(p)
        return path_to_id(str(p.relative_to(self.root)))

    def detail(self, note_id, assistant=False):
        return self.client.get('/vault/associations/' + note_id,
                               headers={'X-PachiMind-Actor': 'assistant'} if assistant else {})

    def test_incoming_connection_is_not_an_orphan_and_ambito_is_not_a_link(self):
        project = self.note('Proyecto', tipo='proyecto')
        linked = self.note('Con entrada', area='Laboral')
        self.note('Otra nota', '[[Con entrada]] [[Proyecto]]')
        orphan = self.note('Sin enlaces', area='Laboral')
        entry = self.detail(linked).json()
        self.assertFalse(entry['orphan']); self.assertEqual(entry['incoming_count'], 1)
        self.assertEqual(entry['outgoing_count'], 0)
        self.assertEqual(entry['ambitos'], ['Trabajo'])
        self.assertEqual(entry['general_nodes'][0]['id'], project)
        self.assertEqual(entry['general_nodes'][0]['depth'], 2)
        self.assertTrue(self.detail(orphan).json()['orphan'])
        audit = self.client.get('/vault/associations').json()
        self.assertEqual([n['id'] for n in audit['results']], [orphan])
        self.assertEqual(audit['summary']['notes'], 4)

    def test_explicit_properties_resolve_aliases_and_no_prose_or_role_inference(self):
        project = self.note('Planes/Real', titulo='Plan de prueba', tipo='proyecto', aliases=['Alias del plan'])
        person = self.note('Persona', tipo='persona')
        n = self.note('Fuente', 'Se menciona Persona sin un enlace.', proyectos=['[[Alias del plan]]'],
                      personas=['Persona'], ambitos=['Formación', 'Trabajo'], area='Laboral')
        entry = self.detail(n).json()
        self.assertEqual({g['id'] for g in entry['general_nodes']}, {project, person})
        self.assertEqual(entry['ambitos'], ['Formación', 'Trabajo'])
        self.assertTrue(all(c['relation'] == 'referencia' for c in entry['connections']))
        prose = self.note('Sólo texto', 'Se menciona Plan de prueba y Persona.')
        self.assertTrue(self.detail(prose).json()['orphan'])

    def test_invalid_ambiguous_self_references_and_pending_links_do_not_connect(self):
        self.note('uno', titulo='Duplicado'); self.note('dos', titulo='Duplicado')
        n = self.note('Origen', '[[Inexistente]] [[Duplicado]] [[Origen]] [[10 Sensible/no-mostrar]] [[10 Sensible\\no-mostrar]]')
        save('changes', 'a'*32, {'state':'pending', 'kind':'links', 'target_id':n, 'links':[]})
        entry = self.detail(n).json()
        self.assertTrue(entry['orphan'])
        self.assertEqual(entry['broken_links'], ['Inexistente'])
        self.assertEqual(entry['ambiguous_links'], ['Duplicado'])
        self.assertEqual(entry['unresolved_count'], 2)
        self.assertNotIn('no-mostrar', json.dumps(entry))

    def test_private_nodes_proofs_and_paths_never_leak_or_bridge_for_assistants(self):
        public = self.note('Pública')
        private = self.note('Privada', '[[Pública]]', tipo='proyecto', sensibilidad='privado')
        allowed_project = self.note('Proyecto visible', '[[Privada]]', tipo='proyecto')
        self.note('10 Sensible/Secret', '[[Pública]]')
        blocked = self.note('Sin permiso', '[[Pública]]', ia_indexar=False)
        key = relation_key(public, allowed_project, 'relacionado con')
        save('relations', key, dict(id=key, source_id=public, target_id=allowed_project,
             relation='relacionado con', origin='assistant', active=True,
             evidence={'source_id':private}))
        human = self.detail(public).json(); self.assertFalse(human['orphan'])
        assistant = self.detail(public, True).json(); self.assertTrue(assistant['orphan'])
        self.assertEqual(assistant['general_nodes'], [])
        self.assertEqual(self.detail(private, True).status_code, 404)
        self.assertEqual(self.detail(blocked, True).status_code, 404)
        self.scope = 'ai_context'
        audit = self.client.get('/vault/associations?view=all').json()
        self.assertEqual(audit['summary']['notes'], 2)
        self.assertNotIn('Secret', json.dumps(audit)); self.assertNotIn('Privada', json.dumps(audit))

    def test_applied_and_removed_overlays_are_respected(self):
        project = self.note('Proyecto', tipo='proyecto')
        n = self.note('Origen', '[[Proyecto]]')
        key = relation_key(n, project, 'referencia')
        save('relations', key, dict(id=key, source_id=n, target_id=project,
             relation='referencia', active=False))
        self.assertTrue(self.detail(n).json()['orphan'])
        key = relation_key(n, project, 'vinculado al proyecto')
        save('relations', key, dict(id=key, source_id=n, target_id=project,
             relation='vinculado al proyecto', active=True, origin='manual'))
        entry = self.detail(n).json()
        self.assertFalse(entry['orphan']); self.assertEqual(entry['connections'][0]['relation'], 'vinculado al proyecto')

    def test_pagination_covers_all_notes_and_filters_do_not_redefine_global_totals(self):
        for i in range(105):
            self.note('Nota ' + str(i), area='Laboral' if i < 4 else 'Personal')
        first = self.client.get('/vault/associations?per_page=100').json()
        second = self.client.get('/vault/associations?per_page=100&page=2').json()
        self.assertEqual(first['total'], 105)
        self.assertEqual(len({n['id'] for n in first['results'] + second['results']}), 105)
        filtered = self.client.get('/vault/associations?ambito=Trabajo').json()
        self.assertEqual(filtered['total'], 4); self.assertEqual(filtered['summary']['notes'], 105)
        self.assertEqual(self.client.get('/vault/associations?per_page=101').status_code, 422)

    def test_no_general_is_distinct_from_orphan_and_walks_stop_after_two_hops(self):
        self.note('A', '[[B]]')
        self.note('B', '[[C]]')
        c = self.note('C', '[[Proyecto]]')
        self.note('Proyecto', tipo='proyecto')
        self.assertTrue(self.detail(path_to_id('A.md')).json()['no_general_node'])
        self.assertFalse(self.detail(c).json()['no_general_node'])
        result = self.client.get('/vault/associations?view=no_general').json()
        self.assertEqual([n['title'] for n in result['results']], ['A'])
        self.assertEqual(result['summary']['orphans'], 0)

    def test_audit_does_not_change_notes_permissions_or_immutable_sources(self):
        n = self.note('Inmutable', '[[Inexistente]]', fuente_inmutable=True, revisado=True, ia_editar=False)
        p = self.root/'Inmutable.md'; before = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(self.client.get('/vault/associations?view=all').status_code, 200)
        response = self.detail(n)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), before)
        self.assertEqual(self.client.post('/vault/associations', json={}).status_code, 405)
