#!/usr/bin/env python3
import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Claude CLI Wrapper", description="OpenAI-compatible API for Claude CLI"
)


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "claude-sonnet-4-5-20250929"
    messages: list[Message]
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Choice(BaseModel):
    index: int = 0
    message: Message
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


def build_prompt(messages: list[Message]) -> str:
    parts = []
    for msg in messages:
        if msg.role == "system":
            parts.append(f"[System]: {msg.content}")
        elif msg.role == "user":
            parts.append(f"[User]: {msg.content}")
        elif msg.role == "assistant":
            parts.append(f"[Assistant]: {msg.content}")
    return "\n\n".join(parts)


async def call_claude_cli(prompt: str, model: str = "sonnet") -> dict[str, Any]:
    model_map = {
        "claude-sonnet-4-5-20250929": "sonnet",
        "claude-opus-4-5-20251101": "opus",
        "claude-3-5-sonnet-20241022": "sonnet",
        "gpt-4": "sonnet",
        "gpt-4o": "sonnet",
        "gpt-3.5-turbo": "haiku",
    }
    cli_model = model_map.get(model, "sonnet")

    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--model",
        cli_model,
        prompt,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except TimeoutError:
            proc.kill()
            raise HTTPException(status_code=504, detail="Claude CLI timeout")

        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Claude CLI error: {stderr.decode()}",
            )

        response_data = json.loads(stdout.decode())

        if response_data.get("is_error"):
            raise HTTPException(
                status_code=500,
                detail=f"Claude error: {response_data.get('result', 'Unknown error')}",
            )

        return response_data

    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse Claude response: {e}",
        )


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    prompt = build_prompt(request.messages)
    response = await call_claude_cli(prompt, request.model)

    content = response.get("result", "")

    usage_data = response.get("usage", {})
    input_tokens = usage_data.get("input_tokens", 0)
    output_tokens = usage_data.get("output_tokens", 0)
    cache_read = usage_data.get("cache_read_input_tokens", 0)
    cache_creation = usage_data.get("cache_creation_input_tokens", 0)

    return ChatCompletionResponse(
        id=f"chatcmpl-{response.get('uuid', uuid.uuid4().hex[:8])}",
        created=int(time.time()),
        model=request.model,
        choices=[
            Choice(
                message=Message(role="assistant", content=content),
            )
        ],
        usage=Usage(
            prompt_tokens=input_tokens + cache_read + cache_creation,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + cache_read + cache_creation + output_tokens,
        ),
    )


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "claude-sonnet-4-5-20250929",
                "object": "model",
                "owned_by": "anthropic",
            },
            {
                "id": "claude-opus-4-5-20251101",
                "object": "model",
                "owned_by": "anthropic",
            },
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
