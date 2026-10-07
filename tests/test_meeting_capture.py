import os
os.environ.setdefault('VAULT_PATH','/tmp/pachimind-tests-unused')
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.core.vault_index import vault_index
from app.core.vault_linker import generate_links,generate_links_for_note
from app.core import meeting_capture
from app.routers import meetings,projects,notes,links
from app.middleware.auth import get_scope
from app.models.meetings import MeetingCreate


class MeetingFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name)
        self.old_root=settings.vault_path;self.old_notes=vault_index._notes;self.old_vault=vault_index._vault_root
        settings.vault_path=str(self.root)
        self.project_path=self.root/'05 Proyectos/demo.md';self.project_path.parent.mkdir()
        self.project_path.write_text('---\ntipo: proyecto\nestado: activo\narea: Laboral\nsensibilidad: interno\n---\n# Proyecto Demo\n')
        vault_index.build(self.root)
        self.project='05-proyectos-demo'
        app=FastAPI()
        for router in [meetings.router,projects.router,notes.router,links.router]:app.include_router(router)
        self.app=app;app.dependency_overrides[get_scope]=lambda:'personal'
        self.client=TestClient(app)
        self.base=f'/projects/{self.project}/meetings'
        self.content='  Ana: Decidimos usar el piloto.\r\nLuis: Enviaré el informe.\n\n'
        self.payload={'request_id':str(uuid4()),'title':'Reunión: "piloto"','fecha':'2026-10-02',
                      'participantes':['Ana','Luis'],'source':'Notas propias','content':self.content,'allow_ai':True}

    def tearDown(self):
        settings.vault_path=self.old_root;vault_index._notes=self.old_notes;vault_index._vault_root=self.old_vault
        self.tmp.cleanup()

    def capture(self):
        r=self.client.post(self.base,json=self.payload);self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def proposal(self):
        return {'request_id':str(uuid4()),'tipo':'accion','title':'Enviar informe','detalle':'Enviar el informe',
                'evidencia':'Luis: Enviaré el informe.','responsable':'Luis','vencimiento':None}

    def test_complete_flow_and_immutable_source(self):
        created=self.capture();url=self.base+'/'+created['id'];file=self.root/created['path'];original=file.read_bytes()
        self.assertTrue(original.endswith(self.content.encode()))
        self.assertEqual(self.client.get(url).json()['content'],self.content)
        self.assertEqual(self.client.get(url).json()['title'],self.payload['title'])
        batch=self.client.post(url+'/proposals',json={'items':[self.proposal()]})
        self.assertEqual(batch.status_code,201,batch.text);proposal=batch.json()[0]
        self.assertEqual(proposal['estado'],'para_revisar')
        before=self.client.get(f'/projects/{self.project}/memory').json()
        self.assertNotIn(proposal['id'],[n['id'] for n in before['sources']])
        approval_url=url+'/proposals/'+proposal['id']+'/review'
        approved=self.client.post(approval_url,json={'action':'approve'})
        self.assertEqual(approved.status_code,200,approved.text)
        self.assertEqual(self.client.post(approval_url,json={'action':'approve'}).json(),approved.json())
        self.assertEqual(self.client.post(approval_url,json={'action':'discard'}).status_code,409)
        self.assertEqual(len(list(self.root.glob('09 Acciones/Capturas/*.md'))),1)
        exported=self.client.get(f'/projects/{self.project}/memory.md').text
        self.assertIn('Enviar informe',exported);self.assertIn(created['path'].removesuffix('.md'),exported)
        source=vault_index.get(created['id'])
        self.assertIsNone(generate_links_for_note(vault_index,self.root,source,dry_run=False))
        generate_links(vault_index,self.root,dry_run=False)
        self.assertEqual(self.client.patch('/notes/'+created['id'],json={'content':'changed'}).status_code,409)
        self.assertEqual(self.client.delete('/notes/'+created['id']).status_code,409)
        self.assertEqual(self.client.post('/notes/'+created['id']+'/promote',json={}).status_code,409)
        self.assertEqual(self.client.post('/notes',json={'title':'duplicate','source_draft_id':created['id']}).status_code,409)
        response=self.client.post('/vault/links/apply',json={'links':[{'source_id':created['id'],'target_id':self.project}]})
        self.assertEqual(response.json()['applied'],0)
        self.assertEqual(file.read_bytes(),original)

    def test_idempotency_conflict_and_concurrent_capture(self):
        body=MeetingCreate(**self.payload)
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda _:meeting_capture.create_meeting(self.project,body),range(3)))
        self.assertEqual(len({r['id'] for r in results}),1)
        self.assertEqual(sum(r['created'] for r in results),1)
        self.payload['content']='Different'
        self.assertEqual(self.client.post(self.base,json=self.payload).status_code,409)

    def test_validation_before_any_proposals_are_written(self):
        created=self.capture();url=self.base+'/'+created['id']+'/proposals'
        valid=self.proposal();bad=self.proposal();bad['evidencia']='Inventado'
        self.assertEqual(self.client.post(url,json={'items':[valid,bad]}).status_code,422)
        self.assertFalse((self.root/'01 Inbox').exists())
        bad['evidencia']='Luis: Enviaré el informe.';bad['vencimiento']='2026-99-99'
        self.assertEqual(self.client.post(url,json={'items':[bad]}).status_code,422)
        self.assertEqual(self.client.post(url,json={'items':[valid,valid]}).status_code,422)

    def test_permissions_and_ai_blocking(self):
        self.payload['allow_ai']=False
        created=self.capture();url=self.base+'/'+created['id']
        self.assertEqual(self.client.get(url+'?for_ai=true').status_code,403)
        self.assertNotIn('Reunión:',self.client.get(f'/projects/{self.project}/memory.md').text)
        for scope in ['public','ai_context']:
            self.app.dependency_overrides[get_scope]=lambda s=scope:s
            self.assertEqual(self.client.get(url).status_code,403)
            self.assertEqual(self.client.post(self.base,json=self.payload).status_code,403)
            self.assertEqual(self.client.post(url+'/proposals',json={'items':[self.proposal()]}).status_code,403)

    def test_wrong_project_and_tampered_source(self):
        created=self.capture();url=self.base+'/'+created['id']
        self.assertEqual(self.client.get('/projects/other/meetings/'+created['id']).status_code,404)
        path=self.root/created['path'];path.write_bytes(path.read_bytes()+b'tampered')
        self.assertEqual(self.client.get(url).status_code,409)
        self.assertEqual(self.client.post(url+'/proposals',json={'items':[self.proposal()]}).status_code,409)

    def test_discard_and_reopen(self):
        created=self.capture();url=self.base+'/'+created['id'];proposal=self.proposal()
        initial=self.client.post(url+'/proposals',json={'items':[proposal]}).json()[0]
        duplicate=self.client.post(url+'/proposals',json={'items':[proposal]}).json()[0]
        self.assertEqual(initial['id'],duplicate['id'])
        reviewed=self.client.post(url+'/proposals/'+initial['id']+'/review',json={'action':'discard'})
        self.assertEqual(reviewed.status_code,200)
        vault_index.build(self.root)
        self.assertEqual(self.client.get(url+'/proposals').json()[0]['review'],'discard')
        self.assertFalse((self.root/'09 Acciones').exists())

    def test_approval_recovers_after_archive_write_failure(self):
        created=self.capture();url=self.base+'/'+created['id'];proposal=self.proposal()
        p=self.client.post(url+'/proposals',json={'items':[proposal]}).json()[0]
        real=meeting_capture.atomic_write
        def failing(relative,text,replace=False):
            if replace:raise OSError('disk failure')
            return real(relative,text,replace)
        with patch.object(meeting_capture,'atomic_write',side_effect=failing):
            with self.assertRaises(OSError):meeting_capture.review_proposal(self.project,created['id'],p['id'],'approve')
        result=meeting_capture.review_proposal(self.project,created['id'],p['id'],'approve')
        self.assertEqual(result['review'],'approve')
        self.assertEqual(len(list(self.root.glob('09 Acciones/Capturas/*.md'))),1)

if __name__=='__main__':unittest.main()
