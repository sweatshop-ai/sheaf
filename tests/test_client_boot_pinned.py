"""A command acts on the hub it proved, not on one that took its place (SPEC 9.4).

A command learns the hub's boot id, pid and version from `challenge()` and then sends its request on
a connection of its own, which proves the hub again. A hub restarted in between must not be sent the
request: `call` carries the boot id the command expects and stops, before sending anything, when
the proof on the request's own connection shows another."""
import http.client

import pytest
from sheafmd import paths
from sheafmd.hub import client, server
from sheafmd.hub.core import Hub


@pytest.fixture
def live(work):
    """A running hub and a client for it: (client, the hub's challenge answer)."""
    sock = server.bind(0)
    port = sock.getsockname()[1]
    key = paths.ensure_key()
    srv = server.HubServer(Hub(port=port, key=key, started_by="test"), sock)
    srv.start()
    c = client.HubClient(key, port)
    yield c, c.challenge()
    srv.close()


@pytest.fixture
def sent(monkeypatch):
    """The paths this process asks of any hub, in order."""
    paths_asked = []
    request = http.client.HTTPConnection.request

    def record(self, method, url, *a, **kw):
        paths_asked.append(url.split("?")[0])
        return request(self, method, url, *a, **kw)
    monkeypatch.setattr(http.client.HTTPConnection, "request", record)
    return paths_asked


def test_a_request_for_the_hub_that_was_proved_goes_through(live, sent):
    c, got = live
    status, res = c.call("GET", "/_/jobs", boot=got["boot"])
    assert status == 200 and "telling" in res
    assert sent == ["/_/health", "/_/jobs"]


def test_a_request_for_another_boot_is_not_sent_and_says_run_it_again(live, sent):
    c, got = live
    with pytest.raises(client.HubChanged) as e:
        c.call("POST", "/_/stop", {"reason": "stop"}, boot="the-boot-of-the-hub-before")
    assert isinstance(e.value, client.Impostor)               # what every command already stops at
    assert "changed" in str(e.value) and "run the command again" in str(e.value)
    assert sent == ["/_/health"]                              # the proof only: the stop never went out


def test_a_stop_asked_of_a_replaced_hub_sends_no_stop(live, sent):
    c, got = live
    with pytest.raises(client.HubChanged):
        client.stop_and_explain(c, {**got, "boot": "the-boot-of-the-hub-before"}, "upgrade")
    assert "/_/stop" not in sent


def test_the_version_check_of_a_replaced_hub_asks_nothing_of_the_new_one(live, sent, monkeypatch):
    c, got = live
    monkeypatch.setattr(client, "__version__", "9.9.9")       # newer than the hub: it would ask GET /_/jobs
    with pytest.raises(client.HubChanged):
        client._meet_version(c, {**got, "boot": "the-boot-of-the-hub-before", "version": "0.0.1"},
                             warn=lambda *a: None)
    assert "/_/jobs" not in sent and "/_/stop" not in sent
