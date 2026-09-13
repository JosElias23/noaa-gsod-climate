"""Run the BigQuery arm for real, and price it.

`sql/bigquery.sql` arrived in `9fb245f`, alongside the SQL analysis itself, with a
comment saying it "returns the same six numbers" — checked by eye, never
executed, never tested. Section 6 of `docs/DECISIONS.md` listed that as the
project's largest hole: the cloud-warehouse path is the more interesting one
professionally, and it was the one path this repository did not run.

This closes it. The file is executed rather than read, against
`bigquery-public-data.noaa_gsod`, and three things come back that the local
DuckDB warehouse cannot produce:

  **Agreement.** The six 2024 event counts from BigQuery against the six this
  repository publishes from NCEI. Two readers of the same NOAA product, so
  disagreement would mean a parse bug on one side; section 4 of DECISIONS
  explains why small positive differences are expected and what they mean.

  **Bytes scanned.** BigQuery bills on bytes read, not on rows returned or time
  elapsed, which makes the column-pruning lesson from
  `scripts/compare_pushdown.py` a line item rather than a stopwatch reading. The
  same `SELECT *` that cost 644 MB of client memory locally costs money here,
  every time it runs.

  **A dry run.** BigQuery will price a query without executing it. That costs
  nothing, needs no billing account, and is the honest way to show the scan cost
  of a query nobody should run — so the `SELECT *` arm is estimated, not
  executed, and the script says which arms were which.

Credentials: application-default credentials, i.e. `gcloud auth
application-default login`. Nothing here reads a service-account key file, and
no credential is stored in this repository. A BigQuery sandbox project is
enough; the queries below are far inside the free monthly tier.

    python scripts/run_bigquery.py --project YOUR_PROJECT_ID
    python scripts/run_bigquery.py --project YOUR_PROJECT_ID --dry-run-only

Writes reports/metrics_bigquery.json.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gsod.utils import (  # noqa: E402
    PROJECT_ROOT,
    human_bytes,
    save_json,
    setup_logging,
)

# BigQuery on-demand analysis pricing, us-multiregion, read September 2026.
# Named and dated rather than folded into a number, because a cost figure whose
# assumption is invisible is not a cost figure -- and because this one will go
# stale without anything in the repository noticing.
USD_PER_TIB_SCANNED = 6.25
PRICING_NOTE = (
    "BigQuery on-demand analysis, USD 6.25 per TiB scanned, us multi-region, "
    "rate read September 2026. The first 1 TiB each month is free, which is "
    "more than this script uses. Storage of the public dataset is paid by "
    "Google under the Public Datasets Program, so the reader pays only for the "
    "bytes their own query scans."
)

TIB = 1024 ** 4

TABLE_PATTERN = re.compile(r"FROM\s+(`[^`]+`)", re.I)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", required=True,
                   help="GCP project id to bill the query to (a sandbox project "
                        "works; the queries here fit in the free tier)")
    p.add_argument("--dry-run-only", action="store_true",
                   help="price every query without executing any of them")
    p.add_argument("--location", default="US",
                   help="dataset location; noaa_gsod lives in US")
    return p.parse_args()


def statements(path: Path) -> list[str]:
    """The SQL file, split into executable statements.

    Read from disk rather than duplicated into this script, so the file a reader
    inspects is the file that runs. Comment-only fragments are dropped.
    """
    text = path.read_text(encoding="utf-8")
    out = []
    for chunk in text.split(";"):
        body = "\n".join(
            line for line in chunk.splitlines() if not line.strip().startswith("--")
        ).strip()
        if body:
            out.append(body)
    return out


def label(sql: str) -> str:
    """A short name for a statement, from its shape."""
    if re.search(r"EXTRACT\(MONTH", sql, re.I):
        return "monthly_events"
    if re.search(r"SELECT\s+\*", sql, re.I):
        return "select_star"
    return "event_counts_2024"


def table_of(statements_: list[str]) -> str:
    """The table the SQL file actually reads.

    Derived rather than hard-coded, because the SELECT * arm below has to price
    the *same* table the real queries scan. A constant here would silently
    price gsod2024 after the file moved on to another year, and the comparison
    would be meaningless in a way nothing would flag.
    """
    tables = {m.group(1) for s in statements_ for m in TABLE_PATTERN.finditer(s)}
    if len(tables) != 1:
        raise SystemExit(
            f"expected sql/bigquery.sql to read exactly one table, found {tables}")
    return tables.pop()


def price(bytes_scanned: int) -> float:
    return round(bytes_scanned / TIB * USD_PER_TIB_SCANNED, 6)


def main() -> int:
    args = parse_args()
    log = setup_logging()

    try:
        from google.api_core import exceptions as gexc
        from google.cloud import bigquery
    except ImportError:
        log.error(
            "google-cloud-bigquery is not installed. This is an optional "
            "dependency because the rest of the repository needs no cloud "
            "account:\n    pip install -e \".[cloud]\""
        )
        return 1

    try:
        client = bigquery.Client(project=args.project, location=args.location)
    except Exception as exc:  # noqa: BLE001 - the message matters more than the type
        log.error("Could not create a BigQuery client: %s", exc)
        log.error("Authenticate with:  gcloud auth application-default login")
        return 1

    sql_path = PROJECT_ROOT / "sql" / "bigquery.sql"
    parsed = statements(sql_path)
    queries = [(label(s), s) for s in parsed]

    # The deliberately wasteful arm, built against whatever table the file
    # reads. Never executed -- only priced -- because the finding is what it
    # would cost, and paying to prove it would be silly.
    queries.append(("select_star", "SELECT *\nFROM " + table_of(parsed)))
    log.info("%d statements from %s, reading %s",
             len(parsed), sql_path.name, table_of(parsed))

    results = []
    for name, sql in queries:
        # Dry run first, always. It is free, it needs no billing account, and it
        # is the only honest way to report the cost of the SELECT * arm.
        dry = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        try:
            estimate = client.query(sql, job_config=dry)
        except gexc.GoogleAPICallError as exc:
            log.error("%s failed to plan: %s", name, exc)
            return 1
        estimated_bytes = int(estimate.total_bytes_processed)
        log.info("%-18s dry run: %s would be scanned (USD %.4f)",
                 name, human_bytes(estimated_bytes), price(estimated_bytes))

        entry = {
            "name": name,
            "executed": False,
            "estimated_bytes_processed": estimated_bytes,
            "estimated_usd": price(estimated_bytes),
        }

        # SELECT * is priced and never run: the finding is what it would cost.
        if name == "select_star" or args.dry_run_only:
            entry["not_executed_because"] = (
                "SELECT * is here to be priced, not to be paid for"
                if name == "select_star" else "--dry-run-only"
            )
            results.append(entry)
            continue

        started = time.perf_counter()
        job = client.query(sql, job_config=bigquery.QueryJobConfig(
            use_query_cache=False))
        rows = [dict(r) for r in job.result()]
        elapsed = time.perf_counter() - started

        entry.update({
            "executed": True,
            "bytes_processed": int(job.total_bytes_processed or 0),
            "bytes_billed": int(job.total_bytes_billed or 0),
            "usd_at_bytes_billed": price(int(job.total_bytes_billed or 0)),
            "cache_hit": bool(job.cache_hit),
            "elapsed_seconds": round(elapsed, 3),
            "slot_millis": int(job.slot_millis or 0) if job.slot_millis else None,
            "rows_returned": len(rows),
            "rows": rows,
        })
        results.append(entry)
        log.info("%-18s ran in %.2fs, billed %s (USD %.4f), %d row(s)",
                 name, elapsed, human_bytes(entry["bytes_billed"]),
                 entry["usd_at_bytes_billed"], len(rows))

    report = {
        "project_note": ("The project id is a command-line argument and is not "
                         "recorded here; it identifies the reader's account, "
                         "not the data."),
        "dataset": "bigquery-public-data.noaa_gsod.gsod2024",
        "pricing": {"usd_per_tib_scanned": USD_PER_TIB_SCANNED,
                    "note": PRICING_NOTE},
        "queries": results,
    }

    # --- the two comparisons that make this worth running ------------------
    counts = next((q for q in results
                   if q["name"] == "event_counts_2024" and q["executed"]), None)
    local_path = PROJECT_ROOT / "reports" / "metrics_analysis.json"
    if counts and local_path.exists():
        import json
        local = json.loads(local_path.read_text(encoding="utf-8"))
        ncei = {row["event"]: row["occurrences"] for row in local["event_counts"]}
        remote = counts["rows"][0]
        agreement = []
        for event, ncei_value in sorted(ncei.items()):
            bq_value = int(remote[event])
            agreement.append({
                "event": event,
                "ncei_archive": ncei_value,
                "bigquery": bq_value,
                "difference": ncei_value - bq_value,
                "pct_difference": round(100 * (ncei_value - bq_value) / bq_value, 3)
                if bq_value else None,
            })
        nonzero = [r for r in agreement if r["difference"] != 0]
        report["agreement_with_ncei"] = {
            "rows": agreement,
            "largest_abs_pct_difference": max(
                abs(r["pct_difference"]) for r in agreement
                if r["pct_difference"] is not None),
            "all_counts_identical": not nonzero,
            # Only meaningful when something actually differs. Reporting
            # "all the same sign" over six zeros would be true and would read
            # as "all positive", which is the kind of true-but-misleading
            # summary this repository exists to avoid.
            "all_differences_same_sign": (
                len({r["difference"] > 0 for r in nonzero}) == 1
                if nonzero else None),
            "note": ("BigQuery's noaa_gsod mirrors the same NCEI product, so "
                     "this checks two parsers and two retrieval dates against "
                     "each other -- not two independent measurements of the "
                     "weather. See docs/DECISIONS.md section 2.1."),
        }

    pruned = next((q for q in results if q["name"] == "event_counts_2024"), None)
    star = next((q for q in results if q["name"] == "select_star"), None)
    if pruned and star:
        saved = star["estimated_bytes_processed"] - pruned["estimated_bytes_processed"]
        report["column_pruning"] = {
            "select_star_bytes": star["estimated_bytes_processed"],
            "six_flag_columns_bytes": pruned["estimated_bytes_processed"],
            "bytes_saved": saved,
            "scan_ratio": round(
                star["estimated_bytes_processed"]
                / pruned["estimated_bytes_processed"], 1)
            if pruned["estimated_bytes_processed"] else None,
            "usd_saved_per_run": price(saved),
            "note": ("Locally, column pruning was 10x of a 38.7x speed-up and "
                     "cost nothing but a one-word change. Here it is the same "
                     "one-word change and it is billed."),
        }

    save_json(report, "reports/metrics_bigquery.json")

    # ------------------------------------------------------------------ console
    print()
    print("| Query | Bytes scanned | USD | Executed |")
    print("|---|---:|---:|:--:|")
    for q in results:
        b = q.get("bytes_billed", q["estimated_bytes_processed"])
        u = q.get("usd_at_bytes_billed", q["estimated_usd"])
        print(f"| {q['name']} | {human_bytes(b)} | {u:.4f} | "
              f"{'yes' if q['executed'] else 'no, priced only'} |")

    if "column_pruning" in report:
        cp = report["column_pruning"]
        print()
        print(f"Column pruning: {human_bytes(cp['select_star_bytes'])} against "
              f"{human_bytes(cp['six_flag_columns_bytes'])}, "
              f"{cp['scan_ratio']}x less scanned, "
              f"USD {cp['usd_saved_per_run']:.4f} saved per run.")

    if "agreement_with_ncei" in report:
        ag = report["agreement_with_ncei"]
        print()
        print("| Event | NCEI archive | BigQuery | Difference |")
        print("|---|---:|---:|---:|")
        for row in ag["rows"]:
            print(f"| {row['event']} | {row['ncei_archive']:,} | "
                  f"{row['bigquery']:,} | {row['pct_difference']:+.2f}% |")
        print()
        if ag["all_counts_identical"]:
            print("Every count is identical. Two parsers, two access paths, "
                  "the same six numbers.")
        else:
            print(f"Largest disagreement "
                  f"{ag['largest_abs_pct_difference']:.2f}%, all differences "
                  f"the same sign: {ag['all_differences_same_sign']}")

    print()
    print(PRICING_NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
