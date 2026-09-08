"""Every number in README.md and docs/DECISIONS.md must exist in reports/.

The whole premise of this repository is that a published table matched no
computation. Guarding against repeating that mistake belongs in the test suite,
not in good intentions.

Skipped when reports/ has not been generated yet, so a fresh clone can still run
`pytest` before downloading 434 MB.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _load(name: str) -> dict | None:
    path = REPORTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def metrics():
    analysis = _load("metrics_analysis.json")
    pushdown = _load("metrics_pushdown.json")
    if analysis is None or pushdown is None:
        pytest.skip("reports/ not generated; run scripts/run_analysis.py first")
    return analysis, pushdown


@pytest.fixture(scope="module")
def prose():
    return "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("README.md", "docs/DECISIONS.md")
    )


def thousands(n: int) -> str:
    return f"{n:,}"


class TestEventCountsAppearAsComputed:
    def test_every_event_count_is_quoted_correctly(self, metrics, prose):
        analysis, _ = metrics
        for row in analysis["event_counts"]:
            printed = thousands(row["occurrences"])
            assert printed in prose, (
                f"{row['event']} = {printed} is in reports but not in the prose"
            )

    def test_every_event_share_is_quoted_correctly(self, metrics, prose):
        analysis, _ = metrics
        for row in analysis["event_counts"]:
            share = f"{row['pct_of_station_days']:.2f}%"
            assert share in prose, f"{row['event']} share {share} missing from prose"

    def test_shares_do_not_sum_to_one_hundred(self, metrics, prose):
        analysis, _ = metrics
        total = sum(r["pct_of_station_days"] for r in analysis["event_counts"])
        assert f"{total:.2f}%" in prose
        assert abs(total - 100) > 1, "if these ever sum to 100 the write-up is wrong"


class TestWarehouseFiguresMatch:
    def test_row_and_station_counts(self, metrics, prose):
        analysis, _ = metrics
        assert thousands(analysis["warehouse"]["rows"]) in prose
        assert thousands(analysis["warehouse"]["stations"]) in prose

    def test_balanced_panel_size(self, metrics, prose):
        analysis, _ = metrics
        assert thousands(analysis["station_overlap"]["stations_every_year"]) in prose


class TestTemperatureFiguresMatch:
    def test_each_year_mean_is_quoted(self, metrics, prose):
        analysis, _ = metrics
        for row in analysis["annual_temperature"]:
            assert f"{row['mean_temp_c']:.3f}" in prose, (
                f"{int(row['year'])} mean {row['mean_temp_c']:.3f} missing from prose"
            )

    def test_the_two_panels_are_both_reported(self, metrics, prose):
        analysis, _ = metrics
        for row in analysis["annual_temperature_balanced_panel"]:
            assert f"{row['mean_temp_c']:.3f}" in prose

    def test_the_stated_gap_matches_the_data(self, metrics, prose):
        """The +0.114 C composition effect must be arithmetic, not assertion."""
        analysis, _ = metrics
        naive = {int(r["year"]): r["mean_temp_c"] for r in analysis["annual_temperature"]}
        panel = {int(r["year"]): r["mean_temp_c"]
                 for r in analysis["annual_temperature_balanced_panel"]}
        first, last = min(naive), max(naive)
        gap = (naive[last] - naive[first]) - (panel[last] - panel[first])
        assert f"{gap:.3f}" in prose, f"composition effect {gap:.3f} not stated"


class TestPushdownFiguresMatch:
    def test_each_arm_speedup_is_quoted(self, metrics, prose):
        _, pushdown = metrics
        for arm in pushdown["arms"]:
            assert f"{arm['speedup_vs_baseline']}×" in prose or \
                   f"{arm['speedup_vs_baseline']}x" in prose

    def test_arms_agreed(self, metrics):
        _, pushdown = metrics
        assert pushdown["all_arms_agree"], "the pushdown comparison is void"


class TestCrossCheckIsHonest:
    def test_the_quoted_worst_case_matches(self, metrics, prose):
        analysis, _ = metrics
        check = analysis["cross_check_vs_original_notebook"]
        assert f"{check['largest_relative_difference_pct']:.2f}%" in prose

    def test_all_differences_point_the_same_way(self, metrics):
        """The claim in the write-up is that every delta is positive."""
        analysis, _ = metrics
        deltas = [c["delta"] for c in
                  analysis["cross_check_vs_original_notebook"]["per_event"]]
        assert deltas and all(d > 0 for d in deltas)
