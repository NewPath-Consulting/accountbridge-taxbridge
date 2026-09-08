"""Deterministic totals from a QuickBooks Balance Sheet, and Part X enforcement.

Part VIII was taken away from the model in an earlier step. Part X was not,
and it shows: across two runs against the same company the model reported net
assets of -7,695.04 and then 23,436.29 -- the second being the total assets
figure copied from elsewhere on the page.

That is not only a wrong line on the return. Form routing reads total assets
from Part X, and the 990-EZ test requires them below $500,000, so a duplicated
figure can change which form an organization files.

The balance sheet is shaped differently from the profit and loss. Its sections
nest: `Liabilities` sits inside `TotalLiabilitiesAndEquity` rather than at the
top level, so sections are found by searching the tree rather than by scanning
its first level.

Net assets are computed as assets less liabilities rather than read from the
report, because that identity is what the IRS checks on the face of the form.
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping, Optional

from app.utils.form_990_totals import PLAccount, _money, iter_accounts

__all__ = [
    "BalanceSheetTotals",
    "balance_sheet_totals",
    "enforce_part_x",
    "find_section",
    "section_accounts",
]

# QuickBooks group markers, in the order they appear on the report.
ASSET_GROUPS = ("BankAccounts", "AR", "OtherCurrentAssets", "FixedAssets", "OtherAssets")
LIABILITY_GROUPS = (
    "AP", "CreditCards", "OtherCurrentLiabilities", "LongTermLiabilities",
)

# Group -> the Form 990 Part X line it maps to.
PART_X_ASSET_LINES = {
    "BankAccounts": ("1", "Cash - non-interest-bearing"),
    "AR": ("4", "Accounts receivable, net"),
    "OtherCurrentAssets": ("9", "Prepaid expenses and deferred charges"),
    "FixedAssets": ("10c", "Land, buildings, and equipment, net"),
    "OtherAssets": ("15", "Other assets"),
}

PART_X_LIABILITY_LINES = {
    "AP": ("17", "Accounts payable and accrued expenses"),
    "CreditCards": ("17", "Accounts payable and accrued expenses"),
    "OtherCurrentLiabilities": ("25", "Other liabilities"),
    "LongTermLiabilities": ("23", "Secured mortgages and notes payable"),
}


class BalanceSheetTotals:
    """The three figures Part X turns on, and the detail behind them."""

    __slots__ = ("total_assets", "total_liabilities", "net_assets", "assets", "liabilities")

    def __init__(
        self,
        total_assets: float,
        total_liabilities: float,
        assets: list[dict[str, Any]],
        liabilities: list[dict[str, Any]],
    ) -> None:
        self.total_assets = total_assets
        self.total_liabilities = total_liabilities
        # Computed, never read. Assets less liabilities is the identity the
        # IRS checks, so deriving it means the return cannot contradict itself.
        self.net_assets = round(total_assets - total_liabilities, 2)
        self.assets = assets
        self.liabilities = liabilities

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_assets": self.total_assets,
            "total_liabilities": self.total_liabilities,
            "net_assets": self.net_assets,
            "assets": list(self.assets),
            "liabilities": list(self.liabilities),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"BalanceSheetTotals(assets={self.total_assets!r}, "
            f"liabilities={self.total_liabilities!r})"
        )


def _rows(node: Any) -> list[dict[str, Any]]:
    return (node or {}).get("Row", []) or []


def find_section(report: Mapping[str, Any] | None, group: str) -> Optional[dict[str, Any]]:
    """Find a section anywhere in the tree by its group marker.

    Balance sheet sections nest, so a scan of the top level is not enough:
    `Liabilities` sits inside `TotalLiabilitiesAndEquity`.
    """

    def search(node: Any) -> Optional[dict[str, Any]]:
        for row in _rows(node):
            if not isinstance(row, dict):
                continue
            if str(row.get("group") or "") == group:
                return row
            found = search(row.get("Rows"))
            if found is not None:
                return found
        return None

    return search((report or {}).get("Rows"))


def _section_total(section: Optional[Mapping[str, Any]]) -> float:
    if not section:
        return 0.0
    summary = (section.get("Summary") or {}).get("ColData") or []
    if len(summary) > 1:
        return _money(summary[1].get("value"))
    header = (section.get("Header") or {}).get("ColData") or []
    if len(header) > 1:
        return _money(header[1].get("value"))
    return 0.0


def section_accounts(
    report: Mapping[str, Any] | None, group: str
) -> list[PLAccount]:
    """Every account inside one section, each counted exactly once."""
    section = find_section(report, group)
    if section is None:
        return []
    return list(iter_accounts(section.get("Rows")))


def _collect(
    report: Mapping[str, Any] | None,
    groups: tuple[str, ...],
    lines: Mapping[str, tuple[str, str]],
) -> list[dict[str, Any]]:
    """Gather sections and combine any that share a Part X line.

    Several QuickBooks groups map to one line on the form -- accounts payable
    and credit cards are both accounts payable and accrued expenses -- and the
    form has one box for them, so they are added together rather than listed
    twice against the same number.
    """
    collected: list[dict[str, Any]] = []
    by_line: dict[str, dict[str, Any]] = {}

    for group in groups:
        section = find_section(report, group)
        if section is None:
            continue
        accounts = section_accounts(report, group)
        total = round(_section_total(section), 2)
        if not total and not accounts:
            continue

        line, label = lines.get(group, ("", group))
        detail = [
            {"name": a.name, "amount": a.amount, "account_id": a.account_id}
            for a in accounts
        ]

        existing = by_line.get(line)
        if existing is None:
            entry = {
                "group": group,
                "groups": [group],
                "lineNumber": line,
                "label": label,
                "amount": total,
                "accounts": detail,
            }
            by_line[line] = entry
            collected.append(entry)
        else:
            existing["amount"] = round(existing["amount"] + total, 2)
            existing["groups"].append(group)
            existing["accounts"].extend(detail)

    return collected


def balance_sheet_totals(
    report: Mapping[str, Any] | None,
) -> Optional[BalanceSheetTotals]:
    """Compute the Part X figures from a QuickBooks Balance Sheet.

    Returns None when the report carries no sections, so callers can tell
    "no data" apart from "genuinely zero".
    """
    if not report or not _rows((report or {}).get("Rows")):
        return None

    assets_section = find_section(report, "TotalAssets")
    liabilities_section = find_section(report, "Liabilities")
    if assets_section is None and liabilities_section is None:
        return None

    return BalanceSheetTotals(
        total_assets=round(_section_total(assets_section), 2),
        total_liabilities=round(_section_total(liabilities_section), 2),
        assets=_collect(report, ASSET_GROUPS, PART_X_ASSET_LINES),
        liabilities=_collect(report, LIABILITY_GROUPS, PART_X_LIABILITY_LINES),
    )


def enforce_part_x(
    content: dict[str, Any],
    balance_sheet_report: Mapping[str, Any] | None,
    *,
    prior_report: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Rebuild Part X from the ledger, keeping nothing the model supplied.

    Unlike Part VIII, there is no classification to preserve here. A balance
    sheet line is a balance sheet line; the mapping from QuickBooks group to
    Part X line is fixed, so the whole section is replaced.
    """
    notes: list[str] = []
    totals = balance_sheet_totals(balance_sheet_report)
    if totals is None:
        notes.append(
            "PART_X_NOT_ENFORCED: no QuickBooks balance sheet available; "
            "model figures left unchanged"
        )
        return content, notes

    prior = balance_sheet_totals(prior_report) if prior_report else None

    def opening(kind: str, group: str = "") -> float:
        if prior is None:
            return 0.0
        if kind == "assets":
            return prior.total_assets
        if kind == "liabilities":
            return prior.total_liabilities
        if kind == "net":
            return prior.net_assets
        for entry in (prior.assets if kind == "asset_line" else prior.liabilities):
            if group in entry.get("groups", [entry["group"]]):
                return entry["amount"]
        return 0.0

    existing = content.get("partX_balanceSheet") or {}
    previous_net = (
        ((existing.get("netAssets") or {}).get("totalNetAssets") or {}).get("endOfYear")
    )
    previous_assets = (existing.get("totalAssets") or {}).get("endOfYear")

    part_x = {
        "assets": [
            {
                "lineNumber": entry["lineNumber"],
                "label": entry["label"],
                "beginningOfYear": opening("asset_line", entry["group"]),
                "endOfYear": entry["amount"],
                "sourceSystem": "QuickBooks",
                "sourceAccounts": [a["name"] for a in entry["accounts"]],
            }
            for entry in totals.assets
        ],
        "totalAssets": {
            "beginningOfYear": opening("assets"),
            "endOfYear": totals.total_assets,
        },
        "liabilitiesAndNetAssets": [
            {
                "lineNumber": entry["lineNumber"],
                "label": entry["label"],
                "beginningOfYear": opening("liability_line", entry["group"]),
                "endOfYear": entry["amount"],
                "sourceSystem": "QuickBooks",
                "sourceAccounts": [a["name"] for a in entry["accounts"]],
            }
            for entry in totals.liabilities
        ],
        "totalLiabilities": {
            "beginningOfYear": opening("liabilities"),
            "endOfYear": totals.total_liabilities,
        },
        "netAssets": {
            "withoutDonorRestrictions": {
                "beginningOfYear": opening("net"),
                "endOfYear": totals.net_assets,
            },
            "withDonorRestrictions": {"beginningOfYear": 0.0, "endOfYear": 0.0},
            "totalNetAssets": {
                "beginningOfYear": opening("net"),
                "endOfYear": totals.net_assets,
            },
        },
        "totalLiabilitiesAndNetAssets": {
            "beginningOfYear": round(opening("liabilities") + opening("net"), 2),
            "endOfYear": round(totals.total_liabilities + totals.net_assets, 2),
        },
    }

    content["partX_balanceSheet"] = part_x

    try:
        if previous_assets is not None and round(float(previous_assets), 2) != totals.total_assets:
            notes.append(
                f"PART_X_ASSETS_CORRECTED: {previous_assets} -> {totals.total_assets}"
            )
    except (TypeError, ValueError):
        pass

    try:
        if previous_net is not None and round(float(previous_net), 2) != totals.net_assets:
            notes.append(
                f"PART_X_NET_ASSETS_CORRECTED: {previous_net} -> {totals.net_assets} "
                f"(assets {totals.total_assets} less liabilities "
                f"{totals.total_liabilities})"
            )
    except (TypeError, ValueError):
        pass

    if prior is None:
        notes.append(
            "PART_X_NO_OPENING_BALANCES: no prior-year balance sheet supplied, "
            "so beginning-of-year columns are zero"
        )

    return content, notes
