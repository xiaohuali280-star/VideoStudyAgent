from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from app.schemas.common import (
    ContentHash,
    ContractModel,
    DocumentModel,
    Milliseconds,
    NonEmptyText,
    PositiveInt,
    SegmentId,
)

Difficulty = Literal["easy", "medium", "hard"]
QuestionCount = Annotated[int, Field(strict=True, ge=1, le=20)]
LanguageCode = Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")]


class StudyOptions(ContractModel):
    model_config = ConfigDict(frozen=True)
    question_count: QuestionCount = 5
    difficulty: Difficulty = "medium"
    question_type: Literal["short_answer"] = "short_answer"
    output_language: LanguageCode = "zh-CN"
    transcript_language: LanguageCode | None = None


class TranscriptSegment(ContractModel):
    id: SegmentId
    start_ms: Milliseconds
    end_ms: Milliseconds
    text: NonEmptyText

    @model_validator(mode="after")
    def check_interval(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class Transcript(DocumentModel):
    source: Literal["subtitle", "asr"]
    language: LanguageCode
    duration_ms: PositiveInt
    segments: Annotated[list[TranscriptSegment], Field(min_length=1)]

    @model_validator(mode="after")
    def check_segments(self) -> Self:
        ids = [segment.id for segment in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("Segment IDs must be unique")
        starts = [segment.start_ms for segment in self.segments]
        if starts != sorted(starts):
            raise ValueError("Segments must be sorted by start_ms")
        if max(segment.end_ms for segment in self.segments) > self.duration_ms:
            raise ValueError("Segment end_ms exceeds duration_ms")
        return self


class ChunkPart(ContractModel):
    model_config = ConfigDict(str_strip_whitespace=False)
    segment_id: SegmentId
    text: NonEmptyText
    part_index: Milliseconds


class TranscriptChunk(ContractModel):
    id: SegmentId
    source_segment_ids: Annotated[list[SegmentId], Field(min_length=1)]
    parts: Annotated[list[ChunkPart], Field(min_length=1)]
    token_estimate: PositiveInt
    content_hash: ContentHash

    @model_validator(mode="after")
    def check_source_mapping(self) -> Self:
        if set(self.source_segment_ids) != {part.segment_id for part in self.parts}:
            raise ValueError("Chunk parts and source IDs must agree")
        return self


class NoteChapter(ContractModel):
    id: SegmentId
    title: NonEmptyText
    content_markdown: NonEmptyText
    source_segment_ids: Annotated[list[SegmentId], Field(min_length=1)]


class NotesDocument(DocumentModel):
    title: NonEmptyText
    learning_objectives: Annotated[list[NonEmptyText], Field(min_length=1)]
    chapters: Annotated[list[NoteChapter], Field(min_length=1)]
    key_concepts: Annotated[list[NonEmptyText], Field(min_length=1)]
    summary: NonEmptyText

    @model_validator(mode="after")
    def check_chapter_ids(self) -> Self:
        if len({chapter.id for chapter in self.chapters}) != len(self.chapters):
            raise ValueError("Chapter IDs must be unique")
        return self


class SourceEvidence(ContractModel):
    segment_id: SegmentId
    quote: NonEmptyText


class Question(ContractModel):
    id: SegmentId
    type: Literal["short_answer"] = "short_answer"
    difficulty: Difficulty
    chapter_id: SegmentId
    question: NonEmptyText
    answer: NonEmptyText
    explanation: NonEmptyText
    source_segment_ids: Annotated[list[SegmentId], Field(min_length=1)]
    evidence: Annotated[list[SourceEvidence], Field(min_length=1)]

    @model_validator(mode="after")
    def check_evidence_ids(self) -> Self:
        if set(self.source_segment_ids) != {item.segment_id for item in self.evidence}:
            raise ValueError("Evidence and source IDs must agree")
        return self


class QuizDocument(DocumentModel):
    question_count: QuestionCount
    difficulty: Difficulty
    questions: Annotated[list[Question], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def check_requested_shape(self) -> Self:
        if len(self.questions) != self.question_count:
            raise ValueError("Question count must match questions length")
        if any(question.difficulty != self.difficulty for question in self.questions):
            raise ValueError("Every question must match the requested difficulty")
        if len({question.id for question in self.questions}) != len(self.questions):
            raise ValueError("Question IDs must be unique")
        return self
