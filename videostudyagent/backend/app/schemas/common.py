from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NonEmptyText = Annotated[str, Field(strict=True, min_length=1)]
Milliseconds = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
SegmentId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=80)]
ContentHash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


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
    stage: Annotated[int, Field(ge=1, le=7)] = 4
