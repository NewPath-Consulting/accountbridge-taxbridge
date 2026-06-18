"""Unit tests for LLM JSON coercion helpers."""

from app.utils.llm_json import coerce_llm_dict


def test_coerce_llm_dict_parses_bedrock_choices_envelope():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"revenue": {"total_revenue": 120000}, '
                        '"expenses": {"total_expenses": 95000}}'
                    ),
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    parsed = coerce_llm_dict(payload)
    assert parsed["revenue"]["total_revenue"] == 120000
    assert parsed["expenses"]["total_expenses"] == 95000


def test_coerce_llm_dict_passthrough_structured_dict():
    payload = {"operating_activities": {"operating_cash_flow": 1000}}
    assert coerce_llm_dict(payload) == payload
