"""Opt-in local HTTP fixture, exercises the production client without cloud calls."""

import json
import os

from fastapi import FastAPI

from app.schemas.providers import ChatMessage, ModelRequest, ToolCall, ToolDefinition
from tests.scripted_llm import ScriptedStudyModel

if os.environ.get("VSA_HTTP_FIXTURE") != "1":
    raise RuntimeError("Explicit VSA_HTTP_FIXTURE=1 required")

app = FastAPI()
model = ScriptedStudyModel()


@app.get("/metrics")
def metrics():
    return {
        "requests": len(model.requests),
        "generation_requests": sum(not request.tools for request in model.requests),
    }


@app.post("/chat/completions")
async def complete(payload: dict):
    messages = []
    for message in payload["messages"]:
        messages.append(
            ChatMessage(
                role=message["role"],
                content=message.get("content") or "",
                tool_call_id=message.get("tool_call_id"),
                tool_calls=[
                    ToolCall(
                        id=call["id"],
                        name=call["function"]["name"],
                        arguments=json.loads(call["function"]["arguments"]),
                    )
                    for call in message.get("tool_calls", [])
                ],
            )
        )
    reply = await model.complete(
        ModelRequest(
            messages=messages,
            tools=[
                ToolDefinition.model_validate(tool["function"]) for tool in payload.get("tools", [])
            ],
            max_output_tokens=payload["max_tokens"],
            json_mode=payload.get("response_format", {}).get("type") == "json_object",
        )
    )
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": reply.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in reply.tool_calls
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 20},
    }
