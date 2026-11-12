"""Real API routes: proposals do not edit originals or imply owner approval."""
import unittest
from uuid import uuid4
from unittest.mock import patch
import test_inbox_access as access_tests
from app.routers.inbox import router
from app.core import people
from app.core.vault_index import vault_index

class ClassificationTests(unittest.TestCase):
    setUp_base = access_tests.InboxAccessTests.setUp
    tearDown = access_tests.InboxAccessTests.tearDown
    note = access_tests.InboxAccessTests.note
    def setUp(self):
        self.setUp_base();self.c.app.include_router(router)
        self.id=self.note('01 Inbox/Desde IA/classification',ia_indexar=True,fuente_inmutable=True)
        self.headers={'X-PachiMind-Actor':'assistant'}
    def source(self):return self.c.get('/notes/'+self.id).json()
    def command(self):
        return {'request_id':str(uuid4()),'revision':self.source()['revision'],
                'classification':{'title':'Clasificación demo','tipo':'recurso','area':'Laboral','tags':['prueba'],
                                  'content':'Síntesis separada.','comment':'Propuesta, sin aprobar acciones.'}}
    def propose(self,body=None):
        return self.c.post('/inbox/'+self.id+'/classification',headers=self.headers,json=body or self.command())
    def decision(self,state,decision='approve',**extra):
        return {'request_id':str(uuid4()),'revision':state['revision'],'decision':decision,'confirmed':True,**extra}
    def decide(self,body,headers=None):
        return self.c.post('/human/inbox-classification/'+self.id+'/decision',json=body,headers=headers or {})
    def test_protected_original_proposal_owner_confirmation_and_idempotency(self):
        source=self.source();path=self.root/source['path'];raw=path.read_bytes();body=self.command()
        self.assertFalse(source['metadata']['ia_editar']);self.assertTrue(source['mcp_access']['available'])
        state=self.propose(body).json();self.assertEqual(state['proposal']['state'],'pending')
        self.assertEqual(self.propose(body).json(),state);self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(self.source()['metadata']['estado'],'borrador')
        self.assertEqual(self.source()['inbox_classification']['state'],'pending')
        self.assertEqual(len(list(self.root.rglob('*.md'))),2)
        command=self.decision(state)
        self.assertEqual(self.decide({**command,'confirmed':False}).status_code,422)
        self.assertEqual(self.decide(command,self.headers).status_code,403)
        r=self.decide(command);self.assertEqual(r.status_code,200,r.text)
        result=r.json();self.assertEqual(result['state'],'approved')
        self.assertEqual(self.decide(command).json(),result)
        self.assertEqual(path.read_bytes(),raw);self.assertFalse(self.source()['metadata']['ia_editar'])
        self.assertEqual(self.source()['metadata']['estado'],'archivado')
        derived=self.c.get('/notes/'+result['derived_id']).json()
        self.assertEqual(derived['content'],'Síntesis separada.')
        self.assertEqual(derived['metadata']['fuentes_ids'],[self.id]);self.assertFalse(derived['metadata']['ia_editar'])
        self.assertNotIn(self.id,[n['id'] for n in self.c.get('/notes?estado=borrador').json()['results']])
        self.assertEqual(len(list(self.root.rglob('*.md'))),3)
    def test_readonly_denied_health_reserved_and_operational_types_cannot_propose(self):
        body=self.command();self.scope='ai_context';self.assertEqual(self.propose(body).status_code,403);self.scope='personal'
        for extra in [{'ia_permiso':'deny'},{'ia_indexar':False},{'sensibilidad':'privado'},
                      {'segmentos_reservados':[{'texto':'Protegido'}]},{'datos_generales':[{'categoria':'salud','texto':'Privado'}]}]:
            self.id=self.note('01 Inbox/Desde IA/blocked-'+str(uuid4()),**extra)
            command={**body,'request_id':str(uuid4())}
            self.assertIn(self.propose(command).status_code,[403,404])
        self.id=self.note('01 Inbox/Desde IA/allowed',ia_indexar=True)
        for tipo in ['accion','decision','persona']:
            command=self.command();command['classification']['tipo']=tipo
            self.assertEqual(self.propose(command).status_code,422)
        self.assertEqual(people.records('inbox_classifications'),[])
    def test_stale_source_reproposal_decline_and_no_permissions_changed(self):
        state=self.propose().json();command=self.decision(state)
        path=self.root/self.source()['path'];path.write_bytes(path.read_bytes()+b'\nCambio');vault_index.rebuild_file(path)
        self.assertEqual(self.decide(command).status_code,409)
        state=self.propose().json();raw=path.read_bytes()
        self.assertEqual(len(people.records('inbox_classification_history')),1)
        result=self.decide(self.decision(state,'decline'));self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['state'],'declined');self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(self.source()['metadata']['estado'],'borrador')
        self.assertEqual(len(list(self.root.rglob('*.md'))),2)
    def test_access_change_blocks_proposal_read_and_derived_source_restrictions(self):
        state=self.propose().json();r=self.decide(self.decision(state));self.assertEqual(r.status_code,200,r.text)
        derived=r.json()['derived_id'];path=self.root/self.source()['path']
        path.write_text(path.read_text().replace('ia_permiso: allow','ia_permiso: deny'));vault_index.rebuild_file(path)
        self.scope='ai_context'
        self.assertEqual(self.c.get('/notes/'+derived).status_code,403)
        self.assertEqual(self.c.get('/inbox/'+self.id+'/classification').status_code,404)
    def test_response_loss_recovers_exact_proposal_and_decision_without_duplicate(self):
        original=people.save;body=self.command()
        def lose_proposal(kind,key,value):
            if kind=='inbox_classification_requests':raise OSError('Synthetic interruption')
            original(kind,key,value)
        with patch.object(people,'save',side_effect=lose_proposal):
            with self.assertRaises(OSError):self.propose(body)
        state=self.propose(body).json();command=self.decision(state)
        def lose_decision(kind,key,value):
            if kind=='inbox_classification_decisions':raise OSError('Synthetic interruption')
            original(kind,key,value)
        with patch.object(people,'save',side_effect=lose_decision):
            with self.assertRaises(OSError):self.decide(command)
        response=self.decide(command);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(list(self.root.rglob('*.md'))),3)
        self.assertEqual(self.decide({**command,'decision':'decline'}).status_code,409)
    def test_duplicate_proposal_or_request_id_with_other_payload_is_rejected(self):
        body=self.command();self.assertEqual(self.propose(body).status_code,200)
        changed={**body,'classification':{**body['classification'],'title':'Otra cosa'}}
        self.assertEqual(self.propose(changed).status_code,409)
        self.assertEqual(self.propose().status_code,409)
