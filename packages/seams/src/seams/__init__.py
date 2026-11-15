"""Semantic Seams library: read and validate Semantic Seams models.

``load`` and ``Model`` read a model. Its views (``model.architecture``,
``model.interfaces``, ``model.processes``, ``model.decisions``,
``model.operations``, ``model.channels``, ``model.shapes``,
``model.lifecycles``, ``model.policies``) answer with ``Many`` collections of
frozen ``Element`` dataclasses across every model of a layer; ``.only()``
asks for exactly one. The views supersede ``ModelGraph``'s one-of-each
resolvers (landmark_page, triggering_operation and the rest), which stay as
transitional methods. Their result types that share a name with a view class
(``Container``, ``Lifecycle``, ``Transition``) are imported from
``seams.graph``; the top-level names are the view classes.

``model.sparql(query, **bindings)`` runs read-only SPARQL with the project
prefixes bound, and ``model.question(name, **bindings)`` runs a bundled
canned question (``question_names()``).

``seams.coverage`` answers what no scenario or test exercises (D054):
``unexercised_paths`` (BPMN paths no scenario runs), ``unfired_transitions``,
``policies_without_deny`` and ``core_operations_untested`` (ADR-0030).

``seams.decisions_check`` finds decision faults the runtime would hit
(backlog K2): ``decision_findings`` lists DMN typeRefs that disagree with
their input's sh:datatype, gateway conditions that read a variable no
upstream decision or user task sets, and overlapping rules and uncovered
inputs of UNIQUE decision tables (backlog X13, ``table_findings``).

``seams.review_check`` runs the model review checks (backlog R1):
``review_findings`` lists sh:in lists that copy a lifecycle's state labels,
sh:class pointing at a sh:NodeShape, shapes without sh:targetClass and
sh:path IRIs nothing declares a property. A ``ReviewFinding`` flags the
model for review; it never refuses it.

``seams.observed`` loads recorded runs as an as-observed named graph
(ADR-0042), kept outside the model and its hash: ``observed_graph(runs)``
from ``ObservedRun``s or (run id, trace rows) pairs, ``spans_to_runs`` from
an OTLP JSON span export, and ``observed_question(model, graph, name)`` asks
``dead-model`` (flow nodes no run reached) or ``conformance`` (steps the
model does not explain) over a read-only union. ``budget_results(model,
graph)`` checks the model's ``nfr:LatencyBudget``s against the steps'
``obs:duration`` (ADR-0043) and returns sorted ``BudgetResult``s, each met,
missed or unobserved.

``seams.context`` assembles the context of a service task (backlog C3):
``context_for(model, task)`` returns a ``Manifest`` of hashed
``ContextItem``s (the model facts and native file fragments its code
depends on, narrowed to the ones it uses) and a context hash.

``seams.vocabularies`` runs the vocabulary version check (ADR-0021) that
``load`` applies: a model declares the vocabulary versions it targets as
``owl:imports`` in ``MANIFEST_GRAPH``; a newer one is refused, an older one is
migrated in memory with the SPARQL Update steps under ``ontology/migrations``,
and ``Model.migrations`` lists the ``MigrationStep``s applied.

``seams.ontologies`` resolves the ``owl:imports`` of ``seam:Ontology``
models (ADR-0022) that ``load`` checks: an import names the version IRI of
another ontology model in the same Dataset (ADR-0030 section 4) or of a file
vendored under ``ontology/vendor``, resolved offline; ``Model.dataset_imports``
lists the ``DatasetOntology``s and ``Model.imports`` the ``VendoredOntology``s
resolved, and ``Model.import_statuses`` the ``ImportStatus`` of each import. ``model.ontologies`` lists the ontology
models, their ``OntologyClass``es and each class's ``Superclass``es.

``seams.profiles`` resolves the domain profile a model attaches to with
``seam:conformsTo`` (ADR-0018, ADR-0033): ``resolve_profile(ds, model_dir)``
returns a ``Profile`` (offered classes, generators, labels, shapes, pill shapes).

``seams.dmn`` reads DMN decision tables with lxml (``parse_dmn``,
``decision_table``); ``Decision.table`` joins one to its graph binding.
"""

from .context import ContextItem, Manifest, context_for
from .coverage import (
    ProcessPath,
    UndeniedPermission,
    core_operations_untested,
    policies_without_deny,
    process_paths,
    unexercised_paths,
    unfired_transitions,
)
from .decisions_check import (
    DecisionFinding,
    condition_findings,
    decision_findings,
    table_findings,
    type_ref_findings,
)
from .dmn import DecisionTable, Rule, TableInput, TableOutput, decision_table, parse_dmn
from .errors import ResolutionError, SeamsError
from .graph import (
    IMPLEMENTATION_KINDS,
    RELATIONAL_STORE_KINDS,
    SEMPKM_GIST_VERSION,
    STORE_FINDING_SEVERITIES,
    SUPPORTED_STORE_KINDS,
    WEBHOOK_EVENT_TYPES,
    ChannelBinding,
    ChannelStart,
    DecisionBinding,
    Implementation,
    InputBinding,
    ModelGraph,
    OperationPath,
    OutputBinding,
    PathMapping,
    Permission,
    PolicyFacts,
    ProcessFacts,
    SemPKMPlan,
    StoreFinding,
    StorePlan,
    WebhookChannel,
    bpmn_start_event_ids,
    dmn_decision_ids,
    dmn_input_types,
)
from .loader import DEFAULT_ONTOLOGY_DIR, Model, load, model_dir, model_hash, payload_path
from .namespaces import (
    ARCH,
    COMM,
    DASH,
    DEC,
    DEPLOY,
    HYDRA,
    IFML,
    NFR,
    OBS,
    ODRL,
    PROC,
    SEAM,
    STATE,
    VERIFY,
    local_name,
)
from .observed import (
    BUDGET_VERDICTS,
    OBSERVED_QUESTIONS,
    BudgetResult,
    ObservedRun,
    budget_results,
    observed_graph,
    observed_ntriples,
    observed_question,
    spans_to_runs,
)
from .ontologies import (
    VENDOR_DIR,
    DatasetOntology,
    ImportStatus,
    VendoredOntology,
    check_imports,
    dataset_imports,
    dataset_ontologies,
    import_statuses,
    vendored_graph,
    vendored_ontologies,
)
from .profiles import Profile, resolve_profile
from .review_check import ReviewFinding, review_findings
from .sparql import PREFIXES, load_question, question_names
from .views import (
    Aggregate,
    Architecture,
    Artifact,
    Binding,
    BoundedContext,
    Build,
    Channel,
    Component,
    Container,
    Decision,
    DecisionExample,
    Deployment,
    DeploymentNode,
    Domain,
    Element,
    Environment,
    ErrorBoundary,
    Event,
    ExpectedOutput,
    Failure,
    Field,
    FlatNode,
    Flow,
    FlowNode,
    Given,
    Healthcheck,
    InteractionModel,
    Interfaces,
    Lifecycle,
    Lifecycles,
    Many,
    MessageStart,
    Ontology,
    OntologyClass,
    Operation,
    Override,
    Page,
    Parameter,
    ParameterBinding,
    PathTemplate,
    Policy,
    Port,
    Process,
    ProcessElement,
    Processes,
    Scenario,
    Shape,
    State,
    Status,
    Step,
    Superclass,
    System,
    TimerEvent,
    Transition,
    Volume,
)
from .vocabularies import (
    MANIFEST_GRAPH,
    MigrationStep,
    check_versions,
    declared_versions,
    shipped_versions,
    version_iri,
)

__all__ = [
    "ARCH",
    "Aggregate",
    "Architecture",
    "Artifact",
    "BUDGET_VERDICTS",
    "Binding",
    "BoundedContext",
    "BudgetResult",
    "Build",
    "COMM",
    "Channel",
    "ChannelBinding",
    "ChannelStart",
    "Component",
    "Container",
    "ContextItem",
    "DASH",
    "DEC",
    "DEFAULT_ONTOLOGY_DIR",
    "DEPLOY",
    "DatasetOntology",
    "Decision",
    "DecisionBinding",
    "DecisionExample",
    "DecisionFinding",
    "DecisionTable",
    "Deployment",
    "DeploymentNode",
    "Domain",
    "Element",
    "Environment",
    "ErrorBoundary",
    "Event",
    "ExpectedOutput",
    "Failure",
    "Field",
    "FlatNode",
    "Flow",
    "FlowNode",
    "Given",
    "HYDRA",
    "Healthcheck",
    "IFML",
    "IMPLEMENTATION_KINDS",
    "Implementation",
    "ImportStatus",
    "InputBinding",
    "InteractionModel",
    "Interfaces",
    "Lifecycle",
    "Lifecycles",
    "MANIFEST_GRAPH",
    "Manifest",
    "Many",
    "MessageStart",
    "MigrationStep",
    "Model",
    "ModelGraph",
    "NFR",
    "OBS",
    "OBSERVED_QUESTIONS",
    "ODRL",
    "ObservedRun",
    "Ontology",
    "OntologyClass",
    "Operation",
    "OperationPath",
    "OutputBinding",
    "Override",
    "PREFIXES",
    "PROC",
    "Page",
    "Parameter",
    "ParameterBinding",
    "PathMapping",
    "PathTemplate",
    "Permission",
    "Policy",
    "PolicyFacts",
    "Port",
    "Process",
    "ProcessElement",
    "ProcessFacts",
    "ProcessPath",
    "Processes",
    "Profile",
    "RELATIONAL_STORE_KINDS",
    "ResolutionError",
    "ReviewFinding",
    "Rule",
    "SEAM",
    "SEMPKM_GIST_VERSION",
    "STATE",
    "STORE_FINDING_SEVERITIES",
    "SUPPORTED_STORE_KINDS",
    "Scenario",
    "SeamsError",
    "SemPKMPlan",
    "Shape",
    "State",
    "Status",
    "Step",
    "StoreFinding",
    "StorePlan",
    "Superclass",
    "System",
    "TableInput",
    "TableOutput",
    "TimerEvent",
    "Transition",
    "UndeniedPermission",
    "VENDOR_DIR",
    "VERIFY",
    "VendoredOntology",
    "Volume",
    "WEBHOOK_EVENT_TYPES",
    "WebhookChannel",
    "bpmn_start_event_ids",
    "budget_results",
    "check_imports",
    "check_versions",
    "condition_findings",
    "context_for",
    "core_operations_untested",
    "dataset_imports",
    "dataset_ontologies",
    "decision_findings",
    "decision_table",
    "declared_versions",
    "dmn_decision_ids",
    "dmn_input_types",
    "import_statuses",
    "load",
    "load_question",
    "local_name",
    "model_dir",
    "model_hash",
    "observed_graph",
    "observed_ntriples",
    "observed_question",
    "parse_dmn",
    "payload_path",
    "policies_without_deny",
    "process_paths",
    "question_names",
    "resolve_profile",
    "review_findings",
    "shipped_versions",
    "spans_to_runs",
    "table_findings",
    "type_ref_findings",
    "unexercised_paths",
    "unfired_transitions",
    "vendored_graph",
    "vendored_ontologies",
    "version_iri",
]
