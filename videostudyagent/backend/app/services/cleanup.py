"""Remove only stale, unreferenced temporary files after acquiring the Worker lock."""

import time
from pathlib import Path
from uuid import UUID

from app.core.errors import StudyError


def linked(path: Path):
    return path.is_symlink() or path.is_junction()


def cleanup_temporary(settings, repository, *, now=None, grace_seconds=3600):
    root = settings.data_dir.resolve()
    cutoff = (time.time() if now is None else now) - grace_seconds
    removed = 0

    def remove(path, protected):
        nonlocal removed
        try:
            resolved = path.resolve()
            if (
                not resolved.is_relative_to(root)
                or linked(path)
                or not path.is_file()
                or resolved in protected
                or path.stat().st_mtime >= cutoff
            ):
                return
            path.unlink()
            removed += 1
        except OSError:
            pass  # Temporary housekeeping must not stop pending courses.

    tasks = root / "tasks"
    if tasks.is_dir() and not linked(tasks):
        for directory in tasks.iterdir():
            if not directory.is_dir() or linked(directory):
                continue
            try:
                task_id = UUID(directory.name)
            except ValueError:
                continue
            try:
                task = repository.get(task_id)
            except StudyError as exc:
                if exc.code != "NOT_FOUND":
                    raise
                task = None
            if task and task.status in {"queued", "running"}:
                continue
            protected = {
                (root / item.storage_key).resolve()
                for item in [*repository.assets(task_id), *repository.artifacts(task_id)]
            }
            for name in ("tmp", "inputs", "artifacts", "exports"):
                folder = directory / name
                if not folder.is_dir() or linked(folder):
                    continue
                for path in folder.iterdir():
                    if path.suffix in {".tmp", ".part"} or (
                        name == "tmp"
                        and (
                            path.name == "audio.wav"
                            or (path.name.startswith("tmp") and path.suffix == ".json")
                        )
                    ):
                        remove(path, protected)
    cache = root / "cache"
    if cache.is_dir() and not linked(cache):
        for directory in cache.iterdir():
            if directory.is_dir() and not linked(directory):
                for path in directory.glob("*.tmp"):
                    remove(path, set())
    return removed
