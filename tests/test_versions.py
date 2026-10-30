"""seams_gen and seams_runtime carry a __version__ equal to their pyproject version (M012/S02/T01, D043).

Both members are virtual (D033) and never installed, so importlib.metadata
cannot read them; the module constant is the source and this test pins it.
"""

import tomllib
from pathlib import Path

import pytest

import seams_gen
import seams_runtime

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("module", [seams_gen, seams_runtime], ids=lambda m: m.__name__)
def test_version_matches_pyproject(module):
    pyproject = tomllib.loads((ROOT / module.__name__ / "pyproject.toml").read_text())
    assert module.__version__ == pyproject["project"]["version"]
    assert "__version__" in module.__all__
