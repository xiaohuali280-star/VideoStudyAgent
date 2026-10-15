"""Bounded scene/maximum-gap extraction using actual FFmpeg PTS."""

import re
import struct
import subprocess
from uuid import uuid5

from app.core.errors import StudyError
from app.schemas.video_context import EvidenceFrame
from app.services.media import media_binary, probe_video
from app.services.storage import ArtifactStore, cache_key, file_hash


def extract_frames(task, asset, settings):
    store = ArtifactStore(settings.data_dir, None)
    source = store.verify(asset)
    probe_video(source, settings, require_audio=False)
    directory = store.path(f"tasks/{task.id}/tmp/vision")
    directory.mkdir(parents=True, exist_ok=True)
    # Never infer frame time from output sequence. showinfo reports original input PTS.
    selection = (
        "select='isnan(prev_selected_t)+gte(t-prev_selected_t,"
        f"{settings.ocr_gap_seconds})+gt(scene,0.35)'"
    )
    args = [
        media_binary(settings.ffmpeg_binary),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        str(source),
        "-an",
        "-vf",
        selection + ",scale='min(1280,iw)':-2,showinfo",
        "-fps_mode",
        "vfr",
        "-frames:v",
        str(settings.ocr_max_frames + 1),
        str(directory / "frame-%06d.png"),
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=settings.media_extract_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise StudyError("MEDIA_TIMEOUT", "关键帧提取超时。", 422, True) from None
    if result.returncode:
        raise StudyError("UNSUPPORTED_MEDIA", "关键帧提取失败。", 422)
    times = re.findall(rb"\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:([0-9.eE+-]+)", result.stderr)
    paths = sorted(directory.glob("frame-*.png"))
    if len(paths) > settings.ocr_max_frames:
        raise StudyError("OCR_FRAME_LIMIT", "画面数量超过本地 OCR 上限，请缩短课程。", 422)
    if len(times) != len(paths) or not paths:
        raise StudyError("FRAME_TIMESTAMP_MISSING", "关键帧缺少可靠时间戳。", 422)
    frames = []
    for path, seconds in zip(paths, times, strict=True):
        timestamp = round(float(seconds) * 1000)
        digest = file_hash(path)
        frame_id = uuid5(
            task.id,
            cache_key(video=asset.sha256, pts=timestamp, image=digest, version="pts-scene-v1"),
        )
        key = f"tasks/{task.id}/frames/{frame_id}.png"
        store._atomic_copy(path, store.path(key))
        width, height = struct.unpack(">II", path.read_bytes()[16:24])
        frames.append(
            EvidenceFrame(
                id=frame_id,
                task_id=task.id,
                video_asset_sha256=asset.sha256,
                timestamp_ms=timestamp,
                storage_key=key,
                sha256=digest,
                width=width,
                height=height,
            )
        )
    return frames
