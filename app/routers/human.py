"""Human-only queue. MCP/assistant actors retain their original restrictions."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from app.middleware.auth import get_scope
from app.core import human_review as human

router = APIRouter(prefix='/human', tags=['humano'])


def owner(scope: str = Depends(get_scope), actor: Literal['manual', 'assistant'] = Header('manual', alias='X-PachiMind-Actor')):
    if scope != 'personal' or actor != 'manual':raise HTTPException(403, 'Esta revisión requiere la sesión humana del propietario')


@router.get('/summary', dependencies=[Depends(owner)])
def summary(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    data = human.queue(per_page=1)
    return {k: data[k] for k in ['total_pending', 'counts']}


@router.get('/queue', dependencies=[Depends(owner)])
def queue(response: Response, kind: Literal['all', 'links', 'person', 'meeting', 'note'] = 'all',
          q: str = Query('', max_length=200), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    response.headers['Cache-Control'] = 'no-store'
    return human.queue(kind, q, page, per_page)


@router.get('/items/{kind}/{item_id}', dependencies=[Depends(owner)])
def detail(kind: human.Kind, item_id: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return human.detail(kind, item_id)


@router.post('/items/{kind}/{item_id}/decision', dependencies=[Depends(owner)])
def decide(kind: human.Kind, item_id: str, command: human.Decision, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return human.decide(kind, item_id, command)


@router.get('/requests/{request_id}', dependencies=[Depends(owner)])
def receipt(request_id: UUID, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return human.request_result(str(request_id))
