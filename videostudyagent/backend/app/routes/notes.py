from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field

from app.adapters.grounding import validate_notes
from app.routes.study import study_repository
from app.schemas.common import ContractModel
from app.schemas.iteration import (
    CourseNotePreferences,
    CourseStudyState,
    NotePreferences,
    NotesRevision,
)
from app.schemas.study import NotesDocument, NotesDocumentV11
from app.schemas.video_context import NotesDocumentV12
from app.services.study_versions import VersionReader

router = APIRouter(prefix="/api/tasks", tags=["notes"])


class PreferencesUpdate(ContractModel):
    expected_revision: int = Field(ge=0, strict=True)
    preferences: NotePreferences


class PublishNotes(ContractModel):
    expected_current_id: UUID | None


@router.get("/{task_id}/note-preferences", response_model=CourseNotePreferences | None)
def preferences(request: Request, task_id: UUID):
    return study_repository(request).preferences(task_id)


@router.put("/{task_id}/note-preferences", response_model=CourseNotePreferences)
def save_preferences(request: Request, task_id: UUID, body: PreferencesUpdate):
    return study_repository(request).save_preferences(
        task_id, body.preferences, expected_revision=body.expected_revision
    )


@router.get("/{task_id}/notes-revisions", response_model=list[NotesRevision])
def revisions(
    request: Request,
    task_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return study_repository(request).note_revisions(task_id, limit=limit, offset=offset)


@router.get(
    "/{task_id}/notes-revisions/{revision_id}",
    response_model=NotesDocument | NotesDocumentV11 | NotesDocumentV12,
)
def revision_document(request: Request, task_id: UUID, revision_id: UUID):
    record = study_repository(request).notes(task_id, revision_id)
    return VersionReader(request.app.state.settings.data_dir).notes(record)


@router.post("/{task_id}/notes-revisions/{revision_id}/apply", response_model=CourseStudyState)
def apply_revision(request: Request, task_id: UUID, revision_id: UUID, body: PublishNotes):
    repo = study_repository(request)
    record = repo.notes(task_id, revision_id)
    reader = VersionReader(request.app.state.settings.data_dir)
    if record.context_snapshot_id:
        from app.db.context_repository import VideoContextRepository
        from app.services.source_context import validate_context_document

        validate_context_document(
            reader.notes(record),
            VideoContextRepository(repo.engine).get(task_id, record.context_snapshot_id),
            require_coverage=True,
        )
    else:
        validate_notes(
            reader.notes(record),
            reader.transcript(repo.snapshot(task_id, record.transcript_snapshot_id)),
        )
    return repo.publish_notes(task_id, revision_id, expected_current_id=body.expected_current_id)


@router.post("/{task_id}/notes-revisions/{revision_id}/discard", response_model=NotesRevision)
def discard_revision(request: Request, task_id: UUID, revision_id: UUID):
    return study_repository(request).discard_notes(task_id, revision_id)
