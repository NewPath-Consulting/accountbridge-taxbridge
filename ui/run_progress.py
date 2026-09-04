"""A progress indicator for the reports run.

The reports endpoint is a single blocking request. The backend fetches from
two systems, makes six model calls in sequence, and returns when it is done,
so there is no progress to read: the client knows only that it is waiting.

What follows is therefore an estimate, not a measurement. The stages are the
real ones, in the real order, and the timings come from the server log across
several runs. The bar advances on elapsed time and jumps to complete when the
response arrives, so it can run ahead or behind the truth. It is honest about
what is happening and approximate about how far along it is, which is more
useful than a spinner and less misleading than a bar that claims to know.

Streamlit cannot draw from a worker thread, so the request runs in one and the
main thread polls it, redrawing as it goes.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

import streamlit as st

# (label, typical seconds for this stage)
#
# Measured from the server log across several runs.
#
# Reading the supporting records is roughly half the wait. The connector is
# rate limited and pages through the records a hundred at a time, so it is
# slow regardless of how much is there. The bar keeps advancing throughout,
# so a single long stage still shows movement.
#
# Runs have ranged from about 175 to 300 seconds. These figures are set near
# the fast end, because a bar that arrives early and waits reads better than
# one that is still at two thirds when the answer appears.
STAGES: list[tuple[str, float]] = [
    ("Connecting to QuickBooks", 1),
    ("Reading the profit and loss and balance sheets", 2),
    ("Reading the supporting records", 12),
    ("Preparing the data for classification", 1),
    ("Generating the cash flow statement", 8),
    ("Generating the balance sheet report", 10),
    ("Classifying revenue into IRS lines (Part VIII)", 5),
    ("Classifying expenses (Part IX)", 3),
    ("Building the balance sheet (Part X)", 3),
    ("Completing the remaining parts of the return", 30),
    ("Reconciling the return against the ledger", 14),
    ("Applying deterministic corrections", 1),
]

TOTAL = sum(seconds for _, seconds in STAGES)


def _stage_at(elapsed: float) -> tuple[int, str]:
    """Which stage the run is most likely in, and its label."""
    running = 0.0
    for index, (label, seconds) in enumerate(STAGES):
        running += seconds
        if elapsed < running:
            return index, label
    # Past the estimate. The last stage is the honest answer.
    return len(STAGES) - 1, STAGES[-1][0]


def run_with_progress(work: Callable[[], Any], *, label: str = "Generating reports") -> Any:
    """Run `work` in a thread, showing the stages while it goes.

    Returns whatever `work` returns. Anything it raises is re-raised here, so
    the caller's error handling is unaffected.
    """
    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def runner() -> None:
        try:
            result_queue.put(("ok", work()))
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            result_queue.put(("error", exc))

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()

    container = st.container()
    with container:
        heading = st.empty()
        bar = st.progress(0.0)
        detail = st.empty()

    started = time.time()
    last_index = -1

    while thread.is_alive():
        elapsed = time.time() - started
        index, stage = _stage_at(elapsed)

        # Hold just short of complete until the response actually arrives, so
        # a full bar always means a finished run.
        fraction = min(elapsed / TOTAL, 0.97) if TOTAL else 0.0

        if index != last_index:
            heading.markdown(f"**{label}** \u00b7 step {index + 1} of {len(STAGES)}")
            last_index = index

        bar.progress(fraction, text=stage)
        if elapsed > TOTAL:
            detail.caption(
                f"{elapsed:.0f}s elapsed. Still running \u2014 the model calls vary "
                f"a good deal in length from one run to the next."
            )
        else:
            detail.caption(
                f"{elapsed:.0f}s elapsed \u00b7 typically about {TOTAL:.0f}s in total."
                + (
                    "  The records are fetched a page at a time against a rate "
                    "limit."
                    if 3 < elapsed < 16 else ""
                )
            )
        time.sleep(0.4)

    thread.join()
    status, payload = result_queue.get()

    bar.progress(1.0, text="Complete")
    heading.empty()
    detail.empty()
    time.sleep(0.2)
    container.empty()

    if status == "error":
        raise payload
    return payload
