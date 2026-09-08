"""The analysis, written as SQL over the Parquet warehouse.

Every question here is a grouped aggregate over a few million rows, which is
what a database is for. The original notebook this repository re-does pulled the
whole year to the client with `SELECT *` and counted in pandas;
`scripts/compare_pushdown.py` measures what that costs.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from gsod.data import EVENT_FLAGS

# ---------------------------------------------------------------- event counts

EVENT_COUNTS = f"""
SELECT
    {", ".join(f"SUM({e}::INT) AS {e}" for e in EVENT_FLAGS)},
    COUNT(*) AS station_days
FROM observations
WHERE year = ?
"""


def event_counts(con: duckdb.DuckDBPyConnection, year: int) -> pd.DataFrame:
    """Occurrences of each weather event, and the share of station-days.

    The share is 'of all station-days', not 'of all events'. The six flags are
    independent -- one station-day can be fog and rain and thunder at once -- so
    the shares do not sum to 100 and it is meaningless to ask what fraction of
    'the events' each one is. The original README printed a bare 'Porcentaje'
    column without saying of what, which is how a 25% and a 10.5% ended up
    looking comparable when they were not even the same quantity.
    """
    row = con.execute(EVENT_COUNTS, [year]).fetchone()
    total = row[-1]
    frame = pd.DataFrame(
        {"event": EVENT_FLAGS, "occurrences": [int(v) for v in row[:-1]]}
    )
    frame["pct_of_station_days"] = (100 * frame["occurrences"] / total).round(2)
    frame["station_days"] = total
    return frame.sort_values("occurrences", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------ monthly seasonality

MONTHLY_EVENTS = f"""
SELECT
    MONTH(date) AS month,
    {", ".join(f"SUM({e}::INT) AS {e}" for e in EVENT_FLAGS)},
    COUNT(*) AS station_days
FROM observations
WHERE year = ?
GROUP BY 1
ORDER BY 1
"""


def monthly_events(con: duckdb.DuckDBPyConnection, year: int) -> pd.DataFrame:
    return con.execute(MONTHLY_EVENTS, [year]).df()


# ------------------------------------------------------- annual temperature trend

ANNUAL_TEMPERATURE = """
SELECT
    year,
    COUNT(*)                       AS station_days,
    COUNT(DISTINCT station)        AS stations,
    ROUND(AVG(temp_c), 4)          AS mean_temp_c,
    ROUND(STDDEV_SAMP(temp_c), 4)  AS sd_temp_c,
    ROUND(MIN(temp_c), 2)          AS min_temp_c,
    ROUND(MAX(temp_c), 2)          AS max_temp_c
FROM observations
WHERE temp_c IS NOT NULL
GROUP BY year
ORDER BY year
"""


def annual_temperature(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Mean temperature per year across all reporting stations.

    This is a mean over whichever stations happened to report, not a global mean
    temperature. The station network is neither uniform over the globe nor
    constant between years, so year-on-year differences here confound real
    climate signal with changes in who was reporting. `station_overlap` below
    exists to measure how large that confound is before anything is concluded.
    """
    return con.execute(ANNUAL_TEMPERATURE).df()


BALANCED_TEMPERATURE = """
WITH every_year AS (
    SELECT station
    FROM observations
    WHERE temp_c IS NOT NULL
    GROUP BY station
    HAVING COUNT(DISTINCT year) = (SELECT COUNT(DISTINCT year) FROM observations)
)
SELECT
    year,
    COUNT(DISTINCT o.station)      AS stations,
    COUNT(*)                       AS station_days,
    ROUND(AVG(temp_c), 4)          AS mean_temp_c
FROM observations o
JOIN every_year USING (station)
WHERE temp_c IS NOT NULL
GROUP BY year
ORDER BY year
"""


def balanced_temperature(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """The same trend, restricted to stations that reported in *every* year.

    A balanced panel. Comparing this against `annual_temperature` separates the
    trend from the changing composition of the station network.
    """
    return con.execute(BALANCED_TEMPERATURE).df()


# --------------------------------------------------------------- station coverage

STATION_COVERAGE = """
SELECT
    RIGHT(TRIM(name), 2)      AS country,
    COUNT(DISTINCT station)   AS stations,
    COUNT(*)                  AS station_days
FROM observations
WHERE year = ? AND LENGTH(TRIM(name)) >= 2
GROUP BY 1
ORDER BY station_days DESC
LIMIT ?
"""


def station_coverage(con: duckdb.DuckDBPyConnection, year: int, top: int = 12) -> pd.DataFrame:
    """Where the reporting stations actually are.

    GSOD's NAME field ends in a two-letter country code. The distribution is
    heavily skewed, which is why 'the most common weather event globally' is
    really 'the most common weather event among stations that report to GSOD'.
    """
    return con.execute(STATION_COVERAGE, [year, top]).df()


STATION_OVERLAP = """
SELECT
    (SELECT COUNT(DISTINCT station) FROM observations)                      AS stations_any_year,
    (SELECT COUNT(*) FROM (
        SELECT station FROM observations
        GROUP BY station
        HAVING COUNT(DISTINCT year) = (SELECT COUNT(DISTINCT year) FROM observations)
    ))                                                                     AS stations_every_year
"""


def station_overlap(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute(STATION_OVERLAP).fetchone()
    any_year, every_year = int(row[0]), int(row[1])
    return {
        "stations_any_year": any_year,
        "stations_every_year": every_year,
        "share_reporting_every_year": round(every_year / any_year, 4) if any_year else 0.0,
    }
