import re
from pathlib import Path

import srt
import webvtt

from app.core.errors import StudyError
from app.schemas.study import Transcript, TranscriptSegment
from app.services.uploads import decode_subtitle


def parse_subtitles(path: Path, language: str, max_duration_ms: int) -> Transcript:
    try:
        text = decode_subtitle(path.read_bytes()).replace("\r\n", "\n").replace("\r", "\n")
        # Validate timestamp fields before library normalization can carry invalid minutes.
        for line in text.splitlines():
            if "-->" in line:
                stamps = re.findall(r"\d{1,3}:\d{2}(?::\d{2})?[,.]\d{3}", line)
                if len(stamps) != 2:
                    raise ValueError("invalid timing")
                for stamp in stamps:
                    parts = stamp.replace(",", ".").split(":")
                    if float(parts[-1]) >= 60 or (len(parts) == 3 and int(parts[-2]) >= 60):
                        raise ValueError("invalid timestamp range")
        if path.suffix.lower() == ".srt":
            cues = [
                (
                    round(cue.start.total_seconds() * 1000),
                    round(cue.end.total_seconds() * 1000),
                    cue.content,
                )
                for cue in srt.parse(text)
            ]
        else:
            cues = [
                (round(cue.start_in_seconds * 1000), round(cue.end_in_seconds * 1000), cue.text)
                for cue in webvtt.from_string(text)
            ]
        if not cues:
            raise StudyError("EMPTY_TRANSCRIPT", "字幕没有可用内容。", 422)
        # Preserve fractional VTT milliseconds (some library versions expose whole seconds).
        if path.suffix.lower() == ".vtt":

            def milliseconds(stamp):
                h, m, s = stamp.split(":")
                return round((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)

            cues = [
                (milliseconds(cue.start), milliseconds(cue.end), cue.text)
                for cue in webvtt.from_string(text)
            ]
        segments = [
            TranscriptSegment(id=f"seg_{index:05d}", start_ms=start, end_ms=end, text=content)
            for index, (start, end, content) in enumerate(sorted(cues), 1)
        ]
        duration = max(segment.end_ms for segment in segments)
        if duration > max_duration_ms:
            raise StudyError("DURATION_EXCEEDED", "字幕时间轴超过课程时长限制。", 422)
        return Transcript(
            source="subtitle", language=language, duration_ms=duration, segments=segments
        )
    except StudyError:
        raise
    except Exception as exc:
        raise StudyError("INVALID_SUBTITLE", "字幕语法或时间轴无效。", 422) from exc
