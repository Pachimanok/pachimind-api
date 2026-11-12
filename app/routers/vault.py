from fastapi import APIRouter, Depends, Header, Query, Response, HTTPException
from typing import Literal
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible
from app.models.responses import VaultStats, VaultActivity, ActivityNote

router = APIRouter(prefix="/vault", tags=["vault"])


@router.get('/graph')
def vault_graph(response: Response, limit: int = Query(2000, ge=1, le=3000),
                focus: str | None = Query(None, max_length=300),
                scope: str = Depends(get_scope),
                actor: Literal['manual', 'assistant'] = Header('manual', alias='X-PachiMind-Actor')):
    from app.core.associations import AssociationGraph, declared_ambitos
    graph = AssociationGraph(scope, actor == 'assistant' or scope == 'ai_context')
    response.headers['Cache-Control'] = 'no-store'
    if focus and focus not in graph.notes: raise HTTPException(404, 'Nota no disponible')
    candidates = ({focus, *graph.neighbors[focus]} if focus else set(graph.notes))
    ordered = sorted(candidates, key=lambda i: (i != focus, -len(graph.neighbors[i]), graph.notes[i].title.casefold(), i))
    chosen = set(ordered[:limit])
    nodes = [{'id': i, 'title': graph.notes[i].title, 'path': graph.notes[i].path,
              'tipo': graph.notes[i].metadata.tipo, 'ambitos': declared_ambitos(graph.notes[i])}
             for i in ordered[:limit]]
    edges = [{'source': r['source_id'], 'target': r['target_id'], 'relation': r['relation']}
             for r in graph.rows if r['source_id'] in chosen and r['target_id'] in chosen]
    return {'nodes': nodes, 'edges': edges, 'total_visible': len(graph.notes), 'total_matching': len(candidates),
            'returned': len(nodes), 'truncated': len(candidates) > limit, 'focus': focus,
            'scope_note': 'Sólo notas y vínculos guardados visibles con tus permisos. Las sugerencias y referencias sin resolver no se dibujan. Los ámbitos son clasificación, no vínculos entre notas.'}


@router.get("/stats", response_model=VaultStats)
def vault_stats(scope: str = Depends(get_scope)):
    return VaultStats(**vault_index.stats([n for n in vault_index.all() if is_visible(n, scope)]))


@router.get("/activity", response_model=VaultActivity)
def vault_activity(scope: str = Depends(get_scope)):
    notes = [n for n in vault_index.all() if is_visible(n, scope)]

    def to_activity(n):
        return ActivityNote(
            id=n.id, title=n.title,
            tipo=n.metadata.tipo, area=n.metadata.area,
            last_modified=n.last_modified,
        )

    sorted_all = sorted(notes, key=lambda n: n.last_modified, reverse=True)

    recently_added = [to_activity(n) for n in sorted_all[:6]]

    ai_notes = sorted(
        [n for n in notes if n.metadata.origen == 'inbox_ia'],
        key=lambda n: n.last_modified, reverse=True,
    )
    processed_by_ai = [to_activity(n) for n in ai_notes[:6]]

    pending = sorted(
        [n for n in notes
         if not n.metadata.revisado
         and n.metadata.estado not in ('borrador', 'archivado')],
        key=lambda n: n.last_modified, reverse=True,
    )
    pending_review = [to_activity(n) for n in pending[:6]]

    return VaultActivity(
        recently_added=recently_added,
        processed_by_ai=processed_by_ai,
        pending_review=pending_review,
    )
