import os
os.environ.setdefault('VAULT_PATH', '/tmp/pachimind-people-tests-unused')
import hashlib, json, logging, unittest, asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import frontmatter
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.core.vault_index import vault_index
from app.core import people
from app.core.meeting_capture import serialize
from app.core.id_utils import path_to_id
from app.core.vault_linker import generate_links_for_note
from app.middleware.auth import get_scope
from app.routers import people_workspace, people as legacy_people, notes, search, vault, ai, projects, links as legacy_links
logging.disable(logging.CRITICAL)

class PeopleWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.old = (settings.vault_path, vault_index._notes, vault_index._vault_root)
        settings.vault_path = str(self.root); vault_index.build(self.root)
        self.scope = 'personal'
        self.app = FastAPI()
        for module in (people_workspace, legacy_people, notes, search, vault, ai, projects, legacy_links):
            self.app.include_router(module.router)
        self.app.dependency_overrides[get_scope] = lambda: self.scope
        self.c = TestClient(self.app)
        self.person = self.note('04 Entidades/Personas/iris.md', 'Iris Demo', tipo='persona', revisado=True, ia_editar=False)
        self.source = self.note('06 Reuniones y Registros/demo.md', 'Fuente demo',
                                'Iris coordina Organización Demo. Se menciona a Iris.', tipo='reunion', fuente_inmutable=True)
        self.project = self.note('05 Proyectos/demo.md', 'Proyecto Demo', tipo='proyecto')
    def tearDown(self):
        settings.vault_path, vault_index._notes, vault_index._vault_root = self.old
        self.tmp.cleanup()
    def note(self, path, title, content='', **meta):
        defaults = {'titulo': title, 'tipo': 'nota', 'estado': 'activo', 'sensibilidad': 'normal',
                    'ia_permiso': 'allow', 'ia_indexar': True, 'ia_editar': False, 'revisado': False}
        defaults.update(meta); p = self.root / path; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(serialize(defaults, content or ('# ' + title + '\n')))
        vault_index.rebuild_file(p); return path_to_id(path)
    def get(self, person=None, assistant=False):
        r = self.c.get('/people/' + (person or self.person) + '/profile', headers=self.actor(assistant))
        self.assertEqual(r.status_code, 200, r.text); return r.json()
    def actor(self, assistant=False):
        return {'X-PachiMind-Actor': 'assistant' if assistant else 'manual'}
    def create(self, name='Nueva Persona Demo', assistant=False, request=None):
        body = {'nombre': name, 'request_id': request or str(uuid4())}
        r = self.c.post('/people/drafts', json=body, headers=self.actor(assistant))
        self.assertEqual(r.status_code, 201, r.text); return r.json(), body
    def proposal(self, person=None, fields=None, assistant=True):
        person = person or self.person
        body = {'request_id': str(uuid4()), 'revision': self.get(person)['revision'],
                'fields': fields or {'organizacion': 'Organización Demo'},
                'evidence': [{'field': 'organizacion', 'source_id': self.source, 'quote': 'Iris coordina Organización Demo.'}]}
        r = self.c.post('/people/' + person + '/proposals', json=body, headers=self.actor(assistant))
        self.assertEqual(r.status_code, 201, r.text); return r.json(), body
    def review(self, change, revision, assistant=False, action='apply', authorized=None, request=None):
        body = {'request_id': request or str(uuid4()), 'revision': revision, 'action': action,
                'authorized_fields': authorized if authorized is not None else ['organizacion']}
        return self.c.post('/people/changes/' + change + '/review', json=body, headers=self.actor(assistant)), body
    def link(self, source, target, relation='relacionado con', assistant=False, action='add', request=None):
        body = {'request_id': request or str(uuid4()), 'source_id': source,
                'revision': people.revision(vault_index.get(source)), 'links': [{'target_id': target,
                'target_revision': people.revision(vault_index.get(target)), 'relation': relation, 'action': action}]}
        if assistant:
            body['links'][0]['evidence'] = {'field': 'relation', 'source_id': self.source, 'quote': 'Se menciona a Iris.'}
        r = self.c.post('/vault/relations/proposals', json=body, headers=self.actor(assistant))
        return r, body
    def test_existing_people_alias_search_and_deduplication(self):
        for name in ['Andrés', 'Sabrina Ramirez', 'Uriel Cabrera', 'Giovana', 'Genaro']:
            self.note('04 Entidades/Personas/' + name + '.md', name, tipo='persona')
        alias = self.note('04 Entidades/Personas/alias.md', 'Lucía Demo', tipo='persona', alias='Lu', rol='Función declarada', organizacion='Institución Demo', ambitos=['Trabajo', 'Formación'])
        items = self.c.get('/people/directory').json(); self.assertEqual(items['total'], 7)
        for query in ['Lu', 'Institución Demo']:
            result = self.c.get('/people/directory', params={'q': query}).json()['results']
            self.assertEqual(result[0]['id'], alias)
        self.assertEqual(self.get(alias)['fields']['funcion'], 'Función declarada')
        before = len(list(self.root.rglob('*.md')))
        result, body = self.create('Iris Demo', assistant=True)
        self.assertEqual(result['id'], self.person); self.assertFalse(result['created']); self.assertTrue(result['needs_identity_review'])
        self.assertEqual(len(list(self.root.rglob('*.md'))), before)
        self.assertEqual(len(self.c.get('/people').json()), 7)
    def test_minimal_manual_create_complete_preview_revision_and_undo(self):
        created, _ = self.create(); profile = self.get(created['id'])
        self.assertIn('organizacion', profile['pending_fields']); self.assertFalse(profile['metadata']['revisado'])
        path = self.root / created['path']; original_body = path.read_text().split('---\n', 2)[2]
        fields = {'organizacion': 'Organización Manual Demo', 'funcion': 'Función ingresada manualmente', 'ambitos': ['Trabajo', 'Colegios'],
                  'aliases': ['Alias Demo'], 'contactos_profesionales': {'email_profesional': 'demo@example.test'}}
        body = {'request_id': str(uuid4()), 'revision': profile['revision'], 'fields': fields, 'confirm_review': True}
        r = self.c.patch('/people/' + created['id'] + '/profile', json=body)
        self.assertEqual(r.status_code, 200, r.text)
        result = self.get(created['id']); self.assertTrue(result['metadata']['revisado']); self.assertEqual(result['fields']['ambitos'], ['Trabajo', 'Colegios'])
        self.assertEqual(path.read_text().split('---\n', 2)[2], original_body)
        undo = self.c.post('/people/history/' + r.json()['history_id'] + '/undo', json={'request_id': str(uuid4()), 'revision': result['revision']})
        self.assertEqual(undo.status_code, 200, undo.text); self.assertIsNone(self.get(created['id'])['fields']['organizacion'])
    def test_ai_draft_proposal_not_fact_explicit_apply_and_retry(self):
        created, body = self.create(assistant=True)
        retry = self.c.post('/people/drafts', json=body, headers=self.actor(True)).json(); self.assertEqual(retry['id'], created['id']); self.assertFalse(retry['created'])
        proposal, request = self.proposal(created['id'])
        self.assertIsNone(self.get(created['id'])['fields']['organizacion'])
        self.assertEqual(self.get(created['id'])['pending_changes'], 1)
        again = self.c.post('/people/' + created['id'] + '/proposals', json=request, headers=self.actor(True))
        self.assertEqual(again.json()['id'], proposal['id'])
        denied, _ = self.review(proposal['id'], created['revision'], assistant=True, authorized=[])
        self.assertEqual(denied.status_code, 422)
        applied, apply_body = self.review(proposal['id'], created['revision'], assistant=True)
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(self.get(created['id'])['fields']['organizacion'], 'Organización Demo')
        self.assertFalse(self.get(created['id'])['metadata']['revisado'])
        again = self.c.post('/people/changes/' + proposal['id'] + '/review', json=apply_body, headers=self.actor(True))
        self.assertEqual(again.json(), applied.json())
    def test_protected_person_keeps_separate_proposal_for_human(self):
        path = self.root / vault_index.get(self.person).path; before = path.read_bytes()
        proposal, _ = self.proposal()
        denied, _ = self.review(proposal['id'], proposal['base_revision'], assistant=True)
        self.assertEqual(denied.status_code, 409); self.assertEqual(path.read_bytes(), before)
        applied, _ = self.review(proposal['id'], proposal['base_revision'])
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertFalse(self.get()['metadata']['ia_editar']); self.assertTrue(self.get()['metadata']['revisado'])
        self.assertEqual(self.get()['field_sources']['organizacion'][0]['source_id'], self.source)
    def test_conflict_does_not_overwrite_manual_change(self):
        proposal, _ = self.proposal(); stale = self.get()['revision']
        body = {'request_id': str(uuid4()), 'revision': stale, 'fields': {'organizacion': 'Manual posterior'}}
        self.assertEqual(self.c.patch('/people/' + self.person + '/profile', json=body).status_code, 200)
        r, _ = self.review(proposal['id'], stale); self.assertEqual(r.status_code, 409)
        self.assertEqual(self.get()['fields']['organizacion'], 'Manual posterior')
        self.assertEqual(self.c.patch('/notes/' + self.person, json={'organizacion': 'Sin revisión'}).status_code, 428)
        self.assertEqual(self.c.patch('/people/' + self.person + '/profile', json={**body, 'request_id': str(uuid4())}).status_code, 409)
    def test_literal_evidence_source_revision_and_missing_sources(self):
        proposal, _ = self.proposal()
        p = self.root / vault_index.get(self.source).path; p.write_text(p.read_text() + '\nEdición externa')
        r, _ = self.review(proposal['id'], proposal['base_revision']); self.assertEqual(r.status_code, 409)
        bad = {'request_id': str(uuid4()), 'revision': self.get()['revision'], 'fields': {'funcion': 'Inventado'},
               'evidence': [{'field': 'funcion', 'source_id': self.source, 'quote': 'No está en la fuente'}]}
        self.assertEqual(self.c.post('/people/' + self.person + '/proposals', json=bad, headers=self.actor(True)).status_code, 422)
        bad['evidence'][0]['source_id'] = 'no-existe'
        self.assertEqual(self.c.post('/people/' + self.person + '/proposals', json=bad, headers=self.actor(True)).status_code, 404)
    def test_read_only_api_keys_cannot_create_apply_or_propose(self):
        proposal, _ = self.proposal()
        for scope in ['ai_context', 'public']:
            self.scope = scope
            self.assertEqual(self.c.post('/people/drafts', json={'nombre': 'No autorizado', 'request_id': str(uuid4())}).status_code, 403)
            r, _ = self.review(proposal['id'], proposal['base_revision']); self.assertEqual(r.status_code, 403)
        self.scope = 'ai_context'; self.assertEqual(self.c.get('/people/directory').status_code, 200)
    def test_reserved_content_excluded_from_directory_search_graph_stats_context_export(self):
        for i, extra in enumerate([{'sensibilidad': 'privado'}, {'sensibilidad': 'sensible'}, {'sensibilidad': 'secreto'}, {'ia_permiso': 'deny'}, {'ia_indexar': False}]):
            self.note(f'04 Entidades/Personas/reservada-{i}.md', f'Reservada {i}', 'NO DIVULGAR RESERVADO', tipo='persona', tags=['oculto'], **extra)
        self.note('04 Entidades/_privado_personal/oculta.md', 'RUTA RESERVADA', 'NO DIVULGAR RUTA', tipo='persona')
        self.scope = 'ai_context'
        for path in ['/people/directory', '/search?q=RESERVADO', '/vault/relations', '/vault/activity']:
            body = self.c.get(path).text; self.assertNotIn('NO DIVULGAR', body); self.assertNotIn('Reservada', body); self.assertNotIn('RUTA RESERVADA', body)
        self.assertEqual(self.c.get('/vault/stats').json()['total_notes'], 3)
        self.assertNotIn('Reservada', self.c.post('/ai/context', json={'query': 'RESERVADO', 'max_results': 20, 'filters': {}}).text)
        self.scope = 'personal'
        project = vault_index.get(self.project)
        for n in vault_index.all():
            if n.metadata.tipo == 'persona' and n.id != self.person:
                post = frontmatter.load(str(self.root/n.path)); post.metadata['proyectos'] = ['[[Proyecto Demo]]']; (self.root/n.path).write_text(frontmatter.dumps(post)); vault_index.rebuild_file(self.root/n.path)
        export = self.c.get('/projects/' + project.id + '/memory.md').text
        self.assertNotIn('NO DIVULGAR', export)
    def test_provenance_and_relationship_evidence_privacy_follows_source(self):
        proposal, _ = self.proposal(); r, _ = self.review(proposal['id'], proposal['base_revision']); self.assertEqual(r.status_code, 200)
        path = self.root / vault_index.get(self.source).path
        post = frontmatter.load(str(path)); post.metadata['sensibilidad'] = 'privado'; path.write_text(frontmatter.dumps(post)); vault_index.rebuild_file(path)
        self.scope = 'ai_context'
        self.assertEqual(self.c.get('/people/' + self.person + '/profile').status_code, 404)
        self.scope = 'personal'
        self.assertEqual(self.c.get('/notes/' + self.person, headers=self.actor(True)).status_code, 403)
        self.scope = 'ai_context'
        for endpoint in ['/people/directory', '/search?q=Organización', '/vault/relations', '/notes?tipo=persona']:
            self.assertNotIn('Organización Demo', self.c.get(endpoint).text)
    def test_links_both_directions_and_no_outgoing_is_not_unconnected(self):
        other = self.note('04 Entidades/Personas/otra.md', 'Otra Demo', tipo='persona')
        r, body = self.link(self.person, other, 'trabaja con'); self.assertEqual(r.status_code, 201, r.text)
        result, apply = self.review(r.json()['id'], body['revision'], authorized=['relations']); self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.get()['outgoing_count'], 1); self.assertEqual(self.get(other)['incoming_count'], 1)
        ids = [x['id'] for x in self.c.get('/people/directory?view=unconnected').json()['results']]; self.assertNotIn(other, ids)
        ids = [x['id'] for x in self.c.get('/people/directory?view=no_outgoing').json()['results']]; self.assertIn(other, ids)
        retry = self.c.post('/people/changes/' + r.json()['id'] + '/review', json=apply); self.assertEqual(retry.json(), result.json())
        self.assertEqual(len(self.c.get('/vault/relations').json()['relations']), 1)
    def test_immutable_original_annotated_in_separate_layer_then_removed_and_undone(self):
        path = self.root / vault_index.get(self.source).path; original = path.read_bytes()
        r, body = self.link(self.source, self.person)
        result, _ = self.review(r.json()['id'], body['revision'], authorized=['relations']); self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(path.read_bytes(), original); self.assertEqual(self.get()['incoming_count'], 1)
        r, body = self.link(self.source, self.person, action='remove')
        result, _ = self.review(r.json()['id'], body['revision'], authorized=['relations']); self.assertEqual(result.status_code, 200)
        self.assertEqual(self.get()['incoming_count'], 0); self.assertEqual(path.read_bytes(), original)
        undo = self.c.post('/people/history/' + result.json()['history_id'] + '/undo', json={'request_id': str(uuid4()), 'revision': result.json()['revision']})
        self.assertEqual(undo.status_code, 200, undo.text); self.assertEqual(self.get()['incoming_count'], 1); self.assertEqual(path.read_bytes(), original)
    def test_mention_is_not_participation_and_wrong_type_or_missing_target_rejected(self):
        r, _ = self.link(self.person, self.source, 'participó en', assistant=True); self.assertEqual(r.status_code, 422)
        r, _ = self.link(self.person, self.source, 'mencionado en', assistant=True); self.assertEqual(r.status_code, 201, r.text)
        r, _ = self.link(self.person, self.source, 'vinculado al proyecto'); self.assertEqual(r.status_code, 422)
        body = {'request_id': str(uuid4()), 'source_id': self.person, 'revision': self.get()['revision'],
                'links': [{'target_id': 'no-existe', 'target_revision': '0'*64, 'relation': 'fuente'}]}
        self.assertEqual(self.c.post('/vault/relations/proposals', json=body).status_code, 404)
    def test_legacy_links_broken_ambiguity_and_no_inferred_mentions(self):
        self.note('07 Conocimiento/entrada.md', 'Entrada', '[[04 Entidades/Personas/iris]] y [[No existe]]. Iris Demo sin wikilink.', tipo='nota')
        self.assertEqual(self.get()['incoming_count'], 1)
        self.note('04 Entidades/Personas/iris-dos.md', 'Iris Demo', tipo='persona')
        self.note('07 Conocimiento/ambigua.md', 'Ambigua', '[[Iris Demo]]', tipo='nota')
        self.assertEqual(self.get()['incoming_count'], 1)
        self.assertEqual(vault_index.resolve_wikilinks(['Iris Demo'])['Iris Demo'], None)
        self.note('04 Entidades/Personas/sin.md', 'Sin Demo', '[[No existe]]', tipo='persona')
        self.assertEqual(self.get('04-entidades-personas-sin')['broken_links'], ['No existe'])
    def test_no_date_knowledge_draft_retry_and_neutral_reserved_segments(self):
        body = {'request_id': str(uuid4()), 'title': 'Contexto sin fecha', 'kind': 'contexto', 'content': 'Resumen elaborado; no transcripción.',
                'source_ids': [self.source], 'reserved_segments': [{'source_reference': 'grabacion-demo', 'start_seconds': 60, 'end_seconds': 90}]}
        r = self.c.post('/notes/knowledge-drafts', json=body, headers=self.actor(True)); self.assertEqual(r.status_code, 201, r.text)
        first = r.json(); retry = self.c.post('/notes/knowledge-drafts', json=body, headers=self.actor(True)).json()
        self.assertEqual(first['id'], retry['id']); self.assertFalse(retry['created'])
        post = frontmatter.load(str(self.root/first['path'])); self.assertNotIn('fecha', post.metadata); self.assertNotEqual(post.metadata['tipo'], 'reunion')
        self.assertEqual(post.content, body['content']); self.assertFalse(post.metadata['revisado']); self.assertFalse(post.metadata['ia_indexar'])
        self.assertEqual(post.metadata['segmentos_reservados'][0]['label'], 'Segmento reservado; contenido no importado')
        self.assertFalse(any(n.path.startswith('.pachimind') for n in vault_index.all()))
    def test_secret_inputs_rejected_and_no_mutation_of_existing_source(self):
        body = {'request_id': str(uuid4()), 'title': 'No guardar', 'kind': 'resumen', 'content': 'api_key=THIS_IS_A_FAKE_SECRET_DO_NOT_STORE'}
        self.assertEqual(self.c.post('/notes/knowledge-drafts', json=body).status_code, 422)
        self.assertFalse(list((self.root/'07 Conocimiento').glob('*')) if (self.root/'07 Conocimiento').exists() else [])
    def test_pagination_ambitos_duplicates_and_classification_warning(self):
        self.note('04 Entidades/Personas/iris-copia.md', 'Iris Demó', tipo='persona', ambitos=['Trabajo', 'Formación'])
        self.note('04 Entidades/Personas/manual.md', 'Manual de prueba', tipo='persona')
        self.note('04 Entidades/Personas/idea.md', 'Idea de prueba', tipo='idea')
        self.assertEqual(self.c.get('/people/directory?per_page=1&page=2').json()['per_page'], 1)
        self.assertEqual(self.c.get('/people/directory?ambito=Formación').json()['total'], 1)
        self.assertGreaterEqual(self.c.get('/people/directory?view=duplicates').json()['total'], 2)
        warnings = [x for x in self.c.get('/people/directory').json()['results'] if x['classification_warning']]
        self.assertEqual(len(warnings), 2)
    def test_question_only_proposal_and_no_inferred_role_or_family(self):
        base = {'request_id': str(uuid4()), 'revision': self.get()['revision'], 'fields': {'funcion': 'Director'},
                'evidence': [{'field': 'funcion', 'source_id': self.source, 'quote': 'Se menciona a Iris.'}]}
        r = self.c.post('/people/' + self.person + '/proposals', json=base, headers=self.actor(True))
        self.assertEqual(r.status_code, 422)
        base.update(request_id=str(uuid4()), fields={}, questions=['¿Cuál es la función confirmada?'])
        base['evidence'][0]['field'] = 'questions'
        r = self.c.post('/people/' + self.person + '/proposals', json=base, headers=self.actor(True))
        self.assertEqual(r.status_code, 201, r.text)
        result, _ = self.review(r.json()['id'], base['revision'], authorized=[])
        self.assertEqual(result.status_code, 422)
        self.assertIsNone(self.get()['fields']['funcion'])
    def test_creation_history_undo_and_retry_preserve_sources(self):
        created, _ = self.create()
        profile = self.get(created['id']); history = profile['history'][0]
        self.assertEqual(history['operation'], 'create_person')
        body = {'request_id': str(uuid4()), 'revision': profile['revision']}
        response = self.c.post('/people/history/' + history['id'] + '/undo', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse((self.root/created['path']).exists())
        self.assertIsNone(vault_index.get(created['id']))
        retry = self.c.post('/people/history/' + history['id'] + '/undo', json=body)
        self.assertEqual(retry.json(), response.json())
        self.assertTrue((self.root/vault_index.get(self.source).path).exists())
    def test_immutable_person_correction_stays_separate_even_for_human(self):
        immutable = self.note('04 Entidades/Personas/inmutable.md', 'Original Demo', tipo='persona', fuente_inmutable=True)
        path = self.root/vault_index.get(immutable).path; before = path.read_bytes()
        proposal, _ = self.proposal(immutable)
        r, _ = self.review(proposal['id'], proposal['base_revision'])
        self.assertEqual(r.status_code, 409); self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.get(immutable)['pending_changes'], 1)
    def test_filename_identity_review_and_reserved_segment_validation(self):
        existing = self.note('04 Entidades/Personas/Genaro.md', 'Genaro — [[Organización de ejemplo]]', tipo='persona')
        result, _ = self.create('Genaro', assistant=True)
        self.assertEqual(result['id'], existing); self.assertFalse(result['created'])
        self.assertEqual(vault_index.resolve_wikilinks(['Genaro — Organización de ejemplo'])['Genaro — Organización de ejemplo'], existing)
        body = {'request_id': str(uuid4()), 'title': 'No importar', 'kind': 'resumen', 'content': 'Resumen no sensible',
                'reserved_segments': [{'source_reference': 'Texto privado que no es una referencia', 'start_seconds': 0, 'end_seconds': 2}]}
        self.assertEqual(self.c.post('/notes/knowledge-drafts', json=body).status_code, 422)

    def test_self_source_and_cyclic_provenance_preserve_permissions(self):
        own = self.note('04 Entidades/Personas/propia.md', 'Propia Demo', 'Organización explícita: Demo.', tipo='persona')
        profile = self.get(own)
        body = {'request_id': str(uuid4()), 'revision': profile['revision'], 'fields': {'organizacion': 'Demo'},
                'evidence': [{'field': 'organizacion', 'source_id': own, 'quote': 'Organización explícita: Demo.'}]}
        response = self.c.patch('/people/' + own + '/profile', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.get(own)['fields']['organizacion'], 'Demo')
        self.scope = 'ai_context'; self.assertEqual(self.c.get('/people/' + own + '/profile').status_code, 200)
        self.scope = 'personal'
        path = self.root / vault_index.get(own).path; post = frontmatter.load(str(path)); post.metadata['sensibilidad'] = 'privado'
        path.write_text(frontmatter.dumps(post)); vault_index.rebuild_file(path)
        self.scope = 'ai_context'; self.assertEqual(self.c.get('/people/' + own + '/profile').status_code, 404)
    def test_incoming_link_change_visible_on_person_and_not_an_access_control_tag(self):
        r, body = self.link(self.source, self.person)
        self.assertEqual(r.status_code, 201)
        pending = self.c.get('/people/changes', params={'note_id': self.person}).json()
        self.assertEqual(pending['results'][0]['id'], r.json()['id'])
        self.assertEqual(self.get()['pending_changes'], 1)
        self.assertEqual(pending['results'][0]['source']['id'], self.source)
        applied, _ = self.review(r.json()['id'], body['revision'], authorized=['relations'])
        self.assertEqual(applied.status_code, 200)
        self.assertTrue(any(h['target_id'] == self.source for h in self.get()['history']))
        plain = self.note('04 Entidades/Personas/etiqueta.md', 'Etiqueta Demo', tipo='persona', tags=['oculto'])
        self.scope = 'ai_context'; self.assertEqual(self.c.get('/people/' + plain + '/profile').status_code, 200)

    def test_renaming_retains_id_body_and_existing_incoming_references(self):
        referring = self.note('07 Conocimiento/ref.md', 'Referencia', '[[Iris Demo]]', tipo='nota')
        before = (self.root/vault_index.get(self.person).path).read_bytes().split(b'---\n', 2)[2]
        body = {'request_id': str(uuid4()), 'revision': self.get()['revision'], 'fields': {'nombre': 'Iris Nombre Corregido'}}
        result = self.c.patch('/people/' + self.person + '/profile', json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['id'], self.person)
        self.assertEqual(self.get()['incoming_count'], 1)
        self.assertEqual(vault_index.resolve_wikilinks(['Iris Demo'])['Iris Demo'], self.person)
        self.assertEqual((self.root/vault_index.get(self.person).path).read_bytes().split(b'---\n', 2)[2], before)

    def test_sensitive_source_not_copied_to_proposals_and_history_omits_body(self):
        source = self.note('07 Conocimiento/reservada.md', 'Fuente privada', 'CONTENIDO PRIVADO DEMO', sensibilidad='privado')
        body = {'request_id': str(uuid4()), 'revision': self.get()['revision'], 'fields': {'organizacion': 'Demo'},
                'evidence': [{'field': 'organizacion', 'source_id': source, 'quote': 'CONTENIDO PRIVADO DEMO'}]}
        self.assertEqual(self.c.post('/people/' + self.person + '/proposals', json=body).status_code, 409)
        self.assertEqual(people.records('changes'), [])
        person = self.note('04 Entidades/Personas/historia.md', 'Historia Demo', 'CUERPO ORIGINAL QUE NO DEBE COPIARSE AL HISTORIAL', tipo='persona')
        profile = self.get(person)
        changed = self.c.patch('/people/' + person + '/profile', json={'request_id': str(uuid4()), 'revision': profile['revision'], 'fields': {'funcion': 'Manual'}})
        self.assertEqual(changed.status_code, 200)
        history = people.load('history', changed.json()['history_id'])
        self.assertNotIn('CUERPO ORIGINAL', json.dumps(history))

    def test_optional_fields_can_be_cleared_without_disappearing(self):
        profile = self.get()
        body = {'request_id': str(uuid4()), 'revision': profile['revision'], 'fields': {'contactos_profesionales': None, 'aliases': None, 'ambitos': None}}
        response = self.c.patch('/people/' + self.person + '/profile', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        current = self.get(); self.assertEqual(current['fields']['contactos_profesionales'], {})
        self.assertEqual(current['fields']['aliases'], []); self.assertEqual(current['fields']['ambitos'], [])

    def test_legacy_link_routes_do_not_leak_or_mutate_reserved_notes(self):
        hidden = self.note('07 Conocimiento/secreto.md', 'TITULO SECRETO', '[[No existe]]', sensibilidad='secreto')
        before = (self.root/vault_index.get(hidden).path).read_bytes()
        self.assertNotIn('TITULO SECRETO', self.c.get('/vault/links/broken').text)
        self.assertEqual(self.c.get('/vault/links/suggest/' + hidden).status_code, 403)
        response = self.c.post('/vault/links/apply', json={'links':[{'source_id': hidden, 'target_id': self.person}]})
        self.assertFalse(response.json()['results'][0]['ok'])
        self.assertEqual((self.root/vault_index.get(hidden).path).read_bytes(), before)
    def test_semantic_prompt_excludes_reserved_candidates(self):
        from app.core.vault_linker import suggest_semantic_links
        hidden = self.note('07 Conocimiento/privada.md', 'TITULO PRIVADO', 'CONTENIDO RESERVADO', sensibilidad='privado')
        response = MagicMock(); response.raise_for_status.return_value = None
        response.json.return_value = {'text': json.dumps([{'note_id': hidden, 'reason': 'No debe salir'}])}
        client = AsyncMock(); client.post.return_value = response
        context = MagicMock(); context.__aenter__ = AsyncMock(return_value=client); context.__aexit__ = AsyncMock(return_value=None)
        with patch('httpx.AsyncClient', return_value=context):
            result = asyncio.run(suggest_semantic_links(vault_index.get(self.project), vault_index))
        prompt = client.post.call_args.kwargs['json']['message']
        self.assertNotIn('CONTENIDO RESERVADO', prompt); self.assertNotIn('TITULO PRIVADO', prompt)
        self.assertEqual(result, [])

    def test_auto_linker_does_not_touch_reviewed_or_disallowed_or_immutable_notes(self):
        for n in [vault_index.get(self.person), vault_index.get(self.source)]:
            before = (self.root/n.path).read_bytes()
            self.assertIsNone(generate_links_for_note(vault_index, self.root, n))
            self.assertEqual((self.root/n.path).read_bytes(), before)
    def test_relation_revision_conflict_preserves_graph(self):
        r, body = self.link(self.person, self.project, 'vinculado al proyecto'); self.assertEqual(r.status_code, 201)
        target = self.root/vault_index.get(self.project).path; target.write_text(target.read_text() + '\nCambio manual')
        result, _ = self.review(r.json()['id'], body['revision'], authorized=['relations'])
        self.assertEqual(result.status_code, 409); self.assertEqual(self.c.get('/vault/relations').json()['relations'], [])

if __name__ == '__main__': unittest.main()
