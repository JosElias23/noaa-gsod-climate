"""Download the NCEI yearly archives and convert them to Parquet.

    python scripts/build_warehouse.py
    python scripts/build_warehouse.py --years 2024

About 100 MB per year over the wire and roughly 20 seconds per year to parse.
Both the archives and the Parquet are cached, so this is a one-off.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gsod.data import download_year, read_archive, sha256_of, write_parquet  # noqa: E402
from gsod.utils import (  # noqa: E402
    PROJECT_ROOT,
    human_bytes,
    load_config,
    save_json,
    setup_logging,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="+", default=None,
                        help="Override the years in configs/default.yaml")
    parser.add_argument("--force", action="store_true",
                        help="Re-parse even if the Parquet already exists")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log = setup_logging()
    config = load_config()

    years = args.years or config["data"]["years"]
    cache_dir = PROJECT_ROOT / config["data"]["cache_dir"]
    parquet_dir = PROJECT_ROOT / config["data"]["parquet_dir"]
    parquet_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for year in years:
        target = parquet_dir / f"gsod_{year}.parquet"
        if target.exists() and not args.force:
            # Still checksum the archive. Skipping it on the cached path was how
            # the load-bearing year ended up in the manifest with no provenance
            # at all: re-running for a year already converted recorded a size and
            # nothing else. If the archive is gone the entry says so explicitly
            # rather than silently omitting the field.
            entry = {"year": year, "parquet": target.name,
                     "parquet_bytes": target.stat().st_size, "cached": True}
            archive_path = cache_dir / f"{year}.tar.gz"
            if archive_path.exists():
                entry["size_bytes"] = archive_path.stat().st_size
                entry["sha256"] = sha256_of(archive_path)
                entry["file"] = archive_path.name
            else:
                entry["sha256"] = None
                entry["provenance_note"] = (
                    "Parquet present but the source archive is no longer cached; "
                    "re-run with --force to restore a verified checksum."
                )
            log.info("%d  cached (%s, sha256 %s)", year,
                     human_bytes(target.stat().st_size),
                     (entry["sha256"] or "unavailable")[:12])
            manifest.append(entry)
            continue

        started = time.time()
        archive = download_year(year, cache_dir)
        log.info("%d  downloaded %s  sha256 %s...",
                 year, human_bytes(archive.size_bytes), archive.sha256[:12])

        frame = read_archive(archive)
        write_parquet(frame, target)
        log.info("%d  %s rows from %s stations -> %s in %.0fs",
                 year, f"{len(frame):,}", f"{frame['station'].nunique():,}",
                 human_bytes(target.stat().st_size), time.time() - started)

        manifest.append({
            **archive.summary(),
            "rows": int(len(frame)),
            "stations": int(frame["station"].nunique()),
            "parquet": target.name,
            "parquet_bytes": target.stat().st_size,
            "cached": False,
        })

    # Merge rather than overwrite. Running this once for 2024 and then again for
    # 2020-2023 replaced the first manifest with the second, and the year that
    # produces every headline number was left with no recorded checksum while the
    # README claimed otherwise. Provenance that a second invocation can silently
    # delete is not provenance.
    existing = PROJECT_ROOT / "reports" / "data_manifest.json"
    merged = {}
    if existing.exists():
        for entry in json.loads(existing.read_text(encoding="utf-8")).get("archives", []):
            merged[entry["year"]] = entry
    for entry in manifest:
        merged[entry["year"]] = entry

    save_json({"source": "NCEI global-summary-of-the-day archive",
               "years": sorted(merged),
               "archives": [merged[y] for y in sorted(merged)]},
              "reports/data_manifest.json")
    log.info("wrote reports/data_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
