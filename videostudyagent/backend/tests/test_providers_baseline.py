import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.providers.fakes import FakeASR, FakeLLM
from app.schemas.providers import ChatMessage, ModelReply, ModelRequest, ToolCall
from app.schemas.study import Transcript
from app.schemas.upstream import UpstreamBaseline, UpstreamCandidate

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_fake_llm_preserves_scripted_native_tool_calls_and_fails_when_exhausted():
    reply = ModelReply(tool_calls=[ToolCall(id="call_1", name="load_subtitles", arguments={})])
    fake = FakeLLM([reply])
    request = ModelRequest(messages=[ChatMessage(role="user", content="test")])
    assert asyncio.run(fake.complete(request)) == reply
    assert fake.requests == [request]
    with pytest.raises(RuntimeError, match="no scripted reply"):
        asyncio.run(fake.complete(request))


def test_fake_asr_returns_independent_copies_without_loading_models(tmp_path):
    transcript = Transcript(
        source="asr",
        language="zh",
        duration_ms=1000,
        segments=[{"id": "seg_1", "start_ms": 0, "end_ms": 1000, "text": "离线样本。"}],
    )
    fake = FakeASR(transcript)
    audio_path = tmp_path / "not-a-real-audio.wav"
    first = fake.transcribe(audio_path, "zh")
    first.segments.clear()
    assert len(fake.transcribe(audio_path).segments) == 1
    assert fake.calls == [(audio_path, "zh"), (audio_path, None)]
    assert not audio_path.exists()


def load_candidates():
    return json.loads((PROJECT_ROOT / "docs/upstream_candidates.json").read_text("utf-8"))


def test_five_repository_baseline_has_all_reuse_entries_and_no_adopted_claims():
    baseline = UpstreamBaseline.model_validate(load_candidates())
    assert {item.id for item in baseline.candidates} == {
        "B1",
        "B2",
        "B3",
        "B4",
        "D1",
        "D2",
        "D3",
        "T1",
        "T2",
        "V1",
        "N1",
    }
    assert len({item.repository for item in baseline.candidates}) == 5
    assert next(item for item in baseline.candidates if item.id == "N1").status == "excluded"
    assert not (PROJECT_ROOT / "backend/app/vendor").exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"commit": "main"},
        {"license": None},
        {"source_paths": ["../escape.py"]},
        {"target_stage": 1},
        {"status": "adopted"},
    ],
)
def test_registry_rejects_unpinned_unlicensed_or_out_of_scope_candidates(overrides):
    data = load_candidates()["candidates"][0]
    with pytest.raises(ValidationError):
        UpstreamCandidate.model_validate(data | overrides)
