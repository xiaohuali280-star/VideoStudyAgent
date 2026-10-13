import os
import tempfile
from pathlib import Path
from typing import get_args

from app.adapters.grounding import validate_notes, validate_quiz
from app.core.errors import StudyError
from app.db.repository import TaskRepository
from app.schemas.common import ExportFormat
from app.schemas.study import NotesDocument, QuizDocument, Transcript
from app.schemas.tasks import ArtifactSummary, StudyResult
from app.services.storage import ArtifactStore

FORMATS = set(get_args(ExportFormat))


def timestamp(milliseconds: int, srt: bool = False):
    seconds, remainder = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    result = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return result + f",{remainder:03d}" if srt else result


def source_times(ids, transcript: Transcript):
    source = {segment.id: segment for segment in transcript.segments}
    return ", ".join(
        f"{timestamp(source[i].start_ms)}–{timestamp(source[i].end_ms)}" for i in dict.fromkeys(ids)
    )


def notes_markdown(notes: NotesDocument, transcript: Transcript, language: str):
    en = language.startswith("en")
    lines = [f"# {notes.title}", "", "## Learning objectives" if en else "## 学习目标", ""]
    lines.extend(f"- {item}" for item in notes.learning_objectives)
    for chapter in notes.chapters:
        lines.extend(
            [
                "",
                f"## {chapter.title}",
                "",
                chapter.content_markdown,
                "",
                ("Source: " if en else "来源：")
                + source_times(chapter.source_segment_ids, transcript),
            ]
        )
    lines.extend(["", "## Key concepts" if en else "## 核心概念", ""])
    lines.extend(f"- {item}" for item in notes.key_concepts)
    lines.extend(["", "## Summary" if en else "## 课程总结", "", notes.summary, ""])
    return "\n".join(lines)


def quiz_markdown(quiz: QuizDocument, transcript: Transcript, language: str):
    en = language.startswith("en")
    lines = ["# Self-check" if en else "# 课程自测", ""]
    for index, question in enumerate(quiz.questions, 1):
        lines.extend(
            [
                f"## {index}. {question.question}",
                "",
                "### Answer" if en else "### 参考答案",
                "",
                question.answer,
                "",
                "### Explanation" if en else "### 解析",
                "",
                question.explanation,
                "",
                ("Source: " if en else "来源：")
                + source_times(question.source_segment_ids, transcript),
            ]
        )
        for evidence in question.evidence:
            lines.extend(["", *["> " + line for line in evidence.quote.splitlines()]])
        lines.append("")
    return "\n".join(lines)


class ResultService:
    def __init__(self, root: Path, repository: TaskRepository):
        self.repository = repository
        self.store = ArtifactStore(root, repository)

    def result(self, task_id):
        task = self.repository.get(task_id)
        artifacts = {artifact.kind: artifact for artifact in self.repository.artifacts(task_id)}
        values = {}
        try:
            for kind, schema in [
                ("transcript", Transcript),
                ("notes", NotesDocument),
                ("quiz", QuizDocument),
            ]:
                if kind in artifacts:
                    values[kind] = self.store.read_json(artifacts[kind], schema)
            if "notes" in values:
                validate_notes(values["notes"], values["transcript"])
            if "quiz" in values:
                validate_quiz(values["quiz"], values["transcript"], values["notes"], task.options)
        except (ValueError, KeyError) as exc:
            raise StudyError(
                "STORAGE_ERROR", "学习结果未通过校验，可重新处理。", 409, True
            ) from exc
        return StudyResult(
            task_id=task.id,
            **values,
            available_artifacts=[
                ArtifactSummary(
                    id=artifact.id,
                    task_id=artifact.task_id,
                    kind=artifact.kind,
                    created_at=artifact.created_at,
                )
                for artifact in artifacts.values()
                if artifact.kind in values
            ],
        )

    def export(self, task_id, format: str) -> Path:
        if format not in FORMATS:
            raise StudyError("NOT_FOUND", "未找到该导出格式。", 404)
        task = self.repository.get(task_id)
        result = self.result(task_id)
        required = (
            "notes"
            if format == "notes.md"
            else "quiz"
            if format.startswith("quiz")
            else "transcript"
        )
        document = getattr(result, required)
        if document is None or result.transcript is None:
            raise StudyError("RESULT_NOT_READY", "对应学习资料尚未生成。", 409)
        if format.endswith(".json"):
            content = document.model_dump_json(indent=2) + "\n"
        elif format == "notes.md":
            content = notes_markdown(document, result.transcript, task.options.output_language)
        elif format == "quiz.md":
            content = quiz_markdown(document, result.transcript, task.options.output_language)
        else:
            content = (
                "\n\n".join(
                    f"{index}\n{timestamp(segment.start_ms, True)} --> "
                    f"{timestamp(segment.end_ms, True)}\n{segment.text}"
                    for index, segment in enumerate(result.transcript.segments, 1)
                )
                + "\n"
            )
        path = self.store.path(f"tasks/{task.id}/exports/{format}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(content.encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path
