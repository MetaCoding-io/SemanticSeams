"""Shared fixtures: the store backends (M011/S03).

``store_backend`` runs a test once per backend. The ``postgres`` run needs
``SEAMS_TEST_POSTGRES_URL`` (for example
``postgresql://postgres:pw@localhost:5433/postgres``) and skips without it,
unless ``SEAMS_REQUIRE_POSTGRES=1`` makes the missing URL a failure (CI).
Each postgres test gets its own schemas, dropped at teardown.
"""

import os
import uuid

import pytest

from seams_runtime.store import PostgresStore, SQLiteStore

POSTGRES_URL_ENV = "SEAMS_TEST_POSTGRES_URL"
REQUIRE_POSTGRES_ENV = "SEAMS_REQUIRE_POSTGRES"


def postgres_url() -> str:
    """The test database URL, or skip (fail when postgres is required)."""
    url = os.environ.get(POSTGRES_URL_ENV)
    if url:
        return url
    if os.environ.get(REQUIRE_POSTGRES_ENV) == "1":
        pytest.fail(f"{REQUIRE_POSTGRES_ENV}=1 but {POSTGRES_URL_ENV} is not set")
    pytest.skip(f"{POSTGRES_URL_ENV} is not set")


@pytest.fixture(params=["sqlite", "postgres"])
def store_backend(request) -> str:
    if request.param == "postgres":
        postgres_url()
    return request.param


@pytest.fixture
def make_store(store_backend, tmp_path):
    """``make_store(name="seams.sqlite")`` builds a store of the current
    backend. The same name gives the same data (a file under ``tmp_path``, or
    one postgres schema), like reopening a SQLite file."""
    schemas: dict[str, str] = {}

    def make(name: str = "seams.sqlite"):
        if store_backend == "sqlite":
            return SQLiteStore(tmp_path / name)
        schema = schemas.setdefault(name, f"seams_test_{uuid.uuid4().hex[:12]}")
        return PostgresStore(postgres_url(), schema=schema)

    yield make

    if schemas:
        import psycopg
        from psycopg import sql

        with psycopg.connect(postgres_url(), autocommit=True) as con:
            for schema in schemas.values():
                con.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
