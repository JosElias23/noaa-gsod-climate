"""Tests for parsing GSOD, written around the failures this actually hit."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pandas as pd
import pytest

from gsod.data import (
    EVENT_FLAGS,
    MISSING,
    Archive,
    _to_float,
    read_archive,
    sha256_of,
    write_parquet,
)

HEADER = ('"STATION","DATE","LATITUDE","LONGITUDE","ELEVATION","NAME","TEMP",'
          '"TEMP_ATTRIBUTES","DEWP","DEWP_ATTRIBUTES","SLP","SLP_ATTRIBUTES",'
          '"STP","STP_ATTRIBUTES","VISIB","VISIB_ATTRIBUTES","WDSP",'
          '"WDSP_ATTRIBUTES","MXSPD","GUST","MAX","MAX_ATTRIBUTES","MIN",'
          '"MIN_ATTRIBUTES","PRCP","PRCP_ATTRIBUTES","SNDP","FRSHTT"')


def row(station="01001099999", date="2024-01-02", name="JAN MAYEN NOR NAVY, NO",
        temp="  33.3", frshtt="111000", prcp=" 0.01", vis=" 15.5"):
    """One GSOD line. NAME carries a comma inside quotes, exactly as NCEI ships it."""
    return (f'"{station}","{date}","70.93","-8.67","9.0","{name}","{temp}","24",'
            f'"  30.9","24","1006.9","24","005.7","24","{vis}"," 4"," 13.1","24",'
            f'" 15.3"," 20.6","  34.5"," ","  31.1"," ","{prcp}","G","999.9","{frshtt}"')


def make_archive(tmp_path: Path, lines, name="01001099999.csv") -> Archive:
    tmp_path.mkdir(parents=True, exist_ok=True)
    csv_bytes = ("\n".join([HEADER, *lines]) + "\n").encode("utf-8")
    tar_path = tmp_path / "2024.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(csv_bytes)
        tar.addfile(info, io.BytesIO(csv_bytes))
    return Archive(2024, tar_path, tar_path.stat().st_size, sha256_of(tar_path))


class TestCommaInsideQuotes:
    """The bug that made the first run report event counts ~400x too small."""

    def test_station_name_with_comma_does_not_shift_columns(self, tmp_path):
        archive = make_archive(tmp_path, [row(name="JAN MAYEN NOR NAVY, NO",
                                              frshtt="111000")])
        frame = read_archive(archive)
        assert frame.loc[0, "name"] == "JAN MAYEN NOR NAVY, NO"
        # F,R,S = 1 and H,T,T = 0
        assert bool(frame.loc[0, "fog"])
        assert bool(frame.loc[0, "rain_drizzle"])
        assert bool(frame.loc[0, "snow_ice_pellets"])
        assert not bool(frame.loc[0, "hail"])
        assert not bool(frame.loc[0, "thunder"])
        assert not bool(frame.loc[0, "tornado_funnel_cloud"])

    def test_a_name_without_a_comma_parses_the_same_way(self, tmp_path):
        with_comma = read_archive(make_archive(tmp_path / "a", [row(name="X, YZ")]))
        without = read_archive(make_archive(tmp_path / "b", [row(name="XYZ")]))
        for event in EVENT_FLAGS:
            assert bool(with_comma.loc[0, event]) == bool(without.loc[0, event])


class TestEventFlags:
    """FRSHTT is positional; an off-by-one silently relabels every event."""

    @pytest.mark.parametrize("position,event", list(enumerate(EVENT_FLAGS)))
    def test_each_position_sets_exactly_its_own_event(self, tmp_path, position, event):
        flags = ["0"] * 6
        flags[position] = "1"
        d = tmp_path / f"p{position}"
        d.mkdir(parents=True, exist_ok=True)
        frame = read_archive(make_archive(d, [row(frshtt="".join(flags))]))
        assert bool(frame.loc[0, event]), f"{event} should be set at position {position}"
        for other in EVENT_FLAGS:
            if other != event:
                assert not bool(frame.loc[0, other]), f"{other} leaked from {event}"

    def test_flags_are_not_mutually_exclusive(self, tmp_path):
        """One station-day can be several events at once.

        This is why the six shares do not sum to 100, and why the original
        README's unlabelled 'Porcentaje' column could not mean what it looked
        like it meant.
        """
        frame = read_archive(make_archive(tmp_path, [row(frshtt="111111")]))
        assert all(bool(frame.loc[0, e]) for e in EVENT_FLAGS)

    def test_malformed_flag_string_sets_nothing(self, tmp_path):
        frame = read_archive(make_archive(tmp_path, [row(frshtt="")]))
        assert not any(bool(frame.loc[0, e]) for e in EVENT_FLAGS)


class TestMissingSentinels:
    """GSOD encodes 'no observation' as repeated nines, per column."""

    @pytest.mark.parametrize("column,sentinel", sorted(MISSING.items()))
    def test_sentinel_becomes_none(self, column, sentinel):
        assert _to_float(str(sentinel), column) is None

    def test_a_real_value_survives(self):
        assert _to_float("  33.3", "TEMP") == pytest.approx(33.3)

    def test_sentinel_for_one_column_is_a_valid_value_for_another(self):
        # 99.99 is missing precipitation but a perfectly ordinary temperature.
        assert _to_float("99.99", "PRCP") is None
        assert _to_float("99.99", "TEMP") == pytest.approx(99.99)

    def test_missing_temperature_does_not_become_a_number(self, tmp_path):
        frame = read_archive(make_archive(tmp_path, [row(temp="9999.9")]))
        assert pd.isna(frame.loc[0, "temp_f"])
        assert pd.isna(frame.loc[0, "temp_c"])


class TestUnitConversion:
    def test_fahrenheit_to_celsius(self, tmp_path):
        frame = read_archive(make_archive(tmp_path, [row(temp="  32.0")]))
        assert frame.loc[0, "temp_c"] == pytest.approx(0.0)

    def test_a_known_pair(self, tmp_path):
        frame = read_archive(make_archive(tmp_path, [row(temp=" 212.0")]))
        assert frame.loc[0, "temp_c"] == pytest.approx(100.0)


class TestAtomicWrite:
    def test_no_partial_file_is_left_behind(self, tmp_path):
        frame = pd.DataFrame({"a": [1, 2, 3]})
        target = tmp_path / "gsod_2024.parquet"
        write_parquet(frame, target)
        assert target.exists()
        assert not list(tmp_path.glob("*.part")), "temporary file was not renamed"
        assert len(pd.read_parquet(target)) == 3
