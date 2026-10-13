import hashlib
import json
from collections import defaultdict

from app.core.config import Settings
from app.core.errors import StudyError
from app.schemas.study import ChunkPart, Transcript, TranscriptChunk
from app.vendor.bilinote.request_chunker import RequestChunker


def conservative_tokens(messages) -> int:
    """UTF-8 byte upper bound, not an exact DeepSeek tokenizer count."""
    return len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 256


def transcript_chunks(transcript: Transcript, settings: Settings, message_builder, reserve_bytes=0):
    budget = (
        min(
            settings.llm_context_tokens - settings.llm_max_output_tokens,
            settings.llm_max_request_bytes - 1024,
        )
        - reserve_bytes
    )
    if budget <= 0:
        raise StudyError("LLM_CONFIGURATION_ERROR", "模型上下文和输出预算不兼容。", 422)
    chunker = RequestChunker(message_builder, budget, conservative_tokens)
    try:
        raw = chunker.chunk([segment.model_dump() for segment in transcript.segments], [])
    except ValueError as exc:
        raise StudyError("CONTEXT_LIMIT", "请求预算不足以容纳课程提示。", 422) from exc
    counts = defaultdict(int)
    results = []
    for index, chunk in enumerate(raw, 1):
        parts = []
        for segment in chunk.segments:
            segment_id = segment["id"]
            parts.append(
                ChunkPart(
                    segment_id=segment_id, text=segment["text"], part_index=counts[segment_id]
                )
            )
            counts[segment_id] += 1
        encoded = json.dumps([part.model_dump() for part in parts], ensure_ascii=False).encode()
        results.append(
            TranscriptChunk(
                id=f"chunk_{index:05d}",
                parts=parts,
                source_segment_ids=list(dict.fromkeys(part.segment_id for part in parts)),
                token_estimate=conservative_tokens(message_builder(chunk.segments, [])),
                content_hash=hashlib.sha256(encoded).hexdigest(),
            )
        )
    return results
