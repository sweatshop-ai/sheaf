"""Read-through over the real channel (ticket 23): the `read` and `comment` verbs a client tiroir answers, and the call an
agency tiroir makes. The two ends are tested apart here, in memory through the handler; the two-hub run is CI's."""
import io
import json
import urllib.error
from dataclasses import replace

import pytest
from test_peer_channel import BEA, PEER, channel, keyring, members, peer_token  # noqa: F401  (fixtures)

from sheafmd import connect
from sheafmd.hub import channel as channel_mod
from sheafmd.hub import outgoing


def test_read_and_comment_need_the_read_scope_and_a_transfer_only_peer_gets_the_answer_of_no_route(members):  # noqa: F811
    assert channel_mod.VERBS["read"] == channel_mod.VERBS["comment"] == "read"
    transfer_only = peer_token()
    for verb in ("read", "comment"):
        assert channel(members, verb, {"as": "bea@example.com", "op": "sheaf"}, transfer_only).status == 404
        assert channel(members, verb, {"as": "bea@example.com", "op": "sheaf"}, peer_token(["read"])).status == 200


def test_a_read_for_a_member_there_is_none_of_answers_as_a_read_with_no_identity(members):  # noqa: F811
    token = peer_token(["read"])
    unknown = channel(members, "read", {"as": "nobody@example.com", "op": "sheaf"}, token)
    missing = channel(members, "read", {"op": "sheaf"}, token)
    assert unknown.status == missing.status == 200
    assert unknown.json() == missing.json()


class Opened:
    def __init__(self, status, body):
        self.status, self.body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        return self.body[:n] if n > 0 else self.body


@pytest.fixture
def opener(monkeypatch):
    """What `outgoing.call` sends through: the requests it made, and the answer each is given."""
    sent, answers = [], []

    class Fake:
        def open(self, req, timeout=None):
            sent.append((req.full_url, req.get_header("Authorization"), json.loads(req.data), timeout))
            got = answers.pop(0)
            if isinstance(got, Exception):
                raise got
            return got

    monkeypatch.setattr(connect, "_NO_REDIRECT", Fake())
    return sent, answers


def test_the_call_posts_the_verb_with_the_peer_token_kept_for_the_origin_and_returns_status_and_answer(keyring, opener):  # noqa: F811
    sent, answers = opener
    keyring.items[(connect.PEER_SERVICE, PEER)] = "sheaf_mcp_x"
    answers.append(Opened(200, b'{"ok": true}'))
    assert outgoing.call(PEER, "read", {"as": "a@b.c"}) == (200, {"ok": True})
    assert sent == [(f"{PEER}/_/tiroir/read", "Bearer sheaf_mcp_x", {"as": "a@b.c"}, outgoing.SECONDS)]


def test_a_refusal_is_its_status_and_no_token_no_answer_or_a_reply_that_is_not_json_is_an_oserror(keyring, opener):  # noqa: F811
    sent, answers = opener
    with pytest.raises(OSError):
        outgoing.call(PEER, "read", {})
    assert sent == []
    keyring.items[(connect.PEER_SERVICE, PEER)] = "sheaf_mcp_x"
    answers.append(urllib.error.HTTPError(PEER, 404, "no", {}, io.BytesIO(b'{"ok": false}')))
    assert outgoing.call(PEER, "read", {}) == (404, {"ok": False})
    answers.append(Opened(200, b"<html>"))
    with pytest.raises(OSError):
        outgoing.call(PEER, "read", {})
    answers.append(urllib.error.URLError("down"))
    with pytest.raises(OSError):
        outgoing.call(PEER, "read", {})


def test_the_hub_calls_only_a_client_it_has_a_name_for(members):  # noqa: F811
    with pytest.raises(OSError, match="no client tiroir"):
        members.hub.peer_call("nowhere", "read", {})


def test_a_read_of_the_sheaf_whose_caller_has_gone_is_ended_with_a_499(members):  # noqa: F811
    members.hub.proxy.members[BEA] = replace(members.hub.proxy.members[BEA], agency=True)
    token = peer_token(["read"])
    body = {"as": "bea@example.com", "op": "sheaf"}
    assert channel(members, "read", body, token, gone=lambda: False).status == 200
    assert channel(members, "read", body, token, gone=lambda: True).status == 499
