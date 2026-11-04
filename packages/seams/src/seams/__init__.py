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
``unexercised_paths`` (BPMN paths no scenario runs), ``unfired_transitions``
and ``policies_without_deny``.

``seams.decisions_check`` finds decision faults the runtime would hit
(backlog K2): ``decision_findings`` lists DMN typeRefs that disagree with
their input's sh:datatype and gateway conditions that read a variable no
upstream decision or user task sets.

``seams.review_check`` runs the model review checks (backlog R1):
``review_findings`` lists sh:in lists that copy a lifecycle's state labels,
sh:class pointing at a sh:NodeShape, shapes without sh:targetClass and
sh:path IRIs nothing declares a property. A ``ReviewFinding`` flags the
model for review; it never refuses it.

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
models (ADR-0022) that ``load`` checks: an import names the version IRI of a
file vendored under ``ontology/vendor``, resolved offline; ``Model.imports``
lists the ``VendoredOntology``s resolved and ``Model.import_statuses`` the
``ImportStatus`` of each import. ``model.ontologies`` lists the ontology
models, their ``OntologyClass``es and each class's ``Superclass``es.

``seams.dmn`` reads DMN decision tables with lxml (``parse_dmn``,
``decision_table``); ``Decision.table`` joins one to its graph binding.
"""

from .context import ContextItem, Manifest, context_for
from .coverage import (
    ProcessPath,
    UndeniedPermission,
    policies_without_deny,
    process_paths,
    unexercised_paths,
    unfired_transitions,
)
from .decisions_check import DecisionFinding, condition_findings, decision_findings, type_ref_findings
from .dmn import DecisionTable, Rule, TableInput, TableOutput, decision_table, parse_dmn
from .errors import ResolutionError, SeamsError
from .graph import (
    IMPLEMENTATION_KINDS,
    RELATIONAL_STORE_KINDS,
    SEMPKM_GIST_VERSION,
    STORE_FINDING_SEVERITIES,
    SUPPORTED_STORE_KINDS,
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
    bpmn_start_event_ids,
    dmn_decision_ids,
    dmn_input_types,
)
from .loader import DEFAULT_ONTOLOGY_DIR, Model, load, model_hash, payload_path
from .namespaces import ARCH, COMM, DASH, DEC, DEPLOY, HYDRA, IFML, ODRL, PROC, SEAM, STATE, VERIFY, local_name
from .ontologies import (
    VENDOR_DIR,
    ImportStatus,
    VendoredOntology,
    check_imports,
    import_statuses,
    vendored_graph,
    vendored_ontologies,
)
from .review_check import ReviewFinding, review_findings
from .sparql import PREFIXES, load_question, question_names
from .views import (
    Architecture,
    Artifact,
    Binding,
    Build,
    Channel,
    Component,
    Container,
    Decision,
    DecisionExample,
    Deployment,
    DeploymentNode,
    Element,
    Environment,
    ErrorBoundary,
    Event,
    ExpectedOutput,
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
    "Architecture",
    "Artifact",
    "Binding",
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
    "Decision",
    "DecisionBinding",
    "DecisionExample",
    "DecisionFinding",
    "DecisionTable",
    "Deployment",
    "DeploymentNode",
    "Element",
    "Environment",
    "ErrorBoundary",
    "Event",
    "ExpectedOutput",
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
    "ODRL",
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
    "Transition",
    "UndeniedPermission",
    "VENDOR_DIR",
    "VERIFY",
    "VendoredOntology",
    "Volume",
    "bpmn_start_event_ids",
    "check_imports",
    "check_versions",
    "condition_findings",
    "context_for",
    "decision_findings",
    "decision_table",
    "declared_versions",
    "dmn_decision_ids",
    "dmn_input_types",
    "import_statuses",
    "load",
    "load_question",
    "local_name",
    "model_hash",
    "parse_dmn",
    "payload_path",
    "policies_without_deny",
    "process_paths",
    "question_names",
    "review_findings",
    "shipped_versions",
    "type_ref_findings",
    "unexercised_paths",
    "unfired_transitions",
    "vendored_graph",
    "vendored_ontologies",
    "version_iri",
]
