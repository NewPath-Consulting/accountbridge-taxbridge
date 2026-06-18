from __future__ import annotations

from typing import Any, Optional


class ModelGatewayError(Exception):
    """
    A small, unified exception type for `model_gateway`.

    We keep this intentionally minimal: callers can inspect `model`,
    `custom_llm_provider`, and `original_exception` for debugging.
    """

    def __init__(
        self,
        message: str,
        *,
        model: Optional[str] = None,
        custom_llm_provider: Optional[str] = None,
        original_exception: Optional[BaseException] = None,
        extra_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.model = model
        self.custom_llm_provider = custom_llm_provider
        self.original_exception = original_exception
        self.extra_kwargs = extra_kwargs or {}


class ModelGatewayUnknownProvider(ModelGatewayError):
    def __init__(self, *, model: Optional[str], custom_llm_provider: Optional[str]) -> None:
        super().__init__(
            f"Unknown provider. model={model!r} custom_llm_provider={custom_llm_provider!r}",
            model=model,
            custom_llm_provider=custom_llm_provider,
        )

