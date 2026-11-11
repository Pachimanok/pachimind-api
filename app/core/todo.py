"""User-managed activities stored as ordinary Markdown action notes."""
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID
import re
import frontmatter
import yaml
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict, model_validator
from app.core.meeting_capture import transaction, path_for, atomic_write, serialize, readable_slug, digest, project_for
from app.core.vault_index import vault_index
from app.core.id_utils import path_to_id
from app.middleware.permissions import is_visible, is_ai_eligible

State=Literal['pendiente','en_proceso','completado']
Priority=Literal['alta','media','baja']
Area=Literal['Laboral','Personal','Familia','Amigos','Apostolado']
ACTIVE={'pendiente','en_proceso','completado','activo','inbox'}
Assignee=Annotated[str,Field(min_length=1,max_length=200)]

class CreateTask(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True, extra='forbid')
    request_id: UUID
    title: str=Field(min_length=1,max_length=200)
    detalle: str=Field(default='',max_length=20000)
    area: Area='Laboral'
    project_id: str | None=None
    responsable: str | None=Field(default=None,max_length=200)
    subresponsables: list[Assignee]=Field(default_factory=list,max_length=20)
    fecha_inicio: date | None=None
    vencimiento: date | None=None
    prioridad: Priority='media'
    source_decision_id: str | None=Field(default=None,min_length=1,max_length=300)
    source_decision_revision: str | None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    @model_validator(mode='after')
    def decision_pair(self):
        if bool(self.source_decision_id) != bool(self.source_decision_revision):
            raise ValueError('La decisión y su revisión deben indicarse juntas')
        if self.fecha_inicio and self.vencimiento and self.fecha_inicio>self.vencimiento:
            raise ValueError('La fecha de inicio no puede ser posterior al vencimiento')
        return self

class UpdateTask(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid')
    revision: str
    estado: State | None=None
    responsable: str | None=Field(default=None,max_length=200)
    subresponsables: list[Assignee]=Field(default_factory=list,max_length=20)
    fecha_inicio: date | None=None
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
    secondary=m.get('subresponsables') or []
    if isinstance(secondary,str):secondary=[secondary]
    if not isinstance(secondary,list):secondary=[]
    result={'id':n.id,'path':n.path,'title':n.title,'estado':m.get('estado') if m.get('estado') in ACTIVE-{'activo','inbox'} else 'pendiente',
            'area':m.get('area'),'proyectos':n.metadata.proyectos,'responsable':str(m['responsable']) if m.get('responsable') else None,
            'subresponsables':[s for s in secondary if isinstance(s,str) and s.strip()],
            'fecha_inicio':str(m['fecha_inicio']) if m.get('fecha_inicio') else None,
            'vencimiento':str(m['vencimiento']) if m.get('vencimiento') else None,'prioridad':m.get('prioridad') or 'media',
            'fuente_ref':m.get('fuente_ref'),'revision':sha256(data).hexdigest()}
    if m.get('source_decision_id'):
        decision=vault_index.get(m['source_decision_id'])
        result.update(source_decision_id=m['source_decision_id'],source_decision_ref=m.get('source_decision_ref'),
                      source_decision_title=decision.title if decision else 'Decisión de origen')
    return result

def list_tasks():
    result=[]
    for n in vault_index.all():
        if n.metadata.tipo=='accion' and n.metadata.estado in ACTIVE and not n.path.startswith('01 Inbox/') and not n.metadata.fuente_inmutable and is_visible(n,'personal'):
            result.append(read_task(n))
    return sorted(result,key=lambda t:(t['estado']=='completado',t['vencimiento'] or '9999',{'alta':0,'media':1,'baja':2}.get(t['prioridad'],3),t['title']))

def create_task(body, ai=False):
    with transaction():
        payload=body.model_dump(mode='json')
        if not body.source_decision_id:
            payload.pop('source_decision_id',None);payload.pop('source_decision_revision',None)
        # Keep the exact fingerprint of requests made before these optional fields existed.
        if not body.subresponsables:payload.pop('subresponsables',None)
        if body.fecha_inicio is None:payload.pop('fecha_inicio',None)
        fingerprint=digest(payload)
        folder=path_for('09 Acciones/TODO');existing=list(folder.glob(f'*{body.request_id}.md')) if folder.exists() else []
        relative=str(existing[0].relative_to(path_for('.'))) if existing else f'09 Acciones/TODO/{readable_slug(body.title)}-{body.request_id}.md'
        if path_for(relative).exists():
            meta=frontmatter.load(str(path_for(relative))).metadata
            if meta.get('request_hash')!=fingerprint:raise HTTPException(409,'La actividad ya existe con otros datos')
            vault_index.rebuild_file(path_for(relative))
            existing=task_note(path_to_id(relative))
            if ai and body.source_decision_id and not is_ai_eligible(existing):raise HTTPException(403,'La actividad no está permitida para IA')
            return read_task(existing)
        decision=None;project_id=body.project_id
        if body.source_decision_id:
            from app.core import people
            decision=people.node(body.source_decision_id,'personal',ai)
            if decision.metadata.tipo!='decision' or decision.path.startswith('01 Inbox/') or decision.metadata.origen=='propuesta_reunion' or decision.metadata.estado in {'borrador','archivado','para_revisar','en_revision'}:
                raise HTTPException(422,'Usá una decisión registrada, no una propuesta pendiente')
            people.require_revision(decision,body.source_decision_revision)
            decision_meta=frontmatter.loads(path_for(decision.path).read_text()).metadata
            recorded_project=decision_meta.get('project_id')
            if recorded_project:
                if project_id and project_id!=recorded_project:raise HTTPException(422,'La actividad debe conservar el proyecto de la decisión')
                project_id=recorded_project
        project=project_for(project_id) if project_id else None
        allowed=(not project or is_ai_eligible(project)) and (not decision or is_ai_eligible(decision))
        sensitivity=project.metadata.sensibilidad if project else 'normal'
        if decision:
            order={'normal':0,'interno':1,'privado':2,'sensible':3,'secreto':4}
            sensitivity=max([sensitivity,decision.metadata.sensibilidad],key=lambda v:order.get(v,4))
        meta={'titulo':body.title,'tipo':'accion','estado':'pendiente','area':project.metadata.area if project else body.area,
              'proyectos':[f'[[{project.path.removesuffix(".md")}]]'] if project else [],'project_id':project_id,
              'responsable':body.responsable,'vencimiento':body.vencimiento.isoformat() if body.vencimiento else None,
              'subresponsables':body.subresponsables,'fecha_inicio':body.fecha_inicio.isoformat() if body.fecha_inicio else None,
              'prioridad':body.prioridad,'fecha':date.today().isoformat(),'origen':'todo_manual','revisado':True,'ia_editar':False,
              'sensibilidad':sensitivity,'ia_permiso':'allow' if allowed else 'deny',
              'ia_indexar':allowed,'request_hash':fingerprint}
        content=f'# {body.title}\n\n{body.detalle}\n'
        if decision:
            meta.update(source_decision_id=decision.id,source_decision_ref=decision.path,fuente_ref=decision.path,
                        fuentes_ids=[decision.id],datos_fuente={'decision_origen':[{'source_id':decision.id,'path':decision.path,'source_revision':body.source_decision_revision}]})
            content+='\n## Decisión de origen\n\n[['+decision.path.removesuffix('.md')+']]\n'
        atomic_write(relative,serialize(meta,content))
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
        if {'fecha_inicio','vencimiento'} & changes.keys():
            start=changes.get('fecha_inicio',meta.get('fecha_inicio'));end=changes.get('vencimiento',meta.get('vencimiento'))
            if start and end:
                try:invalid=date.fromisoformat(str(start))>date.fromisoformat(str(end))
                except ValueError:raise HTTPException(422,'Revisá las fechas de inicio y vencimiento')
                if invalid:raise HTTPException(422,'La fecha de inicio no puede ser posterior al vencimiento')
        meta.update(changes)
        if 'estado' in changes:meta['completada_en']=datetime.now(timezone.utc).isoformat() if changes['estado']=='completado' else None
        # Only frontmatter changes; preserve the original body byte-for-byte.
        updated='---\n'+yaml.safe_dump(meta,allow_unicode=True,sort_keys=False)+'---\n'+text[match.end():]
        atomic_write(n.path,updated,replace=True)
        return read_task(task_note(note_id))
