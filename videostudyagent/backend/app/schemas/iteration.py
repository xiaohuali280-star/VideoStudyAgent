"""Version 1.1 foundation; legacy version 1.0 documents remain unchanged."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, StrictBool, model_validator

from app.schemas.common import ContentHash, ContractModel, ErrorInfo, PositiveInt, SegmentId
from app.schemas.study import (
    Difficulty,
    LanguageCode,
    NotesDocument,
    QuizDocumentV11,
    SourceEvidence,
    StudyOptions,
)
from app.schemas.tasks import StoredObject

ShortText = Annotated[str, Field(strict=True, min_length=1, max_length=2000)]
Counter = Annotated[int, Field(strict=True, ge=0)]
Five = Annotated[int, Field(strict=True, ge=5, le=5)]


class IterationDocument(ContractModel):
    schema_version: Literal["1.1"] = "1.1"


class FrozenOptions(ContractModel):
    model_config = ConfigDict(frozen=True)


class ProcessingOptions(FrozenOptions):
    generate_notes: StrictBool = True
    generate_quiz: StrictBool = True

    def required_artifacts(self):
        return (
            {"transcript"}
            | ({"notes"} if self.generate_notes else set())
            | ({"quiz"} if self.generate_quiz else set())
        )


class QuizGenerationOptions(FrozenOptions):
    question_count: Five = 5
    difficulty: Difficulty = "medium"
    output_language: LanguageCode = "zh-CN"


class NotePreferences(FrozenOptions):
    detail: Literal["concise", "standard", "detailed"] = "standard"
    style: Literal["outline", "explained", "review"] = "outline"
    include_examples: StrictBool = False
    highlight_formulas: StrictBool = True
    focus_topics: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=100)]], Field(max_length=20)
    ] = Field(default_factory=list)
    custom_instructions: Annotated[str, Field(max_length=2000)] = ""


class InitialStudyRequest(FrozenOptions):
    kind: Literal["initial_study"] = "initial_study"
    processing: ProcessingOptions = Field(default_factory=ProcessingOptions)
    quiz: QuizGenerationOptions = Field(default_factory=QuizGenerationOptions)
    preferences: NotePreferences = Field(default_factory=NotePreferences)


class GenerateNotesRequest(FrozenOptions):
    kind: Literal["generate_notes"] = "generate_notes"
    transcript_snapshot_id: UUID
    output_language: LanguageCode = "zh-CN"
    preferences: NotePreferences = Field(default_factory=NotePreferences)


class GenerateQuizRequest(FrozenOptions):
    kind: Literal["generate_quiz"] = "generate_quiz"
    transcript_snapshot_id: UUID
    notes_revision_id: UUID | None = None
    options: QuizGenerationOptions = Field(default_factory=QuizGenerationOptions)


class ChatReplyRequest(FrozenOptions):
    kind: Literal["chat_reply"] = "chat_reply"
    conversation_id: UUID
    notes_revision_id: UUID
    chapter_ids: Annotated[list[SegmentId], Field(min_length=1, max_length=20)]
    message: ShortText


class ReviseNotesRequest(FrozenOptions):
    kind: Literal["revise_notes"] = "revise_notes"
    transcript_snapshot_id: UUID
    base_revision_id: UUID
    chapter_ids: Annotated[list[SegmentId], Field(max_length=20)] = Field(default_factory=list)
    preferences: NotePreferences
    instruction: ShortText


OperationRequest = Annotated[
    InitialStudyRequest
    | GenerateNotesRequest
    | GenerateQuizRequest
    | ChatReplyRequest
    | ReviseNotesRequest,
    Field(discriminator="kind"),
]
OperationStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class OperationUsage(ContractModel):
    request_limit: PositiveInt = 100
    token_limit: PositiveInt = 500000
    requests_reserved: Counter = 0
    tokens_reserved: Counter = 0
    input_tokens: Counter | None = None
    output_tokens: Counter | None = None


class OperationOutput(ContractModel):
    transcript_snapshot_id: UUID | None = None
    notes_revision_id: UUID | None = None
    quiz_batch_id: UUID | None = None
    message_id: UUID | None = None


class OperationAttempt(ContractModel):
    attempt: PositiveInt
    status: Literal["failed", "cancelled"]
    usage: OperationUsage
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime
    error: ErrorInfo | None = None


class StudyOperation(IterationDocument):
    id: UUID
    task_id: UUID
    request: OperationRequest
    request_hash: ContentHash
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    status: OperationStatus = "queued"
    attempt: PositiveInt = 1
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error: ErrorInfo | None = None
    usage: OperationUsage = Field(default_factory=OperationUsage)
    output: OperationOutput = Field(default_factory=OperationOutput)
    legacy_options: StudyOptions | None = None
    cancel_requested: StrictBool = False
    attempts: list[OperationAttempt] = Field(default_factory=list)


class TranscriptSnapshot(IterationDocument, StoredObject):
    id: UUID
    task_id: UUID
    document_schema_version: Literal["1.0"] = "1.0"
    created_at: AwareDatetime


class NotesRevision(IterationDocument, StoredObject):
    id: UUID
    task_id: UUID
    transcript_snapshot_id: UUID
    parent_revision_id: UUID | None = None
    operation_id: UUID | None = None
    status: Literal["draft", "published"] = "draft"
    document_schema_version: Literal["1.0", "1.1"] = "1.1"
    preferences: NotePreferences = Field(default_factory=NotePreferences)
    created_at: AwareDatetime


class QuizBatch(IterationDocument, StoredObject):
    id: UUID
    task_id: UUID
    transcript_snapshot_id: UUID
    notes_revision_id: UUID | None = None
    operation_id: UUID | None = None
    sequence: PositiveInt
    nonce: UUID
    question_count: Annotated[int, Field(strict=True, ge=1, le=20)] = 5
    difficulty: Difficulty = "medium"
    document_schema_version: Literal["1.0", "1.1"] = "1.1"
    created_at: AwareDatetime

    @model_validator(mode="after")
    def fixed_new_count(self) -> Self:
        if self.document_schema_version == "1.1" and self.question_count != 5:
            raise ValueError("New quiz batches require exactly five questions")
        return self


class CourseNotePreferences(IterationDocument):
    task_id: UUID
    revision: PositiveInt = 1
    preferences: NotePreferences = Field(default_factory=NotePreferences)


class CourseStudyState(IterationDocument):
    task_id: UUID
    revision: Counter = 0
    transcript_snapshot_id: UUID | None = None
    notes_revision_id: UUID | None = None
    quiz_batch_id: UUID | None = None


class Conversation(IterationDocument):
    id: UUID
    task_id: UUID
    created_at: AwareDatetime


class ConversationMessage(IterationDocument):
    id: UUID
    task_id: UUID
    conversation_id: UUID
    client_message_id: UUID
    sequence: PositiveInt
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(strict=True, min_length=1, max_length=20000)]
    notes_revision_id: UUID
    operation_id: UUID | None = None
    created_at: AwareDatetime
    citations: Annotated[list[SourceEvidence], Field(max_length=20)] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounded_user_message(self) -> Self:
        if self.role == "user" and len(self.content) > 2000:
            raise ValueError("User messages are limited to 2000 characters")
        return self


class NotesDocumentV11(NotesDocument):
    schema_version: Literal["1.1"] = "1.1"


ITERATION_CONTRACTS = (
    ProcessingOptions,
    QuizGenerationOptions,
    NotePreferences,
    InitialStudyRequest,
    GenerateNotesRequest,
    GenerateQuizRequest,
    ChatReplyRequest,
    ReviseNotesRequest,
    StudyOperation,
    TranscriptSnapshot,
    NotesRevision,
    QuizBatch,
    CourseNotePreferences,
    CourseStudyState,
    Conversation,
    ConversationMessage,
    NotesDocumentV11,
    QuizDocumentV11,
)
