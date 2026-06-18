"""Unit tests for benchmark reference extraction coercion."""

from app.core.benchmark.extraction import _coerce_llm_output


def test_coerce_llm_output_unwraps_bedrock_envelope():
    payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"organization_summary": {"organization_name": "KCWG"}, '
                        '"revenue": {"total_revenue": 50000}}'
                    )
                }
            }
        ]
    }
    parsed = _coerce_llm_output(payload)
    assert parsed["organization_summary"]["organization_name"] == "KCWG"
    assert parsed["revenue"]["total_revenue"] == 50000
