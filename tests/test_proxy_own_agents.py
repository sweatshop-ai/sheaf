"""On the proxy socket a member Tells their own agents only (SPEC 9.9): two members share one document, each with an
agent of their own, and each sees, picks, Tells, cancels and is answered by their own, never the other's and never the
hub account's session."""
import os
import pwd
import threading

import pytest

from helpers import BEA, CAL, FRONT, Front
from sheafmd.hub import proxy
from sheafmd.hub.state import Tokens
from test_hub_target import DOC, pick, row
from test_hub_waiting import agent_token, documents, named, talk  # noqa: F401  (talk is a fixture)

LINE = "Let one of your agents work on this page to Tell it."


def both(work, bea=(), cal=()):
    """Bea and Cal share `work`: the same document is theirs both."""
    return proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                        "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                        "members": {BEA: {"name": "Bea", "roots": [str(work)], "tokens": list(bea)},
                                    CAL: {"name": "Cal", "roots": [str(work)], "tokens": list(cal)}}}, "the test")


@pytest.fixture
def pair(front, browser, talk, work):
    """Both members told one thread each: Bea's agent, Cal's, a loose one, and the hub person's own."""
    tokens = {n: agent_token(n, c) for n, c in (("bea-chatgpt", "ChatGPT"), ("cal-claude", "Claude"),
                                                ("loose", "Codex"), ("ada-chatgpt", "ChatGPT"))}
    front.hub.proxy = both(work, bea=["bea-chatgpt"], cal=["cal-claude"])
    front.tokens = tokens
    return front


def doc(front, member):
    got = front.get(f"/_/doc?doc={DOC}", member=member)
    assert got.status == 200, got.text
    return got.json()


def post(front, member, path, **body):
    return front.post(path, {"doc": DOC, "id": "c1", **body}, member=member)


class As:
    """A member's client: `pick` wants an object with `.post`."""
    def __init__(self, front, member):
        self.front, self.member = front, member

    def post(self, path, body):
        return self.front.post(path, body, member=self.member)


def pick_as(front, member, target):
    r = pick(As(front, member), target)
    assert r.status == 200, r.text


def test_each_member_is_offered_and_picks_only_their_own_agent_and_never_the_session_or_the_others(pair):
    assert doc(pair, BEA)["targets"] == [{"target": "agent:bea-chatgpt", "label": "ChatGPT (Bea)"}]
    assert doc(pair, CAL)["targets"] == [{"target": "agent:cal-claude", "label": "Claude (Cal)"}]
    for member, refused in ((BEA, ("session", "agent:cal-claude", "agent:loose", "agent:ada-chatgpt")),
                            (CAL, ("session", "agent:bea-chatgpt", "agent:loose", "agent:ada-chatgpt"))):
        for target in refused:
            r = pick(As(pair, member), target)
            assert r.status == 400 and r.json()["ok"] is False, (member, target)
    assert doc(pair, BEA)["target"] is None and doc(pair, CAL)["target"] is None


def test_each_member_tells_waits_and_cancels_only_their_own_and_the_other_page_never_hears_of_it(pair, browser):
    bea, cal = pair.tokens["bea-chatgpt"], pair.tokens["cal-claude"]
    pick_as(pair, BEA, "agent:bea-chatgpt")
    pick_as(pair, CAL, "agent:cal-claude")
    bea_tab, cal_tab = (pair.get(f"/_/live?doc={DOC}", member=m).stream for m in (BEA, CAL))
    assert post(pair, BEA, "/_/tell").status == 200 and post(pair, CAL, "/_/tell").status == 200
    heard = lambda sub: [(n, d) for n, d in sub.drain() if n.startswith("tell-")]
    assert heard(bea_tab) == [("tell-queued", {"id": "c1", "agent": "ChatGPT (Bea)"})]
    assert heard(cal_tab) == [("tell-queued", {"id": "c1", "agent": "Claude (Cal)"})]
    assert doc(pair, BEA)["telling"] == [{"id": "c1", "to": "ChatGPT (Bea)", "state": "queued"}]
    assert doc(pair, CAL)["telling"] == [{"id": "c1", "to": "Claude (Cal)", "state": "queued"}]
    assert [t["by"] for t in documents(browser, bea)[0]["tells"]] == ["Bea"]
    assert [t["by"] for t in documents(browser, cal)[0]["tells"]] == ["Cal"]
    assert post(pair, BEA, "/_/cancel").status == 200
    assert heard(bea_tab) == [("tell-seen", {"id": "c1"}), ("tell-cancelled", {"id": "c1", "seen": True})]
    assert heard(cal_tab) == [("tell-seen", {"id": "c1"})]                      # her own listing, nothing of Bea's end
    assert doc(pair, BEA)["telling"] == []
    assert doc(pair, CAL)["telling"] == [{"id": "c1", "to": "Claude (Cal)", "state": "seen"}]
    assert documents(browser, bea)[0]["tells"] == [] and documents(browser, cal)[0]["tells"]


def test_neither_member_nor_either_agent_sees_the_hub_persons_session_or_agent(pair, browser):
    pick_as(pair, BEA, "agent:bea-chatgpt")
    assert pick(browser, "agent:ada-chatgpt").status == 200
    assert browser.post("/_/tell", {"doc": DOC, "id": "c1"}).status == 200
    for member in (BEA, CAL):
        got = doc(pair, member)
        assert got["telling"] == [] and got["question"] == "" and "ada-chatgpt" not in str(got) and "(Ada)" not in str(got)
    assert pair.get(f"/_/doc?doc={DOC}", member=BEA).json()["target"]["token"] == "bea-chatgpt"
    assert [t["by"] for t in documents(browser, pair.tokens["bea-chatgpt"])[0]["tells"]] == []
    assert post(pair, BEA, "/_/cancel").status == 200                           # Bea has no Tell: the hub person's stays
    assert documents(browser, pair.tokens["ada-chatgpt"])[0]["tells"]


def test_a_cancel_that_comes_while_the_agent_lists_ends_bea_once_and_leaves_cal_untouched(pair, browser):
    bea = pair.tokens["bea-chatgpt"]
    pick_as(pair, BEA, "agent:bea-chatgpt")
    pick_as(pair, CAL, "agent:cal-claude")
    assert post(pair, BEA, "/_/tell").status == 200 and post(pair, CAL, "/_/tell").status == 200
    waiting, order, done = pair.hub.waiting_tells, [], []
    real = waiting._emit

    def emit(address, name, data, member=None):
        if name == "tell-seen" and not order:
            c = threading.Thread(target=lambda: (done.append(post(pair, BEA, "/_/cancel").status)))
            c.start()
            order.append(c)                                      # the cancel waits for the listing's lock
        real(address, name, data, member)
    waiting._emit = emit
    first = documents(browser, bea)[0]
    order[0].join(5)
    assert first["tells"] and done == [200]                      # one state wins: listed, then cancelled
    assert documents(browser, bea)[0]["tells"] == [] and doc(pair, BEA)["telling"] == []
    assert doc(pair, CAL)["telling"] == [{"id": "c1", "to": "Claude (Cal)", "state": "queued"}]
    assert documents(browser, pair.tokens["cal-claude"])[0]["tells"]


def test_a_cancel_first_leaves_the_agent_nothing_and_the_page_and_documents_agree(pair, browser):
    bea = pair.tokens["bea-chatgpt"]
    pick_as(pair, BEA, "agent:bea-chatgpt")
    assert post(pair, BEA, "/_/tell").status == 200 and post(pair, BEA, "/_/cancel").status == 200
    assert documents(browser, bea)[0]["tells"] == [] and doc(pair, BEA)["telling"] == []


@pytest.mark.parametrize("config", [{}, {"tokens": ["bea-nobody"]}])
def test_a_member_with_no_tokens_line_or_no_agent_token_gets_the_line_of_10_6_never_a_bare_400(pair, config):
    pair.hub.proxy = both(pair.hub.proxy.members[BEA].roots[0], bea=config.get("tokens", []), cal=["cal-claude"])
    r = post(pair, BEA, "/_/tell")
    assert r.status == 400 and r.json()["error"] == LINE
    c = pair.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": "Please.", "tell": True}, member=BEA)
    assert c.status == 400 and c.json()["error"] == LINE, c.text
    assert post(pair, BEA, "/_/cancel").status == 200


def test_jump_is_not_served_on_the_proxy_socket_to_either_member(pair):
    for member in (BEA, CAL):
        assert pair.post("/_/jump", {"doc": DOC, "id": "c1"}, member=member).status == 404
