# Vendored ontologies

Third-party ontologies a model may `owl:imports`, committed so that loading stays
offline and reproducible ([ADR-0022](../../docs/adr/0022-ontology-notation.md)
section 4). `seams.load` indexes each file here by the `owl:Ontology` IRI and the
`owl:versionIRI` in its header; a model's import must name a version IRI listed
below. The files are the releases unchanged: never edit one by hand. To vendor a new
release, add its file beside the old one and its row here.

| File | `owl:versionIRI` | Source | SHA-256 |
|---|---|---|---|
| `gistCore14.0.0.ttl` | `https://w3id.org/semanticarts/ontology/gistCore14.0.0` | [gist v14.0.0](https://github.com/semanticarts/gist/releases/tag/v14.0.0), `gist14.0.0_webDownload.zip`, `ontologies/gistCore14.0.0.ttl` | `fedce4d1f7d693930ed54bcfd9262fd868cb23faccc3435a1ef517709236b33b` |

## Licence

gist is © Semantic Arts, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), as the ontology header's
`gist:license` states. It is not covered by this repository's Apache-2.0 licence.
