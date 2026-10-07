from fastapi import APIRouter, Depends, HTTPException
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_ai_eligible
from app.models.filters import AIContextRequest
from app.models.responses import AIContextResponse, SearchResult

router = APIRouter(prefix="/ai", tags=["IA"])


@router.post("/context", response_model=AIContextResponse)
def ai_context(body: AIContextRequest, scope: str = Depends(get_scope)):
    if scope not in ("personal", "ai_context"):
        raise HTTPException(status_code=403, detail="Scope insuficiente para consultas de IA")

    # Filtra por los filtros del request
    candidates = vault_index.filter(body.filters)

    # Aplica reglas estrictas de IA (hardcodeadas, no configurables)
    candidates = [n for n in candidates if is_ai_eligible(n)]

    # Rankea por relevancia al query
    from rapidfuzz import fuzz
    q = body.query.lower()
    scored = []
    for note in candidates:
        score = fuzz.partial_ratio(q, f"{note.title} {note.content_text}".lower())
        if score >= 45:
            scored.append((note, score))
    scored.sort(key=lambda x: -x[1])

    results = []
    for note, score in scored[: body.max_results]:
        excerpt = note.content_text[:400] + "..." if len(note.content_text) > 400 else note.content_text
        results.append(SearchResult(
            id=note.id,
            title=note.title,
            type=note.metadata.tipo,
            area=note.metadata.area,
            excerpt=excerpt,
            path=note.path,
            score=round(score / 100, 2),
        ))

    return AIContextResponse(query=body.query, results=results)
