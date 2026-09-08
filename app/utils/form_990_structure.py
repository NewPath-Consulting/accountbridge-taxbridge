"""Rebuild the fixed parts of Form 990 from the line inventories.

Parts IV, V and VI are checklists. Their questions are printed on the form
and do not vary by organization, so the only thing the model can usefully
contribute is a yes or no against known facts. Asking it to supply the
questions as well produces invented ones -- Schedules S through AK in our
runs -- and there is no way to tell a fabricated line from a real one by
reading the output.

This module supplies the questions from `form_990_lines`, keeps whatever
answers the model gave for lines it recognised, and marks the rest for
determination. It then reports what is missing rather than leaving a
half-populated return looking complete.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.utils.form_990_lines import (
    PART_IV_CHECKLIST,
    PART_IX_LINES,
    PART_V_LINES,
    PART_VI_SECTION_A,
    PART_VI_SECTION_B,
    PART_VI_SECTION_C,
    VALID_SCHEDULES,
)

__all__ = [
    "StructureReport",
    "apply_static_line_inventories",
    "find_invented_schedules",
]

UNDETERMINED = "Undetermined"


class StructureReport:
    """The rebuilt content, with what was invented and what is still missing."""

    __slots__ = ("content", "invented", "missing", "notes")

    def __init__(
        self,
        content: dict[str, Any],
        invented: list[str],
        missing: list[str],
        notes: list[str],
    ) -> None:
        self.content = content
        self.invented = invented
        self.missing = missing
        self.notes = notes

    @property
    def is_complete(self) -> bool:
        return not self.missing

    def as_dict(self) -> dict[str, Any]:
        return {
            "invented_lines_removed": list(self.invented),
            "lines_awaiting_determination": list(self.missing),
            "notes": list(self.notes),
            "is_structurally_complete": self.is_complete,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"StructureReport(complete={self.is_complete!r})"


def _answer_index(rows: Any, line_key: str, answer_key: str) -> dict[str, Any]:
    """Map line number -> answer from whatever the model produced."""
    index: dict[str, Any] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        line = str(row.get(line_key) or "").strip()
        if line:
            index[line] = row.get(answer_key)
    return index


def find_invented_schedules(rows: Any) -> list[str]:
    """Return checklist rows referencing a schedule that does not exist.

    Form 990 schedules run A to R. A reference beyond that is fabricated,
    and its presence means the surrounding answers cannot be trusted either.

    Only uppercase tokens count as schedule identifiers, so ordinary prose
    such as "Schedule B, Schedule of Contributors" is not mistaken for a
    reference to a schedule named "of".
    """
    invented: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("question") or "")
        for token in re.findall(r"Schedule ([A-Z]{1,2})\b", text):
            if token not in VALID_SCHEDULES:
                invented.append(
                    f"line {row.get('line')}: references Schedule {token}, "
                    f"which does not exist"
                )
                break
    return invented


def _rebuild_checklist(
    existing: Any,
    inventory: tuple[tuple[str, str | None, str], ...] | tuple[tuple[str, str], ...],
    *,
    line_key: str = "line",
    answer_key: str = "answer",
    with_schedule: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    answers = _answer_index(existing, line_key, answer_key)
    rebuilt: list[dict[str, Any]] = []
    undetermined: list[str] = []

    for entry in inventory:
        if with_schedule:
            line, schedule, question = entry  # type: ignore[misc]
        else:
            line, question = entry  # type: ignore[misc]
            schedule = None

        answer = answers.get(line)
        if answer in (None, "", "N/A"):
            answer = UNDETERMINED
            undetermined.append(line)

        row: dict[str, Any] = {line_key: line, "question": question, answer_key: answer}
        if with_schedule and schedule:
            row["schedule"] = schedule
        rebuilt.append(row)

    return rebuilt, undetermined


def apply_static_line_inventories(content: Mapping[str, Any]) -> StructureReport:
    """Replace the checklist parts with the real IRS line inventories.

    Answers the model supplied for lines that genuinely exist are kept.
    Everything else is marked Undetermined and reported, so a preparer can
    see what still needs deciding rather than inheriting invented answers.
    """
    result = dict(content)
    invented: list[str] = []
    missing: list[str] = []
    notes: list[str] = []

    # --- Part IV ---------------------------------------------------------
    original_iv = result.get("partIV_checklistOfRequiredSchedules")
    invented.extend(find_invented_schedules(original_iv))

    rebuilt_iv, undetermined_iv = _rebuild_checklist(
        original_iv, PART_IV_CHECKLIST, with_schedule=True
    )
    result["partIV_checklistOfRequiredSchedules"] = rebuilt_iv
    if undetermined_iv:
        missing.append(
            f"Part IV: {len(undetermined_iv)} of {len(PART_IV_CHECKLIST)} lines undetermined"
        )
    if isinstance(original_iv, list) and len(original_iv) != len(PART_IV_CHECKLIST):
        notes.append(
            f"PART_IV_LINE_COUNT: model produced {len(original_iv)} rows; "
            f"the form has {len(PART_IV_CHECKLIST)} answer boxes"
        )

    # --- Part V ----------------------------------------------------------
    original_v = result.get("partV_statementsRegardingOtherIRSFilings")
    rebuilt_v, undetermined_v = _rebuild_checklist(
        original_v, PART_V_LINES, answer_key="value"
    )
    result["partV_statementsRegardingOtherIRSFilings"] = rebuilt_v
    if undetermined_v:
        missing.append(
            f"Part V: {len(undetermined_v)} of {len(PART_V_LINES)} lines undetermined"
        )

    # --- Part VI ---------------------------------------------------------
    governance = dict(result.get("partVI_governance") or {})

    rebuilt_a, undetermined_a = _rebuild_checklist(
        governance.get("sectionA"), PART_VI_SECTION_A, answer_key="value"
    )
    governance["sectionA"] = rebuilt_a
    if undetermined_a:
        missing.append(
            f"Part VI Section A: {len(undetermined_a)} of {len(PART_VI_SECTION_A)} lines undetermined"
        )

    rebuilt_b, undetermined_b = _rebuild_checklist(
        governance.get("sectionB_policies"), PART_VI_SECTION_B
    )
    governance["sectionB_policies"] = rebuilt_b
    if undetermined_b:
        missing.append(
            f"Part VI Section B: {len(undetermined_b)} of {len(PART_VI_SECTION_B)} lines undetermined"
        )

    disclosure = dict(governance.get("sectionC_disclosure") or {})
    disclosure.setdefault("lines", [
        {"line": line, "question": question}
        for line, question in PART_VI_SECTION_C
    ])
    governance["sectionC_disclosure"] = disclosure
    result["partVI_governance"] = governance

    # --- Part IX ---------------------------------------------------------
    # Expense lines carry amounts rather than answers, so the inventory is
    # applied as labels only. Amounts remain whatever the deterministic
    # engine supplied.
    expenses = result.get("partIX_expenses")
    if isinstance(expenses, list) and expenses:
        labels = dict(PART_IX_LINES)
        relabelled = []
        for row in expenses:
            if not isinstance(row, dict):
                continue
            line = str(row.get("line_number") or "").strip()
            amended = dict(row)
            if line in labels:
                amended["label"] = labels[line]
            else:
                amended["label"] = None
                notes.append(
                    f"PART_IX_UNKNOWN_LINE: {line!r} is not a Part IX line number"
                )
            relabelled.append(amended)
        result["partIX_expenses"] = relabelled

    if invented:
        notes.append(
            f"PART_IV_INVENTED_SCHEDULES: {len(invented)} row(s) referenced "
            f"schedules beyond R and were replaced"
        )

    return StructureReport(result, invented, missing, notes)
