"""Graph contains permitted metadata and saved relationships, never note bodies."""
import json,unittest,hashlib
import test_associations as associations
from app.routers.vault import router
from app.core.vault_index import vault_index

class VaultGraphTests(unittest.TestCase):
    setUp_base=associations.AssociationTests.setUp
    tearDown=associations.AssociationTests.tearDown
    note=associations.AssociationTests.note
    def setUp(self):self.setUp_base();self.client.app.include_router(router)
    def test_graph_has_real_edges_ambitos_and_isolated_notes_without_bodies_or_mutations(self):
        p=self.note('Proyecto',tipo='proyecto',area='Laboral')
        s=self.note('Fuente','Contenido privado del cuerpo. [[Proyecto]] [[No existe]]',fuente_inmutable=True,ia_editar=False)
        lonely=self.note('Sin enlaces',ambitos=['Familia'])
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.md')}
        r=self.client.get('/vault/graph');self.assertEqual(r.status_code,200);self.assertEqual(r.headers['cache-control'],'no-store')
        d=r.json();self.assertEqual(d['returned'],3);self.assertFalse(d['truncated'])
        self.assertEqual(d['edges'],[{'source':s,'target':p,'relation':'referencia'}])
        self.assertEqual(next(n for n in d['nodes'] if n['id']==p)['ambitos'],['Trabajo'])
        self.assertIn(lonely,[n['id'] for n in d['nodes']]);self.assertNotIn('Contenido privado',r.text)
        self.assertNotIn('evidence',r.text);self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.md')})
        self.assertEqual(self.client.post('/vault/graph',json={}).status_code,405)
    def test_permissions_hidden_endpoints_counts_and_assistant_actor(self):
        public=self.note('Visible',area='Personal');private=self.note('Privada','[[Visible]]',sensibilidad='privado')
        denied=self.note('No IA','[[Visible]]',ia_permiso='deny')
        self.note('00 Sistema/Secret',sensibilidad='secreto')
        self.scope='ai_context';d=self.client.get('/vault/graph').json()
        self.assertEqual(d['total_visible'],1);self.assertEqual(d['edges'],[]);self.assertNotIn('Privada',json.dumps(d));self.assertNotIn('No IA',json.dumps(d))
        self.assertEqual(self.client.get('/vault/graph',params={'focus':private}).status_code,404)
        self.scope='personal'
        d=self.client.get('/vault/graph',headers={'X-PachiMind-Actor':'assistant'}).json();self.assertEqual(d['total_visible'],1)
        self.assertEqual(self.client.get('/vault/graph',params={'focus':denied},headers={'X-PachiMind-Actor':'assistant'}).status_code,404)
        self.assertIn(public,[n['id'] for n in d['nodes']])
    def test_bound_local_graph_and_truncation_do_not_create_dangling_edges(self):
        p=self.note('Proyecto',tipo='proyecto');a=self.note('A','[[Proyecto]]');self.note('Aislada')
        d=self.client.get('/vault/graph',params={'focus':a}).json()
        self.assertEqual({n['id'] for n in d['nodes']},{a,p});self.assertEqual(d['total_matching'],2)
        d=self.client.get('/vault/graph?limit=1').json();self.assertTrue(d['truncated']);self.assertEqual(len(d['nodes']),1)
        self.assertEqual(d['edges'],[]);self.assertEqual(d['total_visible'],3)
        self.assertEqual(self.client.get('/vault/graph?limit=3001').status_code,422)
        self.assertEqual(self.client.get('/vault/graph?limit=0').status_code,422)
