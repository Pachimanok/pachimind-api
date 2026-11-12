from fastapi import APIRouter, Depends, HTTPException, Header, Response
from typing import Literal
from pydantic import BaseModel

from app.core.inbox_writer import write_draft
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import apply_content_rules, is_visible
from app.models.filters import NoteFilters
from app.models.note import NoteResponse

router = APIRouter(prefix="/inbox", tags=["inbox"])

from app.core import inbox_classification as classification


@router.get('/{note_id}/classification')
def get_classification(note_id: str, response: Response, scope: str = Depends(get_scope),
                       actor: Literal['manual', 'assistant'] = Header('manual', alias='X-PachiMind-Actor')):
    response.headers['Cache-Control'] = 'no-store'
    return classification.get(note_id, scope, actor == 'assistant' or scope != 'personal')


@router.post('/{note_id}/classification')
def propose_classification(note_id: str, body: classification.Propose, response: Response,
                           scope: str = Depends(get_scope),
                           actor: Literal['manual', 'assistant'] = Header('manual', alias='X-PachiMind-Actor')):
    if scope != 'personal': raise HTTPException(403, 'Scope insuficiente para proponer clasificación')
    response.headers['Cache-Control'] = 'no-store'
    return classification.propose(note_id, body, scope, actor == 'assistant')


class DraftRequest(BaseModel):
    title: str
    content: str = ""
    area: str = "Personal"
    tipo: str = "nota"
    cliente: str | None = None
    proyecto: str | None = None
    tags: list[str] = []


@router.post("/draft", status_code=201)
def create_draft(body: DraftRequest, scope: str = Depends(get_scope)):
    if scope not in ("personal", "ai_context"):
        raise HTTPException(status_code=403, detail="Scope insuficiente para crear borradores")

    return write_draft(
        title=body.title,
        content=body.content,
        area=body.area,
        tipo=body.tipo,
        cliente=body.cliente,
        proyecto=body.proyecto,
        tags=body.tags,
    )


@router.get("", response_model=list[NoteResponse])
def list_pending_drafts(scope: str = Depends(get_scope)):
    """Borradores pendientes en 01 Inbox/Desde IA, con contenido completo en
    una sola llamada (evita el N+1 de listar + pedir cada nota por separado)."""
    if scope not in ("personal", "ai_context"):
        raise HTTPException(status_code=403, detail="Scope insuficiente")

    drafts = vault_index.filter(NoteFilters(estado="borrador"))
    drafts = [
        n for n in drafts
        if n.path.startswith("01 Inbox/Desde IA") and is_visible(n, scope)
    ]

    results = []
    for n in drafts:
        content, excerpt = apply_content_rules(n, scope)
        results.append(NoteResponse(
            id=n.id, title=n.title, path=n.path, metadata=n.metadata,
            content=content, excerpt=excerpt,
        ))
    return results
