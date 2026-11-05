import os
os.environ.setdefault('VAULT_PATH','/tmp/pachimind-review-tests-unused')
import json,hashlib,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.core.vault_index import vault_index
from app.core.vault_parser import parse_note
from app.core import meeting_capture as capture
from app.core.meeting_capture import serialize
from app.core.meeting_review import record_path
from app.core.people import revision
from app.core.id_utils import path_to_id
from app.models.meetings import MeetingCreate,ProposalBatch,ProposalCreate
from app.middleware.auth import get_scope
from app.routers import notes,vault

class MeetingReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name)
        self.old=settings.vault_path,vault_index._notes,vault_index._vault_root
        settings.vault_path=str(self.root);vault_index.build(self.root)
        p=self.root/'05 Proyectos/Laboral/demo.md';p.parent.mkdir(parents=True)
        p.write_text(serialize({'titulo':'Proyecto demo','tipo':'proyecto','estado':'activo','sensibilidad':'normal','ia_permiso':'allow','ia_indexar':True},'Proyecto'))
        vault_index.rebuild_file(p);self.project=path_to_id(str(p.relative_to(self.root)))
        result=capture.create_meeting(self.project,MeetingCreate(request_id=uuid4(),title='Reunión demo',fecha='2026-11-05',content='A: Propuesta sin aprobar.',source='Fuente sintética'))
        self.id=result['id'];self.path=self.root/result['path'];self.before=self.path.read_bytes()
        self.record={'source_id':self.id,'source_sha256':hashlib.sha256(self.before).hexdigest(),'review_kind':'documental','reviewed':True,'approved_by':'Pablo','approved_date':'2026-11-05','meeting_date':'2026-11-05','participants':['Persona Uno','Persona Dos'],'speaker_assignment':'unassigned','financial_facts_validated':False}
    def tearDown(self):
        settings.vault_path,vault_index._notes,vault_index._vault_root=self.old;self.tmp.cleanup()
    def save(self):
        p=record_path(self.root,self.id);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(self.record))
        vault_index.rebuild_file(self.path)
    def test_review_changes_effective_metadata_and_revision_not_original(self):
        oldrev=revision(vault_index.get(self.id));self.save();note=vault_index.get(self.id)
        self.assertTrue(note.metadata.revisado);self.assertEqual(note.metadata.personas,['Persona Uno','Persona Dos'])
        self.assertNotEqual(revision(note),oldrev);self.assertEqual(self.path.read_bytes(),self.before)
        result=capture.get_meeting(self.project,self.id,True)
        self.assertTrue(result['revisado']);self.assertEqual(result['participantes_originales'],[])
        self.assertEqual(result['content'],'A: Propuesta sin aprobar.')
    def test_changed_source_invalidates_review(self):
        self.save();self.path.write_bytes(self.before+b'\nCambio')
        note=parse_note(self.path,self.root)
        self.assertFalse(note.metadata.revisado);self.assertIsNone(note.metadata.revision_documental)
    def test_invalid_record_never_changes_permissions_or_hides_source(self):
        for changes in [{'source_sha256':'0'*64},{'source_id':'other'},{'reviewed':False},{'ia_indexar':True},{'financial_facts_validated':True}]:
            old=dict(self.record);self.record.update(changes);self.save()
            note=vault_index.get(self.id);self.assertFalse(note.metadata.revisado);self.assertIsNone(note.metadata.revision_documental)
            self.record=old
        p=record_path(self.root,self.id);p.write_text('{invalid');vault_index.rebuild_file(self.path)
        self.assertIsNotNone(vault_index.get(self.id));self.assertFalse(vault_index.get(self.id).metadata.revisado)
    def test_review_does_not_approve_proposals_or_unlock_source(self):
        result=capture.create_proposals(self.project,self.id,ProposalBatch(items=[ProposalCreate(request_id=uuid4(),tipo='accion',title='Propuesta',detalle='Pendiente',evidencia='Propuesta sin aprobar.')]))
        self.save();self.assertIsNone(capture.list_proposals(self.project,self.id)[0]['review'])
        app=FastAPI();app.include_router(notes.router);app.dependency_overrides[get_scope]=lambda:'personal';c=TestClient(app)
        self.assertEqual(c.patch('/notes/'+self.id,json={'content':'Cambio'}).status_code,409)
        self.assertEqual(c.delete('/notes/'+self.id).status_code,409)
        self.assertEqual(self.path.read_bytes(),self.before)
    def test_activity_does_not_list_documentary_review_as_pending(self):
        app=FastAPI();app.include_router(vault.router);app.dependency_overrides[get_scope]=lambda:'personal';c=TestClient(app)
        self.assertIn(self.id,[n['id'] for n in c.get('/vault/activity').json()['pending_review']])
        self.save()
        r=c.get('/vault/activity');self.assertEqual(r.status_code,200,r.text)
        self.assertNotIn(self.id,[n['id'] for n in r.json()['pending_review']])
    def test_correction_date_is_separate_from_original(self):
        self.record['meeting_date']='2026-11-04';self.save()
        result=capture.get_meeting(self.project,self.id,True)
        self.assertEqual(result['fecha'],'2026-11-04')
        self.assertEqual(result['fecha_original'],'2026-11-05')
        self.assertEqual(vault_index.get(self.id).metadata.fecha,'2026-11-04')
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_valid_review_does_not_widen_ai_permissions(self):
        for changes in [{'ia_permiso':'deny'}, {'ia_indexar':False}, {'sensibilidad':'privado'}]:
            import frontmatter
            post=frontmatter.loads(self.before.decode())
            post.metadata.update(changes)
            self.path.write_text(serialize(post.metadata,post.content))
            original=self.path.read_bytes()
            self.record['source_sha256']=hashlib.sha256(original).hexdigest()
            self.save()
            app=FastAPI();app.include_router(notes.router)
            app.dependency_overrides[get_scope]=lambda:'personal';client=TestClient(app)
            response=client.get('/notes/'+self.id,headers={'X-PachiMind-Actor':'assistant'})
            self.assertEqual(response.status_code,403)
            self.assertTrue(vault_index.get(self.id).metadata.revisado)
            self.assertEqual(self.path.read_bytes(),original)
