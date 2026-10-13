import os
from pathlib import Path

from filelock import UnixFileLock, WindowsFileLock


def native_lock(path: Path | str, timeout: float = 0):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    name = str(path)
    if os.name == "nt" and not name.startswith("\\\\?\\"):
        name = "\\\\?\\" + name
    factory = WindowsFileLock if os.name == "nt" else UnixFileLock
    return factory(name, timeout=timeout, fallback_to_soft=False)
