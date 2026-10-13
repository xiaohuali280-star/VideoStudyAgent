from pathlib import Path
from typing import Protocol

from app.schemas.providers import ModelReply, ModelRequest
from app.schemas.study import Transcript


class LLMClient(Protocol):
    async def complete(self, request: ModelRequest) -> ModelReply: ...


class ASRProvider(Protocol):
    def transcribe(self, audio_path: Path, language: str | None = None) -> Transcript: ...
