from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.common import ContractModel
from app.schemas.iteration import CourseStudyState


class OperationEvent(ContractModel):
    event_id: int = Field(ge=1)
    task_id: UUID
    operation_id: UUID
    attempt: int = Field(ge=1)
    state_revision: int = Field(ge=0)
    stage: str = Field(pattern=r"^[a-z_]{1,40}$")
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    stage_status: Literal["pending", "running", "succeeded", "failed", "skipped"] | None = None
    completed_units: int | None = Field(default=None, ge=0)
    total_units: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def actual_units(self):
        if (
            self.completed_units is not None
            and self.total_units is not None
            and self.completed_units > self.total_units
        ):
            raise ValueError("Completed units exceed total")
        return self


class EventOperationState(ContractModel):
    id: UUID
    task_id: UUID
    kind: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    attempt: int
    event_revision: int
    error_code: str | None = None


class EventSnapshot(ContractModel):
    cursor: int = Field(ge=0)
    retention_floor: int = Field(ge=0)
    state: CourseStudyState
    operations: list[EventOperationState]
