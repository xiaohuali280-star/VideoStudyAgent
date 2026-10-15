import os
import tempfile
from pathlib import Path
from typing import get_args

from sqlalchemy import inspect

from app.adapters.grounding import validate_notes, validate_quiz
from app.core.errors import StudyError
from app.db.repository import TaskRepository
from app.db.study_repository import StudyRepository
from app.schemas.common import ExportFormat
from app.schemas.iteration import ProcessingOptions
from app.schemas.study import NotesDocument, QuizDocument, Transcript
from app.schemas.tasks import ArtifactSummary, StudyResult
from app.services.quiz_documents import QuizReader
from app.services.storage import ArtifactStore
from app.services.study_versions import VersionReader

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
                + (
                    context_times(chapter.source_refs, transcript)
                    if hasattr(chapter, "source_refs")
                    else source_times(chapter.source_segment_ids, transcript)
                ),
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
                + (
                    context_times(question.source_refs, transcript)
                    if hasattr(question, "source_refs")
                    else source_times(question.source_segment_ids, transcript)
                ),
            ]
        )
        for evidence in question.evidence:
            lines.extend(["", *["> " + line for line in evidence.quote.splitlines()]])
        lines.append("")
    return "\n".join(lines)


def context_times(refs, context):
    from app.services.source_context import source_items

    sources = {(s["source_type"], s["source_id"]): s for s in source_items(context)}
    return ", ".join(
        f"{ref.source_type} {timestamp(sources[(ref.source_type, ref.source_id)]['start_ms'])}"
        for ref in refs
    )


class ResultService:
    def __init__(self, root: Path, repository: TaskRepository):
        self.repository = repository
        self.store = ArtifactStore(root, repository)

    def result(self, task_id):
        task = self.repository.get(task_id)
        if "course_study_states" in inspect(self.repository.engine).get_table_names():
            study = StudyRepository(self.repository.engine)
            state = study.state(task_id)
            if state.context_snapshot_id:
                from app.db.context_repository import VideoContextRepository
                from app.services.source_context import validate_context_document

                context = VideoContextRepository(study.engine).get(
                    task_id, state.context_snapshot_id
                )
                reader = VersionReader(self.store.root)
                notes = (
                    reader.notes(study.notes(task_id, state.notes_revision_id))
                    if state.notes_revision_id
                    else None
                )
                quiz = (
                    reader.quiz(study.batch(task_id, state.quiz_batch_id))
                    if state.quiz_batch_id
                    else None
                )
                if notes:
                    validate_context_document(notes, context, require_coverage=True)
                if quiz:
                    batch = study.batch(task_id, state.quiz_batch_id)
                    basis = (
                        reader.notes(study.notes(task_id, batch.notes_revision_id))
                        if batch.notes_revision_id
                        else None
                    )
                    validate_context_document(quiz, context, notes=basis)
                return StudyResult(
                    task_id=task.id,
                    transcript=context.transcript,
                    context=context,
                    notes=notes,
                    quiz=quiz,
                )
            if state.transcript_snapshot_id:
                reader = VersionReader(self.store.root)
                source = study.snapshot(task_id, state.transcript_snapshot_id)
                transcript = reader.transcript(source)
                notes = (
                    reader.notes(study.notes(task_id, state.notes_revision_id))
                    if state.notes_revision_id
                    else None
                )
                quiz = None
                if notes:
                    validate_notes(notes, transcript)
                if state.quiz_batch_id:
                    batch = study.batch(task_id, state.quiz_batch_id)
                    quiz = reader.quiz(batch)
                    basis = (
                        reader.notes(study.notes(task_id, batch.notes_revision_id))
                        if batch.notes_revision_id
                        else None
                    )
                    validate_quiz(
                        quiz,
                        transcript,
                        basis,
                        task.options.model_copy(
                            update={
                                "question_count": batch.question_count,
                                "difficulty": batch.difficulty,
                            }
                        ),
                    )
                return StudyResult(task_id=task.id, transcript=transcript, notes=notes, quiz=quiz)
        artifacts = {artifact.kind: artifact for artifact in self.repository.artifacts(task_id)}
        if "context" in artifacts:
            from app.schemas.video_context import VideoContextSnapshot

            context = self.store.read_json(artifacts["context"], VideoContextSnapshot)
            # Unpublished candidates are never exposed by the current-result projection.
            return StudyResult(task_id=task.id, context=context, transcript=context.transcript)
        values = {}
        try:
            for kind, schema in [
                ("transcript", Transcript),
                ("notes", NotesDocument),
                ("quiz", QuizReader),
            ]:
                if kind in artifacts:
                    values[kind] = self.store.read_json(artifacts[kind], schema)
            if "notes" in values:
                validate_notes(values["notes"], values["transcript"])
            if "quiz" in values:
                validate_quiz(
                    values["quiz"], values["transcript"], values.get("notes"), task.options
                )
            if task.status == "succeeded" and not ProcessingOptions(
                generate_notes=task.options.generate_notes, generate_quiz=task.options.generate_quiz
            ).required_artifacts() <= set(values):
                raise ValueError("Completed task has missing artifacts")
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

    def export(self, task_id, format: str, quiz_batch_id=None, notes_revision_id=None) -> Path:
        if format not in FORMATS:
            raise StudyError("NOT_FOUND", "未找到该导出格式。", 404)
        task = self.repository.get(task_id)
        selection = quiz_batch_id or notes_revision_id
        if (
            (quiz_batch_id and notes_revision_id)
            or (quiz_batch_id and not format.startswith("quiz"))
            or (notes_revision_id and format != "notes.md")
        ):
            raise StudyError("VALIDATION_ERROR", "导出格式与所选资料版本不匹配。", 422)
        if selection:
            study = StudyRepository(self.repository.engine)
            reader = VersionReader(self.store.root)
            record = (
                study.batch(task_id, quiz_batch_id)
                if quiz_batch_id
                else study.notes(task_id, notes_revision_id)
            )
            if record.context_snapshot_id:
                from app.db.context_repository import VideoContextRepository
                from app.services.source_context import validate_context_document

                context = VideoContextRepository(study.engine).get(
                    task_id, record.context_snapshot_id
                )
                document = reader.quiz(record) if quiz_batch_id else reader.notes(record)
                basis = (
                    reader.notes(study.notes(task_id, record.notes_revision_id))
                    if quiz_batch_id and record.notes_revision_id
                    else None
                )
                validate_context_document(
                    document, context, require_coverage=not quiz_batch_id, notes=basis
                )
                result = StudyResult(
                    task_id=task.id,
                    context=context,
                    transcript=context.transcript,
                    **({"quiz": document} if quiz_batch_id else {"notes": document}),
                )
                return self._export_document(task, result, format, selection)
            transcript = reader.transcript(study.snapshot(task_id, record.transcript_snapshot_id))
            if quiz_batch_id:
                document = reader.quiz(record)
                basis = (
                    reader.notes(study.notes(task_id, record.notes_revision_id))
                    if record.notes_revision_id
                    else None
                )
                validate_quiz(
                    document,
                    transcript,
                    basis,
                    task.options.model_copy(
                        update={
                            "question_count": record.question_count,
                            "difficulty": record.difficulty,
                        }
                    ),
                )
                result = StudyResult(task_id=task.id, transcript=transcript, quiz=document)
            else:
                document = reader.notes(record)
                validate_notes(document, transcript)
                result = StudyResult(task_id=task.id, transcript=transcript, notes=document)
        else:
            result = self.result(task_id)
        return self._export_document(task, result, format, selection)

    def _export_document(self, task, result, format, selection):
        required = (
            "notes"
            if format == "notes.md"
            else "quiz"
            if format.startswith("quiz")
            else "transcript"
        )
        document = getattr(result, required)
        if document is None:
            raise StudyError("RESULT_NOT_READY", "对应学习资料尚未生成。", 409)
        if format.endswith(".json"):
            content = document.model_dump_json(indent=2) + "\n"
        elif format == "notes.md":
            content = notes_markdown(
                document, result.context or result.transcript, task.options.output_language
            )
        elif format == "quiz.md":
            content = quiz_markdown(
                document, result.context or result.transcript, task.options.output_language
            )
        else:
            content = (
                "\n\n".join(
                    f"{index}\n{timestamp(segment.start_ms, True)} --> "
                    f"{timestamp(segment.end_ms, True)}\n{segment.text}"
                    for index, segment in enumerate(result.transcript.segments, 1)
                )
                + "\n"
            )
        path = self.store.path(f"tasks/{task.id}/exports/{selection or 'current'}/{format}")
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
