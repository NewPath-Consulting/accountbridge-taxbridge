"""Unit tests for benchmark prompt builders."""

from app.core.prompts.benchmarking import (
    BENCHMARK_CASH_FLOW_OUTPUT_SCHEMA,
    BENCHMARK_FINAL_OUTPUT_SCHEMA,
    BENCHMARK_FORM_990_OUTPUT_SCHEMA,
    build_benchmark_cash_flow_prompt,
    build_benchmark_form_990_prompt,
    build_benchmark_synthesis_prompt,
)


def test_form_990_prompt_separates_instructions_and_data():
    body = build_benchmark_form_990_prompt(
        2024,
        {"revenue": {"total_revenue": 100}},
        {"status": "completed", "generated_tax_return_draft": {}},
    )
    content = body["messages"][0]["content"]
    assert "INPUT (JSON):" in content
    assert "manual_form_990_extraction" in content
    assert "ai_tax_return_report" in content
    assert "OUTPUT SCHEMA" in content
    assert body["max_tokens"] > 0
    assert body["max_tokens"] <= 4096


def test_cash_flow_prompt_uses_schema():
    body = build_benchmark_cash_flow_prompt(
        2024,
        {"operating_activities": {"operating_cash_flow": 1000}},
        {"status": "completed"},
    )
    content = body["messages"][0]["content"]
    assert "manual_cash_flow_extraction" in content
    assert "operating_cash_flow" in content


def test_synthesis_prompt_includes_section_reviews():
    body = build_benchmark_synthesis_prompt(
        2024,
        {"score": 90, "rating": "good", "summary": "990 ok"},
        {"score": 85, "rating": "good", "summary": "cf ok"},
        {"tax_return_processing_time": 10},
    )
    content = body["messages"][0]["content"]
    assert "form_990_review" in content
    assert "cash_flow_review" in content
    assert "processing_metadata" in content


def test_output_schemas_are_dicts():
    assert isinstance(BENCHMARK_FORM_990_OUTPUT_SCHEMA, dict)
    assert isinstance(BENCHMARK_CASH_FLOW_OUTPUT_SCHEMA, dict)
    assert isinstance(BENCHMARK_FINAL_OUTPUT_SCHEMA, dict)
    assert "overall_score" in BENCHMARK_FINAL_OUTPUT_SCHEMA
    assert "score" in BENCHMARK_FORM_990_OUTPUT_SCHEMA
