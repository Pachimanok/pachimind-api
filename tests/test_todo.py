import os
os.environ.setdefault('VAULT_PATH','/tmp/pachimind-todo-tests')
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.core.vault_index import vault_index
from app.routers.actions import router
from app.middleware.auth import get_scope

class TodoTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.old=(settings.vault_path,vault_index._notes,vault_index._vault_root)
  settings.vault_path=str(self.root);vault_index.build(self.root)
  app=FastAPI();app.include_router(router);app.dependency_overrides[get_scope]=lambda:'personal';self.app=app;self.c=TestClient(app)
  self.body={'request_id':str(uuid4()),'title':'Enviar informe','area':'Personal','responsable':'Pablo','vencimiento':'2026-10-06','detalle':'Contenido original\nsegunda línea'}
 def tearDown(self):
  settings.vault_path,vault_index._notes,vault_index._vault_root=self.old;self.tmp.cleanup()
 def create(self):
  r=self.c.post('/actions/todo',json=self.body);self.assertEqual(r.status_code,201,r.text);return r.json()
 def test_create_retry_complete_reopen_preserves_body(self):
  t=self.create();self.assertEqual(self.create()['id'],t['id']);p=self.root/t['path'];body=p.read_bytes().split(b'---\n',2)[2]
  r=self.c.patch('/actions/todo/'+t['id'],json={'revision':t['revision'],'estado':'completado'});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['estado'],'completado')
  self.assertEqual(p.read_bytes().split(b'---\n',2)[2],body)
  vault_index.build(self.root);self.assertEqual(self.c.get('/actions/todo').json()[0]['estado'],'completado')
  t=r.json();r=self.c.patch('/actions/todo/'+t['id'],json={'revision':t['revision'],'estado':'pendiente','vencimiento':None});self.assertEqual(r.status_code,200);self.assertIsNone(r.json()['vencimiento'])
 def test_conflicts_validation_and_scope(self):
  t=self.create();self.body['title']='Otro';self.assertEqual(self.c.post('/actions/todo',json=self.body).status_code,409)
  self.assertEqual(self.c.patch('/actions/todo/'+t['id'],json={'revision':'old','estado':'completado'}).status_code,409)
  self.assertEqual(self.c.patch('/actions/todo/'+t['id'],json={'revision':t['revision'],'estado':None}).status_code,422)
  self.body['request_id']=str(uuid4());self.body['vencimiento']='2026-02-31';self.assertEqual(self.c.post('/actions/todo',json=self.body).status_code,422)
  self.app.dependency_overrides[get_scope]=lambda:'ai_context';self.assertEqual(self.c.get('/actions/todo').status_code,403);self.assertEqual(self.c.patch('/actions/todo/'+t['id'],json={'revision':t['revision'],'estado':'completado'}).status_code,403)
 def test_approved_actions_but_not_proposals_or_sources(self):
  for rel,state,extra in [('09 Acciones/aprobada.md','pendiente','origen: revision_reunion\nfuente_ref: reunion.md\n'),('01 Inbox/propuesta.md','para_revisar',''),('09 Acciones/archivada.md','archivado',''),('09 Acciones/original.md','pendiente','fuente_inmutable: true\n')]:
   p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(f'---\ntipo: accion\nestado: {state}\n{extra}---\n\nCuerpo\r\noriginal\n')
  vault_index.build(self.root);items=self.c.get('/actions/todo').json();self.assertEqual(len(items),1);self.assertEqual(items[0]['fuente_ref'],'reunion.md')
  t=items[0];p=self.root/t['path'];old=p.read_bytes().split(b'---\n',2)[2]
  self.assertEqual(self.c.patch('/actions/todo/'+t['id'],json={'revision':t['revision'],'estado':'en_proceso'}).status_code,200);self.assertEqual(p.read_bytes().split(b'---\n',2)[2],old)
 def test_project_inherits_permissions_and_links(self):
  p=self.root/'05 Proyectos/p.md';p.parent.mkdir();p.write_text('---\ntipo: proyecto\nestado: activo\narea: Laboral\nia_permiso: deny\n---\n# Proyecto\n');vault_index.build(self.root)
  self.body['project_id']='05-proyectos-p';t=self.create();self.assertEqual(t['area'],'Laboral');self.assertEqual(t['proyectos'],['[[05 Proyectos/p]]']);self.assertIn('ia_permiso: deny',(self.root/t['path']).read_text())
