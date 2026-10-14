import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.adapters.chunking import conservative_tokens, transcript_chunks
from app.adapters.grounding import quote_present, validate_notes, validate_quiz
from app.core.config import Settings
from app.core.errors import StudyError
from app.providers.budget import BoundedLLM
from app.providers.deepseek import DeepSeekClient
from app.providers.fakes import FakeLLM
from app.schemas.providers import ChatMessage, ModelReply, ModelRequest, ToolDefinition
from app.schemas.study import NotesDocument, QuizDocument, StudyOptions, Transcript
from app.services.generation import GenerationService
from app.services.transcription import TranscriptService
from tests.scripted_llm import ScriptedStudyModel
from tests.test_upload_persistence import upload


def prepared(application, count=5, difficulty="medium", text=None):
    files = None if text is None else {"subtitle": ("course.srt", text.encode("utf-8"))}
    task = upload(
        application,
        files,
        data={
            "options": json.dumps(
                {"question_count": 5, "difficulty": difficulty},
            )
        },
    ).json()
    repo = application.state.repository
    task = repo.get(task["id"]).model_copy(
        update={"options": StudyOptions(question_count=count, difficulty=difficulty)}
    )
    TranscriptService(application.state.settings, repo).load_subtitles(task)
    return task, repo


@pytest.mark.parametrize("count", [1, 5, 20])
@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_exact_quiz_shape_and_cached_generation(application, count, difficulty):
    task, repo = prepared(application, count, difficulty)
    llm = ScriptedStudyModel()
    service = GenerationService(application.state.settings, repo, llm)
    notes = asyncio.run(service.generate_notes(task))
    quiz = asyncio.run(service.generate_quiz(task))
    result = service.store.read_json(quiz, QuizDocument)
    assert len(result.questions) == count
    assert result.difficulty == difficulty
    assert all(q.answer and q.explanation and q.evidence for q in result.questions)
    calls = len(llm.requests)
    assert asyncio.run(service.generate_notes(task)).sha256 == notes.sha256
    assert asyncio.run(service.generate_quiz(task)).sha256 == quiz.sha256
    assert len(llm.requests) == calls


def test_long_course_covers_tail_and_preserves_original_parts(application):
    text = "1\n00:00:00,000 --> 00:00:10,000\n" + ("梯度下降 rate -0.1, " * 1700) + "课程末尾\n"
    task, repo = prepared(application, 5, text=text)
    service = GenerationService(application.state.settings, repo, ScriptedStudyModel())
    transcript = service.store.read_json(service._artifact(task, "transcript"), Transcript)
    original = transcript.model_dump_json()
    chunks = service._chunks(task, transcript)
    assert len(chunks) > 1
    assert "".join(part.text for c in chunks for part in c.parts) == transcript.segments[0].text
    assert transcript.model_dump_json() == original
    notes = service.store.read_json(asyncio.run(service.generate_notes(task)), NotesDocument)
    assert "课程末尾" in notes.chapters[-1].content_markdown
    assert len(notes.chapters) == len(chunks)
    assert all(c.token_estimate <= application.state.settings.llm_context_tokens for c in chunks)


def test_invalid_generation_has_one_repair_only(application):
    task, repo = prepared(application)
    fake = FakeLLM([ModelReply(content="{}"), ModelReply(content='{"title":"incomplete"}')])
    service = GenerationService(application.state.settings, repo, fake)
    with pytest.raises(StudyError, match="GENERATION_INVALID"):
        asyncio.run(service.generate_notes(task))
    assert len(fake.requests) == 2
    assert not any(a.kind == "notes" for a in repo.artifacts(task.id))


def test_foreign_sources_and_duplicate_questions_are_rejected(application):
    task, repo = prepared(application, 5)
    service = GenerationService(application.state.settings, repo, ScriptedStudyModel())
    notes = service.store.read_json(asyncio.run(service.generate_notes(task)), NotesDocument)
    transcript = service.store.read_json(service._artifact(task, "transcript"), Transcript)
    result = service.store.read_json(asyncio.run(service.generate_quiz(task)), QuizDocument)
    result.questions[1].question = result.questions[0].question
    with pytest.raises(ValueError, match="Duplicate"):
        validate_quiz(result, transcript, notes, task.options)
    notes.chapters[0].source_segment_ids = ["foreign"]
    with pytest.raises(ValueError, match="cover exactly"):
        validate_notes(notes, transcript)


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("rate is -0.1", True),
        ("rate is 0.1", False),
        ("-0.1", True),
        ("0.1", False),
        ("Rate\n is -0.1", True),
        ("2", False),
        ("", False),
    ],
)
def test_grounding_preserves_math_and_negative_numbers(quote, expected):
    assert quote_present(quote, "rate is -0.1 and gradient is 12") is expected


def test_budget_blocks_before_model_request():
    fake = FakeLLM([ModelReply(content="unused")])
    settings = Settings(_env_file=None, llm_max_requests=1, llm_total_tokens=4096)
    budget = BoundedLLM(fake, settings)
    request = ModelRequest(messages=[ChatMessage(role="user", content="too much")])
    with pytest.raises(StudyError, match="AGENT_LIMIT_EXCEEDED"):
        asyncio.run(budget.complete(request))
    assert not fake.requests


def test_chunker_obeys_conservative_budget_and_source_ids():
    source = Transcript(
        source="subtitle",
        language="zh",
        duration_ms=1000,
        segments=[
            {"id": "seg1", "start_ms": 0, "end_ms": 1000, "text": "中英文 mixed content " * 1000}
        ],
    )
    settings = Settings(_env_file=None, llm_context_tokens=4096, llm_max_output_tokens=256)

    def builder(segments, images):
        return [{"role": "user", "content": segments}]

    chunks = transcript_chunks(source, settings, builder)
    assert len(chunks) > 1
    assert {ref for chunk in chunks for ref in chunk.source_segment_ids} == {"seg1"}
    assert "".join(p.text for c in chunks for p in c.parts) == source.segments[0].text
    assert all(chunk.token_estimate <= 3840 for chunk in chunks)
    assert conservative_tokens(builder([], [])) < 3840


def test_deepseek_native_tool_call_contract_without_network():
    inspected = []
    synthetic = SecretStr("unit-test-" + uuid4().hex)
    settings = Settings(_env_file=None, llm_api_key=synthetic)

    def respond(request):
        body = json.loads(request.content)
        inspected.append(body)
        assert body["model"] == "deepseek-flash"
        assert body["thinking"]["type"] == "disabled"
        assert body["tools"][0]["function"]["name"] == "load_subtitles"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "load_subtitles", "arguments": "{}"},
                                },
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            },
        )

    client = DeepSeekClient(settings, httpx.MockTransport(respond))
    response = asyncio.run(
        client.complete(
            ModelRequest(
                messages=[ChatMessage(role="user", content="study")],
                tools=[
                    ToolDefinition(
                        name="load_subtitles",
                        description="load",
                        parameters={"type": "object"},
                    )
                ],
            )
        )
    )
    assert response.tool_calls[0].name == "load_subtitles" and response.input_tokens == 12
    assert synthetic.get_secret_value() not in json.dumps(inspected)


@pytest.mark.parametrize(
    ("status", "calls", "code"),
    [
        (401, 1, "LLM_CONFIGURATION_ERROR"),
        (429, 3, "LLM_RATE_LIMIT"),
        (500, 3, "LLM_UNAVAILABLE"),
    ],
)
def test_deepseek_http_errors_are_bounded_and_sanitized(status, calls, code):
    seen = []

    async def sleep(_):
        pass

    def respond(request):
        seen.append(1)
        return httpx.Response(
            status, json={"private": "provider-error-detail"}, headers={"Retry-After": "0"}
        )

    client = DeepSeekClient(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-test")),
        httpx.MockTransport(respond),
        sleep,
    )
    with pytest.raises(StudyError, match=code) as error:
        asyncio.run(client.complete(ModelRequest(messages=[])))
    assert len(seen) == calls
    assert "provider-error-detail" not in str(error.value)
