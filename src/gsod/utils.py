"""Paths, config, logging and JSON reporting.

Every number this repository publishes is written here as JSON, so a claim in
the README can always be traced back to the run that produced it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("gsod")


def load_config(path: str | Path = "configs/default.yaml") -> dict:
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def save_json(payload: Any, path: str | Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return path


def human_bytes(n: float) -> str:
    """Binary units, labelled as binary units.

    This divided by 1024 and printed "MB" until the BigQuery arm arrived, which
    prices bytes per **TiB**. A reader checking 68.0 MB against a per-TB rate
    would have got a different answer than the one published, for no better
    reason than a loose label. Powers of 1024 are KiB/MiB/GiB/TiB, so that is
    what they now say.
    """
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"
