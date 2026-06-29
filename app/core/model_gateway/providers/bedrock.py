from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Union

import boto3


def _resolve_read_timeout(timeout: Optional[Any]) -> int:
    if timeout is not None:
        try:
            return max(60, int(float(timeout)))
        except (TypeError, ValueError):
            pass
    try:
        from app.config.settings import get_settings

        settings = get_settings()
        return max(60, int(settings.REPORTS_LLM_TIMEOUT or settings.LLM_TIMEOUT))
    except Exception:
        return 600


def _bedrock_client(timeout: Optional[Any] = None):
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    read_timeout = _resolve_read_timeout(timeout)

    # WARNING: SSL verification disabled for development
    import warnings
    from botocore.config import Config

    warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    config = Config(
        region_name=region,
        signature_version="v4",
        read_timeout=read_timeout,
        connect_timeout=30,
        retries={"max_attempts": 2, "mode": "standard"},
    )

    return boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=config,
        verify=False,
    )


def bedrock_embedding(
    *,
    model: str,
    input: Union[str, List[str]],
    timeout: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    """
    Minimal embedding wrapper for Bedrock Titan embedding models.

    Returns an OpenAI-like dict: {"data": [{"embedding": [...]}, ...]}
    """

    _ = timeout  # embedding calls use default client timeout
    client = _bedrock_client(timeout)
    model_id = model.replace("bedrock/", "")

    if isinstance(input, list):
        vectors: List[List[float]] = []
        for text in input:
            body = json.dumps({"inputText": text})
            resp = client.invoke_model(modelId=model_id, body=body)
            payload = json.loads(resp["body"].read().decode("utf-8"))
            vec = payload.get("embedding") or payload.get("vector") or []
            vectors.append([float(x) for x in vec])
        return {"data": [{"embedding": v} for v in vectors]}

    body = json.dumps({"inputText": input})
    resp = client.invoke_model(modelId=model_id, body=body)
    payload = json.loads(resp["body"].read().decode("utf-8"))
    vec = payload.get("embedding") or payload.get("vector") or []
    return {"data": [{"embedding": [float(x) for x in vec]}]}


def bedrock_chat_completion(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    optional_params: Dict[str, Any],
    timeout: Optional[Any] = None,
) -> Any:
    """
    Minimal Bedrock chat via Converse API (best-effort).

    Returns an OpenAI-like dict: {"choices":[{"message":{"role":"assistant","content":...}}], ...}
    """

    client = _bedrock_client(timeout)
    model_id = model.replace("bedrock/", "")

    converse_messages: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant"):
            continue
        if content is None:
            continue
        converse_messages.append({"role": role, "content": [{"text": str(content)}]})

    max_tokens = optional_params.get("max_tokens")
    temperature = optional_params.get("temperature")
    top_p = optional_params.get("top_p")

    inference_config: Dict[str, Any] = {}
    if max_tokens is not None:
        inference_config["maxTokens"] = int(max_tokens)
    # Bedrock Converse (Claude): temperature and topP are mutually exclusive.
    if temperature is not None:
        inference_config["temperature"] = float(temperature)
    elif top_p is not None:
        inference_config["topP"] = float(top_p)

    resp = client.converse(
        modelId=model_id,
        messages=converse_messages,
        inferenceConfig=inference_config,
        **(
            {}
            if "outputConfig" not in optional_params
            else {"outputConfig": optional_params["outputConfig"]}
        ),
    )

    out_text = ""
    try:
        out_blocks = resp.get("output", {}).get("message", {}).get("content", [])
        if isinstance(out_blocks, list):
            out_text = "".join(
                [b.get("text", "") for b in out_blocks if isinstance(b, dict)]
            )
    except Exception:
        out_text = ""

    usage_block: Dict[str, Any] = {}
    try:
        raw_usage = resp.get("usage") or resp.get("Usage") or {}
        if isinstance(raw_usage, dict):
            inp = (
                raw_usage.get("inputTokens")
                or raw_usage.get("input_tokens")
                or raw_usage.get("prompt_tokens")
            )
            out = (
                raw_usage.get("outputTokens")
                or raw_usage.get("output_tokens")
                or raw_usage.get("completion_tokens")
            )
            total = raw_usage.get("totalTokens") or raw_usage.get("total_tokens")
            if inp is not None:
                usage_block["prompt_tokens"] = int(inp)
            if out is not None:
                usage_block["completion_tokens"] = int(out)
            if total is not None:
                usage_block["total_tokens"] = int(total)
            elif inp is not None and out is not None:
                usage_block["total_tokens"] = int(inp) + int(out)
    except (TypeError, ValueError, AttributeError):
        usage_block = {}

    result: Dict[str, Any] = {
        "choices": [
            {
                "message": {"role": "assistant", "content": out_text},
                "finish_reason": (
                    "length"
                    if str(resp.get("stopReason") or "").lower() == "max_tokens"
                    else "stop"
                ),
                "index": 0,
            }
        ],
        "model": model,
        "object": "chat.completion",
    }
    if usage_block:
        result["usage"] = usage_block
    return result


async def abedrock_chat_completion(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    optional_params: Dict[str, Any],
    timeout: Optional[Any] = None,
) -> Any:
    return await asyncio.to_thread(
        bedrock_chat_completion,
        model=model,
        messages=messages,
        optional_params=optional_params,
        timeout=timeout,
    )
