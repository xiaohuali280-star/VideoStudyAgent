import asyncio
import json
import time
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.api import repository
from app.core.errors import StudyError
from app.db.event_repository import EventRepository

router = APIRouter(prefix="/api/tasks", tags=["events"])
TERMINAL = {"succeeded", "failed", "cancelled"}


def encode(event, data, cursor):
    return f"id: {cursor}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_events(
    repo, task_id, initial, *, since=None, operation_id=None, disconnected=None, poll=0.5
):
    cursor = initial.cursor
    if since is not None and since < initial.retention_floor:
        yield encode("reset", initial.model_dump(mode="json"), cursor)
    elif since is not None:
        replay = since
        while replay < initial.cursor:
            if disconnected and await disconnected():
                return
            events = await run_in_threadpool(repo.after, task_id, replay, operation_id)
            events = [e for e in events if e.event_id <= initial.cursor]
            if not events:
                break
            for event in events:
                yield encode("operation", event.model_dump(mode="json"), event.event_id)
                replay = event.event_id
        yield encode("snapshot", initial.model_dump(mode="json"), cursor)
    else:
        yield encode("snapshot", initial.model_dump(mode="json"), cursor)
    if operation_id and initial.operations[0].status in TERMINAL:
        return
    heartbeat = time.monotonic()
    while True:
        if disconnected and await disconnected():
            return
        floor = await run_in_threadpool(repo.retention_floor, task_id)
        if cursor < floor:
            window = await run_in_threadpool(repo.snapshot, task_id, operation_id)
            cursor = window.cursor
            yield encode("reset", window.model_dump(mode="json"), cursor)
            if operation_id and window.operations[0].status in TERMINAL:
                return
            continue
        events = await run_in_threadpool(repo.after, task_id, cursor, operation_id)
        for event in events:
            cursor = event.event_id
            yield encode("operation", event.model_dump(mode="json"), cursor)
            if operation_id and event.status in TERMINAL:
                return
        if time.monotonic() - heartbeat > 15:
            yield ": heartbeat\n\n"
            heartbeat = time.monotonic()
        await asyncio.sleep(poll)


@router.get("/{task_id}/events")
async def events(
    request: Request,
    task_id: UUID,
    since: int | None = Query(None, ge=0, le=2**53 - 1),
    operation_id: UUID | None = None,
    last_event_id: str | None = Header(None),
):
    if last_event_id is not None:
        if not last_event_id.isascii() or not last_event_id.isdecimal() or len(last_event_id) > 16:
            raise StudyError("VALIDATION_ERROR", "实时提示游标无效。", 422)
        header_cursor = int(last_event_id)
        if header_cursor > 2**53 - 1 or (since is not None and since != header_cursor):
            raise StudyError("VALIDATION_ERROR", "实时提示游标不一致。", 422)
        since = header_cursor
    repo = EventRepository(repository(request).engine)
    initial = await run_in_threadpool(repo.snapshot, task_id, operation_id)
    if since is not None and since > initial.cursor:
        raise StudyError("VALIDATION_ERROR", "实时提示游标超过当前版本。", 422)
    return StreamingResponse(
        stream_events(
            repo,
            task_id,
            initial,
            since=since,
            operation_id=operation_id,
            disconnected=request.is_disconnected,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
