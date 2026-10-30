"""ModelGraph.store_health (M011/S04): storage findings for model-health tools (ADR-0011)."""

from pathlib import Path

import seams
from rdflib import URIRef
from seams import DEPLOY, SEAM, STORE_FINDING_SEVERITIES, ModelGraph, StoreFinding
from test_seams_store_resolution import BASE, CH07, CH08, CHAT, PG, PREFIXES, STORED, T, binding

ROOT = Path(__file__).resolve().parent.parent
CHECKOUT = ROOT / "examples/checkout.trig"


def health_of(tmp_path: Path, extra: str, *stores: str, base: str = BASE) -> list[StoreFinding]:
    path = tmp_path / "model.trig"
    path.write_text(f"{PREFIXES}\n:g {{\n{base.format(binding=binding(*stores))}\n{extra}\n}}\n")
    return ModelGraph(path).store_health()


def test_exports():
    assert seams.StoreFinding is StoreFinding
    assert STORE_FINDING_SEVERITIES == ("Violation", "Warning", "Info")


# ── the example models ──────────────────────────────────────────────────────


def test_chat_app_is_healthy():
    assert ModelGraph(CHAT).store_health() == []


def test_expenses_chapter_08_is_healthy():
    assert ModelGraph(CH08).store_health() == []


def test_expenses_chapter_07_notes_the_embedded_sqlite_default():
    [finding] = ModelGraph(CH07).store_health()
    assert (finding.severity, finding.subject, finding.predicate) == ("Info", None, None)
    assert "SQLite" in finding.message and "SEAMS_DB" in finding.message


def test_checkout_postgres_without_a_connecting_binding_is_a_violation():
    [finding] = ModelGraph(CHECKOUT).store_health()
    assert finding.severity == "Violation"
    assert finding.subject == URIRef("https://example.org/shop/order_api")
    assert finding.predicate == DEPLOY.connectsTo
    assert "connectsTo" in finding.message


# ── fixtures ────────────────────────────────────────────────────────────────


def test_inline_postgres_store_is_healthy(tmp_path: Path):
    assert health_of(tmp_path, f"{PG}\n{STORED}", "db") == []


def test_declared_store_no_shape_is_stored_in_warns(tmp_path: Path):
    # The original chat-app mismatch: an embedded-SQLite runtime next to a
    # declared PostgreSQL container nothing is stored in.
    warning, note = health_of(tmp_path, PG)
    assert (warning.severity, warning.subject, warning.predicate) == ("Warning", URIRef(T + "db"), SEAM.storedIn)
    assert T + "db" in warning.message
    assert note.severity == "Info"


def test_connected_store_without_a_store_kind_or_shapes_warns_and_fails(tmp_path: Path):
    # :db is a store only because a binding connects to it.
    findings = health_of(tmp_path, ":db a arch:Container .", "db")
    assert [f.severity for f in findings] == ["Violation", "Warning"]
    assert findings[1].subject == URIRef(T + "db")


def test_unsupported_store_kind_is_a_violation(tmp_path: Path):
    extra = f":db a arch:Container ; deploy:storeKind deploy:MongoDB .\n{STORED}"
    [finding] = health_of(tmp_path, extra, "db")
    assert (finding.severity, finding.subject, finding.predicate) == ("Violation", URIRef(T + "db"), DEPLOY.storeKind)
    assert "unsupported" in finding.message


def test_written_shape_with_no_stored_in_is_a_violation_and_the_store_warns(tmp_path: Path):
    findings = health_of(tmp_path, PG, "db")
    assert [(f.severity, f.subject, f.predicate) for f in findings] == [
        ("Violation", URIRef(T + "MessageShape"), SEAM.storedIn),
        ("Warning", URIRef(T + "db"), SEAM.storedIn),
    ]


def test_warnings_sort_by_subject(tmp_path: Path):
    extra = f"""{PG}
    {STORED}
    :zeta a arch:Container ; deploy:storeKind deploy:PostgreSQL .
    :alpha a arch:Container ; deploy:storeKind deploy:SQLite .
    """
    findings = health_of(tmp_path, extra, "db")
    assert [(f.severity, f.subject) for f in findings] == [
        ("Warning", URIRef(T + "alpha")),
        ("Warning", URIRef(T + "zeta")),
    ]
