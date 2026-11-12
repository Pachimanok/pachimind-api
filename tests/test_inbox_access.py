import os
os.environ.setdefault('VAULT_PATH','/tmp/pachimind-inbox-access-test-unused')
import unittest,hashlib,json
from tempfile import TemporaryDirectory
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.core import people,inbox_access,meeting_capture as capture
from app.core.inbox_access_review import access_path
from app.core.vault_index import vault_index
from app.core.id_utils import path_to_id
from app.middleware.auth import get_scope
from app.middleware.permissions import is_ai_eligible
from app.routers.human import router
from app.routers.notes import router as notes_router

class InboxAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name)
        self.old=settings.vault_path,vault_index._notes,vault_index._vault_root
        settings.vault_path=str(self.root);vault_index.build(self.root)
        self.scope='personal';app=FastAPI();app.include_router(router);app.include_router(notes_router);app.dependency_overrides[get_scope]=lambda:self.scope
        self.c=TestClient(app);self.id=self.note('01 Inbox/Desde IA/demo')
    def tearDown(self):
        settings.vault_path,vault_index._notes,vault_index._vault_root=self.old;self.tmp.cleanup()
    def note(self,path,**extra):
        meta={'titulo':'Borrador demo','tipo':'nota','estado':'borrador','revisado':False,'sensibilidad':'normal','ia_permiso':'allow','ia_indexar':False,'ia_editar':False}
        meta.update(extra);p=self.root/(path+'.md');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(capture.serialize(meta,'Original áéíóú.\nNo aprobar tareas.\r\nTexto completo.'))
        vault_index.rebuild_file(p);return path_to_id(path+'.md')
    def preview(self,note_id=None):
        r=self.c.get('/human/inbox-access/'+(note_id or self.id));self.assertEqual(r.status_code,200,r.text);return r.json()
    def command(self,state,action='enable'):
        return {'request_id':str(uuid4()),'revision':state['revision'],'action':action,'confirmed':True,'authorized_fields':list(state['actions'][action]['changes'])}
    def post(self,body,note_id=None):return self.c.post('/human/inbox-access/'+(note_id or self.id),json=body)
    def test_preview_no_writes_explicit_consent_and_original_preserved_with_revoke(self):
        path=self.root/vault_index.get(self.id).path;raw=path.read_bytes();before=self.preview()
        self.assertFalse(before['available_to_ai']);self.assertEqual(before['actions']['enable']['changes'],{'ia_indexar':{'before':False,'after':True}})
        self.assertEqual(people.records('inbox_access'),[])
        body=self.command(before)
        for bad in [{**body,'confirmed':False},{**body,'authorized_fields':[]},{**body,'authorized_fields':['ia_indexar','ia_editar']}]:
            self.assertEqual(self.post(bad).status_code,422)
        self.assertEqual(people.records('inbox_access'),[])
        r=self.post(body);self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['verified']);self.assertTrue(r.json()['access']['available_to_ai'])
        self.assertEqual(self.post(body).json(),r.json());self.assertEqual(len(people.records('inbox_access_history')),1)
        n=vault_index.get(self.id);self.assertEqual(n.metadata.estado,'borrador');self.assertFalse(n.metadata.revisado);self.assertFalse(n.metadata.ia_editar);self.assertEqual(path.read_bytes(),raw)
        self.assertNotEqual(self.preview()['revision'],before['revision'])
        self.scope='ai_context';visible=self.c.get('/notes?estado=borrador').json();self.assertEqual(visible['total'],1)
        self.assertEqual(self.c.get('/notes/'+self.id).status_code,200)
        self.scope='personal';revoke=self.command(self.preview(),'revoke');r=self.post(revoke);self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json()['access']['available_to_ai'])
        self.assertEqual(self.post(revoke).status_code,200);self.assertEqual(self.post(body).status_code,409)
        self.assertEqual(path.read_bytes(),raw);self.assertFalse(is_ai_eligible(vault_index.get(self.id)))
        self.scope='ai_context';self.assertEqual(self.c.get('/notes?estado=borrador').json()['total'],0);self.assertEqual(self.c.get('/notes/'+self.id).status_code,403)
    def test_owner_only_and_no_cache(self):
        state=self.preview();body=self.command(state)
        self.assertEqual(self.c.get('/human/inbox-access/'+self.id).headers['cache-control'],'no-store')
        for scope in ['ai_context','public']:
            self.scope=scope;self.assertEqual(self.c.get('/human/inbox-access/'+self.id).status_code,403);self.assertEqual(self.post(body).status_code,403)
        self.scope='personal'
        self.assertEqual(self.c.get('/human/inbox-access/'+self.id,headers={'X-PachiMind-Actor':'assistant'}).status_code,403)
        self.assertEqual(self.c.post('/human/inbox-access/'+self.id,json=body,headers={'X-PachiMind-Actor':'assistant'}).status_code,403)
        self.assertEqual(people.records('inbox_access'),[])
    def test_denied_and_summary_only_require_exact_permission_confirmation(self):
        for value in ['deny','summary_only']:
            note_id=self.note('01 Inbox/Desde IA/'+value,ia_permiso=value)
            state=self.preview(note_id);self.assertEqual(set(state['actions']['enable']['changes']),{'ia_permiso','ia_indexar'})
            bad=self.command(state);bad['authorized_fields']=['ia_indexar'];self.assertEqual(self.post(bad,note_id).status_code,422)
            r=self.post(self.command(state),note_id);self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['access']['available_to_ai'])
    def test_no_declassification_health_reserved_or_source_bypass(self):
        for sensitivity in ['privado','sensible']:
            note_id=self.note('01 Inbox/Desde IA/'+sensitivity,sensibilidad=sensitivity);state=self.preview(note_id)
            self.assertFalse(state['actions']['enable']['allowed']);self.assertEqual(self.post(self.command(state),note_id).status_code,409)
        health=self.note('01 Inbox/Desde IA/health',datos_generales=[{'categoria':'salud','texto':'No divulgar'}]);self.assertFalse(self.preview(health)['actions']['enable']['allowed'])
        source=self.note('07 Conocimiento/source',estado='activo',ia_permiso='deny')
        for label,extra in [('proof',{'datos_fuente':{'origen':[{'source_id':source}]}}),('source',{'fuentes_ids':[source]}),('missing',{'fuentes_ids':['missing']})]:
            n=self.note('01 Inbox/Desde IA/'+label,**extra);state=self.preview(n);self.assertFalse(state['actions']['enable']['allowed']);self.assertEqual(self.post(self.command(state),n).status_code,409)
        reserved=self.note('00 Sistema/private');self.assertEqual(self.c.get('/human/inbox-access/'+reserved).status_code,404)
        secret=self.note('01 Inbox/Desde IA/secret',sensibilidad='secreto');self.assertEqual(self.c.get('/human/inbox-access/'+secret).status_code,404)
        self.assertEqual(people.records('inbox_access'),[])
    def test_immutable_originals_are_not_rewritten_or_made_editable(self):
        n=self.note('07 Conocimiento/Contexto/inmutable',fuente_inmutable=True);path=self.root/vault_index.get(n).path;raw=path.read_bytes()
        self.assertEqual(self.post(self.command(self.preview(n)),n).status_code,200)
        self.assertEqual(path.read_bytes(),raw);meta=vault_index.get(n).metadata;self.assertTrue(meta.fuente_inmutable);self.assertFalse(meta.ia_editar);self.assertFalse(meta.revisado)
    def test_stale_source_grant_change_replay_and_file_edit_expiry(self):
        state=self.preview();body=self.command(state);path=self.root/vault_index.get(self.id).path
        path.write_bytes(path.read_bytes()+b'\nCambio');vault_index.rebuild_file(path)
        self.assertEqual(self.post(body).status_code,409);self.assertEqual(people.records('inbox_access'),[])
        body=self.command(self.preview());self.assertEqual(self.post(body).status_code,200)
        path.write_bytes(path.read_bytes()+b'\nOtro cambio');vault_index.rebuild_file(path)
        self.assertFalse(is_ai_eligible(vault_index.get(self.id)));self.assertEqual(self.post(body).status_code,409)
        state=self.preview();self.assertTrue(state['actions']['revoke']['allowed']);self.assertEqual(self.post(self.command(state,'revoke')).status_code,200)
    def test_retry_recovers_grant_saved_before_receipt_and_preserves_id(self):
        body=self.command(self.preview());original=people.save
        def lose(kind,key,value):
            if kind=='inbox_access_requests':raise OSError('Synthetic receipt interruption')
            return original(kind,key,value)
        with patch.object(people,'save',side_effect=lose):
            with self.assertRaises(OSError):self.post(body)
        self.assertTrue(self.preview()['available_to_ai'])
        r=self.post(body);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['request_id'],body['request_id']);self.assertEqual(len(people.records('inbox_access_history')),1)
        self.assertEqual(self.post({**body,'action':'revoke'}).status_code,409)
    def test_source_cannot_forge_an_access_grant_and_symlinks_rejected(self):
        n=self.note('01 Inbox/Desde IA/forged',acceso_inbox_ia={'decision':'allow'})
        self.assertFalse(is_ai_eligible(vault_index.get(n)));self.assertIsNone(vault_index.get(n).metadata.acceso_inbox_ia)
        p=access_path(self.root,self.id);p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(self.root/vault_index.get(n).path)
        self.assertEqual(self.c.get('/human/inbox-access/'+self.id).status_code,409)
    def test_grant_survives_documentary_review_and_remains_revocable(self):
        self.assertEqual(self.post(self.command(self.preview())).status_code,200)
        detail=self.c.get('/human/items/note/'+self.id).json()
        r=self.c.post('/human/items/note/'+self.id+'/decision',json={'request_id':str(uuid4()),'revision':detail['revision'],'decision':'approve','authorized_fields':['review']})
        self.assertEqual(r.status_code,200,r.text);state=self.preview();self.assertEqual(state['estado'],'activo');self.assertTrue(state['available_to_ai'])
        self.assertEqual(self.post(self.command(state,'revoke')).status_code,200);self.assertFalse(is_ai_eligible(vault_index.get(self.id)))
    def test_grant_never_bypasses_later_source_restriction(self):
        source=self.note('07 Conocimiento/Contexto/source-ok',estado='activo',ia_indexar=True)
        target=self.note('01 Inbox/Desde IA/with-source',fuentes_ids=[source])
        self.assertEqual(self.post(self.command(self.preview(target)),target).status_code,200)
        path=self.root/vault_index.get(source).path;path.write_text(path.read_text().replace('ia_permiso: allow','ia_permiso: deny'));vault_index.rebuild_file(path)
        self.assertFalse(is_ai_eligible(vault_index.get(target)));self.assertFalse(self.preview(target)['available_to_ai'])
        self.scope='ai_context';self.assertEqual(self.c.get('/notes/'+target).status_code,403)
    def test_reserved_segments_require_separate_owner_review(self):
        n=self.note('01 Inbox/Desde IA/reserved',segmentos_reservados=[{'texto':'Contenido reservado'}]);state=self.preview(n)
        self.assertFalse(state['actions']['enable']['allowed']);self.assertEqual(self.post(self.command(state),n).status_code,409)
