"""Put a cluster-bootstrap interval on the composition effect.

    python scripts/run_uncertainty.py
    python scripts/run_uncertainty.py --resamples 5000

The README claimed "about 14% of the apparent warming is the station network
changing" from a difference of two differences, with no uncertainty attached.
This is the missing computation. It also reports the naive row-level standard
error alongside, to show how much too narrow that would have been.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gsod.analysis import annual_temperature  # noqa: E402
from gsod.uncertainty import composition_effect  # noqa: E402
from gsod.utils import PROJECT_ROOT, load_config, save_json, setup_logging  # noqa: E402
from gsod.warehouse import attach_observations, connect  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--resamples", type=int, default=2000)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    log = setup_logging()
    config = load_config()

    con = connect()
    attach_observations(con, PROJECT_ROOT / config["data"]["parquet_dir"])

    log.info("Cluster-bootstrapping the composition effect over %d resamples ...",
             args.resamples)
    effect = composition_effect(con, args.resamples, config["seed"])

    # For contrast: the interval somebody would get by treating station-days as
    # independent. Kept in the report because the gap between the two is the
    # whole methodological point.
    annual = annual_temperature(con).set_index("year")
    naive_se = float(
        (annual.loc[effect.first_year, "sd_temp_c"] ** 2
         / annual.loc[effect.first_year, "station_days"]
         + annual.loc[effect.last_year, "sd_temp_c"] ** 2
         / annual.loc[effect.last_year, "station_days"]) ** 0.5
    )

    payload = {
        "composition_effect": effect.summary(),
        "row_level_standard_error_for_contrast": {
            "value_c": round(naive_se, 5),
            "note": ("Standard error of the change in mean, computed as if every "
                     "station-day were an independent draw. Reported only to show "
                     "how much too narrow that assumption is; it is not used for "
                     "any published interval."),
        },
    }
    save_json(payload, "reports/metrics_uncertainty.json")

    print(f"\nComposition effect, {effect.first_year} to {effect.last_year}")
    print("-" * 66)
    print(f"  change, all stations        {effect.naive_change:+.4f} C")
    print(f"  change, balanced panel      {effect.balanced_change:+.4f} C")
    print(f"  composition effect          {effect.effect:+.4f} C"
          f"   ({effect.summary()['share_pct']:.1f}% of the apparent warming)")
    print(f"  95% CI (station bootstrap)  [{effect.ci_lower:+.4f}, {effect.ci_upper:+.4f}]")
    print(f"  excludes zero               {effect.excludes_zero}")
    print("-" * 66)
    print(f"  stations resampled          {effect.n_stations:,}"
          f"  ({effect.n_stations_balanced:,} in the balanced panel)")
    print(f"  resamples kept              {effect.n_resamples:,}")
    shares = effect.summary()
    print(f"  as a share of the apparent warming: {shares['share_pct']:.1f}%, "
          f"95% CI [{shares['share_pct_ci95_lower']:.1f}%, "
          f"{shares['share_pct_ci95_upper']:.1f}%]")
    print()
    print(f"  for scale, the row-level SE of the ANNUAL MEAN CHANGE is {naive_se:.5f} C,")
    print("  computed as if station-days were independent. It is not an interval for")
    print("  the composition effect and is not compared against one here.")

    log.info("wrote reports/metrics_uncertainty.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
