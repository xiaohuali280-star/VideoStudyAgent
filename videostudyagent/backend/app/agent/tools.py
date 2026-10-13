from time import monotonic
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.adapters.grounding import validate_notes, validate_quiz
from app.adapters.tool_args import missing_args_message, unsatisfied_required_args
from app.core.errors import StudyError
from app.db.repository import now
from app.schemas.common import ContractModel, ErrorInfo
from app.schemas.providers import ToolCall, ToolDefinition
from app.schemas.study import NotesDocument, QuizDocument, Transcript
from app.schemas.tasks import TaskStep
from app.services.generation import GenerationService
from app.services.transcription import TranscriptService


class EmptyArgs(ContractModel):
    pass


class AudioArgs(ContractModel):
    audio_artifact_id: UUID


class TranscriptArgs(ContractModel):
    transcript_artifact_id: UUID


class QuizArgs(TranscriptArgs):
    notes_artifact_id: UUID


SPECS = {
    "load_subtitles": (
        EmptyArgs,
        "有字幕时加载字幕，得到 transcript；参数为空。",
        "transcript",
        {},
    ),
    "extract_audio": (EmptyArgs, "只有视频且无字幕时提取 audio；参数为空。", "audio", {}),
    "transcribe_audio": (
        AudioArgs,
        "从当前任务 audio 生成 transcript。",
        "transcript",
        {"audio_artifact_id": "audio"},
    ),
    "generate_notes": (
        TranscriptArgs,
        "从已验证 transcript 生成 notes。",
        "notes",
        {"transcript_artifact_id": "transcript"},
    ),
    "generate_quiz": (
        QuizArgs,
        "从已验证 transcript 和 notes 生成 quiz，选项由服务端固定。",
        "quiz",
        {"transcript_artifact_id": "transcript", "notes_artifact_id": "notes"},
    ),
}


def definitions():
    return [
        ToolDefinition(name=name, description=spec[1], parameters=spec[0].model_json_schema())
        for name, spec in SPECS.items()
    ]


class StudyTools:
    def __init__(self, task, settings, repository, llm, asr=None):
        self.task, self.settings, self.repository = task, settings, repository
        self.transcription = TranscriptService(settings, repository, asr)
        self.generation = GenerationService(settings, repository, llm)
        self.store = self.transcription.store

    def valid_artifacts(self):
        stored = {item.kind: item for item in self.repository.artifacts(self.task.id)}
        valid, documents = {}, {}
        for kind, schema in [
            ("audio", None),
            ("transcript", Transcript),
            ("notes", NotesDocument),
            ("quiz", QuizDocument),
        ]:
            if kind not in stored:
                continue
            try:
                artifact = stored[kind]
                if schema:
                    value = self.store.read_json(artifact, schema)
                    if kind == "notes":
                        validate_notes(value, documents["transcript"])
                    if kind == "quiz":
                        validate_quiz(
                            value, documents["transcript"], documents["notes"], self.task.options
                        )
                    documents[kind] = value
                else:
                    self.store.verify(artifact)
                valid[kind] = artifact
            except (StudyError, ValueError, KeyError, OSError):
                continue
        return valid

    def state(self):
        assets = self.transcription.assets(self.task)
        return {
            "has_subtitle": "subtitle" in assets,
            "has_video": "video" in assets,
            "options": self.task.options.model_dump(),
            "artifacts": {kind: str(item.id) for kind, item in self.valid_artifacts().items()},
        }

    def complete(self):
        return {"transcript", "notes", "quiz"} <= self.valid_artifacts().keys()

    async def execute(self, call: ToolCall, sequence: int):
        start = monotonic()
        name = call.name if call.name in SPECS else "unknown"
        step = TaskStep(
            id=uuid4(),
            task_id=self.task.id,
            attempt=self.task.attempt,
            tool_name=name,
            sequence=sequence,
            status="running",
            started_at=now(),
        )
        self.repository.save_step(step)
        try:
            if name == "unknown":
                raise StudyError("UNKNOWN_TOOL", "工具不在允许列表中。", 422)
            schema, _, output_kind, required = SPECS[name]
            definition = next(item for item in definitions() if item.name == name)
            absent, blank = unsatisfied_required_args(definition, call.arguments)
            if absent or blank:
                raise StudyError(
                    "INVALID_TOOL_ARGUMENTS", missing_args_message(name, absent, blank), 422
                )
            try:
                arguments = schema.model_validate(call.arguments)
            except ValidationError:
                raise StudyError(
                    "INVALID_TOOL_ARGUMENTS", "参数类型错误或包含额外字段。", 422
                ) from None
            available = self.valid_artifacts()
            for field, kind in required.items():
                if kind not in available:
                    raise StudyError("TOOL_PRECONDITION", "所需产物尚未完成。", 409)
                if getattr(arguments, field) != available[kind].id:
                    raise StudyError("TOOL_FORBIDDEN", "只能引用当前任务的已验证产物。", 422)
            if name == "extract_audio" and self.state()["has_subtitle"]:
                raise StudyError("TOOL_PRECONDITION", "已有字幕，应优先使用字幕。", 409)
            if name == "transcribe_audio" and self.state()["has_subtitle"]:
                raise StudyError("TOOL_PRECONDITION", "已有字幕，不调用语音识别。", 409)
            if name == "load_subtitles" and not self.state()["has_subtitle"]:
                raise StudyError("TOOL_PRECONDITION", "该任务没有字幕。", 409)
            if output_kind in available:
                artifact = available[output_kind]
                step.status = "skipped"
                cache_hit = False
            else:
                owner = self.generation if name.startswith("generate_") else self.transcription
                action = getattr(owner, name)
                result = action(self.task)
                artifact = await result if name.startswith("generate_") else result
                step.status = "succeeded"
                cache_hit = getattr(owner.store, "last_cache_hit", False)
            step.artifact_id, step.cache_key = artifact.id, artifact.cache_key
            step.cache_hit = cache_hit
            return {
                "ok": True,
                "artifact_id": str(artifact.id),
                "kind": artifact.kind,
                "summary": "产物已验证。",
                "cache_hit": cache_hit,
                "error": None,
            }
        except StudyError as exc:
            step.status = "failed"
            step.error = ErrorInfo(
                code=exc.code, message=exc.message, step=name, retryable=exc.retryable
            )
            raise
        except Exception:
            step.status = "failed"
            step.error = ErrorInfo(
                code="INTERNAL_ERROR", message="工具执行未完成。", step=name, retryable=True
            )
            raise StudyError("INTERNAL_ERROR", "工具执行未完成。", 500, True, name) from None
        finally:
            step.finished_at = now()
            step.duration_ms = round((monotonic() - start) * 1000)
            self.repository.save_step(step)
