from fastapi import APIRouter, Depends, Query
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible
from app.models.filters import NoteFilters
from app.models.responses import SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["búsqueda"])


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=2),
    area: str | None = None,
    tipo: str | None = None,
    estado: str | None = None,
    sensibilidad: str | None = None,
    include_content: bool = False,
    limit: int = Query(20, ge=1, le=50),
    scope: str = Depends(get_scope),
):
    filters = NoteFilters(area=area, tipo=tipo, estado=estado, sensibilidad=sensibilidad)
    scored = vault_index.search(q, filters, limit=limit * 2)  # busca más, filtra permisos después

    results = []
    for note, score in scored:
        if not is_visible(note, scope):
            continue
        excerpt = note.content_text[:300] + "..." if len(note.content_text) > 300 else note.content_text
        results.append(SearchResult(
            id=note.id,
            title=note.title,
            type=note.metadata.tipo,
            area=note.metadata.area,
            excerpt=excerpt,
            path=note.path,
            score=round(score, 2),
        ))
        if len(results) >= limit:
            break

    return SearchResponse(query=q, total=len(results), results=results)
