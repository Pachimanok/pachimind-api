"""Capture immutable meeting sources and explicit, traceable review proposals."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import fcntl
import json
import os
import tempfile
import re
import unicodedata

import frontmatter
import yaml
from fastapi import HTTPException
from app.config import settings
from app.core.id_utils import path_to_id
from app.core.vault_index import vault_index
from app.middleware.permissions import is_visible, is_ai_eligible


def root():
    return Path(settings.vault_path).resolve()


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@contextmanager
def transaction():
    # One process-shared lock per vault. Not a vault note or a synchronization artifact.
    key=sha256(str(root()).encode()).hexdigest()
    with open(Path(tempfile.gettempdir()) / f'pachimind-capture-{key}.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def path_for(relative):
    path=(root()/relative).resolve()
    if not path.is_relative_to(root()):
        raise HTTPException(400, 'Ruta fuera del vault')
    return path


def serialize(meta, content):
    return '---\n'+yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)+'---\n\n'+content


def atomic_write(relative, text, replace=False):
    path=path_for(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.capture-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(text.encode('utf-8'));out.flush();os.fsync(out.fileno())
        if replace:
            os.replace(tmp,path)
        else:
            os.link(tmp,path)  # create-only and atomic, never overwrite an existing note
        vault_index.rebuild_file(path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def raw_note(relative):
    path=path_for(relative)
    if not path.exists():raise HTTPException(404,'Nota no encontrada')
    # Preserve exact original whitespace, including CRLF, independently of the index parser.
    text=path.read_bytes().decode('utf-8')
    post=frontmatter.loads(text)
    header,sep,body=text.partition('\n---\n\n')
    if not sep:raise HTTPException(409,'Formato de captura modificado; revisar el archivo original')
    return post.metadata,body


def project_for(project_id):
    project=vault_index.get(project_id)
    if (not project or project.metadata.tipo!='proyecto' or not is_visible(project,'personal')
            or project.metadata.estado in {'archivado','borrador'}):
        raise HTTPException(404,'Proyecto no disponible')
    return project


def source_for(project_id, meeting_id):
    project_for(project_id)
    note=vault_index.get(meeting_id)
    if not note or not is_visible(note,'personal'):
        raise HTTPException(404,'Reunión no disponible')
    meta,body=raw_note(note.path)
    if meta.get('origen')!='captura_reunion' or meta.get('project_id')!=project_id:
        raise HTTPException(404,'Reunión no disponible para este proyecto')
    if sha256(body.encode()).hexdigest()!=meta.get('original_sha256'):
        raise HTTPException(409,'La fuente original cambió en disco. Revisala antes de continuar.')
    return note,meta,body


def readable_slug(title):
    plain=unicodedata.normalize('NFKD',title).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','-',plain).strip('-')[:48] or 'sin-titulo'


def create_meeting(project_id, body):
    with transaction():
        project=project_for(project_id)
        payload=body.model_dump(mode='json')
        request_hash=digest({'project_id':project_id,**payload})
        folder=path_for('06 Reuniones y Registros/Capturas')
        existing=list(folder.glob(f'*{body.request_id}.md')) if folder.exists() else []
        relative=(str(existing[0].relative_to(root())) if existing else
                  f'06 Reuniones y Registros/Capturas/{body.fecha}-reunion-{readable_slug(body.title)}-{body.request_id}.md')
        if path_for(relative).exists():
            meta,_=raw_note(relative)
            if meta.get('request_hash')!=request_hash:raise HTTPException(409,'La captura ya existe con otro contenido')
            source_for(project_id,path_to_id(relative))
            return {'id':path_to_id(relative),'path':relative,'created':False}
        ai_allowed=body.allow_ai and is_ai_eligible(project)
        meta={'titulo':body.title,'tipo':'reunion','estado':'activo','area':project.metadata.area,
              'fecha':body.fecha.isoformat(),'personas':body.participantes,
              'proyectos':[f'[[{project.path.removesuffix(".md")}]]'],'project_id':project_id,
              'cliente':project.metadata.cliente,'fuente':body.source,
              'capturada_en':datetime.now(timezone.utc).isoformat(),
              'sensibilidad':project.metadata.sensibilidad,'ia_permiso':'allow' if ai_allowed else 'deny',
              'ia_indexar':ai_allowed,'ia_editar':False,'revisado':False,'fuente_inmutable':True,
              'origen':'captura_reunion','request_hash':request_hash,
              'original_sha256':sha256(body.content.encode()).hexdigest()}
        atomic_write(relative,serialize(meta,body.content))
        return {'id':path_to_id(relative),'path':relative,'created':True}


def get_meeting(project_id, meeting_id, for_ai=False):
    note,meta,content=source_for(project_id,meeting_id)
    if for_ai and not is_ai_eligible(note):raise HTTPException(403,'Esta reunión no permite uso por IA')
    return {'id':note.id,'path':note.path,'title':meta['titulo'],'fecha':meta['fecha'],
            'source':meta['fuente'],'participantes':meta['personas'],'content':content,
            'allow_ai':is_ai_eligible(note)}


def proposal_path(request_id):
    return f'01 Inbox/Desde IA/propuesta-reunion-{request_id}.md'


def proposal_result(relative):
    meta,body=raw_note(relative)
    return {'id':path_to_id(relative),'path':relative,'title':meta['titulo'],
            'tipo':meta['tipo'],'estado':meta['estado'],'review':meta.get('review'),
            'detalle':meta['detalle'],'evidencia':meta['evidencia'],
            'responsable':meta.get('responsable'),'vencimiento':meta.get('vencimiento'),
            'approved_path':meta.get('approved_path')}


def list_proposals(project_id, meeting_id):
    source_for(project_id,meeting_id)
    results=[]
    for note in vault_index.all():
        if note.path.startswith('01 Inbox/Desde IA/propuesta-reunion-'):
            meta,_=raw_note(note.path)
            if meta.get('meeting_id')==meeting_id and meta.get('project_id')==project_id:
                results.append(proposal_result(note.path))
    return sorted(results,key=lambda n:n['path'])


def create_proposals(project_id,meeting_id,batch):
    with transaction():
        source,meta,content=source_for(project_id,meeting_id)
        pending=[]
        ids=set()
        for item in batch.items:
            if item.request_id in ids:raise HTTPException(422,'Identificador repetido en el lote')
            ids.add(item.request_id)
            if item.evidencia not in content:raise HTTPException(422,'Cada propuesta necesita una cita literal de la fuente')
            request_hash=digest({'meeting_id':meeting_id,**item.model_dump(mode='json')})
            relative=proposal_path(item.request_id)
            if path_for(relative).exists():
                old,_=raw_note(relative)
                if old.get('request_hash')!=request_hash:raise HTTPException(409,'Propuesta ya registrada con otro contenido')
                pending.append((relative,None));continue
            fields={k:meta.get(k) for k in ['area','proyectos','cliente','sensibilidad','ia_permiso']}
            fields.update(item.model_dump(mode='json'))
            fields.update({'titulo':item.title,'tipo':item.tipo,'estado':'para_revisar','fecha':meta['fecha'],
                           'ia_indexar':False,'ia_editar':False,'revisado':False,'origen':'propuesta_reunion',
                           'project_id':project_id,'meeting_id':meeting_id,'fuente_ref':source.path,
                           'request_hash':request_hash,'review':None})
            body=(f'# {item.title}\n\n{item.detalle}\n\n'
                  f'Fuente: [[{source.path.removesuffix(".md")}]]\n\n'
                  f'Responsable: {item.responsable or "Sin confirmar"}\n'
                  f'Vencimiento: {item.vencimiento or "Sin confirmar"}\n\n'
                  '## Evidencia literal\n\n'+''.join('> '+line+'\n' for line in item.evidencia.splitlines()))
            pending.append((relative,serialize(fields,body)))
        for relative,text in pending:
            if text is not None:atomic_write(relative,text)
        return [proposal_result(relative) for relative,_ in pending]


def review_proposal(project_id,meeting_id,proposal_id,action):
    with transaction():
        _,source_meta,original_content=source_for(project_id,meeting_id)
        proposal=vault_index.get(proposal_id)
        if not proposal or not proposal.path.startswith('01 Inbox/Desde IA/propuesta-reunion-'):
            raise HTTPException(404,'Propuesta no encontrada')
        meta,body=raw_note(proposal.path)
        if meta.get('meeting_id')!=meeting_id or meta.get('project_id')!=project_id:
            raise HTTPException(404,'Propuesta no encontrada')
        if meta.get('review'):
            if meta['review']!=action:raise HTTPException(409,'La propuesta ya fue resuelta')
            return proposal_result(proposal.path)
        if action=='approve':
            if meta.get('tipo') not in {'accion','decision'} or not meta.get('evidencia') or meta['evidencia'] not in original_content:
                raise HTTPException(409,'La propuesta cambió o perdió su evidencia; revisala antes de aprobar')
            folder='09 Acciones/Capturas' if meta['tipo']=='accion' else '07 Conocimiento/Decisiones'
            relative=f'{folder}/{meta["tipo"]}-{readable_slug(meta["titulo"])}-{meta["request_id"]}.md'
            approved=dict(meta)
            approved.update({'estado':'pendiente' if meta['tipo']=='accion' else 'activo','revisado':True,
                             'origen':'revision_reunion','ia_indexar':source_meta.get('ia_indexar',False),
                             'ia_permiso':source_meta['ia_permiso'],'sensibilidad':source_meta['sensibilidad']})
            # Resume a partial operation after a write error without duplicating its result.
            if path_for(relative).exists():
                existing,_=raw_note(relative)
                if existing.get('request_hash')!=meta['request_hash']:raise HTTPException(409,'Destino en conflicto')
            else:atomic_write(relative,serialize(approved,body))
            meta['approved_path']=relative
        meta.update({'estado':'archivado','review':action,'reviewed_at':datetime.now(timezone.utc).isoformat()})
        atomic_write(proposal.path,serialize(meta,body),replace=True)
        return proposal_result(proposal.path)
