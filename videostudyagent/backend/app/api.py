from threading import Lock
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse

from app.core.errors import StudyError
from app.db.repository import TaskRepository, initialize_database
from app.schemas.study import StudyOptions
from app.schemas.tasks import StudyResult, Task, TaskDetail
from app.services.exports import ResultService
from app.services.storage import ArtifactStore
from app.services.uploads import save_uploads

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
initialization_lock = Lock()


def repository(request: Request) -> TaskRepository:
    with initialization_lock:
        if not hasattr(request.app.state, "repository"):
            settings = request.app.state.settings
            request.app.state.repository = TaskRepository(
                initialize_database(settings.data_dir / "app.db"),
            )
    return request.app.state.repository


@router.post(
    "",
    response_model=Task,
    status_code=202,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "video": {"type": "string", "format": "binary"},
                            "subtitle": {"type": "string", "format": "binary"},
                            "options": {"type": "string", "description": "JSON StudyOptions"},
                            "title": {"type": "string", "maxLength": 200},
                        },
                    }
                }
            },
        },
    },
)
async def create_task(request: Request):
    try:
        form = await request.form(max_files=2, max_fields=2)
    except HTTPException as exc:
        raise StudyError("INVALID_UPLOAD", "上传表单无效或字段过多。", 422) from exc
    files, fields = {}, {}
    for key, value in form.multi_items():
        if key in files or key in fields or key not in {"video", "subtitle", "options", "title"}:
            await form.close()
            raise StudyError("INVALID_UPLOAD", "上传包含重复或未知字段。", 422)
        if key in {"video", "subtitle"} and isinstance(value, UploadFile):
            files[key] = value
        elif key in {"options", "title"} and isinstance(value, str):
            fields[key] = value
        else:
            await form.close()
            raise StudyError("INVALID_UPLOAD", "上传字段类型错误。", 422)
    try:
        options = StudyOptions.model_validate_json(fields.get("options", "{}"))
        title = fields.get("title", "").strip() or None
        if title and len(title) > 200:
            raise ValueError("title too long")
        return await save_uploads(
            request.app.state.settings, repository(request), files, options, title
        )
    except (ValidationError, ValueError) as exc:
        raise StudyError("VALIDATION_ERROR", "学习参数或标题不符合要求。", 422) from exc
    finally:
        await form.close()


@router.get("", response_model=list[Task])
def list_tasks(
    request: Request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)
):
    return repository(request).list(limit, offset)


@router.get("/{task_id}", response_model=TaskDetail)
def task_detail(request: Request, task_id: UUID):
    return repository(request).detail(task_id)


@router.post("/{task_id}/retry", response_model=Task, status_code=202)
def retry_task(request: Request, task_id: UUID):
    repo = repository(request)
    if repo.get(task_id).status == "succeeded":
        try:
            value = ResultService(request.app.state.settings.data_dir, repo).result(task_id)
            if not (value.transcript and value.notes and value.quiz):
                raise StudyError("STORAGE_ERROR", "学习资料不完整。", 409, True)
        except StudyError as exc:
            if exc.code != "STORAGE_ERROR":
                raise
            repo.invalidate_completed(task_id)
    return repo.retry(task_id)


@router.get("/{task_id}/result", response_model=StudyResult)
def study_result(request: Request, task_id: UUID):
    return ResultService(request.app.state.settings.data_dir, repository(request)).result(task_id)


@router.get("/{task_id}/exports/{format}")
def export_result(request: Request, task_id: UUID, format: str):
    path = ResultService(request.app.state.settings.data_dir, repository(request)).export(
        task_id, format
    )
    types = {"json": "application/json", "md": "text/markdown", "srt": "application/x-subrip"}
    return FileResponse(path, filename=format, media_type=types[path.suffix[1:]])


@router.get("/{task_id}/video")
def course_video(request: Request, task_id: UUID):
    repo = repository(request)
    repo.get(task_id)
    for asset in repo.assets(task_id):
        if asset.kind == "video":
            path = ArtifactStore(request.app.state.settings.data_dir, repo).verify(asset)
            return FileResponse(
                path,
                filename="course.mp4",
                media_type="video/mp4",
                content_disposition_type="inline",
            )
    raise StudyError("NOT_FOUND", "该课程没有视频文件。", 404)
