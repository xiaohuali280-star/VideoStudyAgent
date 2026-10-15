from uuid import UUID

from fastapi import APIRouter, Request

from app.db.review_repository import ReviewRepository
from app.routes.study import study_repository
from app.schemas.review import ReviewReport

router = APIRouter(prefix="/api/tasks", tags=["reviews"])


@router.get("/{task_id}/operations/{operation_id}/reviews", response_model=list[ReviewReport])
def reviews(request: Request, task_id: UUID, operation_id: UUID):
    repo = study_repository(request)
    return ReviewRepository(repo.engine).reports(task_id, operation_id)
