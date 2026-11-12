"""The dictation relay (ticket 06, plan-06-micro.md): `POST /_/transcribe` and `GET /_/transcribe`.

The t-compute here is a fake HTTP server on 127.0.0.1 and the key a throwaway one in a temp file:
nothing leaves the machine and no real key is read. No audio is decoded; the bytes are a stand-in."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sheafmd import diagnostics
from sheafmd.hub import auth, transcribe

KEY = "fake-key-for-tests-0123"


class FakeTCompute:
    """/api/v1/status and /audio/gpu-status of t-compute, with what each answers."""

    def __init__(self):
        self.ready, self.gpu = True, 200
        self.redirect = self.truncate = False
        self.seen = []                                    # (method, path, headers, body)
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                outer.seen.append((self.command, self.path, dict(self.headers), body))
                if outer.truncate:                           # promises more than it sends, then hangs up
                    self.send_response(200)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.wfile.write(b'1f4\r\n{"whisper"')              # a chunk of 500 bytes, 10 sent
                    self.close_connection = True
                    return
                if outer.redirect:
                    self.send_response(302)
                    self.send_header("Location", "/elsewhere")
                    self.end_headers()
                    return
                if self.path.endswith("/status"):
                    status, obj = 200, {"whisper": {"ready": outer.ready}}
                elif self.path.endswith("/audio/gpu-status"):
                    keyed = self.headers.get("X-API-Key") == KEY
                    status, obj = (outer.gpu if keyed else 401), {"gpu": "idle"}
                else:
                    status, obj = 404, {}
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def calls(self, suffix):
        return [s for s in self.seen if s[1].endswith(suffix)]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def tcompute():
    t = FakeTCompute()
    yield t
    t.close()


@pytest.fixture
def clock():
    now = [1000.0]
    return type("Clock", (), {"__call__": lambda self: now[0], "advance": lambda self, s: now.__setitem__(0, now[0] + s)})()


@pytest.fixture
def key_file(tmp_path):
    f = tmp_path / "t-compute.env"
    f.write_text(f"OTHER=1\nRAG_API_KEY={KEY}\n")
    f.chmod(0o600)
    return f


def table(tcompute, key_file, **extra):
    return {"url": tcompute.url, "key_file": str(key_file), "key_name": "RAG_API_KEY", **extra}


@pytest.fixture
def relay(browser, tcompute, key_file, clock):
    browser.hub.transcribe = transcribe.Relay(transcribe.parse(table(tcompute, key_file), "the test"), clock=clock)
    return browser.hub.transcribe


# ── the [transcribe] table ───────────────────────────────────────────────────

def test_a_table_is_read_with_its_defaults(tcompute, key_file):
    cfg = transcribe.parse(table(tcompute, key_file), "the test")
    assert cfg.url == tcompute.url and cfg.key_file == key_file and cfg.key_name == "RAG_API_KEY"


@pytest.mark.parametrize("bad", [
    {"url": "ftp://h/api"}, {"url": "http:///api"}, {"url": "http://user:pw@h/api"}, {"url": 3},
    {"key_file": "relative.env"}, {"nope": 1}, {"key_name": ""}])
def test_a_table_that_cannot_be_used_stops_the_start(tcompute, key_file, bad):
    with pytest.raises(transcribe.TranscribeError, match="the test"):
        transcribe.parse({**table(tcompute, key_file), **bad}, "the test")


# ── is dictation available (GET) ─────────────────────────────────────────────

def available(browser):
    r = browser.get("/_/transcribe")
    assert r.status == 200
    return r.json()["available"]


def test_dictation_is_available_when_t_compute_is_ready_and_takes_the_key(browser, relay, tcompute):
    assert available(browser) is True
    assert "X-Api-Key" not in tcompute.calls("/status")[0][2]          # the open route is asked without the key
    assert tcompute.calls("/audio/gpu-status")[0][2]["X-Api-Key"] == KEY


def test_only_a_signed_in_browser_is_told(browser, relay, tcompute):
    assert browser.get("/_/transcribe", cookie=False).status == 401
    assert browser.get("/_/transcribe", cookie=False, key=True).status == 403
    assert tcompute.seen == []


def test_dictation_is_off_without_the_table(browser):
    assert browser.hub.transcribe is None and available(browser) is False


def test_dictation_is_off_when_the_model_is_not_ready(browser, relay, tcompute):
    tcompute.ready = False
    assert available(browser) is False


def test_dictation_is_off_when_the_key_is_refused(browser, relay, tcompute):
    tcompute.gpu = 401
    assert available(browser) is False


def test_dictation_is_off_when_t_compute_is_down(browser, tcompute, key_file):
    t = table(tcompute, key_file)
    tcompute.close()
    browser.hub.transcribe = transcribe.Relay(transcribe.parse(t, "the test"))
    assert available(browser) is False


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604])
def test_a_key_file_others_can_read_is_not_used(browser, relay, tcompute, key_file, mode):
    key_file.chmod(mode)
    assert available(browser) is False and tcompute.seen == []


@pytest.mark.parametrize("kind", ["directory", "fifo", "symlink"])
def test_a_key_file_that_is_not_a_plain_file_is_not_used_and_said_once(browser, tcompute, tmp_path, kind):
    real = tmp_path / "real.env"
    real.write_text(f"RAG_API_KEY={KEY}\n")
    real.chmod(0o600)
    bad = tmp_path / "bad.env"
    {"directory": bad.mkdir, "fifo": lambda: os.mkfifo(bad), "symlink": lambda: bad.symlink_to(real)}[kind]()
    browser.hub.transcribe = transcribe.Relay(transcribe.parse(table(tcompute, bad), "the test"), record=browser.hub.record)
    assert available(browser) is False and tcompute.seen == []
    assert len([r for r in diagnostics.read() if r["kind"] == "transcribe-key-file"]) == 1


def test_a_redirect_is_not_followed_and_the_key_goes_nowhere_else(browser, relay, tcompute):
    tcompute.redirect = True
    assert available(browser) is False
    assert {s[1] for s in tcompute.seen} == {"/api/v1/status"}


def test_an_answer_cut_short_is_no_answer(browser, relay, tcompute):
    tcompute.truncate = True
    assert available(browser) is False


def test_the_answer_is_kept_for_30_seconds(browser, relay, tcompute, clock):
    assert available(browser) and available(browser)
    assert len(tcompute.calls("/status")) == 1
    clock.advance(31)
    tcompute.ready = False
    assert available(browser) is False and len(tcompute.calls("/status")) == 2


# ── not on the proxy socket, and the page's policy ───────────────────────────

def test_the_proxy_socket_has_no_such_route(front, tcompute, key_file):
    front.hub.transcribe = transcribe.Relay(transcribe.parse(table(tcompute, key_file), "the test"))
    assert front.get("/_/transcribe").status == 404
    assert tcompute.seen == []


def test_a_page_allows_the_microphone_to_itself_and_its_csp_is_unchanged(browser, plan):
    r = browser.get("/work/plan.md")
    assert r.headers["Permissions-Policy"] == "microphone=(self), camera=(), geolocation=()"
    nonce = r.headers["Content-Security-Policy"].split("script-src 'nonce-")[1].split("'")[0]
    assert r.headers["Content-Security-Policy"] == (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; img-src data:; "
        "font-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    assert auth.csp(nonce) == r.headers["Content-Security-Policy"]
