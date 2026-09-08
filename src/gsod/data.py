"""Download NOAA GSOD from NCEI and turn it into Parquet.

Source: https://www.ncei.noaa.gov/data/global-summary-of-the-day/archive/<year>.tar.gz
One gzipped tarball per year, roughly 100 MB, holding one CSV per reporting
station. No key, no registration, no cloud credentials — which is the point:
anyone can clone this repository and reproduce every number in it.

The same data is also the BigQuery public dataset `bigquery-public-data.noaa_gsod`
and the AWS Open Data bucket `s3://noaa-gsod-pds`. `sql/bigquery.sql` holds the
equivalent BigQuery query; see docs/DECISIONS.md section 2 for why the published
numbers come from the NCEI path rather than from BigQuery.
"""

from __future__ import annotations

import csv
import hashlib
import io
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ARCHIVE_URL = "https://www.ncei.noaa.gov/data/global-summary-of-the-day/archive/{year}.tar.gz"

# FRSHTT is a six-character indicator string in the GSOD record, one flag per
# event, always in this order. The flags are independent: a single station-day
# can be fog and rain and thunder at once, so the six shares do not sum to 100%.
EVENT_FLAGS = ["fog", "rain_drizzle", "snow_ice_pellets", "hail", "thunder", "tornado_funnel_cloud"]

# Columns kept from the 28 GSOD publishes. Dropping the rest is not tidiness:
# it is the difference between a 3.9 million row frame that fits in memory and
# one that does not.
KEEP = ["STATION", "DATE", "LATITUDE", "LONGITUDE", "ELEVATION", "NAME",
        "TEMP", "MAX", "MIN", "PRCP", "WDSP", "VISIB", "DEWP", "FRSHTT"]

# GSOD encodes "no observation" as a repeated-9 sentinel rather than as null,
# and the sentinel differs per column. Treating 9999.9 as a temperature is the
# single easiest way to get a wrong answer out of this dataset.
MISSING = {
    "TEMP": 9999.9, "MAX": 9999.9, "MIN": 9999.9, "DEWP": 9999.9,
    "PRCP": 99.99, "WDSP": 999.9, "VISIB": 999.9,
}


@dataclass(frozen=True)
class Archive:
    """One downloaded year, with the checksum of exactly what was parsed."""

    year: int
    path: Path
    size_bytes: int
    sha256: str

    def summary(self) -> dict:
        return {"year": self.year, "size_bytes": self.size_bytes,
                "sha256": self.sha256, "file": self.path.name}


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def download_year(year: int, cache_dir: Path) -> Archive:
    """Fetch one yearly archive, or reuse the cached copy."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{year}.tar.gz"
    if not path.exists():
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(ARCHIVE_URL.format(year=year), tmp)
        tmp.rename(path)
    return Archive(year, path, path.stat().st_size, sha256_of(path))


def _to_float(value: str, column: str) -> float | None:
    """Parse a GSOD numeric field, mapping its sentinel to None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    sentinel = MISSING.get(column)
    return None if sentinel is not None and number == sentinel else number


def read_archive(archive: Archive) -> pd.DataFrame:
    """Parse one yearly tarball into a tidy frame, one row per station-day.

    The rows go through csv.DictReader rather than str.split(","), because NAME
    contains commas inside quotes ("JAN MAYEN NOR NAVY, NO"). Splitting on the
    comma shifts every column after NAME, and the failure is silent: FRSHTT then
    reads whatever landed in the last position and the event counts come out
    roughly four hundred times too small while everything still runs.
    """
    records: list[dict] = []
    with tarfile.open(archive.path, "r:gz") as tar:
        for member in tar:
            if not member.name.endswith(".csv"):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            stream = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            for row in csv.DictReader(stream):
                flags = (row.get("FRSHTT") or "").strip()
                record = {
                    "station": row.get("STATION", "").strip(),
                    "date": row.get("DATE", "").strip(),
                    "name": row.get("NAME", "").strip(),
                    "latitude": _to_float(row.get("LATITUDE", ""), "LATITUDE"),
                    "longitude": _to_float(row.get("LONGITUDE", ""), "LONGITUDE"),
                    "elevation": _to_float(row.get("ELEVATION", ""), "ELEVATION"),
                }
                for column, key in (("TEMP", "temp_f"), ("MAX", "max_f"),
                                    ("MIN", "min_f"), ("DEWP", "dewp_f"),
                                    ("PRCP", "prcp_in"), ("WDSP", "wdsp_kn"),
                                    ("VISIB", "visib_mi")):
                    record[key] = _to_float(row.get(column, ""), column)
                for position, event in enumerate(EVENT_FLAGS):
                    record[event] = bool(len(flags) == 6 and flags[position] == "1")
                records.append(record)

    frame = pd.DataFrame.from_records(records)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["year"] = archive.year
    # GSOD reports in Fahrenheit. Celsius is derived here, once, rather than in
    # each analysis, so no query can forget the conversion.
    for source, target in (("temp_f", "temp_c"), ("max_f", "max_c"), ("min_f", "min_c")):
        frame[target] = (frame[source] - 32.0) * 5.0 / 9.0
    return frame


def write_parquet(frame: pd.DataFrame, path: Path) -> Path:
    """Write atomically: a reader must never see a half-written year.

    The warehouse view globs `gsod_*.parquet`, so a file that is still being
    written is a file DuckDB will try to read, and it fails with "No magic bytes
    found at end of file" -- which reads like corruption rather than like a race.
    Writing to a temporary name and renaming makes the file appear complete or
    not at all.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.part")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)
    return path
