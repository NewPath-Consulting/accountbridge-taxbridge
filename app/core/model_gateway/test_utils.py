from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator, Iterable, Optional


def has_any_env(*names: str) -> bool:
    return any(bool(os.getenv(n)) for n in names)


def extract_text(resp: Any) -> str:
    """
    Best-effort extraction of assistant text from OpenAI-compatible responses.
    """

    if resp is None:
        return ""

    # OpenAI SDK objects support model_dump()
    try:
        data = resp.model_dump()
        return (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
            or data.get("choices", [{}])[0].get("text", "")
            or ""
        )
    except Exception:
        pass

    # dict-shaped fallback
    if isinstance(resp, dict):
        try:
            return (
                resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                or resp.get("choices", [{}])[0].get("text", "")
                or ""
            )
        except Exception:
            return ""

    # attribute-shaped fallback
    try:
        choices = getattr(resp, "choices", None)
        if choices:
            c0 = choices[0]
            msg = getattr(c0, "message", None)
            if msg is not None and getattr(msg, "content", None):
                return str(msg.content)
            if getattr(c0, "text", None):
                return str(c0.text)
    except Exception:
        pass

    return ""


def try_parse_json(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except Exception:
        return None


def consume_sync_stream(stream: Any, *, max_chars: int = 600) -> str:
    """
    Consume an OpenAI-SDK-style sync stream, but gracefully handle non-stream
    responses (e.g., dicts from lightweight providers like Bedrock wrappers).
    """

    if stream is None:
        return ""

    # Non-iterable response (or dict-shaped response) -> best-effort text.
    if isinstance(stream, dict) or not hasattr(stream, "__iter__"):
        return extract_text(stream)[:max_chars]

    out = ""
    for chunk in stream:  # type: ignore[assignment]
        try:
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                out += str(content)
        except Exception:
            # Some providers may stream bytes/strings; append if possible.
            try:
                if isinstance(chunk, (bytes, str)):
                    out += chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            except Exception:
                pass
        if len(out) >= max_chars:
            break
    return out[:max_chars]


async def consume_async_stream(stream: Any, *, max_chars: int = 600) -> str:
    """
    Consume an OpenAI-SDK-style async stream, but gracefully handle non-stream
    responses (e.g., dicts from lightweight providers like Bedrock wrappers).
    """

    if stream is None:
        return ""

    # Not actually async-iterable -> best-effort text.
    if isinstance(stream, dict) or not hasattr(stream, "__aiter__"):
        return extract_text(stream)[:max_chars]

    out = ""
    async for chunk in stream:
        try:
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                out += str(content)
        except Exception:
            try:
                if isinstance(chunk, (bytes, str)):
                    out += chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            except Exception:
                pass
        if len(out) >= max_chars:
            break
    return out[:max_chars]


