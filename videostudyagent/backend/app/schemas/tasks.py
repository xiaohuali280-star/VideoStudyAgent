from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from app.schemas.common import (
    ContentHash,
    ContractModel,
    DocumentModel,
    ErrorInfo,
    Milliseconds,
    NonEmptyText,
    PositiveInt,
)
from app.schemas.study import NotesDocument, QuizDocument, StudyOptions, Transcript

TaskStatus = Literal["queued", "running", "succeeded", "failed"]
StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]
ToolName = Literal[
    "load_subtitles", "extract_audio", "transcribe_audio", "generate_notes", "generate_quiz"
]
ArtifactKind = Literal["audio", "transcript", "notes", "quiz"]
ExportFormat = Literal["notes.md", "quiz.md", "quiz.json", "transcript.json", "transcript.srt"]


class StoredObject(ContractModel):
    """Internal storage metadata; never a public file path parameter."""

    storage_key: NonEmptyText
    sha256: ContentHash

    @field_validator("storage_key")
    @classmethod
    def check_relative_key(cls, value: str) -> str:
        parts = value.split("/")
        if (
            PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in value
            or ":" in value
        ):
            raise ValueError("Storage keys must be relative POSIX paths without traversal")
        return value


class InputAsset(StoredObject):
    id: UUID
    task_id: UUID
    kind: Literal["video", "subtitle"]
    original_name: NonEmptyText
    size_bytes: PositiveInt
    duration_ms: PositiveInt | None = None


class ArtifactSummary(DocumentModel):
    id: UUID
    task_id: UUID
    kind: ArtifactKind
    created_at: AwareDatetime


class Artifact(StoredObject):
    schema_version: Literal["1.0"] = "1.0"
    id: UUID
    task_id: UUID
    kind: ArtifactKind
    cache_key: ContentHash | None = None
    created_at: AwareDatetime


class CacheEntry(StoredObject):
    key: ContentHash
    kind: ArtifactKind
    schema_version: Literal["1.0"] = "1.0"
    created_at: AwareDatetime


class Task(DocumentModel):
    id: UUID
    title: Annotated[str, Field(min_length=1, max_length=200)]
    options: StudyOptions
    status: TaskStatus = "queued"
    current_step: ToolName | None = None
    attempt: PositiveInt = 1
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error: ErrorInfo | None = None


class TaskStep(DocumentModel):
    id: UUID
    task_id: UUID
    attempt: PositiveInt
    tool_name: ToolName
    status: StepStatus = "pending"
    cache_key: ContentHash | None = None
    artifact_id: UUID | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error: ErrorInfo | None = None


class ToolCallRecord(ContractModel):
    task_id: UUID
    attempt: PositiveInt
    sequence: PositiveInt
    tool_name: ToolName
    status: StepStatus
    artifact_id: UUID | None = None
    duration_ms: Milliseconds


class TaskDetail(DocumentModel):
    task: Task
    steps: list[TaskStep] = Field(default_factory=list)
    available_artifacts: list[ArtifactSummary] = Field(default_factory=list)


class StudyResult(DocumentModel):
    task_id: UUID
    available_artifacts: list[ArtifactSummary] = Field(default_factory=list)
    transcript: Transcript | None = None
    notes: NotesDocument | None = None
    quiz: QuizDocument | None = None
