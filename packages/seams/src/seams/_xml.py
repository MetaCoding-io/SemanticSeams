"""Reading the BPMN and DMN payload XML (lxml), shared by the resolvers and the views."""

from __future__ import annotations

import os

from lxml import etree


def elements(path: str | os.PathLike[str]):  # -> list of lxml elements (their type is private)
    """Every element of the XML file at ``path`` (comments and PIs left out)."""
    root = etree.parse(str(path)).getroot()
    return [el for el in root.iter() if isinstance(el.tag, str)]


def localname(tag: object) -> str | None:
    """The local name of an element tag; None for comments and PIs."""
    return etree.QName(tag).localname if isinstance(tag, str) else None
