"""Measure form-variant routing against forms actually filed, using ProPublica.

    # Named organizations
    python scripts/propublica_routing_harness.py --eins 01-0165097 14-2007220

    # Stratified sample: N organizations per size band, found through keyword searches
    python scripts/propublica_routing_harness.py --sample-per-band 25 --c-code 3

    # Dataset only, no router (or the plain form-test reference router)
    python scripts/propublica_routing_harness.py --eins 01-0165097 --router none
    python scripts/propublica_routing_harness.py --eins 01-0165097 --router reference

Outputs, under --out (default data/propublica_harness):
    dataset.csv   one row per filed 990 / 990-EZ with the routing inputs and the form filed
    results.csv   dataset plus prediction, outcome, attribution, near-boundary flags
    summary.json  counts and accuracy

Every API response is cached under --cache-dir, so re-runs are free.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils import propublica_harness as h  # noqa: E402
from app.utils.propublica_client import ProPublicaClient  # noqa: E402

DEFAULT_QUERIES = ("association", "foundation", "society", "club", "council", "center", "alliance", "league", "community", "friends")

DATASET_COLUMNS = [
    "ein", "name", "tax_prd", "tax_year", "form_filed", "total_revenue", "gross_receipts", "gross_receipts_addbacks",
    "total_assets_end", "age_years", "ruling_date", "subsection_code", "filing_requirement_code", "history", "history_complete",
]
RESULT_COLUMNS = DATASET_COLUMNS + ["predicted", "review", "reason", "outcome", "attribution", "near_boundary"]


def record_row(record: h.FilingRecord) -> dict:
    row = asdict(record)
    row["gross_receipts_addbacks"] = record.gross_receipts_addbacks
    row["history"] = "|".join(f"{v:.0f}" for v in record.history)
    row["age_years"] = None if record.age_years is None else round(record.age_years, 2)
    return {key: row[key] for key in DATASET_COLUMNS}


def result_row(result: h.EvaluationResult) -> dict:
    row = record_row(result.record)
    row.update(
        predicted=result.prediction.variant,
        review=result.prediction.review,
        reason=result.prediction.reason,
        outcome=result.outcome,
        attribution=result.attribution,
        near_boundary="|".join(result.near_boundary),
    )
    return row


def write_csv(path: Path, rows: Iterable[dict], columns: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load_router(name: str) -> Optional[Callable[[h.FilingRecord], h.Prediction]]:
    if name == "none":
        return None
    if name == "reference":
        return h.reference_router
    from app.utils.form_routing import route_form_variant  # the project router

    return h.make_router_adapter(route_form_variant)


def sample_eins(client: ProPublicaClient, per_band: int, queries: Iterable[str], state: Optional[str], c_code: Optional[int], max_pages: int) -> List[int]:
    """Walk search results until every size band has ``per_band`` organizations with extracted filings.

    Bands are keyed on the Business Master File income amount, which the IRS
    computes from the latest return as total revenue plus the cost and expense
    items that gross receipts adds back, so it approximates gross receipts.
    """
    filler = h.BandFiller(target=per_band)
    chosen: List[int] = []
    seen = set()
    for query in queries:
        for org in client.iter_search(q=query, state=state, c_code=c_code, max_pages=max_pages):
            ein = org.get("ein")
            if ein is None or ein in seen:
                continue
            seen.add(ein)
            amount = org.get("income_amount")
            if amount is None:
                amount = (client.organization(ein).get("organization") or {}).get("income_amount")
            if not filler.has_room(amount):
                continue
            report = h.build_records(client.organization(ein))
            if not report.records:
                continue
            filler.accept(amount)
            chosen.append(int(ein))
            print(f"  sampled {ein} ({org.get('name', '')[:40]}) band={h.size_band(amount)} filings={len(report.records)}", file=sys.stderr)
            if filler.is_full():
                return chosen
    print(f"  bands not all full after search: {filler.counts}", file=sys.stderr)
    return chosen


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eins", nargs="*", default=[], help="EINs to evaluate (any format)")
    parser.add_argument("--eins-file", type=Path, help="text file with one EIN per line")
    parser.add_argument("--sample-per-band", type=int, default=0, help="organizations per size band to find through search")
    parser.add_argument("--queries", nargs="*", default=list(DEFAULT_QUERIES), help="search keywords used for sampling")
    parser.add_argument("--state", help="two-letter state filter for sampling")
    parser.add_argument("--c-code", type=int, help="501(c) subsection filter for sampling, e.g. 3")
    parser.add_argument("--max-pages", type=int, default=20, help="search pages per query (25 organizations each)")
    parser.add_argument("--router", choices=["project", "reference", "none"], default="project")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "propublica_cache")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between live API requests")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "propublica_harness")
    parser.add_argument("--show", type=int, default=25, help="disagreements to print")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    client = ProPublicaClient(cache_dir=args.cache_dir, delay_seconds=args.delay)
    args.out.mkdir(parents=True, exist_ok=True)

    eins: List[str] = list(args.eins)
    if args.eins_file:
        eins += [line.strip() for line in args.eins_file.read_text().splitlines() if line.strip()]
    if args.sample_per_band:
        print(f"sampling {args.sample_per_band} organizations per band", file=sys.stderr)
        eins += [str(e) for e in sample_eins(client, args.sample_per_band, args.queries, args.state, args.c_code, args.max_pages)]
    if not eins:
        print("no organizations: pass --eins, --eins-file, or --sample-per-band", file=sys.stderr)
        return 2

    records: List[h.FilingRecord] = []
    skipped_pf = skipped_missing = 0
    for ein in dict.fromkeys(eins):
        report = h.build_records(client.organization(ein))
        records.extend(report.records)
        skipped_pf += report.skipped_pf
        skipped_missing += report.skipped_missing_data
    write_csv(args.out / "dataset.csv", (record_row(r) for r in records), DATASET_COLUMNS)
    print(f"dataset: {len(records)} filings from {len(set(r.ein for r in records))} organizations "
          f"(skipped {skipped_pf} 990-PF, {skipped_missing} without data); "
          f"{client.live_requests} live requests, {client.cache_hits} cache hits", file=sys.stderr)

    router = load_router(args.router)
    if router is None:
        return 0
    unbound = getattr(router, "unbound_parameters", ())
    if unbound:
        print(f"WARNING: router parameters not supplied by the harness, defaults used: {list(unbound)}; "
              f"router signature {getattr(router, 'signature', '')}. Add aliases in app/utils/propublica_harness.py "
              f"or every record may be held for review.", file=sys.stderr)
    print(f"router bound parameters: {list(getattr(router, 'bound_parameters', ()))}; "
          f"configuration left at router defaults: {list(getattr(router, 'configuration_parameters', ()))}", file=sys.stderr)

    results = h.evaluate_records(records, router)
    write_csv(args.out / "results.csv", (result_row(r) for r in results), RESULT_COLUMNS)
    summary = h.summarize(results)
    summary["router"] = args.router
    summary["router_bound_parameters"] = list(getattr(router, "bound_parameters", ()))
    summary["router_unbound_parameters"] = list(unbound)
    summary["router_configuration_parameters"] = list(getattr(router, "configuration_parameters", ()))
    summary["skipped_990pf"] = skipped_pf
    summary["skipped_missing_data"] = skipped_missing
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

    disagreements = [r for r in results if r.outcome in (h.UNDER_FILED, h.REVIEW, h.NO_PREDICTION)]
    if disagreements:
        print(f"\n{len(disagreements)} filings to examine (showing up to {args.show}):")
        for r in disagreements[: args.show]:
            rec = r.record
            print(f"  {rec.ein:>9} {rec.tax_prd} filed={rec.form_filed:<6} predicted={r.prediction.variant or '-':<6} "
                  f"{r.outcome:<13} {r.attribution or '':<34} gross_receipts={rec.gross_receipts:>12,.0f} "
                  f"assets={rec.total_assets_end if rec.total_assets_end is not None else float('nan'):>12,.0f} "
                  f"age={rec.age_years if rec.age_years is not None else float('nan'):>5.1f} history={rec.history}"
                  f"{'  ' + r.prediction.reason if r.prediction.reason else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
