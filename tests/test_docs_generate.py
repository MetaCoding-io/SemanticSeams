"""docs/scripts/generate.py reads through the seams library and is deterministic."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest
import seams

SCRIPT = Path(__file__).resolve().parent.parent / "docs" / "scripts" / "generate.py"


@pytest.fixture(scope="module")
def generate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("docs_generate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before running: @dataclass looks its module up in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reads_through_seams(generate: ModuleType) -> None:
    assert generate.seams is seams
    assert generate.SEAM is seams.SEAM


def test_queries_page_has_one_section_per_seams_question(generate: ModuleType) -> None:
    page = generate.queries()
    anchors = re.findall(r"^## .* \{#([\w-]+)\}$", page, re.M)
    assert anchors == sorted(seams.question_names(), key=lambda n: n + ".rq")
    for name in seams.question_names():
        assert f"(../queries/{name}.rq)" in page


def test_unknown_question_is_rejected_by_the_catalog() -> None:
    with pytest.raises(KeyError):
        seams.load_question("../README")


def test_seam_predicates_is_deterministic(generate: ModuleType) -> None:
    assert generate.seam_predicates() == generate.seam_predicates()
