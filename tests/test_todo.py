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
 def decision(self,restricted=False):
  from app.core import meeting_capture as capture,people
  from app.models.meetings import MeetingCreate,ProposalBatch,ProposalCreate
  p=self.root/'05 Proyectos/proyecto.md';p.parent.mkdir(exist_ok=True);p.write_text('---\ntitulo: Proyecto Demo\ntipo: proyecto\nestado: activo\narea: Laboral\nia_permiso: allow\nia_indexar: true\nsensibilidad: normal\n---\n\n# Proyecto Demo');vault_index.rebuild_file(p)
  m=capture.create_meeting('05-proyectos-proyecto',MeetingCreate(request_id=uuid4(),title='Reunión demo',fecha='2026-11-11',source='Fixture',content='Registrar acuerdo.'))
  proposal=capture.create_proposals('05-proyectos-proyecto',m['id'],ProposalBatch(items=[ProposalCreate(request_id=uuid4(),tipo='decision',title='Acuerdo Demo',detalle='Mantener el acuerdo original.',evidencia='Registrar acuerdo.',responsable='Responsable registrado',vencimiento='2026-11-30')]))[0]
  approved=capture.review_proposal('05-proyectos-proyecto',m['id'],proposal['id'],'approve')
  from app.core.id_utils import path_to_id
  note=vault_index.get(path_to_id(approved['approved_path']))
  if restricted:
   path=self.root/note.path;path.write_text(path.read_text().replace('ia_permiso: allow','ia_permiso: deny'));vault_index.rebuild_file(path);note=vault_index.get(note.id)
  self.body.update(request_id=str(uuid4()),title='Ejecutar el acuerdo',responsable=None,vencimiento=None,project_id='05-proyectos-proyecto',source_decision_id=note.id,source_decision_revision=people.revision(note))
  return note,proposal
 def test_task_from_decision_preserves_original_and_only_creates_pending_activity(self):
  note,_=self.decision();original=(self.root/note.path).read_bytes();t=self.create()
  self.assertEqual(t['estado'],'pendiente');self.assertIsNone(t['responsable']);self.assertIsNone(t['vencimiento'])
  self.assertEqual(t['source_decision_id'],note.id);self.assertEqual(t['source_decision_title'],'Acuerdo Demo');self.assertEqual(t['proyectos'],['[[05 Proyectos/proyecto]]'])
  self.assertIn('[['+note.path.removesuffix('.md')+']]',(self.root/t['path']).read_text())
  self.assertEqual((self.root/note.path).read_bytes(),original);self.assertEqual(self.create()['id'],t['id'])
  self.assertEqual(len(list(self.root.glob('09 Acciones/TODO/*.md'))),1)
 def test_task_from_decision_rejects_stale_source_proposals_and_wrong_project(self):
  from app.core import people
  note,proposal=self.decision();path=self.root/note.path;path.write_text(path.read_text()+'\nCambio');vault_index.rebuild_file(path)
  self.assertEqual(self.c.post('/actions/todo',json=self.body).status_code,409)
  self.body.update(source_decision_id=proposal['id'],source_decision_revision=people.revision(vault_index.get(proposal['id'])))
  self.assertEqual(self.c.post('/actions/todo',json=self.body).status_code,422)
  self.body.update(source_decision_id=note.id,source_decision_revision=people.revision(vault_index.get(note.id)),project_id='otro-proyecto')
  self.assertEqual(self.c.post('/actions/todo',json=self.body).status_code,422)
  self.assertEqual(list(self.root.glob('09 Acciones/TODO/*.md')),[])
 def test_task_from_decision_inherits_privacy_and_assistant_cannot_read_restricted_source(self):
  from app.middleware.permissions import is_ai_eligible
  note,_=self.decision(True)
  self.assertEqual(self.c.post('/actions/todo',json=self.body,headers={'X-PachiMind-Actor':'assistant'}).status_code,404)
  t=self.create();self.assertFalse(is_ai_eligible(vault_index.get(t['id'])))
  self.assertEqual(self.c.post('/actions/todo',json=self.body,headers={'X-PachiMind-Actor':'assistant'}).status_code,403)
  path=self.root/note.path;path.write_text(path.read_text().replace('sensibilidad: normal','sensibilidad: secreto'));vault_index.rebuild_file(path)
  self.assertEqual(self.c.get('/actions/todo').json(),[])
 def test_legacy_task_request_fingerprint_still_replays(self):
  self.body['request_id']='11111111-1111-4111-8111-111111111111'
  p=self.root/'09 Acciones/TODO/enviar-informe-11111111-1111-4111-8111-111111111111.md';p.parent.mkdir(parents=True)
  p.write_text('---\ntitulo: Enviar informe\ntipo: accion\nestado: pendiente\nrequest_hash: 28e805cace4146052cbb0ccacd808664d9160c3d8e2c3f00b6e4269c05e875b0\n---\n\nContenido original\nsegunda línea')
  vault_index.rebuild_file(p);before=p.read_bytes();self.create();self.assertEqual(p.read_bytes(),before)
 def test_assignments_and_dates_roundtrip_edit_clear_and_preserve_body(self):
  self.body.update(subresponsables=[' Andrés Buteler ','Genaro La Fata'],fecha_inicio='2026-10-01')
  task=self.create();self.assertEqual(task['subresponsables'],['Andrés Buteler','Genaro La Fata']);self.assertEqual(task['fecha_inicio'],'2026-10-01')
  self.assertEqual(self.create()['id'],task['id']);self.assertEqual(len(list(self.root.glob('09 Acciones/TODO/*.md'))),1)
  path=self.root/task['path'];body=path.read_bytes().split(b'---\n',2)[2]
  vault_index.build(self.root);self.assertEqual(self.c.get('/actions/todo').json()[0],task)
  r=self.c.patch('/actions/todo/'+task['id'],json={'revision':task['revision'],'responsable':'Sabrina','subresponsables':['Pablo'],'fecha_inicio':'2026-10-02','vencimiento':'2026-10-08'})
  self.assertEqual(r.status_code,200,r.text);task=r.json()
  self.assertEqual(task['responsable'],'Sabrina');self.assertEqual(task['subresponsables'],['Pablo']);self.assertEqual(task['fecha_inicio'],'2026-10-02')
  r=self.c.patch('/actions/todo/'+task['id'],json={'revision':task['revision'],'estado':'completado'})
  self.assertEqual(r.status_code,200,r.text);task=r.json();self.assertEqual(task['subresponsables'],['Pablo']);self.assertEqual(task['fecha_inicio'],'2026-10-02')
  r=self.c.patch('/actions/todo/'+task['id'],json={'revision':task['revision'],'responsable':None,'subresponsables':[],'fecha_inicio':None,'vencimiento':None})
  self.assertEqual(r.status_code,200,r.text);task=r.json()
  self.assertIsNone(task['responsable']);self.assertEqual(task['subresponsables'],[]);self.assertIsNone(task['fecha_inicio']);self.assertIsNone(task['vencimiento'])
  self.assertEqual(path.read_bytes().split(b'---\n',2)[2],body)
 def test_assignment_and_date_validation_is_atomic_and_checks_merged_patch(self):
  for fields in [{'fecha_inicio':'2026-10-07'},{'fecha_inicio':'2026-02-31'},{'subresponsables':[' ']},{'subresponsables':['x'*201]},{'subresponsables':['Persona']*21},{'subresponsables':None},{'subresponsables':'Pablo'}]:
   r=self.c.post('/actions/todo',json={**self.body,**fields});self.assertEqual(r.status_code,422,r.text)
  self.assertEqual(list(self.root.glob('09 Acciones/TODO/*.md')),[])
  self.body.update(fecha_inicio='2026-10-01',subresponsables=['Andrés']);task=self.create();path=self.root/task['path'];before=path.read_bytes()
  for changes in [{'vencimiento':'2026-09-30'},{'fecha_inicio':'2026-10-07'},{'subresponsables':[' '*4]}]:
   r=self.c.patch('/actions/todo/'+task['id'],json={'revision':task['revision'],**changes});self.assertEqual(r.status_code,422,r.text);self.assertEqual(path.read_bytes(),before)
  r=self.c.patch('/actions/todo/'+task['id'],json={'revision':'stale','subresponsables':['Otra persona']});self.assertEqual(r.status_code,409);self.assertEqual(path.read_bytes(),before)
  r=self.c.patch('/actions/todo/'+task['id'],json={'revision':task['revision'],'fecha_inicio':'2026-10-06'})
  self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['fecha_inicio'],r.json()['vencimiento'])
 def test_old_notes_have_optional_assignment_defaults_without_migration(self):
  path=self.root/'09 Acciones/historica.md';path.parent.mkdir(parents=True);path.write_text('---\ntitulo: Histórica\ntipo: accion\nestado: pendiente\n---\n\nOriginal')
  before=path.read_bytes();vault_index.build(self.root);task=self.c.get('/actions/todo').json()[0]
  self.assertIsNone(task['responsable']);self.assertEqual(task['subresponsables'],[]);self.assertIsNone(task['fecha_inicio']);self.assertIsNone(task['vencimiento']);self.assertEqual(path.read_bytes(),before)
 def test_assignment_changes_keep_decision_source_and_idempotency(self):
  note,_=self.decision();original=(self.root/note.path).read_bytes();self.body.update(responsable='Pablo',subresponsables=['Andrés'],fecha_inicio='2026-11-12',vencimiento='2026-11-15')
  task=self.create();self.assertEqual(self.create()['id'],task['id']);self.assertEqual(task['source_decision_id'],note.id)
  changed={**self.body,'subresponsables':['Genaro']};self.assertEqual(self.c.post('/actions/todo',json=changed).status_code,409)
  r=self.c.patch('/actions/todo/'+task['id'],json={'revision':task['revision'],'subresponsables':['Genaro'],'fecha_inicio':'2026-11-13'})
  self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['source_decision_id'],note.id);self.assertEqual(r.json()['proyectos'],task['proyectos']);self.assertEqual((self.root/note.path).read_bytes(),original)
