"""User-managed activities stored as ordinary Markdown action notes."""
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import UUID
import re
import frontmatter
import yaml
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from app.core.meeting_capture import transaction, path_for, atomic_write, serialize, readable_slug, digest, project_for
from app.core.vault_index import vault_index
from app.core.id_utils import path_to_id
from app.middleware.permissions import is_visible, is_ai_eligible

State=Literal['pendiente','en_proceso','completado']
Priority=Literal['alta','media','baja']
Area=Literal['Laboral','Personal','Familia','Amigos','Apostolado']
ACTIVE={'pendiente','en_proceso','completado','activo','inbox'}

class CreateTask(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True, extra='forbid')
    request_id: UUID
    title: str=Field(min_length=1,max_length=200)
    detalle: str=Field(default='',max_length=20000)
    area: Area='Laboral'
    project_id: str | None=None
    responsable: str | None=Field(default=None,max_length=200)
    vencimiento: date | None=None
    prioridad: Priority='media'

class UpdateTask(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid')
    revision: str
    estado: State | None=None
    responsable: str | None=Field(default=None,max_length=200)
    vencimiento: date | None=None
    prioridad: Priority | None=None

def task_note(note_id):
    n=vault_index.get(note_id)
    if not n or n.metadata.tipo!='accion' or not is_visible(n,'personal') or n.path.startswith('01 Inbox/') or n.metadata.estado not in ACTIVE:
        raise HTTPException(404,'Actividad no disponible en TODO')
    if n.metadata.fuente_inmutable:raise HTTPException(409,'Fuente protegida')
    return n

def read_task(n):
    data=path_for(n.path).read_bytes();post=frontmatter.loads(data.decode());m=post.metadata
    return {'id':n.id,'path':n.path,'title':n.title,'estado':m.get('estado') if m.get('estado') in ACTIVE-{'activo','inbox'} else 'pendiente',
            'area':m.get('area'),'proyectos':n.metadata.proyectos,'responsable':str(m['responsable']) if m.get('responsable') else None,
            'vencimiento':str(m['vencimiento']) if m.get('vencimiento') else None,'prioridad':m.get('prioridad') or 'media',
            'fuente_ref':m.get('fuente_ref'),'revision':sha256(data).hexdigest()}

def list_tasks():
    result=[]
    for n in vault_index.all():
        if n.metadata.tipo=='accion' and n.metadata.estado in ACTIVE and not n.path.startswith('01 Inbox/') and not n.metadata.fuente_inmutable and is_visible(n,'personal'):
            result.append(read_task(n))
    return sorted(result,key=lambda t:(t['estado']=='completado',t['vencimiento'] or '9999',{'alta':0,'media':1,'baja':2}.get(t['prioridad'],3),t['title']))

def create_task(body):
    with transaction():
        payload=body.model_dump(mode='json');fingerprint=digest(payload)
        folder=path_for('09 Acciones/TODO');existing=list(folder.glob(f'*{body.request_id}.md')) if folder.exists() else []
        relative=str(existing[0].relative_to(path_for('.'))) if existing else f'09 Acciones/TODO/{readable_slug(body.title)}-{body.request_id}.md'
        if path_for(relative).exists():
            meta=frontmatter.load(str(path_for(relative))).metadata
            if meta.get('request_hash')!=fingerprint:raise HTTPException(409,'La actividad ya existe con otros datos')
            vault_index.rebuild_file(path_for(relative))
            return read_task(task_note(path_to_id(relative)))
        project=project_for(body.project_id) if body.project_id else None
        allowed=not project or is_ai_eligible(project)
        meta={'titulo':body.title,'tipo':'accion','estado':'pendiente','area':project.metadata.area if project else body.area,
              'proyectos':[f'[[{project.path.removesuffix(".md")}]]'] if project else [],'project_id':body.project_id,
              'responsable':body.responsable,'vencimiento':body.vencimiento.isoformat() if body.vencimiento else None,
              'prioridad':body.prioridad,'fecha':date.today().isoformat(),'origen':'todo_manual','revisado':True,'ia_editar':False,
              'sensibilidad':project.metadata.sensibilidad if project else 'normal','ia_permiso':'allow' if allowed else 'deny',
              'ia_indexar':allowed,'request_hash':fingerprint}
        atomic_write(relative,serialize(meta,f'# {body.title}\n\n{body.detalle}\n'))
        return read_task(task_note(path_to_id(relative)))

def update_task(note_id,body):
    with transaction():
        n=task_note(note_id);raw=path_for(n.path).read_bytes()
        if sha256(raw).hexdigest()!=body.revision:raise HTTPException(409,'La actividad cambió. Actualizá la lista antes de editarla.')
        text=raw.decode();match=re.match(r'\A---\r?\n.*?\r?\n---(?:\r?\n|$)',text,re.S)
        if not match:raise HTTPException(409,'Frontmatter inválido')
        meta=frontmatter.loads(text).metadata
        changes=body.model_dump(mode='json',exclude_unset=True);changes.pop('revision')
        if any(changes.get(k,'not-null') is None for k in ['estado','prioridad']):raise HTTPException(422,'Estado y prioridad no pueden quedar vacíos')
        meta.update(changes)
        if 'estado' in changes:meta['completada_en']=datetime.now(timezone.utc).isoformat() if changes['estado']=='completado' else None
        # Only frontmatter changes; preserve the original body byte-for-byte.
        updated='---\n'+yaml.safe_dump(meta,allow_unicode=True,sort_keys=False)+'---\n'+text[match.end():]
        atomic_write(n.path,updated,replace=True)
        return read_task(task_note(note_id))
