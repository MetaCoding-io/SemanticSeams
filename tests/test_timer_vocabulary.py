"""Tests for the timer vocabulary (M030/S02 T01, ADR-0037).

ontology/proc.ttl 1.1 adds proc:TimerStartEvent and proc:TimerCatchEvent, and
ontology/seam.ttl 1.6 adds seam:schedules. ontology/shapes/seam-shapes.ttl adds
seamsh:SchedulesShape and seamsh:TimerStartedProcessShape and lets a timer start be
the way an executed process starts. In packages/seams,
``ModelGraph.scheduling_container`` resolves the one container that schedules a
process, and ``Process.timer_events()`` joins each lifted timer to its BPMN XML,
checking that the two agree.

The shapes run over the ontology plus an inline digest model. The library runs
over a scratch copy of the chapter 9 checkpoint, which ships the overdue-approval
reminder (a non-interrupting PT48H boundary timer on Approve Expense, M030/S02 T04).
The copy adds a digest process started by a daily timer, which the Expense API
executes and schedules. ``untimed`` strips the reminder again, byte for byte, for the
tests that compare a timed model with one that has no timers.
"""

import shutil
from pathlib import Path

import pytest
import rdflib
from rdflib import RDF, RDFS, URIRef
from seams import PROC, SEAM, ModelGraph, ResolutionError
from seams.bpmn import TimerDefinition, TimerExpression, parse_bpmn

from tests.test_error_vocabulary import ontology, violating_shapes

ROOT = Path(__file__).resolve().parents[1]
CHAPTER_09 = ROOT / "examples" / "expenses" / "chapter-09"
SEAMSH = rdflib.Namespace("https://w3id.org/seams/shapes#")

EX = "https://example.org/expenses/"
APPROVAL = EX + "approval_process"
DIGEST = EX + "digest_process"
API, DB = EX + "expense_api", EX + "expense_db"
REMINDER = EX + "approval_bpmn#overdue_reminder"
APPROVE = EX + "approval_bpmn#approve_expense"
TICK = EX + "digest_bpmn#tick"
DEFINITION = "bpmn:timerEventDefinition"

# ── the ontology ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("term", [PROC.TimerStartEvent, PROC.TimerCatchEvent, SEAM.schedules])
def test_new_terms_are_commented(term):
    assert ontology().value(term, RDFS.comment) is not None


def test_schedules_is_a_labelled_nest_seam():
    g = ontology()
    assert (SEAM.schedules, RDF.type, RDF.Property) in g
    assert g.value(SEAM.schedules, RDFS.label) == rdflib.Literal("schedules")
    assert g.value(SEAM.schedules, SEAM.reveal) == SEAM.Nest


def test_schedules_must_declare_a_reveal_mode():
    g = ontology()
    g.remove((SEAM.schedules, SEAM.reveal, None))
    assert SEAMSH.RevealShape in violating_shapes(g)


# ── the shapes ───────────────────────────────────────────────────────────────

DIGEST_MODEL = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix seam: <https://w3id.org/seams/seam#> .
@prefix arch: <https://w3id.org/seams/arch#> .
@prefix proc: <https://w3id.org/seams/proc#> .
@prefix :     <https://example.org/expenses/> .

:expenses a arch:System ; rdfs:label "Expenses" ; arch:contains :worker , :other .
:worker a arch:Container ; rdfs:label "Worker" ;
    seam:executes :digest_process ;
    seam:schedules :digest_process .
:other a arch:Container ; rdfs:label "Other" .
:digest_process a proc:Process ; rdfs:label "Daily Digest" ; seam:detailedBy :digest_bpmn .
:digest_bpmn a seam:Model ; rdfs:label "Daily Digest (BPMN)" ;
    seam:notation seam:BPMN ; seam:renderPayload <digest.bpmn> .
<https://example.org/expenses/digest_bpmn#tick> a proc:TimerStartEvent ; rdfs:label "Every morning" .
"""
WORKER, OTHER = URIRef(EX + "worker"), URIRef(EX + "other")
DIGEST_PROCESS, TICK_IRI = URIRef(DIGEST), URIRef(TICK)


def digest_graph() -> rdflib.Graph:
    g = ontology()
    g.parse(data=DIGEST_MODEL, format="turtle")
    return g


def test_ontology_alone_conforms():
    assert violating_shapes(ontology()) == set()


def test_a_scheduled_timer_started_process_conforms():
    """The timer start is the one way the executed process starts."""
    assert violating_shapes(digest_graph()) == set()


def test_an_executed_process_with_no_timer_start_has_no_way_to_start():
    g = digest_graph()
    g.remove((WORKER, SEAM.schedules, None))
    g.remove((TICK_IRI, RDF.type, PROC.TimerStartEvent))
    assert violating_shapes(g) == {SEAMSH.ExecutedProcessShape}


def test_scheduling_a_process_the_container_does_not_execute_is_flagged():
    g = digest_graph()
    g.remove((WORKER, SEAM.executes, DIGEST_PROCESS))
    assert SEAMSH.SchedulesShape in violating_shapes(g)


def test_scheduling_a_process_with_no_timer_start_is_flagged():
    g = digest_graph()
    g.remove((TICK_IRI, RDF.type, PROC.TimerStartEvent))
    assert SEAMSH.SchedulesShape in violating_shapes(g)


def test_scheduling_something_other_than_a_process_is_flagged():
    g = digest_graph()
    g.add((WORKER, SEAM.schedules, URIRef(EX + "not_a_process")))
    assert SEAMSH.SchedulesShape in violating_shapes(g)


def test_only_a_container_schedules():
    g = digest_graph()
    g.remove((WORKER, RDF.type, URIRef("https://w3id.org/seams/arch#Container")))
    assert SEAMSH.SchedulesShape in violating_shapes(g)


def test_a_timer_started_process_nobody_schedules_is_flagged():
    g = digest_graph()
    g.remove((WORKER, SEAM.schedules, DIGEST_PROCESS))
    assert violating_shapes(g) == {SEAMSH.TimerStartedProcessShape}


def test_a_timer_started_process_two_containers_schedule_is_flagged():
    g = digest_graph()
    g.add((OTHER, SEAM.executes, DIGEST_PROCESS))
    g.add((OTHER, SEAM.schedules, DIGEST_PROCESS))
    assert violating_shapes(g) == {SEAMSH.TimerStartedProcessShape}


# ── the library: a scratch chapter 9 with timers ─────────────────────────────

# The reminder as chapters 9 to 11 ship it: approval.bpmn holds REMINDER_NOTE plus
# REMINDER_XML before </bpmn:process> and REMINDER_DI before </bpmndi:BPMNPlane>;
# expenses.trig holds REMINDER_LIFT after Approve Expense's lift, and REMINDER_SCENARIO.
REMINDER_NOTE = """
    <!-- The overdue-approval reminder (ADR-0037): a non-interrupting timer on the
         manager's approval task. When the task has been open for 48 hours the
         reminder runs its own path, and the task stays open for the manager. -->
"""
REMINDER_XML = """    <bpmn:boundaryEvent id="overdue_reminder" name="Approval overdue" attachedToRef="approve_expense" cancelActivity="false">
      <bpmn:outgoing>flow_to_remind</bpmn:outgoing>
      <bpmn:timerEventDefinition id="overdue_reminder_def">
        <bpmn:timeDuration xsi:type="bpmn:tFormalExpression">"PT48H"</bpmn:timeDuration>
      </bpmn:timerEventDefinition>
    </bpmn:boundaryEvent>
    <bpmn:endEvent id="reminder_end" name="Reminded">
      <bpmn:incoming>flow_to_remind</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="flow_to_remind" sourceRef="overdue_reminder" targetRef="reminder_end" />
  </bpmn:process>"""
REMINDER_DI = """      <bpmndi:BPMNShape id="overdue_reminder_di" bpmnElement="overdue_reminder">
        <dc:Bounds x="742" y="80" width="36" height="36" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="reminder_end_di" bpmnElement="reminder_end">
        <dc:Bounds x="832" y="40" width="36" height="36" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="flow_to_remind_di" bpmnElement="flow_to_remind">
        <di:waypoint x="760" y="80" />
        <di:waypoint x="760" y="58" />
        <di:waypoint x="832" y="58" />
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>"""
DURATION = '<bpmn:timeDuration xsi:type="bpmn:tFormalExpression">"PT48H"</bpmn:timeDuration>'

DIGEST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                  id="digest_bpmn_defs" targetNamespace="https://example.org/expenses/digest_bpmn">
  <bpmn:process id="digest_process" name="Daily Digest" isExecutable="true">
    <bpmn:startEvent id="tick" name="Every morning">
      <bpmn:outgoing>flow_to_wait</bpmn:outgoing>
      <bpmn:timerEventDefinition id="tick_def">
        <bpmn:timeCycle xsi:type="bpmn:tFormalExpression">"R/2026-11-09T08:00:00Z/P1D"</bpmn:timeCycle>
      </bpmn:timerEventDefinition>
    </bpmn:startEvent>
    <bpmn:intermediateCatchEvent id="settle" name="Let the day settle">
      <bpmn:incoming>flow_to_wait</bpmn:incoming>
      <bpmn:outgoing>flow_to_end</bpmn:outgoing>
      <bpmn:timerEventDefinition id="settle_def">
        <bpmn:timeDuration xsi:type="bpmn:tFormalExpression">"PT1H"</bpmn:timeDuration>
      </bpmn:timerEventDefinition>
    </bpmn:intermediateCatchEvent>
    <bpmn:endEvent id="digest_end" name="Sent">
      <bpmn:incoming>flow_to_end</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="flow_to_wait" sourceRef="tick" targetRef="settle" />
    <bpmn:sequenceFlow id="flow_to_end" sourceRef="settle" targetRef="digest_end" />
    <bpmn:subProcess id="on_cancel" triggeredByEvent="true">
      <bpmn:startEvent id="nightly_sweep" name="Nightly sweep">
        <bpmn:timerEventDefinition id="sweep_def">
          <bpmn:timeDate xsi:type="bpmn:tFormalExpression">"2026-12-01T00:00:00Z"</bpmn:timeDate>
        </bpmn:timerEventDefinition>
      </bpmn:startEvent>
    </bpmn:subProcess>
  </bpmn:process>
</bpmn:definitions>
"""

REMINDER_LIFT = """    # Lifted because it is a timer (ADR-0037). Its duration and attachedToRef
    # stay in approval.bpmn; the runtime checks them when it loads, and the
    # scheduler fires it once, 48 hours after Approve Expense opens.
    <https://example.org/expenses/approval_bpmn#overdue_reminder> a proc:TimerCatchEvent ;
        rdfs:label "Approval overdue" ;
        seam:inModel :approval_bpmn .

    # Lifted only because :manager_reminded names it as its end event
    # (ADR-0014); proc has no class for a plain end event, so it has none.
    <https://example.org/expenses/approval_bpmn#reminder_end> rdfs:label "Reminded" ;
        seam:inModel :approval_bpmn .

"""
REMINDER_SCENARIO = """    # Up to 1000 the manager is told, then does not decide: once a run's steps
    # are done, the timers its instance waits on fire, so the overdue reminder
    # (ADR-0037) runs to its end while the expense stays submitted and
    # Approve Expense stays open.
    :manager_reminded a verify:Scenario ;
        verify:process :approval_process ;
        verify:actor :employee ;
        verify:given [ verify:field :description ; verify:value "Train to Leeds" ] ,
                     [ verify:field :amount ; verify:value 200.00 ] ,
                     [ verify:field :date ; verify:value "2026-10-01"^^xsd:date ] ;
        verify:expectState :s_submitted ;
        verify:expectEndEvent <https://example.org/expenses/approval_bpmn#reminder_end> .

"""
DIGEST_GRAPH = """
<urn:seams:graph:model:digest_bpmn> {
    :digest_bpmn a seam:Model ; rdfs:label "Daily Digest (BPMN)" .
    :digest_process a proc:Process ; rdfs:label "Daily Digest" ;
        seam:inModel :digest_bpmn .
    <https://example.org/expenses/digest_bpmn#tick> a proc:TimerStartEvent ;
        rdfs:label "Every morning" ;
        seam:inModel :digest_bpmn .
    <https://example.org/expenses/digest_bpmn#settle> a proc:TimerCatchEvent ;
        rdfs:label "Let the day settle" ;
        seam:inModel :digest_bpmn .
}

<urn:seams:graph:seams> {
"""
DIGEST_SEAMS = """    :digest_bpmn seam:notation seam:BPMN ;
        seam:renderPayload <digest.bpmn> .
    :digest_process seam:detailedBy :digest_bpmn .
    :expense_api seam:executes :digest_process ;
        seam:schedules :digest_process .
"""
APPROVAL_LIFT_ANCHOR = "    <https://example.org/expenses/approval_bpmn#approve_expense> a proc:UserTask ;\n"
APPROVAL_LIFT = (
    APPROVAL_LIFT_ANCHOR + '        rdfs:label "Approve Expense" ;\n        seam:inModel :approval_bpmn .\n\n'
)
SEAMS_ANCHOR = "\n<urn:seams:graph:seams> {\n"


def _shipped(text: str, *parts: str) -> None:
    for part in parts:
        assert text.count(part) == 1, part


def checkpoint(tmp_path: Path, *, trig_edits=(), bpmn_edits=(), digest_edits=()) -> Path:
    """A scratch chapter 9, which ships the reminder, plus the digest; each edit is (old, new)."""
    app = Path(shutil.copytree(CHAPTER_09, tmp_path / "chapter-09"))
    bpmn = app / "approval.bpmn"
    text = bpmn.read_text(encoding="utf-8")
    _shipped(text, REMINDER_NOTE + REMINDER_XML, REMINDER_DI)
    for old, new in bpmn_edits:
        assert old in text, old
        text = text.replace(old, new)
    bpmn.write_text(text, encoding="utf-8")
    digest = DIGEST_XML
    for old, new in digest_edits:
        assert old in digest, old
        digest = digest.replace(old, new)
    (app / "digest.bpmn").write_text(digest, encoding="utf-8")
    trig = app / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    _shipped(text, APPROVAL_LIFT + REMINDER_LIFT, SEAMS_ANCHOR)
    text = text.replace(SEAMS_ANCHOR, "\n" + DIGEST_GRAPH + DIGEST_SEAMS)
    for old, new in trig_edits:
        assert old in text, old
        text = text.replace(old, new)
    trig.write_text(text, encoding="utf-8")
    return trig


def untimed(tmp_path: Path) -> Path:
    """A scratch chapter 9 with the reminder taken out: no timers at all."""
    app = Path(shutil.copytree(CHAPTER_09, tmp_path / "untimed" / "chapter-09"))
    bpmn = app / "approval.bpmn"
    text = bpmn.read_text(encoding="utf-8")
    _shipped(text, REMINDER_NOTE + REMINDER_XML, REMINDER_DI)
    text = text.replace(REMINDER_NOTE + REMINDER_XML, "  </bpmn:process>")
    text = text.replace(REMINDER_DI, "    </bpmndi:BPMNPlane>")
    bpmn.write_text(text, encoding="utf-8")
    trig = app / "expenses.trig"
    text = trig.read_text(encoding="utf-8")
    _shipped(text, APPROVAL_LIFT + REMINDER_LIFT, REMINDER_SCENARIO)
    text = text.replace(APPROVAL_LIFT + REMINDER_LIFT, APPROVAL_LIFT).replace(REMINDER_SCENARIO, "")
    trig.write_text(text, encoding="utf-8")
    return trig


def graph(tmp_path: Path, **edits) -> ModelGraph:
    return ModelGraph(checkpoint(tmp_path, **edits))


def timers(g: ModelGraph, process: str):
    return g.processes.where(lambda p: str(p.iri) == process)[0].timer_events()


def refusal(g: ModelGraph, process: str) -> ResolutionError:
    with pytest.raises(ResolutionError) as err:
        timers(g, process)
    return err.value


# ── the parser ──


def test_the_parser_reads_timer_definitions_as_written(tmp_path):
    checkpoint(tmp_path)
    (approval,) = parse_bpmn(tmp_path / "chapter-09" / "approval.bpmn")
    reminder = approval.node("overdue_reminder")
    assert reminder.is_timer and not reminder.is_error_boundary
    assert reminder.timers == (TimerDefinition((TimerExpression("timeDuration", '"PT48H"'),)),)
    assert reminder.cancel_activity is False
    assert approval.node("notify_failed_boundary").cancel_activity is True
    assert not approval.node("approve_expense").is_timer
    (digest,) = parse_bpmn(tmp_path / "chapter-09" / "digest.bpmn")
    assert [n.id for n in digest.nodes if n.in_event_subprocess] == ["nightly_sweep"]
    assert digest.node("tick").timers[0].expressions == (TimerExpression("timeCycle", '"R/2026-11-09T08:00:00Z/P1D"'),)


# ── scheduling_container ──


def test_the_scheduling_container_is_the_one_that_schedules(tmp_path):
    container = graph(tmp_path).scheduling_container(DIGEST)
    assert (str(container.iri), container.label) == (API, "Expense API")


def test_no_scheduling_container_is_refused(tmp_path):
    g = graph(tmp_path, trig_edits=((" ;\n        seam:schedules :digest_process .", " ."),))
    with pytest.raises(ResolutionError) as err:
        g.scheduling_container(DIGEST)
    assert (err.value.subject, err.value.predicate) == (DIGEST, str(SEAM.schedules))
    assert err.value.detail == "expected one scheduling container, found []"


def test_two_scheduling_containers_are_refused_by_sorted_iri(tmp_path):
    g = graph(
        tmp_path,
        trig_edits=(
            (
                "    :expense_db seam:deployedTo",
                "    :expense_db seam:schedules :digest_process ;\n        seam:deployedTo",
            ),
        ),
    )
    with pytest.raises(ResolutionError) as err:
        g.scheduling_container(DIGEST)
    assert (err.value.subject, err.value.predicate) == (DIGEST, str(SEAM.schedules))
    assert err.value.detail == f"expected one scheduling container, found {[API, DB]}"


def test_a_process_that_is_not_scheduled_has_no_scheduling_container(tmp_path):
    with pytest.raises(ResolutionError) as err:
        graph(tmp_path).scheduling_container(APPROVAL)
    assert (err.value.subject, err.value.predicate) == (APPROVAL, str(SEAM.schedules))


def test_the_container_view_lists_what_it_schedules(tmp_path):
    g = graph(tmp_path)
    api = g.architecture.containers().where(lambda c: str(c.iri) == API)[0]
    assert [str(p.iri) for p in api.schedules] == [DIGEST]


# ── timer_events: the join ──


def test_the_checkpoint_ships_the_reminder_and_nothing_else():
    assert [str(t.iri) for t in timers(ModelGraph(CHAPTER_09 / "expenses.trig"), APPROVAL)] == [REMINDER]


@pytest.mark.parametrize("chapter", ["chapter-09", "chapter-10", "chapter-11"])
def test_every_checkpoint_from_chapter_9_ships_the_same_reminder(chapter):
    app = ROOT / "examples" / "expenses" / chapter
    _shipped((app / "approval.bpmn").read_text(encoding="utf-8"), REMINDER_NOTE + REMINDER_XML, REMINDER_DI)
    _shipped((app / "expenses.trig").read_text(encoding="utf-8"), APPROVAL_LIFT + REMINDER_LIFT, REMINDER_SCENARIO)


def test_the_untimed_copy_has_no_timers(tmp_path):
    assert len(timers(ModelGraph(untimed(tmp_path)), APPROVAL)) == 0


def test_the_reminder_joins_to_its_user_task(tmp_path):
    (reminder,) = timers(graph(tmp_path), APPROVAL)
    assert str(reminder.iri) == REMINDER
    assert reminder.kind == PROC.TimerCatchEvent and not reminder.is_start
    assert reminder.node.kind == "TimerCatchEvent"
    assert reminder.attached_to is not None and str(reminder.attached_to.iri) == APPROVE
    assert reminder.interrupting is False
    assert (reminder.expression, reminder.body) == ("timeDuration", '"PT48H"')
    assert reminder.expression_predicate == "bpmn:timeDuration"


def test_the_digest_start_and_catch_join_in_flow_order(tmp_path):
    found = timers(graph(tmp_path), DIGEST)
    assert [(str(t.iri), t.is_start, t.interrupting, t.expression, t.body) for t in found] == [
        (TICK, True, True, "timeCycle", '"R/2026-11-09T08:00:00Z/P1D"'),
        (EX + "digest_bpmn#settle", False, True, "timeDuration", '"PT1H"'),
    ]
    assert all(t.attached_to is None for t in found)


def test_an_interrupting_boundary_says_so(tmp_path):
    g = graph(tmp_path, bpmn_edits=((' cancelActivity="false"', ""),))
    assert timers(g, APPROVAL)[0].interrupting is True


def test_a_timer_boundary_on_a_service_task_is_left_unlifted(tmp_path):
    g = graph(
        tmp_path,
        bpmn_edits=(('attachedToRef="approve_expense"', 'attachedToRef="notify_manager"'),),
        trig_edits=((REMINDER_LIFT, ""),),
    )
    assert len(timers(g, APPROVAL)) == 0


# ── timer_events: disagreement names the event ──


def test_an_unlifted_reminder_is_refused(tmp_path):
    err = refusal(graph(tmp_path, trig_edits=((REMINDER_LIFT, ""),)), APPROVAL)
    assert (err.subject, err.predicate) == (REMINDER, DEFINITION)
    assert err.detail == (
        f"a boundaryEvent attached to {APPROVE} with a timerEventDefinition is a proc:TimerCatchEvent, "
        "but the graph does not lift it"
    )


def test_a_reminder_lifted_as_a_start_is_refused(tmp_path):
    lift = (REMINDER_LIFT, REMINDER_LIFT.replace("proc:TimerCatchEvent", "proc:TimerStartEvent"))
    err = refusal(graph(tmp_path, trig_edits=(lift,)), APPROVAL)
    assert (err.subject, err.predicate) == (REMINDER, DEFINITION)
    assert err.detail == (
        f"a boundaryEvent attached to {APPROVE} with a timerEventDefinition is a proc:TimerCatchEvent, "
        "but the graph types it proc:TimerStartEvent"
    )


def test_a_lifted_timer_boundary_on_a_service_task_is_refused(tmp_path):
    g = graph(tmp_path, bpmn_edits=(('attachedToRef="approve_expense"', 'attachedToRef="notify_manager"'),))
    err = refusal(g, APPROVAL)
    assert (err.subject, err.predicate) == (REMINDER, DEFINITION)
    assert err.detail == (
        f"a boundaryEvent attached to {EX}approval_bpmn#notify_manager is not a timer ADR-0037 lifts "
        "(a process start event, an intermediate catch event, or a boundary on a proc:UserTask), "
        "but the graph types it proc:TimerCatchEvent"
    )


def test_a_lifted_event_subprocess_start_is_refused(tmp_path):
    lift = "    <https://example.org/expenses/digest_bpmn#nightly_sweep> a proc:TimerStartEvent ; seam:inModel :digest_bpmn .\n"
    g = graph(
        tmp_path,
        trig_edits=(("<urn:seams:graph:model:digest_bpmn> {\n", "<urn:seams:graph:model:digest_bpmn> {\n" + lift),),
    )
    err = refusal(g, DIGEST)
    assert (err.subject, err.predicate) == (EX + "digest_bpmn#nightly_sweep", DEFINITION)
    assert err.detail.startswith("a startEvent is not a timer ADR-0037 lifts")


def test_a_timer_with_another_event_definition_is_refused(tmp_path):
    edit = (
        '<bpmn:timerEventDefinition id="overdue_reminder_def">',
        '<bpmn:messageEventDefinition id="m" />\n      <bpmn:timerEventDefinition id="overdue_reminder_def">',
    )
    err = refusal(graph(tmp_path, bpmn_edits=(edit,)), APPROVAL)
    assert (err.subject, err.predicate) == (REMINDER, DEFINITION)
    assert err.detail == (
        "a timer event has exactly one event definition, found ['messageEventDefinition', 'timerEventDefinition']"
    )


def test_two_timer_definitions_are_refused(tmp_path):
    edit = (
        "</bpmn:timerEventDefinition>\n    </bpmn:boundaryEvent>",
        f"</bpmn:timerEventDefinition>\n      <bpmn:timerEventDefinition>{DURATION}</bpmn:timerEventDefinition>\n    </bpmn:boundaryEvent>",
    )
    err = refusal(graph(tmp_path, bpmn_edits=(edit,)), APPROVAL)
    assert err.detail == (
        "a timer event has exactly one event definition, found ['timerEventDefinition', 'timerEventDefinition']"
    )


def test_a_definition_with_no_expression_is_refused(tmp_path):
    err = refusal(graph(tmp_path, bpmn_edits=((DURATION, ""),)), APPROVAL)
    assert (err.subject, err.predicate) == (REMINDER, DEFINITION)
    assert err.detail == "a timerEventDefinition holds exactly one timeDate, timeDuration or timeCycle, found []"


def test_a_definition_with_two_expressions_is_refused(tmp_path):
    two = DURATION + '<bpmn:timeDate xsi:type="bpmn:tFormalExpression">"2026-12-01T09:00:00Z"</bpmn:timeDate>'
    err = refusal(graph(tmp_path, bpmn_edits=((DURATION, two),)), APPROVAL)
    assert err.detail == (
        "a timerEventDefinition holds exactly one timeDate, timeDuration or timeCycle, "
        "found ['timeDuration', 'timeDate']"
    )


def test_a_lifted_timer_with_no_xml_event_is_refused(tmp_path):
    ghost = "    <https://example.org/expenses/approval_bpmn#ghost> a proc:TimerCatchEvent ; seam:inModel :approval_bpmn .\n"
    err = refusal(graph(tmp_path, trig_edits=((REMINDER_LIFT, REMINDER_LIFT + ghost),)), APPROVAL)
    assert (err.subject, err.predicate) == (EX + "approval_bpmn#ghost", DEFINITION)
    assert err.detail == (
        "the graph types it proc:TimerCatchEvent, but no event with a timerEventDefinition "
        "has id 'ghost' in approval.bpmn"
    )


def test_a_timer_type_on_a_plain_task_is_refused(tmp_path):
    lift = (
        APPROVAL_LIFT_ANCHOR,
        APPROVAL_LIFT_ANCHOR.replace("a proc:UserTask", "a proc:UserTask , proc:TimerCatchEvent"),
    )
    err = refusal(graph(tmp_path, trig_edits=(lift,)), APPROVAL)
    assert (err.subject, err.predicate) == (APPROVE, DEFINITION)
    assert "no event with a timerEventDefinition has id 'approve_expense'" in err.detail
