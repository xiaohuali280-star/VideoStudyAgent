from sqlalchemy import delete, func, insert, select, text, update

from app.core.errors import StudyError
from app.db.event_models import EventRetentionRow, OperationEventRow
from app.db.iteration_models import OperationRow
from app.db.repository import now
from app.db.study_repository import StudyRepository
from app.schemas.events import EventOperationState, EventSnapshot, OperationEvent
from app.schemas.iteration import StudyOperation


def available(connection):
    return bool(
        connection.scalar(text("SELECT 1 FROM sqlite_master WHERE name='operation_events'"))
    )


def append_event(
    connection,
    operation,
    stage="status",
    *,
    stage_status=None,
    completed_units=None,
    total_units=None,
):
    event = OperationEvent(
        event_id=1,
        task_id=operation.task_id,
        operation_id=operation.id,
        attempt=operation.attempt,
        state_revision=operation.event_revision,
        stage=stage,
        status=operation.status,
        stage_status=stage_status,
        completed_units=completed_units,
        total_units=total_units,
        error_code=operation.error.code if operation.error else None,
        occurred_at=now(),
    )
    result = connection.execute(
        insert(OperationEventRow).values(
            task_id=str(operation.task_id),
            operation_id=str(operation.id),
            state_revision=operation.event_revision,
            payload={},
        )
    )
    event.event_id = result.inserted_primary_key[0]
    connection.execute(
        update(OperationEventRow)
        .where(OperationEventRow.event_id == event.event_id)
        .values(payload=event.model_dump(mode="json"))
    )
    prune_events(connection, operation.task_id, keep=1000)
    return event


def prune_events(connection, task_id, *, keep):
    cutoff = connection.scalar(
        select(OperationEventRow.event_id)
        .where(OperationEventRow.task_id == str(task_id))
        .order_by(OperationEventRow.event_id.desc())
        .offset(keep)
        .limit(1)
    )
    if cutoff is None:
        return 0
    removed = connection.execute(
        delete(OperationEventRow).where(
            OperationEventRow.task_id == str(task_id), OperationEventRow.event_id <= cutoff
        )
    ).rowcount
    connection.execute(
        text(
            "INSERT INTO event_retention(task_id,floor) VALUES (:task,:floor) "
            "ON CONFLICT(task_id) DO UPDATE SET floor=MAX(floor,excluded.floor)"
        ),
        dict(task=str(task_id), floor=cutoff),
    )
    return removed


def step_event(connection, step):
    if not available(connection):
        return
    payload = connection.scalar(
        select(OperationRow.payload)
        .where(OperationRow.task_id == str(step.task_id), OperationRow.status == "running")
        .limit(1)
    )
    if payload:
        operation = StudyOperation.model_validate(payload)
        operation.event_revision += 1
        connection.execute(
            update(OperationRow)
            .where(OperationRow.id == str(operation.id))
            .values(payload=operation.model_dump(mode="json"))
        )
        append_event(
            connection,
            operation,
            step.tool_name,
            stage_status=step.status,
            completed_units=1 if step.status in {"succeeded", "skipped"} else 0,
            total_units=1,
        )


class EventRepository(StudyRepository):
    def retention_floor(self, task_id):
        with self.engine.connect() as connection:
            return (
                connection.scalar(
                    select(EventRetentionRow.floor).where(EventRetentionRow.task_id == str(task_id))
                )
                or 0
            )

    def snapshot(self, task_id, operation_id=None):
        with self.engine.connect() as connection:
            # SQLite legacy transaction mode does not BEGIN on SELECT automatically.
            connection.exec_driver_sql("BEGIN")
            self._course(connection, task_id)
            if not available(connection):
                raise StudyError("EVENTS_UNAVAILABLE", "实时提示暂不可用，仍可定期刷新。", 503)
            cursor = connection.scalar(select(func.max(OperationEventRow.event_id))) or 0
            floor = (
                connection.scalar(
                    select(EventRetentionRow.floor).where(EventRetentionRow.task_id == str(task_id))
                )
                or 0
            )
            state = self._state(connection, task_id)
            if operation_id:
                operations = [
                    self._owned(connection, OperationRow, StudyOperation, task_id, operation_id)
                ]
            else:
                operations = [
                    StudyOperation.model_validate(p)
                    for p in connection.scalars(
                        select(OperationRow.payload)
                        .where(OperationRow.task_id == str(task_id))
                        .order_by(OperationRow.created_at.desc(), OperationRow.id.desc())
                        .limit(100)
                    )
                ]
            summaries = [
                EventOperationState(
                    id=op.id,
                    task_id=op.task_id,
                    kind=op.request.kind,
                    status=op.status,
                    attempt=op.attempt,
                    event_revision=op.event_revision,
                    error_code=op.error.code if op.error else None,
                )
                for op in operations
            ]
            return EventSnapshot(
                cursor=cursor, retention_floor=floor, state=state, operations=summaries
            )

    def after(self, task_id, cursor, operation_id=None, *, limit=100):
        if cursor < 0 or not 1 <= limit <= 500:
            raise ValueError("Invalid event cursor")
        with self.engine.connect() as connection:
            query = select(OperationEventRow.payload).where(
                OperationEventRow.task_id == str(task_id), OperationEventRow.event_id > cursor
            )
            if operation_id:
                query = query.where(OperationEventRow.operation_id == str(operation_id))
            return [
                OperationEvent.model_validate(p)
                for p in connection.scalars(query.order_by(OperationEventRow.event_id).limit(limit))
            ]

    def prune(self, task_id, *, keep=1000):
        if keep < 1:
            raise ValueError("Must retain at least one event")
        with self._write() as connection:
            self._course(connection, task_id)
            return prune_events(connection, task_id, keep=keep)
