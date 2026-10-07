"""Persistent call cache keyed on (provider, model, params, prompt hash, sample index, attempt).

A rerun with the same configuration reads every completion from here and makes no API calls.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def cache_key(
    provider: str, model_id: str, params: dict[str, Any], prompt_hash: str, sample_index: int, attempt: int
) -> str:
    payload = json.dumps([provider, model_id, params, prompt_hash, sample_index, attempt], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class CallCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("CREATE TABLE IF NOT EXISTS calls (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT value FROM calls WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._conn.execute("INSERT OR REPLACE INTO calls VALUES (?, ?)", (key, json.dumps(value)))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
