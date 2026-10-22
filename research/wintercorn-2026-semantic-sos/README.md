# Research note: Wintercorn (2026), semantic interoperability in industrial systems of systems

*Status: open. Written 2026-10-22 from Part I of the thesis (the summary chapters); the appended papers were not available.*

*Why this note exists.* SemanticSeams puts every layer of a software system in one RDF graph, keeps each model in its own named graph, holds the cross-layer edges in a separate seams graph, and plans an as-deployed graph fed by monitoring so that drift is a SPARQL diff with semantics. This thesis built the as-deployed half of that picture for industrial service-oriented deployments, aligned it to two hand-authored engineering views, measured it, and wrote down what could not be made automatic. Sections 1 to 7 summarise the thesis in enough detail to cite from. Section 8 maps it onto SemanticSeams, ADR by ADR where one applies. `todos.md` beside this file lists what to do about it.

## 1. The source

Oskar Wintercorn, *Bridging Engineering and Operations: Semantic Interoperability in Industrial Systems of Systems*. Doctoral thesis, Cyber-Physical Systems, Department of Computer Science, Electrical and Space Engineering, Luleå University of Technology, 2026. Supervisors Jan van Deventer and Eric Chiquito. ISBN 978-91-8142-118-7 (pdf), ISSN 1402-1544. Funded by the Chips Joint Undertaking Arrowhead fPVN project (Grant Agreement 101111977).

The file read is Part I only (88 pages): the six summary chapters plus references. Part II, the six appended papers, is not in the file. Statements below about the individual papers come from the thesis's own Chapter 6 abstracts and from how Chapters 4 and 5 use them, not from the papers themselves. Public artifacts named by the thesis:

| Artifact | Where |
| --- | --- |
| Arrowhead Framework Ontology (AFO), source and IDO alignment | `github.com/oskwin/Arrowhead-Framework-Ontology` |
| Pump-station alignment use case: three bridge ontologies, `lis-ext`, instance data, synthetic generator, SPARQL queries | `github.com/oskwin/afo-alignment-use-case` |
| IDO pump-station use case | `github.com/PCA-POSC-Caesar-Association/IDO_Use_Case_Pumpstation` |
| IDO digital product description (chemical supply chain) | `github.com/PCA-POSC-Caesar-Association/IDO_Use_Case_Supply_Chain_in_Chemical_Industry` |

The OWL representations of DEXPI and of STEP AP4K that two of the bridges target are not public (Torbjörn Holm, Plant&Bytes, Semantum; Holm and Alexander Svensson).

## 2. The problem as the thesis states it

Connectivity is not interpretation. Industrial systems now exchange data and invoke each other's services freely (IIoT, cyber-physical systems, service-oriented architectures), but a service interface confirms that two systems are connected without recording why, what a failure would affect, or how the current configuration compares to an earlier one. The thesis uses Tolk and Muguira's Levels of Conceptual Interoperability Model (LCIM) to place itself: it works at level 3, semantic, above technical (1) and syntactic (2), and deliberately below pragmatic (4), dynamic (5) and conceptual (6).

The running example is one pump described three ways by three disciplines, each authoritative for its purpose and revised on its own schedule:

| View | Identifier | Maintained by | Organised around | Drifts how |
| --- | --- | --- | --- | --- |
| Run-time | service `pumpSpeed` | the deployment itself | what is currently configured, including which provider a consumer is actually bound to | does not drift (it is current by definition), but leaves no record of earlier states |
| Plant design (P&ID, DEXPI) | tag `123PU001`, a functional location | process engineer | positions where a function is required; the tag is stable while units come and go | gradually, as small modifications outpace drawing updates |
| Lifecycle record (STEP AP4K) | serial `Pump 24C01213`, a physical unit | maintenance / asset management | the object and its history across locations | event-driven, when an intervention goes unrecorded |

Nothing records how the three map. Engineers bridge them through personal familiarity, ad hoc conversion tables, or bespoke integrations, all of which describe the plant as it was, not as it is. The thesis's framing of the fix: the three descriptions are not duplicates from which one authoritative version could be picked. Each keeps distinctions the others have no reason to keep. So the goal is not a universal model but to make their connections explicit while each keeps its own semantics. The agreement required is narrower: each party relates its own vocabulary to a small, published reference vocabulary that none of them owns.

A second idea runs underneath: the functional location versus the physical unit occupying it. IEC 81346 formalises the separation of function, position and object as independently identified aspects. The thesis defines a functional location as a named, hierarchically arranged place where a function is performed and which successive units occupy over the plant's life. This distinction is the hinge of every cross-domain trace, and the thesis found it less firmly established in existing vocabularies than its centrality suggests.

## 3. Research questions and method

- **RQ1.** How can a practical, reusable semantic description of an industrial system of systems be generated from the running system and kept current as the deployment changes?
- **RQ2.** How can a shared reference ontology mediate alignment between independently developed domain models while preserving domain-specific semantics?
- **RQ3.** What reasoning, validation and representational capabilities does a run-time-generated, ontology-based representation enable, and what does each make possible?

Method is Peffers et al.'s design science research process (identify, define, design, demonstrate, evaluate, communicate) with explicit iteration loops. The primary evaluation instrument is competency questions (CQs): questions stated in the user's vocabulary, formulated before building to bound scope and retained afterwards as the pass criterion. A CQ counts as answered only when three conditions hold:

1. the query executes over the instantiated graph after reasoning and returns the expected bindings;
2. it required no modification to any source model and no separate consultation of a domain model outside the shared vocabulary;
3. where the question concerns an inferred relation, that relation appears in the reasoner's materialised output and not in the source graphs before alignment.

Condition 3 separates entailment from new knowledge: most of what an alignment entails is an asserted fact re-expressed in the shared vocabulary, and that re-expression is exactly what lets one query cross vocabularies that do not otherwise meet. Three further forms of evidence: scenario coverage (healthy, malformed instance data, degraded with a missing provider, recovery after replacement), reasoning cost at scale over synthetically generated instance data, and paired generation of two representations from the same deployment so differences are attributable to paradigm alone.

## 4. Contributions

### 4.1 The Arrowhead Framework Ontology (RQ1, Paper D)

An OWL 2 ontology of an Arrowhead local cloud: systems, their husk (interface) and unit assets, hosts and servers, provided and consumed services, core-system roles (service registry, orchestrator, authorisation). The graph is populated by a pipeline from the running deployment, not authored. Snapshots are timestamped RDF exported from live systems, loaded into GraphDB, validated with SHACL, enriched by OWL 2 reasoning, and queried with SPARQL for diagnosis and impact analysis (which systems depend on this provider; what a failed service would affect). Because regeneration is re-running a pipeline, the view cannot drift; the price is that it describes only what the deployment exposes, not intent or rationale. Some facts, such as which provider a consumer is actually bound to, are settled at run-time and could not appear in a design-time description however well maintained. Scope is deliberately bounded to deployment topology, service dependencies and core roles; not control logic, telemetry, or authorisation policy. Paper D also experiments with a natural-language interface that generates SPARQL.

The thesis declines the Asset Administration Shell (AAS) as its representation. An AAS describes one asset as a container of submodels whose elements get meaning by pointing at a dictionary entry, so meaning is by reference, not by axioms, and the structure is a per-asset hierarchy rather than a graph of relations among many things. The thesis needs relations across disciplines to be derivable rather than enumerated. It treats this as a difference of purpose, not quality, and Paper F includes a system that emits AAS representations from the run-time graph.

### 4.2 Reference-mediated alignment (RQ2, Paper E)

The Industrial Data Ontology (IDO, ISO 23726-3, POSC Caesar Association) is used as a reference-layer vocabulary (systems, functional objects, physical artefacts and their relations). Each of three domain models is related to IDO by a bridge ontology: AFO (run-time), a DEXPI-based plant-design model, and the STEP-derived AP4K lifecycle model. A bridge imports the domain vocabulary and the reference vocabulary and adds only the axioms needed to relate them, almost all subclass and subproperty statements. No bridge asserts equivalence, because a domain model routinely carries structure IDO does not represent; the narrower subsumption claim is enough to make domain instances discoverable through the reference vocabulary without discarding anything. No bridge relates any two domain models directly. The three bridges total 66 axioms.

IDO lacked the functional-location granularity needed, so the alignment adds a small extension, `lis-ext`: a functional-location class, a class for the physical unit that may occupy it, and the relation between the two. Every hop of the cross-domain trace passes through these three terms. Because `lis-ext` is authored within the work, it does not inherit IDO's stability.

Why a reference rather than pairwise mapping. Both leave sources intact and both support cross-domain interpretation. The decisive difference is maintenance under change: under pairwise mapping every model revision is every other model's concern; under reference mediation a revision touches only that model's own bridge. The arrangement concentrates volatile dependencies where change is frequent and local (the bridges) and shared dependencies where change is rare (the published standard). The thesis is careful about the counting argument: with three models, pairwise and mediated need the same number of mappings; counting favours mediation only from the fourth model, whereas the maintenance argument applies from the second.

Why the correspondences are curated, not mined. Automatic ontology matching has advanced (embedding- and language-model-based matchers), but on benchmarks unlike this setting: here correspondences are few, terms technical, and the engineers who know what a term means are available. More important is the failure mode: a reasoner applies a wrong subsumption without judgement and produces a confident result, materialised alongside every other inferred fact and indistinguishable from them, propagated into every query that crosses it. The burden sits on the correctness of a small number of statements, so the bridges assert the least that suffices.

The cost that cannot be removed. A bridge axiom relates terms, never individuals. Where two graphs share no identifier, value or assertion, no terminological axiom can connect them. The run-time and plant-design graphs are in exactly this position: the deployment was not configured by consulting the plant design, and the plant design does not record what was deployed. So two kinds of correspondence must be asserted explicitly per deployment: one relating each deployed run-time asset to the functional location it serves, and one (recorded as ordinary lifecycle practice) stating which unit occupies which location over which interval. Both point at plant-design individuals, so at the instance level the plant-design view is where the other two meet. The alignment reduces these assertions to one per deployed asset and one per recorded installation, in place of an integration per pair of models; it does not eliminate them.

A further step is outside alignment entirely. Reasoning derives the unit-to-location relation for every recorded installation, current and historical alike, because nothing in the shared vocabulary distinguishes them. The *currently* installed unit is identified by a separate SPARQL update that selects the installation with no recorded end. Its result is derived deployment state, not entailment, and it holds only for the graph on which the update last ran.

Reasoning requirements and cost. Most bridge axioms work under any rule set, but the unit-to-location relation is a property chain over the lifecycle record. OWL-Horst lacks property chains and leaves that leg of the trace silently absent; OWL 2 RL or equivalent is required. On synthetic pump stations, materialisation time grows linearly, about a quarter of a second per station on a single-board computer, and the fixed load cost is dominated by the domain ontologies rather than the bridges.

### 4.3 What the layer buys (RQ3, Papers C, D, F)

- **Querying and diagnosis** at the level of the composed system rather than one interface: dependency and impact questions the Arrowhead core services do not answer, since they exist for discovery and orchestration, not retrospective composed queries.
- **Inference** of relations nobody configured and that exist only because of how independently developed systems happen to be composed at a moment.
- **Validation** with SHACL under a closed-world reading, carried from Paper C's supply-chain setting into run-time snapshots: catching a graph that is consistent but incomplete or unsuitable. The open-world (OWL) versus closed-world (SHACL) distinction is treated as a methodological result in its own right.
- **Traceability** from a run-time observation to engineering and lifecycle information and back, extended in Paper F into a structural failure-modes-and-effects basis: a system consumes the run-time graph, runs a fixed query set, and reports dependent services, components shared across otherwise separate functions, and structural conditions such as a command issued with no feedback consumed. Severity, occurrence and detection remain the analyst's.
- **Representational form.** Paper F generates an RDF graph (AFO) and a SysML v2 model from the same deployment and evaluates both against shared CQs. RDF suited semantic integration, cross-boundary querying and reasoning; SysML v2 suited structure, interfaces and behaviour. The conclusion is complementarity, which the thesis says bounds its own claims: the case for ontologies is a case for specific capabilities, not for the formalism in general, and generating a formal description from a running system is not tied to the ontology approach.

### 4.4 How the program developed

Two initially separate strands converged. Paper A (IECON 2023) is systems engineering with no semantics: "indistinguishable twins", a digital and a physical twin of a fischertechnik factory behind the same Arrowhead services so external systems cannot tell which they talk to. Its lesson is that a useful digital representation must participate in the operational environment as a service, which motivated the run-time orientation. Papers B (SysCon 2025) and C (2026) built the semantic toolkit on hand-authored models: IDO as reference on a pump station, then OWL reasoning plus SHACL validation for supply-chain compliance (Digital Product Passport adjacent, IDO plus ChEBI). Papers D, E and F combine both strands.

## 5. Limitations the thesis states about itself

- Lifecycle stages covered are plant design, lifecycle records and run-time operation; not requirements elicitation, not decommissioning.
- Every demonstrator is laboratory scale and single organisation: a climate-control local cloud, a lab pump station, a second climate-control deployment of eleven systems and fifty services federated with the pump-station graph. No externally operated deployment.
- Cross-organisational interoperability is not evaluated, though Paper C's named graphs per business partner and the bridges' indifference to who asserted the data suggest no architectural restriction.
- Ground truth: the representations describe configured or declared state, not independently verified physical reality. Paper F states that trust in a run-time-generated representation is inseparable from trust in the pipeline that generates it, and that artifacts were checked for structural completeness rather than full semantic conformance.
- A limitation discovered only after alignment: the architecture relates three views, of which one stays current by construction and two do not. A trace is only as current as the least current model it crosses. Two further dependencies bound it the same way: "currently installed" is as current as the last update run, and the explicit correspondences reference plant-design individuals and survive only while those keep their identifiers across design revisions. The thesis notes this is the same drift it criticised in hand-maintained conversion tables, reduced in number but not made immune.

## 6. Future work, as five threads

1. Scale and external validation: richer plant structures, multiple clouds, longer maintenance histories, deployments the author did not build.
2. Reducing the manual steps: deriving the asset-to-location correspondence from commissioning records or tag conventions; deciding mechanically when a SHACL violation should reject a snapshot versus preserve an imperfect one for root-cause analysis (today a judgement call made by applying SHACL selectively).
3. Behavioural validation: joining the structural backbone to time-series observations from the running plant, moving from configured traceability to validation against what a deployment does.
4. Pipeline trust: conformance testing, assurance, and security and disclosure controls for operational knowledge graphs.
5. Standards reach: extending the run-time bridge to AAS submodels alongside AFO.

## 7. Reading the thesis's references for our purposes

Worth pulling directly: Tolk and Muguira (2003) on LCIM; ISO/DIS 23726-3 (IDO); IEC 81346-1:2022; DEXPI P&ID specification 1.4 (2024); Nagy, Wisnesky, Carlson, Subrahmanian and Zardini (2026), *A categorical approach to semantic interoperability across building lifecycle* (the thesis cites it for the linear-versus-quadratic mapping argument); Blair, Bencomo and France (2009), *Models@run.time*; Hedberg, Bajaj and Camelio (2020) on graphs linking data across the product lifecycle; Maier (1998) on architecting principles for systems of systems; Noy (2004) and Euzenat and Shvaiko (2013) on ontology alignment.

## 8. What it means for SemanticSeams

### 8.1 AFO is a worked as-deployed graph

`ontology/deploy.ttl` and ADR-0001 describe the loop SemanticSeams intends: the as-designed named graph is desired state, a reconciler emits artifacts, an observer writes actual state into `<urn:seams:graph:deployed>` from monitoring, and drift is a SPARQL diff between the two. Nothing in the repository yet writes the deployed graph. The Arrowhead Framework Ontology is that observer, built and evaluated:

| AFO (run-time, generated) | SemanticSeams today | Gap |
| --- | --- | --- |
| `System` with one husk and one or more unit assets | `arch:Container` / `arch:Component` | AFO separates the interface (husk) from the thing that does the work (unit asset); `arch:` does not |
| `Host` and `Server` | `arch:DeploymentNode`, `comm:Endpoint` | same concepts |
| provided and consumed services | `seam:exposes`, `seam:consumes` over `comm:Channel` and operations | same edges, but AFO's are observed bindings (which provider this consumer is *actually* bound to) whereas seams are designed ones |
| service registry, orchestrator, authorisation as core-system roles | not represented | an as-deployed graph of a real platform has platform roles; `deploy:` has none |
| timestamped snapshot per export, each a named graph | one `deployed` graph | history, and therefore "what was deployed when", is missing |
| SHACL validation of each snapshot before it is relied upon | `seam-shapes.ttl` validates the designed model only | no shapes for the deployed graph |
| OWL 2 RL materialisation to recover dependencies never configured | SPARQL property paths, no reasoner | fine today; see §8.5 |
| "what depends on this provider; what does a failed service affect" | `docs/queries/impact-of-node.rq` | the same competency question, answered over designed data here and over observed data there |

Two things to take directly. First, AFO's dependency facts are settled at run-time and *could not* appear in the designed graph however well it was maintained (which provider the orchestrator bound a consumer to). SemanticSeams's drift detection should expect legitimate differences of this kind, not only violations, and the diff needs a way to classify a difference as "design silent, deployment decided" rather than "design violated". Second, AFO's snapshots are timestamped named graphs, one per export. ADR-0001's single `deployed` graph should become a family, with "current" derived (see §8.3).

### 8.2 Seams are instance correspondences, and the thesis explains why they stay hand-asserted

A seam edge (`seam:triggers` from this `ui:Event` to that `proc:Process`) is an instance-level correspondence between elements of two independently authored models. The thesis's bridges are the other kind: class-level subsumptions into a reference. Its hard result is that the class-level kind cannot produce the instance-level kind: where two graphs share no identifier, value or assertion, no axiom can connect their individuals, and the correspondences must be asserted one per deployed asset. So the seams graph will always be authored or derived from a convention, never inferred from the layer vocabularies.

SemanticSeams already took the convention route: ADR-0002 makes the IRI fragment identical to the native element id (`:order_bpmn#persist_task`), and ADR-0006's drift lint checks the convention holds. That is precisely the thesis's proposed mitigation for its own manual step, "derive the correspondence from tag conventions or commissioning records". The thesis gives independent support for the decision and a name for what the lint protects: the identifier agreement that makes the two graphs share something an edge can act on. It also gives the failure mode to watch: the thesis's correspondences remain valid only while the referenced individuals keep their identifiers across design revisions. ADR-0002's migration rules are the equivalent safeguard, and the drift lint should be read as guarding it.

### 8.3 The third view: occupancy over time

The thesis relates three views; SemanticSeams has two (as-designed, as-deployed). The missing one is the lifecycle record: which physical unit occupied which functional location over which interval. In SemanticSeams terms, which `deploy:Artifact` version ran on which `arch:DeploymentNode` from when to when. Three transferable rules:

- Occupancy is a time-bounded record with a start and an optional end, asserted deliberately; it is a statement about a particular deployment at a particular time and cannot be derived from either the designed or the deployed graph alone.
- "What is deployed on db01 now" is a question about a moment; "what has been deployed on db01" is a historical question the same record must answer. A current-state graph cannot answer the second.
- "Current" is not entailed. The thesis derives it with a SPARQL update that selects the record with no end, and is explicit that the result is derived state that holds only for the graph the update last ran on. SemanticSeams should mark its "current deployment" view the same way rather than treating `<urn:seams:graph:deployed>` as self-evidently current.

### 8.4 A reference layer versus seams with layer-typed domains

`seam.ttl` types its predicates into the layer vocabularies (`seam:decidedBy` goes from `proc:BusinessRuleTask` to `dec:Decision`), and `seam-shapes.ttl` enforces that. The thesis's maintenance argument for reference mediation says: couple the volatile things (domain vocabularies) to the stable thing (a published reference) through thin bridges, so a change in one domain touches only its own bridge. In SemanticSeams, a change in a layer vocabulary touches the seam shapes, and a new layer (a seventh notation) touches the seam vocabulary's domains and ranges.

This is not a reason to adopt IDO; the thesis is careful that the counting argument only bites from the fourth model, and SemanticSeams has six layer modules already, so it may already bite. The planned methodology profiles (IDesign first, as SHACL shapes over the model) are structurally bridge ontologies: a profile's component taxonomy is a domain vocabulary that specialises `arch:` and adds constraints. Worth deciding on purpose, in an ADR, whether `seam:` is the reference layer (and layer vocabularies align to it) or the bridge layer (and something thinner above it is the reference). The thesis's rule that a bridge asserts subsumption, never equivalence, and the least that suffices, applies either way.

### 8.5 Reasoning, if it ever arrives

The canned queries use SPARQL property paths, so no entailment is needed and the thesis's reasoner requirement does not apply today. Two cautions for when inference is switched on in Fuseki or elsewhere:

- The cross-view trace in the thesis needs OWL 2 RL because one leg is a property chain; OWL-Horst drops it with no error. Any seam that is ever modelled as a chain (for instance `seam:triggers / seam:decidedBy / seam:invokes` collapsed into a derived "can reach" edge) has the same exposure.
- A wrong axiom produces a confident, materialised, indistinguishable inference. The thesis's answer is curated, minimal correspondences; the structural answer is to keep entailed triples in their own named graph so they can be dropped and regenerated. ADR-0001 has no `inferred` graph; it should, before any reasoner is enabled.

### 8.6 Competency questions are what the query catalog already is

`docs/queries/README.md` and `tests/test_acceptance.py` assert exact rows for three cross-layer queries so that a traversal can never silently regress to zero rows. That is competency-question evaluation in the thesis's sense. The thesis adds the pass criterion worth copying: the query runs with the expected bindings; no source model was modified and no model was consulted outside the shared vocabulary; and where the question concerns an inferred relation, it appears only after alignment. The second condition is the interesting one for SemanticSeams: a cross-layer query should be answerable from the seams graph plus the layer graphs without reaching into a `seam:renderPayload`. The acceptance test should say so.

### 8.7 Selective validation

The thesis's open question, when a SHACL violation should reject a snapshot and when an imperfect snapshot should be kept for root-cause analysis, is the question the as-deployed graph will raise on its first malformed monitoring export. The designed-model shapes can be strict (a model that fails `seam-shapes.ttl` is wrong). Deployed-graph shapes cannot be, because a malformed observation is itself information. The severity should be declared per shape (`sh:severity` is enough) with a stated policy: `sh:Violation` rejects the snapshot, `sh:Warning` records and keeps it.

### 8.8 SysML v2 as a sixth notation

Paper F generated an RDF graph and a SysML v2 model from the same deployment and found them complementary: RDF for cross-boundary query and reasoning, SysML v2 for structure, interfaces and behaviour. That is SemanticSeams's claim that notations are projections of one graph, with evidence from an independent group. SysML v2 has a textual notation and a standard API, so it fits the payload pattern (`seam:renderPayload` plus lifted seam-participating elements) the same way BPMN XML does. It would most naturally detail `arch:` elements. Whether to add `seam:SysMLv2` to the notation values is a decision to take deliberately, not a default.

### 8.9 Two ideas to borrow from the AAS argument

The thesis declines the Asset Administration Shell because meaning there is established by pointing at a dictionary entry rather than by axioms, and the structure is a per-asset hierarchy rather than a graph of relations. SemanticSeams's `seam:renderPayload` is a controlled use of the same "meaning by pointing" pattern: native XML is opaque to the graph by design, and only seam-participating elements get IRIs. The thesis's argument is the reason to keep lifting more elements when a cross-layer question needs them, and the drift lint (ADR-0006) is what keeps the lifted and unlifted halves consistent. The thesis's other observation, that a digital twin keeps one representation current but does not relate it to the others, is SemanticSeams's pitch in one sentence: the other tools draw one layer each.

### 8.10 What not to take

The Arrowhead framework's local-cloud structure (service registry, orchestrator, authorisation as core systems; husk and unit asset per system) is specific to industrial automation. IDO's functional-object and physical-artefact vocabulary is about plants. The patterns transfer; the terms mostly do not, except possibly for the as-deployed graph where a real platform's roles have to be represented anyway.
