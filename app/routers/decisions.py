from fastapi import APIRouter, Depends
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible
from app.models.filters import NoteFilters
from app.models.note import NoteSummary

router = APIRouter(prefix="/decisions", tags=["decisiones"])


@router.get("", response_model=list[NoteSummary])
def list_decisions(
    area: str | None = None,
    proyecto: str | None = None,
    fecha_desde: str | None = None,
    scope: str = Depends(get_scope),
):
    filters = NoteFilters(tipo="decision", area=area, proyecto=proyecto)
    notes = [n for n in vault_index.filter(filters) if is_visible(n, scope)]

    if fecha_desde:
        notes = [n for n in notes
                 if n.metadata.fecha and n.metadata.fecha >= fecha_desde]

    notes.sort(key=lambda n: n.metadata.fecha or "", reverse=True)

    return [
        NoteSummary(
            id=n.id, title=n.title, path=n.path,
            tipo=n.metadata.tipo, estado=n.metadata.estado,
            area=n.metadata.area, sensibilidad=n.metadata.sensibilidad,
            prioridad=n.metadata.prioridad, revisado=n.metadata.revisado,
        )
        for n in notes
    ]
