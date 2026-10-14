from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from pydantic import TypeAdapter

from app.api import repository
from app.core.errors import StudyError
from app.db.study_repository import StudyRepository
from app.schemas.iteration import (
    Conversation,
    ConversationMessage,
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
    if action.kind not in {"generate_notes", "generate_quiz", "chat_reply", "revise_notes"}:
        raise StudyError("OPERATION_UNAVAILABLE", "此入口仅支持补生成笔记或自测。", 422)
    repo = study_repository(request)
    if action.kind == "revise_notes":
        from app.services.note_revisions import revision_context

        revision_context(repo, VersionReader(request.app.state.settings.data_dir), task_id, action)
    if action.kind == "chat_reply":
        from app.services.note_chat import chat_context

        chat_context(repo, VersionReader(request.app.state.settings.data_dir), task_id, action)
    operation = repo.enqueue(
        task_id,
        TypeAdapter(OperationRequest).validate_python(action),
        idempotency_key,
        usage=OperationUsage(
            request_limit=request.app.state.settings.llm_max_requests,
            token_limit=request.app.state.settings.llm_total_tokens,
        ),
    )

    if action.kind == "chat_reply":
        from app.services.note_chat import user_message

        user_message(repo, operation)
    return operation


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


@router.get("/{task_id}/conversations", response_model=list[Conversation])
def conversations(request: Request, task_id: UUID):
    return study_repository(request).conversations(task_id)


@router.post("/{task_id}/conversations", response_model=Conversation, status_code=201)
def create_conversation(request: Request, task_id: UUID):
    return study_repository(request).create_conversation(task_id)


@router.get(
    "/{task_id}/conversations/{conversation_id}/messages", response_model=list[ConversationMessage]
)
def conversation_messages(
    request: Request,
    task_id: UUID,
    conversation_id: UUID,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    return study_repository(request).messages(
        task_id, conversation_id, after_sequence=after_sequence, limit=limit
    )
