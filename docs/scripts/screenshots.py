"""Retake the viewer screenshots in the docs guide and the project site.

Each shot is a viewer URL, optional clicks, and an output name. Run three
viewers first (the chat app, expense chapter 11, and an edit-mode copy of
chapter 8), then this script:

    mkdir -p /tmp/shots/examples/expenses
    cp -r examples/expenses/chapter-08 /tmp/shots/examples/expenses/
    git ls-files '*pyproject.toml' uv.lock | xargs -I{} cp --parents {} /tmp/shots/
    uv run uvicorn viewer.app:app --port 8791 &
    SEAMS_MODEL=examples/expenses/chapter-11 uv run uvicorn viewer.app:app --port 8792 &
    SEAMS_MODEL=/tmp/shots/examples/expenses/chapter-08 SEAMS_EDIT=1 uv run uvicorn viewer.app:app --port 8793 &
    uv run playwright install chromium   # once
    uv run python docs/scripts/screenshots.py [NAME...]

It writes docs/guide/img/<name>.webp (cwebp must be on PATH) and copies the
descent shots to site/img/. The edit-mode copy keeps the repository's
relative layout so the Dockerfile build-context check passes in the preview. Set PLAYWRIGHT_CHROMIUM to a Chromium executable
when the Playwright package and its downloaded browser builds differ.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
GUIDE_IMG = ROOT / "docs" / "guide" / "img"
SITE_IMG = ROOT / "site" / "img"
CHAT = "http://localhost:8791"
CH11 = "http://localhost:8792"
EDIT = "http://localhost:8793"
C = "https://example.org/chat/"
E = "https://example.org/expenses/"
WIDTH, HEIGHT = 1280, 710


def view(base: str, iri: str, query: str = "") -> str:
    return f"{base}/view/{quote(iri, safe='')}{query}"


@dataclass
class Shot:
    name: str
    url: str
    clicks: list[str] = field(default_factory=list)
    wait_for: str | None = None
    site: bool = False
    height: int = HEIGHT
    scroll_to: str | None = None


SHOTS = [
    Shot("viewer-architecture", view(CHAT, C + "chat_architecture"), site=True, height=900),
    Shot("viewer-interaction", view(CHAT, C + "chat_ifml"), site=True),
    Shot("viewer-process", view(CHAT, C + "chat_bpmn"), wait_for=".djs-container", site=True),
    Shot("viewer-disambiguation", view(CHAT, C + "routing_decision"), site=True),
    Shot(
        "viewer-decision-table",
        view(CHAT, C + "routing_dmn"),
        clicks=[".drill-down-overlay"],
        wait_for=".tjs-table, .dmn-decision-table-container",
        site=True,
    ),
    Shot(
        "viewer-impact-question",
        view(CHAT, C + "db01"),
        clicks=["#query-catalog a.query-button"],
        wait_for="#query-results table, #query-results li",
        site=True,
    ),
    Shot("viewer-layers", f"{CHAT}/layers", site=True, height=900),
    Shot("viewer-generation", f"{CHAT}/generation/{quote(C + 'send_message', safe='')}", site=True),
    Shot(
        "viewer-storm",
        view(CHAT, C + "send_message_process"),
        clicks=["#storm-catalog a.storm-link"],
        wait_for="#storm-view *",
        scroll_to="#storm-catalog",
        height=900,
    ),
    Shot(
        "viewer-sequence",
        view(CHAT, C + "send_message"),
        clicks=["#sequence-catalog a.sequence-link"],
        wait_for="#sequence-view svg",
        scroll_to="#sequence-catalog",
        height=900,
    ),
    Shot("viewer-context-map", view(CH11, E + "expense_architecture", "?level=L1"), site=True, height=1000),
    Shot("viewer-type-pills", view(CH11, E + "ExpenseShape"), wait_for=".type-pill", height=260),
    Shot("viewer-edit-form", view(EDIT, E + "expense_list"), clicks=["text=Edit"], wait_for="form", site=True),
]


def take(page: Page, shot: Shot, png: Path) -> None:
    page.set_viewport_size({"width": WIDTH, "height": shot.height})
    page.goto(shot.url, wait_until="networkidle")
    for selector in shot.clicks:
        page.locator(selector).first.click()
        page.wait_for_load_state("networkidle")
    if shot.wait_for:
        page.locator(shot.wait_for).first.wait_for(timeout=10_000)
    page.wait_for_timeout(800)  # let bpmn-js, ELK and Mermaid finish drawing
    # Same model, same bytes: no machine's absolute paths in a committed image.
    page.evaluate(
        """root => {
          const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          for (let n = walk.nextNode(); n; n = walk.nextNode())
            n.nodeValue = n.nodeValue.split("file://" + root).join("").split(root).join("");
        }""",
        str(ROOT) + "/",
    )
    if shot.scroll_to:
        page.locator(shot.scroll_to).first.evaluate(
            "e => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 16)"
        )
        page.wait_for_timeout(300)
    page.screenshot(path=str(png))


def main(names: list[str]) -> int:
    shots = [s for s in SHOTS if not names or s.name in names]
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM") or None
    failed: list[str] = []
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch(executable_path=exe)
        page = browser.new_page()
        for shot in shots:
            png = Path(tmp) / f"{shot.name}.png"
            try:
                take(page, shot, png)
            except Exception as exc:  # report every failing shot, keep going
                failed.append(f"{shot.name}: {exc}".splitlines()[0])
                continue
            out = GUIDE_IMG / f"{shot.name}.webp"
            subprocess.run(["cwebp", "-quiet", "-q", "85", str(png), "-o", str(out)], check=True)
            if shot.site:
                shutil.copyfile(out, SITE_IMG / out.name)
            print(f"wrote {out.relative_to(ROOT)}")
        browser.close()
    for line in failed:
        print(f"failed {line}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
