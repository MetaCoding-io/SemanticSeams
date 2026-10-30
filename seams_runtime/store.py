"""Persistence for process state and entities: one ``Store`` interface, two backends.

Three tables:

- ``workflow_state(instance_id PK, process, correlation_key, state, status, updated)``
  holds serialized Spiff workflows (``Engine.serialize`` output).
- ``entities(id PK, shape, correlation_key, instance_id, data JSON, status, created)``
  holds the payloads the worker persisted, keyed by their SHACL shape IRI.
- ``user_tasks(instance_id, task, bpmn_id, process, correlation_key, created)``
  holds one row per open BPMN user task (ADR-0009). The worker replaces an
  instance's rows at every checkpoint, so they are empty once it ends.

``SQLiteStore`` keeps them in an embedded SQLite file (stdlib sqlite3).
``PostgresStore`` keeps them in PostgreSQL (psycopg 3): ``data`` is jsonb, the
timestamps are double precision and a ``seq bigserial`` column stands in for
SQLite's rowid as the insertion-order tie-breaker. Both return the same rows.

Every operation opens and closes its own connection, so one store can be
shared by coroutines and by the worker threads asyncio hands blocking calls to.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

log = logging.getLogger(__name__)

_INSTANCE_COLUMNS = "instance_id, process, correlation_key, status, updated"
_ENTITY_COLUMNS = "id, shape, correlation_key, instance_id, data, status, created"
_USER_TASK_COLUMNS = "instance_id, task, bpmn_id, process, correlation_key, created"


@runtime_checkable
class Store(Protocol):
    """What the runtime needs from persistence. ``kind`` is ``"sqlite"`` or
    ``"postgresql"``; ``location`` is a file path or a password-redacted URL."""

    kind: str
    location: str

    def save_state(
        self, instance_id: str, process, state: str, *, correlation_key: str | None = None, status: str | None = None
    ) -> None: ...

    def load_state(self, instance_id: str) -> str: ...

    def get_instance(self, instance_id: str) -> dict | None: ...

    def list_instances(self, correlation_key: str | None = None) -> list[dict]: ...

    def put_entity(
        self,
        id: str,
        shape,
        data: dict,
        *,
        correlation_key: str | None = None,
        instance_id: str | None = None,
        status: str | None = None,
    ) -> dict: ...

    def get_entity(self, id: str) -> dict | None: ...

    def query(self, shape, **filters) -> list[dict]: ...

    def replace_user_tasks(self, instance_id: str, rows) -> None: ...

    def list_user_tasks(self) -> list[dict]: ...

    def get_user_task(self, task_iri, correlation_key: str) -> dict | None: ...


def redact(url: str) -> str:
    """``url`` with any password replaced by ``***``: the userinfo password of
    a URL, a ``password`` query parameter, or a libpq ``password=`` keyword."""
    if "://" not in url:
        return re.sub(r"(\bpassword\s*=\s*)('(?:[^'\\]|\\.)*'|\S+)", r"\1***", url)
    parts = urlsplit(url)
    netloc = parts.netloc
    if parts.password is not None:
        userinfo, _, hostport = netloc.rpartition("@")
        user = userinfo.split(":", 1)[0]
        netloc = f"{user}:***@{hostport}"
    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        if any(k == "password" for k, _ in pairs):
            query = urlencode([(k, "***" if k == "password" else v) for k, v in pairs], safe="*")
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _match(entities: list[dict], filters: dict) -> list[dict]:
    """The data filters of ``query``, applied in Python so both backends agree."""
    return [e for e in entities if all(k in e["data"] and e["data"][k] == v for k, v in filters.items())]


def _task_rows(instance_id: str, rows, created: dict, now: float) -> list[tuple]:
    return [
        (
            instance_id,
            str(r["task"]),
            str(r["bpmn_id"]),
            str(r["process"]),
            r.get("correlation_key"),
            created.get(str(r["task"]), now),
        )
        for r in rows
    ]


# ── SQLite ───────────────────────────────────────────────────────────────────

_SQLITE_SCHEMA = """
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


class SQLiteStore:
    kind = "sqlite"

    def __init__(self, path, timeout: float = 30.0):
        self.path = Path(path)
        self.location = str(self.path)
        self.timeout = timeout
        with closing(self._connect()) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_SQLITE_SCHEMA)

    def __repr__(self) -> str:
        return f"SQLiteStore({self.location!r})"

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

    def save_state(
        self, instance_id: str, process, state: str, *, correlation_key: str | None = None, status: str | None = None
    ) -> None:
        self._write(
            "INSERT OR REPLACE INTO workflow_state VALUES (?, ?, ?, ?, ?, ?)",
            (str(instance_id), str(process), correlation_key, state, status, time.time()),
        )
        log.debug("saved workflow %s (%s, %d bytes, status=%s)", instance_id, process, len(state), status)

    def load_state(self, instance_id: str) -> str:
        rows = self._read("SELECT state FROM workflow_state WHERE instance_id = ?", (str(instance_id),))
        if not rows:
            raise LookupError(f"no workflow_state row for instance {instance_id} in {self.location}")
        return rows[0]["state"]

    def get_instance(self, instance_id: str) -> dict | None:
        """Instance metadata (no state), or None."""
        rows = self._read(
            f"SELECT {_INSTANCE_COLUMNS} FROM workflow_state WHERE instance_id = ?",
            (str(instance_id),),
        )
        return dict(rows[0]) if rows else None

    def list_instances(self, correlation_key: str | None = None) -> list[dict]:
        """Instance metadata (no state), oldest update first."""
        sql = f"SELECT {_INSTANCE_COLUMNS} FROM workflow_state"
        params: tuple = ()
        if correlation_key is not None:
            sql += " WHERE correlation_key = ?"
            params = (correlation_key,)
        return [dict(r) for r in self._read(sql + " ORDER BY updated, rowid", params)]

    # ── entities ──

    def put_entity(
        self,
        id: str,
        shape,
        data: dict,
        *,
        correlation_key: str | None = None,
        instance_id: str | None = None,
        status: str | None = None,
    ) -> dict:
        """Insert or update an entity. An update keeps the original ``created``."""
        payload = json.dumps(data, sort_keys=True)
        with closing(self._connect()) as con, con:
            con.execute(
                f"INSERT INTO entities({_ENTITY_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "shape = excluded.shape, correlation_key = excluded.correlation_key, "
                "instance_id = excluded.instance_id, data = excluded.data, status = excluded.status",
                (str(id), str(shape), correlation_key, instance_id, payload, status, time.time()),
            )
        return self.get_entity(id)

    def get_entity(self, id: str) -> dict | None:
        rows = self._read(f"SELECT {_ENTITY_COLUMNS} FROM entities WHERE id = ?", (str(id),))
        return _sqlite_entity(rows[0]) if rows else None

    def query(self, shape, **filters) -> list[dict]:
        """Entities of ``shape`` ordered by created. ``correlation_key=`` matches
        the column; every other filter matches a top-level key of ``data``."""
        sql = f"SELECT {_ENTITY_COLUMNS} FROM entities WHERE shape = ?"
        params: list = [str(shape)]
        if "correlation_key" in filters:
            sql += " AND correlation_key = ?"
            params.append(filters.pop("correlation_key"))
        rows = [_sqlite_entity(r) for r in self._read(sql + " ORDER BY created, rowid", tuple(params))]
        return _match(rows, filters)

    # ── open user tasks ──

    def replace_user_tasks(self, instance_id: str, rows) -> None:
        """Make ``rows`` (dicts with task, bpmn_id, process, correlation_key)
        the instance's open user tasks. A task that was already open keeps
        its ``created``; an empty ``rows`` clears the instance."""
        instance_id = str(instance_id)
        now = time.time()
        with closing(self._connect()) as con, con:
            created = {
                r["task"]: r["created"]
                for r in con.execute("SELECT task, created FROM user_tasks WHERE instance_id = ?", (instance_id,))
            }
            con.execute("DELETE FROM user_tasks WHERE instance_id = ?", (instance_id,))
            con.executemany(
                f"INSERT INTO user_tasks({_USER_TASK_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                _task_rows(instance_id, rows, created, now),
            )

    def list_user_tasks(self) -> list[dict]:
        """Every open user task, oldest first."""
        return [dict(r) for r in self._read(f"SELECT {_USER_TASK_COLUMNS} FROM user_tasks ORDER BY created, rowid")]

    def get_user_task(self, task_iri, correlation_key: str) -> dict | None:
        """The open row of ``task_iri`` for ``correlation_key`` (the newest
        when several instances share the key), or None."""
        rows = self._read(
            f"SELECT {_USER_TASK_COLUMNS} FROM user_tasks WHERE task = ? AND correlation_key = ? "
            "ORDER BY created DESC, rowid DESC LIMIT 1",
            (str(task_iri), correlation_key),
        )
        return dict(rows[0]) if rows else None


def _sqlite_entity(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["data"] = json.loads(out["data"])
    return out


# ── PostgreSQL ───────────────────────────────────────────────────────────────

_POSTGRES_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS workflow_state(
    seq BIGSERIAL NOT NULL,
    instance_id TEXT PRIMARY KEY,
    process TEXT NOT NULL,
    correlation_key TEXT,
    state TEXT NOT NULL,
    status TEXT,
    updated DOUBLE PRECISION NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS workflow_state_ck ON workflow_state(correlation_key)",
    """CREATE TABLE IF NOT EXISTS entities(
    seq BIGSERIAL NOT NULL,
    id TEXT PRIMARY KEY,
    shape TEXT NOT NULL,
    correlation_key TEXT,
    instance_id TEXT,
    data JSONB NOT NULL,
    status TEXT,
    created DOUBLE PRECISION NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS entities_shape_ck ON entities(shape, correlation_key)",
    """CREATE TABLE IF NOT EXISTS user_tasks(
    seq BIGSERIAL NOT NULL,
    instance_id TEXT NOT NULL,
    task TEXT NOT NULL,
    bpmn_id TEXT NOT NULL,
    process TEXT NOT NULL,
    correlation_key TEXT,
    created DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (instance_id, task)
)""",
    "CREATE INDEX IF NOT EXISTS user_tasks_task_ck ON user_tasks(task, correlation_key)",
)

# Serialises schema creation across runtimes starting together on one database:
# concurrent CREATE TABLE IF NOT EXISTS can still collide in the catalog.
_SCHEMA_LOCK = 0x5EA35


class PostgresStore:
    kind = "postgresql"

    def __init__(self, url: str, *, schema: str | None = None, connect_timeout: int = 10):
        import psycopg  # the binary wheel is a runtime dependency; imported here so SQLite-only use never loads it
        from psycopg import sql
        from psycopg.rows import dict_row

        self._psycopg, self._sql, self._dict_row = psycopg, sql, dict_row
        self.url = url
        self.schema = schema
        self.connect_timeout = connect_timeout
        self.location = redact(url) + (f" (schema {schema})" if schema else "")
        with self._connect(create_schema=True) as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK,))
            for statement in _POSTGRES_SCHEMA:
                con.execute(statement)
        log.info("postgresql store ready at %s", self.location)

    def __repr__(self) -> str:
        return f"PostgresStore({self.location!r})"

    def _connect(self, *, create_schema: bool = False):
        """A connection whose ``with`` block is one transaction (committed on
        success, rolled back on error) and which is closed afterwards."""
        try:
            con = self._psycopg.connect(self.url, connect_timeout=self.connect_timeout, row_factory=self._dict_row)
        except self._psycopg.OperationalError as exc:
            log.error("cannot connect to postgresql store %s: %s", self.location, exc)
            raise
        if self.schema is not None:
            name = self._sql.Identifier(self.schema)
            try:
                if create_schema:
                    con.execute(self._sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(name))
                con.execute(self._sql.SQL("SET search_path TO {}").format(name))
            except BaseException:
                con.close()
                raise
        return con

    def _read(self, query: str, params: tuple = ()) -> list[dict]:
        with self._connect() as con:
            return con.execute(query, params).fetchall()

    # ── workflow state ──

    def save_state(
        self, instance_id: str, process, state: str, *, correlation_key: str | None = None, status: str | None = None
    ) -> None:
        # seq = DEFAULT mirrors SQLite's INSERT OR REPLACE, which gives the row a new rowid.
        with self._connect() as con:
            con.execute(
                "INSERT INTO workflow_state(instance_id, process, correlation_key, state, status, updated) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (instance_id) DO UPDATE SET "
                "process = excluded.process, correlation_key = excluded.correlation_key, state = excluded.state, "
                "status = excluded.status, updated = excluded.updated, seq = DEFAULT",
                (str(instance_id), str(process), correlation_key, state, status, time.time()),
            )
        log.debug("saved workflow %s (%s, %d bytes, status=%s)", instance_id, process, len(state), status)

    def load_state(self, instance_id: str) -> str:
        rows = self._read("SELECT state FROM workflow_state WHERE instance_id = %s", (str(instance_id),))
        if not rows:
            raise LookupError(f"no workflow_state row for instance {instance_id} in {self.location}")
        return rows[0]["state"]

    def get_instance(self, instance_id: str) -> dict | None:
        """Instance metadata (no state), or None."""
        rows = self._read(f"SELECT {_INSTANCE_COLUMNS} FROM workflow_state WHERE instance_id = %s", (str(instance_id),))
        return rows[0] if rows else None

    def list_instances(self, correlation_key: str | None = None) -> list[dict]:
        """Instance metadata (no state), oldest update first."""
        query = f"SELECT {_INSTANCE_COLUMNS} FROM workflow_state"
        params: tuple = ()
        if correlation_key is not None:
            query += " WHERE correlation_key = %s"
            params = (correlation_key,)
        return self._read(query + " ORDER BY updated, seq", params)

    # ── entities ──

    def put_entity(
        self,
        id: str,
        shape,
        data: dict,
        *,
        correlation_key: str | None = None,
        instance_id: str | None = None,
        status: str | None = None,
    ) -> dict:
        """Insert or update an entity. An update keeps the original ``created``."""
        payload = json.dumps(data, sort_keys=True)
        with self._connect() as con:
            con.execute(
                f"INSERT INTO entities({_ENTITY_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s) ON CONFLICT (id) DO UPDATE SET "
                "shape = excluded.shape, correlation_key = excluded.correlation_key, "
                "instance_id = excluded.instance_id, data = excluded.data, status = excluded.status",
                (str(id), str(shape), correlation_key, instance_id, payload, status, time.time()),
            )
        return self.get_entity(id)

    def get_entity(self, id: str) -> dict | None:
        rows = self._read(f"SELECT {_ENTITY_COLUMNS} FROM entities WHERE id = %s", (str(id),))
        return _postgres_entity(rows[0]) if rows else None

    def query(self, shape, **filters) -> list[dict]:
        """Entities of ``shape`` ordered by created. ``correlation_key=`` matches
        the column; every other filter matches a top-level key of ``data``."""
        query = f"SELECT {_ENTITY_COLUMNS} FROM entities WHERE shape = %s"
        params: list = [str(shape)]
        if "correlation_key" in filters:
            query += " AND correlation_key = %s"
            params.append(filters.pop("correlation_key"))
        rows = [_postgres_entity(r) for r in self._read(query + " ORDER BY created, seq", tuple(params))]
        return _match(rows, filters)

    # ── open user tasks ──

    def replace_user_tasks(self, instance_id: str, rows) -> None:
        """Make ``rows`` (dicts with task, bpmn_id, process, correlation_key)
        the instance's open user tasks. A task that was already open keeps
        its ``created``; an empty ``rows`` clears the instance."""
        instance_id = str(instance_id)
        now = time.time()
        with self._connect() as con:
            # One replacement per instance at a time, as SQLite's write lock gives.
            con.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (instance_id,))
            created = {
                r["task"]: r["created"]
                for r in con.execute("SELECT task, created FROM user_tasks WHERE instance_id = %s", (instance_id,))
            }
            con.execute("DELETE FROM user_tasks WHERE instance_id = %s", (instance_id,))
            values = _task_rows(instance_id, rows, created, now)
            if values:
                with con.cursor() as cur:
                    cur.executemany(
                        f"INSERT INTO user_tasks({_USER_TASK_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s)", values
                    )

    def list_user_tasks(self) -> list[dict]:
        """Every open user task, oldest first."""
        return self._read(f"SELECT {_USER_TASK_COLUMNS} FROM user_tasks ORDER BY created, seq")

    def get_user_task(self, task_iri, correlation_key: str) -> dict | None:
        """The open row of ``task_iri`` for ``correlation_key`` (the newest
        when several instances share the key), or None."""
        rows = self._read(
            f"SELECT {_USER_TASK_COLUMNS} FROM user_tasks WHERE task = %s AND correlation_key = %s "
            "ORDER BY created DESC, seq DESC LIMIT 1",
            (str(task_iri), correlation_key),
        )
        return rows[0] if rows else None


def _postgres_entity(row: dict) -> dict:
    # jsonb reorders object keys; re-sorting gives the sort_keys order SQLite stored.
    row["data"] = json.loads(json.dumps(row["data"], sort_keys=True))
    return row
