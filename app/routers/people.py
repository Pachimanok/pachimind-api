from fastapi import APIRouter, Depends
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible
from app.models.filters import NoteFilters
from app.models.note import NoteSummary

router = APIRouter(prefix="/people", tags=["personas"])


@router.get("", response_model=list[NoteSummary])
def list_people(
    area: str | None = None,
    organizacion: str | None = None,
    cliente: str | None = None,
    scope: str = Depends(get_scope),
):
    filters = NoteFilters(tipo="persona", area=area, organizacion=organizacion, cliente=cliente)
    notes = [n for n in vault_index.filter(filters) if is_visible(n, scope)]

    return [
        NoteSummary(
            id=n.id, title=n.title, path=n.path,
            tipo=n.metadata.tipo, estado=n.metadata.estado,
            area=n.metadata.area, sensibilidad=n.metadata.sensibilidad,
            prioridad=n.metadata.prioridad, revisado=n.metadata.revisado,
        )
        for n in notes
    ]
