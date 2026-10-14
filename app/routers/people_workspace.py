"""People workspace. Existing /people list remains compatible."""
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from app.core import people
from app.middleware.auth import get_scope
from app.models.people import PersonCreate, PersonUpdate, PersonProposal, LinkCommand, ReviewCommand, KnowledgeDraft, UndoCommand
from app.models.responses import PersonProfile, PeopleDirectory, PendingChanges, OperationResult

router = APIRouter(tags=['personas y conocimiento'])


def context(scope: str = Depends(get_scope), actor: Literal['manual', 'assistant'] = Header('manual', alias='X-PachiMind-Actor')):
    return scope, actor == 'assistant' or scope == 'ai_context'


def writer(ctx):
    if ctx[0] != 'personal':
        raise HTTPException(403, 'La escritura requiere la credencial personal; el MCP además exige OAuth write')


@router.get('/people/directory', response_model=PeopleDirectory)
def directory(q: str = Query('', max_length=200), ambito: str | None = None,
              view: Literal['incomplete', 'pending', 'unconnected', 'no_outgoing', 'duplicates'] | None = None,
              page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), ctx=Depends(context)):
    return people.directory(*ctx, query=q, ambito=ambito, view=view, page=page, per_page=per_page)


@router.get('/people/changes', response_model=PendingChanges)
def changes(note_id: str | None = None, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), ctx=Depends(context)):
    return people.pending(*ctx, note_id=note_id, page=page, per_page=per_page)


@router.post('/people/drafts', response_model=OperationResult, status_code=201)
def create(body: PersonCreate, ctx=Depends(context)):
    writer(ctx)
    return people.create_person(body, *ctx)


@router.get('/people/{person_id}/profile', response_model=PersonProfile)
def profile(person_id: str, ctx=Depends(context)):
    return people.profile(person_id, *ctx)


@router.patch('/people/{person_id}/profile', response_model=OperationResult)
def edit(person_id: str, body: PersonUpdate, ctx=Depends(context)):
    writer(ctx)
    return people.update_person(person_id, body, *ctx)


@router.post('/people/{person_id}/proposals', status_code=201)
def propose(person_id: str, body: PersonProposal, ctx=Depends(context)):
    writer(ctx)
    return people.propose_person(person_id, body, *ctx)


@router.post('/vault/relations/proposals', status_code=201)
def propose_links(body: LinkCommand, ctx=Depends(context)):
    writer(ctx)
    return people.propose_links(body, *ctx)


@router.post('/people/changes/{change_id}/review', response_model=OperationResult)
def review(change_id: str, body: ReviewCommand, ctx=Depends(context)):
    writer(ctx)
    return people.review(change_id, body, *ctx)


@router.post('/notes/knowledge-drafts', response_model=OperationResult, status_code=201)
def knowledge(body: KnowledgeDraft, ctx=Depends(context)):
    writer(ctx)
    return people.knowledge(body, *ctx)


@router.get('/vault/relations')
def graph(ctx=Depends(context)):
    rows, _, notes = people.relation_rows(*ctx)
    return {'nodes': [{'id': n.id, 'title': n.title, 'path': n.path, 'tipo': n.metadata.tipo} for n in notes.values()],
            'relations': rows}


@router.post('/people/history/{history_id}/undo', response_model=OperationResult)
def undo(history_id: str, body: UndoCommand, ctx=Depends(context)):
    writer(ctx)
    return people.undo(history_id, body, *ctx)
