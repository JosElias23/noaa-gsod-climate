"""Tests for the BigQuery arm, most of which need no cloud account.

`sql/bigquery.sql` sat in this repository from the first commit with a comment
claiming it "returns the same six numbers", checked by eye and never executed.
Section 6 of `docs/DECISIONS.md` listed exactly that as the project's largest
hole. `scripts/run_bigquery.py` runs it; these tests are what stop the claim
drifting back into an assertion.

The first three run offline and on every push. The rest read
`reports/metrics_bigquery.json` and skip when it is absent, so CI stays
credential-free -- which is the same reason the published numbers come from
NCEI in the first place.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "sql" / "bigquery.sql"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_bigquery", ROOT / "scripts" / "run_bigquery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rbq():
    return _module()


class TestTheSqlFileItself:
    """No network needed: these are properties of the file on disk."""

    def test_it_parses_into_the_two_statements_it_documents(self, rbq):
        names = [rbq.label(s) for s in rbq.statements(SQL)]
        assert names == ["event_counts_2024", "monthly_events"]

    def test_it_never_selects_star(self):
        """The file's own argument is that naming columns is what costs less.

        A `SELECT *` here would be billed, not merely slow, and it would
        contradict the comment at the top of the file.
        """
        body = "\n".join(
            line for line in SQL.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("--")
        )
        assert "SELECT *" not in body.upper()

    def test_the_script_executes_the_file_rather_than_a_copy(self, rbq):
        """A duplicated query is one that can drift from the one on display.

        Checked on the distinctive lines rather than the first line, because
        every statement here starts with a bare `SELECT` and an assertion about
        that would pass whatever the script contained.
        """
        source = (ROOT / "scripts" / "run_bigquery.py").read_text(encoding="utf-8")
        assert 'PROJECT_ROOT / "sql" / "bigquery.sql"' in source

        distinctive = [
            line.strip()
            for statement in rbq.statements(SQL)
            for line in statement.splitlines()
            if "COUNTIF" in line or "EXTRACT" in line or "FROM" in line
        ]
        assert distinctive, "no distinctive lines found; this test is not testing"
        duplicated = [line for line in distinctive if line in source]
        assert not duplicated, (
            f"these lines from sql/bigquery.sql are inlined in the script and "
            f"can drift from the file a reader inspects: {duplicated[:3]}"
        )

    def test_pricing_is_linear_in_bytes_and_anchored_at_a_tebibyte(self, rbq):
        assert rbq.price(rbq.TIB) == pytest.approx(rbq.USD_PER_TIB_SCANNED)
        assert rbq.price(rbq.TIB // 2) == pytest.approx(
            rbq.USD_PER_TIB_SCANNED / 2, rel=1e-6)
        assert rbq.price(0) == 0


@pytest.fixture(scope="module")
def report():
    path = ROOT / "reports" / "metrics_bigquery.json"
    if not path.exists():
        pytest.skip("reports/metrics_bigquery.json not generated; "
                    "run scripts/run_bigquery.py with a GCP project")
    return json.loads(path.read_text(encoding="utf-8"))


class TestTheRun:
    def test_the_wasteful_arm_was_priced_and_not_paid_for(self, report):
        star = next(q for q in report["queries"] if q["name"] == "select_star")
        assert star["executed"] is False
        assert star["estimated_bytes_processed"] > 0

    def test_naming_columns_scans_less_than_selecting_everything(self, report):
        pruning = report["column_pruning"]
        assert pruning["six_flag_columns_bytes"] < pruning["select_star_bytes"]
        assert pruning["scan_ratio"] > 1

    def test_no_credential_or_project_id_is_recorded(self, report):
        """The report is committed, so it must carry nothing account-specific."""
        blob = json.dumps(report).lower()
        for forbidden in ("credential", "access_token", "private_key",
                          "client_secret", "refresh_token"):
            assert forbidden not in blob
        assert "project_id" not in blob


class TestAgreementWithTheArchive:
    """Two readers of the same NOAA product must produce the same counts."""

    @pytest.fixture(scope="class")
    def agreement(self, report):
        if "agreement_with_ncei" not in report:
            pytest.skip("the counts query was not executed in this run")
        return report["agreement_with_ncei"]

    def test_all_six_events_are_compared(self, agreement):
        assert len(agreement["rows"]) == 6

    def test_every_count_agrees_to_within_a_few_percent(self, agreement):
        """Not exact equality: NOAA keeps ingesting late station reports.

        Section 4 of docs/DECISIONS.md explains why an archive read later holds
        slightly more of 2024 than a query run earlier. A few percent is late
        data; a large disagreement would be a parse bug on one side.
        """
        for row in agreement["rows"]:
            assert abs(row["pct_difference"]) < 5.0, (
                f"{row['event']}: NCEI {row['ncei_archive']} vs BigQuery "
                f"{row['bigquery']} is {row['pct_difference']:+.2f}%, too far "
                f"apart to be late reports"
            )

    def test_the_counts_match_the_published_ones(self, agreement):
        """The NCEI side of the comparison must be what the README publishes."""
        local = json.loads(
            (ROOT / "reports" / "metrics_analysis.json").read_text(encoding="utf-8"))
        published = {row["event"]: row["occurrences"] for row in local["event_counts"]}
        for row in agreement["rows"]:
            assert row["ncei_archive"] == published[row["event"]]
