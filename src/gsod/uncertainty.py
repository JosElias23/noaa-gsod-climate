"""How much of the composition effect is signal, and how much is sampling?

The README claims that about 14% of the apparent five-year warming is the
station network changing rather than the climate, from

    (naive 2024 - naive 2020) - (balanced 2024 - balanced 2020)
    =        +0.820           -        +0.706              = 0.114 C

That is a difference of two differences of two averages, published with no
uncertainty at all. This module puts an interval on it.

**Why the obvious standard error is wrong.** `annual_temperature` already
returns sd_temp_c, around 12.5 C. Divided by the square root of four million
station-days that gives 0.006 C, which would make everything here
overwhelmingly significant. It is badly overconfident for two reasons:

  - That 12.5 C is not measurement error. It is the spread between a station in
    Greenland and one in the Sahara -- spatial variation, not noise.
  - Station-days are not independent draws. They are clustered by station
    (roughly 320 days from the same instrument in the same place) and
    autocorrelated in time (today's temperature predicts tomorrow's).

So the resampling unit is the **station**, not the row. That is the standard
cluster-bootstrap correction, and it is the difference between an interval
somebody can defend and one that is simply too narrow.

**Why both panels are computed on the same resample.** The naive and balanced
trends share most of their data, so their errors are strongly positively
correlated, and the variance of their difference is much smaller than the sum of
their variances. Bootstrapping them separately and subtracting would overstate
the uncertainty. Each draw therefore recomputes both from the same sampled
stations.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np

# One row per station-year: the sum and the count needed to rebuild a
# row-weighted mean for any subset of stations, without touching 20 M rows again.
PER_STATION_YEAR = """
SELECT
    station,
    year,
    SUM(temp_c)   AS total,
    COUNT(temp_c) AS n
FROM observations
WHERE temp_c IS NOT NULL
GROUP BY station, year
ORDER BY station, year
"""


@dataclass(frozen=True)
class CompositionEffect:
    """The composition effect and its cluster-bootstrap interval."""

    naive_change: float
    balanced_change: float
    effect: float
    share_of_naive: float
    ci_lower: float
    ci_upper: float
    n_resamples: int
    n_stations: int
    n_stations_balanced: int
    first_year: int
    last_year: int
    excludes_zero: bool

    def summary(self) -> dict:
        return {
            "naive_change_c": round(self.naive_change, 4),
            "balanced_change_c": round(self.balanced_change, 4),
            "composition_effect_c": round(self.effect, 4),
            # Percentages at one decimal, the precision this is published at.
            # Storing the raw ratio and formatting it later means rounding twice,
            # and 0.0765 then prints as 7.6% where the ratio prints as 7.7%.
            "share_pct": round(100 * self.share_of_naive, 1),
            "share_pct_ci95_lower": round(100 * self.ci_lower / self.naive_change, 1),
            "share_pct_ci95_upper": round(100 * self.ci_upper / self.naive_change, 1),
            "ci95_lower_c": round(self.ci_lower, 4),
            "ci95_upper_c": round(self.ci_upper, 4),
            "excludes_zero": self.excludes_zero,
            "n_resamples": self.n_resamples,
            "n_stations": self.n_stations,
            "n_stations_balanced": self.n_stations_balanced,
            "resampling_unit": "station",
            "note": (
                "Stations are resampled with replacement, not station-days: rows "
                "are clustered by station and autocorrelated in time, so a "
                "row-level interval would be far too narrow. Both panels are "
                "recomputed from the same draw, because they share most of their "
                "data and the variance of their difference is much smaller than "
                "the sum of their variances."
            ),
        }


def _weighted_change(totals: np.ndarray, counts: np.ndarray,
                     first: int, last: int) -> float:
    """Row-weighted mean at `last` minus at `first`, for one set of stations.

    Columns are years; rows are stations. A station absent in a year contributes
    a count of zero there, which is exactly how the unbalanced panel behaves.
    """
    n_first, n_last = counts[:, first].sum(), counts[:, last].sum()
    if n_first == 0 or n_last == 0:
        return float("nan")
    return float(totals[:, last].sum() / n_last - totals[:, first].sum() / n_first)


def composition_effect(
    con: duckdb.DuckDBPyConnection,
    n_resamples: int = 2000,
    seed: int = 42,
) -> CompositionEffect:
    frame = con.execute(PER_STATION_YEAR).df()
    years = sorted(frame["year"].unique())
    stations = frame["station"].unique()
    year_index = {y: i for i, y in enumerate(years)}
    station_index = {s: i for i, s in enumerate(stations)}

    totals = np.zeros((len(stations), len(years)))
    counts = np.zeros((len(stations), len(years)))
    for station, year, total, n in frame.itertuples(index=False):
        i, j = station_index[station], year_index[year]
        totals[i, j] = total
        counts[i, j] = n

    balanced = (counts > 0).all(axis=1)
    first, last = 0, len(years) - 1

    naive_change = _weighted_change(totals, counts, first, last)
    balanced_change = _weighted_change(totals[balanced], counts[balanced], first, last)
    effect = naive_change - balanced_change

    rng = np.random.default_rng(seed)
    draws = np.empty(n_resamples)
    for b in range(n_resamples):
        pick = rng.integers(0, len(stations), size=len(stations))
        t, c = totals[pick], counts[pick]
        keep = balanced[pick]
        draws[b] = (_weighted_change(t, c, first, last)
                    - _weighted_change(t[keep], c[keep], first, last))

    draws = draws[~np.isnan(draws)]
    lower, upper = np.percentile(draws, [2.5, 97.5])

    return CompositionEffect(
        naive_change=naive_change,
        balanced_change=balanced_change,
        effect=effect,
        share_of_naive=effect / naive_change if naive_change else float("nan"),
        ci_lower=float(lower),
        ci_upper=float(upper),
        n_resamples=int(len(draws)),
        n_stations=int(len(stations)),
        n_stations_balanced=int(balanced.sum()),
        first_year=int(years[first]),
        last_year=int(years[last]),
        excludes_zero=bool(lower > 0 or upper < 0),
    )
