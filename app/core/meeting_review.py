"""Read owner-confirmed documentary reviews without rewriting immutable captures.

Records are installed by the operator after human confirmation, outside the note
write API. They confirm date/attendance only, not attributed voices or proposals.
"""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentaryReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_kind: Literal["documental"]
    reviewed: Literal[True]
    approved_by: str = Field(min_length=1, max_length=200)
    approved_date: date
    meeting_date: date
    participants: list[str] = Field(min_length=1, max_length=100)
    speaker_assignment: Literal["unassigned"]
    financial_facts_validated: Literal[False]

    @field_validator("participants")
    @classmethod
    def valid_names(cls, values):
        if any(not name.strip() or len(name) > 200 for name in values):
            raise ValueError("Invalid participant")
        return list(dict.fromkeys(name.strip() for name in values))


def record_path(root: Path, note_id: str) -> Path:
    return root / ".pachimind/meeting_reviews" / (sha256(note_id.encode()).hexdigest() + ".json")


def apply_documentary_review(metadata, root, note_id, raw):
    if (metadata.get("origen") != "captura_reunion"
            or metadata.get("tipo") != "reunion"
            or metadata.get("fuente_inmutable") is not True):
        return metadata
    path = record_path(root, note_id)
    try:
        if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
                or path.stat().st_size > 64000):
            return metadata
        record = DocumentaryReview.model_validate(json.loads(path.read_text()))
        if record.source_id != note_id or record.source_sha256 != sha256(raw).hexdigest():
            return metadata
    except (OSError, ValueError):
        return metadata
    # Never take permission, content, task or decision approval from this record.
    return {**metadata, "revisado": True, "fecha": record.meeting_date.isoformat(),
            "personas": record.participants, "revision_documental": record.model_dump(mode="json")}
