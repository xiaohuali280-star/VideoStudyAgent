import asyncio
import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import StudyError
from app.schemas.providers import ModelReply, ModelRequest, ToolCall


class DeepSeekClient:
    """DeepSeek's native Chat Completions / Tool Calling protocol. No SDK or Agent runtime."""

    def __init__(self, settings: Settings, transport=None, sleep=asyncio.sleep):
        if not settings.llm_api_key or not settings.llm_base_url or not settings.llm_model:
            raise StudyError("LLM_CONFIGURATION_ERROR", "请配置服务端模型和 API Key。", 503)
        self.settings, self.transport, self.sleep = settings, transport, sleep

    async def complete(self, request: ModelRequest) -> ModelReply:
        messages = []
        for message in request.messages:
            item = {"role": message.role, "content": message.content}
            if message.tool_call_id:
                item["tool_call_id"] = message.tool_call_id
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            messages.append(item)
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "stream": False,
            "max_tokens": request.max_output_tokens,
            "thinking": {"type": "disabled"},
        }
        if request.tools:
            payload["tools"] = [
                {"type": "function", "function": tool.model_dump()} for tool in request.tools
            ]
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = False
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if (
            len(json.dumps(payload, ensure_ascii=False).encode())
            > self.settings.llm_max_request_bytes
        ):
            raise StudyError("CONTEXT_LIMIT", "模型请求超过大小预算。", 422)
        headers = {"Authorization": "Bearer " + self.settings.llm_api_key.get_secret_value()}
        async with httpx.AsyncClient(
            timeout=self.settings.llm_timeout, transport=self.transport, follow_redirects=False
        ) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        str(self.settings.llm_base_url).rstrip("/") + "/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                except httpx.TimeoutException:
                    if attempt < 2:
                        await self.sleep(2**attempt)
                        continue
                    raise StudyError("LLM_TIMEOUT", "模型服务超时，请重试。", 503, True) from None
                except httpx.HTTPError:
                    if attempt < 2:
                        await self.sleep(2**attempt)
                        continue
                    raise StudyError("LLM_UNAVAILABLE", "模型服务无法连接。", 503, True) from None
                if response.status_code in {401, 403}:
                    raise StudyError("LLM_CONFIGURATION_ERROR", "模型服务认证失败。", 503)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        try:
                            raw_wait = response.headers.get("Retry-After")
                            if raw_wait is None:
                                wait = 2**attempt
                            else:
                                try:
                                    wait = max(0, float(raw_wait))
                                except ValueError:
                                    wait = max(
                                        0,
                                        (
                                            parsedate_to_datetime(raw_wait) - datetime.now(UTC)
                                        ).total_seconds(),
                                    )
                        except (ValueError, TypeError):
                            wait = 2**attempt
                        if wait > 10:
                            raise StudyError("LLM_RATE_LIMIT", "服务要求稍后重试。", 503, True)
                        await self.sleep(wait)
                        continue
                    code = "LLM_RATE_LIMIT" if response.status_code == 429 else "LLM_UNAVAILABLE"
                    raise StudyError(code, "模型服务暂时不可用，请稍后重试。", 503, True)
                if response.status_code != 200:
                    raise StudyError("LLM_CONFIGURATION_ERROR", "模型服务不支持当前请求。", 503)
                try:
                    data = response.json()
                    message = data["choices"][0]["message"]
                    calls = [
                        ToolCall(
                            id=item["id"],
                            name=item["function"]["name"],
                            arguments=json.loads(item["function"]["arguments"]),
                        )
                        for item in message.get("tool_calls", [])
                    ]
                    usage = data.get("usage", {})
                    return ModelReply(
                        content=message.get("content") or "",
                        tool_calls=calls,
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                    )
                except (ValueError, KeyError, IndexError, TypeError, ValidationError):
                    raise StudyError(
                        "LLM_INVALID_RESPONSE", "模型返回的数据无效。", 503, True
                    ) from None
        raise StudyError("LLM_UNAVAILABLE", "模型请求未完成。", 503, True)
