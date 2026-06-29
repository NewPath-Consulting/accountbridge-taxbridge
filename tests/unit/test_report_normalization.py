"""Unit tests for report normalization and mandatory-field backfill."""

from app.utils.report_normalization import (
    build_organization_summary,
    ensure_balance_sheet_mandatory_fields,
    ensure_part_x_mandatory_fields,
    normalize_tax_return_content,
)


def test_normalize_tax_return_content_builds_benchmark_sections():
    content = {
        "partVIII_totalRevenue": 100000.0,
        "partIX_totals": {
            "totalExpenses": 80000.0,
            "totalProgramServices": 50000.0,
            "totalManagementAndGeneral": 25000.0,
            "totalFundraising": 5000.0,
        },
        "partX_balanceSheet": {
            "totalAssets": 200000.0,
            "totalLiabilities": 50000.0,
            "netAssets": {"totalNetAssets": 150000.0},
        },
        "partXI_reconciliationOfNetAssets": {
            "line4_netAssetsBeginningOfYear": 140000.0,
            "line9_otherChangesInNetAssets": 10000.0,
        },
        "reconciliation": {
            "total_revenue": 100000.0,
            "total_expenses": 80000.0,
            "beginning_net_assets": 140000.0,
            "change_in_net_assets": 10000.0,
            "ending_net_assets": 150000.0,
        },
    }

    result = normalize_tax_return_content(content)

    assert result["revenue"]["total_revenue"] == 100000.0
    assert result["expenses"]["total_expenses"] == 80000.0
    assert result["expenses"]["program_services"] == 50000.0
    assert result["balance_sheet"]["total_assets"] == 200000.0
    assert result["reconciliation"]["ending_net_assets"] == 150000.0
    assert result["totals"]["beginning_net_assets"] == 140000.0
    assert result["totals"]["change_in_net_assets"] == 10000.0


def test_build_organization_summary_maps_tax_year_and_gross_receipts():
    content = {
        "statement": {
            "taxYear": {"startDate": "2025-01-01", "endDate": "2025-12-31"},
        },
        "organizationInformation": {
            "legalName": "KCWG Inc",
            "ein": "43-1615506",
        },
        "partVIII_totalRevenue": 302868.0,
        "partI_summary": {"missionStatement": "Woodworking guild"},
    }

    summary = build_organization_summary(content, "2025-01-01", "2025-12-31")

    assert summary["organization_name"] == "KCWG Inc"
    assert summary["ein"] == "43-1615506"
    assert summary["tax_year"] == "2025"
    assert summary["gross_receipts"] == 302868.0
    assert summary["mission"] == "Woodworking guild"


def test_ensure_balance_sheet_mandatory_fields_adds_ppe_and_total_liabilities():
    content = {
        "assets": {
            "currentAssets": [],
            "nonCurrentAssets": [],
            "totalAssets": 5000.0,
        },
        "liabilities": {
            "currentLiabilities": [
                {"conceptId": "AccountsPayable", "amount": 0.0},
            ],
            "nonCurrentLiabilities": [],
        },
    }

    result = ensure_balance_sheet_mandatory_fields(content)

    ppe = result["assets"]["nonCurrentAssets"]
    assert any(item.get("conceptId") == "PropertyPlantAndEquipmentNet" for item in ppe)
    assert result["liabilities"]["totalLiabilities"] == 0.0


def test_ensure_part_x_mandatory_fields_adds_accounts_payable_line():
    part_x = {
        "assets": [],
        "liabilitiesAndNetAssets": [
            {
                "lineNumber": "19",
                "label": "Deferred revenue",
                "endOfYear": 0.0,
            }
        ],
    }

    result = ensure_part_x_mandatory_fields(part_x)

    labels = [item.get("label", "") for item in result["liabilitiesAndNetAssets"]]
    assert any("Accounts payable" in label for label in labels)
