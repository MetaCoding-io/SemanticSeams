"""SemPKM webhook channels in the model (M024/S04, ADR-0027 sections 1, 2, 7 and 10).

A channel whose comm:transport is comm:SemPKMWebhook is inbound: SemPKM POSTs its
deliveries to the channel's comm:path on the one container that seam:exposes it.
``ModelGraph.webhook_channel`` resolves its facts (event type, accepted shape, its
class and SemPKM store, the receiving container and its two bindings, the
subscribed processes) and raises ``ResolutionError(subject, predicate)`` for each
row of the ADR's section 10 table. ``seamsh:SemPKMWebhookChannelShape`` reports the
same faults, so a model that passes the shapes resolves.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
import seams
from rdflib import RDFS, URIRef
from rdflib.namespace import SH
from seams import (
    COMM,
    DEPLOY,
    SEAM,
    WEBHOOK_EVENT_TYPES,
    ModelGraph,
    ResolutionError,
    WebhookChannel,
)
from seams_cli.check import check_shapes, model_graph

T = "https://example.org/hooks/"
CHANNEL = URIRef(T + "vendor_changes")
SHAPE = URIRef(T + "VendorShape")
API = URIRef(T + "api")
PKM = URIRef(T + "pkm")
PROCESS = URIRef(T + "vendor_check_process")

ROOT = Path(__file__).resolve().parents[1]
# A message start event that the graph says seam:subscribesTo the channel.
BPMN = (ROOT / "tests" / "fixtures" / "channel_start" / "payout.bpmn").read_text()

PREFIXES = """\
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix hydra:  <http://www.w3.org/ns/hydra/core#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix proc:   <https://w3id.org/seams/proc#> .
@prefix :       <https://example.org/hooks/> .
"""

# The ADR-0027 section 1 example: a webhook channel accepting vendors stored in
# SemPKM, received by :api, which executes the one subscribed process and holds
# both SemPKM bindings. Each case edits one fact of it.
GOOD = """
<urn:seams:graph:model:hooks_architecture> {
    :hooks_architecture a seam:Model ; rdfs:label "Hooks Architecture" .
    :system a arch:System ; rdfs:label "Hooks" ; arch:contains :api , :pkm ;
        seam:inModel :hooks_architecture .
    :pkm a arch:Container ; rdfs:label "PKM" ; deploy:storeKind deploy:SemPKM ;
        seam:inModel :hooks_architecture .
    :api a arch:Container ; rdfs:label "API" ;
        deploy:configuration [ a deploy:Configuration ;
            deploy:binding [ deploy:key "SEMPKM_URL" ; deploy:value "http://pkm:8000" ; deploy:connectsTo :pkm ] ,
                [ deploy:key "SEMPKM_TOKEN" ; deploy:secretRef <https://secrets.example.org/pkm-token> ;
                  deploy:secretName "pkm-token" ; deploy:authenticatesTo :pkm ] ] ;
        seam:inModel :hooks_architecture .
    :vendor_changes a comm:Channel ; rdfs:label "vendor changed in SemPKM" ;
        comm:transport comm:SemPKMWebhook ;
        comm:eventName "object.changed" ;
        comm:path [ a hydra:IriTemplate ; hydra:template "/sempkm/vendor-changes" ] ;
        seam:inModel :hooks_architecture .
}

<urn:seams:graph:model:hooks_data> {
    :hooks_data a seam:Model ; rdfs:label "Hooks Data" .
    :VendorShape a sh:NodeShape ; rdfs:label "Vendor" ;
        sh:targetClass :Vendor ;
        seam:inModel :hooks_data .
}

<urn:seams:graph:model:payout_bpmn> {
    :payout_bpmn a seam:Model ; rdfs:label "Vendor check (BPMN)" .
    :vendor_check_process a proc:Process ; rdfs:label "Vendor check" ;
        seam:inModel :payout_bpmn .
    <https://example.org/hooks/payout_bpmn#payment_received> a proc:MessageCatchEvent ;
        rdfs:label "Vendor changed" ;
        seam:inModel :payout_bpmn .
    <https://example.org/hooks/payout_bpmn#pay_expense> a proc:ServiceTask ;
        rdfs:label "Check vendor" ;
        seam:inModel :payout_bpmn .
}

<urn:seams:graph:seams> {
    :api seam:exposes :vendor_changes ;
        seam:executes :vendor_check_process .
    :vendor_changes seam:acceptsShape :VendorShape .
    :VendorShape seam:storedIn :pkm .
    :vendor_check_process seam:detailedBy :payout_bpmn .
    <https://example.org/hooks/payout_bpmn#payment_received> seam:subscribesTo :vendor_changes .
    :payout_bpmn seam:renderPayload <payout.bpmn> .
}
"""

START = "<https://example.org/hooks/payout_bpmn#payment_received> seam:subscribesTo :vendor_changes ."
TASK = "<https://example.org/hooks/payout_bpmn#pay_expense>"
PATH = 'comm:path [ a hydra:IriTemplate ; hydra:template "/sempkm/vendor-changes" ]'
URL = '[ deploy:key "SEMPKM_URL" ; deploy:value "http://pkm:8000" ; deploy:connectsTo :pkm ] ,'
SECRET = 'deploy:secretRef <https://secrets.example.org/pkm-token> ;\n                  deploy:secretName "pkm-token"'

# A second webhook channel of :api (in the seams graph), for the shared-path case.
OTHER = """
<urn:seams:graph:model:hooks_more> {
    :other_changes a comm:Channel ; rdfs:label "other" ;
        comm:transport comm:SemPKMWebhook ;
        comm:eventName "object.changed" ;
        comm:path [ a hydra:IriTemplate ; hydra:template "/sempkm/vendor-changes" ] ;
        seam:acceptsShape :VendorShape ;
        seam:inModel :hooks_architecture .
    :api seam:exposes :other_changes .
    <https://example.org/hooks/payout_bpmn#payment_received> seam:subscribesTo :other_changes .
}
"""


def write(tmp_path: Path, edit: Callable[[str], str] = lambda text: text) -> Path:
    """The GOOD model with ``edit`` applied, beside its BPMN file."""
    (tmp_path / "payout.bpmn").write_text(BPMN)
    body = edit(GOOD)
    path = tmp_path / "model.trig"
    path.write_text(PREFIXES + body)
    return path


def replace(old: str, new: str) -> Callable[[str], str]:
    def edit(text: str) -> str:
        assert old in text, old
        return text.replace(old, new, 1)

    return edit


def append(extra: str) -> Callable[[str], str]:
    return lambda text: text + extra


def seams_graph(triples: str) -> Callable[[str], str]:
    """Add ``triples`` to the seams graph."""
    return replace("<urn:seams:graph:seams> {\n", "<urn:seams:graph:seams> {\n    " + triples + "\n")


def raises(path: Path) -> ResolutionError:
    with pytest.raises(ResolutionError) as info:
        ModelGraph(path).webhook_channel(CHANNEL)
    return info.value


def webhook_findings(path: Path) -> list[str]:
    """The SHACL findings of the webhook channel shape (their messages cite ADR-0027)."""
    return [f.detail for f in check_shapes(model_graph(path)) if "ADR-0027" in f.detail]


# ── the vocabulary ──────────────────────────────────────────────────────────


def test_the_transport_is_a_labelled_and_commented_comm_transport():
    from rdflib import RDF, Graph

    g = Graph().parse(ROOT / "ontology" / "comm.ttl", format="turtle")
    assert (COMM.SemPKMWebhook, RDF.type, COMM.Transport) in g
    assert g.value(COMM.SemPKMWebhook, RDFS.label) is not None
    assert "ADR-0027" in str(g.value(COMM.SemPKMWebhook, RDFS.comment))


def test_exports():
    assert seams.WebhookChannel is WebhookChannel
    assert WEBHOOK_EVENT_TYPES == ("object.changed",)


# ── a webhook channel that resolves ─────────────────────────────────────────


def test_the_section_1_example_resolves(tmp_path: Path):
    m = ModelGraph(write(tmp_path))
    expected = WebhookChannel(
        CHANNEL,
        "vendor changed in SemPKM",
        "object.changed",
        "/sempkm/vendor-changes",
        SHAPE,
        URIRef(T + "Vendor"),
        PKM,
        API,
        "SEMPKM_URL",
        "SEMPKM_TOKEN",
        (PROCESS,),
    )
    assert m.webhook_channel(":vendor_changes") == expected
    assert m.webhook_channels() == [expected]
    assert m.webhook_channel_iris() == [CHANNEL]
    assert m.is_webhook_channel(CHANNEL) is True
    assert m.subscribed_processes(CHANNEL) == [PROCESS]


def test_the_section_1_example_passes_the_shapes(tmp_path: Path):
    assert webhook_findings(write(tmp_path)) == []


def test_a_token_read_from_a_file_resolves(tmp_path: Path):
    path = write(tmp_path, replace(SECRET, 'deploy:secretFile "secrets/pkm-token"'))
    assert ModelGraph(path).webhook_channel(CHANNEL).token_key == "SEMPKM_TOKEN"


def test_subscribers_are_sorted(tmp_path: Path):
    # A second process whose BPMN model holds the same start event id.
    (tmp_path / "second.bpmn").write_text(BPMN)
    extra = """
<urn:seams:graph:model:second_bpmn> {
    :second_bpmn a seam:Model ; rdfs:label "Second (BPMN)" .
    :a_second_process a proc:Process ; rdfs:label "Second" ; seam:inModel :second_bpmn .
    <https://example.org/hooks/second_bpmn#payment_received> a proc:MessageCatchEvent ;
        rdfs:label "Vendor changed" ; seam:inModel :second_bpmn .
    :a_second_process seam:detailedBy :second_bpmn .
    :second_bpmn seam:renderPayload <second.bpmn> .
    <https://example.org/hooks/second_bpmn#payment_received> seam:subscribesTo :vendor_changes .
    :api seam:executes :a_second_process .
}
"""
    channel = ModelGraph(write(tmp_path, append(extra))).webhook_channel(CHANNEL)
    assert channel.processes == (URIRef(T + "a_second_process"), PROCESS)


def test_other_channels_are_not_webhook_channels(tmp_path: Path):
    path = write(tmp_path, replace("comm:transport comm:SemPKMWebhook ;", "comm:transport comm:SSE ;"))
    m = ModelGraph(path)
    assert m.webhook_channel_iris() == []
    assert m.webhook_channels() == []
    assert m.is_webhook_channel(CHANNEL) is False
    err = raises(path)
    assert (URIRef(err.subject), URIRef(err.predicate)) == (CHANNEL, COMM.transport)
    assert webhook_findings(path) == []


def test_a_model_without_webhook_channels_is_unchanged():
    m = ModelGraph(ROOT / "tests" / "fixtures" / "channel_start" / "expenses.trig")
    assert m.webhook_channels() == []


# ── each resolution error of ADR-0027 section 10 ───────────────────────────

# (case, edit, subject, predicate, SHACL message fragment)
CASES: list[tuple[str, Callable[[str], str], URIRef, URIRef, str]] = [
    (
        "no event name",
        replace('comm:eventName "object.changed" ;', ""),
        CHANNEL,
        COMM.eventName,
        "exactly one comm:eventName",
    ),
    (
        "two event names",
        replace('comm:eventName "object.changed" ;', 'comm:eventName "object.changed" , "edge.changed" ;'),
        CHANNEL,
        COMM.eventName,
        "exactly one comm:eventName",
    ),
    (
        "an unsupported event name",
        replace('comm:eventName "object.changed" ;', 'comm:eventName "edge.changed" ;'),
        CHANNEL,
        COMM.eventName,
        "exactly one comm:eventName",
    ),
    (
        "no accepted shape",
        replace(":vendor_changes seam:acceptsShape :VendorShape .", ""),
        CHANNEL,
        SEAM.acceptsShape,
        "seam:acceptsShape exactly one shape",
    ),
    (
        "two accepted shapes",
        seams_graph(
            ":vendor_changes seam:acceptsShape :OtherShape .\n"
            "    :OtherShape a sh:NodeShape ; sh:targetClass :Other ; seam:storedIn :pkm ."
        ),
        CHANNEL,
        SEAM.acceptsShape,
        "seam:acceptsShape exactly one shape",
    ),
    (
        "an accepted shape stored nowhere",
        replace(":VendorShape seam:storedIn :pkm .", ""),
        SHAPE,
        SEAM.storedIn,
        "seam:storedIn exactly one store, a deploy:SemPKM store",
    ),
    (
        "an accepted shape stored in a relational store",
        replace(
            ":VendorShape seam:storedIn :pkm .",
            ":VendorShape seam:storedIn :db .\n    :db a arch:Container ; deploy:storeKind deploy:PostgreSQL .",
        ),
        SHAPE,
        SEAM.storedIn,
        "seam:storedIn exactly one store, a deploy:SemPKM store",
    ),
    (
        "an accepted shape with no target class",
        replace("sh:targetClass :Vendor ;", ""),
        SHAPE,
        SH.targetClass,
        "exactly one sh:targetClass",
    ),
    (
        "an accepted shape with two target classes",
        replace("sh:targetClass :Vendor ;", "sh:targetClass :Vendor , :Supplier ;"),
        SHAPE,
        SH.targetClass,
        "exactly one sh:targetClass",
    ),
    ("no path", replace(PATH + " ;", ""), CHANNEL, COMM.path, "exactly one comm:path"),
    (
        "two paths",
        replace(PATH, PATH + ' , [ a hydra:IriTemplate ; hydra:template "/sempkm/other" ]'),
        CHANNEL,
        COMM.path,
        "exactly one comm:path",
    ),
    (
        "a path with a mapping",
        replace(
            PATH,
            'comm:path [ a hydra:IriTemplate ; hydra:template "/sempkm/{vendor}" ; '
            'hydra:mapping [ hydra:variable "vendor" ; hydra:property :id ] ]',
        ),
        CHANNEL,
        COMM.path,
        "exactly one comm:path",
    ),
    (
        "two channels of one container sharing a path",
        append(OTHER),
        API,
        COMM.path,
        "different comm:path templates",
    ),
    (
        "no exposing container",
        replace(":api seam:exposes :vendor_changes ;", ":api"),
        CHANNEL,
        SEAM.exposes,
        "Exactly one container seam:exposes",
    ),
    (
        "two exposing containers",
        seams_graph(':web seam:exposes :vendor_changes .\n    :web a arch:Container ; rdfs:label "Web" .'),
        CHANNEL,
        SEAM.exposes,
        "Exactly one container seam:exposes",
    ),
    (
        "a publisher",
        seams_graph(f"{TASK} seam:publishesTo :vendor_changes ."),
        CHANNEL,
        SEAM.publishesTo,
        "SemPKM is its only publisher",
    ),
    ("no subscriber", replace(START, ""), CHANNEL, SEAM.subscribesTo, "a channel with no subscriber is a fault"),
    (
        "a subscriber the receiving container does not execute",
        replace(
            ":api seam:exposes :vendor_changes ;\n        seam:executes :vendor_check_process .",
            ":api seam:exposes :vendor_changes .\n    :worker seam:executes :vendor_check_process .\n"
            '    :worker a arch:Container ; rdfs:label "Worker" .',
        ),
        API,
        SEAM.executes,
        "seam:executes every process subscribed to it",
    ),
    ("no connecting binding", replace(URL, ""), API, DEPLOY.connectsTo, "deploy:connectsTo the SemPKM store"),
    (
        "no token binding",
        replace(
            ' ,\n                [ deploy:key "SEMPKM_TOKEN" ; deploy:secretRef <https://secrets.example.org/pkm-token> ;\n'
            '                  deploy:secretName "pkm-token" ; deploy:authenticatesTo :pkm ]',
            "",
        ),
        API,
        DEPLOY.authenticatesTo,
        "exactly one binding that deploy:authenticatesTo",
    ),
    (
        "two token bindings",
        replace(
            URL,
            URL + ' [ deploy:key "SEMPKM_TOKEN_2" ; deploy:secretFile "secrets/t" ; deploy:authenticatesTo :pkm ] ,',
        ),
        API,
        DEPLOY.authenticatesTo,
        "exactly one binding that deploy:authenticatesTo",
    ),
    (
        "the accepted shape written by an executed process",
        seams_graph(f"{TASK} seam:writes :VendorShape ."),
        SHAPE,
        SEAM.writes,
        "the runtime's own writes must not start processes",
    ),
    (
        "a second transport",
        replace("comm:transport comm:SemPKMWebhook ;", "comm:transport comm:SemPKMWebhook , comm:SSE ;"),
        CHANNEL,
        COMM.transport,
        "exactly one comm:transport",
    ),
]


@pytest.mark.parametrize(("case", "edit", "subject", "predicate", "message"), CASES, ids=[c[0] for c in CASES])
def test_each_fault_raises_and_fails_the_shapes(
    tmp_path: Path,
    case: str,
    edit: Callable[[str], str],
    subject: URIRef,
    predicate: URIRef,
    message: str,
):
    path = write(tmp_path, edit)
    err = raises(path)
    assert (URIRef(err.subject), URIRef(err.predicate)) == (subject, predicate), case
    with pytest.raises(ResolutionError) as info:
        ModelGraph(path).webhook_channels()
    assert (URIRef(info.value.subject), URIRef(info.value.predicate)) == (subject, predicate)
    findings = webhook_findings(path)
    assert any(message in f for f in findings), findings


def test_a_token_as_a_plain_value_raises(tmp_path: Path):
    # The secret-ness of a token binding is seamsh:AuthenticatesToShape's (ADR-0025).
    path = write(tmp_path, replace(SECRET, 'deploy:value "abc"'))
    err = raises(path)
    assert (URIRef(err.subject), URIRef(err.predicate)) == (API, DEPLOY.authenticatesTo)
    assert "must take its value from a secret" in str(err)


def test_errors_name_the_fact(tmp_path: Path):
    err = raises(write(tmp_path, replace('comm:eventName "object.changed" ;', 'comm:eventName "edge.changed" ;')))
    assert "'object.changed'" in str(err) and "edge.changed" in str(err)
    err = raises(write(tmp_path, seams_graph(f"{TASK} seam:writes :VendorShape .")))
    assert str(PROCESS) in str(err) and str(API) in str(err)
