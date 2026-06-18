"""Unit tests for benchmark LLM response parsing."""

from app.core.benchmark.llm import parse_benchmark_llm_response


def test_parse_benchmark_llm_response_extracts_score_from_bedrock_envelope():
    envelope = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"score": 2, "rating": "poor", "summary": "Large variance", '
                        '"key_differences": [], "issues": []}'
                    ),
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    parsed, err = parse_benchmark_llm_response(envelope)
    assert err is None
    assert parsed["score"] == 2
    assert parsed["rating"] == "poor"


def test_parse_benchmark_llm_response_extracts_synthesis_overall_score():
    envelope = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"overall_score": 2, "executive_summary": "Low match"}',
                }
            }
        ]
    }
    parsed, err = parse_benchmark_llm_response(envelope)
    assert err is None
    assert parsed["overall_score"] == 2
