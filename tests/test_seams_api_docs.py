"""The seams API reference page names every public name and view (M010/S07)."""

from pathlib import Path

import pytest
import seams

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs/reference/seams-library.md"
README = ROOT / "packages/seams/README.md"

VIEWS = (
    "architecture",
    "interfaces",
    "processes",
    "decisions",
    "shapes",
    "operations",
    "channels",
    "lifecycles",
    "policies",
)


@pytest.fixture(scope="module")
def page() -> str:
    assert PAGE.is_file(), f"missing API reference page {PAGE.relative_to(ROOT)}"
    return PAGE.read_text()


@pytest.mark.parametrize("name", seams.__all__)
def test_every_public_name_is_documented(page: str, name: str):
    # `name`, `name(`, `name.` or the qualified `seams.name` all count.
    assert f"`{name}" in page or f"`seams.{name}" in page, (
        f"seams.{name} is in seams.__all__ but not documented in {PAGE.relative_to(ROOT)}"
    )


@pytest.mark.parametrize("view", VIEWS)
def test_every_model_view_is_documented(page: str, view: str):
    assert hasattr(seams.Model, view), f"Model has no view property {view}; update VIEWS"
    assert f"`model.{view}" in page, f"view model.{view} is not documented in {PAGE.relative_to(ROOT)}"


def test_page_names_the_distribution_and_says_it_is_unpublished(page: str):
    assert "`semanticseams`" in page, "the page does not name the semanticseams distribution"
    assert "not published" in page, "the page does not say the library is not published"
    assert "uv sync --all-packages" in page, "the page does not show the workspace install"


def test_package_readme_links_to_the_reference():
    text = README.read_text()
    assert "seams-library.md" in text, f"{README.relative_to(ROOT)} does not link to seams-library.md"
