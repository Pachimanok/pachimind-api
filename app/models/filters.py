from pydantic import BaseModel


class NoteFilters(BaseModel):
    area: str | None = None
    tipo: str | None = None
    estado: str | None = None
    sensibilidad: str | None = None
    cliente: str | None = None
    organizacion: str | None = None
    persona: str | None = None
    proyecto: str | None = None
    marca: str | None = None
    tag: str | None = None
    revisado: bool | None = None
    prioridad: str | None = None


class AIContextRequest(BaseModel):
    query: str
    filters: NoteFilters = NoteFilters()
    max_results: int = 10
