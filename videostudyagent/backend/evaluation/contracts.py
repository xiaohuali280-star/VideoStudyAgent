from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EvaluationCase(Contract):
    case_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    suite_version: Literal["1"] = "1"
    scenario: str
    provenance: Literal["self_created", "authorized"]
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    fixture_refs: list[str]
    capabilities_required: list[str] = []
    expected_assertions: dict[str, bool]
    reference_fact_ids: list[str] = []


class MetricResult(Contract):
    name: str
    value: float | None = None
    numerator: int | None = None
    denominator: int | None = None
    status: Literal["measured", "not_run", "not_applicable", "insufficient_data"]
    measurement_scope: Literal["synthetic_fixture", "replay"]
    reason: str | None = None


class CaseResult(Contract):
    case_id: str
    execution_status: Literal["passed", "failed", "pending_capability"]
    assertions: dict[str, bool] = {}
    metrics: list[MetricResult] = []
    missing_capabilities: list[str] = []


class EvaluationRun(Contract):
    run_id: str
    project_git_sha: str | None
    suite_sha256: str
    mode: Literal["fixture", "replay"]
    capabilities: list[str]
    config_version: Literal["offline-v1"] = "offline-v1"
    started_at: str
    case_results: list[CaseResult]
    usage_completeness: Literal["unknown"] = "unknown"
    cost: None = None
