from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class MeetingCreate(BaseModel):
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    fecha: date
    participantes: list[str] = Field(default_factory=list, max_length=100)
    source: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1, max_length=500000)
    allow_ai: bool = True

    @field_validator('title', 'source', 'content')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('No puede estar vacío')
        return value


class ProposalCreate(BaseModel):
    request_id: UUID
    tipo: Literal['decision', 'accion']
    title: str = Field(min_length=1, max_length=200)
    detalle: str = Field(min_length=1, max_length=10000)
    evidencia: str = Field(min_length=1, max_length=10000)
    responsable: str | None = Field(default=None, max_length=200)
    vencimiento: date | None = None

    @field_validator('title', 'detalle', 'evidencia')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('No puede estar vacío')
        return value


class ProposalBatch(BaseModel):
    items: list[ProposalCreate] = Field(min_length=1, max_length=40)


class ProposalReview(BaseModel):
    action: Literal['approve', 'discard']
