from fastapi import APIRouter, Depends
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible
from app.models.filters import NoteFilters
from app.models.responses import ClientSummary

router = APIRouter(prefix="/clients", tags=["clientes"])


@router.get("", response_model=list[ClientSummary])
def list_clients(scope: str = Depends(get_scope)):
    filters = NoteFilters(tipo="cliente")
    notes = [n for n in vault_index.filter(filters) if is_visible(n, scope)]

    result = []
    for n in notes:
        client_name = n.metadata.cliente or n.title

        # contar proyectos y personas relacionadas
        project_filters = NoteFilters(tipo="proyecto", cliente=client_name)
        projects_count = len([
            p for p in vault_index.filter(project_filters) if is_visible(p, scope)
        ])

        people_filters = NoteFilters(tipo="persona", cliente=client_name)
        people_count = len([
            p for p in vault_index.filter(people_filters) if is_visible(p, scope)
        ])

        result.append(ClientSummary(
            id=n.id,
            title=n.title,
            status=n.metadata.estado,
            projects_count=projects_count,
            people_count=people_count,
        ))

    return result
