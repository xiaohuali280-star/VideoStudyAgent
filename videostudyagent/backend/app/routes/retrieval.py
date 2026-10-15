from uuid import UUID

from fastapi import APIRouter, Request

from app.api import repository
from app.schemas.retrieval import EvidenceQuery, EvidenceSearchResult
from app.services.retrieval import retrieve

router = APIRouter(prefix="/api/tasks", tags=["retrieval"])


@router.post("/{task_id}/evidence/search", response_model=EvidenceSearchResult)
def search(request: Request, task_id: UUID, query: EvidenceQuery):
    repo = repository(request)
    repo.get(task_id)
    return retrieve(repo, request.app.state.settings.data_dir, task_id, query)
