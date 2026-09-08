#!/usr/bin/env python
"""Put the AccountBridge look and feel back, keeping the File a return tab.

The earlier patch did two unrelated things at once: it added a tab, and it
restyled the application \u2014 renamed it, stripped the emoji, and rewrote every
heading. The second was not asked for and made a feature addition look like a
rewrite of someone else's product.

This reverses the styling and leaves the tab. Specifically it restores:

    the page title and icon
    the main heading and its subtitle
    the emoji and capitalisation on every sidebar and section heading
    the emoji on the tab labels

and leaves alone:

    the File a return tab and everything behind it
    the import of filing_tab

Run from the project root:

    python scripts/revert_ui_cosmetics.py

It reports what it changed and refuses to apply an edit twice, so running it
again is safe.
"""

from __future__ import annotations

from pathlib import Path

TARGET = Path("ui/app.py")

# (label, what the patch left behind, what it should say)
EDITS = [
    (
        "page title",
        'page_title="TaxBridge · Form 990 Preparation",',
        'page_title="AccountBridge · Reports & Benchmark",',
    ),
    (
        "page icon",
        'page_icon="\u25EB",',
        'page_icon="\U0001F4CA",',
    ),
    (
        "main heading and subtitle",
        'st.markdown("# TaxBridge")\n'
        'st.markdown(\n'
        '    \'<p class="ab-subtitle">Prepare Form 990 returns from QuickBooks and \'\n'
        '    "WildApricot. The model classifies; the code calculates.</p>",\n'
        '    unsafe_allow_html=True,\n'
        ')',
        'st.markdown("# \U0001F4CA AccountBridge · Reports → Benchmark")\n'
        'st.markdown(\n'
        '    \'<p class="ab-subtitle">Generate financial reports, then run benchmark \'\n'
        '    "against reference documents.</p>",\n'
        '    unsafe_allow_html=True,\n'
        ')',
    ),
    (
        "sidebar: configuration",
        'st.markdown("## Configuration")',
        'st.markdown("## \u2699\ufe0f Configuration")',
    ),
    (
        "sidebar: data sources",
        'st.markdown("### Data sources")',
        'st.markdown("### \U0001F3E2 Data Sources")',
    ),
    (
        "sidebar: date range",
        'st.markdown("### Date range")',
        'st.markdown("### \U0001F4C5 Date Range")',
    ),
    (
        "sidebar: benchmark options",
        'st.markdown("### Benchmark options")',
        'st.markdown("### \U0001F3AF Benchmark Options")',
    ),
    (
        "sidebar: pipeline status",
        'st.markdown("### Pipeline status")',
        'st.markdown("### \U0001F504 Pipeline Status")',
    ),
    (
        "reset button",
        'st.button("Reset", use_container_width=True)',
        'st.button("\U0001F501 Reset", use_container_width=True)',
    ),
    (
        "quickbooks credentials heading",
        'st.markdown("### QuickBooks credentials")',
        'st.markdown("### \U0001F510 QuickBooks Credentials")',
    ),
    (
        "report instructions heading",
        'st.markdown("#### Report instructions")',
        'st.markdown("#### \u270D\ufe0f Report Instructions")',
    ),
    (
        "stored reports message",
        'f"Stored cash_flow, tax_return and balance_sheet for benchmarking "\n'
        '            f"in {elapsed:.1f}s."',
        'f"\u2705 Stored **cash_flow**, **tax_return**, and **balance_sheet** for benchmark ({elapsed:.1f}s)."',
    ),
    (
        "select documents heading",
        'st.markdown("#### Reference documents")',
        'st.markdown("#### \U0001F4D1 Select Reference Documents")',
    ),
    (
        "refresh documents button",
        'st.button("Refresh", key="refresh_docs"',
        'st.button("\U0001F504 Refresh", key="refresh_docs"',
    ),
    (
        "benchmark prerequisite caption",
        'st.caption("Run the reports first, then select reference documents.")',
        'st.caption("\u26A0 Run Reports first, then select reference documents.")',
    ),
    (
        "generated reports heading",
        'st.markdown("## Generated reports")',
        'st.markdown("## \U0001F4C4 Generated Reports")',
    ),
    (
        "benchmark results heading",
        'st.markdown("## Benchmark results")',
        'st.markdown("## \U0001F3AF Benchmark Results")',
    ),
    (
        "raw responses heading",
        'st.markdown("## Raw API responses")',
        'st.markdown("## \U0001F529 Raw API Responses")',
    ),
    (
        # the tab strip keeps the new tab; only the labels change back
        "tab labels",
        '    ["Pipeline", "Reports", "File a return", "Benchmark", "Raw JSON"]',
        '    ["\U0001F680 Pipeline", "\U0001F4C4 Reports", "\U0001F4EE File a Return", '
        '"\U0001F3AF Benchmark", "\U0001F529 Raw JSON"]',
    ),
]


def main() -> int:
    if not TARGET.exists():
        print(f"Cannot find {TARGET}. Run this from the project root.")
        return 1

    source = TARGET.read_text()
    original = source
    applied: list[str] = []
    skipped: list[str] = []

    for label, patched, restored in EDITS:
        if restored in source:
            skipped.append(f"{label} (already restored)")
        elif patched in source:
            source = source.replace(patched, restored, 1)
            applied.append(label)
        else:
            skipped.append(f"{label} (not found \u2014 may have been edited by hand)")

    if source == original:
        print("Nothing to change.")
    else:
        backup = TARGET.with_suffix(".py.pre-revert")
        backup.write_text(original)
        TARGET.write_text(source)
        print(f"Backed up to {backup}")

    for item in applied:
        print(f"  restored  {item}")
    for item in skipped:
        print(f"  skipped   {item}")

    print(
        "\nThe File a return tab and its import are untouched.\n"
        "Restart Streamlit \u2014 Ctrl-C, then streamlit run ui/app.py \u2014 since it\n"
        "caches imported modules."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
