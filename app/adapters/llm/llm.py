from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

from pydantic import BaseModel

from app.config.settings import get_settings
from app.core.model_gateway.aim_main import (
    acompletion,
    atext_completion,
    completion,
    text_completion,
)
from app.core.model_gateway.schemas import ModelResponse
from app.core.model_gateway.test_utils import (
    consume_async_stream,
    consume_sync_stream,
    extract_text,
    
)

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


def _extract_json_from_llm_response(raw: str) -> str:
    """Strip markdown code fences and isolate a JSON object from model text."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\n?```\s*$", "", text.strip())
    text = text.strip()
    if not text.startswith("{") and not text.startswith("["):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    return text


class Bedrock:
    """
    Adapter around ``aim_main`` chat/text completion, pinned to the Bedrock provider.

    ``get_llm_provider`` only selects Bedrock when the model string uses a ``bedrock/``
    prefix, a Bedrock ARN, or when ``custom_llm_provider="bedrock"`` is supplied; this
    wrapper always passes the latter so plain model IDs from settings work.
    """

    def __init__(
        self,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
    ) -> None:
        self.model_id = get_settings().LLM_MODEL
        self.temperature = (
            temperature
            if temperature is not None
            else get_settings().TEMPERATURE
        )
        self.max_tokens = (
            max_tokens if max_tokens is not None else get_settings().MAX_TOKENS
        )
        self.top_p = top_p if top_p is not None else get_settings().TOP_P

    def _provider_kwargs(self, **kwargs: Any) -> Dict[str, Any]:
        temperature = kwargs.get("temperature", self.temperature)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        top_p = kwargs.get("top_p", self.top_p)
        rest = {
            k: v
            for k, v in kwargs.items()
            if k not in ("temperature", "max_tokens", "top_p")
        }
        return {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "custom_llm_provider": "bedrock",
            **rest,
        }

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> Union[ModelResponse, Any]:
        try:
            logger.info(
                "Bedrock.chat called with model_id=%s, stream=%s, kwargs=%s",
                self.model_id,
                stream,
                kwargs,
            )
            response = completion(
                self.model_id,
                messages,
                stream=stream,
                **self._provider_kwargs(**kwargs),
            )
            logger.debug("Bedrock.chat response: %s", response)
            return response
        except Exception as e:
            logger.exception("Exception in Bedrock.chat: %s", e)
            raise

    async def achat(
        self,
        messages: List[Dict[str, Any]],
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> Union[ModelResponse, Any]:
        try:
            logger.info(
                "Bedrock.achat called with model_id=%s, stream=%s, kwargs=%s",
                self.model_id,
                stream,
                kwargs,
            )
            response = await acompletion(
                self.model_id,
                messages,
                stream=stream,
                **self._provider_kwargs(**kwargs),
            )
            logger.debug("Bedrock.achat response: %s", response)
            return response
        except Exception as e:
            logger.exception("Exception in Bedrock.achat: %s", e)
            raise

    def chat_text(
        self,
        messages: List[Dict[str, Any]],
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            logger.info("Bedrock.chat_text called")
            resp = self.chat(messages, stream=stream, **kwargs)
            if stream:
                result = consume_sync_stream(resp)
                logger.debug("Bedrock.chat_text (stream): %s", result)
                return result
            result = extract_text(resp).strip()
            logger.debug("Bedrock.chat_text (single): %s", result)
            return result
        except Exception as e:
            logger.exception("Exception in Bedrock.chat_text: %s", e)
            raise

    async def achat_text(
        self,
        messages: List[Dict[str, Any]],
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            logger.info("Bedrock.achat_text called")
            resp = await self.achat(messages, stream=stream, **kwargs)
            if stream:
                result = (await consume_async_stream(resp)).strip()
                logger.debug("Bedrock.achat_text (stream): %s", result)
                return result
            result = extract_text(resp).strip()
            logger.debug("Bedrock.achat_text (single): %s", result)
            return result
        except Exception as e:
            logger.exception("Exception in Bedrock.achat_text: %s", e)
            raise

    def complete_prompt(
        self,
        prompt: str,
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        try:
            logger.info("Bedrock.complete_prompt called")
            response = text_completion(
                prompt,
                self.model_id,
                stream=stream,
                **self._provider_kwargs(**kwargs),
            )
            logger.debug("Bedrock.complete_prompt response: %s", response)
            return response
        except Exception as e:
            logger.exception("Exception in Bedrock.complete_prompt: %s", e)
            raise

    async def acomplete_prompt(
        self,
        prompt: str,
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        try:
            logger.info("Bedrock.acomplete_prompt called")
            response = await atext_completion(
                prompt,
                self.model_id,
                stream=stream,
                **self._provider_kwargs(**kwargs),
            )
            logger.debug("Bedrock.acomplete_prompt response: %s", response)
            return response
        except Exception as e:
            logger.exception("Exception in Bedrock.acomplete_prompt: %s", e)
            raise

    def invoke_structured_output(
        self,
        messages: List[Dict[str, Any]],
        schema: Type[T],
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> T:
        """
        Ask the model for JSON matching ``schema`` and parse it into that model.

        Same keyword-only parameters as :meth:`achat` (``stream`` plus any extras
        handled by :meth:`_provider_kwargs`). ``stream=True`` is rejected; the call
        must be non-streaming so the assistant text is valid JSON for parsing.
        """
        logger.info(
            "Bedrock.invoke_structured_output called with schema=%s, stream=%s",
            schema,
            stream,
        )
        if stream:
            logger.error("stream=True is not supported for invoke_structured_output")
            raise ValueError(
                "invoke_structured_output requires stream=False (structured JSON)."
            )

        try:
            schema_json = json.dumps(schema.model_json_schema(), indent=2)
            full_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Respond with ONLY a single raw JSON object. "
                        "Do not wrap the JSON in markdown code fences or add commentary. "
                        f"It must satisfy this JSON Schema:\n{schema_json}"
                    ),
                },
            ]
            logger.debug(
                "Bedrock.invoke_structured_output full_messages: %s", full_messages
            )
            resp = self.chat(full_messages, stream=stream, **kwargs)
            raw = extract_text(resp).strip()
            logger.debug("Bedrock.invoke_structured_output raw model response: %s", raw)
            json_text = _extract_json_from_llm_response(raw)
            parsed = schema.model_validate_json(json_text)
            logger.info("Bedrock.invoke_structured_output successfully parsed response")
            return parsed
        except Exception as e:
            logger.exception("Exception in Bedrock.invoke_structured_output: %s", e)
            raise

    async def ainvoke_structured_output(
        self,
        messages: List[Dict[str, Any]],
        schema: Type[T],
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> T:
        """
        Async variant of :meth:`invoke_structured_output` using :meth:`achat`.
        """
        logger.info(
            "Bedrock.ainvoke_structured_output called with schema=%s, stream=%s",
            schema,
            stream,
        )
        if stream:
            logger.error("stream=True is not supported for ainvoke_structured_output")
            raise ValueError(
                "ainvoke_structured_output requires stream=False (structured JSON)."
            )

        try:
            schema_json = json.dumps(schema.model_json_schema(), indent=2)
            full_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Respond with ONLY a single raw JSON object. "
                        "Do not wrap the JSON in markdown code fences or add commentary. "
                        f"It must satisfy this JSON Schema:\n{schema_json}"
                    ),
                },
            ]
            logger.debug(
                "Bedrock.ainvoke_structured_output full_messages: %s", full_messages
            )
            resp = await self.achat(full_messages, stream=stream, **kwargs)
            raw = extract_text(resp).strip()
            logger.debug(
                "Bedrock.ainvoke_structured_output raw model response: %s", raw
            )
            json_text = _extract_json_from_llm_response(raw)
            parsed = schema.model_validate_json(json_text)
            logger.info(
                "Bedrock.ainvoke_structured_output successfully parsed response"
            )
            return parsed
        except Exception as e:
            logger.exception(
                "Exception in Bedrock.ainvoke_structured_output: %s", e
            )
            raise


if __name__ == "__main__":
    # Demonstrate structured output call with Bedrock adapter
    import asyncio

    # Example Pydantic schema for structured output
    class GreetingResponse(BaseModel):
        greeting: str
        identity: str

    # Example payloads for the structured output
    sample_structured_messages = [
        {"role": "user", "content": "Say hello and tell me who you are in JSON."}
    ]
    bedrock = Bedrock()

    async def structured_demo():
        print("Async invoke_structured_output demo:")
        try:
            result = await bedrock.ainvoke_structured_output(
                sample_structured_messages, GreetingResponse
            )
            print("Structured output:", result)
        except Exception as ex:
            print(f"Error during invoke_structured_output: {ex}")

    asyncio.run(structured_demo())
