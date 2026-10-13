from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NonEmptyText = Annotated[str, Field(strict=True, min_length=1)]
Milliseconds = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
SegmentId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=80)]
ContentHash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ExportFormat = Literal["notes.md", "quiz.md", "quiz.json", "transcript.json", "transcript.srt"]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
        json_schema_serialization_defaults_required=True,
    )


class DocumentModel(ContractModel):
    schema_version: Literal["1.0"] = "1.0"


class ErrorInfo(ContractModel):
    code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
    message: NonEmptyText
    step: str | None = None
    retryable: bool = False


class ErrorResponse(DocumentModel):
    error: ErrorInfo


class HealthResponse(DocumentModel):
    status: Literal["ok"] = "ok"
    service: Literal["VideoStudyAgent"] = "VideoStudyAgent"
    version: str
    stage: Annotated[int, Field(ge=1, le=7)] = 7


class PublicConfig(DocumentModel):
    max_video_bytes: PositiveInt
    max_subtitle_bytes: PositiveInt
    max_duration_ms: PositiveInt
    export_formats: list[ExportFormat]
