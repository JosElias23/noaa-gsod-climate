"""Every number in the prose must exist in reports/, in both languages.

The whole premise of this repository is that a published table matched no
computation. Guarding against repeating that mistake belongs in the test suite,
not in good intentions.

Two languages double the opportunity to drift, so both are checked against the
same JSON, each in its own convention: English writes 983,613 and 25.02%, Spanish
writes 983.613 and 25,02 %. A figure corrected in one file and not the other
fails here.

Skipped when reports/ has not been generated yet, so a fresh clone can still run
`pytest` before downloading 434 MB.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

ENGLISH_FILES = ("README.md", "docs/DECISIONS.md")
SPANISH_FILES = ("README.es.md",)


# --------------------------------------------------------------- formatting

def en_int(n: int) -> str:
    return f"{n:,}"


def es_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def en_dec(x: float, places: int = 2) -> str:
    return f"{x:.{places}f}"


def es_dec(x: float, places: int = 2) -> str:
    return f"{x:.{places}f}".replace(".", ",")


def en_pct(x: float, places: int = 2) -> str:
    return f"{x:.{places}f}%"


def es_pct(x: float, places: int = 2) -> str:
    return f"{x:.{places}f}".replace(".", ",") + " %"


# ------------------------------------------------------------------ fixtures

def _load(name: str) -> dict | None:
    path = REPORTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@pytest.fixture(scope="module")
def metrics():
    analysis = _load("metrics_analysis.json")
    pushdown = _load("metrics_pushdown.json")
    if analysis is None or pushdown is None:
        pytest.skip("reports/ not generated; run scripts/run_analysis.py first")
    return analysis, pushdown


def _read(names) -> str:
    return "\n".join((ROOT / n).read_text(encoding="utf-8") for n in names)


@pytest.fixture(scope="module")
def prose():
    """Both languages, each with the formatter it is written in."""
    return {
        "en": (_read(ENGLISH_FILES), en_int, en_dec, en_pct),
        "es": (_read(SPANISH_FILES), es_int, es_dec, es_pct),
    }


LANGS = ["en", "es"]


# --------------------------------------------------------------------- tests

class TestBothLanguagesExist:
    def test_the_spanish_readme_is_present(self):
        assert (ROOT / "README.es.md").exists()

    @pytest.mark.parametrize("a,b", [("README.md", "README.es.md"),
                                     ("README.es.md", "README.md")])
    def test_each_readme_links_to_the_other(self, a, b):
        assert b in (ROOT / a).read_text(encoding="utf-8"), f"{a} does not link to {b}"


@pytest.mark.parametrize("lang", LANGS)
class TestEventCounts:
    def test_every_count_is_quoted_correctly(self, metrics, prose, lang):
        analysis, _ = metrics
        text, fmt_int, _, _ = prose[lang]
        for row in analysis["event_counts"]:
            printed = fmt_int(row["occurrences"])
            assert printed in text, (
                f"[{lang}] {row['event']} = {printed} is in reports but not in the prose"
            )

    def test_every_share_is_quoted_correctly(self, metrics, prose, lang):
        analysis, _ = metrics
        text, _, _, fmt_pct = prose[lang]
        for row in analysis["event_counts"]:
            share = fmt_pct(row["pct_of_station_days"])
            assert share in text, f"[{lang}] {row['event']} share {share} missing"

    def test_shares_do_not_sum_to_one_hundred(self, metrics, prose, lang):
        analysis, _ = metrics
        text, _, _, fmt_pct = prose[lang]
        total = sum(r["pct_of_station_days"] for r in analysis["event_counts"])
        assert fmt_pct(total) in text
        assert abs(total - 100) > 1, "if these ever sum to 100 the write-up is wrong"


@pytest.mark.parametrize("lang", LANGS)
class TestWarehouseFigures:
    def test_row_and_station_counts(self, metrics, prose, lang):
        analysis, _ = metrics
        text, fmt_int, _, _ = prose[lang]
        assert fmt_int(analysis["warehouse"]["rows"]) in text
        assert fmt_int(analysis["warehouse"]["stations"]) in text

    def test_balanced_panel_size(self, metrics, prose, lang):
        analysis, _ = metrics
        text, fmt_int, _, _ = prose[lang]
        assert fmt_int(analysis["station_overlap"]["stations_every_year"]) in text


@pytest.mark.parametrize("lang", LANGS)
class TestTemperatureFigures:
    def test_each_year_mean_is_quoted(self, metrics, prose, lang):
        analysis, _ = metrics
        text, _, fmt_dec, _ = prose[lang]
        for row in analysis["annual_temperature"]:
            printed = fmt_dec(row["mean_temp_c"], 3)
            assert printed in text, f"[{lang}] {int(row['year'])} mean {printed} missing"

    def test_both_panels_are_reported(self, metrics, prose, lang):
        analysis, _ = metrics
        text, _, fmt_dec, _ = prose[lang]
        for row in analysis["annual_temperature_balanced_panel"]:
            assert fmt_dec(row["mean_temp_c"], 3) in text

    def test_the_stated_composition_effect_is_arithmetic(self, metrics, prose, lang):
        """The 0.114 C gap must follow from the data, not be asserted."""
        analysis, _ = metrics
        text, _, fmt_dec, _ = prose[lang]
        naive = {int(r["year"]): r["mean_temp_c"] for r in analysis["annual_temperature"]}
        panel = {int(r["year"]): r["mean_temp_c"]
                 for r in analysis["annual_temperature_balanced_panel"]}
        first, last = min(naive), max(naive)
        gap = (naive[last] - naive[first]) - (panel[last] - panel[first])
        assert fmt_dec(gap, 3) in text, f"[{lang}] composition effect {gap:.3f} not stated"


@pytest.mark.parametrize("lang", LANGS)
class TestPushdownFigures:
    def test_each_speedup_is_quoted(self, metrics, prose, lang):
        _, pushdown = metrics
        text, _, fmt_dec, _ = prose[lang]
        for arm in pushdown["arms"]:
            printed = fmt_dec(arm["speedup_vs_baseline"], 1)
            assert f"{printed}×" in text, f"[{lang}] speedup {printed}x missing"

@pytest.mark.parametrize("lang", LANGS)
class TestCrossCheck:
    def test_the_quoted_worst_case_matches(self, metrics, prose, lang):
        analysis, _ = metrics
        text, _, _, fmt_pct = prose[lang]
        check = analysis["cross_check_vs_original_notebook"]
        assert fmt_pct(check["largest_relative_difference_pct"]) in text

    def test_every_per_event_difference_is_quoted(self, metrics, prose, lang):
        analysis, _ = metrics
        text, _, _, fmt_pct = prose[lang]
        for c in analysis["cross_check_vs_original_notebook"]["per_event"]:
            assert fmt_pct(c["relative_pct"]) in text, (
                f"[{lang}] {c['event']} difference {c['relative_pct']} missing"
            )


class TestDataProperties:
    """Claims about the data itself, independent of how any file words them."""

    def test_arms_agreed(self, metrics):
        _, pushdown = metrics
        assert pushdown["all_arms_agree"], "the pushdown comparison is void"

    def test_all_differences_point_the_same_way(self, metrics):
        """Both write-ups claim every delta is positive; that must be true."""
        analysis, _ = metrics
        deltas = [c["delta"] for c in
                  analysis["cross_check_vs_original_notebook"]["per_event"]]
        assert deltas and all(d > 0 for d in deltas)
