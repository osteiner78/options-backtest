"""SQLite persistence layer for backtest run history."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DB_PATH = Path("data/runs.db")


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id      TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL,
                status      TEXT NOT NULL,
                label       TEXT,
                params_json TEXT,
                result_json TEXT
            )
        """)
        conn.commit()


def upsert_run(run_id: str, status: str, params: dict, result: Optional[dict] = None, label: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO runs (run_id, created_at, status, label, params_json, result_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status      = excluded.status,
                label       = excluded.label,
                params_json = excluded.params_json,
                result_json = excluded.result_json
        """, (
            run_id,
            datetime.now(timezone.utc).isoformat(),
            status,
            label,
            json.dumps(params),
            json.dumps(result) if result is not None else None,
        ))
        conn.commit()


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT run_id, created_at, status, label, params_json FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [
        {
            "run_id": r["run_id"],
            "created_at": r["created_at"],
            "status": r["status"],
            "label": r["label"],
            "params": json.loads(r["params_json"]) if r["params_json"] else {},
        }
        for r in rows
    ]


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    result = json.loads(row["result_json"]) if row["result_json"] else None
    return {
        "run_id": row["run_id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "label": row["label"],
        "params": json.loads(row["params_json"]) if row["params_json"] else {},
        "result": result,
    }


def delete_run(run_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()
    return cur.rowcount > 0


def patch_label(run_id: str, label: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("UPDATE runs SET label = ? WHERE run_id = ?", (label, run_id))
        conn.commit()
    return cur.rowcount > 0
