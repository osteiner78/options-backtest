"""Tests for runs_store: DB path anchoring and label-preservation on status update."""

import pytest
from pathlib import Path


class TestRunsStoreDBPath:
    """_DB_PATH must be anchored to project root, not CWD (Bug #7)."""

    def test_db_path_is_absolute(self):
        from straddle.runs_store import _DB_PATH
        assert _DB_PATH.is_absolute()

    def test_db_path_ends_with_data_runs_db(self):
        from straddle.runs_store import _DB_PATH
        assert _DB_PATH.parts[-1] == "runs.db"
        assert _DB_PATH.parts[-2] == "data"


class TestUpsertRunLabelPreservation:
    """upsert_run must not erase an existing label on status update (Bug #6)."""

    def test_label_preserved_on_status_update(self, tmp_path, monkeypatch):
        import straddle.runs_store as rs
        # Redirect the DB to a temp path so we don't pollute the real one
        monkeypatch.setattr(rs, "_DB_PATH", tmp_path / "test_runs.db")

        rs.init_db()
        rs.upsert_run("run-1", "pending", {}, label="my-label")
        rs.upsert_run("run-1", "running", {}, label=None)  # status update without label

        row = rs.get_run("run-1")
        assert row["label"] == "my-label", (
            "Label should be preserved when upsert_run is called with label=None"
        )

    def test_label_updated_when_explicitly_provided(self, tmp_path, monkeypatch):
        import straddle.runs_store as rs
        monkeypatch.setattr(rs, "_DB_PATH", tmp_path / "test_runs.db")

        rs.init_db()
        rs.upsert_run("run-2", "pending", {}, label="old-label")
        rs.upsert_run("run-2", "completed", {}, label="new-label")

        row = rs.get_run("run-2")
        assert row["label"] == "new-label"
