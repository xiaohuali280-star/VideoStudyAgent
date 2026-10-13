from collections import deque
from collections.abc import Iterable
from pathlib import Path

from app.schemas.providers import ModelReply, ModelRequest
from app.schemas.study import Transcript


class FakeLLM:
    """Return supplied replies; never invent content or contact a service."""

    def __init__(self, replies: Iterable[ModelReply]):
        self._replies = deque(reply.model_copy(deep=True) for reply in replies)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelReply:
        if not self._replies:
            raise RuntimeError("FakeLLM has no scripted reply")
        self.requests.append(request.model_copy(deep=True))
        return self._replies.popleft()


class FakeASR:
    def __init__(self, transcript: Transcript):
        self._transcript = transcript.model_copy(deep=True)
        self.calls: list[tuple[Path, str | None]] = []

    def transcribe(self, audio_path: Path, language: str | None = None) -> Transcript:
        self.calls.append((audio_path, language))
        return self._transcript.model_copy(deep=True)
