from app.core.config import Settings
from app.core.errors import StudyError
from app.db.repository import TaskRepository
from app.providers.asr import ProcessASR, model_fingerprint
from app.schemas.study import Transcript
from app.schemas.tasks import Task
from app.services.media import extract_audio, probe_video
from app.services.storage import ArtifactStore, cache_key
from app.services.subtitles import parse_subtitles


class TranscriptService:
    def __init__(self, settings: Settings, repository: TaskRepository, asr=None):
        self.settings, self.repository = settings, repository
        self.store = ArtifactStore(settings.data_dir, repository)
        self.asr = asr or ProcessASR(settings)

    def assets(self, task: Task):
        return {asset.kind: asset for asset in self.repository.assets(task.id)}

    def load_subtitles(self, task: Task):
        assets = self.assets(task)
        if "subtitle" not in assets:
            raise StudyError("TOOL_PRECONDITION", "当前任务没有字幕。", 409)
        asset = assets["subtitle"]
        path = self.store.verify(asset)
        language = task.options.transcript_language or "und"
        key = cache_key(
            tool="subtitle-v1",
            sha=asset.sha256,
            language=language,
            limit=self.settings.max_duration_ms,
        )
        transcript = parse_subtitles(path, language, self.settings.max_duration_ms)
        if "video" in assets:
            duration = probe_video(self.store.verify(assets["video"]), self.settings, False)
            if transcript.duration_ms > duration + self.settings.subtitle_tolerance_ms:
                raise StudyError("SUBTITLE_VIDEO_MISMATCH", "字幕时间超出视频范围。", 422)
        cached = self.store.reuse(task.id, "transcript", key, Transcript)
        return cached or self.store.put_json(task.id, "transcript", transcript, key)

    def extract_audio(self, task: Task):
        assets = self.assets(task)
        if "subtitle" in assets or "video" not in assets:
            raise StudyError("TOOL_PRECONDITION", "该任务应使用字幕或缺少视频。", 409)
        asset = assets["video"]
        path = self.store.verify(asset)
        probe_video(path, self.settings)
        key = cache_key(
            tool="audio-v1",
            sha=asset.sha256,
            hz=16000,
            channels=1,
            limit=self.settings.max_duration_ms,
        )
        cached = self.store.reuse(task.id, "audio", key)
        if cached:
            return cached
        target = self.settings.data_dir / "tasks" / str(task.id) / "tmp" / "audio.wav"
        try:
            extract_audio(path, target, self.settings)
            return self.store.put_file(task.id, "audio", target, ".wav", key)
        finally:
            target.unlink(missing_ok=True)

    def transcribe_audio(self, task: Task):
        if "subtitle" in self.assets(task):
            raise StudyError("TOOL_PRECONDITION", "提供字幕时不调用语音识别。", 409)
        artifacts = {item.kind: item for item in self.repository.artifacts(task.id)}
        if "audio" not in artifacts:
            raise StudyError("TOOL_PRECONDITION", "请先提取音频。", 409)
        audio = artifacts["audio"]
        fingerprint = (
            model_fingerprint(self.settings) if isinstance(self.asr, ProcessASR) else "fake"
        )
        key = cache_key(
            tool="asr-v1",
            sha=audio.sha256,
            weights=fingerprint,
            language=task.options.transcript_language,
            device=self.settings.asr_device,
            compute=self.settings.asr_compute_type,
        )
        cached = self.store.reuse(task.id, "transcript", key, Transcript)
        if cached:
            return cached
        result = self.asr.transcribe(self.store.verify(audio), task.options.transcript_language)
        if result.duration_ms > self.settings.max_duration_ms:
            raise StudyError("DURATION_EXCEEDED", "转写时间超过课程限制。", 422)
        return self.store.put_json(task.id, "transcript", result, key)
