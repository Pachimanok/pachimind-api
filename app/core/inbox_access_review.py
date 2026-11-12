"""Owner-consented IA reading, bound to exact original bytes; never trusts note declarations."""
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict

class InboxAccessReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    note_id:str
    source_sha256:str
    decision:Literal['allow','revoke']
    reviewed_by:Literal['owner']
    reviewed_at:str
    request_id:UUID
    fingerprint:str

def access_path(root:Path,note_id:str):
    return root/'.pachimind/inbox_access'/(sha256(note_id.encode()).hexdigest()+'.json')

def access_record(root,note_id):
    p=access_path(root,note_id)
    try:
        if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or p.stat().st_size>16000:return None
        value=InboxAccessReview.model_validate(json.loads(p.read_text()))
        return value if value.note_id==note_id else None
    except (OSError,ValueError):return None

def apply_inbox_access(metadata,root,note_id,raw):
    result={k:v for k,v in metadata.items() if k!='acceso_inbox_ia'}
    record=access_record(root,note_id)
    if not record or record.source_sha256!=sha256(raw).hexdigest():return result
    result['acceso_inbox_ia']=record.model_dump(mode='json')
    if record.decision=='allow':result.update(ia_permiso='allow',ia_indexar=True)
    return result
