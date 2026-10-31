"""The docs embed the derived sequence goldens by snippet import, never by copy (M013/S03, D048)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SNIPPET = re.compile(r"^<<< @/(generation/sequences/\S+\.mmd)\{mermaid\}$", re.MULTILINE)

PAGES = {
    "concepts/diagrams-are-views.md": [
        "generation/sequences/chat-app/send_message.mmd",
        "generation/sequences/chat-app/send_message.executed.mmd",
    ],
    "tutorial.md": ["generation/sequences/chat-app/send_message.mmd"],
    "tutorials/expenses/08-growing-up.md": [
        "generation/sequences/expenses/submit_expense--auto.mmd",
        "generation/sequences/expenses/submit_expense--manager--approved.mmd",
    ],
}


@pytest.mark.parametrize("page,imports", PAGES.items())
def test_page_imports_its_goldens(page: str, imports: list[str]) -> None:
    text = (DOCS / page).read_text(encoding="utf-8")
    for target in imports:
        assert f"<<< @/{target}{{mermaid}}" in text.splitlines()
    found = SNIPPET.findall(text)
    assert sorted(found) == sorted(imports)
    for target in found:
        assert (DOCS / target).is_file(), target


def test_concept_page_has_no_inline_copy() -> None:
    text = (DOCS / "concepts/diagrams-are-views.md").read_text(encoding="utf-8")
    assert "%% derived from" not in text
    assert "sequenceDiagram" not in text


def test_snippet_with_unknown_lang_is_not_a_mermaid_import() -> None:
    assert not SNIPPET.search("<<< @/generation/sequences/chat-app/send_message.mmd{text}")
    assert not SNIPPET.search("<<< @/generation/sequences/chat-app/missing.txt{mermaid}")


def test_site_renders_mermaid() -> None:
    config = (DOCS / ".vitepress/config.ts").read_text(encoding="utf-8")
    theme = (DOCS / ".vitepress/theme/index.ts").read_text(encoding="utf-8")
    assert 'class="mermaid"' in config
    assert "mermaid@11" in theme
    assert 'securityLevel: "strict"' in theme
    assert "SidebarToggle" in theme
