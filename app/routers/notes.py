from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from typing import Literal
from pydantic import BaseModel

from app.config import settings
from app.core.note_writer import TIPO_FOLDER, write_note, delete_note
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible, is_ai_eligible, apply_content_rules
from app.models.filters import NoteFilters
from app.models.responses import PaginatedNotes
from app.models.note import NoteResponse, NoteMetadata

router = APIRouter(prefix="/notes", tags=["notas"])


@router.get("", response_model=PaginatedNotes)
def list_notes(
    area: str | None = None,
    tipo: str | None = None,
    estado: str | None = None,
    sensibilidad: str | None = None,
    cliente: str | None = None,
    organizacion: str | None = None,
    persona: str | None = None,
    proyecto: str | None = None,
    marca: str | None = None,
    tag: str | None = None,
    revisado: bool | None = None,
    prioridad: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    scope: str = Depends(get_scope),
):
    filters = NoteFilters(
        area=area, tipo=tipo, estado=estado, sensibilidad=sensibilidad,
        cliente=cliente, organizacion=organizacion, persona=persona,
        proyecto=proyecto, marca=marca, tag=tag, revisado=revisado,
        prioridad=prioridad,
    )
    notes = vault_index.filter(filters)
    notes = [n for n in notes if is_visible(n, scope)]

    total = len(notes)
    start = (page - 1) * per_page
    page_notes = notes[start: start + per_page]

    results = [
        NoteResponse(
            id=n.id,
            title=n.title,
            path=n.path,
            metadata=n.metadata,
            excerpt=n.content_text[:200] if n.content_text else None,
        )
        for n in page_notes
    ]
    return PaginatedNotes(total=total, page=page, per_page=per_page, results=results)


class NoteCreateRequest(BaseModel):
    title: str
    tipo: str = "nota"
    area: str = "Laboral"
    estado: str = "activo"
    content: str = ""
    tags: list[str] = []
    cliente: str | None = None
    personas: list[str] = []
    source_draft_id: str | None = None


@router.post("", status_code=201)
def create_note(body: NoteCreateRequest, scope: str = Depends(get_scope)):
    if scope not in ("personal",):
        raise HTTPException(status_code=403, detail="Scope insuficiente para crear notas")

    if body.tipo == 'persona':
        raise HTTPException(409, "Creá la ficha mínima desde Personas (/people/drafts), sin duplicar ni inferir datos")

    return write_note(
        title=body.title,
        tipo=body.tipo,
        area=body.area,
        estado=body.estado,
        content=body.content,
        tags=body.tags,
        cliente=body.cliente,
        personas=body.personas,
        source_draft_id=body.source_draft_id,
    )


class PromoteRequest(BaseModel):
    title: str | None = None
    tipo: str | None = None
    area: str | None = None
    estado: str = "activo"
    content: str | None = None
    tags: list[str] | None = None
    cliente: str | None = None
    personas: list[str] | None = None


@router.post("/{note_id}/promote", status_code=201)
def promote_draft(note_id: str, body: PromoteRequest, scope: str = Depends(get_scope)):
    """Acepta un borrador del Inbox tal cual (o con overrides puntuales) y lo
    convierte en nota definitiva, sin tener que reenviar todo el contenido."""
    if scope != "personal":
        raise HTTPException(status_code=403, detail="Scope insuficiente")

    draft = vault_index.get(note_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Borrador no encontrado")

    if draft.metadata.fuente_inmutable:
        raise HTTPException(409, "La fuente original no se puede promover ni reescribir")

    return write_note(
        title=body.title or draft.title,
        tipo=body.tipo or draft.metadata.tipo or "nota",
        area=body.area or draft.metadata.area or "Laboral",
        estado=body.estado,
        content=body.content if body.content is not None else (draft.content or ""),
        tags=body.tags if body.tags is not None else (draft.metadata.tags or []),
        cliente=body.cliente or draft.metadata.cliente,
        personas=body.personas,
        source_draft_id=note_id,
    )


@router.get("/{note_id}", response_model=NoteResponse)
def get_note(note_id: str, scope: str = Depends(get_scope),
             actor: Literal['manual', 'assistant'] = Header('manual', alias='X-PachiMind-Actor')):
    note = vault_index.get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    if not is_visible(note, scope):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    if (actor == 'assistant' or scope == 'ai_context') and not is_ai_eligible(note):
        raise HTTPException(403, "Esta nota o sus fuentes no permiten acceso por IA")

    content, excerpt = apply_content_rules(note, scope)
    resolved = vault_index.resolve_wikilinks(note.wikilinks, scope)
    from app.core.people import revision

    return NoteResponse(
        id=note.id,
        title=note.title,
        path=note.path,
        metadata=note.metadata,
        content=content,
        excerpt=excerpt,
        resolved_links=resolved,
        revision=revision(note),
    )


class NotePatchRequest(BaseModel):
    revision: str | None = None
    tipo: str | None = None
    estado: str | None = None
    area: str | None = None
    cliente: str | None = None
    organizacion: str | None = None
    rol: str | None = None
    personas: list[str] | None = None
    proyectos: list[str] | None = None
    tags: list[str] | None = None
    sensibilidad: str | None = None
    ia_permiso: str | None = None
    revisado: bool | None = None
    content: str | None = None


@router.patch("/{note_id}", status_code=200)
def patch_note(note_id: str, body: NotePatchRequest, scope: str = Depends(get_scope)):
    if scope != "personal":
        raise HTTPException(status_code=403, detail="Scope insuficiente")

    from app.core.meeting_capture import transaction, path_for, atomic_write
    from app.core.people import node, person, require_revision
    from hashlib import sha256
    import frontmatter as fm
    with transaction():
        note = node(note_id, scope)
        if note.metadata.fuente_inmutable:
            raise HTTPException(409, "Fuente original protegida. Registrá una corrección en otra nota.")
        if person(note):
            if body.revision is None:
                raise HTTPException(428, "La edición de personas requiere revision; releé la ficha")
            require_revision(note, body.revision)
        file_path = path_for(note.path)
        raw = file_path.read_bytes()
        if not person(note) and body.revision and sha256(raw).hexdigest() != body.revision:
            raise HTTPException(409, "La nota cambió. Releé antes de editar.")
        post = fm.loads(raw.decode())
        fields = body.model_dump(exclude_none=True)
        fields.pop('revision', None)
        content = fields.pop("content", None)
        for key, value in fields.items():
            post.metadata[key] = value
        if content is not None:
            post.content = content
        atomic_write(note.path, fm.dumps(post), replace=True)
        return {"id": note_id, "path": note.path}


@router.delete("/{note_id}", status_code=200)
def remove_note(note_id: str, scope: str = Depends(get_scope)):
    if scope != "personal":
        raise HTTPException(status_code=403, detail="Scope insuficiente")

    note = vault_index.get(note_id)
    if note and note.metadata.fuente_inmutable:
        raise HTTPException(409, "Fuente original protegida. Conservá su historial.")
    if not delete_note(note_id):
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    return {"id": note_id, "deleted": True}
