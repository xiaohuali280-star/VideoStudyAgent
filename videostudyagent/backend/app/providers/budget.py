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
        self.on_usage = None
        self.usage_known = False
        self.requests_reserved = 0
        self.tokens_reserved = 0
        self.actual_input_tokens = 0
        self.actual_output_tokens = 0

    def preflight(self, requests):
        attempts = 3 if isinstance(self.client, DeepSeekClient) else 1
        tokens = sum(
            attempts * (conservative_tokens(r.model_dump(mode="json")) + r.max_output_tokens)
            for r in requests
        )
        if (
            self.requests_reserved + len(requests) * attempts > self.settings.llm_max_requests
            or self.tokens_reserved + tokens > self.settings.llm_total_tokens
        ):
            raise StudyError(
                "BUDGET_PREFLIGHT",
                "剩余预算不足以完成未缓存的笔记分块，请缩短字幕后另建课程。",
                422,
                True,
            )

    def notify(self):
        if self.on_usage:
            self.on_usage(self)

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
        self.notify()
        reply = await self.client.complete(request)
        self.usage_known = self.usage_known or reply.usage_available
        self.actual_input_tokens += reply.input_tokens
        self.actual_output_tokens += reply.output_tokens
        self.notify()
        if self.actual_input_tokens + self.actual_output_tokens > self.settings.llm_total_tokens:
            raise StudyError("AGENT_LIMIT_EXCEEDED", "模型返回用量超过任务预算。", 422)
        return reply
