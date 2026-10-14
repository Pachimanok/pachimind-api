from fastapi import APIRouter, Depends
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible
from app.models.responses import VaultStats, VaultActivity, ActivityNote

router = APIRouter(prefix="/vault", tags=["vault"])


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
