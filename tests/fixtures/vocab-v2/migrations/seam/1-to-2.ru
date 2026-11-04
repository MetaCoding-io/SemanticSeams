# Test fixture (tests/fixtures/vocab-v2): seam 1 to 2 renames seam:inModel to
# seam:partOfModel. Each triple stays in its named graph (ADR-0021 section 4).
PREFIX seam: <https://w3id.org/seams/seam#>

DELETE { GRAPH ?g { ?s seam:inModel ?o } }
INSERT { GRAPH ?g { ?s seam:partOfModel ?o } }
WHERE  { GRAPH ?g { ?s seam:inModel ?o } }
