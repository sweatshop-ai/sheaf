"""What a client does with the 503 of a hub that is stopping (SPEC 8.4, 9.4).

A hub whose stop has begun refuses the second request of a kept connection with `503`, `Connection:
close` and `{"error": "the hub is stopping"}`, and applies nothing. The client proves the hub on
a connection and sends on that same connection, so it meets exactly that answer. It must say
that nothing was sent and must not send again; it must not hand the 503 back as the hub's answer."""
import json
import threading

import pytest
from helpers import BEA, UnixHTTP
from sheafmd import paths
from sheafmd.hub import client, server
from sheafmd.hub.core import Hub

PING = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()


@pytest.fixture
def stopping(work):
    """A hub whose stop has begun and is held there: (port, key)."""
    sock = server.bind(0)
    port = sock.getsockname()[1]
    key = paths.ensure_key()
    hub = Hub(port=port, key=key, started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    release = threading.Event()
    hub.announce_stop = lambda reason: release.wait(5)
    hub.on_stop("stop")
    assert srv.closing.is_set()
    yield port, key
    release.set()
    srv.close()


def test_the_door_says_the_hub_is_stopping_and_sends_nothing_again(stopping, monkeypatch):
    port, key = stopping
    link = client.DoorLink("Codex", say=lambda *a: None)
    link._client = client.HubClient(key, port)
    sent = []
    door = link._client.door
    monkeypatch.setattr(link._client, "door", lambda *a: sent.append(1) or door(*a))
    with pytest.raises(client.HubUnavailable) as e:
        link.post(PING)
    assert "the hub is stopping" in str(e.value) and "nothing of yours was sent" in str(e.value)
    assert sent == [1]                                    # one try: no second connection, no resend


def test_a_command_is_told_the_hub_stopped_before_its_request_and_does_not_resend(stopping, monkeypatch):
    port, key = stopping
    c = client.HubClient(key, port)
    sent = []
    send = c._send_proved
    monkeypatch.setattr(c, "_send_proved", lambda *a: sent.append(1) or send(*a))
    with pytest.raises(client.HubLost) as e:
        c.call("POST", "/_/comment", {"doc": "work/plan.md"})
    assert "nothing was sent" in str(e.value) and isinstance(e.value, client.Impostor)
    assert sent == [1]


def test_the_version_check_of_a_command_meets_the_stopping_hub_as_a_lost_request(stopping, monkeypatch):
    port, key = stopping
    c = client.HubClient(key, port)
    monkeypatch.setattr(client, "__version__", "9.9.9")        # newer than the hub: it asks GET /_/jobs
    with pytest.raises(client.HubLost) as e:
        client._meet_version(c, {"version": "0.0.1"}, warn=lambda *a: None)
    assert "nothing was sent" in str(e.value)


def test_a_503_that_is_not_the_stopping_hub_is_still_the_hubs_answer():
    assert client.hub_is_stopping(503, json.dumps({"ok": False, "error": "no browser"}).encode()) is False
    assert client.hub_is_stopping(200, json.dumps({"error": client.STOPPING}).encode()) is False
    assert client.hub_is_stopping(503, b"not json") is False
    assert client.hub_is_stopping(503, json.dumps({"error": client.STOPPING}).encode()) is True


# ── the same refusal through the proxy socket (it shares `_serve` with the port) ──────────────

def test_a_kept_connection_of_the_proxy_socket_is_not_served_once_the_hub_is_stopping(proxy_served):
    hub = proxy_served
    headers = {"Host": hub.proxy.host, "Origin": hub.proxy.origin, "X-Sheaf-Member": BEA}
    kept = UnixHTTP(hub.proxy.socket)
    kept.request("GET", "/work/", headers=headers)
    first = kept.getresponse()
    first.read()
    assert first.status == 200
    release = threading.Event()
    hub.announce_stop = lambda reason: release.wait(5)
    try:
        hub.on_stop("stop")
        body = json.dumps({"doc": "work/plan.md"}).encode()
        kept.request("POST", "/_/seen", body, {**headers, "Content-Type": "application/json"})
        r = kept.getresponse()
        assert r.status == 503 and r.getheader("Connection") == "close"
        assert json.loads(r.read())["error"] == client.STOPPING
    finally:
        release.set()
        kept.close()
