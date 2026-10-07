from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core import notebooklm_importer as nlm
from app.core.inbox_writer import write_draft
from app.middleware.auth import get_scope
from app.models.responses import (
    NotebookLMImportResponse,
    NotebookLMImportResult,
    NotebookLMNotebook,
    NotebookLMSource,
)

router = APIRouter(prefix="/notebooklm", tags=["notebooklm"])


def _require_scope(scope: str):
    if scope not in ("personal", "ai_context"):
        raise HTTPException(status_code=403, detail="Scope insuficiente")


@router.get("/notebooks", response_model=list[NotebookLMNotebook])
def list_notebooks(scope: str = Depends(get_scope)):
    _require_scope(scope)
    try:
        notebooks = nlm.list_notebooks()
    except nlm.NotebookLMError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return [NotebookLMNotebook(id=n["id"], title=n["title"]) for n in notebooks]


@router.get("/notebooks/{notebook_id}/sources", response_model=list[NotebookLMSource])
def list_sources(notebook_id: str, scope: str = Depends(get_scope)):
    _require_scope(scope)
    try:
        sources = nlm.list_sources(notebook_id)
    except nlm.NotebookLMError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return [
        NotebookLMSource(id=s["id"], title=s["title"], type=s["type"], status=s["status"])
        for s in sources
    ]


class ImportSource(BaseModel):
    source_id: str
    title: str
    tags: list[str] = []
    cliente: str | None = None
    proyecto: str | None = None


class ImportRequest(BaseModel):
    notebook_id: str
    area: str = "Laboral"
    sources: list[ImportSource]


@router.post("/import", response_model=NotebookLMImportResponse, status_code=201)
def import_meetings(body: ImportRequest, scope: str = Depends(get_scope)):
    _require_scope(scope)

    results: list[NotebookLMImportResult] = []
    for src in body.sources:
        try:
            transcript = nlm.get_source_fulltext(body.notebook_id, src.source_id)
        except nlm.NotebookLMError as e:
            results.append(NotebookLMImportResult(
                source_id=src.source_id, title=src.title, ok=False, error=str(e),
            ))
            continue

        if not transcript.strip():
            results.append(NotebookLMImportResult(
                source_id=src.source_id, title=src.title, ok=False, error="Transcripción vacía",
            ))
            continue

        content = (
            f"> Importado desde NotebookLM. Notebook `{body.notebook_id}` / fuente `{src.source_id}`.\n\n"
            f"## Transcripción completa\n\n{transcript}\n"
        )
        draft = write_draft(
            title=src.title,
            content=content,
            area=body.area,
            tipo="reunion",
            cliente=src.cliente,
            proyecto=src.proyecto,
            tags=["notebooklm", *src.tags],
        )
        results.append(NotebookLMImportResult(
            source_id=src.source_id, title=src.title, ok=True, id=draft["id"], path=draft["path"],
        ))

    return NotebookLMImportResponse(results=results)
