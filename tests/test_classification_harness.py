"""Tests for the Part VIII classification harness.

Every expectation is derived from `data/crn_synthetic.json` itself, so
refreshing the fixture from its source cannot break these. Line numbers come
from the Part VIII inventory rather than being written out, for the same
reason.
"""

import json
from pathlib import Path

import pytest

from app.utils.classification_harness import (
    load_answer_key,
    load_runs,
    score,
)
from app.utils.form_990_enforce import part_viii_family_for_line
from app.utils.form_990_lines import PART_VIII_LINES, PART_VIII_ASSIGNABLE_KINDS

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "crn_synthetic.json"


@pytest.fixture(scope="module")
def key():
    return load_answer_key(FIXTURE)


@pytest.fixture(scope="module")
def fixture_years():
    return {y["year"]: y for y in json.loads(FIXTURE.read_text())["years"]}


def _line_for(family: str) -> str:
    """Any assignable Part VIII line belonging to `family`."""
    for line, kind, _ in PART_VIII_LINES:
        if kind in PART_VIII_ASSIGNABLE_KINDS and part_viii_family_for_line(line) == family:
            return line
    raise AssertionError(f"no assignable line for {family}")


def _write_run(tmp_path: Path, year: int, revenue: dict, families, name: str) -> Path:
    """A saved /api/reports response placing each account on `families`."""
    items = [
        {
            "lineNumber": _line_for(families(account)),
            "label": account,
            "totalRevenue": amount,
        }
        for account, amount in revenue.items()
    ]
    payload = {
        "request_id": name,
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "reports": {
            "tax_return": {
                "content": {
                    "partVIII_revenue": items,
                    "partVIII_totalRevenue": round(sum(revenue.values()), 2),
                }
            }
        },
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- the answer key -------------------------------------------------------

def test_key_covers_every_account_in_every_year(key, fixture_years):
    """If an account has no expected family, that year silently under-scores."""
    for year in fixture_years.values():
        for account in year["revenue"]:
            assert key.family_for(account) is not None, f"{account} missing from the key"


def test_published_totals_match_the_account_amounts(key, fixture_years):
    """Guards the fixture: the key is only meaningful if its years add up."""
    for number, year in fixture_years.items():
        filed = key.published[number]
        for section, figure in (("revenue", filed.revenue), ("expenses", filed.expenses),
                                ("assets", filed.assets)):
            assert round(sum(year[section].values()), 2) == pytest.approx(figure), (
                f"{number} {section}"
            )


def test_headline_totals_are_compared_against_the_filed_return(tmp_path, key, fixture_years):
    """Part VIII, IX and X totals are scored, not just the classification."""
    year = max(fixture_years)
    path = _write_run(tmp_path, year, fixture_years[year]["revenue"], key.family_for, "totals")
    report = score(load_runs([path], key), key)

    # The stub payload carries a Part VIII total only, so revenue is compared
    # and the other two are absent rather than counted as zero.
    totals = report.years[0].totals
    assert "revenue" in totals
    stated, filed = totals["revenue"]
    assert stated == pytest.approx(filed)
    assert "expenses" not in totals and "assets" not in totals


# --- scoring --------------------------------------------------------------

def test_a_perfect_run_scores_100(tmp_path, key, fixture_years):
    year = max(fixture_years)
    path = _write_run(tmp_path, year, fixture_years[year]["revenue"], key.family_for, "perfect")
    report = score(load_runs([path], key), key)

    assert report.years[0].pct == 100.0
    assert {a.verdict for a in report.accounts} == {"correct"}


def test_an_account_wrong_in_every_run_reads_wrong_not_inconsistent(tmp_path, key, fixture_years):
    year = max(fixture_years)
    revenue = fixture_years[year]["revenue"]
    target = next(a for a in revenue if key.family_for(a) == "contributions")

    def misplace(account: str) -> str:
        return "other" if account == target else key.family_for(account)

    paths = [_write_run(tmp_path, year, revenue, misplace, f"wrong{i}") for i in range(2)]
    report = score(load_runs(paths, key), key)

    verdicts = {a.account: a.verdict for a in report.accounts}
    assert verdicts[target] == "wrong"
    assert set(verdicts.values()) == {"wrong", "correct"}


def test_an_account_that_flips_between_runs_reads_inconsistent(tmp_path, key, fixture_years):
    year = max(fixture_years)
    revenue = fixture_years[year]["revenue"]
    target = next(a for a in revenue if key.family_for(a) == "contributions")

    good = _write_run(tmp_path, year, revenue, key.family_for, "good")
    bad = _write_run(
        tmp_path, year, revenue,
        lambda a: "other" if a == target else key.family_for(a), "bad",
    )
    report = score(load_runs([good, bad], key), key)

    verdict = next(a for a in report.accounts if a.account == target)
    assert verdict.verdict == "inconsistent"
    assert verdict.correct == 1 and verdict.runs == 2


def test_only_the_family_is_scored_not_the_sub_letter(tmp_path, key, fixture_years):
    """Two lines in the same family are the same answer."""
    year = max(fixture_years)
    revenue = fixture_years[year]["revenue"]
    path = _write_run(tmp_path, year, revenue, key.family_for, "families")

    run = load_runs([path], key)[0]
    contributions = [p for p in run.placements if p.expected == "contributions"]
    assert contributions, "fixture year has no contributions account"
    for placement in contributions:
        assert placement.is_correct
        assert placement.line_number != "1"  # a real box, not a bare root


# --- weighting ------------------------------------------------------------

def test_repeating_a_year_does_not_increase_its_weight(tmp_path, key, fixture_years):
    """A year run twice must not count twice against a year run once."""
    a, b = sorted(fixture_years)[:2]
    once = _write_run(tmp_path, a, fixture_years[a]["revenue"], key.family_for, "a1")
    twice = [
        _write_run(tmp_path, b, fixture_years[b]["revenue"], key.family_for, f"b{i}")
        for i in range(2)
    ]

    one_each = score(load_runs([once, twice[0]], key), key)
    lopsided = score(load_runs([once, *twice], key), key)

    assert lopsided.overall_pct() == one_each.overall_pct()
    assert next(y for y in lopsided.years if y.year == b).runs == 2


# --- inputs the harness has actually been handed --------------------------

def test_non_report_json_is_skipped_not_fatal(tmp_path, key):
    """`/tmp` holds stray JSON; a directory scan must not die on it."""
    (tmp_path / "a_list.json").write_text("[1, 2, 3]", encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "no_period.json").write_text('{"reports": {}}', encoding="utf-8")

    assert load_runs(sorted(tmp_path.glob("*.json")), key) == []
