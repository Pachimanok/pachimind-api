import os
os.environ.setdefault('VAULT_PATH','/tmp/pachimind-human-tests-unused')
import hashlib,json,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.core import people,human_review as human,meeting_capture as meeting
from app.core.id_utils import path_to_id
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.models.people import LinkCommand,PersonProposal
from app.models.meetings import MeetingCreate,ProposalBatch,ProposalCreate
from app.routers.human import router


class HumanReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name)
        self.old=settings.vault_path,vault_index._notes,vault_index._vault_root
        settings.vault_path=str(self.root);vault_index.build(self.root)
        self.scope='personal';app=FastAPI();app.include_router(router)
        app.dependency_overrides[get_scope]=lambda:self.scope
        self.c=TestClient(app)
        self.project=self.note('05 Proyectos/demo','Proyecto Demo',tipo='proyecto')
        self.source=self.note('07 Conocimiento/source','Fuente Demo','Función: Coordinación. Organización Demo.',fuente_inmutable=True)
        self.person=self.note('04 Entidades/Personas/demo','Persona Demo',tipo='persona',nombre='Persona Demo')
    def tearDown(self):
        settings.vault_path,vault_index._notes,vault_index._vault_root=self.old;self.tmp.cleanup()
    def note(self,path,title,body='',**meta):
        p=self.root/(path+'.md');p.parent.mkdir(parents=True,exist_ok=True)
        values=dict(titulo=title,tipo='nota',estado='activo',sensibilidad='normal',ia_permiso='allow',ia_indexar=True,ia_editar=False,revisado=True)
        values.update(meta);p.write_text(meeting.serialize(values,body or '# '+title));vault_index.rebuild_file(p)
        return path_to_id(path+'.md')
    def pending_link(self,target=None):
        target=target or self.project
        cmd=LinkCommand(request_id=uuid4(),source_id=self.source,revision=people.revision(vault_index.get(self.source)),
            links=[dict(target_id=target,target_revision=people.revision(vault_index.get(target)),relation='relacionado con')])
        return people.propose_links(cmd,'personal',False)['id']
    def person_proposal(self,question=False):
        cmd=PersonProposal(request_id=uuid4(),revision=people.revision(vault_index.get(self.person)),fields={} if question else {'funcion':'Coordinación'},
            evidence=[dict(field='funcion',source_id=self.source,quote='Función: Coordinación.')],questions=['¿Qué función tiene?'] if question else [])
        return people.propose_person(self.person,cmd,'personal',True)['id']
    def detail(self,kind,item):
        r=self.c.get('/human/items/'+kind+'/'+item);self.assertEqual(r.status_code,200,r.text);return r.json()
    def decision(self,kind,item,action='approve',detail=None,request=None,**extra):
        d=detail or self.detail(kind,item)
        body=dict(request_id=request or str(uuid4()),revision=d['revision'],decision=action,
                  authorized_fields=d['authorized_fields'] if action=='approve' else [])
        body.update(extra)
        return self.c.post('/human/items/'+kind+'/'+item+'/decision',json=body),body
    def test_human_only_and_no_cache(self):
        for scope in ['ai_context','public']:
            self.scope=scope;self.assertEqual(self.c.get('/human/queue').status_code,403)
        self.scope='personal'
        self.assertEqual(self.c.get('/human/queue',headers={'X-PachiMind-Actor':'assistant'}).status_code,403)
        self.assertEqual(self.c.get('/human/queue').headers['cache-control'],'no-store')
        self.assertEqual(self.c.get('/human/summary').json()['total_pending'],0)
    def test_queue_includes_both_proposals_and_protected_drafts_without_effects(self):
        link=self.pending_link();person=self.person_proposal()
        draft=self.note('07 Conocimiento/draft','Borrador protegido','Texto de borrador',estado='borrador',revisado=False,ia_indexar=False)
        original={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.md')}
        q=self.c.get('/human/queue').json();self.assertEqual(q['counts'],{'links':1,'person':1,'meeting':0,'note':1})
        self.assertNotIn('Texto de borrador',json.dumps(q))
        self.assertTrue(self.detail('links',link)['validation']['ok'])
        self.assertTrue(self.detail('person',person)['validation']['ok'])
        self.assertIn('Texto de borrador',self.detail('note',draft)['content'])
        self.assertEqual(original,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.md')})
    def test_manual_link_approval_preserves_immutable_body_and_requires_exact_fields(self):
        item=self.pending_link();d=self.detail('links',item);p=meeting.path_for(vault_index.get(self.source).path);before=p.read_bytes()
        r,_=self.decision('links',item,detail=d,authorized_fields=[]);self.assertEqual(r.status_code,422)
        r,body=self.decision('links',item,detail=d);self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['verified'])
        self.assertEqual(p.read_bytes(),before);self.assertEqual(people.load('changes',item)['state'],'applied')
        again=self.c.post('/human/items/links/'+item+'/decision',json=body);self.assertEqual(again.json(),r.json())
        self.assertEqual(len(people.records('relations')),1)
        receipt=self.c.get('/human/requests/'+body['request_id']);self.assertEqual(receipt.json(),r.json())
    def test_stale_link_is_blocked_but_decline_is_available(self):
        item=self.pending_link();d=self.detail('links',item)
        p=meeting.path_for(vault_index.get(self.project).path);p.write_text(p.read_text()+'\nCambio humano');vault_index.rebuild_file(p)
        current=self.detail('links',item);self.assertFalse(current['validation']['ok'])
        r,_=self.decision('links',item,detail=d);self.assertEqual(r.status_code,409)
        r,_=self.decision('links',item,'decline',detail=current);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(people.load('changes',item)['state'],'rejected');self.assertEqual(people.records('relations'),[])
    def test_changed_proposal_payload_needs_new_preview(self):
        item=self.pending_link();d=self.detail('links',item)
        p=people.load('changes',item);p['questions']=['Nueva pregunta'];people.save('changes',item,p)
        r,_=self.decision('links',item,detail=d);self.assertEqual(r.status_code,409)
        self.assertEqual(people.records('relations'),[])
    def test_questions_cannot_be_approved_as_fields_and_answer_stays_private(self):
        item=self.person_proposal(True);d=self.detail('person',item);self.assertFalse(d['validation']['ok'])
        p=meeting.path_for(vault_index.get(self.person).path);before=p.read_bytes()
        r,_=self.decision('person',item,detail=d);self.assertIn(r.status_code,[409,422])
        r,_=self.decision('person',item,'answer',detail=d,answer='Coordinación confirmada por el propietario.')
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['state'],'answered')
        self.assertEqual(p.read_bytes(),before)
        self.assertNotIn('Coordinación confirmada',json.dumps(people.load('changes',item)))
        self.assertEqual(self.c.get('/human/queue?kind=person').json()['total'],0)
    def test_person_change_can_be_approved_after_preview(self):
        item=self.person_proposal();before=people.raw(vault_index.get(self.person))[1].content
        r,_=self.decision('person',item);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(people.fields(vault_index.get(self.person))['funcion'],'Coordinación')
        self.assertEqual(people.raw(vault_index.get(self.person))[1].content,before)
    def test_note_review_uses_sidecar_preserves_bytes_and_access_flags(self):
        item=self.note('07 Conocimiento/draft','Borrador','Original\r\n',estado='borrador',revisado=False,ia_indexar=False,fuente_inmutable=True)
        p=meeting.path_for(vault_index.get(item).path);before=p.read_bytes()
        d=self.detail('note',item);r,_=self.decision('note',item,detail=d)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(p.read_bytes(),before)
        n=vault_index.get(item);self.assertEqual(n.metadata.estado,'activo');self.assertTrue(n.metadata.revisado)
        self.assertFalse(n.metadata.ia_indexar);self.assertFalse(n.metadata.ia_editar);self.assertTrue(n.metadata.fuente_inmutable)
        self.assertEqual(self.c.get('/human/queue?kind=note').json()['total'],0)
        p.write_bytes(before+b'\nCambio');vault_index.rebuild_file(p)
        self.assertFalse(vault_index.get(item).metadata.revisado)
        self.assertEqual(self.c.get('/human/queue?kind=note').json()['total'],1)
    def test_decline_archives_effective_note_without_deleting_original(self):
        item=self.note('07 Conocimiento/review','Revisar','Original',revisado=False)
        p=meeting.path_for(vault_index.get(item).path);before=p.read_bytes()
        r,_=self.decision('note',item,'decline');self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(p.read_bytes(),before);self.assertEqual(vault_index.get(item).metadata.estado,'archivado')
    def test_summary_only_cannot_be_approved_without_full_content(self):
        item=self.note('07 Conocimiento/summary','Resumen','Contenido incompleto',revisado=False,ia_permiso='summary_only')
        d=self.detail('note',item);self.assertIsNone(d['content']);self.assertFalse(d['validation']['ok'])
        r,_=self.decision('note',item,detail=d);self.assertEqual(r.status_code,409)
    def test_readonly_and_secret_sources_do_not_leak(self):
        secret=self.note('Secreto','NO MOSTRAR SECRETO',revisado=False)
        item=self.pending_link(secret)
        path=meeting.path_for(vault_index.get(secret).path)
        path.write_text(path.read_text().replace('sensibilidad: normal','sensibilidad: secreto'))
        vault_index.rebuild_file(path)
        q=self.c.get('/human/queue').text;self.assertNotIn('NO MOSTRAR',q);self.assertNotIn(item,q)
        self.assertEqual(self.c.get('/human/items/links/'+item).status_code,404)
        self.assertEqual(self.c.get('/human/items/note/'+secret).status_code,404)
        self.scope='ai_context';self.assertEqual(self.c.post('/human/items/note/'+self.source+'/decision',json={}).status_code,403)
    def test_meeting_actions_approve_and_decline_without_touching_capture(self):
        meeting_result=meeting.create_meeting(self.project,MeetingCreate(request_id=uuid4(),title='Reunión demo',fecha='2026-11-10',source='Fixture sintética',content='Preparar informe.'))
        mid=meeting_result['id'];source=meeting.path_for(meeting_result['path']);before=source.read_bytes()
        batch=ProposalBatch(items=[ProposalCreate(request_id=uuid4(),tipo='accion',title='Informe demo',detalle='Preparar el informe',evidencia='Preparar informe.')])
        item=meeting.create_proposals(self.project,mid,batch)[0]['id']
        self.assertEqual(self.c.get('/human/queue?kind=meeting').json()['total'],1)
        r,body=self.decision('meeting',item);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['state'],'approved');self.assertEqual(source.read_bytes(),before)
        self.assertEqual(len(list(self.root.glob('09 Acciones/Capturas/*.md'))),1)
        again=self.c.post('/human/items/meeting/'+item+'/decision',json=body);self.assertEqual(again.json(),r.json())
        self.assertEqual(len(list(self.root.glob('09 Acciones/Capturas/*.md'))),1)
    def test_meeting_stale_proposal_does_not_approve(self):
        m=meeting.create_meeting(self.project,MeetingCreate(request_id=uuid4(),title='Demo',fecha='2026-11-10',source='Fixture',content='Confirmar decisión.'))
        p=meeting.create_proposals(self.project,m['id'],ProposalBatch(items=[ProposalCreate(request_id=uuid4(),tipo='decision',title='Decisión',detalle='Revisar',evidencia='Confirmar decisión.')]))[0]
        d=self.detail('meeting',p['id']);f=meeting.path_for(p['path']);f.write_text(f.read_text()+'\nCambio');vault_index.rebuild_file(f)
        r,_=self.decision('meeting',p['id'],detail=d);self.assertEqual(r.status_code,409)
        self.assertEqual(len(list(self.root.glob('07 Conocimiento/Decisiones/*.md'))),0)
        current=self.detail('meeting',p['id']);r,_=self.decision('meeting',p['id'],'decline',detail=current)
        self.assertEqual(r.status_code,200,r.text)
    def test_pagination_and_filter_counts_and_no_automatic_decisions(self):
        for i in range(18):self.note('07 Conocimiento/n'+str(i),'Pendiente '+str(i),revisado=False)
        one=self.c.get('/human/queue?per_page=10').json();two=self.c.get('/human/queue?per_page=10&page=2').json()
        self.assertEqual(len(one['results'])+len(two['results']),18)
        self.assertEqual(one['total_pending'],18)
        self.assertEqual(self.c.get('/human/queue?q=Pendiente+17').json()['total'],1)
        self.assertEqual(people.records('human_history'),[])

    def test_note_without_explicit_state_keeps_default_after_review(self):
        note=self.note('07 Conocimiento/legacy','Legacy sin estado',revisado=False)
        path=meeting.path_for(vault_index.get(note).path)
        path.write_text(path.read_text().replace('estado: activo\n',''))
        vault_index.rebuild_file(path)
        before=path.read_bytes()
        response,_=self.decision('note',note)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(vault_index.get(note).metadata.estado,'activo')
        self.assertTrue(vault_index.get(note).metadata.revisado)
