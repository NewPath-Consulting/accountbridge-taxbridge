from __future__ import annotations

import os

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, cast

import tiktoken


# ------------------------------------------------------------------
# Minimal global configuration (mirrors the small subset `aim_main.py` uses)
# ------------------------------------------------------------------
api_key: Optional[str] = None
api_base: Optional[str] = None
api_version: Optional[str] = None

openai_key: Optional[str] = None
azure_key: Optional[str] = None

# Providers which are "OpenAI-compatible" (use OpenAI SDK with custom base_url).
openai_compatible_providers: List[str] = [
    "openai",
    "azure",
]

_builtin_provider_prefixes: set[str] = {"openai", "azure", "bedrock"}


@dataclass(frozen=True)
class CustomProviderHandler:
    provider: str
    completion: Callable[..., Any]
    acompletion: Optional[Callable[..., Any]] = None
    embedding: Optional[Callable[..., Any]] = None
    aembedding: Optional[Callable[..., Any]] = None


_custom_providers: set[str] = set()
_custom_provider_handlers: Dict[str, CustomProviderHandler] = {}


def register_custom_provider(*, provider: str, custom_handler: Any) -> None:
    """
    Register a custom provider handler for `model_gateway.aim_main`.

    Expected callables on `custom_handler`:
    - completion(...)
    - optionally acompletion(...)
    - optionally embedding(...) / aembedding(...)
    """

    if not provider or not isinstance(provider, str):
        raise ValueError("provider must be a non-empty string")
    if custom_handler is None:
        raise ValueError("custom_handler is required")
    if not hasattr(custom_handler, "completion"):
        raise ValueError("custom_handler must implement .completion(...)")

    handler = CustomProviderHandler(
        provider=provider,
        completion=cast(Callable[..., Any], getattr(custom_handler, "completion")),
        acompletion=cast(Optional[Callable[..., Any]], getattr(custom_handler, "acompletion", None)),
        embedding=cast(Optional[Callable[..., Any]], getattr(custom_handler, "embedding", None)),
        aembedding=cast(Optional[Callable[..., Any]], getattr(custom_handler, "aembedding", None)),
    )
    _custom_providers.add(provider)
    _custom_provider_handlers[provider] = handler


def get_custom_provider_handler(provider: str) -> Optional[CustomProviderHandler]:
    return _custom_provider_handlers.get(provider)


def get_llm_provider(
    *,
    model: str,
    custom_llm_provider: Optional[str] = None,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Minimal provider resolver for `model_gateway.aim_main`.

    Returns:
        (model_without_prefix, provider, dynamic_api_key, dynamic_api_base)
    """

    if model is None:
        raise ValueError("model is required")

    # Explicit provider wins.
    if custom_llm_provider:
        if isinstance(model, str) and model.startswith(f"{custom_llm_provider}/"):
            model = model.split("/", 1)[1]
        return model, custom_llm_provider, api_key, api_base

    # Support "provider/model" routing strings.
    if isinstance(model, str) and "/" in model:
        prefix, rest = model.split("/", 1)
        if prefix in _builtin_provider_prefixes:
            return rest, prefix, api_key, api_base
        if prefix in openai_compatible_providers or prefix in _custom_providers:
            return rest, prefix, api_key, api_base

    # Bedrock ARNs can be passed directly (no "bedrock/" prefix).
    if isinstance(model, str) and model.startswith("arn:") and ":bedrock:" in model:
        return model, "bedrock", api_key, api_base

    # Infer based on env vars / defaults.
    if os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_BASE"):
        return model, "azure", api_key, api_base

    return model, "openai", api_key, api_base


def get_non_default_completion_params(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Separate provider-specific extras. For model_gateway we just pass through non-None kwargs.
    """

    return {k: v for k, v in (kwargs or {}).items() if v is not None}


def get_optional_params(
    *,
    model: str,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    n: Optional[int] = None,
    stream: Optional[bool] = None,
    stop: Optional[Union[str, List[str]]] = None,
    max_tokens: Optional[int] = None,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    logit_bias: Optional[Dict[int, int]] = None,
    user: Optional[str] = None,
    custom_llm_provider: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    Build the OpenAI-chat-compatible optional params dict.
    """

    params: Dict[str, Any] = {
        "temperature": temperature,
        "top_p": top_p,
        "n": n,
        "stream": stream,
        "stop": stop,
        "max_tokens": max_tokens,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
        "logit_bias": logit_bias,
        "user": user,
        **extra,
    }
    return {k: v for k, v in params.items() if v is not None}


def token_counter(
    *,
    model: str,
    messages: Optional[List[Dict[str, Any]]] = None,
    text: Optional[str] = None,
) -> int:
    if messages is None and text is None:
        return 0

    try:
        enc = tiktoken.encoding_for_model(model)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")

    if text is not None:
        return len(enc.encode(text))

    joined = ""
    for m in messages or []:
        c = m.get("content")
        if c is None:
            continue
        joined += c if isinstance(c, str) else str(c)
        joined += "\n"
    return len(enc.encode(joined))


def embedding(
    *,
    model: str,
    input: Union[str, List[str]],
    custom_llm_provider: Optional[str] = None,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    timeout: Optional[Union[float, Any]] = None,
    **kwargs: Any,
) -> Any:
    """
    Minimal embedding entrypoint used by `test_aim_model_gateway.py`.

    Supports:
    - OpenAI embeddings via OpenAI SDK
    - Bedrock embeddings via native provider module
    - Custom providers (if handler exposes `.embedding`)
    """

    model, custom_llm_provider, dyn_key, dyn_base = get_llm_provider(
        model=model,
        custom_llm_provider=custom_llm_provider,
        api_key=api_key,
        api_base=api_base,
    )
    api_key = dyn_key or api_key
    api_base = dyn_base or api_base

    if custom_llm_provider in (None, "openai") or custom_llm_provider in openai_compatible_providers:
        import openai

        api_base = api_base or os.getenv("OPENAI_API_BASE") or "https://api.openai.com/v1"
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        client = openai.OpenAI(api_key=api_key, base_url=api_base, timeout=timeout)
        return client.embeddings.create(model=model, input=input, **kwargs)

    if custom_llm_provider == "bedrock":
        from app.core.model_gateway.providers.bedrock import bedrock_embedding

        return bedrock_embedding(model=model, input=input, timeout=timeout, **kwargs)

    if custom_llm_provider in _custom_providers:
        handler = get_custom_provider_handler(custom_llm_provider)
        if handler is None or handler.embedding is None:
            raise ValueError(f"Custom provider '{custom_llm_provider}' does not implement embedding()")
        return handler.embedding(model=model, input=input, api_key=api_key, api_base=api_base, timeout=timeout, **kwargs)

    raise ValueError(f"Unknown provider for embedding: {custom_llm_provider}")

