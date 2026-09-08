"""Run the analysis and write every published number to reports/.

    python scripts/run_analysis.py

Also checks the event counts against the figures the original notebook obtained
from BigQuery in March 2025, because two independent paths agreeing is worth
more than either one on its own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gsod.analysis import (  # noqa: E402
    annual_temperature,
    balanced_temperature,
    event_counts,
    monthly_events,
    station_coverage,
    station_overlap,
)
from gsod.utils import PROJECT_ROOT, load_config, save_json, setup_logging  # noqa: E402
from gsod.warehouse import attach_observations, connect, table_stats  # noqa: E402

# What the original notebook's BigQuery run reported for 2024. Kept here as a
# fixed reference so the cross-check is part of the pipeline rather than a
# one-off thing somebody did once and remembered.
NOTEBOOK_2024 = {
    "rain_drizzle": 968620, "snow_ice_pellets": 234571, "fog": 217755,
    "thunder": 173891, "hail": 4473, "tornado_funnel_cloud": 206,
}

# What the original README's results table claimed, which is a different thing
# again. Kept for the same reason.
README_2024 = {"fog": 120, "rain_drizzle": 85, "snow_ice_pellets": 30}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    log = setup_logging()
    config = load_config()
    year = args.year or config["analysis"]["event_year"]

    con = connect()
    n_files = attach_observations(con, PROJECT_ROOT / config["data"]["parquet_dir"])
    stats = table_stats(con)
    log.info("warehouse: %d Parquet files, %s rows, %s stations, %d-%d",
             n_files, f"{stats['rows']:,}", f"{stats['stations']:,}",
             stats["first_year"], stats["last_year"])

    events = event_counts(con, year)
    log.info("event counts for %d computed over %s station-days",
             year, f"{int(events['station_days'].iloc[0]):,}")

    # --- cross-check against the original BigQuery run --------------------
    checks = []
    for _, row in events.iterrows():
        reference = NOTEBOOK_2024.get(row["event"])
        if reference is None or year != 2024:
            continue
        delta = int(row["occurrences"]) - reference
        checks.append({
            "event": row["event"],
            "ncei": int(row["occurrences"]),
            "notebook_bigquery": reference,
            "delta": delta,
            "relative_pct": round(100 * abs(delta) / reference, 3),
        })
    worst = max((c["relative_pct"] for c in checks), default=0.0)

    annual = annual_temperature(con)
    balanced = balanced_temperature(con)
    overlap = station_overlap(con)
    coverage = station_coverage(con, year, config["analysis"]["top_countries"])
    monthly = monthly_events(con, year)

    save_json(
        {
            "year": year,
            "warehouse": stats,
            "event_counts": events.to_dict(orient="records"),
            "cross_check_vs_original_notebook": {
                "note": ("The original notebook queried "
                         "bigquery-public-data.noaa_gsod.gsod2024 in March 2025. "
                         "NCEI's archive is read today and includes station "
                         "reports filed since, so NCEI is expected to be "
                         "slightly higher throughout."),
                "largest_relative_difference_pct": worst,
                "per_event": checks,
            },
            "original_readme_claim": {
                "note": ("What the original README's results table stated. It is "
                         "not what that notebook computed."),
                "claimed": README_2024,
            },
            "monthly_events": monthly.to_dict(orient="records"),
            "station_coverage_top": coverage.to_dict(orient="records"),
            "station_overlap": overlap,
            "annual_temperature": annual.to_dict(orient="records"),
            "annual_temperature_balanced_panel": balanced.to_dict(orient="records"),
        },
        "reports/metrics_analysis.json",
    )

    # ------------------------------------------------------------- console
    print(f"\nWeather events, {year} — {int(events['station_days'].iloc[0]):,} station-days")
    print(f"{'event':<24}{'occurrences':>13}{'% of station-days':>20}")
    print("-" * 57)
    for _, r in events.iterrows():
        print(f"{r['event']:<24}{r['occurrences']:>13,}{r['pct_of_station_days']:>19.2f}%")
    print("-" * 57)
    print(f"{'sum of shares':<24}{'':>13}{events['pct_of_station_days'].sum():>19.2f}%"
          "   (flags are independent)")

    if checks:
        print(f"\nCross-check against the original BigQuery run "
              f"(largest relative difference {worst:.2f}%)")
        print(f"{'event':<24}{'NCEI':>12}{'notebook':>12}{'delta':>10}{'rel':>9}")
        print("-" * 67)
        for c in checks:
            print(f"{c['event']:<24}{c['ncei']:>12,}{c['notebook_bigquery']:>12,}"
                  f"{c['delta']:>+10,}{c['relative_pct']:>8.2f}%")

    print(f"\nStation panel: {overlap['stations_any_year']:,} stations reported in at "
          f"least one year, {overlap['stations_every_year']:,} in every year "
          f"({overlap['share_reporting_every_year']:.1%})")

    print("\nMean temperature by year")
    print(f"{'year':<8}{'stations':>10}{'all stations':>15}{'balanced panel':>17}")
    print("-" * 50)
    bal = balanced.set_index("year")["mean_temp_c"].to_dict()
    for _, r in annual.iterrows():
        y = int(r["year"])
        b = bal.get(y)
        balanced_cell = f"{b:.3f}C" if b is not None else "n/a"
        print(f"{y:<8}{int(r['stations']):>10,}{r['mean_temp_c']:>14.3f}C{balanced_cell:>17}")

    log.info("wrote reports/metrics_analysis.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
