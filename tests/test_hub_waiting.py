"""A Tell to an agent waits on the document until that agent next calls `documents` (SPEC 9.8, D26, 10.5, 12).

Over the HTTP door with fake agent tokens: the full loop, the token's stable `id` as the key, isolation between
tokens and between members, the transitions under one lock, and the diagnostics rows."""
import threading

import pytest

from helpers import BEA, CAL, call, comment, hub_rows, ok, refused
from sheafmd.hub.state import Tokens
from test_hub_target import DOC, agent, members, pick, row

SECOND = "{agent} has this comment waiting already: cancel it first, or reply in the thread."


@pytest.fixture
def talk(plan):
    comment(plan)
    return plan


def agent_token(name="ada-chatgpt", client="ChatGPT", **kw):
    return Tokens().add(name, client=client, **kw)


def tell(browser, **body):
    return browser.post("/_/tell", {"doc": DOC, "id": "c1", **body})


def documents(browser, token, **args):
    return ok(browser, "documents", token=token, **args)


def target(browser, name="ada-chatgpt"):
    assert pick(browser, f"agent:{name}").status == 200


def tab(hub):
    return hub.entry(DOC).bus.subscribe()


def named(evs, name):
    return [d for n, d in evs if n == name]


# ── the full loop ────────────────────────────────────────────────────────────

def test_a_tell_to_an_agent_waits_is_listed_first_and_ends_on_its_action_reply(browser, talk):
    token = agent_token()
    target(browser)
    sub = tab(browser.hub)
    assert tell(browser).status == 200
    assert named(sub.drain(), "tell-queued") == [{"id": "c1", "agent": "ChatGPT (" + browser.hub.person + ")"}]
    first, = documents(browser, token)
    assert first["doc"] == DOC
    t, = first["tells"]
    assert t["thread"] == "c1" and "Why pears?" in t["message"] and 'role="action"' in t["message"]
    assert named(sub.drain(), "tell-seen") == [{"id": "c1"}]
    assert documents(browser, token)[0]["tells"][0]["id"] == t["id"]       # listed again, seen once
    assert named(sub.drain(), "tell-seen") == []
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", role="action", token=token)
    assert "tells" not in documents(browser, token)[0]
    assert named(sub.drain(), "tell-done") == [{"id": "c1"}]
