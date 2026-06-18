from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict, List, Optional, Union

import openai

from app.core.model_gateway.core import (
    get_custom_provider_handler,
    get_llm_provider,
    get_non_default_completion_params,
    get_optional_params,
    openai_compatible_providers,
)
from app.core.model_gateway.model_routing.router import CircuitBreaker, resolve_route_attempts



_cb_singleton: Optional[CircuitBreaker] = None


def _get_circuit_breaker(open_after_failures: int, cooldown_seconds: int) -> CircuitBreaker:
    global _cb_singleton
    if _cb_singleton is None:
        _cb_singleton = CircuitBreaker(
            open_after_failures=open_after_failures, cooldown_seconds=cooldown_seconds
        )
    return _cb_singleton


def _classify_error(exc: Exception) -> str:
    """
    Return a coarse error category used by retry policy.
    """

    if isinstance(exc, openai.APITimeoutError):
        return "timeout"
    if isinstance(exc, openai.RateLimitError):
        return "rate_limit"
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code and int(exc.status_code) >= 500:
            return "http_5xx"
        if exc.status_code and int(exc.status_code) == 429:
            return "rate_limit"
    # Fallback heuristics
    if "timed out" in str(exc).lower():
        return "timeout"
    return "other"


def _compute_backoff_s(*, attempt_idx: int, base_delay_ms: int, max_delay_ms: int, jitter: str) -> float:
    delay_ms = min(max_delay_ms, int(base_delay_ms * (2**attempt_idx)))
    if jitter == "full":
        return random.random() * (delay_ms / 1000.0)
    return delay_ms / 1000.0


def _call_provider_sync(
    *,
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    optional_params: Dict[str, Any],
    api_key: Optional[str],
    api_base: Optional[str],
    timeout: Optional[Any],
) -> Any:
    if provider == "azure":
        # Azure is considered openai-compatible, but the SDK uses a different client class.
        # Here api_base is expected to be the azure endpoint.
        api_version = optional_params.pop("api_version", None)
        client = openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=api_base,
            api_version=api_version,
            timeout=timeout,
        )
        return client.chat.completions.create(model=model, messages=messages, **optional_params)

    if provider in (None, "openai") or provider in openai_compatible_providers:
        base_url = api_base
        key = api_key
        # defaults resolved by OpenAI SDK; we keep this minimal
        client = openai.OpenAI(api_key=key, base_url=base_url, timeout=timeout)
        return client.chat.completions.create(model=model, messages=messages, **optional_params)

    if provider == "bedrock":
        from app.core.model_gateway.providers.bedrock import bedrock_chat_completion

        return bedrock_chat_completion(model=model, messages=messages, optional_params=optional_params, timeout=timeout)

    handler = get_custom_provider_handler(provider)
    if handler is None:
        raise ValueError(f"Unknown provider '{provider}'")
    return handler.completion(
        model=model,
        messages=messages,
        optional_params=optional_params,
        api_key=api_key,
        api_base=api_base,
        timeout=timeout,
    )


async def _call_provider_async(
    *,
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    optional_params: Dict[str, Any],
    api_key: Optional[str],
    api_base: Optional[str],
    timeout: Optional[Any],
) -> Any:
    if provider == "azure":
        api_version = optional_params.pop("api_version", None)
        client = openai.AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=api_base,
            api_version=api_version,
            timeout=timeout,
        )
        return await client.chat.completions.create(model=model, messages=messages, **optional_params)

    if provider in (None, "openai") or provider in openai_compatible_providers:
        client = openai.AsyncOpenAI(api_key=api_key, base_url=api_base, timeout=timeout)
        return await client.chat.completions.create(model=model, messages=messages, **optional_params)

    if provider == "bedrock":
        from app.core.model_gateway.providers.bedrock import abedrock_chat_completion

        return await abedrock_chat_completion(
            model=model, messages=messages, optional_params=optional_params, timeout=timeout
        )

    handler = get_custom_provider_handler(provider)
    if handler is None or handler.acompletion is None:
        raise ValueError(f"Unknown provider '{provider}' or async not supported")
    return await handler.acompletion(
        model=model,
        messages=messages,
        optional_params=optional_params,
        api_key=api_key,
        api_base=api_base,
        timeout=timeout,
    )


def completion(  # noqa: PLR0915
    model: str,
    messages: List[Dict[str, Any]],
    *,
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
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    timeout: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    return _completion_impl(
        model=model,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        n=n,
        stream=stream,
        stop=stop,
        max_tokens=max_tokens,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        logit_bias=logit_bias,
        user=user,
        custom_llm_provider=custom_llm_provider,
        api_key=api_key,
        api_base=api_base,
        timeout=timeout,
        **kwargs,
    )


def _completion_impl(  # noqa: PLR0915
    model: str,
    messages: List[Dict[str, Any]],
    *,
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
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    timeout: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    # Build optional params
    non_default_params = get_non_default_completion_params(kwargs)
    optional_params = get_optional_params(
        model=model,
        temperature=temperature,
        top_p=top_p,
        n=n,
        stream=stream,
        stop=stop,
        max_tokens=max_tokens,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        logit_bias=logit_bias,
        user=user,
        custom_llm_provider=custom_llm_provider,
        **non_default_params,
    )

    # If router is configured, compute route attempts.
    cfg, _group, _alias, attempts = resolve_route_attempts(
        model=model, user=user, explicit_provider=custom_llm_provider
    )

    # Routing not applicable → normal provider resolution
    if not attempts:
        resolved_model, provider, dyn_key, dyn_base = get_llm_provider(
            model=model, custom_llm_provider=custom_llm_provider, api_key=api_key, api_base=api_base
        )
        return _call_provider_sync(
            provider=provider or "openai",
            model=resolved_model,
            messages=messages,
            optional_params=optional_params,
            api_key=dyn_key or api_key,
            api_base=dyn_base or api_base,
            timeout=timeout,
        )

    retry = cfg.retry if cfg else None
    cbp = cfg.circuit_breaker if cfg else None
    cb = _get_circuit_breaker(
        open_after_failures=(cbp.open_after_failures if cbp else 5),
        cooldown_seconds=(cbp.cooldown_seconds if cbp else 30),
    )

    last_exc: Optional[Exception] = None

    # Streaming: do not retry/failover after starting output; simplest v1 behavior is no retry at all.
    # (We can safely improve this later by retrying only if failure happens before first chunk.)
    allow_retry = not bool(stream)

    for attempt in attempts:
        if cb.is_open(attempt):
            continue

        # attempt-level overrides
        attempt_timeout = timeout
        if attempt.timeout_s is not None:
            attempt_timeout = attempt.timeout_s

        max_attempts = max(1, int(retry.max_attempts)) if (retry and allow_retry) else 1

        for retry_idx in range(max_attempts):
            try:
                resp = _call_provider_sync(
                    provider=attempt.provider,
                    model=attempt.model,
                    messages=messages,
                    optional_params=dict(optional_params),
                    api_key=attempt.api_key or api_key,
                    api_base=attempt.api_base or api_base,
                    timeout=attempt_timeout,
                )
                cb.record_success(attempt)

                return resp
            except Exception as e:  # noqa: BLE001
                last_exc = e
                category = _classify_error(e)
                can_retry = bool(retry and allow_retry and category in set(retry.retry_on or []))
                if can_retry and (retry_idx < max_attempts - 1):
                    delay_s = _compute_backoff_s(
                        attempt_idx=retry_idx,
                        base_delay_ms=retry.base_delay_ms,
                        max_delay_ms=retry.max_delay_ms,
                        jitter=retry.jitter,
                    )
                    time.sleep(delay_s)
                    continue
                cb.record_failure(attempt)
                break

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Routing configured but no candidates were available")


async def acompletion(  # noqa: PLR0915
    model: str,
    messages: List[Dict[str, Any]],
    *,
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
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    timeout: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    return await _acompletion_impl(
        model=model,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        n=n,
        stream=stream,
        stop=stop,
        max_tokens=max_tokens,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        logit_bias=logit_bias,
        user=user,
        custom_llm_provider=custom_llm_provider,
        api_key=api_key,
        api_base=api_base,
        timeout=timeout,
        **kwargs,
    )


async def _acompletion_impl(  # noqa: PLR0915
    model: str,
    messages: List[Dict[str, Any]],
    *,
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
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    timeout: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    non_default_params = get_non_default_completion_params(kwargs)
    optional_params = get_optional_params(
        model=model,
        temperature=temperature,
        top_p=top_p,
        n=n,
        stream=stream,
        stop=stop,
        max_tokens=max_tokens,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        logit_bias=logit_bias,
        user=user,
        custom_llm_provider=custom_llm_provider,
        **non_default_params,
    )

    cfg, _group, _alias, attempts = resolve_route_attempts(
        model=model, user=user, explicit_provider=custom_llm_provider
    )

    if not attempts:
        resolved_model, provider, dyn_key, dyn_base = get_llm_provider(
            model=model, custom_llm_provider=custom_llm_provider, api_key=api_key, api_base=api_base
        )
        return await _call_provider_async(
            provider=provider or "openai",
            model=resolved_model,
            messages=messages,
            optional_params=optional_params,
            api_key=dyn_key or api_key,
            api_base=dyn_base or api_base,
            timeout=timeout,
        )

    retry = cfg.retry if cfg else None
    cbp = cfg.circuit_breaker if cfg else None
    cb = _get_circuit_breaker(
        open_after_failures=(cbp.open_after_failures if cbp else 5),
        cooldown_seconds=(cbp.cooldown_seconds if cbp else 30),
    )

    last_exc: Optional[Exception] = None
    allow_retry = not bool(stream)

    for attempt in attempts:
        if cb.is_open(attempt):
            continue

        attempt_timeout = timeout
        if attempt.timeout_s is not None:
            attempt_timeout = attempt.timeout_s

        max_attempts = max(1, int(retry.max_attempts)) if (retry and allow_retry) else 1
        for retry_idx in range(max_attempts):
            try:
                resp = await _call_provider_async(
                    provider=attempt.provider,
                    model=attempt.model,
                    messages=messages,
                    optional_params=dict(optional_params),
                    api_key=attempt.api_key or api_key,
                    api_base=attempt.api_base or api_base,
                    timeout=attempt_timeout,
                )
                cb.record_success(attempt)
                return resp
            except Exception as e:  # noqa: BLE001
                last_exc = e
                category = _classify_error(e)
                can_retry = bool(retry and allow_retry and category in set(retry.retry_on or []))
                if can_retry and (retry_idx < max_attempts - 1):
                    delay_s = _compute_backoff_s(
                        attempt_idx=retry_idx,
                        base_delay_ms=retry.base_delay_ms,
                        max_delay_ms=retry.max_delay_ms,
                        jitter=retry.jitter,
                    )
                    await asyncio.sleep(delay_s)
                    continue
                cb.record_failure(attempt)
                break

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Routing configured but no candidates were available")


# ------------------------------------------------------------------
# Legacy text completion wrappers (prompt -> chat)
# ------------------------------------------------------------------
def _prompt_to_messages(prompt: Union[str, List[Any]]) -> List[Dict[str, Any]]:
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    if isinstance(prompt, list):
        return [{"role": "user", "content": p} for p in prompt]
    raise ValueError("prompt must be a string or list")


def text_completion(prompt: Union[str, List[Any]], model: str, **kwargs: Any) -> Any:
    messages = _prompt_to_messages(prompt)
    return completion(model=model, messages=messages, **kwargs)


async def atext_completion(prompt: Union[str, List[Any]], model: str, **kwargs: Any) -> Any:
    messages = _prompt_to_messages(prompt)
    return await acompletion(model=model, messages=messages, **kwargs)


__all__ = ["completion", "acompletion", "text_completion", "atext_completion"]


