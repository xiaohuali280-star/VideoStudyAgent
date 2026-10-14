from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import TypeAdapter

from app.api import repository
from app.core.errors import StudyError
from app.db.study_repository import StudyRepository
from app.schemas.iteration import CourseStudyState, OperationRequest, StudyOperation
from app.services.operations import ensure_study_schema

router = APIRouter(prefix="/api/tasks", tags=["study"])


def study_repository(request):
    repo = repository(request)
    ensure_study_schema(request.app.state.settings, repo.engine)
    return StudyRepository(repo.engine)


@router.get("/{task_id}/study-state", response_model=CourseStudyState)
def state(request: Request, task_id: UUID):
    return study_repository(request).state(task_id)


@router.get("/{task_id}/operations", response_model=list[StudyOperation])
def operations(request: Request, task_id: UUID):
    return study_repository(request).operations(task_id)


@router.get("/{task_id}/operations/{operation_id}", response_model=StudyOperation)
def operation(request: Request, task_id: UUID, operation_id: UUID):
    return study_repository(request).operation(task_id, operation_id)


@router.post("/{task_id}/operations", response_model=StudyOperation, status_code=202)
def submit(
    request: Request,
    task_id: UUID,
    action: OperationRequest,
    idempotency_key: str = Header(min_length=1, max_length=200),
):
    if action.kind not in {"generate_notes", "generate_quiz"}:
        raise StudyError("OPERATION_UNAVAILABLE", "此入口仅支持补生成笔记或自测。", 422)
    repo = study_repository(request)
    return repo.enqueue(
        task_id, TypeAdapter(OperationRequest).validate_python(action), idempotency_key
    )
