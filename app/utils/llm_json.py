"""Helpers for parsing and recovering JSON from LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple


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


def _json_closers_for_prefix(text: str) -> str:
    """Return suffix characters needed to close an incomplete JSON prefix."""
    stack: list[str] = []
    in_string = False
    escape = False

    for char in text:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()

    suffix = ""
    if in_string:
        suffix += '"'
    suffix += "".join(reversed(stack))
    return suffix


def coerce_llm_dict(llm_output: Any) -> Dict[str, Any]:
    """
    Normalize an LLM response into a JSON object dict.

    Handles Bedrock/OpenAI chat envelopes (choices[].message.content), nested
    ``result`` keys, raw JSON strings, and Pydantic model_dump objects.
    """
    from app.core.model_gateway.test_utils import extract_text

    if llm_output is None:
        return {"_parse_error": True, "_raw": "null response"}

    if hasattr(llm_output, "model_dump"):
        try:
            llm_output = llm_output.model_dump()
        except Exception:
            pass

    if isinstance(llm_output, dict):
        if llm_output.get("_parse_error"):
            return llm_output
        if "error" in llm_output and len(llm_output) <= 2:
            return llm_output
        if any(
            key in llm_output
            for key in (
                "organization_summary",
                "organizationInformation",
                "revenue",
                "operating_activities",
                "operatingActivities",
                "score",
                "overall_score",
            )
        ):
            return llm_output
        if "result" in llm_output:
            return coerce_llm_dict(llm_output["result"])
        if llm_output.get("choices") or llm_output.get("usage"):
            text = extract_text(llm_output)
            if text:
                return coerce_llm_dict(text)
        return llm_output

    if isinstance(llm_output, str):
        parsed, _ = salvage_json_object(llm_output)
        if isinstance(parsed, dict):
            return coerce_llm_dict(parsed)
        return {"_parse_error": True, "_raw": llm_output[:500]}

    text = extract_text(llm_output)
    if text:
        return coerce_llm_dict(text)
    return {"_parse_error": True, "_raw": str(llm_output)[:500]}


def salvage_json_object(raw_text: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Parse JSON from model text; if that fails, try to recover a truncated object.
    Returns (parsed_dict_or_none, was_salvaged).
    """
    json_text = _extract_json_from_llm_response(raw_text)
    try:
        parsed = json.loads(json_text)
        if isinstance(parsed, dict):
            return parsed, False
    except json.JSONDecodeError:
        pass

    trimmed = json_text.rstrip()
    min_length = max(0, len(trimmed) - 8000)
    for end in range(len(trimmed), min_length, -1):
        candidate = trimmed[:end].rstrip().rstrip(",")
        if not candidate:
            continue
        closers = _json_closers_for_prefix(candidate)
        try:
            parsed = json.loads(candidate + closers)
            if isinstance(parsed, dict):
                return parsed, True
        except json.JSONDecodeError:
            continue

    return None, False
