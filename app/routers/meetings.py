from fastapi import APIRouter, Depends, HTTPException
from app.middleware.auth import get_scope
from app.models.meetings import MeetingCreate, ProposalBatch, ProposalReview
from app.core import meeting_capture as capture

router=APIRouter(prefix='/projects',tags=['memoria-reuniones'])


def personal(scope: str = Depends(get_scope)):
    if scope!='personal':raise HTTPException(403,'Se requiere scope personal')
    return scope


@router.post('/{project_id}/meetings',status_code=201)
def create_meeting(project_id: str,body: MeetingCreate,scope: str = Depends(personal)):
    return capture.create_meeting(project_id,body)


@router.get('/{project_id}/meetings/{meeting_id}')
def get_meeting(project_id: str,meeting_id: str,for_ai: bool=False,scope: str=Depends(personal)):
    return capture.get_meeting(project_id,meeting_id,for_ai)


@router.get('/{project_id}/meetings/{meeting_id}/proposals')
def proposals(project_id: str,meeting_id: str,scope: str=Depends(personal)):
    return capture.list_proposals(project_id,meeting_id)


@router.post('/{project_id}/meetings/{meeting_id}/proposals',status_code=201)
def create_proposals(project_id: str,meeting_id: str,body: ProposalBatch,scope: str=Depends(personal)):
    return capture.create_proposals(project_id,meeting_id,body)


@router.post('/{project_id}/meetings/{meeting_id}/proposals/{proposal_id}/review')
def review(project_id: str,meeting_id: str,proposal_id: str,body: ProposalReview,scope: str=Depends(personal)):
    return capture.review_proposal(project_id,meeting_id,proposal_id,body.action)
