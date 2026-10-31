"""A small process-less model (D026), shared by the runtime-write, FastAPI and
compose generator tests: an API container exposes a POST and a GET operation,
a portal presents one IFML page whose form seam:writes :ExpenseShape and
whose event seam:submitsTo the POST. No arch:Container seam:executes a
proc:Process, so only the write rule makes :expense_api serve routes.
"""

from pathlib import Path

EXPENSES = "https://example.org/expenses/"

SUBMITS = "    :submit_expense seam:submitsTo :submit_expense_op .\n"

TRIG = (
    """\
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:     <http://www.w3.org/ns/shacl#> .
@prefix hydra:  <http://www.w3.org/ns/hydra/core#> .
@prefix seam:   <https://w3id.org/seams/seam#> .
@prefix arch:   <https://w3id.org/seams/arch#> .
@prefix ifml:   <https://w3id.org/seams/ifml#> .
@prefix state:  <https://w3id.org/seams/state#> .
@prefix comm:   <https://w3id.org/seams/comm#> .
@prefix deploy: <https://w3id.org/seams/deploy#> .
@prefix :       <https://example.org/expenses/> .

<urn:seams:graph:model:expense_architecture> {
    :expense_architecture a seam:Model ; rdfs:label "Expense Architecture" .
    :expense_system a arch:System ; rdfs:label "Expenses" ;
        arch:contains :expense_portal , :expense_api ;
        seam:inModel :expense_architecture .
    :expense_portal a arch:Container ; rdfs:label "Expense Portal" ;
        deploy:artifact [ a deploy:Artifact ; deploy:reference "ghcr.io/example/expense-portal" ;
                          deploy:version "0.1.0" ] ;
        deploy:port [ a deploy:Port ; deploy:containerPort 8000 ; deploy:publishedPort 8080 ] ;
        seam:inModel :expense_architecture .
    :expense_api a arch:Container ; rdfs:label "Expense API" ;
        deploy:artifact [ a deploy:Artifact ; deploy:reference "ghcr.io/example/expense-api" ;
                          deploy:version "0.1.0" ] ;
        deploy:port [ a deploy:Port ; deploy:containerPort 8000 ] ;
        seam:inModel :expense_architecture .
}

<urn:seams:graph:model:expense_ifml> {
    :expense_ifml a seam:Model , ifml:InteractionModel ; rdfs:label "Expense Interface" ;
        ifml:contains :expense_page .
    :expense_page a ifml:ViewContainer ; rdfs:label "Expenses" ;
        ifml:isLandmark true ; ifml:path "/" ;
        ifml:contains :expense_list , :expense_form ;
        seam:inModel :expense_ifml .
    :expense_list a ifml:Details ; rdfs:label "Expenses" ; ifml:order 0 ; seam:inModel :expense_ifml .
    :expense_form a ifml:Form ; rdfs:label "New Expense" ; ifml:order 1 ;
        ifml:hasEvent :submit_expense ;
        ifml:hasParameter :description_input ;
        seam:inModel :expense_ifml .
    :description_input a ifml:Parameter ; rdfs:label "description" ;
        ifml:boundTo :description ; seam:inModel :expense_ifml .
    :submit_expense a ifml:Event ; rdfs:label "Submit Expense" ;
        ifml:trigger "submit" ; seam:inModel :expense_ifml .
    :submit_to_list a ifml:NavigationFlow ;
        ifml:source :submit_expense ; ifml:target :expense_list ;
        ifml:swap ifml:Append ; seam:inModel :expense_ifml .
}

<urn:seams:graph:model:expense_data> {
    :expense_data a seam:Model ; rdfs:label "Expense Data" .
    :ExpenseShape a sh:NodeShape ; rdfs:label "Expense" ;
        sh:property [ sh:path :description ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ;
                      sh:maxLength 200 ; sh:order 0 ] ;
        sh:property [ sh:path :status ; sh:datatype xsd:string ; sh:maxCount 1 ; sh:order 1 ;
                      sh:in ( "draft" "submitted" ) ] ;
        seam:inModel :expense_data .
}

<urn:seams:graph:model:expense_lifecycle> {
    :expense_lifecycle a state:StateMachine , seam:Model ; rdfs:label "Expense Lifecycle" ;
        state:initial :s_draft ;
        state:hasState :s_draft , :s_submitted ;
        state:hasTransition :t_submit .
    :s_draft a state:State ; rdfs:label "draft" ; seam:inModel :expense_lifecycle .
    :s_submitted a state:State ; rdfs:label "submitted" ; seam:inModel :expense_lifecycle .
    :t_submit a state:Transition ; state:from :s_draft ; state:to :s_submitted ;
        state:trigger "submit" ; seam:inModel :expense_lifecycle .
}

<urn:seams:graph:seams> {
    :expense_portal seam:presents :expense_ifml ;
        seam:consumes :submit_expense_op , :list_expenses_op .
    :expense_api seam:exposes :submit_expense_op , :list_expenses_op .
"""
    + SUBMITS
    + """\
    :submit_expense_op seam:rendersComponent :expense_list .
    :list_expenses_op seam:rendersComponent :expense_list .
    :expense_list seam:reads :ExpenseShape .
    :expense_form seam:writes :ExpenseShape .
    :ExpenseShape seam:lifecycle :expense_lifecycle .

    :submit_expense_op a hydra:Operation ; rdfs:label "Submit Expense" ;
        hydra:method "POST" ;
        seam:acceptsShape :ExpenseShape ;
        seam:returnsShape :ExpenseShape ;
        seam:mediaKind seam:UIFragment ;
        comm:requestMediaType "application/x-www-form-urlencoded" ;
        comm:path [ a hydra:IriTemplate ; hydra:template "/expenses" ] .
    :list_expenses_op a hydra:Operation ; rdfs:label "List Expenses" ;
        hydra:method "GET" ;
        seam:returnsShape :ExpenseShape ;
        seam:mediaKind seam:UIFragment ;
        comm:path [ a hydra:IriTemplate ; hydra:template "/expenses" ] .
}
"""
)


def write_model(directory, *, submits: bool = True) -> Path:
    """Write expenses.trig into ``directory``; ``submits=False`` drops the
    event's seam:submitsTo, leaving no serving container."""
    text = TRIG if submits else TRIG.replace(SUBMITS, "")
    path = Path(directory) / "expenses.trig"
    path.write_text(text, encoding="utf-8")
    return path
