"""Part VIII classification scored against the key that ships with the fixture.

`data/crn_synthetic.json` carries `expected_classification.line_mapping`: which
Form 990 Part VIII family each CRN income account belongs on, taken from the
filed returns and written when the fixture was built, without reference to the
classifier. That is an answer key, and this scores against it.

Scoring against the key is what the key is for. Writing prompt rules from it is
what spoils the test, and CRN 2024 is spoiled that way -- the sponsorship and
trade show rules in the Part VIII prompt were written after reading its filed
return. 2019 to 2023 are clean.

**Why it wants several runs per year rather than one.** Classification is
stable within a year and flips between years. Three runs on 2024 produced
byte-identical Part VIII, which reads as reproducibility and is not: the same
account classifies differently on 2021 and 2023. Membership dues have landed on
1b, 2a and 1f across six years -- three answers for one unchanged account name.

A single run per year therefore cannot tell "wrong about membership dues" from
"inconsistent about membership dues", and those want opposite fixes: a rule for
the first, a constraint for the second. Reading a repeated run as agreement is
how an earlier round of this work concluded that a prompt rule "never worked,
five for five" when four of the five were the same year and the rule in fact
worked in four years of six.

So every account is scored across every run of every year and given a verdict:

    correct       every run put it in the right family
    wrong         every run agreed with each other and all were wrong
    inconsistent  the runs disagree

Only the family is scored, never the sub-letter. Dues on 1b and dues on 1f are
both contributions: same section of the form, same money, and the choice among
filer-described rows carries nothing we could grade. Families come from
`part_viii_family_for_line` rather than a second copy of the mapping, so the
harness cannot drift from what enforcement actually does.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from app.utils.form_990_enforce import part_viii_family_for_line

__all__ = [
    "AnswerKey",
    "Placement",
    "AccountVerdict",
    "YearScore",
    "Report",
    "load_answer_key",
    "load_run",
    "load_runs",
    "score",
]

DEFAULT_FIXTURE = Path("data/crn_synthetic.json")

# The fixture names families the way the filed return does; the code names them
# the way Part VIII groups them. Same three things.
_KEY_TO_FAMILY = {
    "contributions": "contributions",
    "program_service_revenue": "program_service",
    "investment_income": "investment",
}


@dataclass(frozen=True)
class AnswerKey:
    """Account name -> the Part VIII family the filed return puts it on."""

    families: Mapping[str, str]
    published_revenue: Mapping[int, float] = field(default_factory=dict)

    def family_for(self, account: str) -> str | None:
        return self.families.get(_norm(account))


@dataclass(frozen=True)
class Placement:
    """Where one run put one account."""

    year: int
    run_id: str
    account: str
    line_number: str
    family: str | None
    amount: float
    expected: str | None

    @property
    def is_scored(self) -> bool:
        """False for an account the key says nothing about."""
        return self.expected is not None

    @property
    def is_correct(self) -> bool:
        return self.is_scored and self.family == self.expected


@dataclass
class Run:
    year: int
    run_id: str
    source: str
    placements: list[Placement]
    stated_total: float


@dataclass
class AccountVerdict:
    """One account's behaviour across every run of every year."""

    account: str
    expected: str
    runs: int = 0
    correct: int = 0
    families: Counter = field(default_factory=Counter)
    lines: Counter = field(default_factory=Counter)
    years_right: list[int] = field(default_factory=list)
    years_wrong: list[int] = field(default_factory=list)
    dollars: float = 0.0
    dollars_correct: float = 0.0

    @property
    def verdict(self) -> str:
        if self.runs and self.correct == self.runs:
            return "correct"
        if self.correct == 0 and len(self.families) == 1:
            return "wrong"
        return "inconsistent"

    def as_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "expected": self.expected,
            "verdict": self.verdict,
            "runs": self.runs,
            "correct": self.correct,
            "families": dict(self.families),
            "lines": dict(self.lines),
            "years_right": sorted(set(self.years_right)),
            "years_wrong": sorted(set(self.years_wrong)),
            "dollars": round(self.dollars, 2),
            "dollars_correct": round(self.dollars_correct, 2),
        }


@dataclass
class YearScore:
    year: int
    runs: int = 0
    accounts: int = 0
    accounts_correct: int = 0
    dollars: float = 0.0
    dollars_correct: float = 0.0
    unscored: list[str] = field(default_factory=list)
    total_mismatch: float | None = None

    @property
    def pct(self) -> float:
        return round(100.0 * self.dollars_correct / self.dollars, 1) if self.dollars else 0.0

    # Dollars are summed over every run of the year, so a year that happens to
    # have been run seven times would otherwise outweigh one run seven-fold in
    # any total. These are the per-run means, and totals are built from them so
    # each year counts once whatever its run count.
    @property
    def mean_dollars(self) -> float:
        return self.dollars / self.runs if self.runs else 0.0

    @property
    def mean_dollars_correct(self) -> float:
        return self.dollars_correct / self.runs if self.runs else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "runs": self.runs,
            "accounts_scored": self.accounts,
            "accounts_correct": self.accounts_correct,
            "mean_dollars": round(self.mean_dollars, 2),
            "mean_dollars_correct": round(self.mean_dollars_correct, 2),
            "pct": self.pct,
            "unscored_accounts": sorted(set(self.unscored)),
            "total_vs_published": self.total_mismatch,
        }


@dataclass
class Report:
    years: list[YearScore]
    accounts: list[AccountVerdict]
    placements: list[Placement]
    contaminated_years: frozenset[int] = frozenset({2024})

    def _totals(self, years: Iterable[int] | None = None) -> tuple[float, float, int, int]:
        """Per-run means, so every year counts once however often it was run."""
        keep = set(years) if years is not None else {y.year for y in self.years}
        rows = [y for y in self.years if y.year in keep]
        return (
            sum(y.mean_dollars_correct for y in rows),
            sum(y.mean_dollars for y in rows),
            sum(y.accounts_correct for y in rows),
            sum(y.accounts for y in rows),
        )

    def overall_pct(self, *, clean_only: bool = False) -> float:
        years = None
        if clean_only:
            years = [y.year for y in self.years if y.year not in self.contaminated_years]
        ok, total, _, _ = self._totals(years)
        return round(100.0 * ok / total, 1) if total else 0.0

    def as_dict(self) -> dict[str, Any]:
        ok, total, acct_ok, acct_all = self._totals()
        return {
            "years": [y.as_dict() for y in self.years],
            "accounts": [a.as_dict() for a in self.accounts],
            "overall": {
                "mean_dollars_correct": round(ok, 2),
                "mean_dollars": round(total, 2),
                "pct": self.overall_pct(),
                "pct_excluding_contaminated": self.overall_pct(clean_only=True),
                "accounts_correct": acct_ok,
                "accounts": acct_all,
                "contaminated_years": sorted(self.contaminated_years),
            },
        }


def _norm(name: Any) -> str:
    return " ".join(str(name or "").split()).lower()


def _amount(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def load_answer_key(fixture: Path | str = DEFAULT_FIXTURE) -> AnswerKey:
    """Read `expected_classification.line_mapping` out of the fixture."""
    data = json.loads(Path(fixture).read_text(encoding="utf-8"))
    mapping = data["expected_classification"]["line_mapping"]

    families: dict[str, str] = {}
    for key_family, accounts in mapping.items():
        family = _KEY_TO_FAMILY.get(key_family)
        if family is None or not isinstance(accounts, list):
            continue  # "_comment" and "note" live in the same object
        for account in accounts:
            families[_norm(account)] = family

    published = {
        int(year["year"]): float((year.get("published") or {}).get("revenue") or 0.0)
        for year in data.get("years") or []
        if year.get("year")
    }
    return AnswerKey(families=families, published_revenue=published)


def _revenue_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Part VIII line items, wherever this payload keeps them."""
    for path in (
        ("reports", "tax_return", "content", "partVIII_revenue"),
        ("tax_return", "content", "partVIII_revenue"),
        ("content", "partVIII_revenue"),
        ("partVIII_revenue",),
    ):
        node: Any = payload
        for step in path:
            node = node.get(step) if isinstance(node, Mapping) else None
            if node is None:
                break
        if isinstance(node, list):
            return [i for i in node if isinstance(i, dict)]
    return []


def _stated_total(payload: Mapping[str, Any]) -> float:
    for path in (
        ("reports", "tax_return", "content", "partVIII_totalRevenue"),
        ("tax_return", "content", "partVIII_totalRevenue"),
        ("content", "partVIII_totalRevenue"),
        ("partVIII_totalRevenue",),
    ):
        node: Any = payload
        for step in path:
            node = node.get(step) if isinstance(node, Mapping) else None
            if node is None:
                break
        if node is not None:
            return _amount(node)
    return 0.0


def load_run(path: Path | str, key: AnswerKey) -> Run | None:
    """One saved /api/reports response. None when it carries no Part VIII."""
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(payload, Mapping):
        return None

    period = str(payload.get("start_date") or payload.get("end_date") or "")
    try:
        year = int(period[:4])
    except ValueError:
        return None

    items = _revenue_items(payload)
    if not items:
        return None

    run_id = str(payload.get("request_id") or path.stem)
    placements = [
        Placement(
            year=year,
            run_id=run_id,
            account=str(item.get("label") or ""),
            line_number=str(item.get("lineNumber") or ""),
            family=part_viii_family_for_line(item.get("lineNumber")),
            amount=_amount(item.get("totalRevenue")),
            expected=key.family_for(item.get("label")),
        )
        for item in items
    ]
    return Run(year, run_id, str(path), placements, _stated_total(payload))


def load_runs(paths: Sequence[Path | str], key: AnswerKey) -> list[Run]:
    runs = [load_run(p, key) for p in paths]
    return sorted(
        (r for r in runs if r is not None), key=lambda r: (r.year, r.run_id)
    )


def score(runs: Sequence[Run], key: AnswerKey) -> Report:
    """Aggregate runs into per-year scores and per-account verdicts."""
    by_year: dict[int, YearScore] = {}
    by_account: dict[str, AccountVerdict] = {}
    placements: list[Placement] = []
    seen_runs: dict[int, set[str]] = defaultdict(set)

    for run in runs:
        year = by_year.setdefault(run.year, YearScore(year=run.year))
        seen_runs[run.year].add(run.run_id)

        published = key.published_revenue.get(run.year)
        if published:
            mismatch = round(run.stated_total - published, 2)
            # Any run of the year disagreeing is worth surfacing, so keep the
            # largest gap rather than the last one seen.
            if year.total_mismatch is None or abs(mismatch) > abs(year.total_mismatch):
                year.total_mismatch = mismatch

        for p in run.placements:
            placements.append(p)

            if not p.is_scored:
                year.unscored.append(p.account)
                continue

            year.accounts += 1
            year.dollars += p.amount
            if p.is_correct:
                year.accounts_correct += 1
                year.dollars_correct += p.amount

            verdict = by_account.setdefault(
                _norm(p.account),
                AccountVerdict(account=p.account, expected=p.expected),
            )
            verdict.runs += 1
            verdict.families[p.family or "unmapped"] += 1
            verdict.lines[p.line_number or "(none)"] += 1
            verdict.dollars += p.amount
            if p.is_correct:
                verdict.correct += 1
                verdict.dollars_correct += p.amount
                verdict.years_right.append(p.year)
            else:
                verdict.years_wrong.append(p.year)

    for year, score_row in by_year.items():
        score_row.runs = len(seen_runs[year])

    return Report(
        years=sorted(by_year.values(), key=lambda y: y.year),
        accounts=sorted(
            by_account.values(),
            key=lambda a: (a.verdict == "correct", -a.dollars),
        ),
        placements=placements,
    )
