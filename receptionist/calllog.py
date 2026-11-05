from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class CallLog:
    """Every call and every tool call, in SQLite. One row per call, one row per tool event,
    plus one row per webhook delivery so Retell's retries are only handled once."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(
            """CREATE TABLE IF NOT EXISTS calls (
                call_id TEXT PRIMARY KEY, kind TEXT, caller TEXT, started_at TEXT, ended_at TEXT,
                ended_reason TEXT, duration_seconds REAL, cost REAL, summary TEXT, transcript TEXT,
                outcome TEXT, handover INTEGER DEFAULT 0, updated_utc TEXT,
                analysis_summary TEXT, sentiment TEXT, summary_emailed INTEGER DEFAULT 0);
               CREATE TABLE IF NOT EXISTS webhook_events (
                call_id TEXT, event TEXT, at_utc TEXT, PRIMARY KEY (call_id, event));
               CREATE TABLE IF NOT EXISTS tool_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT, tool TEXT, arguments TEXT,
                result TEXT, at_utc TEXT);"""
        )
        self._db.commit()

    def _upsert(self, call_id: str, **fields: Any) -> None:
        fields["updated_utc"] = datetime.now(timezone.utc).isoformat()
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{k}=COALESCE(excluded.{k}, calls.{k})" for k in fields)
        with self._lock:
            self._db.execute(
                f"INSERT INTO calls (call_id, {cols}) VALUES (?, {marks}) ON CONFLICT(call_id) DO UPDATE SET {updates}",
                [call_id, *fields.values()],
            )
            self._db.commit()

    def tool_event(self, call_id: Optional[str], tool: str, arguments: Dict[str, Any], result: str) -> None:
        with self._lock:
            if call_id:
                self._db.execute("INSERT OR IGNORE INTO calls (call_id, updated_utc) VALUES (?, ?)",
                                 (call_id, datetime.now(timezone.utc).isoformat()))
            self._db.execute(
                "INSERT INTO tool_events (call_id, tool, arguments, result, at_utc) VALUES (?,?,?,?,?)",
                (call_id, tool, json.dumps(arguments), result, datetime.now(timezone.utc).isoformat()),
            )
            self._db.commit()

    def first_delivery(self, call_id: str, event: str) -> bool:
        """Retell retries a webhook up to 3 times if it doesn't get a 2xx in 10 seconds.
        True the first time (call_id, event) is seen, False for every repeat."""
        with self._lock:
            cur = self._db.execute("INSERT OR IGNORE INTO webhook_events VALUES (?,?,?)",
                                   (call_id, event, datetime.now(timezone.utc).isoformat()))
            self._db.commit()
            return cur.rowcount == 1

    def get(self, call_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._db.execute("SELECT * FROM calls WHERE call_id=?", (call_id,))
            row = cur.fetchone()
            return dict(zip([c[0] for c in cur.description], row)) if row else None

    def call_seen(self, call_id: str, kind: Optional[str], caller: Optional[str]) -> None:
        self._upsert(call_id, kind=kind, caller=caller)

    def mark(self, call_id: str, **fields: Any) -> None:
        self._upsert(call_id, **fields)

    def end_of_call(self, call_id: str, report: Dict[str, Any]) -> None:
        self._upsert(call_id, **report)

    def calls(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._db.execute("SELECT * FROM calls ORDER BY COALESCE(started_at, updated_utc) DESC LIMIT ?", (limit,))
            cols = [c[0] for c in cur.description]
            calls = [dict(zip(cols, r)) for r in cur.fetchall()]
            for c in calls:
                ev = self._db.execute(
                    "SELECT tool, arguments, result, at_utc FROM tool_events WHERE call_id=? ORDER BY id", (c["call_id"],))
                c["tool_events"] = [dict(zip(["tool", "arguments", "result", "at_utc"], r)) for r in ev.fetchall()]
        return calls
