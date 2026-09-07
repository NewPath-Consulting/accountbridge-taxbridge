"""Tests for Form 990 structural completeness.

The premise is an observed failure: across three runs against the same
company the model produced Part IV checklists referencing Schedules S
through AK, then AP, then AK again. Form 990 schedules end at R. The
questions are printed on the form and should never have been generated.
"""

import pytest

from app.utils.form_990_lines import (
    PART_IV_CHECKLIST,
    PART_V_LINES,
    PART_VI_SECTION_A,
    PART_VI_SECTION_B,
    VALID_SCHEDULES,
    part_iv_line_numbers,
)
from app.utils.form_990_structure import (
    UNDETERMINED,
    apply_static_line_inventories,
    find_invented_schedules,
)


@pytest.fixture
def model_output() -> dict:
    """A Part IV as the model actually produced it: correct for the first
    handful of lines, then the alphabet continued past R."""
    rows = [
        {"line": "1", "question": "Section 501(c)(3) or 4947(a)(1) organization?", "answer": "Yes"},
        {"line": "2", "question": "Required to complete Schedule B?", "answer": "No"},
        {"line": "3", "question": "Required to complete Schedule C?", "answer": "No"},
    ]
    for index, letter in enumerate("STUVWXYZ", start=19):
        rows.append({
            "line": str(index),
            "question": f"Required to complete Schedule {letter}?",
            "answer": "No",
        })
    for index, pair in enumerate(("AA", "AB", "AC", "AK"), start=27):
        rows.append({
            "line": str(index),
            "question": f"Required to complete Schedule {pair}?",
            "answer": "No",
        })
    return {
        "partIV_checklistOfRequiredSchedules": rows,
        "partV_statementsRegardingOtherIRSFilings": [
            {"line": "1a", "label": "Number reported in box 3 of Form 1096", "value": 0}
        ],
        "partVI_governance": {
            "sectionA": [
                {"line": "1a", "label": "Voting members of governing body", "value": 0}
            ],
            "sectionB_policies": [
                {"line": "12a", "label": "Written conflict of interest policy?", "answer": "No"}
            ],
        },
        "partIX_expenses": [
            {"line_number": "1", "amount": 15020.24, "classification": "Program Services"},
            {"line_number": "2", "amount": 658.08, "classification": "Management and General"},
        ],
    }


# --- the inventories themselves -------------------------------------------

def test_part_iv_has_every_answer_box():
    """Thirty-eight numbered lines, but more answer boxes because several
    lines have sub-parts."""
    lines = part_iv_line_numbers()
    assert len(lines) == len(set(lines)), "duplicate line numbers"
    assert "1" in lines and "38" in lines
    assert "11f" in lines and "24d" in lines and "28c" in lines


def test_no_inventory_line_references_a_schedule_beyond_r():
    for _, schedule, _ in PART_IV_CHECKLIST:
        if schedule:
            assert schedule in VALID_SCHEDULES


def test_known_schedule_anchors_are_correct():
    """Cross-checked against the IRS instructions: line 1 triggers Schedule
    A, lines 21 and 22 Schedule I, line 23 Schedule J, lines 31 and 32
    Schedule N, line 38 Schedule O."""
    mapping = {line: schedule for line, schedule, _ in PART_IV_CHECKLIST}
    assert mapping["1"] == "A"
    assert mapping["2"] == "B"
    assert mapping["21"] == "I"
    assert mapping["22"] == "I"
    assert mapping["23"] == "J"
    assert mapping["31"] == "N"
    assert mapping["32"] == "N"
    assert mapping["38"] == "O"


def test_part_v_and_vi_inventories_are_populated():
    assert len(PART_V_LINES) > 30
    assert len(PART_VI_SECTION_A) == 12
    assert len(PART_VI_SECTION_B) == 12


# --- detecting the fabrication --------------------------------------------

def test_invented_schedules_are_found(model_output):
    invented = find_invented_schedules(
        model_output["partIV_checklistOfRequiredSchedules"]
    )
    assert invented
    assert any("Schedule S" in note for note in invented)
    assert any("Schedule AK" in note for note in invented)


def test_real_schedules_are_not_flagged():
    rows = [
        {"line": "1", "question": "If 'Yes,' complete Schedule A"},
        {"line": "13", "question": "If 'Yes,' complete Schedule E"},
        {"line": "34", "question": "If 'Yes,' complete Schedule R"},
    ]
    assert find_invented_schedules(rows) == []


# --- the rebuild ----------------------------------------------------------

def test_checklist_is_replaced_with_the_real_inventory(model_output):
    report = apply_static_line_inventories(model_output)
    rebuilt = report.content["partIV_checklistOfRequiredSchedules"]
    assert len(rebuilt) == len(PART_IV_CHECKLIST)
    assert [r["line"] for r in rebuilt] == list(part_iv_line_numbers())


def test_no_invented_schedule_survives_the_rebuild(model_output):
    report = apply_static_line_inventories(model_output)
    assert find_invented_schedules(
        report.content["partIV_checklistOfRequiredSchedules"]
    ) == []


def test_answers_for_real_lines_are_kept(model_output):
    """The model was right about line 1. That answer survives."""
    report = apply_static_line_inventories(model_output)
    rebuilt = {r["line"]: r["answer"] for r in report.content["partIV_checklistOfRequiredSchedules"]}
    assert rebuilt["1"] == "Yes"
    assert rebuilt["2"] == "No"


def test_unanswered_lines_are_marked_not_guessed(model_output):
    report = apply_static_line_inventories(model_output)
    rebuilt = {r["line"]: r["answer"] for r in report.content["partIV_checklistOfRequiredSchedules"]}
    assert rebuilt["17"] == UNDETERMINED
    assert rebuilt["28c"] == UNDETERMINED


def test_schedule_reference_is_carried_as_data(model_output):
    report = apply_static_line_inventories(model_output)
    rebuilt = {r["line"]: r for r in report.content["partIV_checklistOfRequiredSchedules"]}
    assert rebuilt["1"]["schedule"] == "A"
    assert rebuilt["38"]["schedule"] == "O"


def test_line_count_discrepancy_is_reported(model_output):
    report = apply_static_line_inventories(model_output)
    assert any("PART_IV_LINE_COUNT" in note for note in report.notes)


def test_invented_lines_are_reported(model_output):
    report = apply_static_line_inventories(model_output)
    assert report.invented
    assert any("PART_IV_INVENTED_SCHEDULES" in note for note in report.notes)


# --- Parts V and VI -------------------------------------------------------

def test_part_v_is_expanded_from_one_line(model_output):
    """The model produced a single row against roughly forty answer boxes."""
    assert len(model_output["partV_statementsRegardingOtherIRSFilings"]) == 1
    report = apply_static_line_inventories(model_output)
    assert len(report.content["partV_statementsRegardingOtherIRSFilings"]) == len(PART_V_LINES)


def test_part_vi_sections_are_expanded(model_output):
    report = apply_static_line_inventories(model_output)
    governance = report.content["partVI_governance"]
    assert len(governance["sectionA"]) == len(PART_VI_SECTION_A)
    assert len(governance["sectionB_policies"]) == len(PART_VI_SECTION_B)


def test_part_vi_section_c_gets_its_line_list(model_output):
    report = apply_static_line_inventories(model_output)
    disclosure = report.content["partVI_governance"]["sectionC_disclosure"]
    assert len(disclosure["lines"]) == 4


# --- Part IX labels -------------------------------------------------------

def test_expense_lines_are_labelled(model_output):
    """Part IX line 5 is officer compensation and line 11 is fees for
    services. The model's output carried numbers with no labels at all."""
    report = apply_static_line_inventories(model_output)
    expenses = {r["line_number"]: r["label"] for r in report.content["partIX_expenses"]}
    assert "domestic organizations" in expenses["1"]
    assert "domestic individuals" in expenses["2"]


def test_expense_amounts_are_untouched(model_output):
    report = apply_static_line_inventories(model_output)
    amounts = {r["line_number"]: r["amount"] for r in report.content["partIX_expenses"]}
    assert amounts["1"] == 15020.24
    assert amounts["2"] == 658.08


def test_unknown_expense_line_is_reported(model_output):
    model_output["partIX_expenses"].append({"line_number": "99", "amount": 0})
    report = apply_static_line_inventories(model_output)
    assert any("PART_IX_UNKNOWN_LINE" in note for note in report.notes)


# --- completeness reporting -----------------------------------------------

def test_incomplete_return_is_declared_incomplete(model_output):
    report = apply_static_line_inventories(model_output)
    assert not report.is_complete
    assert any("Part IV" in m for m in report.missing)
    assert any("Part V" in m for m in report.missing)


def test_report_serialises(model_output):
    result = apply_static_line_inventories(model_output).as_dict()
    assert result["is_structurally_complete"] is False
    assert isinstance(result["invented_lines_removed"], list)
    assert isinstance(result["lines_awaiting_determination"], list)


def test_empty_content_produces_a_full_skeleton():
    report = apply_static_line_inventories({})
    assert len(report.content["partIV_checklistOfRequiredSchedules"]) == len(PART_IV_CHECKLIST)
    assert not report.is_complete


# --- the pass has to actually be wired in ---------------------------------
# It was written, tested, and then never called from the application. Reports
# shipped with Part V and Part VI entirely absent and nothing said so, because
# every test here exercised the function directly.

def test_the_reports_pipeline_applies_the_inventories():
    import inspect
    from app.services import reports_service

    source = inspect.getsource(reports_service)
    assert "apply_static_line_inventories" in source, (
        "reports_service no longer applies the static line inventories; "
        "Parts IV, V and VI would ship as whatever the model happened to emit"
    )


def test_the_filing_payload_receives_a_structure_report():
    import inspect
    from app.services import filing_service

    source = inspect.getsource(filing_service)
    assert "structure_report=" in source, (
        "build_draft_payload is being called without a structure_report, so "
        "confidence scores an absent Part V as complete"
    )


def test_the_prompt_does_not_ask_for_the_question_text():
    """The questions are static data; asking for them is what invents them."""
    from app.core.prompts.report_prompts import (
        build_tax_return_parts_i_vii_xi_xii_prompt,
    )

    prompt = build_tax_return_parts_i_vii_xi_xii_prompt(
        {}, {}, {}, {}, "2024-01-01", "2024-12-31"
    )["messages"][0]["content"]
    start = prompt.index("partIV_checklistOfRequiredSchedules")
    template = prompt[start : start + 400]
    assert '"question"' not in template
    assert '"line"' in template and '"answer"' in template
