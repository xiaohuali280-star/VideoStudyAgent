from app.adapters.chunking import conservative_tokens
from app.core.config import Settings
from app.core.errors import StudyError
from app.providers.deepseek import DeepSeekClient
from app.schemas.providers import ModelRequest


class BoundedLLM:
    """Per-task budget shared by generation and the single Agent.

    DeepSeek transport may attempt three times; reserve the worst case before sending.
    UTF-8 bytes are a conservative input estimate, not billed provider token usage.
    """

    def __init__(self, client, settings: Settings):
        self.client, self.settings = client, settings
        self.requests_reserved = 0
        self.tokens_reserved = 0
        self.actual_input_tokens = 0
        self.actual_output_tokens = 0

    async def complete(self, request: ModelRequest):
        estimate = conservative_tokens(request.model_dump(mode="json"))
        if estimate + request.max_output_tokens > self.settings.llm_context_tokens:
            raise StudyError("CONTEXT_LIMIT", "模型请求超出上下文预算。", 422)
        attempts = 3 if isinstance(self.client, DeepSeekClient) else 1
        reserve = attempts * (estimate + request.max_output_tokens)
        if (
            self.requests_reserved + attempts > self.settings.llm_max_requests
            or self.tokens_reserved + reserve > self.settings.llm_total_tokens
        ):
            raise StudyError("AGENT_LIMIT_EXCEEDED", "本任务已达到模型调用预算。", 422)
        self.requests_reserved += attempts
        self.tokens_reserved += reserve
        reply = await self.client.complete(request)
        self.actual_input_tokens += reply.input_tokens
        self.actual_output_tokens += reply.output_tokens
        if self.actual_input_tokens + self.actual_output_tokens > self.settings.llm_total_tokens:
            raise StudyError("AGENT_LIMIT_EXCEEDED", "模型返回用量超过任务预算。", 422)
        return reply
