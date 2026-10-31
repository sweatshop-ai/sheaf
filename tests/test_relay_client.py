"""`sheaf relay` (SPEC 9.14, sheaf#117): the member's side of the relay. The token is read from a 0600 file of the
user's own and never from argv; each Tell of the stream is handed to the session with its id as msg_id and acked;
`gone` or a refused token ends the relay. The network and the session are stand-ins here."""
import io
import json
import os
import urllib.error

import pytest

from sheafmd import relay_client as rc
from sheafmd.agents.base import DeliveryError

TOKEN = "sheaf_" "relay_" + "A" * 43        # two literals: one secret-shaped would stop the review runner (#53)
DOC = "work/thinkingtoo/tiroir/2026-10-28-contract.md"
SID = "7e8f9a0b-1c2d-4e3f-8a4b-5c6d7e8f9a0b"
TID = "11111111-2222-4333-8444-555555555555"


def token_file(tmp_path, text=TOKEN, mode=0o600):
    f = tmp_path / "relay-token"
    f.write_text(text + "\n", encoding="ascii")
    os.chmod(f, mode)
    return f


def test_a_0600_token_file_of_ones_own_is_read(tmp_path):
    assert rc.read_token(str(token_file(tmp_path))) == TOKEN


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_a_token_file_others_may_read_is_refused(tmp_path, mode):
    with pytest.raises(rc.Refused, match="chmod 600"):
        rc.read_token(str(token_file(tmp_path, mode=mode)))


def test_a_token_file_that_is_a_link_is_refused(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(token_file(tmp_path))
    with pytest.raises(rc.Refused, match="link"):
        rc.read_token(str(link))


def test_a_token_file_without_a_relay_token_is_refused(tmp_path):
    with pytest.raises(rc.Refused, match="no relay token"):
        rc.read_token(str(token_file(tmp_path, text="sheaf_code_" + "A" * 43)))


@pytest.mark.parametrize("flag", ["--token", "--token-file"])
def test_a_token_on_the_command_line_is_refused_and_never_printed(capsys, flag):
    assert rc.cmd_relay(["--hub", "https://front.example", "--doc", DOC, "--session", SID, flag, TOKEN]) == 2
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err and "--token-file FILE" in out.err


def test_events_are_read_from_the_stream_lines():
    raw = b"retry: 2000\n\nevent: hello\ndata: {}\n\n: keepalive\n\nevent: tell\ndata: {\"id\": 1}\n\n"
    assert list(rc.events(io.BytesIO(raw))) == [("hello", "{}"), ("tell", '{"id": 1}')]


class Net:
    """The front: one stream of `frames`, and every POST kept."""
    def __init__(self, *streams, refuse=None, ack=200):
        self.streams, self.refuse, self.ack, self.posts, self.gets = list(streams), refuse, ack, [], []

    def __call__(self, req, timeout=None):
        if req.get_method() == "POST":
            self.posts.append((req.full_url, dict(req.header_items()), json.loads(req.data)))
            ack = self.ack.pop(0) if isinstance(self.ack, list) else self.ack
            if isinstance(ack, Exception):
                raise ack
            if ack != 200:
                raise urllib.error.HTTPError(req.full_url, ack, "no", {}, io.BytesIO(b"{}"))
            return io.BytesIO(b'{"ok": true}')
        self.gets.append((req.full_url, dict(req.header_items())))
        if self.refuse or not self.streams:       # out of streams: a refused token, so a relay never spins here
            raise urllib.error.HTTPError(req.full_url, self.refuse or 401, "no", {}, io.BytesIO(b"{}"))
        return io.BytesIO(b"".join(rc_frame(n, d) for n, d in self.streams.pop(0)))


def rc_frame(name, data):
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


def relay(net, deliver):
    return rc.Relay("https://front.example", DOC, SID, TOKEN, "/tmp/none", opener=net, deliver=deliver,
                    sleep=lambda s: None)


def test_each_tell_is_delivered_with_its_id_and_acked():
    got = []
    net = Net([("hello", {}), ("tell", {"id": TID, "message": "Tell from sheaf"}), ("gone", {"doc": DOC})])
    r = relay(net, lambda message, id: got.append((message, id)))
    assert r.run() == rc.EXIT_FAILED
    assert got == [("Tell from sheaf", TID)]
    (url, headers, body), = net.posts
    assert url == "https://front.example/_/relay"
    assert body == {"doc": DOC, "id": TID, "outcome": "delivered"}
    assert headers["Authorization"] == f"Bearer {TOKEN}" and headers["Origin"] == "https://front.example"
    get_url, _ = net.gets[0]
    assert get_url == f"https://front.example/_/relay?doc={DOC}" and TOKEN not in get_url


def test_a_tell_the_session_did_not_take_is_acked_failed_with_why():
    def cleared(message, id):
        raise DeliveryError(rc.CLEARED.format(id=SID))
    net = Net([("tell", {"id": TID, "message": "m"}), ("gone", {})])
    relay(net, cleared).run()
    assert net.posts[0][2] == {"doc": DOC, "id": TID, "outcome": "failed",
                               "error": f"no open session {SID}: if it was cleared (/clear), fork again"}


def test_the_relay_reconnects_after_a_stream_ends_and_takes_the_tell_again():
    got = []
    net = Net([("tell", {"id": TID, "message": "m"})], [("tell", {"id": TID, "message": "m"}), ("gone", {})])
    relay(net, lambda m, i: got.append(i)).run()
    assert got == [TID, TID] and len(net.gets) == 2


def test_a_refused_token_ends_the_relay():
    assert relay(Net(refuse=401), lambda m, i: None).run() == rc.EXIT_FAILED


def test_a_tell_of_another_shape_is_skipped():
    got = []
    net = Net([("tell", {"id": "nope", "message": "m"}), ("tell", "x"), ("gone", {})])
    relay(net, lambda m, i: got.append(i)).run()
    assert got == [] and net.posts == []


def test_revoke_ends_the_tokens_of_a_sheaf(capsys):
    from sheafmd.hub.relay import Relays
    token, _ = Relays().issue("hans", DOC, SID)
    assert rc.cmd_relay(["revoke", DOC]) == 0
    assert capsys.readouterr().out == f"revoked 1 relay token of {DOC}\n"
    from sheafmd.hub.relay import digest
    assert Relays().find(digest(token)) is None


def test_the_sender_socket_is_the_users_own_and_goes_with_the_relay():
    s = rc.Sender()
    try:
        assert s.path.name == f"sheaf-relay-{os.getpid()}.sock"
        assert oct(os.stat(s.path).st_mode & 0o777) == oct(0o600)
        assert oct(os.stat(s.path.parent).st_mode & 0o777) == oct(0o700)
    finally:
        s.close()
    assert not s.path.exists()


def test_the_token_is_never_carried_onto_a_redirect():
    net = Net([("gone", {})])
    relay(net, lambda m, i: None).run()
    req = rc.Relay("https://front.example", DOC, SID, TOKEN, "/tmp/none")._request("https://front.example/_/relay")
    assert "Authorization" not in req.headers and req.unredirected_hdrs["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("hub", ["http://front.example", "https://front.example/path", "ftp://front.example",
                                 "https://front.example:x"])
def test_a_hub_that_is_not_https_or_this_machine_is_refused(tmp_path, hub, capsys):
    f = token_file(tmp_path)
    assert rc.cmd_relay(["--hub", hub, "--doc", DOC, "--session", SID, "--token-file", str(f)]) == 2
    assert "--hub must be an origin" in capsys.readouterr().err


def test_an_ack_the_hub_no_longer_waits_for_keeps_the_stream_and_says_so(capsys):
    got = []
    other = "22222222-3333-4444-8555-666666666666"
    net = Net([("tell", {"id": TID, "message": "m"}), ("tell", {"id": other, "message": "n"}), ("gone", {})], ack=404)
    relay(net, lambda m, i: got.append(i)).run()
    assert got == [TID, other] and len(net.gets) == 1
    err = capsys.readouterr().err
    assert f"Tell {TID} delivered; the hub was no longer waiting for it (it expired, or was acked)" in err
    assert "unreachable" not in err


def test_the_token_is_in_no_line_the_relay_prints(capsys):
    def cleared(message, id):
        raise DeliveryError("no")
    for net, deliver in ((Net([("tell", {"id": TID, "message": "m"}), ("gone", {})]), lambda m, i: None),
                         (Net([("tell", {"id": TID, "message": "m"}), ("gone", {})]), cleared),
                         (Net([("tell", {"id": TID, "message": "m"})], [("gone", {})]), lambda m, i: None),
                         (Net(refuse=401), lambda m, i: None)):
        relay(net, deliver).run()
    out = capsys.readouterr()
    assert out.err and TOKEN not in out.out + out.err


@pytest.mark.parametrize("failure", [403, 502, urllib.error.URLError("connection reset")])
def test_a_tell_whose_ack_failed_is_acked_again_and_never_delivered_twice(failure, capsys):
    """#134: the stream sends the Tell again after the reconnect; the relay only acks it again."""
    got = []
    first = failure if isinstance(failure, Exception) else \
        urllib.error.HTTPError("https://front.example/_/relay", failure, "no", {}, io.BytesIO(b"{}"))
    net = Net([("tell", {"id": TID, "message": "m"})], [("tell", {"id": TID, "message": "m"}), ("gone", {})],
              ack=[first, 200])
    relay(net, lambda m, i: got.append(i)).run()
    assert got == [TID] and len(net.gets) == 2
    assert [b for _, _, b in net.posts] == [{"doc": DOC, "id": TID, "outcome": "delivered"}] * 2


def test_a_failed_tell_whose_ack_failed_is_acked_failed_again_with_its_error():
    def cleared(message, id):
        raise DeliveryError("cleared")
    net = Net([("tell", {"id": TID, "message": "m"})], [("tell", {"id": TID, "message": "m"}), ("gone", {})],
              ack=[503, 200])
    calls = []
    relay(net, lambda m, i: (calls.append(i), cleared(m, i))).run()
    assert calls == [TID]
    assert [b for _, _, b in net.posts] == [{"doc": DOC, "id": TID, "outcome": "failed", "error": "cleared"}] * 2


@pytest.mark.parametrize("hub", ["https://Front.Example:443", "https://front.example:443", "HTTPS://FRONT.EXAMPLE"])
def test_the_hub_is_spelled_as_the_fronts_origin(hub):
    """#134: Origin is compared with the front's own; `:443` or capitals would make every ack a 403."""
    net = Net([("tell", {"id": TID, "message": "m"}), ("gone", {})])
    rc.Relay(hub, DOC, SID, TOKEN, "/tmp/none", opener=net, deliver=lambda m, i: None, sleep=lambda s: None).run()
    (url, headers, _), = net.posts
    assert url == "https://front.example/_/relay" and headers["Origin"] == "https://front.example"
