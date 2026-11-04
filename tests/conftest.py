"""Shared fixtures: the store backends (M011/S03).

``store_backend`` runs a test once per backend. The ``postgres`` run needs
``SEAMS_TEST_POSTGRES_URL`` (for example
``postgresql://postgres:pw@localhost:5433/postgres``) and skips without it,
unless ``SEAMS_REQUIRE_POSTGRES=1`` makes the missing URL a failure (CI).
Each postgres test gets its own schemas, dropped at teardown.

``generator_dist`` simulates an installed third-party generator distribution
(M018/S01, D056): a ``<name>-<version>.dist-info`` directory and a module on
sys.path, so ``seams_gen.registry.discover()`` finds its entry points while
nothing is installed.
"""

import os
import sys
import uuid

import pytest

from seams_runtime.store import PostgresStore, SQLiteStore

# tests/golden holds golden generator outputs, compared byte for byte by the generator
# tests. The acceptance golden is named test_*.py because the generated file is, but
# it is output to compare, not a test of this repository: it only runs inside a
# project with a seams.toml (examples/expenses/chapter-09/generated/acceptance).
collect_ignore = ["golden"]

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


@pytest.fixture
def generator_dist(tmp_path, monkeypatch):
    """``generator_dist(module, source, entries)`` writes ``module``.py holding
    ``source`` and a distribution ``example-gen 1.0`` whose ``seams.generators``
    group is ``entries`` ({entry-point name: "module:object"}), under
    tmp_path/site, and puts that directory on sys.path."""

    def make(module: str, source: str, entries: dict[str, str]):
        site = tmp_path / "site"
        info = site / "example_gen-1.0.dist-info"
        info.mkdir(parents=True)
        (site / f"{module}.py").write_text(source, encoding="utf-8")
        (info / "METADATA").write_text("Metadata-Version: 2.1\nName: example-gen\nVersion: 1.0\n", encoding="utf-8")
        lines = "".join(f"{name} = {value}\n" for name, value in entries.items())
        (info / "entry_points.txt").write_text(f"[seams.generators]\n{lines}", encoding="utf-8")
        monkeypatch.syspath_prepend(str(site))
        monkeypatch.delitem(sys.modules, module, raising=False)
        return site

    return make


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
