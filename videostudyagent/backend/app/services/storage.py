import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.core.errors import StudyError
from app.db.repository import TaskRepository, now
from app.schemas.tasks import Artifact, CacheEntry, StoredObject


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def cache_key(**parameters) -> str:
    encoded = json.dumps(parameters, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ArtifactStore:
    def __init__(self, root: Path, repository: TaskRepository):
        self.root, self.repository = root.resolve(), repository

    def path(self, key: str) -> Path:
        StoredObject(storage_key=key, sha256="0" * 64)
        result = (self.root / key).resolve()
        if not result.is_relative_to(self.root):
            raise StudyError("STORAGE_ERROR", "文件路径无效。", 409, True)
        if os.name == "nt" and not str(result).startswith("\\\\?\\"):
            return Path("\\\\?\\" + str(result))
        return result

    def verify(self, item: StoredObject) -> Path:
        path = self.path(item.storage_key)
        if not path.is_file() or file_hash(path) != item.sha256:
            raise StudyError("STORAGE_ERROR", "文件缺失或损坏，请重试。", 409, True)
        return path

    def _atomic_copy(self, source: Path, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as out:
                temporary = Path(out.name)
                with source.open("rb") as stream:
                    shutil.copyfileobj(stream, out, 1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, target)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def put_file(
        self, task_id: UUID, kind: str, source: Path, suffix: str, key: str | None = None
    ) -> Artifact:
        digest = file_hash(source)
        storage_key = f"tasks/{task_id}/artifacts/{kind}-{digest}{suffix}"
        self._atomic_copy(source, self.path(storage_key))
        artifact = Artifact(
            id=uuid4(),
            task_id=task_id,
            kind=kind,
            storage_key=storage_key,
            sha256=digest,
            cache_key=key,
            created_at=now(),
        )
        self.repository.save_artifact(artifact)
        if key:
            cached_key = f"cache/{key}/{kind}-{digest}{suffix}"
            self._atomic_copy(self.path(storage_key), self.path(cached_key))
            self.repository.save_cache(
                CacheEntry(
                    key=key, kind=kind, storage_key=cached_key, sha256=digest, created_at=now()
                )
            )
        return artifact

    def put_json(self, task_id: UUID, kind: str, model: BaseModel, key: str) -> Artifact:
        directory = self.path(f"tasks/{task_id}/tmp")
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".json", delete=False) as out:
            temporary = Path(out.name)
            out.write(model.model_dump_json().encode("utf-8"))
        try:
            return self.put_file(task_id, kind, temporary, ".json", key)
        finally:
            temporary.unlink(missing_ok=True)

    def read_json(self, artifact: Artifact, model):
        try:
            return model.model_validate_json(self.verify(artifact).read_bytes())
        except (ValueError, OSError) as exc:
            raise StudyError("STORAGE_ERROR", "结果文件无效，请重试。", 409, True) from exc

    def reuse(self, task_id: UUID, kind: str, key: str, model=None) -> Artifact | None:
        self.last_cache_hit = False
        entry = self.repository.get_cache(key)
        if not entry or entry.kind != kind:
            return None
        try:
            path = self.verify(entry)
            if model:
                model.model_validate_json(path.read_bytes())
        except (StudyError, ValueError, OSError):
            return None
        result = self.put_file(task_id, kind, path, path.suffix, key)
        self.last_cache_hit = True
        return result
