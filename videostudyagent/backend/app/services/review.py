from hashlib import sha256
from uuid import uuid4

from app.adapters.grounding import quote_present
from app.core.errors import StudyError
from app.db.review_repository import ReviewRepository
from app.prompts.review import REVIEW_SYSTEM
from app.schemas.review import ReviewIssue, ReviewReport, ReviewVerdict
from app.services.source_context import source_items, validate_refs


def document_hash(document):
    return sha256(document.model_dump_json().encode("utf-8")).hexdigest()


class SourceScopeResolver:
    def __init__(self, task_id, snapshot_id, source):
        self.task_id, self.snapshot_id, self.source = task_id, snapshot_id, source
        self.items = (
            source_items(source)
            if hasattr(source, "observations")
            else [
                dict(
                    source_type="transcript",
                    source_id=s.id,
                    text=s.text,
                    start_ms=s.start_ms,
                    end_ms=s.end_ms,
                )
                for s in source.segments
            ]
        )

    def resolve(self, ids=(), ranges=()):
        if not ids and not ranges:
            return self.items
        return [
            s
            for s in self.items
            if s["source_id"] in ids
            or any(s["start_ms"] <= end and s["end_ms"] >= start for start, end in ranges)
        ]

    def validate(self, refs):
        if hasattr(self.source, "observations"):
            return validate_refs(refs, self.source)
        by_id = {s["source_id"]: s["text"] for s in self.items}
        for ref in refs:
            if (
                ref.task_id != self.task_id
                or ref.snapshot_id != self.snapshot_id
                or ref.source_type != "transcript"
                or ref.source_id not in by_id
                or not quote_present(ref.quote, by_id[ref.source_id])
            ):
                raise ValueError("Invalid reviewer source")


class ReviewService:
    def __init__(self, repository, generation):
        self.repo, self.generation = ReviewRepository(repository.engine), generation

    async def assess(self, operation, document, scope, hard_validate, *, round=0):
        self.repo.progress(operation.task_id, operation.id, "review")
        policy = operation.request.review_policy
        digest = document_hash(document)
        previous = next(
            (
                r
                for r in self.repo.reports(operation.task_id, operation.id)
                if r.target_document_sha256 == digest
                and r.source_snapshot_id == scope.snapshot_id
                and r.policy == policy
                and r.round == round
                and r.reviewer_model
                == (self.generation.settings.llm_model if policy == "semantic" else None)
            ),
            None,
        )
        # Hard checks always rerun, even with a cached semantic verdict.
        try:
            hard_validate(document)
        except ValueError:
            verdict = ReviewVerdict(
                status="failed",
                issues=[
                    ReviewIssue(
                        target_id="document",
                        type="invalid_source",
                        suggestion="修正结构或来源校验后重新生成。",
                    )
                ],
            )
        else:
            if previous:
                return previous
            if policy == "hard_only":
                verdict = ReviewVerdict(status="passed")
            else:
                allowed_targets = {
                    s.id
                    for s in (
                        document.chapters if hasattr(document, "chapters") else document.questions
                    )
                }

                def valid(value):
                    if set(value.required_source_ids) - {s["source_id"] for s in scope.items}:
                        raise ValueError("Unknown requested source")
                    for issue in value.issues:
                        if issue.target_id not in allowed_targets:
                            raise ValueError("Unknown review target")
                        scope.validate(issue.source_refs)

                before = self.generation.llm.requests_reserved
                try:
                    verdict = await self.generation._structured(
                        REVIEW_SYSTEM,
                        dict(
                            task_id=str(scope.task_id),
                            snapshot_id=str(scope.snapshot_id),
                            candidate=document.model_dump(mode="json"),
                            source_items=scope.items,
                        ),
                        ReviewVerdict,
                        valid,
                    )
                except StudyError as exc:
                    if exc.code in {"AGENT_LIMIT_EXCEEDED", "BUDGET_PREFLIGHT"}:
                        raise
                    verdict = ReviewVerdict(
                        status="uncertain",
                        issues=[
                            ReviewIssue(
                                target_id="document",
                                type="review_unavailable",
                                suggestion="审核未能完成，请保留旧资料。",
                            )
                        ],
                    )
                except Exception:
                    verdict = ReviewVerdict(
                        status="uncertain",
                        issues=[
                            ReviewIssue(
                                target_id="document",
                                type="review_unavailable",
                                suggestion="审核服务未完成，请保留旧资料。",
                            )
                        ],
                    )
                usage = self.generation.llm.requests_reserved - before
        return self.repo.add(
            ReviewReport(
                id=uuid4(),
                task_id=operation.task_id,
                operation_id=operation.id,
                target_document_sha256=digest,
                source_snapshot_id=scope.snapshot_id,
                target_kind="notes" if hasattr(document, "chapters") else "quiz",
                policy=policy,
                reviewer_model=self.generation.settings.llm_model if policy == "semantic" else None,
                round=round,
                usage_delta=locals().get("usage", 0),
                measurement_scope="model_judgment" if policy == "semantic" else "hard_checks",
                **verdict.model_dump(),
            )
        )

    async def gate(self, operation, document, scope, validate, repair):
        report = await self.assess(operation, document, scope, validate)
        if report.status == "failed" and all(i.type != "invalid_source" for i in report.issues):
            from app.schemas.tasks import StoredObject
            from app.services.operations import VersionWriter
            from app.services.storage import ArtifactStore, cache_key

            binding = cache_key(
                request=operation.request_hash,
                base=document_hash(document),
                source=scope.source.model_dump(mode="json"),
                policy=operation.request.review_policy,
                model=self.generation._model_key(),
                review="critic-v1",
            )
            if self.repo.claim_repair(operation.task_id, operation.id):
                repaired = await repair(document, report, scope)
                stored = VersionWriter(self.generation.settings.data_dir).write(
                    operation.task_id, "review-repair", repaired
                )
                self.repo.repair_candidate(
                    operation.task_id, operation.id, save=dict(binding=binding, stored=stored)
                )
                document = repaired
                report = await self.assess(operation, document, scope, validate, round=1)
            else:
                checkpoint = self.repo.repair_candidate(operation.task_id, operation.id)
                if checkpoint and checkpoint.get("binding") == binding:
                    try:
                        path = ArtifactStore(self.generation.settings.data_dir, None).verify(
                            StoredObject.model_validate(checkpoint["stored"])
                        )
                        restored = type(document).model_validate_json(path.read_bytes())
                        validate(restored)
                    except (ValueError, StudyError, OSError):
                        raise StudyError(
                            "REVIEW_FAILED", "修复检查点无效，已保留旧资料。", 422
                        ) from None
                    document = restored
                    report = await self.assess(operation, document, scope, validate, round=1)
        if report.status != "passed":
            raise StudyError(
                "REVIEW_FAILED" if report.status == "failed" else "REVIEW_UNCERTAIN",
                "审核未通过，已保留原有正式资料。",
                422,
                False,
            )
        return document, report
