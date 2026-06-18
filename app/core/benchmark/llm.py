"""LLM runner for benchmark evaluation steps."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

from app.config.settings import settings
from app.utils.llm_json import coerce_llm_dict

logger = logging.getLogger(__name__)


def parse_benchmark_llm_response(raw_response: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Normalize a Bedrock/OpenAI completion into a benchmark review dict."""
    parsed = coerce_llm_dict(raw_response)
    if parsed.get("_parse_error"):
        preview = parsed.get("_raw") or parsed.get("_raw_preview") or ""
        return parsed, f"Failed to parse LLM response as JSON: {str(preview)[:200]}"
    return parsed, None


async def run_benchmark_llm(
    prompt_body: Dict[str, Any],
    *,
    step: str = "benchmark",
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Call LLM for a benchmark step and return parsed JSON."""
    from app.core.model_gateway.aim_main import acompletion

    started = time.monotonic()
    logger.info(
        "Benchmark LLM start: step=%s model=%s timeout=%ss",
        step,
        settings.LLM_MODEL,
        settings.REPORTS_LLM_TIMEOUT,
    )

    try:
        response = await acompletion(
            model=settings.LLM_MODEL,
            custom_llm_provider=settings.LLM_PROVIDER,
            timeout=settings.REPORTS_LLM_TIMEOUT,
            **prompt_body,
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - started
        logger.error(
            "Benchmark LLM timed out: step=%s elapsed=%.2fs limit=%ss",
            step,
            elapsed,
            settings.REPORTS_LLM_TIMEOUT,
        )
        return {"_parse_error": True}, "LLM processing timed out"
    except Exception as exc:
        elapsed = time.monotonic() - started
        logger.error(
            "Benchmark LLM failed: step=%s elapsed=%.2fs error=%s",
            step,
            elapsed,
            exc,
        )
        return {"_parse_error": True}, str(exc)

    elapsed = time.monotonic() - started
    logger.info("Benchmark LLM done: step=%s elapsed=%.2fs", step, elapsed)

    return parse_benchmark_llm_response(response.get("result", response))
