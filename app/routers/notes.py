from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.config import settings
from app.core.note_writer import TIPO_FOLDER, write_note, delete_note
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible, apply_content_rules
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
def get_note(note_id: str, scope: str = Depends(get_scope)):
    note = vault_index.get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    if not is_visible(note, scope):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    content, excerpt = apply_content_rules(note, scope)
    resolved = vault_index.resolve_wikilinks(note.wikilinks)

    return NoteResponse(
        id=note.id,
        title=note.title,
        path=note.path,
        metadata=note.metadata,
        content=content,
        excerpt=excerpt,
        resolved_links=resolved,
    )


class NotePatchRequest(BaseModel):
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

    note = vault_index.get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    if note.metadata.fuente_inmutable:
        raise HTTPException(409, "Fuente original protegida. Registrá una corrección en otra nota.")
    vault_root = Path(settings.vault_path)
    file_path = vault_root / note.path

    import frontmatter as fm
    post = fm.load(str(file_path))

    fields = body.model_dump(exclude_none=True)
    content = fields.pop("content", None)

    for k, v in fields.items():
        post.metadata[k] = v

    if content is not None:
        post.content = content

    file_path.write_text(fm.dumps(post), encoding="utf-8")
    vault_index.rebuild_file(file_path)

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
