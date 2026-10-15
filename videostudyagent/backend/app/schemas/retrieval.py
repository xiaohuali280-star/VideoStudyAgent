from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import ContractModel


class EvidenceQuery(ContractModel):
    snapshot_id: UUID
    snapshot_type: Literal["transcript", "context"]
    notes_revision_id: UUID | None = None
    query: str = Field(min_length=1, max_length=300)
    top_k: int = Field(default=5, ge=1, le=20, strict=True)
    start_ms: int | None = Field(default=None, ge=0, strict=True)
    end_ms: int | None = Field(default=None, ge=0, strict=True)
    source_types: list[Literal["transcript", "ocr"]] = Field(
        default=["transcript", "ocr"], min_length=1, max_length=2
    )

    @model_validator(mode="after")
    def interval(self):
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("Invalid time filter")
        return self


class EvidenceHit(ContractModel):
    task_id: UUID
    snapshot_id: UUID
    source_type: Literal["transcript", "ocr"]
    source_id: str
    start_ms: int
    end_ms: int
    raw_text: str
    frame_id: UUID | None = None
    score_components: dict[str, float]


class EvidenceSearchResult(ContractModel):
    hits: list[EvidenceHit]
    warnings: list[str] = []
    mode: Literal["lexical_fts5", "scoped_source_fallback"]
    scanned_sources: int
    total_sources: int
    index_generation: int | None = None
