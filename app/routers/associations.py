"""Read-only note connections; assistant requests retain AI restrictions."""
from typing import Literal
from fastapi import APIRouter, Depends, Header, Query, Response
from app.core.associations import AssociationGraph
from app.middleware.auth import get_scope

router = APIRouter(prefix='/vault/associations', tags=['asociaciones'])


def graph(scope: str = Depends(get_scope),
          actor: Literal['manual', 'assistant'] = Header('manual', alias='X-PachiMind-Actor')):
    return AssociationGraph(scope, actor == 'assistant' or scope == 'ai_context')


@router.get('')
def audit(response: Response, view: Literal['all', 'orphans', 'no_general', 'unresolved'] = 'orphans',
          q: str = Query('', max_length=200), ambito: str = Query('', max_length=200),
          page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
          context=Depends(graph)):
    response.headers['Cache-Control'] = 'no-store'
    return context.audit(view, q, ambito, page, per_page)


@router.get('/{note_id}')
def detail(note_id: str, response: Response, context=Depends(graph)):
    response.headers['Cache-Control'] = 'no-store'
    return context.detail(note_id)
