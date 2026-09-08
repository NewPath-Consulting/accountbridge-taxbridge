"""The same figure appears in several blocks; they must not disagree.

Part X computes net assets as assets less liabilities. `totals` and Part XI
restate that figure, and before this they restated the model's instead: on a
2024 run Part X reported 192,028 -- matching the filed return -- while
totals.net_assets said 217,675 and Part XI line 10 said 217,675 against a
line 4 of 159,828 and a line 3 of 32,200. Part XI exists to prove the balance
sheet ties to the income statement, and it was out by 25,647.

Expectations are derived from the fixture's own figures, so changing them
does not require editing assertions.
"""

from app.utils.form_990_propagate import propagate_enforced_totals

ASSETS_BOY = 159828.0
ASSETS_EOY = 192028.0
LIABILITIES = 0.0
REVENUE = 305506.0
EXPENSES = 273306.0


def _content(**overrides):
    content = {
        "partVIII_totalRevenue": REVENUE,
        "partIX_totals": {"totalExpenses": EXPENSES},
        "partX_balanceSheet": {
            "totalAssets": {"beginningOfYear": ASSETS_BOY, "endOfYear": ASSETS_EOY},
            "totalLiabilities": {"beginningOfYear": LIABILITIES, "endOfYear": LIABILITIES},
        },
        # the model's figures, deliberately wrong
        "totals": {
            "total_assets": None,
            "total_liabilities": None,
            "net_assets": 217675.0,
            "beginning_net_assets": 185475.0,
            "ending_net_assets": 217675.0,
            "change_in_net_assets": 32100.0,
        },
        "partXI_reconciliationOfNetAssets": {
            "line3_revenueLessExpenses": REVENUE - EXPENSES,
            "line4_netAssetsBeginningOfYear": ASSETS_BOY,
            "line5_netUnrealizedGainsLosses": 0.0,
            "line6_donatedServicesAndUseOfFacilities": 0.0,
            "line7_investmentExpenses": 0.0,
            "line8_priorPeriodAdjustments": 0.0,
            "line9_otherChanges": 0.0,
            "line10_netAssetsEndOfYear": 217675.0,
        },
    }
    content.update(overrides)
    return content


def test_totals_take_the_balance_sheet_from_part_x():
    content = _content()
    wrong = content["totals"]["net_assets"]
    propagate_enforced_totals(content, None)

    totals = content["totals"]
    assert totals["total_assets"] == ASSETS_EOY
    assert totals["total_liabilities"] == LIABILITIES
    assert totals["net_assets"] == ASSETS_EOY - LIABILITIES
    assert totals["net_assets"] != wrong
    assert totals["beginning_net_assets"] == ASSETS_BOY - LIABILITIES
    assert totals["ending_net_assets"] == totals["net_assets"]


def test_change_in_net_assets_is_the_difference_not_the_models_number():
    content = _content()
    propagate_enforced_totals(content, None)
    assert content["totals"]["change_in_net_assets"] == ASSETS_EOY - ASSETS_BOY


def test_part_xi_actually_reconciles():
    content = _content()
    propagate_enforced_totals(content, None)

    xi = content["partXI_reconciliationOfNetAssets"]
    addends = (
        xi["line4_netAssetsBeginningOfYear"],
        xi["line3_revenueLessExpenses"],
        xi["line5_netUnrealizedGainsLosses"],
        xi["line6_donatedServicesAndUseOfFacilities"],
        xi["line7_investmentExpenses"],
        xi["line8_priorPeriodAdjustments"],
        xi["line9_otherChanges"],
    )
    assert xi["line10_netAssetsEndOfYear"] == round(sum(addends), 2)
    # and it agrees with Part X, which is the point of the reconciliation
    assert xi["line10_netAssetsEndOfYear"] == content["totals"]["net_assets"]


def test_the_correction_is_recorded():
    content = _content()
    wrong = content["totals"]["net_assets"]
    _, notes = propagate_enforced_totals(content, None)
    joined = " ".join(notes)
    assert "TOTALS_NET_ASSETS_CORRECTED" in joined
    assert "PART_XI_LINE10_CORRECTED" in joined
    assert str(wrong) in joined


def test_a_disagreement_between_part_xi_and_part_x_is_reported():
    """If an addend is wrong the two routes diverge; say so, don't pick one."""
    content = _content()
    content["partXI_reconciliationOfNetAssets"]["line8_priorPeriodAdjustments"] = 5000.0
    _, notes = propagate_enforced_totals(content, None)
    assert any("PART_XI_PART_X_DISAGREE" in n for n in notes)


def test_without_part_x_nothing_is_invented():
    content = _content(partX_balanceSheet=None)
    before = dict(content["totals"])
    propagate_enforced_totals(content, None)
    for key in ("total_assets", "net_assets", "beginning_net_assets"):
        assert content["totals"][key] == before[key]
