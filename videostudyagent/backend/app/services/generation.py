import json
from collections import Counter

from pydantic import ValidationError

from app.adapters.chunking import transcript_chunks
from app.adapters.grounding import normalized, validate_notes, validate_quiz
from app.core.config import Settings
from app.core.errors import StudyError
from app.db.repository import TaskRepository
from app.prompts.study import DIFFICULTY, NOTE_SYSTEM, PROMPT_VERSION, QUIZ_SYSTEM
from app.providers.budget import BoundedLLM
from app.providers.deepseek import DeepSeekClient
from app.schemas.providers import ChatMessage, ModelRequest
from app.schemas.study import NotesDocument, QuizDocument, QuizDocumentV11, QuizPartV11, Transcript
from app.schemas.tasks import Task
from app.services.storage import ArtifactStore, cache_key
from app.vendor.deeptutor.json_output import extract_json_object


def messages(system, data, schema):
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(
            role="user",
            content=json.dumps(
                {"schema": schema.model_json_schema(), "course_data": data},
                ensure_ascii=False,
            ),
        ),
    ]


def unique(values):
    return list(dict.fromkeys(values))


class GenerationService:
    def __init__(self, settings: Settings, repository: TaskRepository, llm=None):
        self.settings, self.repository = settings, repository
        client = llm or DeepSeekClient(settings)
        self.llm = client if isinstance(client, BoundedLLM) else BoundedLLM(client, settings)
        self.store = ArtifactStore(settings.data_dir, repository)

    def _artifact(self, task: Task, kind: str):
        for artifact in self.repository.artifacts(task.id):
            if artifact.kind == kind:
                return artifact
        raise StudyError("TOOL_PRECONDITION", "所需课程产物尚未生成。", 409)

    def _model_key(self):
        return {
            "provider": str(self.settings.llm_base_url),
            "model": self.settings.llm_model,
            "prompt": PROMPT_VERSION,
            "schema": "1.0",
            "context": self.settings.llm_context_tokens,
            "output": self.settings.llm_max_output_tokens,
            "request_bytes": self.settings.llm_max_request_bytes,
        }

    def _note_data(self, task, segments):
        return {
            "title": task.title,
            "output_language": task.options.output_language,
            "segments": [
                {"segment_id": s.get("id", s.get("segment_id")), "text": s["text"]}
                for s in segments
            ],
        }

    def _chunks(self, task: Task, transcript: Transcript):
        def builder(segments, images):
            return [
                message.model_dump(mode="json")
                for message in messages(
                    NOTE_SYSTEM,
                    self._note_data(task, segments),
                    NotesDocument,
                )
            ]

        return transcript_chunks(transcript, self.settings, builder, reserve_bytes=8192)

    async def _structured(self, system, data, schema, validate):
        for attempt in range(2):
            instructions = system
            if attempt:
                instructions += (
                    "\n上次输出校验失败。请重新核对 Schema、题数、有效来源及必填字段，"
                    "返回完整 JSON。"
                )
            response = await self.llm.complete(
                ModelRequest(
                    messages=messages(instructions, data, schema),
                    json_mode=True,
                    max_output_tokens=self.settings.llm_max_output_tokens,
                )
            )
            try:
                result = schema.model_validate(extract_json_object(response.content))
                validate(result)
                return result
            except (ValueError, ValidationError):
                if attempt:
                    raise StudyError(
                        "GENERATION_INVALID", "模型输出连续两次未通过内容校验。", 422, True
                    ) from None
        raise StudyError("GENERATION_INVALID", "模型未返回有效结果。", 422, True)

    async def generate_notes(self, task: Task):
        source = self._artifact(task, "transcript")
        transcript = self.store.read_json(source, Transcript)
        key = cache_key(
            tool="notes-v1",
            transcript=source.sha256,
            title=task.title,
            language=task.options.output_language,
            **self._model_key(),
        )
        cached = self.store.reuse(task.id, "notes", key, NotesDocument)
        if cached:
            validate_notes(self.store.read_json(cached, NotesDocument), transcript)
            return cached
        partials = []
        for chunk in self._chunks(task, transcript):
            result = await self._structured(
                NOTE_SYSTEM,
                self._note_data(task, [part.model_dump() for part in chunk.parts]),
                NotesDocument,
                lambda value: validate_notes(value, transcript, chunk.source_segment_ids),
            )
            partials.append(result)
        chapters = [chapter for note in partials for chapter in note.chapters]
        chapters = [
            chapter.model_copy(update={"id": f"ch_{index:05d}"})
            for index, chapter in enumerate(chapters, 1)
        ]
        result = NotesDocument(
            title=task.title,
            chapters=chapters,
            learning_objectives=unique([v for note in partials for v in note.learning_objectives]),
            key_concepts=unique([v for note in partials for v in note.key_concepts]),
            summary="\n\n".join(unique([note.summary for note in partials])),
        )
        validate_notes(result, transcript)
        return self.store.put_json(task.id, "notes", result, key)

    async def generate_quiz(self, task: Task):
        source = self._artifact(task, "transcript")
        note_artifact = next(
            (a for a in self.repository.artifacts(task.id) if a.kind == "notes"), None
        )
        transcript = self.store.read_json(source, Transcript)
        notes = self.store.read_json(note_artifact, NotesDocument) if note_artifact else None
        if notes:
            validate_notes(notes, transcript)
        from app.services.quiz_documents import QuizReader

        key = cache_key(
            tool="quiz-v2",
            nonce=getattr(self.repository, "quiz_nonce", None),
            transcript=source.sha256,
            notes=note_artifact.sha256 if note_artifact else None,
            options=task.options.model_dump(),
            **self._model_key(),
        )
        cached = self.store.reuse(task.id, "quiz", key, QuizReader)
        if cached:
            validate_quiz(self.store.read_json(cached, QuizReader), transcript, notes, task.options)
            return cached
        chunks = self._chunks(task, transcript)
        count = task.options.question_count
        indices = (
            [len(chunks) // 2]
            if count == 1
            else [i * (len(chunks) - 1) // (count - 1) for i in range(count)]
        )
        questions = []
        for index, quota in Counter(indices).items():
            chunk = chunks[index]
            while quota:
                batch_size = min(5, quota)
                options = task.options.model_copy(update={"question_count": batch_size})
                chapters = [
                    chapter
                    for chapter in (notes.chapters if notes else [])
                    if set(chapter.source_segment_ids) & set(chunk.source_segment_ids)
                ]
                data = {
                    "options": options.model_dump(),
                    "difficulty_instruction": DIFFICULTY[options.difficulty],
                    "segments": [part.model_dump() for part in chunk.parts],
                    "chapters": [{"id": c.id, "title": c.title[:80]} for c in chapters],
                    "avoid_questions": getattr(self.repository, "previous_questions", [])[-15:]
                    + [q.question for q in questions],
                }

                def validate(result):
                    validate_quiz(result, transcript, notes, options)
                    if any(
                        set(q.source_segment_ids) - set(chunk.source_segment_ids)
                        for q in result.questions
                    ):
                        raise ValueError("Question cited a segment outside the supplied chunk")
                    previous = {normalized(q.question) for q in questions} | {
                        normalized(q) for q in getattr(self.repository, "previous_questions", [])
                    }
                    if any(normalized(q.question) in previous for q in result.questions):
                        raise ValueError("Question duplicates a previous batch")

                result = await self._structured(
                    QUIZ_SYSTEM
                    + ("\nNo chapters supplied: chapter_id must be null." if not notes else ""),
                    data,
                    QuizDocument if notes else QuizPartV11,
                    validate,
                )
                questions.extend(result.questions)
                quota -= batch_size
        questions = [
            question.model_copy(update={"id": f"q_{index:05d}"})
            for index, question in enumerate(questions, 1)
        ]
        result = (QuizDocument if notes else QuizDocumentV11)(
            question_count=count, difficulty=task.options.difficulty, questions=questions
        )
        validate_quiz(result, transcript, notes, task.options)
        return self.store.put_json(task.id, "quiz", result, key)
