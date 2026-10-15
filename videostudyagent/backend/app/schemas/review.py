from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import ContentHash, ContractModel
from app.schemas.video_context import EvidenceRef

ReviewPolicy = Literal["hard_only", "semantic"]


class ReviewIssue(ContractModel):
    target_id: str = Field(min_length=1, max_length=200)
    type: Literal[
        "coverage", "unsupported_answer", "conflict", "invalid_source", "review_unavailable"
    ]
    suggestion: str = Field(min_length=1, max_length=1000)
    source_refs: list[EvidenceRef] = Field(default_factory=list, max_length=20)


class ReviewVerdict(ContractModel):
    status: Literal["passed", "failed", "uncertain"]
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=30)
    required_source_ids: list[str] = Field(default_factory=list, max_length=100)
    required_time_ranges: list[tuple[int, int]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "passed" and self.issues:
            raise ValueError("Passed review cannot contain issues")
        if self.status == "failed" and not self.issues:
            raise ValueError("Failed review must identify targets")
        if any(start < 0 or end < start for start, end in self.required_time_ranges):
            raise ValueError("Invalid evidence time range")
        return self


class ReviewReport(ReviewVerdict):
    id: UUID
    task_id: UUID
    operation_id: UUID
    target_document_sha256: ContentHash
    target_kind: Literal["notes", "quiz"]
    source_snapshot_id: UUID
    policy: ReviewPolicy
    policy_version: Literal["review-v1"] = "review-v1"
    reviewer_model: str | None
    prompt_version: Literal["critic-v1"] = "critic-v1"
    round: int = Field(ge=0, le=1)
    usage_delta: int = Field(ge=0)
    measurement_scope: Literal["hard_checks", "model_judgment"]
