from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class Usage(BaseModel):
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool", "developer"] = "assistant"
    content: Optional[Union[str, List[Any], Dict[str, Any]]] = None


class Choices(BaseModel):
    index: Optional[int] = None
    message: Optional[Message] = None
    finish_reason: Optional[str] = None
    # Legacy text-completions compat
    text: Optional[str] = None


class ModelResponse(BaseModel):
    """
    Minimal OpenAI-chat-compatible response shape.

    We allow extra fields because different SDK versions/providers can include
    additional keys (e.g. `system_fingerprint`, `service_tier`, etc.).
    """

    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    object: Optional[str] = None
    created: Optional[int] = None
    model: Optional[str] = None
    choices: List[Choices] = Field(default_factory=list)
    usage: Optional[Usage] = None

    _hidden_params: Dict[str, Any] = PrivateAttr(default_factory=dict)


class ModelResponseStream(BaseModel):
    """
    Placeholder for stream-chunk models.

    `model_gateway.aim_main` primarily forwards the OpenAI SDK iterator for
    streaming; this exists to preserve import compatibility.
    """

    model_config = ConfigDict(extra="allow")


class TextCompletionResponse(ModelResponse):
    """
    Legacy `/v1/completions`-style response shim.
    """

    pass


class ProviderConfigManager(BaseModel):
    """
    Lightweight placeholder to preserve `aim_main` import compatibility.
    """

    model_config = ConfigDict(extra="allow")

