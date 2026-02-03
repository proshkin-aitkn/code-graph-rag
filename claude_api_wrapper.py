#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Claude CLI Wrapper", description="OpenAI-compatible API for Claude CLI"
)

VERBOSE = False


def log(msg: str) -> None:
    if VERBOSE:
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()


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


async def call_claude_cli(
    prompt: str, model: str = "sonnet", system_prompt: str | None = None
) -> dict[str, Any]:
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
        "--tools",
        "",
        "--disable-slash-commands",
        "--strict-mcp-config",
    ]

    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    cmd.append(prompt)

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
    log(f"\n{'=' * 60}")
    log(f"[REQUEST] Model: {request.model}")
    log(f"[REQUEST] Messages: {len(request.messages)}")
    for i, msg in enumerate(request.messages):
        content_preview = (
            msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
        )
        log(f"  [{i}] {msg.role}: {content_preview}")
    log(f"{'=' * 60}")

    prompt = build_prompt(request.messages)
    response = await call_claude_cli(prompt, request.model)

    content = response.get("result", "")

    usage_data = response.get("usage", {})
    input_tokens = usage_data.get("input_tokens", 0)
    output_tokens = usage_data.get("output_tokens", 0)
    cache_read = usage_data.get("cache_read_input_tokens", 0)
    cache_creation = usage_data.get("cache_creation_input_tokens", 0)

    result = ChatCompletionResponse(
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

    content_preview = content[:300] + "..." if len(content) > 300 else content
    log(
        f"\n[RESPONSE] Tokens: {result.usage.prompt_tokens} in / {result.usage.completion_tokens} out"
    )
    log(f"[RESPONSE] Content: {content_preview}")
    log(f"{'=' * 60}\n")

    return result


class ResponsesRequest(BaseModel):
    model: str = "claude-sonnet-4-5-20250929"
    input: str | list[dict[str, Any]] = ""
    instructions: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None


class OutputText(BaseModel):
    type: str = "output_text"
    text: str


class OutputItem(BaseModel):
    type: str = "message"
    id: str
    status: str = "completed"
    role: str = "assistant"
    content: list[OutputText]


class ResponsesResponse(BaseModel):
    id: str
    object: str = "response"
    created_at: int
    model: str
    output: list[OutputItem]
    usage: Usage


@app.post("/v1/responses")
async def responses(request: ResponsesRequest):
    if isinstance(request.input, str):
        prompt = request.input
    else:
        parts = []
        for item in request.input:
            role = item.get("role", "user")
            content = item.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if c.get("type") == "input_text"
                )
            parts.append(f"[{role.capitalize()}]: {content}")
        prompt = "\n\n".join(parts)

    system_prompt = request.instructions

    log(f"\n{'=' * 60}")
    log(f"[RESPONSES API] Model: {request.model}")
    if system_prompt:
        sys_preview = (
            system_prompt[:200] + "..." if len(system_prompt) > 200 else system_prompt
        )
        log(f"[RESPONSES API] System: {sys_preview}")
    prompt_preview = prompt[:300] + "..." if len(prompt) > 300 else prompt
    log(f"[RESPONSES API] Prompt: {prompt_preview}")
    log(f"{'=' * 60}")

    response = await call_claude_cli(prompt, request.model, system_prompt)
    content = response.get("result", "")

    usage_data = response.get("usage", {})
    input_tokens = usage_data.get("input_tokens", 0)
    output_tokens = usage_data.get("output_tokens", 0)
    cache_read = usage_data.get("cache_read_input_tokens", 0)
    cache_creation = usage_data.get("cache_creation_input_tokens", 0)

    msg_id = f"msg-{uuid.uuid4().hex[:12]}"
    result = ResponsesResponse(
        id=f"resp-{response.get('uuid', uuid.uuid4().hex[:8])}",
        created_at=int(time.time()),
        model=request.model,
        output=[
            OutputItem(
                id=msg_id,
                content=[OutputText(text=content)],
            )
        ],
        usage=Usage(
            prompt_tokens=input_tokens + cache_read + cache_creation,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + cache_read + cache_creation + output_tokens,
        ),
    )

    content_preview = content[:300] + "..." if len(content) > 300 else content
    log(
        f"\n[RESPONSE] Tokens: {result.usage.prompt_tokens} in / {result.usage.completion_tokens} out"
    )
    log(f"[RESPONSE] Content: {content_preview}")
    log(f"{'=' * 60}\n")

    return result


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


def main() -> None:
    global VERBOSE
    import uvicorn

    parser = argparse.ArgumentParser(description="Claude CLI Wrapper Server")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print request/response details"
    )
    parser.add_argument(
        "-p", "--port", type=int, default=8000, help="Port to listen on"
    )
    args = parser.parse_args()

    VERBOSE = args.verbose
    if VERBOSE:
        sys.stdout.write("Verbose mode enabled - will print request/response details\n")

    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
