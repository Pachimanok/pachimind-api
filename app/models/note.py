from datetime import datetime
from pydantic import BaseModel, Field


class NoteMetadata(BaseModel):
    tipo: str | None = None
    estado: str | None = None
    area: str | None = None
    subarea: str | None = None
    cliente: str | None = None
    organizacion: str | None = None
    marca: str | None = None
    personas: list[str] = []
    proyectos: list[str] = []
    fecha: str | None = None
    prioridad: str | None = None
    sensibilidad: str = "normal"
    ia_permiso: str = "allow"
    ia_indexar: bool = True
    ia_editar: bool = False
    revisado: bool = False
    tags: list[str] = []
    origen: str | None = None
    fuente_inmutable: bool = False


class NoteModel(BaseModel):
    id: str
    path: str
    title: str
    metadata: NoteMetadata
    content: str
    content_text: str
    wikilinks: list[str] = []
    last_modified: datetime


class NoteResponse(BaseModel):
    id: str
    title: str
    path: str
    metadata: NoteMetadata
    content: str | None = None
    excerpt: str | None = None
    resolved_links: dict[str, str | None] = {}


class NoteSummary(BaseModel):
    id: str
    title: str
    path: str
    tipo: str | None = None
    estado: str | None = None
    area: str | None = None
    sensibilidad: str = "normal"
    prioridad: str | None = None
    revisado: bool = False
