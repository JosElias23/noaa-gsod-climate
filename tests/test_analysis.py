"""Tests for the SQL, on a small hand-built warehouse with known answers."""

from __future__ import annotations

import pandas as pd
import pytest

from gsod.analysis import (
    annual_temperature,
    balanced_temperature,
    event_counts,
    station_coverage,
    station_overlap,
)
from gsod.data import EVENT_FLAGS
from gsod.warehouse import connect


@pytest.fixture
def con(tmp_path):
    """Six station-days over two years, with counts that can be done by hand.

    2024: 4 rows. fog on 3 of them, rain on 2, one row is both.
    2023: 2 rows, from one station that also reports in 2024 and one that does not.
    """
    rows = [
        # station, year, date, name, temp_c, fog, rain, snow, hail, thunder, tornado
        ("A", 2024, "2024-01-01", "ALPHA FIELD, US", 10.0, 1, 1, 0, 0, 0, 0),
        ("A", 2024, "2024-02-01", "ALPHA FIELD, US", 20.0, 1, 0, 0, 0, 0, 0),
        ("B", 2024, "2024-01-01", "BRAVO FIELD, CL", 30.0, 1, 0, 0, 0, 0, 0),
        ("B", 2024, "2024-03-01", "BRAVO FIELD, CL", 40.0, 0, 1, 0, 0, 0, 0),
        ("A", 2023, "2023-01-01", "ALPHA FIELD, US", 0.0, 0, 0, 1, 0, 0, 0),
        ("C", 2023, "2023-01-01", "CHARLIE FIELD, US", 100.0, 0, 0, 0, 1, 1, 1),
    ]
    frame = pd.DataFrame(rows, columns=[
        "station", "year", "date", "name", "temp_c", *EVENT_FLAGS])
    frame["date"] = pd.to_datetime(frame["date"])
    for e in EVENT_FLAGS:
        frame[e] = frame[e].astype(bool)

    path = tmp_path / "gsod_test.parquet"
    frame.to_parquet(path, index=False)
    posix = str(path).replace("\\", "/")
    connection = connect()
    connection.execute(
        f"CREATE VIEW observations AS SELECT * FROM read_parquet('{posix}')"
    )
    return connection


class TestEventCounts:
    def test_counts_match_a_hand_count(self, con):
        result = event_counts(con, 2024).set_index("event")["occurrences"].to_dict()
        assert result["fog"] == 3
        assert result["rain_drizzle"] == 2
        assert result["snow_ice_pellets"] == 0

    def test_denominator_is_station_days_not_events(self, con):
        result = event_counts(con, 2024)
        assert int(result["station_days"].iloc[0]) == 4
        fog = result.set_index("event").loc["fog", "pct_of_station_days"]
        assert fog == pytest.approx(75.0)  # 3 of 4 station-days, not 3 of 5 flags

    def test_shares_need_not_sum_to_one_hundred(self, con):
        """The property that makes an unlabelled 'Porcentaje' column misleading."""
        total = event_counts(con, 2024)["pct_of_station_days"].sum()
        assert total == pytest.approx(125.0)  # 75 + 50, and that is correct

    def test_other_years_are_excluded(self, con):
        result = event_counts(con, 2024).set_index("event")["occurrences"].to_dict()
        assert result["hail"] == 0  # the only hail is in 2023
        assert result["tornado_funnel_cloud"] == 0


class TestTemperature:
    def test_mean_per_year(self, con):
        result = annual_temperature(con).set_index("year")["mean_temp_c"].to_dict()
        assert result[2024] == pytest.approx(25.0)   # (10+20+30+40)/4
        assert result[2023] == pytest.approx(50.0)   # (0+100)/2

    def test_balanced_panel_keeps_only_stations_present_in_every_year(self, con):
        result = balanced_temperature(con).set_index("year")
        # Only station A reports in both years.
        assert set(result.index) == {2023, 2024}
        assert result.loc[2023, "stations"] == 1
        assert result.loc[2024, "stations"] == 1
        assert result.loc[2023, "mean_temp_c"] == pytest.approx(0.0)
        assert result.loc[2024, "mean_temp_c"] == pytest.approx(15.0)  # (10+20)/2

    def test_the_two_panels_disagree_which_is_the_whole_point(self, con):
        """Station composition, not climate, moves the unbalanced mean."""
        unbalanced = annual_temperature(con).set_index("year")["mean_temp_c"]
        balanced = balanced_temperature(con).set_index("year")["mean_temp_c"]
        assert unbalanced[2023] != pytest.approx(balanced[2023])


class TestCoverage:
    def test_country_comes_from_the_end_of_the_name(self, con):
        result = station_coverage(con, 2024, top=10).set_index("country")
        assert result.loc["US", "stations"] == 1
        assert result.loc["CL", "stations"] == 1

    def test_overlap_counts_stations_present_in_every_year(self, con):
        overlap = station_overlap(con)
        assert overlap["stations_any_year"] == 3     # A, B, C
        assert overlap["stations_every_year"] == 1   # only A
        assert overlap["share_reporting_every_year"] == pytest.approx(1 / 3, abs=1e-4)
