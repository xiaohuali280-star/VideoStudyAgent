import json

from sqlalchemy import select, text

from app.core.errors import StudyError
from app.db.review_models import ReviewRow
from app.db.study_repository import StudyRepository
from app.schemas.review import ReviewReport


class ReviewRepository(StudyRepository):
    def reports(self, task_id, operation_id):
        from app.db.iteration_models import OperationRow
        from app.schemas.iteration import StudyOperation

        with self.engine.connect() as connection:
            self._owned(connection, OperationRow, StudyOperation, task_id, operation_id)
            rows = connection.scalars(
                select(ReviewRow.payload).where(
                    ReviewRow.task_id == str(task_id), ReviewRow.operation_id == str(operation_id)
                )
            )
            return [ReviewReport.model_validate(row) for row in rows]

    def add(self, report):
        with self._write() as connection:
            self._immutable(
                connection,
                ReviewRow,
                ReviewReport,
                report,
                dict(
                    id=str(report.id),
                    task_id=str(report.task_id),
                    operation_id=str(report.operation_id),
                    target_sha256=report.target_document_sha256,
                ),
            )
        return report

    def claim_repair(self, task_id, operation_id):
        with self._write() as connection:
            result = connection.execute(
                text(
                    "INSERT OR IGNORE INTO review_repairs(operation_id,task_id) VALUES (:op,:task)"
                ),
                dict(op=str(operation_id), task=str(task_id)),
            )
            return result.rowcount == 1

    def repair_candidate(self, task_id, operation_id, *, save=None):
        with self._write() as connection:
            parameters = dict(op=str(operation_id), task=str(task_id))
            if save is not None:
                connection.execute(
                    text(
                        "UPDATE review_repairs SET candidate=:candidate "
                        "WHERE operation_id=:op AND task_id=:task AND candidate IS NULL"
                    ),
                    parameters | dict(candidate=json.dumps(save)),
                )
            raw = connection.scalar(
                text(
                    "SELECT candidate FROM review_repairs WHERE operation_id=:op AND task_id=:task"
                ),
                parameters,
            )
            return json.loads(raw) if raw else None


def require_approved(connection, item):
    if item.review_policy is None:
        return  # Historical immutable versions are readable/restorable without cloud review.
    payload = connection.scalar(
        select(ReviewRow.payload).where(
            ReviewRow.id == str(item.review_report_id), ReviewRow.task_id == str(item.task_id)
        )
    )
    if payload is None:
        raise StudyError("REVIEW_REQUIRED", "该版本需要通过发布前审核。", 409)
    report = ReviewReport.model_validate(payload)
    if (
        report.status != "passed"
        or report.policy != item.review_policy
        or report.target_document_sha256 != item.sha256
        or report.operation_id != item.operation_id
        or report.source_snapshot_id != (item.context_snapshot_id or item.transcript_snapshot_id)
    ):
        raise StudyError("REVIEW_REQUIRED", "审核与版本内容或来源不一致。", 409)
