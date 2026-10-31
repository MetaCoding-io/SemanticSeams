"""The vocabularies a seams model is written in, as rdflib Namespaces."""

from __future__ import annotations

from rdflib import Namespace

SEAM = Namespace("https://w3id.org/seams/seam#")
COMM = Namespace("https://w3id.org/seams/comm#")
DEC = Namespace("https://w3id.org/seams/dec#")
PROC = Namespace("https://w3id.org/seams/proc#")
STATE = Namespace("https://w3id.org/seams/state#")
HYDRA = Namespace("http://www.w3.org/ns/hydra/core#")
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
DEPLOY = Namespace("https://w3id.org/seams/deploy#")
IFML = Namespace("https://w3id.org/seams/ifml#")
ARCH = Namespace("https://w3id.org/seams/arch#")
DASH = Namespace("http://datashapes.org/dash#")
VERIFY = Namespace("https://w3id.org/seams/verify#")


def local_name(iri: object) -> str:
    """The part of an IRI after its last '#' or '/'."""
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
