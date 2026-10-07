from datetime import datetime
from pydantic import BaseModel
from .note import NoteResponse


class PaginatedNotes(BaseModel):
    total: int
    page: int
    per_page: int
    results: list[NoteResponse]


class VaultStats(BaseModel):
    total_notes: int
    by_type: dict[str, int]
    by_area: dict[str, int]
    sensitive_notes: int
    ai_indexable_notes: int
    notes_to_review: int


class SearchResult(BaseModel):
    id: str
    title: str
    type: str | None
    area: str | None
    excerpt: str
    path: str
    score: float


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResult]


class AIContextResponse(BaseModel):
    query: str
    results: list[SearchResult]


class ClientSummary(BaseModel):
    id: str
    title: str
    status: str | None
    projects_count: int
    people_count: int


class HealthResponse(BaseModel):
    status: str
    vault_connected: bool
    indexed_notes: int


class ActivityNote(BaseModel):
    id: str
    title: str
    tipo: str | None
    area: str | None
    last_modified: datetime


class VaultActivity(BaseModel):
    recently_added: list[ActivityNote]
    processed_by_ai: list[ActivityNote]
    pending_review: list[ActivityNote]


class NotebookLMNotebook(BaseModel):
    id: str
    title: str


class NotebookLMSource(BaseModel):
    id: str
    title: str
    type: str
    status: str


class NotebookLMImportResult(BaseModel):
    source_id: str
    title: str
    ok: bool
    id: str | None = None
    path: str | None = None
    error: str | None = None


class NotebookLMImportResponse(BaseModel):
    results: list[NotebookLMImportResult]


class MemorySource(BaseModel):
    id: str
    title: str
    path: str
    tipo: str | None
    estado: str | None
    fecha: str | None
    fecha_registrada: str | None
    revisado: bool
    relation: str
    content: str | None
    excerpt: str
    truncated: bool
    fuente_inmutable: bool = False


class ProjectMemory(BaseModel):
    project_id: str
    title: str
    for_ai: bool
    sources: list[MemorySource]
    warnings: list[str]
