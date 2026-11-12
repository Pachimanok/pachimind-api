"""Individual IA-read consent from the owner session. No source edits or content approvals."""
from hashlib import sha256
from typing import Literal
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from app.core import people,meeting_capture as capture
from app.core.vault_index import vault_index
from app.core.inbox_access_review import access_path,access_record
from app.middleware.permissions import is_ai_eligible

class AccessCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    revision:str=Field(pattern=r'^[a-f0-9]{64}$')
    action:Literal['enable','revoke']
    confirmed:bool=False
    authorized_fields:list[str]=Field(default_factory=list,max_length=2)

def load(note_id):
    n=people.node(note_id,'personal')
    record=access_record(capture.root(),note_id)
    if n.metadata.estado!='borrador' and not record:raise HTTPException(409,'Esta nota ya no está pendiente en INBOX.')
    return n,record

def version(n):
    p=access_path(capture.root(),n.id)
    if p.is_symlink():raise HTTPException(409,'Registro de acceso inválido; requiere revisión del propietario.')
    return capture.digest({'note':people.revision(n),'access':sha256(p.read_bytes()).hexdigest() if p.is_file() else None})

def preview(note_id):
    n,record=load(note_id);_,post=people.raw(n);raw=post.metadata
    current={k:getattr(n.metadata,k) for k in ['ia_permiso','ia_indexar']}
    original={'ia_permiso':raw.get('ia_permiso','allow'),'ia_indexar':raw.get('ia_indexar',True)}
    candidate=n.model_copy(deep=True);candidate.metadata.ia_permiso='allow';candidate.metadata.ia_indexar=True
    sources_ok=all((source:=vault_index.get(i)) is not None and is_ai_eligible(source) for i in n.metadata.fuentes_ids)
    can_read=is_ai_eligible(n) and sources_ok
    can_enable=n.metadata.estado=='borrador' and not can_read and is_ai_eligible(candidate) and sources_ok and not n.metadata.segmentos_reservados
    reason=('La nota ya está habilitada para lectura IA.' if can_read else
            'Esta nota o una fuente vinculada tiene una restricción adicional. No se modifican sensibilidad, fuentes ni protecciones desde este control.' if not can_enable else
            'Permite leer el contenido completo desde MCP y otras consultas IA. No permite editarlo ni aprobarlo.')
    changes={k:{'before':current[k],'after':v} for k,v in {'ia_permiso':'allow','ia_indexar':True}.items() if current[k]!=v}
    revoke=bool(record and record.decision=='allow')
    return {'id':n.id,'title':n.title,'path':n.path,'revision':version(n),'estado':n.metadata.estado,'revisado':n.metadata.revisado,
            'available_to_ai':can_read,'current':current,'source_immutable':n.metadata.fuente_inmutable,
            'grant_active':bool(n.metadata.acceso_inbox_ia and n.metadata.acceso_inbox_ia.get('decision')=='allow'),
            'actions':{'enable':{'allowed':can_enable,'changes':changes,'reason':reason},
                       'revoke':{'allowed':revoke,'changes':{k:{'before':current[k],'after':v} for k,v in original.items() if current[k]!=v},
                                 'reason':'Retira esta autorización y recupera los permisos del archivo original. Los agentes conservan lo que ya hayan leído.'}},
            'effect':'La nota conserva texto, ubicación, estado, revisión documental y permiso de edición. La autorización deja de aplicar si cambia el archivo original.'}

def change(note_id,command):
    require_id=str(command.request_id);fingerprint=capture.digest({'id':note_id,**command.model_dump(mode='json')})
    with capture.transaction():
        n,record=load(note_id);raw,_=people.raw(n);source_hash=sha256(raw).hexdigest()
        receipt_path=capture.path_for(people.record_path('inbox_access_requests',require_id))
        previous=people.load('inbox_access_requests',require_id) if receipt_path.exists() else None
        if previous and previous['fingerprint']!=fingerprint:raise HTTPException(409,'Este identificador corresponde a otra autorización.')
        if record and str(record.request_id)==require_id:
            if record.fingerprint!=fingerprint or record.source_sha256!=source_hash:raise HTTPException(409,'La nota cambió después de autorizar. Comprobá el acceso y revisá de nuevo.')
        else:
            if previous:raise HTTPException(409,'Otra autorización reemplazó este permiso. Comprobá el acceso actual.')
            state=preview(note_id)
            if state['revision']!=command.revision:raise HTTPException(409,'La nota o su acceso cambió. Volvé a comprobar antes de autorizar.')
            action=state['actions'][command.action]
            if not action['allowed']:raise HTTPException(409,action['reason'])
            if not command.confirmed or set(command.authorized_fields)!=set(action['changes']) or len(command.authorized_fields)!=len(set(command.authorized_fields)):
                raise HTTPException(422,'Confirmá todos y sólo los cambios de lectura mostrados.')
            value={'note_id':note_id,'source_sha256':source_hash,'decision':'allow' if command.action=='enable' else 'revoke',
                   'reviewed_by':'owner','reviewed_at':people.now(),'request_id':require_id,'fingerprint':fingerprint}
            people.save('inbox_access_history',require_id,{'grant':value,'previous':record.model_dump(mode='json') if record else None})
            people.save('inbox_access',sha256(note_id.encode()).hexdigest(),value)
        vault_index.rebuild_file(capture.path_for(n.path));result=preview(note_id)
        if sha256(capture.path_for(n.path).read_bytes()).hexdigest()!=source_hash:raise HTTPException(409,'El original cambió durante la autorización. Volvé a comprobar su acceso.')
        if command.action=='enable' and not result['available_to_ai']:raise HTTPException(409,'Una fuente vinculada cambió. Esta nota todavía no está habilitada para IA.')
        response={'id':note_id,'action':command.action,'request_id':require_id,'verified':True,'access':result}
        people.save('inbox_access_requests',require_id,{'fingerprint':fingerprint,'result':response})
        return response
