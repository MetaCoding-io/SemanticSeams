"""The SPARQL coverage queries: unfired transitions and policies without a deny test (M015/S04, D054).

Both are SELECTs that return no rows when the model is covered, so they work as
`seams check` gates. Chapter 9 is fully covered; the chat app leaves its two
failure transitions unfired and governs sending with a party collection, so it
is the real negative. A small fixture built in the test covers the other cases.
"""

from importlib import resources
from pathlib import Path

import pytest
import seams
from rdflib import URIRef
from seams.sparql import QUESTION_FOLDERS, load_question, question_names

from seams_gen.tests import extract_tests

ROOT = Path(__file__).resolve().parent.parent
DOCS_COVERAGE = ROOT / "docs/queries/coverage"
CHAPTER_09 = ROOT / "examples/expenses/chapter-09/expenses.trig"
CHAT = ROOT / "examples/chat-app/chat-app.trig"

C = "https://example.org/chat/"
F = "https://example.org/fx/"

FIXTURE = """\
@prefix :      <https://example.org/fx/> .
@prefix seam:  <https://w3id.org/seams/seam#> .
@prefix state: <https://w3id.org/seams/state#> .
@prefix odrl:  <http://www.w3.org/ns/odrl/2/> .

<urn:seams:graph:model:lc> {
    :lc a state:StateMachine , seam:Model .
    :t_fired   a state:Transition ; seam:inModel :lc .
    :t_unfired a state:Transition ; seam:inModel :lc .
}

<urn:seams:graph:model:other_lc> {
    :other_lc a state:StateMachine , seam:Model .
    :t_other a state:Transition ; seam:inModel :other_lc .
}

<urn:seams:graph:seams> {
    :task seam:fires :t_fired .

    :solo a odrl:Party .
    :everyone a odrl:PartyCollection .
    # :solo is the only party, so no party is outside the assignee.
    :solo_policy a odrl:Policy ;
        odrl:permission [ odrl:target :op_solo ; odrl:assignee :solo ] .
    # A party collection lets anyone in.
    :everyone_policy a odrl:Policy ;
        odrl:permission [ odrl:target :op_everyone ; odrl:assignee :everyone ] .
    # No assignee lets anyone in too.
    :open_policy a odrl:Policy ;
        odrl:permission [ odrl:target :op_open ] .
}
"""


@pytest.fixture(scope="module")
def chapter_09() -> seams.Model:
    return seams.load(CHAPTER_09)


@pytest.fixture(scope="module")
def chat() -> seams.Model:
    return seams.load(CHAT)


@pytest.fixture
def fixture(tmp_path: Path) -> seams.Model:
    path = tmp_path / "coverage.trig"
    path.write_text(FIXTURE, encoding="utf-8")
    return seams.load(path)


def _pairs(rows: list, *names: str) -> list[tuple[str | None, ...]]:
    return [tuple(None if row.get(n) is None else str(row[n]) for n in names) for row in rows]


# ── bundle ──


def test_coverage_questions_match_docs():
    assert question_names("coverage") == sorted(f"coverage/{p.stem}" for p in DOCS_COVERAGE.glob("*.rq"))
    assert question_names("coverage") == ["coverage/policies-without-deny", "coverage/unfired-transitions"]
    assert QUESTION_FOLDERS == ("coverage",)


def test_top_level_question_names_leave_coverage_out():
    assert not any("/" in name or name.startswith("coverage") for name in question_names())


@pytest.mark.parametrize("name", sorted(p.stem for p in DOCS_COVERAGE.glob("*.rq")))
def test_bundled_coverage_query_is_byte_identical_to_docs(name: str):
    bundled = (resources.files("seams") / "queries" / "coverage" / f"{name}.rq").read_bytes()
    assert bundled == (DOCS_COVERAGE / f"{name}.rq").read_bytes()
    assert load_question(f"coverage/{name}") == (DOCS_COVERAGE / f"{name}.rq").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "name",
    [
        "coverage/missing",
        "coverage/../what-moves-state",
        "gates/ungoverned-writes",
        "complexity/seam-edges",
        "coverage/",
        "/unfired-transitions",
        "unfired-transitions",
        "coverage/Unfired-Transitions",
    ],
)
def test_unknown_coverage_names_raise_key_error(name: str):
    with pytest.raises(KeyError):
        load_question(name)


def test_unknown_question_folder_raises_key_error():
    with pytest.raises(KeyError, match="unknown question folder"):
        question_names("gates")


# ── unfired transitions ──


def test_chapter_09_fires_every_transition(chapter_09: seams.Model):
    assert chapter_09.question("coverage/unfired-transitions") == []


def test_chat_app_leaves_its_failure_transitions_unfired(chat: seams.Model):
    rows = chat.question("coverage/unfired-transitions")
    assert _pairs(rows, "lifecycle", "transition") == [
        (C + "message_lifecycle", C + "t_fail_send"),
        (C + "message_lifecycle", C + "t_fail_stream"),
    ]


def test_fixture_unfired_transitions_and_lifecycle_binding(fixture: seams.Model):
    rows = fixture.question("coverage/unfired-transitions")
    assert _pairs(rows, "lifecycle", "transition") == [
        (F + "lc", F + "t_unfired"),
        (F + "other_lc", F + "t_other"),
    ]
    bound = fixture.question("coverage/unfired-transitions", lifecycle=URIRef(F + "lc"))
    assert _pairs(bound, "lifecycle", "transition") == [(F + "lc", F + "t_unfired")]
    assert fixture.question("coverage/unfired-transitions", lifecycle=URIRef(F + "nowhere")) == []


# ── policies without a deny test ──


def test_chapter_09_has_a_deny_test_for_every_policy(chapter_09: seams.Model):
    assert chapter_09.question("coverage/policies-without-deny") == []


def test_chat_app_party_collection_policy_has_no_deny_test(chat: seams.Model):
    rows = chat.question("coverage/policies-without-deny")
    assert _pairs(rows, "policy", "target", "assignee") == [
        (C + "user_send_policy", C + "send_message_op", C + "authenticated_user"),
    ]


def test_fixture_policies_without_deny_and_policy_binding(fixture: seams.Model):
    rows = fixture.question("coverage/policies-without-deny")
    assert _pairs(rows, "policy", "target", "assignee") == [
        (F + "everyone_policy", F + "op_everyone", F + "everyone"),
        (F + "open_policy", F + "op_open", None),
        (F + "solo_policy", F + "op_solo", F + "solo"),
    ]
    bound = fixture.question("coverage/policies-without-deny", policy=URIRef(F + "solo_policy"))
    assert _pairs(bound, "policy", "target", "assignee") == [(F + "solo_policy", F + "op_solo", F + "solo")]


def test_a_second_party_gives_the_solo_policy_a_deny_test(tmp_path: Path):
    path = tmp_path / "coverage.trig"
    path.write_text(FIXTURE.replace(":solo a odrl:Party .", ":solo a odrl:Party .\n    :other a odrl:Party ."), "utf-8")
    rows = seams.load(path).question("coverage/policies-without-deny")
    assert [str(row["policy"]) for row in rows] == [F + "everyone_policy", F + "open_policy"]


@pytest.mark.parametrize("trig", [CHAPTER_09, CHAT], ids=["chapter-09", "chat-app"])
def test_policies_without_deny_mirror_the_tests_generator(trig: Path):
    """A row is exactly a permission the tests generator writes no party deny case for."""
    model = seams.load(trig)
    no_deny = {
        target.policy_curie
        for target in extract_tests(model).targets
        if not any(not case.allowed and case.party_curie is not None for case in target.cases)
    }
    rows = model.question("coverage/policies-without-deny")
    assert {model.compact(row["policy"]) for row in rows} == no_deny
