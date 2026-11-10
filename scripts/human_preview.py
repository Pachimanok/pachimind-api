"""Human-inbox acceptance fixture. Always a fresh synthetic vault, never production."""
import os,sys
from pathlib import Path
from uuid import uuid4
os.environ.update(VAULT_PATH='/tmp/pachimind-human-preview-unused',API_KEYS='{"test-personal":"personal","reader":"ai_context","test-public":"public"}',
                  PM_API_KEY='test-personal',LOG_LEVEL='WARNING',NODE_URL='http://127.0.0.1:18301',NOTEBOOKLM_BIN='/nonexistent/preview-notebooklm')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from people_preview import create_demo
from app.core import people,meeting_capture as meeting
from app.core.vault_index import vault_index
from app.core.id_utils import path_to_id
from app.models.people import LinkCommand,PersonProposal,KnowledgeDraft
from app.models.meetings import MeetingCreate,ProposalBatch,ProposalCreate
root=create_demo()
def write(name,title,body='',**extra):
    p=root/(name+'.md');p.parent.mkdir(parents=True,exist_ok=True)
    meta=dict(titulo=title,tipo='recurso',estado='activo',sensibilidad='normal',ia_permiso='allow',ia_indexar=True,ia_editar=False,revisado=True)
    meta.update(extra);p.write_text(meeting.serialize(meta,body or '# '+title));vault_index.rebuild_file(p);return path_to_id(name+'.md')
project=path_to_id('05 Proyectos/proyecto-demo.md')
for i,name in enumerate(['Actividad','Alineación','Arquitectura']):
    source=write('07 Conocimiento/Recursos/'+str(i)+'-demo',name+' huérfana (demo)',name+' para Proyecto de ejemplo.',fuente_inmutable=True)
    cmd=LinkCommand(request_id=uuid4(),source_id=source,revision=people.revision(vault_index.get(source)),links=[dict(target_id=project,target_revision=people.revision(vault_index.get(project)),relation='vinculado al proyecto',evidence=dict(field='relation',source_id=source,quote=name+' para Proyecto de ejemplo.'))])
    people.propose_links(cmd,'personal',True)
source=path_to_id('06 Reuniones y Registros/fuente-demo.md');person=path_to_id('04 Entidades/Personas/1-demo.md')
people.propose_person(person,PersonProposal(request_id=uuid4(),revision=people.revision(vault_index.get(person)),fields={},
    evidence=[dict(field='funcion',source_id=source,quote='Documentación de prueba.')],questions=['¿Cuál es el alcance confirmado de la función?']),'personal',True)
people.knowledge(KnowledgeDraft(request_id=uuid4(),title='Síntesis protegida (demo)',kind='resumen',content='Síntesis sintética pendiente de revisar. Sin cifras reales.',source_ids=[source]),'personal',True)
m=meeting.create_meeting(project,MeetingCreate(request_id=uuid4(),title='Reunión sintética (demo)',fecha='2026-11-10',source='Fixture ficticia',content='Preparar informe demo. Registrar decisión demo.'))
meeting.create_proposals(project,m['id'],ProposalBatch(items=[ProposalCreate(request_id=uuid4(),tipo='accion',title='Informe a aprobar (demo)',detalle='Preparar un informe de ejemplo.',evidencia='Preparar informe demo.'),ProposalCreate(request_id=uuid4(),tipo='decision',title='Decisión a declinar (demo)',detalle='Decisión de ejemplo sin aplicar.',evidencia='Registrar decisión demo.')]))
for i in range(18):write('07 Conocimiento/Contexto/pendiente-'+str(i),'Nota pendiente demo '+str(i),revisado=False)
write('07 Conocimiento/Contexto/xss','<img src=x onerror=alert(1)>',revisado=False)
from app.main import app
@app.get('/health/preview')
def marker():return {'synthetic':True,'fixture':'human-demo'}
if __name__=='__main__':
    import uvicorn
    print('Fresh synthetic human-inbox fixture ready.',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('PREVIEW_API_PORT','18001')),access_log=False,log_level='warning')
