"""Deterministic totals from a QuickBooks Profit & Loss report.

Every figure the tax return reports must be computed here, in code, from the
QuickBooks payload. The language model classifies accounts; it never supplies
an amount.

QuickBooks returns the P&L as a tree:

    Section  "Landscaping Services"   Header amount 1477.50   <- posted directly
      Section  "Job Materials"        Summary       4736.47
        Data   "Plants and Soil"                    2351.97
      Section  "Labor"                Summary        300.00
      Summary  "Total Landscaping Services"        6513.97

The Summary of a Section already contains both its children *and* any amount
posted directly to the parent account (its Header amount). Adding a Summary to
the rows beneath it double counts; summing only the leaves silently drops the
Header amount. Neither is correct on its own.

This module walks the tree once and yields each account exactly once, carrying
only the amount posted directly to it. The sum of those amounts equals the
section Summary, which `verify_section` asserts.
"""

from __future__ import annotations

from typing import Any, Iterator

__all__ = [
    "PLAccount",
    "iter_accounts",
    "section_rows",
    "section_total",
    "section_totals",
    "verify_section",
]

# Sections QuickBooks derives from the others. Counting these as well as their
# inputs would double count the entire report.
DERIVED_GROUPS = frozenset(
    {"GrossProfit", "NetOperatingIncome", "NetOtherIncome", "NetIncome"}
)

# Sections that carry real postings, mapped to a stable internal key.
REAL_GROUPS = {
    "Income": "income",
    "COGS": "cogs",
    "Expenses": "expenses",
    "OtherIncome": "other_income",
    "OtherExpenses": "other_expenses",
}


class PLAccount:
    """One account, carrying only the amount posted directly to it."""

    __slots__ = ("name", "account_id", "amount", "depth", "path", "is_parent")

    def __init__(
        self,
        name: str,
        account_id: str | None,
        amount: float,
        depth: int,
        path: tuple[str, ...],
        is_parent: bool,
    ) -> None:
        self.name = name
        self.account_id = account_id
        self.amount = amount
        self.depth = depth
        self.path = path
        self.is_parent = is_parent

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PLAccount({self.name!r}, {self.amount!r}, depth={self.depth})"


def _money(value: Any) -> float:
    """Parse a QuickBooks money string. Blank, None and junk become 0.0."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        amount = float(text)
    except ValueError:
        return 0.0
    return -amount if negative else amount


def _col(row: dict[str, Any], block: str, index: int) -> Any:
    cols = (row.get(block) or {}).get("ColData") or []
    if len(cols) > index:
        return cols[index]
    return {}


def iter_accounts(
    rows: dict[str, Any] | None,
    *,
    _depth: int = 0,
    _path: tuple[str, ...] = (),
) -> Iterator[PLAccount]:
    """Yield every account beneath ``rows`` exactly once.

    A Data row yields its own amount. A Section row yields the amount posted
    directly to the parent account (its Header amount, often blank) and then
    recurses. Summary values are never yielded: they are totals of what has
    already been counted.
    """
    for row in (rows or {}).get("Row", []) or []:
        if not isinstance(row, dict):
            continue

        row_type = str(row.get("type") or "").strip()

        if row_type == "Data" or ("ColData" in row and "Rows" not in row):
            cols = row.get("ColData") or []
            name = str((cols[0] if cols else {}).get("value") or "").strip()
            amount = _money((cols[1] if len(cols) > 1 else {}).get("value"))
            if name:
                yield PLAccount(
                    name=name,
                    account_id=(cols[0] if cols else {}).get("id"),
                    amount=amount,
                    depth=_depth,
                    path=_path,
                    is_parent=False,
                )
            continue

        header = _col(row, "Header", 0)
        name = str(header.get("value") or "").strip()
        own = _money(_col(row, "Header", 1).get("value"))

        # An amount on a Section header is money posted to the parent account
        # itself rather than to any child. It is a sibling of the children,
        # not a total of them, so it is counted here.
        if name and own:
            yield PLAccount(
                name=name,
                account_id=header.get("id"),
                amount=own,
                depth=_depth,
                path=_path,
                is_parent=True,
            )

        child_path = _path + ((name,) if name else ())
        yield from iter_accounts(row.get("Rows"), _depth=_depth + 1, _path=child_path)


def _top_sections(report: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for row in ((report or {}).get("Rows") or {}).get("Row", []) or []:
        if not isinstance(row, dict):
            continue
        group = str(row.get("group") or "").strip()
        if group and group not in DERIVED_GROUPS:
            yield group, row


def section_rows(report: dict[str, Any], group: str) -> list[PLAccount]:
    """Every account inside one top-level section, each counted once."""
    for name, row in _top_sections(report):
        if name == group:
            return list(iter_accounts(row.get("Rows")))
    return []


def section_total(report: dict[str, Any], group: str) -> float | None:
    """The Summary total QuickBooks reports for a top-level section."""
    for name, row in _top_sections(report):
        if name == group:
            return _money(_col(row, "Summary", 1).get("value"))
    return None


def section_totals(report: dict[str, Any]) -> dict[str, float]:
    """Headline totals keyed by internal name, computed from the report."""
    totals: dict[str, float] = {}
    for group, row in _top_sections(report):
        key = REAL_GROUPS.get(group)
        if not key:
            continue
        totals[key] = _money(_col(row, "Summary", 1).get("value"))
    return totals


def verify_section(report: dict[str, Any], group: str) -> tuple[float, float, float]:
    """Return (sum of accounts, reported total, difference).

    The difference must be zero. A non-zero value means the walk has either
    missed an account or counted one twice, and no figure derived from it can
    be trusted.
    """
    walked = round(sum(a.amount for a in section_rows(report, group)), 2)
    reported = section_total(report, group)
    reported = 0.0 if reported is None else round(reported, 2)
    return walked, reported, round(walked - reported, 2)
