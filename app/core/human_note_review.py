"""Human review status is separate from original text and access permissions."""
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class HumanNoteReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note_id: str
    source_sha256: str
    decision: Literal['approve', 'decline']
    reviewed_by: Literal['owner']
    reviewed_at: str
    request_id: UUID


def review_path(root: Path, note_id: str):
    return root / '.pachimind/human_notes' / (sha256(note_id.encode()).hexdigest() + '.json')


def apply_human_review(metadata, root, note_id, raw):
    metadata = {k: v for k, v in metadata.items() if k != 'revision_humana'}
    path = review_path(root, note_id)
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 16000:
            return metadata
        value = HumanNoteReview.model_validate(json.loads(path.read_text()))
        if value.note_id != note_id or value.source_sha256 != sha256(raw).hexdigest():
            return metadata
    except (OSError, ValueError):
        return metadata
    state = ('archivado' if value.decision == 'decline' else
             'activo' if metadata.get('estado') in {'borrador', 'para_revisar', 'en_revision'} else (metadata.get('estado') or 'activo'))
    return {**metadata, 'estado': state, 'revisado': True,
            'revision_humana': value.model_dump(mode='json')}
