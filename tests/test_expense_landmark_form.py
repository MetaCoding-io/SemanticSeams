"""The expense form on the landmark page submits from the browser.

The "New Expense" form submits to POST /expenses/{expense}, and its
correlation key starts a new approval process instance. No component on the
page reads expenses scoped by that key, so Runtime.page_context binds nothing
to it. The generator used to emit ``hx-post="/expenses/{{ expense }}"``, which
rendered as ``/expenses/`` and failed. It now keeps ``{expense}`` literal and
adds an ``hx-on::config-request`` handler that replaces it with a fresh random
key on every submit. These tests render GET / for every process chapter,
replace the key the way that handler does, and post to the resulting path.
"""

import re
import secrets

import pytest

from expense_app import PROCESS_CHAPTERS, serve, status, until
from seams_gen.htmx import extract_page
from seams_runtime import ModelGraph

EXPENSE = {"description": "Train to Leeds", "amount": "42.50", "date": "2026-10-01"}
EMPLOYEE = {"X-Forwarded-User": "employee"}

FORM = re.compile(r'<form id="expense_form".*?hx-post="([^"]*)"\s+hx-on::config-request="([^"]*)"', re.S)


@pytest.mark.parametrize("chapter", PROCESS_CHAPTERS)
def test_landmark_form_submits_with_a_fresh_key(chapter, tmp_path, monkeypatch):
    with serve(chapter, tmp_path, monkeypatch) as (c, runtime):
        page = c.get("/", headers=EMPLOYEE)
        assert page.status_code == 200, page.text
        match = FORM.search(page.text)
        assert match, page.text
        path, handler = match.groups()
        assert path == "/expenses/{expense}"
        assert "replace('{expense}'" in handler and "crypto.getRandomValues" in handler

        keys = []
        for _ in range(2):
            key = secrets.token_hex(8)  # what the handler puts in place of {expense}
            r = c.post(path.replace("{expense}", key), data=EXPENSE, headers=EMPLOYEE)
            assert r.status_code == 200, r.text
            assert until(lambda: status(runtime, key)), f"no instance under {key}"
            keys.append(key)
        assert len(set(keys)) == 2


def test_a_bound_key_is_not_minted():
    """The chat app's conversation key is bound by the scoped message thread,
    so its form fills the key from the page, as before."""
    page = extract_page(ModelGraph.load("examples/chat-app/chat-app.trig"))
    [form] = [c for c in page.components if c.kind == "Form"]
    assert form.submit.mint == ()
    assert form.submit.path == "/conversations/{{ conversation }}/messages"
