# Vocabulary fixture: seam 2.0

A copy of `ontology/` (vocabularies and shapes) in which `seam` is at version 2.0 and
every other vocabulary is at 1.0, for the ADR-0021 load check and migration tests
(D060). Seam 2.0 renames `seam:inModel` to `seam:partOfModel`:
`migrations/seam/1-to-2.ru` rewrites the uses, and `seam:inModel` stays in the
vocabulary marked `owl:deprecated`. Seam 2.0 also deprecates the class `seam:Model`,
which the migration leaves alone, so a migrated model still meets a deprecation.
`shapes/seam-shapes.ttl` ends with one `sh:Warning` shape per deprecated term
(ADR-0021 section 6; tests/test_deprecation_shapes.py checks the pairing). Nothing outside the tests reads this tree; when
`ontology/` changes, copy the change here.
