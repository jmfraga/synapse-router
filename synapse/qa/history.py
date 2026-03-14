"""QA history — store and query test results in SQLite for regression tracking."""

import datetime
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "synapse_qa.db"


def _get_db() -> sqlite3.Connection:
    """Get QA history database connection, creating tables if needed."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS qa_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            route_filter TEXT DEFAULT '',
            total INTEGER NOT NULL,
            passed INTEGER NOT NULL,
            failed INTEGER NOT NULL,
            errors INTEGER NOT NULL,
            accuracy REAL NOT NULL,
            avg_quality REAL,
            avg_latency_ms INTEGER,
            total_cost REAL DEFAULT 0,
            report_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.commit()
    return db


def save_run(
    run_type: str,
    route_filter: str,
    report: dict,
) -> int:
    """Save a QA run to history. Returns the run ID."""
    db = _get_db()
    s = report["summary"]

    cursor = db.execute(
        """INSERT INTO qa_runs
           (run_type, route_filter, total, passed, failed, errors,
            accuracy, avg_quality, avg_latency_ms, total_cost, report_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_type,
            route_filter,
            s.get("total", 0),
            s.get("passed", s.get("routing_correct", 0)),
            s.get("failed", s.get("total", 0) - s.get("routing_correct", s.get("passed", 0))),
            s.get("errors", 0),
            s.get("accuracy", s.get("routing_accuracy", 0)),
            s.get("avg_quality"),
            s.get("avg_latency_ms", 0),
            s.get("total_cost", 0),
            json.dumps(report, ensure_ascii=False),
        ),
    )
    db.commit()
    run_id = cursor.lastrowid
    db.close()
    return run_id


def get_history(
    run_type: str = "",
    route_filter: str = "",
    limit: int = 20,
) -> list[dict]:
    """Get recent QA runs from history."""
    db = _get_db()
    query = "SELECT * FROM qa_runs WHERE 1=1"
    params = []

    if run_type:
        query += " AND run_type = ?"
        params.append(run_type)
    if route_filter:
        query += " AND route_filter = ?"
        params.append(route_filter)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    db.close()

    return [
        {
            "id": r["id"],
            "run_type": r["run_type"],
            "route_filter": r["route_filter"],
            "total": r["total"],
            "passed": r["passed"],
            "accuracy": r["accuracy"],
            "avg_quality": r["avg_quality"],
            "avg_latency_ms": r["avg_latency_ms"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def get_regression(
    run_type: str,
    route_filter: str = "",
) -> dict | None:
    """Compare latest run with previous run. Returns regression info or None."""
    history = get_history(run_type=run_type, route_filter=route_filter, limit=2)
    if len(history) < 2:
        return None

    current = history[0]
    previous = history[1]

    delta_accuracy = current["accuracy"] - previous["accuracy"]
    delta_quality = None
    if current["avg_quality"] is not None and previous["avg_quality"] is not None:
        delta_quality = round(current["avg_quality"] - previous["avg_quality"], 2)

    return {
        "current_run": current["id"],
        "previous_run": previous["id"],
        "current_accuracy": current["accuracy"],
        "previous_accuracy": previous["accuracy"],
        "delta_accuracy": round(delta_accuracy, 1),
        "current_quality": current["avg_quality"],
        "previous_quality": previous["avg_quality"],
        "delta_quality": delta_quality,
        "regression": delta_accuracy < -5,  # Flag if accuracy dropped >5%
        "current_date": current["created_at"],
        "previous_date": previous["created_at"],
    }
