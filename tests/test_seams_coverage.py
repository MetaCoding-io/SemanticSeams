"""seams.coverage: BPMN paths no scenario exercises, plus the two SPARQL coverage wrappers (M015/S04, D054).

Chapter 9's three scenarios run the auto, manager-approve and finance-approve
paths of the approval process. Its two reject paths, the two escalation paths
through the notify-failed boundary event and both payout paths are not run by
any scenario, and that is the real result pinned here. A small fixture written
in the test covers loops, step order and expectations that are not on a path.
"""

from pathlib import Path

import pytest
import seams
from rdflib import RDF, URIRef
from seams import VERIFY, ResolutionError
from seams.coverage import exercises

ROOT = Path(__file__).resolve().parent.parent
CHAPTER_09 = ROOT / "examples/expenses/chapter-09"
CHAT = ROOT / "examples/chat-app/chat-app.trig"

EX = "https://example.org/expenses/"
APPROVAL = URIRef(EX + "approval_process")
PAYOUT = URIRef(EX + "payout_process")
HEAD = ("start", "persist_expense", "route_expense", "route_gateway")

AUTO = (*HEAD, "record_approval", "pay_expense", "approved_end")
MANAGER_APPROVE = (
    *HEAD,
    "notify_manager",
    "approve_expense",
    "decision_gateway",
    "record_approval",
    "pay_expense",
    "approved_end",
)
MANAGER_REJECT = (*HEAD, "notify_manager", "approve_expense", "decision_gateway", "record_rejection", "rejected_end")
ESCALATE = (*HEAD, "notify_manager", "notify_failed_boundary", "finance_approve_expense", "decision_gateway")
FINANCE = (*HEAD, "finance_approve_expense", "decision_gateway")


@pytest.fixture(scope="module")
def chapter9() -> seams.Model:
    return seams.load(CHAPTER_09)


def _ids(paths: tuple[seams.ProcessPath, ...]) -> list[tuple[str, tuple[str, ...]]]:
    return [(str(p.process.iri), p.bpmn_ids) for p in paths]


def test_chapter_9_paths_and_the_scenarios_that_run_them(chapter9: seams.Model) -> None:
    found = [(p.bpmn_ids, [str(s.iri) for s in p.scenarios]) for p in seams.process_paths(chapter9, APPROVAL)]
    assert found == [
        (AUTO, [EX + "auto_approved"]),
        (MANAGER_APPROVE, [EX + "manager_approved"]),
        (MANAGER_REJECT, []),
        ((*ESCALATE, "record_approval", "pay_expense", "approved_end"), []),
        ((*ESCALATE, "record_rejection", "rejected_end"), []),
        ((*FINANCE, "record_approval", "pay_expense", "approved_end"), [EX + "finance_approved"]),
        ((*FINANCE, "record_rejection", "rejected_end"), []),
    ]


def test_chapter_9_unexercised_paths(chapter9: seams.Model) -> None:
    uncovered = seams.unexercised_paths(chapter9)
    assert _ids(uncovered) == [
        (str(APPROVAL), MANAGER_REJECT),
        (str(APPROVAL), (*ESCALATE, "record_approval", "pay_expense", "approved_end")),
        (str(APPROVAL), (*ESCALATE, "record_rejection", "rejected_end")),
        (str(APPROVAL), (*FINANCE, "record_rejection", "rejected_end")),
        (
            str(PAYOUT),
            ("payout_requested", "schedule_payout", "choose_payout", "method_gateway", "add_to_batch", "paid_out"),
        ),
        (
            str(PAYOUT),
            ("payout_requested", "schedule_payout", "choose_payout", "method_gateway", "send_now", "paid_out"),
        ),
    ]
    reject = uncovered[0]
    assert reject.end.iri == URIRef(EX + "approval_bpmn#rejected_end")
    assert reject.start.bpmn_id == "start"
    assert reject.iris[-1] == reject.end.iri
    assert not reject.exercised


def test_a_process_can_be_named_by_curie_and_an_unknown_one_raises(chapter9: seams.Model) -> None:
    assert _ids(seams.unexercised_paths(chapter9, ":payout_process")) == _ids(seams.unexercised_paths(chapter9, PAYOUT))
    with pytest.raises(ResolutionError, match="no_such_process"):
        seams.process_paths(chapter9, ":no_such_process")


def test_removing_a_scenario_leaves_its_path_unexercised() -> None:
    model = seams.load(CHAPTER_09)  # a fresh copy: the views are built on first use
    scenario = URIRef(EX + "manager_approved")
    assert (scenario, RDF.type, VERIFY.Scenario) in model.ds
    model.ds.remove((scenario, None, None))
    uncovered = [p.bpmn_ids for p in seams.unexercised_paths(model, APPROVAL)]
    assert MANAGER_APPROVE in uncovered
    assert AUTO not in uncovered


def test_the_sparql_wrappers_match_the_canned_questions(chapter9: seams.Model) -> None:
    assert seams.unfired_transitions(chapter9) == ()
    assert seams.policies_without_deny(chapter9) == ()
    chat = seams.load(CHAT)
    C = "https://example.org/chat/"
    assert seams.unfired_transitions(chat).iris() == (URIRef(C + "t_fail_send"), URIRef(C + "t_fail_stream"))
    assert seams.unfired_transitions(chat, ":message_lifecycle").iris() == (
        URIRef(C + "t_fail_send"),
        URIRef(C + "t_fail_stream"),
    )
    assert seams.unfired_transitions(chat, ":no_such_lifecycle") == ()
    (gap,) = seams.policies_without_deny(chat)
    assert (gap.policy.iri, gap.target, gap.assignee) == (
        URIRef(C + "user_send_policy"),
        URIRef(C + "send_message_op"),
        URIRef(C + "authenticated_user"),
    )


# A loop (review can send the claim back to fill), and a second end.
LOOP_BPMN = """\
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="defs">
  <bpmn:process id="claim_process" isExecutable="true">
    <bpmn:startEvent id="start" />
    <bpmn:userTask id="fill" />
    <bpmn:userTask id="review" />
    <bpmn:exclusiveGateway id="gw" />
    <bpmn:serviceTask id="accept" />
    <bpmn:endEvent id="done" />
    <bpmn:endEvent id="dropped" />
    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="fill" />
    <bpmn:sequenceFlow id="f2" sourceRef="fill" targetRef="review" />
    <bpmn:sequenceFlow id="f3" sourceRef="review" targetRef="gw" />
    <bpmn:sequenceFlow id="f4" sourceRef="gw" targetRef="fill" />
    <bpmn:sequenceFlow id="f5" sourceRef="gw" targetRef="accept" />
    <bpmn:sequenceFlow id="f6" sourceRef="gw" targetRef="dropped" />
    <bpmn:sequenceFlow id="f7" sourceRef="accept" targetRef="done" />
  </bpmn:process>
</bpmn:definitions>
"""

LOOP_TRIG = """\
@prefix :       <https://example.org/fx/> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix state:  <https://w3id.org/seams/state#> .
@prefix verify: <https://w3id.org/seams/verify#> .

<urn:seams:graph:model:claim_bpmn> {
    :claim_bpmn a seam:Model .
    :claim_process a proc:Process ; seam:inModel :claim_bpmn .
    <https://example.org/fx/claim_bpmn#fill> a proc:UserTask ; seam:inModel :claim_bpmn .
    <https://example.org/fx/claim_bpmn#review> a proc:UserTask ; seam:inModel :claim_bpmn .
    <https://example.org/fx/claim_bpmn#accept> a proc:ServiceTask ; seam:inModel :claim_bpmn .
}

<urn:seams:graph:model:claim_lc> {
    :claim_lc a state:StateMachine , seam:Model ;
        state:hasState :s_new , :s_accepted ; state:hasTransition :t_accept .
    :t_accept a state:Transition ; state:from :s_new ; state:to :s_accepted ; seam:inModel :claim_lc .
}

<urn:seams:graph:seams> {
    :claim_bpmn seam:renderPayload <claim.bpmn> .
    :claim_process seam:detailedBy :claim_bpmn .
    <https://example.org/fx/claim_bpmn#accept> seam:fires :t_accept .

    # Runs the accept path: both user tasks, in order, then the accept state.
    :accepted a verify:Scenario ;
        verify:process :claim_process ; verify:actor :someone ;
        verify:step ( [ verify:task <https://example.org/fx/claim_bpmn#fill> ; verify:actor :someone ]
                      [ verify:task <https://example.org/fx/claim_bpmn#review> ; verify:actor :someone ] ) ;
        verify:expectState :s_accepted .

    # Steps out of order: exercises nothing.
    :backwards a verify:Scenario ;
        verify:process :claim_process ; verify:actor :someone ;
        verify:step ( [ verify:task <https://example.org/fx/claim_bpmn#review> ; verify:actor :someone ]
                      [ verify:task <https://example.org/fx/claim_bpmn#fill> ; verify:actor :someone ] ) ;
        verify:expectEndEvent <https://example.org/fx/claim_bpmn#dropped> .

    # Skips the review user task: exercises nothing.
    :skips_review a verify:Scenario ;
        verify:process :claim_process ; verify:actor :someone ;
        verify:step ( [ verify:task <https://example.org/fx/claim_bpmn#fill> ; verify:actor :someone ] ) ;
        verify:expectEndEvent <https://example.org/fx/claim_bpmn#dropped> .

    # Expects an end event no path reaches with it (a state the dropped path never fires).
    :dropped_but_accepted a verify:Scenario ;
        verify:process :claim_process ; verify:actor :someone ;
        verify:step ( [ verify:task <https://example.org/fx/claim_bpmn#fill> ; verify:actor :someone ]
                      [ verify:task <https://example.org/fx/claim_bpmn#review> ; verify:actor :someone ] ) ;
        verify:expectEndEvent <https://example.org/fx/claim_bpmn#dropped> ;
        verify:expectState :s_accepted .
}
"""


@pytest.fixture
def claim(tmp_path: Path) -> seams.Model:
    (tmp_path / "claim.bpmn").write_text(LOOP_BPMN)
    (tmp_path / "claim.trig").write_text(LOOP_TRIG)
    return seams.load(tmp_path / "claim.trig")


def test_a_loop_back_is_not_a_path_and_scenarios_match_steps_and_expectations(claim: seams.Model) -> None:
    found = [(p.bpmn_ids, [str(s.iri) for s in p.scenarios]) for p in seams.process_paths(claim)]
    assert found == [
        (("start", "fill", "review", "gw", "accept", "done"), ["https://example.org/fx/accepted"]),
        (("start", "fill", "review", "gw", "dropped"), []),
    ]
    assert [p.end.bpmn_id for p in seams.unexercised_paths(claim)] == ["dropped"]


def test_a_scenario_of_another_process_exercises_nothing(claim: seams.Model, chapter9: seams.Model) -> None:
    other = chapter9.scenarios.by_iri(URIRef(EX + "auto_approved"))
    (path, _) = seams.process_paths(claim)
    assert not exercises(other, path.process, path.nodes)
