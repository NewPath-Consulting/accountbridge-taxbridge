"""Run /api/reports across a grid of years and repeats, for the classification harness.

    # three runs of every year the fixture covers, into their own directory
    python scripts/run_classification_grid.py --repeat 3 --out data/classification_runs/step-10

    # one year, five times
    python scripts/run_classification_grid.py --years 2021 --repeat 5 --out /tmp/grid

    # then
    python scripts/classification_harness.py --runs-dir data/classification_runs/step-10

Responses are written as `<year>-<n>.json`, which is what the harness reads.

**Runs are serial and cannot be parallelised.** QuickBooks refresh tokens rotate
on every use, so two concurrent runs race for the same token and the loser gets
a 401 that looks like a credentials problem and is not. The grid therefore
takes roughly ninety seconds per run: eighteen runs is about half an hour.

**Give each code revision its own --out directory.** Nothing in a saved response
records which classifier produced it, and scoring runs from different revisions
together silently corrupts the harness verdicts.

**Set QUICKBOOKS_OUTPUT_DIR on the server before starting it**, or every run
rewrites `data/quickbooks/*.json`, which two tests read as fixtures. That is the
server's environment, not this script's -- exporting it here does nothing.

Credentials come from .env by default (QUICKBOOKS_REALM_ID,
WILDAPRICOT_ACCOUNT_ID); --realm and --account override them.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_FIXTURE = ROOT / "data" / "crn_synthetic.json"
DEFAULT_BASE_URL = "http://localhost:8000"
# A run is three sequential model calls plus a reconciliation pass; ~90s is
# typical and the tail is long, so this is deliberately generous.
DEFAULT_TIMEOUT = 600.0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--years", nargs="*", type=int, help="Years to run. Default: every year in the fixture.")
    p.add_argument("--repeat", type=int, default=3, help="Runs per year (default 3).")
    p.add_argument("--out", type=Path, required=True, help="Directory to write <year>-<n>.json into.")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Backend (default {DEFAULT_BASE_URL}).")
    p.add_argument("--realm", help="QuickBooks realm id. Default: QUICKBOOKS_REALM_ID from .env.")
    p.add_argument("--account", help="WildApricot account id. Default: WILDAPRICOT_ACCOUNT_ID from .env.")
    p.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE, help="Fixture supplying the year list.")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"Per-run timeout (default {DEFAULT_TIMEOUT:.0f}s).")
    p.add_argument("--skip-existing", action="store_true", help="Leave responses already on disk alone.")
    return p.parse_args()


def _env(name: str) -> str | None:
    """Read one key out of .env without importing the app's settings."""
    path = ROOT / ".env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def _fixture_years(fixture: Path) -> list[int]:
    data = json.loads(fixture.read_text(encoding="utf-8"))
    return sorted(int(y["year"]) for y in data.get("years") or [] if y.get("year"))


def _run_once(client: httpx.Client, base_url: str, body: dict, dest: Path) -> tuple[bool, str]:
    started = time.time()
    try:
        response = client.post(f"{base_url.rstrip('/')}/api/reports", json=body)
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"

    elapsed = time.time() - started
    if response.status_code != 200:
        detail = response.text[:200].replace("\n", " ")
        hint = ""
        if response.status_code == 401:
            hint = "  (a 401 usually means the refresh token was spent, not that credentials are wrong)"
        return False, f"HTTP {response.status_code} after {elapsed:.0f}s: {detail}{hint}"

    dest.write_text(json.dumps(response.json(), indent=1), encoding="utf-8")
    return True, f"{elapsed:.0f}s -> {dest.name}"


def main() -> int:
    args = _parse_args()

    realm = args.realm or _env("QUICKBOOKS_REALM_ID")
    account = args.account or _env("WILDAPRICOT_ACCOUNT_ID")
    if not realm:
        print("No QuickBooks realm id. Pass --realm or set QUICKBOOKS_REALM_ID in .env.", file=sys.stderr)
        return 2
    if not account:
        print("No WildApricot account id. Pass --account or set WILDAPRICOT_ACCOUNT_ID in .env.", file=sys.stderr)
        return 2

    years = args.years or _fixture_years(args.fixture)
    if not years:
        print(f"No years to run. {args.fixture} lists none and --years was not given.", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    total = len(years) * args.repeat
    print(
        f"{total} run(s): {len(years)} year(s) x {args.repeat}, serially, "
        f"~{total * 90 / 60:.0f} min into {args.out}"
    )

    done = failed = skipped = 0
    with httpx.Client(timeout=args.timeout) as client:
        for year in years:
            for n in range(1, args.repeat + 1):
                dest = args.out / f"{year}-{n}.json"
                label = f"[{done + failed + skipped + 1}/{total}] {year} run {n}"

                if args.skip_existing and dest.exists():
                    print(f"{label}: exists, skipped")
                    skipped += 1
                    continue

                print(f"{label}: ...", end="", flush=True)
                ok, message = _run_once(
                    client,
                    args.base_url,
                    {
                        "wildapricot_account_id": account,
                        "quickbooks_realm_id": realm,
                        "start_date": f"{year}-01-01",
                        "end_date": f"{year}-12-31",
                    },
                    dest,
                )
                print(f"\r{label}: {message}")
                if ok:
                    done += 1
                else:
                    failed += 1

    print(f"\n{done} written, {failed} failed, {skipped} skipped -> {args.out}")
    if done:
        print(f"score it:\n  python scripts/classification_harness.py --runs-dir {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
