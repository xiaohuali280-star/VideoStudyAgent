from typing import Literal

from pydantic import Field, JsonValue

from app.schemas.common import ContractModel, NonEmptyText


class ToolDefinition(ContractModel):
    name: NonEmptyText
    description: NonEmptyText
    parameters: dict[str, JsonValue]


class ToolCall(ContractModel):
    id: NonEmptyText
    name: NonEmptyText
    arguments: dict[str, JsonValue]


class ChatMessage(ContractModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ModelReply(ContractModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ModelRequest(ContractModel):
    messages: list[ChatMessage]
    tools: list[ToolDefinition] = Field(default_factory=list)
