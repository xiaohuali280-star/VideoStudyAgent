from uuid import UUID

from fastapi import APIRouter, Request
from starlette.responses import FileResponse

from app.api import repository
from app.core.errors import StudyError
from app.db.context_repository import VideoContextRepository
from app.schemas.video_context import VideoContextSnapshot
from app.services.storage import ArtifactStore

router = APIRouter(prefix="/api/tasks", tags=["evidence"])


@router.get("/{task_id}/contexts/{snapshot_id}", response_model=VideoContextSnapshot)
def context(request: Request, task_id: UUID, snapshot_id: UUID):
    repo = repository(request)
    repo.get(task_id)
    return VideoContextRepository(repo.engine).get(task_id, snapshot_id)


@router.get("/{task_id}/contexts/{snapshot_id}/frames/{frame_id}")
def frame(request: Request, task_id: UUID, snapshot_id: UUID, frame_id: UUID):
    snapshot = context(request, task_id, snapshot_id)
    for item in snapshot.frames:
        if item.id == frame_id:
            path = ArtifactStore(request.app.state.settings.data_dir, None).verify(item)
            return FileResponse(path, media_type="image/png")
    raise StudyError("NOT_FOUND", "未找到该课程画面。", 404)
