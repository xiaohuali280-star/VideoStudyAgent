from uuid import uuid4, uuid5

from app.core.errors import StudyError
from app.db.context_repository import VideoContextRepository, manifest
from app.db.study_repository import StudyRepository
from app.providers.ocr import TesseractOCR
from app.schemas.iteration import TranscriptSnapshot
from app.schemas.study import Transcript
from app.schemas.video_context import OcrObservation, VideoContextSegment, VideoContextSnapshot
from app.services.source_context import source_items
from app.services.storage import cache_key
from app.services.transcription import TranscriptService
from app.services.vision import extract_frames


class VideoContextService:
    def __init__(self, settings, repository, asr=None, ocr=None, frames=None):
        self.settings, self.repository = settings, repository
        self.transcription = TranscriptService(settings, repository, asr)
        self.store = self.transcription.store
        self.ocr = ocr or TesseractOCR(
            settings.ocr_binary, settings.ocr_language, settings.ocr_timeout
        )
        self.frames = frames or extract_frames

    def prepare_video_context(self, task):
        assets = self.transcription.assets(task)
        transcript, source = None, None
        warnings, frames, observations = [], [], []
        statuses = {"transcript": "empty", "ocr": "disabled"}
        try:
            if "subtitle" in assets:
                artifact = self.transcription.load_subtitles(task)
            else:
                self.transcription.extract_audio(task)
                artifact = self.transcription.transcribe_audio(task)
            transcript = self.store.read_json(artifact, Transcript)
            source = StudyRepository(self.repository.engine).add_snapshot(
                TranscriptSnapshot(
                    id=uuid4(),
                    task_id=task.id,
                    storage_key=artifact.storage_key,
                    sha256=artifact.sha256,
                    created_at=artifact.created_at,
                )
            )
            statuses["transcript"] = "succeeded"
        except StudyError as exc:
            if "subtitle" in assets or exc.code not in {
                "NO_AUDIO_TRACK",
                "EMPTY_TRANSCRIPT",
                "ASR_UNAVAILABLE",
                "ASR_FAILED",
                "ASR_TIMEOUT",
            }:
                raise
            if exc.code.startswith("ASR_"):
                statuses["transcript"] = "failed"
            warnings.append(exc.code)
        if task.options.enable_ocr and "video" in assets:
            try:
                frames = self.frames(task, assets["video"], self.settings)
                # Exact-image reuse only; approximate image hash cannot skip changed digits.
                recognized = {}
                for frame_index, frame in enumerate(frames, 1):
                    key = cache_key(
                        image=frame.sha256, engine=self.ocr.version, language=self.ocr.language
                    )
                    if key not in recognized:
                        recognized[key] = self.ocr.recognize(self.store.verify(frame))
                    for index, word in enumerate(recognized[key]):
                        observation_id = str(uuid5(frame.id, cache_key(index=index, word=word)))
                        observations.append(
                            OcrObservation(
                                id=observation_id,
                                frame_id=frame.id,
                                engine_version=self.ocr.version,
                                language=self.ocr.language,
                                status="succeeded",
                                **word,
                            )
                        )
                    operation_id = getattr(self.repository, "operation_id", None)
                    if operation_id:
                        StudyRepository(self.repository.engine).progress(
                            task.id,
                            operation_id,
                            "ocr",
                            completed_units=frame_index,
                            total_units=len(frames),
                        )
                statuses["ocr"] = "succeeded" if observations else "empty"
            except StudyError as exc:
                statuses["ocr"] = "failed"
                warnings.append(exc.code)
        elif task.options.enable_ocr:
            warnings.append("OCR_NO_VIDEO")
        if not transcript and not observations:
            raise StudyError(
                "CONTEXT_EMPTY", "语音与画面均无可用内容，请提供字幕或检查 OCR。", 422, True
            )
        payload = dict(
            id=uuid4(),
            task_id=task.id,
            video_asset_id=assets["video"].id if "video" in assets else None,
            transcript_snapshot_id=source.id if source else None,
            transcript=transcript,
            frames=frames,
            observations=observations,
            segments=[],
            branch_statuses=statuses,
            warnings=warnings,
            manifest_sha256="0" * 64,
        )
        context = VideoContextSnapshot(**payload)
        context.segments = [
            VideoContextSegment(
                id=f"ctx-{index}",
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                transcript_segment_ids=[item["source_id"]]
                if item["source_type"] == "transcript"
                else [],
                ocr_observation_ids=[item["source_id"]] if item["source_type"] == "ocr" else [],
                frame_ids=[item["frame_id"]] if item["frame_id"] else [],
                source_types=[item["source_type"]],
            )
            for index, item in enumerate(source_items(context), 1)
        ]
        context.manifest_sha256 = manifest(context)
        context.id = uuid5(task.id, context.manifest_sha256)
        VideoContextRepository(self.repository.engine).add(context)
        return self.store.put_json(
            task.id, "context", context, cache_key(context=context.manifest_sha256)
        )
