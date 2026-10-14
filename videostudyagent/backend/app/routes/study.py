from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from pydantic import TypeAdapter

from app.api import repository
from app.core.errors import StudyError
from app.db.study_repository import StudyRepository
from app.schemas.iteration import (
    CourseStudyState,
    OperationRequest,
    OperationUsage,
    QuizBatch,
    StudyOperation,
)
from app.schemas.study import QuizDocument, QuizDocumentV11
from app.services.operations import ensure_study_schema
from app.services.study_versions import VersionReader

router = APIRouter(prefix="/api/tasks", tags=["study"])


def study_repository(request):
    repo = repository(request)
    ensure_study_schema(request.app.state.settings, repo.engine)
    return StudyRepository(repo.engine)


@router.get("/{task_id}/study-state", response_model=CourseStudyState)
def state(request: Request, task_id: UUID):
    return study_repository(request).state(task_id)


@router.get("/{task_id}/operations", response_model=list[StudyOperation])
def operations(
    request: Request,
    task_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return study_repository(request).operations(task_id, limit, offset)


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
        task_id,
        TypeAdapter(OperationRequest).validate_python(action),
        idempotency_key,
        usage=OperationUsage(
            request_limit=request.app.state.settings.llm_max_requests,
            token_limit=request.app.state.settings.llm_total_tokens,
        ),
    )


@router.get("/{task_id}/quiz-batches", response_model=list[QuizBatch])
def batches(
    request: Request,
    task_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return study_repository(request).quiz_batches(task_id, limit=limit, offset=offset)


@router.get("/{task_id}/quiz-batches/{batch_id}", response_model=QuizDocument | QuizDocumentV11)
def batch_document(request: Request, task_id: UUID, batch_id: UUID):
    batch = study_repository(request).batch(task_id, batch_id)
    return VersionReader(request.app.state.settings.data_dir).quiz(batch)


@router.post(
    "/{task_id}/operations/{operation_id}/retry", response_model=StudyOperation, status_code=202
)
def retry_operation(request: Request, task_id: UUID, operation_id: UUID):
    repo = study_repository(request)
    if repo.operation(task_id, operation_id).request.kind == "initial_study":
        raise StudyError("STUDY_CONFLICT", "初次处理请使用课程重试入口。", 409)
    return repo.retry(task_id, operation_id)


@router.post("/{task_id}/operations/{operation_id}/cancel", response_model=StudyOperation)
def cancel_operation(request: Request, task_id: UUID, operation_id: UUID):
    return study_repository(request).request_cancel(task_id, operation_id)
