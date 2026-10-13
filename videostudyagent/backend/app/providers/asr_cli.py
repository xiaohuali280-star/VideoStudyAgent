import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.core.errors import StudyError
from app.providers.asr import LocalWhisper


def main():
    try:
        payload = json.load(sys.stdin)
        settings = Settings(
            _env_file=None,
            asr_model_path=Path(payload["model_path"]),
            asr_device=payload["device"],
            asr_compute_type=payload["compute_type"],
            asr_cpu_threads=payload["cpu_threads"],
        )
        result = LocalWhisper(settings).transcribe(Path(payload["path"]), payload["language"])
        sys.stdout.buffer.write(result.model_dump_json().encode("utf-8"))
    except Exception as exc:
        code = exc.code if isinstance(exc, StudyError) else "ASR_FAILED"
        sys.stdout.write(json.dumps({"code": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
