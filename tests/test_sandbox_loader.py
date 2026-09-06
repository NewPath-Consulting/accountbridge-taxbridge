"""Tests for the QuickBooks sandbox loader's balance sheet arithmetic.

The loader posts journal entries; QuickBooks derives the reports. So the only
thing testable without a sandbox is whether the entries it would post add up to
the position the filed returns report — which is exactly what was wrong. The
sandbox balance sheet was cumulative net income from a zero start, short by the
organization's opening equity in every year and negative in two of them, and
nothing caught it until the totals were scored against the filed figures.

Everything here derives from `data/crn_synthetic.json`, so refreshing the
fixture cannot leave a stale expectation behind.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "crn_synthetic.json"


def _loader_module():
    """The loader is a script, not a package module."""
    spec = importlib.util.spec_from_file_location(
        "load_quickbooks_sandbox", ROOT / "scripts" / "load_quickbooks_sandbox.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def loader():
    return _loader_module()


@pytest.fixture(scope="module")
def definition():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _simulate(loader, definition):
    """Year-end asset balances the loader's entries would produce."""
    balances = dict(loader.opening_balances(definition))
    closing = {}
    for year in definition["years"]:
        primary = next(iter(year["assets"]))
        balances[primary] = round(
            balances.get(primary, 0.0) + loader.net_income(year), 2
        )
        for name, target in year["assets"].items():
            balances[name] = round(target, 2)
        closing[year["year"]] = dict(balances)
    return closing


def test_opening_equity_is_what_the_first_year_cannot_explain(loader, definition):
    first = definition["years"][0]
    opening = loader.opening_balances(definition)

    # Whatever the organization held before the first year is its closing
    # position less what that year earned.
    assert round(sum(opening.values()), 2) == pytest.approx(
        first["published"]["assets"] - loader.net_income(first)
    )
    assert all(amount > 0 for amount in opening.values()), opening


def test_every_year_closes_on_the_filed_total_assets(loader, definition):
    closing = _simulate(loader, definition)
    for year in definition["years"]:
        total = round(sum(closing[year["year"]].values()), 2)
        assert total == pytest.approx(year["published"]["assets"]), year["year"]


def test_no_year_closes_negative(loader, definition):
    """Two years did, before the opening balance existed."""
    closing = _simulate(loader, definition)
    for number, balances in closing.items():
        assert min(balances.values()) >= 0, f"{number}: {balances}"


def test_every_asset_account_carries_a_balance(loader, definition):
    """The loader used to post only to the first asset account."""
    closing = _simulate(loader, definition)
    for year in definition["years"]:
        for name, expected in year["assets"].items():
            assert closing[year["year"]][name] == pytest.approx(expected)


def test_the_adjustments_balance(loader, definition):
    """An unbalanced journal entry is rejected by QuickBooks outright.

    The year's activity all lands in the primary bank, so moving each account
    onto its filed closing figure has to net to zero or the entry will not
    post.
    """
    balances = dict(loader.opening_balances(definition))
    for year in definition["years"]:
        primary = next(iter(year["assets"]))
        balances[primary] = round(
            balances.get(primary, 0.0) + loader.net_income(year), 2
        )
        moves = [
            round(target - balances.get(name, 0.0), 2)
            for name, target in year["assets"].items()
        ]
        assert round(sum(moves), 2) == 0.0, f"{year['year']}: {moves}"
        for name, target in year["assets"].items():
            balances[name] = round(target, 2)
