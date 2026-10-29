"""SQLite persistence for process state and entities (stdlib sqlite3).

Three tables:

- ``workflow_state(instance_id PK, process, correlation_key, state, status, updated)``
  holds serialized Spiff workflows (``Engine.serialize`` output).
- ``entities(id PK, shape, correlation_key, instance_id, data JSON, status, created)``
  holds the payloads the worker persisted, keyed by their SHACL shape IRI.
- ``user_tasks(instance_id, task, bpmn_id, process, correlation_key, created)``
  holds one row per open BPMN user task (ADR-0009). The worker replaces an
  instance's rows at every checkpoint, so they are empty once it ends.

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
CREATE TABLE IF NOT EXISTS user_tasks(
    instance_id TEXT NOT NULL,
    task TEXT NOT NULL,
    bpmn_id TEXT NOT NULL,
    process TEXT NOT NULL,
    correlation_key TEXT,
    created REAL NOT NULL,
    PRIMARY KEY (instance_id, task)
);
CREATE INDEX IF NOT EXISTS user_tasks_task_ck ON user_tasks(task, correlation_key);
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

    def get_instance(self, instance_id: str) -> dict | None:
        """Instance metadata (no state), or None."""
        rows = self._read("SELECT instance_id, process, correlation_key, status, updated "
                          "FROM workflow_state WHERE instance_id = ?", (str(instance_id),))
        return dict(rows[0]) if rows else None

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

    # ── open user tasks ──

    def replace_user_tasks(self, instance_id: str, rows) -> None:
        """Make ``rows`` (dicts with task, bpmn_id, process, correlation_key)
        the instance's open user tasks. A task that was already open keeps
        its ``created``; an empty ``rows`` clears the instance."""
        instance_id = str(instance_id)
        now = time.time()
        with closing(self._connect()) as con, con:
            created = {r["task"]: r["created"] for r in con.execute(
                "SELECT task, created FROM user_tasks WHERE instance_id = ?", (instance_id,))}
            con.execute("DELETE FROM user_tasks WHERE instance_id = ?", (instance_id,))
            con.executemany(
                "INSERT INTO user_tasks(instance_id, task, bpmn_id, process, correlation_key, created) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(instance_id, str(r["task"]), str(r["bpmn_id"]), str(r["process"]),
                  r.get("correlation_key"), created.get(str(r["task"]), now)) for r in rows],
            )

    def list_user_tasks(self) -> list[dict]:
        """Every open user task, oldest first."""
        return [dict(r) for r in self._read("SELECT * FROM user_tasks ORDER BY created, rowid")]

    def get_user_task(self, task_iri, correlation_key: str) -> dict | None:
        """The open row of ``task_iri`` for ``correlation_key`` (the newest
        when several instances share the key), or None."""
        rows = self._read("SELECT * FROM user_tasks WHERE task = ? AND correlation_key = ? "
                          "ORDER BY created DESC, rowid DESC LIMIT 1", (str(task_iri), correlation_key))
        return dict(rows[0]) if rows else None


def _entity(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["data"] = json.loads(out["data"])
    return out
