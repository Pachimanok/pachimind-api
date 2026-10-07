from fastapi import APIRouter, Depends
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.middleware.permissions import is_visible
from app.models.filters import NoteFilters
from app.models.note import NoteSummary

router = APIRouter(prefix="/actions", tags=["acciones"])

PENDING_ESTADOS = {"para_revisar", "pendiente", "en_proceso", "inbox"}


@router.get("/pending", response_model=list[NoteSummary])
def pending_actions(
    area: str | None = None,
    proyecto: str | None = None,
    prioridad: str | None = None,
    scope: str = Depends(get_scope),
):
    filters = NoteFilters(tipo="accion", area=area, proyecto=proyecto, prioridad=prioridad)
    notes = [n for n in vault_index.filter(filters)
             if is_visible(n, scope) and n.metadata.estado in PENDING_ESTADOS]

    # orden: alta primero, luego por fecha
    priority_order = {"alta": 0, "media": 1, "baja": 2}
    notes.sort(key=lambda n: (
        priority_order.get(n.metadata.prioridad or "baja", 99),
        n.metadata.fecha or "",
    ))

    return [
        NoteSummary(
            id=n.id, title=n.title, path=n.path,
            tipo=n.metadata.tipo, estado=n.metadata.estado,
            area=n.metadata.area, sensibilidad=n.metadata.sensibilidad,
            prioridad=n.metadata.prioridad, revisado=n.metadata.revisado,
        )
        for n in notes
    ]

# Explicit user actions only; AI proposals stay in the Inbox until approved.
from app.core.todo import CreateTask, UpdateTask, list_tasks, create_task, update_task
from fastapi import HTTPException


def personal(scope):
    if scope != 'personal':raise HTTPException(403,'TODO requiere acceso personal')


@router.get('/todo')
def todo_list(scope: str = Depends(get_scope)):
    personal(scope)
    return list_tasks()


@router.post('/todo', status_code=201)
def todo_create(body: CreateTask, scope: str = Depends(get_scope)):
    personal(scope)
    return create_task(body)


@router.patch('/todo/{note_id}')
def todo_update(note_id: str, body: UpdateTask, scope: str = Depends(get_scope)):
    personal(scope)
    return update_task(note_id,body)
