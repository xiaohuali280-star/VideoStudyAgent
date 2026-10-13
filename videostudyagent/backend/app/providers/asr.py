"""B2: adapted from BiliNote whisper.py, MIT (see THIRD_PARTY_NOTICES.md).

Modified: local-only loading, injected configuration, strict millisecond DTOs,
no event bus/cache deletion/downloads/exception prints; timeout in child process.
"""

import json
import subprocess
import sys
from pathlib import Path

from app.core.config import PROJECT_ROOT, Settings
from app.core.errors import StudyError
from app.schemas.study import Transcript, TranscriptSegment
from app.services.storage import cache_key, file_hash


def model_path(settings: Settings) -> Path:
    path = settings.asr_model_path or settings.data_dir / "models" / settings.asr_model
    path = path if path.is_absolute() else PROJECT_ROOT / path
    if not (path / "model.bin").is_file():
        raise StudyError("ASR_UNAVAILABLE", "请先准备本地 ASR 模型。", 503, True)
    return path.resolve()


def model_fingerprint(settings: Settings) -> str:
    path = model_path(settings)
    files = {item.name: file_hash(item) for item in sorted(path.iterdir()) if item.is_file()}
    return cache_key(files=files)


class LocalWhisper:
    def __init__(self, settings: Settings, model_factory=None):
        self.settings = settings
        if model_factory is None:
            try:
                from faster_whisper import WhisperModel

                model_factory = WhisperModel
            except ImportError as exc:
                raise StudyError("ASR_UNAVAILABLE", "请安装 ASR 可选依赖。", 503, True) from exc
        try:
            self.model = model_factory(
                model_size_or_path=str(model_path(settings)),
                device=settings.asr_device,
                compute_type=settings.asr_compute_type,
                cpu_threads=settings.asr_cpu_threads,
                local_files_only=True,
            )
        except StudyError:
            raise
        except Exception as exc:
            raise StudyError("ASR_UNAVAILABLE", "本地模型无法加载。", 503, True) from exc

    def transcribe(self, path: Path, language: str | None = None) -> Transcript:
        try:
            raw, info = self.model.transcribe(
                str(path),
                language=language.split("-")[0].lower() if language else None,
                vad_filter=True,
                beam_size=5,
            )
            segments = [
                TranscriptSegment(
                    id=f"seg_{index:05d}",
                    start_ms=round(segment.start * 1000),
                    end_ms=round(segment.end * 1000),
                    text=segment.text.strip(),
                )
                for index, segment in enumerate(raw, 1)
                if segment.text.strip()
            ]
            if not segments:
                raise StudyError("EMPTY_TRANSCRIPT", "音频没有可识别语音。", 422)
            return Transcript(
                source="asr",
                language=info.language,
                duration_ms=max(
                    round(info.duration * 1000), max(segment.end_ms for segment in segments)
                ),
                segments=segments,
            )
        except StudyError:
            raise
        except Exception as exc:
            raise StudyError("ASR_FAILED", "语音转写失败，请检查音频和模型。", 422, True) from exc


class ProcessASR:
    def __init__(self, settings: Settings):
        self.settings = settings

    def transcribe(self, path: Path, language: str | None = None) -> Transcript:
        payload = {
            "path": str(path),
            "language": language,
            "model_path": str(model_path(self.settings)),
            "device": self.settings.asr_device,
            "compute_type": self.settings.asr_compute_type,
            "cpu_threads": self.settings.asr_cpu_threads,
        }
        try:
            result = subprocess.run(
                [sys.executable, "-m", "app.providers.asr_cli"],
                input=json.dumps(payload).encode(),
                capture_output=True,
                timeout=self.settings.asr_timeout,
                cwd=Path(__file__).resolve().parents[2],
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise StudyError("ASR_TIMEOUT", "语音转写超时，可稍后重试。", 422, True) from exc
        try:
            if result.returncode:
                error = json.loads(result.stdout)
                code = error.get("code")
                if code not in {"EMPTY_TRANSCRIPT", "ASR_UNAVAILABLE", "ASR_FAILED"}:
                    raise ValueError("unknown child error")
                raise StudyError(
                    code, "语音转写未完成，请检查本地模型或音频。", 422, code != "EMPTY_TRANSCRIPT"
                )
            return Transcript.model_validate_json(result.stdout)
        except StudyError:
            raise
        except (ValueError, TypeError) as exc:
            raise StudyError("ASR_FAILED", "语音进程未返回有效结果。", 422, True) from exc
