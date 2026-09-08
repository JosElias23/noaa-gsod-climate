"""What it costs to count in pandas instead of in SQL.

The notebook this repository re-does ran `SELECT *` over a full year of GSOD and
counted the event flags in pandas. The same six numbers are one grouped
aggregate. This measures the difference on identical data, and reports the
result whichever way it comes out.

    python scripts/compare_pushdown.py

Three arms, all producing the identical six counts:

  client_side_all_columns    SELECT *              -- what the original did
  client_side_needed_columns SELECT the 6 flags    -- column pruning only
  sql_pushdown               SUM(...) GROUP BY     -- aggregate in the engine
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gsod.data import EVENT_FLAGS  # noqa: E402
from gsod.utils import (  # noqa: E402
    PROJECT_ROOT,
    human_bytes,
    load_config,
    save_json,
    setup_logging,
)
from gsod.warehouse import attach_observations, connect  # noqa: E402

REPEATS = 3


def measure(name: str, fn) -> dict:
    """Run an arm, keeping the best wall time of REPEATS.

    Best rather than mean: the slow runs are contention with whatever else the
    machine is doing, and the question here is how much work the approach costs,
    not how busy the laptop was.
    """
    timings, result = [], None
    for _ in range(REPEATS):
        started = time.perf_counter()
        result = fn()
        timings.append(time.perf_counter() - started)
    counts, rows, frame_bytes = result
    return {
        "arm": name,
        "seconds": round(min(timings), 3),
        "rows_to_client": int(rows),
        "client_bytes": int(frame_bytes),
        "counts": counts,
    }


def main() -> int:
    args = parse_args()
    log = setup_logging()
    config = load_config()
    year = args.year or config["analysis"]["event_year"]

    con = connect()
    attach_observations(con, PROJECT_ROOT / config["data"]["parquet_dir"])

    def client_side_all_columns():
        frame = con.execute("SELECT * FROM observations WHERE year = ?", [year]).df()
        counts = {e: int(frame[e].sum()) for e in EVENT_FLAGS}
        return counts, len(frame), frame.memory_usage(deep=True).sum()

    def client_side_needed_columns():
        cols = ", ".join(EVENT_FLAGS)
        frame = con.execute(
            f"SELECT {cols} FROM observations WHERE year = ?", [year]).df()
        counts = {e: int(frame[e].sum()) for e in EVENT_FLAGS}
        return counts, len(frame), frame.memory_usage(deep=True).sum()

    def sql_pushdown():
        cols = ", ".join(f"SUM({e}::INT) AS {e}" for e in EVENT_FLAGS)
        frame = con.execute(
            f"SELECT {cols} FROM observations WHERE year = ?", [year]).df()
        counts = {e: int(frame[e].iloc[0]) for e in EVENT_FLAGS}
        return counts, len(frame), frame.memory_usage(deep=True).sum()

    arms = [
        measure("client_side_all_columns", client_side_all_columns),
        measure("client_side_needed_columns", client_side_needed_columns),
        measure("sql_pushdown", sql_pushdown),
    ]

    # An optimisation that changes the answer is not an optimisation. Every arm
    # must return byte-identical counts or the comparison means nothing.
    reference = arms[0]["counts"]
    identical = all(a["counts"] == reference for a in arms)
    if not identical:
        log.error("Arms disagree on the counts; the comparison is void.")

    baseline = arms[0]
    for arm in arms:
        arm["speedup_vs_baseline"] = round(baseline["seconds"] / arm["seconds"], 1)
        arm["client_bytes_ratio"] = round(baseline["client_bytes"] / arm["client_bytes"], 1)

    save_json(
        {
            "year": year,
            "repeats": REPEATS,
            "all_arms_agree": identical,
            "counts": reference,
            "arms": [{k: v for k, v in a.items() if k != "counts"} for a in arms],
            "note": ("Wall time is the best of three runs on one machine; treat "
                     "the ratios as the finding, not the absolute seconds. "
                     "client_bytes is the in-memory size of the frame handed "
                     "back to Python, which is what the original notebook had "
                     "to hold to do its counting."),
        },
        "reports/metrics_pushdown.json",
    )

    print(f"\nCounting {len(EVENT_FLAGS)} event flags over {year} "
          f"({baseline['rows_to_client']:,} station-days)")
    print(f"{'arm':<28}{'seconds':>9}{'rows to client':>17}{'client memory':>16}{'speedup':>10}")
    print("-" * 80)
    for a in arms:
        print(f"{a['arm']:<28}{a['seconds']:>9.3f}{a['rows_to_client']:>17,}"
              f"{human_bytes(a['client_bytes']):>16}{a['speedup_vs_baseline']:>9.1f}x")
    print("-" * 80)
    print(f"all arms return identical counts: {identical}")
    log.info("wrote reports/metrics_pushdown.json")
    return 0 if identical else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, default=None)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
