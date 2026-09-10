"""Tests for the cluster bootstrap, on cases with a hand-computable answer."""

from __future__ import annotations

import pandas as pd
import pytest

from gsod.data import EVENT_FLAGS
from gsod.uncertainty import composition_effect
from gsod.warehouse import connect


def warehouse(tmp_path, rows):
    """rows: (station, year, temp_c) triples, one per station-day."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=["station", "year", "temp_c"])
    frame["date"] = pd.to_datetime(
        frame["year"].astype(str) + "-01-01"
    ) + pd.to_timedelta(frame.groupby(["station", "year"]).cumcount(), unit="D")
    frame["name"] = frame["station"] + " FIELD, US"
    for e in EVENT_FLAGS:
        frame[e] = False

    path = tmp_path / "gsod_test.parquet"
    frame.to_parquet(path, index=False)
    con = connect()
    con.execute(
        f"CREATE VIEW observations AS "
        f"SELECT * FROM read_parquet('{str(path).replace(chr(92), '/')}')"
    )
    return con


class TestPointEstimate:
    def test_a_case_computable_by_hand(self, tmp_path):
        """Station C appears only in the last year and drags the naive mean up.

        year 1: A=10, B=0                 -> naive mean  5
        year 2: A=20, B=0, C=100          -> naive mean 40   change +35
        balanced panel is A and B only:
        year 1: 5, year 2: (20+0)/2 = 10                     change  +5
        composition effect                                    35 - 5 = 30
        """
        con = warehouse(tmp_path, [
            ("A", 2020, 10.0), ("B", 2020, 0.0),
            ("A", 2024, 20.0), ("B", 2024, 0.0), ("C", 2024, 100.0),
        ])
        effect = composition_effect(con, n_resamples=200, seed=42)
        assert effect.naive_change == pytest.approx(35.0)
        assert effect.balanced_change == pytest.approx(5.0)
        assert effect.effect == pytest.approx(30.0)
        assert effect.n_stations == 3
        assert effect.n_stations_balanced == 2

    def test_a_balanced_network_has_no_composition_effect(self, tmp_path):
        """Every station present in every year: the two panels must coincide."""
        con = warehouse(tmp_path, [
            ("A", 2020, 10.0), ("B", 2020, 20.0),
            ("A", 2024, 12.0), ("B", 2024, 22.0),
        ])
        effect = composition_effect(con, n_resamples=200, seed=42)
        assert effect.effect == pytest.approx(0.0)
        assert effect.n_stations == effect.n_stations_balanced == 2

    def test_rows_are_weighted_by_reporting_days(self, tmp_path):
        """A station reporting twice counts twice, as AVG over rows does."""
        con = warehouse(tmp_path, [
            ("A", 2020, 0.0), ("A", 2020, 0.0), ("B", 2020, 30.0),
            ("A", 2024, 0.0), ("A", 2024, 0.0), ("B", 2024, 30.0),
        ])
        effect = composition_effect(con, n_resamples=100, seed=42)
        # Both years: (0 + 0 + 30) / 3 = 10. No change, no composition effect.
        assert effect.naive_change == pytest.approx(0.0)
        assert effect.effect == pytest.approx(0.0)


class TestInterval:
    def test_the_interval_brackets_the_point_estimate(self, tmp_path):
        con = warehouse(tmp_path, [
            (f"S{i:03d}", 2020, 10.0 + i % 7) for i in range(60)
        ] + [
            (f"S{i:03d}", 2024, 11.0 + i % 7) for i in range(60)
        ] + [
            (f"N{i:03d}", 2024, 30.0) for i in range(20)
        ])
        effect = composition_effect(con, n_resamples=500, seed=42)
        assert effect.ci_lower <= effect.effect <= effect.ci_upper

    def test_a_zero_effect_interval_contains_zero(self, tmp_path):
        """No newcomers means no composition effect, and the interval must say so."""
        con = warehouse(tmp_path, [
            (f"S{i:03d}", y, 10.0 + i % 5) for i in range(40) for y in (2020, 2024)
        ])
        effect = composition_effect(con, n_resamples=500, seed=42)
        assert effect.effect == pytest.approx(0.0)
        assert effect.ci_lower <= 0 <= effect.ci_upper
        assert not effect.excludes_zero

    def test_the_resampling_unit_is_the_station(self, tmp_path):
        """The methodological claim, made testable.

        Two warehouses hold the same number of station-days and the same
        temperatures. In the first they come from many stations; in the second
        from few stations each reporting many days. Under row-level resampling
        the two would give the same interval. Resampling stations must give a
        clearly wider interval for the second, because there are fewer
        independent units.
        """
        many = warehouse(tmp_path / "many", [
            (f"S{i:03d}", y, 10.0 + (i % 11)) for i in range(110) for y in (2020, 2024)
        ] + [(f"N{i:03d}", 2024, 40.0) for i in range(20)])

        few = warehouse(tmp_path / "few", [
            (f"S{i:03d}", y, 10.0 + (i % 11)) for i in range(11) for y in (2020, 2024)
            for _ in range(10)
        ] + [(f"N{i:03d}", 2024, 40.0) for i in range(2) for _ in range(10)])

        wide = composition_effect(few, n_resamples=800, seed=42)
        narrow = composition_effect(many, n_resamples=800, seed=42)

        width_few = wide.ci_upper - wide.ci_lower
        width_many = narrow.ci_upper - narrow.ci_lower
        assert width_few > width_many, (
            "fewer independent stations must yield a wider interval; "
            f"got {width_few:.4f} vs {width_many:.4f}"
        )


class TestReproducibility:
    def test_the_same_seed_gives_the_same_interval(self, tmp_path):
        rows = [(f"S{i:02d}", y, 10.0 + i % 4) for i in range(30)
                for y in (2020, 2024)] + [("NEW", 2024, 50.0)]
        a = composition_effect(warehouse(tmp_path / "a", rows), 300, seed=7)
        b = composition_effect(warehouse(tmp_path / "b", rows), 300, seed=7)
        assert (a.ci_lower, a.ci_upper) == (b.ci_lower, b.ci_upper)

    def test_a_different_seed_moves_the_interval_but_not_the_estimate(self, tmp_path):
        rows = [(f"S{i:02d}", y, 10.0 + i % 4) for i in range(30)
                for y in (2020, 2024)] + [("NEW", 2024, 50.0)]
        a = composition_effect(warehouse(tmp_path / "a", rows), 300, seed=7)
        b = composition_effect(warehouse(tmp_path / "b", rows), 300, seed=8)
        assert a.effect == pytest.approx(b.effect)
        assert (a.ci_lower, a.ci_upper) != (b.ci_lower, b.ci_upper)
