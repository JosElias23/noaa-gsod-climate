"""The DuckDB warehouse: one Parquet file per year, one view over all of them.

Parquet rather than a loaded table because the columns are then pruned by the
reader: a query touching three of the twenty columns reads three columns off
disk. That is the same mechanism that makes `SELECT *` expensive on BigQuery,
reproduced locally where it can be measured without a billing account.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def connect(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """In-memory unless a path is given; the data lives in Parquet either way."""
    return duckdb.connect(str(db_path) if db_path else ":memory:")


def attach_observations(con: duckdb.DuckDBPyConnection, parquet_dir: Path) -> int:
    """Expose every year's Parquet as a single `observations` view."""
    files = sorted(parquet_dir.glob("gsod_*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"No Parquet in {parquet_dir}. Run scripts/build_warehouse.py first."
        )
    pattern = str(parquet_dir / "gsod_*.parquet").replace("\\", "/")
    con.execute(
        f"CREATE OR REPLACE VIEW observations AS "
        f"SELECT * FROM read_parquet('{pattern}')"
    )
    return len(files)


def table_stats(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT station), MIN(year), MAX(year) FROM observations"
    ).fetchone()
    return {
        "rows": int(row[0]),
        "stations": int(row[1]),
        "first_year": int(row[2]),
        "last_year": int(row[3]),
    }
