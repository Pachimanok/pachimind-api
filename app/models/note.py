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
    nombre: str | None = None
    aliases: list[str] = []
    ambitos: list[str] = []
    rol: str | None = None
    funcion: str | None = None
    relacion_conmigo: str | None = None
    contactos_profesionales: dict[str, str] = {}
    notas_manuales: str | None = None
    ultima_revision: str | None = None
    datos_fuente: dict[str, list[dict]] = {}
    clase_conocimiento: str | None = None
    fuentes_ids: list[str] = []
    segmentos_reservados: list[dict] = []
    titulos_anteriores: list[str] = []


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
    revision: str | None = None


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
