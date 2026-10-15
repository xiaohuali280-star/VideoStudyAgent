"""Versioned multimodal sources; OCR observations never masquerade as Transcript."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import ContentHash, ContractModel, Milliseconds, NonEmptyText
from app.schemas.study import (
    NotesDocument,
    QuestionV11,
    QuizDocumentV11,
    SourceEvidence,
    Transcript,
)


class EvidenceRef(ContractModel):
    task_id: UUID
    snapshot_id: UUID
    source_type: Literal["transcript", "ocr"]
    source_id: NonEmptyText
    quote: NonEmptyText


class EvidenceFrame(ContractModel):
    id: UUID
    task_id: UUID
    video_asset_sha256: ContentHash
    timestamp_ms: Milliseconds
    storage_key: str = Field(pattern=r"^tasks/[a-f0-9-]+/frames/[a-f0-9-]+\.png$")
    sha256: ContentHash
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    extract_version: Literal["pts-scene-v1"] = "pts-scene-v1"


class OcrObservation(ContractModel):
    id: str
    frame_id: UUID
    raw_text: str
    bbox: tuple[int, int, int, int]
    confidence: float | None = Field(default=None, ge=0, le=100)
    engine_version: str
    language: str
    status: Literal["succeeded", "empty", "failed"]
    error_code: str | None = None


class VideoContextSegment(ContractModel):
    id: str
    start_ms: Milliseconds
    end_ms: Milliseconds
    transcript_segment_ids: list[str] = []
    ocr_observation_ids: list[str] = []
    frame_ids: list[UUID] = []
    source_types: list[Literal["transcript", "ocr"]] = []


class VideoContextSnapshot(ContractModel):
    schema_version: Literal["1.2"] = "1.2"
    id: UUID
    task_id: UUID
    video_asset_id: UUID | None = None
    transcript_snapshot_id: UUID | None = None
    transcript: Transcript | None = None
    frames: list[EvidenceFrame] = []
    observations: list[OcrObservation] = []
    segments: list[VideoContextSegment]
    branch_statuses: dict[str, Literal["succeeded", "failed", "disabled", "empty"]]
    warnings: list[str] = []
    manifest_sha256: ContentHash
    config_version: Literal["context-v1"] = "context-v1"

    @model_validator(mode="after")
    def valid_sources(self) -> Self:
        if (self.transcript is None) != (self.transcript_snapshot_id is None):
            raise ValueError("Transcript and snapshot must agree")
        frames = {str(f.id): f for f in self.frames}
        if len(frames) != len(self.frames) or any(f.task_id != self.task_id for f in self.frames):
            raise ValueError("Invalid frame ownership")
        if len({o.id for o in self.observations}) != len(self.observations):
            raise ValueError("Duplicate observation")
        if any(str(o.frame_id) not in frames for o in self.observations):
            raise ValueError("Observation frame missing")
        if not self.transcript and not any(
            o.raw_text and o.status == "succeeded" for o in self.observations
        ):
            raise ValueError("Context has no usable source")
        return self


class ContextChapter(ContractModel):
    id: str
    title: NonEmptyText
    content_markdown: NonEmptyText
    source_segment_ids: list[str] = []
    source_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class NotesDocumentV12(NotesDocument):
    schema_version: Literal["1.2"] = "1.2"
    context_snapshot_id: UUID
    chapters: Annotated[list[ContextChapter], Field(min_length=1)]


class QuestionV12(QuestionV11):
    source_segment_ids: list[str] = []
    evidence: list[SourceEvidence] = []
    source_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class QuizDocumentV12(QuizDocumentV11):
    schema_version: Literal["1.2"] = "1.2"
    context_snapshot_id: UUID
    questions: Annotated[list[QuestionV12], Field(min_length=5, max_length=5)]


class QuizPartV12(QuizDocumentV12):
    question_count: Annotated[int, Field(strict=True, ge=1, le=5)]
    questions: Annotated[list[QuestionV12], Field(min_length=1, max_length=5)]
