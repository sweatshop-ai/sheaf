"""The agency's "Clients" node in the Sheaf (SPEC 9.9): a child per client tiroir, drawn with no rows, whose rows are read through
when it is opened and replace the last ones; a client page's row has none of the owner's buttons; a client that does not answer is
one line. The hub's channel is a function here that answers for the client; every request is answered as Bea."""
import dataclasses

import pytest
from helpers import BEA
from test_mount_sheaf import agentview, mounted  # noqa: F401  (fixtures)
from test_mount_sheaf import pages as plain_pages  # noqa: F401

from sheafmd.hub import readthrough

pytestmark = pytest.mark.page

CLIENT_ROW = {"doc": "work/plan.md", "url": "/work/plan.md", "title": "Client plan", "root": "work", "folder": "work", "share": "x",
              "own": True, "archived": False, "kept": False, "mtime": 5.0, "when": "now", "open": 0, "write": "", "write_tip": "",
              "session": "", "session_tip": "", "session_link": None, "shared_by": ""}


@pytest.fixture
def answers():
    return {"call": lambda client, verb, body: (200, {"rows": [CLIENT_ROW], "tree": [], "more": {}})}


@pytest.fixture
def pages(plain_pages, answers):
    hub = plain_pages.hub
    me = hub.proxy.members[BEA]
    hub.proxy.members[BEA] = dataclasses.replace(me, email="bea@example.com", agency=True)
    hub.clients = readthrough.Clients({"acme": "https://acme.example.com"}, lambda *a: answers["call"](*a))
    return plain_pages


def test_the_node_is_drawn_with_no_client_row_until_it_is_opened(mounted):
    assert mounted.js("return !!root.querySelector('.sheaf-folder[data-client=\"acme\"]');") is True
    assert mounted.js("return root.querySelectorAll('.sheaf-row[data-client]').length;") == 0


def test_opening_the_node_shows_the_clients_rows_without_the_owners_buttons(mounted):
    mounted.click('.sheaf-folder[data-client="acme"]')
    rows = lambda: mounted.js("return Array.from(root.querySelectorAll('.sheaf-row[data-client=\"acme\"]')).map((r) => r.dataset.doc);")
    from pagehelp import until
    until(lambda: rows() == ["Clients/acme/work/plan.md"], what="the client's row")
    assert mounted.js("return root.querySelectorAll('.sheaf-row[data-client] .sheaf-share, .sheaf-row[data-client] .sheaf-act').length;") == 0


def test_a_client_that_does_not_answer_is_one_line_and_no_row(mounted, answers):
    def down(*a):
        raise OSError("down")
    answers["call"] = down
    mounted.click('.sheaf-folder[data-client="acme"]')
    from pagehelp import until
    until(lambda: "not reachable" in mounted.js("return root.querySelector('.sheaf-said').textContent;"), what="the line")
    assert mounted.js("return root.querySelectorAll('.sheaf-row[data-client]').length;") == 0
