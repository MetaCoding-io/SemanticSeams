---
layout: home
title: SemanticSeams
titleTemplate: One RDF graph, every diagram a view

hero:
  name: SemanticSeams
  text: Diagrams are views. The graph is the source of truth.
  tagline: C4 architecture, IFML interaction, BPMN process, DMN decisions and SHACL data in one RDF graph, navigated by clicking from one notation into the next and queried across layers with SPARQL.
  actions:
    - theme: brand
      text: Get started
      link: /guide/getting-started
    - theme: alt
      text: The seams
      link: /concepts/the-seams
    - theme: alt
      text: GitHub
      link: https://github.com/MetaCoding-io/SemanticSeams

features:
  - title: Zooming in is a graph traversal
    details: Click a container and land on the interface it presents. Click an event and land on the process it triggers. Click a rule task and land on the decision table. The renderer changes with the notation of the node you clicked.
  - title: The seams are the product
    details: Twenty-five bridging predicates name the joins between layers, and each one must earn a cross-layer query. Inside a layer, the layer's own vocabulary does the work.
  - title: Native notations stay native
    details: BPMN and DMN keep their XML and render in bpmn-js and dmn-js. Only the elements that take part in a seam get an IRI, using the element's own ID as the IRI fragment.
  - title: Questions no single tool can answer
    details: Which screens can write this data? What breaks if this server goes away? Which tasks move an order out of this state? Each is one SPARQL query, shown as a button in the viewer.
  - title: The method applied to itself
    details: SHACL shapes constrain the seams. CI parses every file, validates the examples, proves the shapes reject broken seams, and asserts the exact rows every canned query returns.
  - title: Reference generated from the model
    details: The reference pages on this site are generated from the ontology, the shapes and the query catalog on every build, so they cannot drift from the files CI validates.
---
