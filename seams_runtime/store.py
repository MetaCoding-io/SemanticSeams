"""SQLite persistence for process state and entities (stdlib sqlite3).

Two tables:

- ``workflow_state(instance_id PK, process, correlation_key, state, status, updated)``
  holds serialized Spiff workflows (``Engine.serialize`` output).
- ``entities(id PK, shape, correlation_key, instance_id, data JSON, status, created)``
  holds the payloads the worker persisted, keyed by their SHACL shape IRI.

Every operation opens and closes its own connection, so one ``Store`` can be
shared by coroutines and by the worker threads asyncio hands blocking calls to.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_state(
    instance_id TEXT PRIMARY KEY,
    process TEXT NOT NULL,
    correlation_key TEXT,
    state TEXT NOT NULL,
    status TEXT,
    updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS workflow_state_ck ON workflow_state(correlation_key);
CREATE TABLE IF NOT EXISTS entities(
    id TEXT PRIMARY KEY,
    shape TEXT NOT NULL,
    correlation_key TEXT,
    instance_id TEXT,
    data TEXT NOT NULL,
    status TEXT,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS entities_shape_ck ON entities(shape, correlation_key);
"""


class Store:
    def __init__(self, path, timeout: float = 30.0):
        self.path = Path(path)
        self.timeout = timeout
        with closing(self._connect()) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=self.timeout)
        con.row_factory = sqlite3.Row
        return con

    def _write(self, sql: str, params: tuple) -> None:
        with closing(self._connect()) as con, con:
            con.execute(sql, params)

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with closing(self._connect()) as con:
            return con.execute(sql, params).fetchall()

    # ── workflow state ──

    def save_state(self, instance_id: str, process, state: str, *,
                   correlation_key: str | None = None, status: str | None = None) -> None:
        self._write(
            "INSERT OR REPLACE INTO workflow_state VALUES (?, ?, ?, ?, ?, ?)",
            (str(instance_id), str(process), correlation_key, state, status, time.time()),
        )
        log.debug("saved workflow %s (%s, %d bytes, status=%s)", instance_id, process, len(state), status)

    def load_state(self, instance_id: str) -> str:
        rows = self._read("SELECT state FROM workflow_state WHERE instance_id = ?", (str(instance_id),))
        if not rows:
            raise LookupError(f"no workflow_state row for instance {instance_id} in {self.path}")
        return rows[0]["state"]

    def list_instances(self, correlation_key: str | None = None) -> list[dict]:
        """Instance metadata (no state), oldest update first."""
        sql = "SELECT instance_id, process, correlation_key, status, updated FROM workflow_state"
        params: tuple = ()
        if correlation_key is not None:
            sql += " WHERE correlation_key = ?"
            params = (correlation_key,)
        return [dict(r) for r in self._read(sql + " ORDER BY updated, rowid", params)]

    # ── entities ──

    def put_entity(self, id: str, shape, data: dict, *, correlation_key: str | None = None,
                   instance_id: str | None = None, status: str | None = None) -> dict:
        """Insert or update an entity. An update keeps the original ``created``."""
        payload = json.dumps(data, sort_keys=True)
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT INTO entities(id, shape, correlation_key, instance_id, data, status, created) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "shape = excluded.shape, correlation_key = excluded.correlation_key, "
                "instance_id = excluded.instance_id, data = excluded.data, status = excluded.status",
                (str(id), str(shape), correlation_key, instance_id, payload, status, time.time()),
            )
        return self.get_entity(id)

    def get_entity(self, id: str) -> dict | None:
        rows = self._read("SELECT * FROM entities WHERE id = ?", (str(id),))
        return _entity(rows[0]) if rows else None

    def query(self, shape, **filters) -> list[dict]:
        """Entities of ``shape`` ordered by created. ``correlation_key=`` matches
        the column; every other filter matches a top-level key of ``data``."""
        sql = "SELECT * FROM entities WHERE shape = ?"
        params: list = [str(shape)]
        if "correlation_key" in filters:
            sql += " AND correlation_key = ?"
            params.append(filters.pop("correlation_key"))
        rows = [_entity(r) for r in self._read(sql + " ORDER BY created, rowid", tuple(params))]
        return [e for e in rows
                if all(k in e["data"] and e["data"][k] == v for k, v in filters.items())]


def _entity(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["data"] = json.loads(out["data"])
    return out
