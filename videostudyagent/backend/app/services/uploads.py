import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

from starlette.datastructures import UploadFile

from app.core.config import Settings
from app.core.errors import StudyError
from app.db.repository import TaskRepository, now
from app.schemas.study import StudyOptions
from app.schemas.tasks import InputAsset, Task


def decode_subtitle(data: bytes) -> str:
    encodings = (
        ["utf-16"]
        if data.startswith((b"\xff\xfe", b"\xfe\xff"))
        else [
            "utf-8-sig",
            "gb18030",
        ]
    )
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            if "\x00" not in text:
                return text
        except UnicodeDecodeError:
            continue
    raise StudyError("INVALID_SUBTITLE", "字幕编码无效。", 415)


async def save_uploads(
    settings: Settings,
    repository: TaskRepository,
    files: dict[str, UploadFile],
    options: StudyOptions,
    title: str | None,
) -> Task:
    if not files:
        raise StudyError("INPUT_REQUIRED", "请至少提供视频或字幕。", 422)
    task_id = uuid4()
    directory = settings.data_dir / "tasks" / str(task_id)
    assets = []
    try:
        directory.mkdir(parents=True)
        for kind, upload in files.items():
            original_name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
            extension = Path(original_name).suffix.lower()
            if extension not in ({".mp4"} if kind == "video" else {".srt", ".vtt"}):
                raise StudyError("UNSUPPORTED_MEDIA", "仅支持 MP4、SRT 和 VTT 文件。", 415)
            limit = settings.max_video_bytes if kind == "video" else settings.max_subtitle_bytes
            key = f"tasks/{task_id}/inputs/{kind}{extension}"
            target = settings.data_dir / key
            target.parent.mkdir(exist_ok=True)
            temporary = target.with_suffix(extension + ".part")
            size, digest = 0, hashlib.sha256()
            with temporary.open("wb") as output:
                while block := await upload.read(1024 * 1024):
                    size += len(block)
                    if size > limit:
                        raise StudyError("UPLOAD_TOO_LARGE", "上传文件超过大小限制。", 413)
                    output.write(block)
                    digest.update(block)
            if not size:
                raise StudyError("EMPTY_UPLOAD", "上传文件不能为空。", 422)
            if kind == "video":
                with temporary.open("rb") as source:
                    header = source.read(32)
                if len(header) < 12 or header[4:8] != b"ftyp":
                    raise StudyError("UNSUPPORTED_MEDIA", "文件不是可识别的 MP4 容器。", 415)
            else:
                text = decode_subtitle(temporary.read_bytes())
                if "-->" not in text or (extension == ".vtt" and not text.startswith("WEBVTT")):
                    raise StudyError("INVALID_SUBTITLE", "字幕文件缺少合法时间轴。", 415)
            temporary.replace(target)
            assets.append(
                InputAsset(
                    id=uuid4(),
                    task_id=task_id,
                    kind=kind,
                    original_name=original_name[:200],
                    storage_key=key,
                    sha256=digest.hexdigest(),
                    size_bytes=size,
                )
            )
        task = Task(
            id=task_id,
            title=title or Path(assets[0].original_name).stem or "新课程",
            options=options,
            created_at=now(),
        )
        repository.create(task, assets)
        return task
    except Exception:
        # This directory is generated from our UUID, never from the supplied filename.
        if directory.resolve().is_relative_to((settings.data_dir / "tasks").resolve()):
            shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        for upload in files.values():
            await upload.close()
