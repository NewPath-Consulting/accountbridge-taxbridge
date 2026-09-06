"""Score Part VIII classification against the CRN answer key.

    # Everything in a directory of saved /api/reports responses
    python scripts/classification_harness.py --runs-dir /tmp

    # Named files
    python scripts/classification_harness.py /tmp/2019.json /tmp/2020.json

    # Write the tables out as well as printing them
    python scripts/classification_harness.py --runs-dir /tmp --out data/classification_harness

Each input is a saved response from POST /api/reports. The year comes from the
payload's own start_date, so several runs of the same year can sit in the same
directory and will be aggregated rather than overwriting each other -- which is
the point: one run per year cannot tell a wrong classification from an
inconsistent one. See `app/utils/classification_harness` for why.

**Keep one directory per code revision.** Nothing in a saved response records
which version of the classifier produced it, and mixing revisions quietly
corrupts the verdicts: scoring pre- and post-change 2024 runs together made
trade show fees read "inconsistent" when every run under the current code has
them right. Per-year dollars are averaged over that year's runs, so a year run
seven times still counts once -- but only runs of the same code belong in the
same average.

Outputs, under --out:
    placements.csv  one row per account per run: where it landed, where it belongs
    accounts.csv    one row per account: verdict across every run
    summary.json    per-year scores and the overall figure
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils.classification_harness import (  # noqa: E402
    DEFAULT_FIXTURE,
    load_answer_key,
    load_runs,
    score,
)

PLACEMENT_COLUMNS = [
    "year", "run_id", "account", "line_number", "family", "expected", "correct", "amount",
]
ACCOUNT_COLUMNS = [
    "account", "expected", "verdict", "runs", "correct", "families", "lines",
    "years_right", "years_wrong", "dollars", "dollars_correct",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", type=Path, help="Saved /api/reports response JSON files.")
    parser.add_argument("--runs-dir", type=Path, help="Directory of response JSON files to score.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE, help=f"Answer key (default {DEFAULT_FIXTURE}).")
    parser.add_argument("--out", type=Path, help="Directory to write placements.csv, accounts.csv and summary.json.")
    return parser.parse_args()


def _collect(args: argparse.Namespace) -> list[Path]:
    paths = list(args.paths)
    if args.runs_dir:
        paths.extend(sorted(args.runs_dir.glob("*.json")))
    return [p for p in paths if p.is_file()]


def _print_report(report) -> None:
    print(f"\n{'year':<7}{'runs':>6}{'accounts':>11}{'correct $':>14}{'total $':>14}{'pct':>8}")
    print("-" * 60)
    for y in report.years:
        flag = " *" if y.year in report.contaminated_years else ""
        print(
            f"{y.year:<7}{y.runs:>6}{f'{y.accounts_correct}/{y.accounts}':>11}"
            f"{y.mean_dollars_correct:>14,.0f}{y.mean_dollars:>14,.0f}{y.pct:>7.1f}%{flag}"
        )
    print("-" * 60)
    print(f"{'all':<7}{'':>6}{'':>11}{'':>14}{'':>14}{report.overall_pct():>7.1f}%")
    print(f"{'clean':<7}{'':>6}{'':>11}{'':>14}{'':>14}{report.overall_pct(clean_only=True):>7.1f}%")
    print("\ndollars are the mean per run, so a year runs N times counts once, not N times.")
    print("\n* rules in the Part VIII prompt were written from this year's filed return.")

    print(f"\n{'account':<28}{'expected':<18}{'verdict':<14}{'runs':>6}  lines seen")
    print("-" * 92)
    for a in report.accounts:
        lines = ", ".join(f"{k}x{v}" if v > 1 else k for k, v in sorted(a.lines.items()))
        print(f"{a.account[:27]:<28}{a.expected:<18}{a.verdict:<14}{a.correct}/{a.runs:<4}  {lines}")

    inconsistent = [a for a in report.accounts if a.verdict == "inconsistent"]
    wrong = [a for a in report.accounts if a.verdict == "wrong"]
    if wrong:
        print(f"\nwrong every run (wants a rule):")
        for a in wrong:
            print(f"  {a.account} -> {', '.join(a.families)}, should be {a.expected}")
    if inconsistent:
        print("\ninconsistent between runs (wants a constraint, not a rule):")
        for a in inconsistent:
            right = sorted(set(a.years_right)) or "-"
            wrong = sorted(set(a.years_wrong)) or "-"
            print(f"  {a.account}: right in {right}, wrong in {wrong}")

    mismatched = [y for y in report.years if y.total_mismatch]
    if mismatched:
        print(f"\ntotal revenue disagrees with the filed return:")
        for y in mismatched:
            print(f"  {y.year}: {y.total_mismatch:+,.2f}")

    unscored = {a for y in report.years for a in y.unscored}
    if unscored:
        print(f"\nnot in the answer key, unscored: {', '.join(sorted(unscored))}")


def _write(out: Path, report) -> None:
    out.mkdir(parents=True, exist_ok=True)

    with (out / "placements.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(PLACEMENT_COLUMNS)
        for p in report.placements:
            writer.writerow([
                p.year, p.run_id, p.account, p.line_number, p.family or "",
                p.expected or "", int(p.is_correct) if p.is_scored else "", f"{p.amount:.2f}",
            ])

    with (out / "accounts.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(ACCOUNT_COLUMNS)
        for a in report.accounts:
            d = a.as_dict()
            writer.writerow([
                d["account"], d["expected"], d["verdict"], d["runs"], d["correct"],
                "; ".join(f"{k}={v}" for k, v in d["families"].items()),
                "; ".join(f"{k}={v}" for k, v in d["lines"].items()),
                " ".join(str(y) for y in d["years_right"]),
                " ".join(str(y) for y in d["years_wrong"]),
                d["dollars"], d["dollars_correct"],
            ])

    (out / "summary.json").write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    print(f"\nwrote {out}/placements.csv, accounts.csv, summary.json")


def main() -> int:
    args = _parse_args()
    paths = _collect(args)
    if not paths:
        print("No input files. Pass paths or --runs-dir.", file=sys.stderr)
        return 2

    key = load_answer_key(args.fixture)
    runs = load_runs(paths, key)
    if not runs:
        print(f"None of the {len(paths)} file(s) carried a Part VIII.", file=sys.stderr)
        return 2

    report = score(runs, key)
    print(f"scored {len(runs)} run(s) across {len(report.years)} year(s)")
    _print_report(report)
    if args.out:
        _write(args.out, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
