# Seams — Product Brief (v1)

*This document answers the question both external reviews asked first: who is this for?*

## Primary user

**The application builder** — in two flavors sharing one need:

1. **The solo operator / indiehacker**: builds and runs everything themselves, wants *one model* from which the app, its API, its data contracts, and its deployment all derive. Their pain: every project is five disconnected artifact piles (frontend code, backend code, schema, docs, compose files) that drift apart the week after launch.
2. **The enterprise modernizer** (secondary, later): an organization that wants to *start modeling* its applications — same graph, same viewer, arriving via architecture review rather than app building.

v1 optimizes for the solo operator. Non-users we explicitly do not design for in v1: compliance auditors, BPM practitioners, ontology specialists. They may benefit; they don't drive decisions.

## The job-to-be-done

> "I describe my app once — screens, workflow, rules, data, where it runs — and I get a running, deployable application plus a living map of it I can click through and query."

## The organizing artifact: the tutorial

Development is organized around one end-to-end tutorial: **build a simple LLM chat app from a single model, ending in deployable artifacts** (`docs/tutorial/llm-chat-app.md`). Every milestone is defined as "the tutorial works through step N." The tutorial model replaces `checkout.ttl` as the product acceptance test (checkout remains as an ontology smoke test).

This amends the earlier "read-only browser only" v1 scope: **generation is on the critical path**, because the persona's payoff is `docker compose up`, not browsing. Still deferred: graphical *editing* (the tutorial's authoring story is "write this Turtle," acceptable for early adopters), BPMN *execution* engines, CMMN, editing-grade IFML tooling.

## Success criteria

A builder who has never seen RDF can follow the tutorial and, at the end:
1. run `docker compose up` and chat with an LLM through an app they modeled, never hand-wrote;
2. open the Seams viewer, click from architecture → chat screen → send-message workflow → data contract in under 60 seconds;
3. run the canned query "what writes Message?" and see the full UI-event → task → operation path;
4. see model-health warnings if they break a seam (trust is the product).

## Named design principle: RDF invisibility

Users never see Turtle, IRIs, or vocabulary names in the viewer. Internal names stay precise (`ifml:`, `sh:NodeShape`, `hydra:Operation`); user-facing labels are product language: *Screens & interactions, Workflow, Business rules, Data contract, API operation, Policy, Runtime location*. The semantic stack is the engine, not the dashboard. (Authoring in Turtle is the one sanctioned exception until form-based authoring exists — framed as "writing code," which builders already do.)

## Non-goals for v1

No graphical model editing; no BPMN engine integration; no multi-user collaboration; no importing existing codebases; no attempt at lossless IFML/XMI interchange.
