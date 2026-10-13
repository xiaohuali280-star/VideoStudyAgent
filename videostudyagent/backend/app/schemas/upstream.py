from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.common import ContractModel, DocumentModel, NonEmptyText


class UpstreamCandidate(ContractModel):
    id: Annotated[str, Field(pattern=r"^[BDTVN][1-9][0-9]*$")]
    repository: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    commit: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    license: Literal["MIT", "Apache-2.0"] | None
    disposition: Literal["direct", "adapt", "reference", "excluded"]
    status: Literal["candidate", "reference_only", "excluded"]
    target_stage: Literal[3, 4, 5, 6] | None
    source_paths: Annotated[list[NonEmptyText], Field(min_length=1)]
    reason: NonEmptyText

    @model_validator(mode="after")
    def check_adoption_boundaries(self) -> Self:
        for path in self.source_paths:
            if (
                PurePosixPath(path).is_absolute()
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or "\\" in path
                or ":" in path
            ):
                raise ValueError("Source paths must stay within the upstream repository")
        if self.disposition in {"direct", "adapt"}:
            if self.license is None or self.target_stage is None or self.status != "candidate":
                raise ValueError(
                    "Reusable candidates require a license and an implementation stage"
                )
        if self.license is None and self.status != "excluded":
            raise ValueError("Sources without a clear license cannot be implementation candidates")
        return self


class UpstreamBaseline(DocumentModel):
    candidates: Annotated[list[UpstreamCandidate], Field(min_length=1)]

    @model_validator(mode="after")
    def check_unique_ids(self) -> Self:
        ids = [item.id for item in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("Candidate IDs must be unique")
        return self
