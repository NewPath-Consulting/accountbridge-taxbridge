from __future__ import annotations

from typing import Any, Optional

from .exceptions import ModelGatewayError


def exception_type(
    *,
    model: Optional[str],
    original_exception: BaseException,
    custom_llm_provider: Optional[str] = None,
    extra_kwargs: Optional[dict[str, Any]] = None,
) -> Exception:
    """
    Normalize arbitrary exceptions into a single, lightweight error type.
    """

    if isinstance(original_exception, ModelGatewayError):
        return original_exception
    return ModelGatewayError(
        message=str(original_exception),
        model=model,
        custom_llm_provider=custom_llm_provider,
        original_exception=original_exception,
        extra_kwargs=extra_kwargs,
    )

