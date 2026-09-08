#!/usr/bin/env python
"""Wire the filing tab into ui/app.py and clean up the presentation.

  1. the page title and main heading, which still said "Reports & Benchmark"
  2. an import of the new tab module
  3. a fifth tab in the tab strip
  4. the call that renders it
  5. the emoji removed from headings, tabs and status messages

The emoji are removed because the application produces tax returns. A page
that files with the IRS should not look like a chat client, and the icons
carried no information -- every one of them sat beside a heading that
already said what the section was.

Run from the project root:

    python scripts/patch_ui_filing_tab.py

It reports what it changed and refuses to apply an edit twice, so running it
again is safe.
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path("ui/app.py")

EDITS = [
    (
        "page title",
        'page_title="AccountBridge · Reports & Benchmark",',
        'page_title="TaxBridge · Form 990 Preparation",',
    ),
    (
        "page icon",
        'page_icon="\U0001F4CA",',
        'page_icon="\u25EB",',
    ),
    (
        "main heading",
        'st.markdown("# \U0001F4CA AccountBridge · Reports → Benchmark")',
        'st.markdown("# TaxBridge")\n'
        'st.caption(\n'
        '    "Form 990 preparation from QuickBooks and WildApricot \u00b7 "\n'
        '    "the model classifies, the code calculates"\n'
        ')',
    ),
    (
        "subtitle",
        'st.caption(\n'
        '    "Form 990 preparation from QuickBooks and WildApricot \u00b7 "\n'
        '    "the model classifies, the code calculates"\n'
        ')\n'
        'st.markdown(\n'
        '    \'<p class="ab-subtitle">Generate financial reports, then run benchmark \'\n'
        '    "against reference documents.</p>",\n'
        '    unsafe_allow_html=True,\n'
        ')',
        'st.markdown(\n'
        '    \'<p class="ab-subtitle">Prepare Form 990 returns from QuickBooks and \'\n'
        '    "WildApricot. The model classifies; the code calculates.</p>",\n'
        '    unsafe_allow_html=True,\n'
        ')',
    ),
    (
        "sidebar: configuration",
        'st.markdown("## \u2699\ufe0f Configuration")',
        'st.markdown("## Configuration")',
    ),
    (
        "sidebar: data sources",
        'st.markdown("### \U0001F3E2 Data Sources")',
        'st.markdown("### Data sources")',
    ),
    (
        "sidebar: date range",
        'st.markdown("### \U0001F4C5 Date Range")',
        'st.markdown("### Date range")',
    ),
    (
        "sidebar: benchmark options",
        'st.markdown("### \U0001F3AF Benchmark Options")',
        'st.markdown("### Benchmark options")',
    ),
    (
        "quickbooks credentials heading",
        'st.markdown("### \U0001F510 QuickBooks Credentials")',
        'st.markdown("### QuickBooks credentials")',
    ),
    (
        "report instructions heading",
        'st.markdown("#### \u270D\ufe0f Report Instructions")',
        'st.markdown("#### Report instructions")',
    ),
    (
        "stored reports message",
        'f"\u2705 Stored **cash_flow**, **tax_return**, and **balance_sheet** for benchmark ({elapsed:.1f}s)."',
        'f"Stored cash_flow, tax_return and balance_sheet for benchmarking "\n'
        '            f"in {elapsed:.1f}s."',
    ),
    (
        "generated reports heading",
        'st.markdown("## \U0001F4C4 Generated Reports")',
        'st.markdown("## Generated reports")',
    ),
    (
        "benchmark results heading",
        'st.markdown("## \U0001F3AF Benchmark Results")',
        'st.markdown("## Benchmark results")',
    ),
    (
        "raw responses heading",
        'st.markdown("## \U0001F529 Raw API Responses")',
        'st.markdown("## Raw API responses")',
    ),
    (
        "sidebar: pipeline status",
        'st.markdown("### \U0001F504 Pipeline Status")',
        'st.markdown("### Pipeline status")',
    ),
    (
        "reset button",
        'st.button("\U0001F501 Reset", use_container_width=True)',
        'st.button("Reset", use_container_width=True)',
    ),
    (
        "select documents heading",
        'st.markdown("#### \U0001F4D1 Select Reference Documents")',
        'st.markdown("#### Reference documents")',
    ),
    (
        "refresh documents button",
        'st.button("\U0001F504 Refresh", key="refresh_docs"',
        'st.button("Refresh", key="refresh_docs"',
    ),
    (
        "benchmark prerequisite caption",
        'st.caption("\u26A0 Run Reports first, then select reference documents.")',
        'st.caption("Run the reports first, then select reference documents.")',
    ),
    (
        "tab strip",
        'tab_pipeline, tab_reports, tab_benchmark, tab_raw = st.tabs(\n'
        '    ["\U0001F680 Pipeline", "\U0001F4C4 Reports", "\U0001F3AF Benchmark", '
        '"\U0001F529 Raw JSON"]\n'
        ')',
        'tab_pipeline, tab_reports, tab_filing, tab_benchmark, tab_raw = st.tabs(\n'
        '    ["Pipeline", "Reports", "File a return", "Benchmark", "Raw JSON"]\n'
        ')\n'
        '\n'
        '# ──────────────────────────────────────────────\n'
        '# TAB · File a Return\n'
        '# ──────────────────────────────────────────────\n'
        'with tab_filing:\n'
        '    _reports_response = st.session_state.get("reports_response") or {}\n'
        '    _tax_return = (\n'
        '        (_reports_response.get("reports") or {}).get("tax_return") or {}\n'
        '    )\n'
        '    filing_tab.render(\n'
        '        base_url=resolve_api_base_url(),\n'
        '        headers=build_api_headers(),\n'
        '        quickbooks_realm_id=qb_id,\n'
        '        start_date=str(start_date),\n'
        '        end_date=str(end_date),\n'
        '        report_content=_tax_return.get("content"),\n'
        '        format_request_error=format_api_request_error,\n'
        '    )',
    ),
]

IMPORT_ANCHOR = "import streamlit as st"
# Streamlit puts the script's own directory on sys.path, so a sibling module
# is imported by plain name. `ui` is not a package -- it has no __init__.py --
# so `from ui import filing_tab` would fail at runtime.
IMPORT_LINE = "import filing_tab"


def main() -> int:
    if not TARGET.exists():
        print(f"Cannot find {TARGET}. Run this from the project root.")
        return 1

    source = TARGET.read_text()
    original = source
    applied: list[str] = []
    skipped: list[str] = []

    for label, old, new in EDITS:
        if new in source:
            skipped.append(f"{label} (already applied)")
        elif old in source:
            source = source.replace(old, new, 1)
            applied.append(label)
        else:
            skipped.append(f"{label} (anchor not found)")

    if IMPORT_LINE in source:
        skipped.append("import (already applied)")
    elif IMPORT_ANCHOR in source:
        source = source.replace(
            IMPORT_ANCHOR, f"{IMPORT_ANCHOR}\n\n{IMPORT_LINE}", 1
        )
        applied.append("import")
    else:
        skipped.append("import (anchor not found)")

    if source == original:
        print("Nothing to change.")
    else:
        backup = TARGET.with_suffix(".py.bak")
        backup.write_text(original)
        TARGET.write_text(source)
        print(f"Backed up to {backup}")

    for item in applied:
        print(f"  applied  {item}")
    for item in skipped:
        print(f"  skipped  {item}")

    if any("anchor not found" in s for s in skipped):
        print(
            "\nOne or more anchors did not match. The file may have been "
            "edited since. Apply those by hand."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
