import json
import math
import shutil
import subprocess
from pathlib import Path

from app.core.config import PROJECT_ROOT, Settings
from app.core.errors import StudyError


def media_binary(configured: str) -> str:
    found = shutil.which(configured)
    if found:
        return found
    if Path(configured).is_file():
        return str(Path(configured).resolve())
    if configured in {"ffmpeg", "ffprobe"}:
        bundled = sorted((PROJECT_ROOT / ".tools" / "ffmpeg").glob(f"*/bin/{configured}.exe"))
        if bundled:
            return str(bundled[-1])
    raise StudyError("MEDIA_UNAVAILABLE", "请配置 FFmpeg 和 FFprobe。", 503, True)


def run_media(binary: str, arguments: list[str], timeout: int):
    try:
        result = subprocess.run(
            [media_binary(binary), *arguments],
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise StudyError("MEDIA_TIMEOUT", "媒体处理超时，请重试。", 422, True) from exc
    if result.returncode != 0:
        raise StudyError("UNSUPPORTED_MEDIA", "媒体无法解码或已损坏。", 422)
    return result.stdout


def probe_video(path: Path, settings: Settings, require_audio: bool = True) -> int:
    output = run_media(
        settings.ffprobe_binary,
        [
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        settings.media_probe_timeout,
    )
    try:
        info = json.loads(output)
        duration = float(info["format"]["duration"])
        streams = info["streams"]
        if not math.isfinite(duration) or duration <= 0 or not streams:
            raise ValueError("invalid duration")
        duration_ms = round(duration * 1000)
    except (ValueError, KeyError, TypeError) as exc:
        raise StudyError("UNSUPPORTED_MEDIA", "媒体缺少有效时长或音视频流。", 422) from exc
    if duration_ms > settings.max_duration_ms:
        raise StudyError("DURATION_EXCEEDED", "视频超过课程时长限制。", 422)
    if require_audio and not any(stream.get("codec_type") == "audio" for stream in streams):
        raise StudyError("NO_AUDIO_TRACK", "视频没有音轨，请提供字幕。", 422)
    return duration_ms


def extract_audio(path: Path, target: Path, settings: Settings):
    probe_video(path, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_media(
            settings.ffmpeg_binary,
            [
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                str(target),
            ],
            settings.media_extract_timeout,
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise
