from fastapi import APIRouter, Depends, Query
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible
from app.models.filters import NoteFilters
from app.models.note import NoteSummary
from app.models.responses import ProjectMemory

router = APIRouter(prefix="/projects", tags=["proyectos"])

ACTIVE_ESTADOS = {"activo", "en_proceso", "en_revision"}


@router.get("/active", response_model=list[NoteSummary])
def active_projects(
    area: str | None = None,
    cliente: str | None = None,
    prioridad: str | None = None,
    scope: str = Depends(get_scope),
):
    filters = NoteFilters(tipo="proyecto", area=area, cliente=cliente, prioridad=prioridad)
    notes = vault_index.filter(filters)
    notes = [n for n in notes
             if is_visible(n, scope) and n.metadata.estado in ACTIVE_ESTADOS]
    notes.sort(key=lambda n: n.metadata.prioridad or "z")

    return [
        NoteSummary(
            id=n.id, title=n.title, path=n.path,
            tipo=n.metadata.tipo, estado=n.metadata.estado,
            area=n.metadata.area, sensibilidad=n.metadata.sensibilidad,
            prioridad=n.metadata.prioridad, revisado=n.metadata.revisado,
        )
        for n in notes
    ]


@router.get('/memory', response_model=list[NoteSummary])
def memory_projects(scope: str = Depends(get_scope)):
    from fastapi import HTTPException
    from app.core.project_memory import eligible
    if scope not in {'personal', 'ai_context'}:
        raise HTTPException(403, 'Scope insuficiente')
    notes = sorted((n for n in vault_index.all() if n.metadata.tipo == 'proyecto'
                    and eligible(n, scope, scope == 'ai_context')), key=lambda n: n.title.casefold())
    return [NoteSummary(id=n.id, title=n.title, path=n.path, tipo=n.metadata.tipo,
            estado=n.metadata.estado, area=n.metadata.area, sensibilidad=n.metadata.sensibilidad,
            prioridad=n.metadata.prioridad, revisado=n.metadata.revisado) for n in notes]


@router.get('/{project_id}/memory', response_model=ProjectMemory)
def project_memory(project_id: str, for_ai: bool = False, scope: str = Depends(get_scope)):
    from fastapi import HTTPException
    from app.core.project_memory import eligible, build_memory
    if scope not in {'personal', 'ai_context'}:
        raise HTTPException(403, 'Scope insuficiente')
    for_ai = for_ai or scope == 'ai_context'
    project = vault_index.get(project_id)
    if not project or project.metadata.tipo != 'proyecto' or not eligible(project, scope, for_ai):
        raise HTTPException(404, 'Proyecto no disponible')
    return build_memory(project, vault_index.all(), scope, for_ai)


@router.get('/{project_id}/memory.md')
def project_memory_markdown(project_id: str, scope: str = Depends(get_scope)):
    from fastapi.responses import PlainTextResponse
    from app.core.project_memory import as_markdown
    memory = project_memory(project_id, for_ai=True, scope=scope)
    return PlainTextResponse(as_markdown(memory), media_type='text/markdown',
                             headers={'Cache-Control': 'no-store'})
