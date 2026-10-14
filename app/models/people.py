"""Validated commands for people, proposals and the separate relationship layer."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

Ambito = Literal['Trabajo', 'Apostólico', 'Colegios', 'Formación']
RelationType = Literal['participó en', 'mencionado en', 'trabaja con', 'vinculado al proyecto', 'fuente', 'relacionado con', 'referencia']

class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')

class PersonFields(Command):
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = Field(default=None, max_length=30)
    organizacion: str | None = Field(default=None, max_length=300)
    funcion: str | None = Field(default=None, max_length=300)
    relacion_conmigo: str | None = Field(default=None, max_length=1000)
    ambitos: list[Ambito] | None = Field(default=None, max_length=4)
    contactos_profesionales: dict[Literal['email_profesional', 'telefono_profesional', 'perfil_profesional'], str] | None = None
    notas_manuales: str | None = Field(default=None, max_length=20000)
    tipo: Literal['persona', 'idea', 'recurso', 'nota'] | None = None
    @field_validator('nombre')
    @classmethod
    def name(cls, value):
        if value is not None and (not value.strip() or any(ord(c) < 32 for c in value)):
            raise ValueError('Nombre no vacío, sin caracteres de control')
        return value.strip() if value is not None else value
    @field_validator('aliases')
    @classmethod
    def alias_lengths(cls, values):
        if values and any(not v.strip() or len(v) > 200 for v in values):
            raise ValueError('Alias no vacíos, de hasta 200 caracteres')
        return values
    @field_validator('contactos_profesionales')
    @classmethod
    def contact_lengths(cls, values):
        if values and any(len(v) > 500 for v in values.values()):
            raise ValueError('Contactos de hasta 500 caracteres')
        return values

class PersonCreate(Command):
    request_id: UUID
    nombre: str = Field(min_length=1, max_length=200)
    distinct_from: list[str] = Field(default_factory=list, max_length=30)
    @field_validator('nombre')
    @classmethod
    def name(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError('Nombre no vacío, sin caracteres de control')
        return value.strip()

class Evidence(Command):
    field: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=300)
    quote: str = Field(min_length=1, max_length=4000)

class PersonUpdate(Command):
    request_id: UUID
    revision: str = Field(min_length=64, max_length=64)
    fields: PersonFields
    evidence: list[Evidence] = Field(default_factory=list, max_length=50)
    confirm_review: bool = False

class PersonProposal(Command):
    request_id: UUID
    revision: str = Field(min_length=64, max_length=64)
    fields: PersonFields
    evidence: list[Evidence] = Field(min_length=1, max_length=50)
    questions: list[str] = Field(default_factory=list, max_length=20)

class NeutralSegment(Command):
    source_reference: str = Field(min_length=1, max_length=300)
    start_seconds: int = Field(ge=0)
    end_seconds: int = Field(ge=0)
    @field_validator('source_reference')
    @classmethod
    def neutral_locator(cls, value):
        import re
        from urllib.parse import urlparse
        url = urlparse(value)
        opaque = bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,299}', value))
        https = url.scheme == 'https' and url.hostname and not url.username and not url.password and not url.query and not url.fragment and not any(c.isspace() for c in value)
        if not opaque and not https:
            raise ValueError('Usá un identificador opaco o URL HTTPS sin credenciales, query ni texto del segmento')
        return value
    @model_validator(mode='after')
    def order(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError('El segmento debe terminar después de comenzar')
        return self

class LinkItem(Command):
    target_id: str = Field(min_length=1, max_length=300)
    target_revision: str = Field(min_length=64, max_length=64)
    relation: RelationType
    action: Literal['add', 'remove'] = 'add'
    evidence: Evidence | None = None

class LinkCommand(Command):
    request_id: UUID
    source_id: str = Field(min_length=1, max_length=300)
    revision: str = Field(min_length=64, max_length=64)
    links: list[LinkItem] = Field(min_length=1, max_length=30)
    reserved_segments: list[NeutralSegment] = Field(default_factory=list, max_length=20)

class ReviewCommand(Command):
    request_id: UUID
    revision: str = Field(min_length=64, max_length=64)
    action: Literal['apply', 'reject']
    authorized_fields: list[str] = Field(default_factory=list, max_length=30)
    expected_kind: Literal['person', 'links'] | None = None

class KnowledgeDraft(Command):
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    kind: Literal['contexto', 'resumen', 'lectura']
    content: str = Field(min_length=1, max_length=50000)
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    reserved_segments: list[NeutralSegment] = Field(default_factory=list, max_length=20)

class UndoCommand(Command):
    request_id: UUID
    revision: str = Field(min_length=64, max_length=64)
