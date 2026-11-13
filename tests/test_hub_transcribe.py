"""The dictation relay (ticket 06, plan-06-micro.md): `POST /_/transcribe` and `GET /_/transcribe`.

The t-compute here is a fake HTTP server on 127.0.0.1 and the key a throwaway one in a temp file:
nothing leaves the machine and no real key is read. No audio is decoded; the bytes are a stand-in."""
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sheafmd import diagnostics
from sheafmd.hub import auth, transcribe

KEY = "fake-key-for-tests-0123"
AUDIO = b"RIFF-not-really-audio"


class FakeTCompute:
    """/api/v1/status, /audio/gpu-status and /audio/transcribe of t-compute, with what each answers."""

    def __init__(self):
        self.ready, self.gpu, self.reply = True, 200, (200, {"text": "hello there", "error": None})
        self.redirect = self.truncate = self.drip = False
        self.dropped = threading.Event()                  # the drip found the connection gone
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
                if outer.drip:                               # answers a byte at a time, each well inside any per-read limit
                    self.send_response(200)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    try:
                        for _ in range(100):
                            self.wfile.write(b"1\r\n{\r\n")
                            self.wfile.flush()
                            time.sleep(0.2)
                    except OSError:
                        outer.dropped.set()
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
                    status, obj = outer.reply
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


def dictate(browser, data=AUDIO, name="dictee.webm", ctype="audio/webm", cookie=True, key=False, origin=None):
    """What the page sends: the audio as it came. (`Browser.request` would make its Content-Type JSON.)"""
    host = f"127.0.0.1:{browser.hub.port}"
    h = {"Host": host, "Origin": origin or f"http://{host}", "Content-Type": ctype, "X-Filename": name,
         "Content-Length": str(len(data))}
    if cookie:
        h["Cookie"] = f"{browser.hub.auth.cookie_name}={browser.hub.auth.cookie_value()}"
    if key:
        h["X-Sheaf-Key"] = browser.hub.auth.key
    return browser.handler.handle("POST", "/_/transcribe", h, data)


# ── the [transcribe] table ───────────────────────────────────────────────────

def test_a_table_is_read_with_its_defaults(tcompute, key_file):
    cfg = transcribe.parse(table(tcompute, key_file), "the test")
    assert cfg.url == tcompute.url and cfg.key_file == key_file and cfg.key_name == "RAG_API_KEY"
    assert (cfg.per_minute, cfg.per_hour) == (12, 120)


@pytest.mark.parametrize("bad", [
    {"url": "ftp://h/api"}, {"url": "http:///api"}, {"url": "http://user:pw@h/api"}, {"url": 3},
    {"key_file": "relative.env"}, {"nope": 1}, {"key_name": ""},
    {"per_minute": 0}, {"per_hour": 0}, {"per_minute": "12"}, {"per_hour": True}])
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
    assert "x-api-key" not in {k.lower() for k in tcompute.calls("/status")[0][2]}          # the open route is asked without the key
    assert {k.lower(): v for k, v in tcompute.calls("/audio/gpu-status")[0][2].items()}["x-api-key"] == KEY


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


@pytest.mark.parametrize("failing", ["fstat", "read"])
def test_a_key_file_that_fails_after_it_is_open_is_not_used_said_once_and_closed(browser, tcompute, key_file, monkeypatch, failing):
    browser.hub.transcribe = transcribe.Relay(transcribe.parse(table(tcompute, key_file), "the test"), record=browser.hub.record)
    opened = []
    real_open, real_close = os.open, os.close
    monkeypatch.setattr(os, "open", lambda *a, **k: opened.append(real_open(*a, **k)) or opened[-1])
    closed = []
    monkeypatch.setattr(os, "close", lambda fd: closed.append(fd) or real_close(fd))
    if failing == "fstat":
        real_fstat = os.fstat

        def fstat(fd):
            if fd in opened and fd not in closed:            # only the key file's open descriptor; teardown fstats others
                raise OSError(5, "Input/output error")
            return real_fstat(fd)
        monkeypatch.setattr(os, "fstat", fstat)
    else:
        real_fdopen = os.fdopen

        class Unreadable:
            def __init__(self, fd, *a, **k):
                self.f = real_fdopen(fd, *a, **k)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.f.close()

            def read(self):
                raise OSError(5, "Input/output error")

        def fdopen(fd, *a, **k):
            return Unreadable(fd, *a, **k)
        monkeypatch.setattr(os, "fdopen", fdopen)
    assert available(browser) is False and tcompute.seen == []
    assert len([r for r in diagnostics.read() if r["kind"] == "transcribe-key-file"]) == 1
    if failing == "fstat":
        assert closed == opened
    else:
        with pytest.raises(OSError):
            os.fstat(opened[0])                              # the one descriptor was closed, once


def test_a_redirect_is_not_followed_and_the_key_goes_nowhere_else(browser, relay, tcompute):
    tcompute.redirect = True
    assert available(browser) is False
    assert {s[1] for s in tcompute.seen} == {"/api/v1/status"}


def test_the_limit_is_on_the_whole_call_not_on_each_read(tcompute, monkeypatch):
    tcompute.drip = True
    began = time.monotonic()
    assert transcribe._call("POST", f"{tcompute.url}/audio/transcribe", {}, b"x", timeout=1) == (0, b"")
    assert time.monotonic() - began < 2.5
    assert tcompute.dropped.wait(2)                          # the connection was shut, not left to a thread


@pytest.fixture
def full_backlog():
    """A listening socket that never accepts and whose queue is full: a connect to it waits for its timeout.
    Linux drops the SYN of a full queue; another kernel may refuse instead, and the test then proves nothing."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(0)
    port, fill = listener.getsockname()[1], []
    for _ in range(4):
        c = socket.socket()
        c.setblocking(False)
        try:
            c.connect(("127.0.0.1", port))
        except BlockingIOError:
            pass
        fill.append(c)
    yield port
    for c in fill + [listener]:
        c.close()


def test_the_limit_covers_every_address_tried_for_the_connection(full_backlog, monkeypatch):
    one = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", full_backlog))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [one, one, one])
    began = time.monotonic()
    assert transcribe._call("POST", f"http://tc.invalid:{full_backlog}/x", {}, b"x", timeout=1) == (0, b"")
    assert time.monotonic() - began < 2.5                    # three addresses at 1 s each would take 3 s


def test_the_limit_covers_the_resolution_of_the_name(monkeypatch):
    release = threading.Event()

    def stuck(*a, **k):
        release.wait(5)
        return []
    monkeypatch.setattr(socket, "getaddrinfo", stuck)
    began = time.monotonic()
    try:
        assert transcribe._call("POST", "http://tc.invalid:9/x", {}, b"x", timeout=1) == (0, b"")
        assert time.monotonic() - began < 2.5
    finally:
        release.set()


def test_call_returns_only_after_the_timer_has_finished_cutting(tcompute, monkeypatch):
    tcompute.drip = True
    timers = []

    class SlowCut(threading.Timer):
        def __init__(self, interval, fn):
            def slow():
                fn()
                time.sleep(0.5)                              # the cut is still going on when the call has its answer
            super().__init__(interval, slow)
            timers.append(self)
    monkeypatch.setattr(transcribe.threading, "Timer", SlowCut)
    assert transcribe._call("POST", f"{tcompute.url}/audio/transcribe", {}, b"x", timeout=0.3) == (0, b"")
    assert not timers[0].is_alive()


def test_an_answer_cut_short_is_no_answer(browser, relay, tcompute):
    tcompute.truncate = True
    assert available(browser) is False


def test_the_answer_is_kept_for_30_seconds(browser, relay, tcompute, clock):
    assert available(browser) and available(browser)
    assert len(tcompute.calls("/status")) == 1
    clock.advance(31)
    tcompute.ready = False
    assert available(browser) is False and len(tcompute.calls("/status")) == 2


# ── the relay (POST) ─────────────────────────────────────────────────────────

def test_the_audio_goes_to_t_compute_and_the_text_comes_back(browser, relay, tcompute):
    r = dictate(browser)
    assert r.status == 200 and r.json() == {"ok": True, "text": "hello there"}
    method, path, h, body = tcompute.calls("/audio/transcribe")[0]
    assert (method, path) == ("POST", "/api/v1/audio/transcribe")
    h = {k.lower(): v for k, v in h.items()}
    assert h["x-api-key"] == KEY and h["x-priority"] == "high"
    assert h["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="dictee.webm"' in body and AUDIO in body


def test_each_extension_is_sent_under_its_fixed_name(browser, relay, tcompute):
    assert dictate(browser, name="dictee.mp4", ctype="audio/mp4").status == 200
    assert b'filename="dictee.mp4"' in tcompute.calls("/audio/transcribe")[0][3]


@pytest.mark.parametrize("name", ["dictee.wav", "x.webm", "dictee.webm\r\nX: y", "../dictee.webm", "", "dictee.webm.exe"])
def test_only_the_fixed_file_names_are_taken(browser, relay, tcompute, name):
    assert dictate(browser, name=name).status == 415 and tcompute.calls("/audio/transcribe") == []


def test_only_audio_is_taken(browser, relay, tcompute):
    assert dictate(browser, ctype="text/html").status == 415 and tcompute.calls("/audio/transcribe") == []


def test_an_empty_recording_is_refused(browser, relay):
    assert dictate(browser, data=b"").status == 400


def test_more_than_two_mebibytes_is_refused_before_t_compute_hears_of_it(browser, relay, tcompute):
    assert dictate(browser, data=b"x" * (2 * 1024 * 1024 + 1)).status == 413
    assert dictate(browser, data=b"x" * (2 * 1024 * 1024)).status == 200
    assert len(tcompute.calls("/audio/transcribe")) == 1


def test_a_recording_over_two_mebibytes_is_refused_by_its_header_before_a_byte_is_read(browser, relay, tcompute):
    def never():
        raise AssertionError("the body was read")
    host = f"127.0.0.1:{browser.hub.port}"
    h = {"Host": host, "Origin": f"http://{host}", "Content-Type": "audio/webm", "X-Filename": "dictee.webm",
         "Content-Length": str(3 * 1024 * 1024), "Cookie": f"{browser.hub.auth.cookie_name}={browser.hub.auth.cookie_value()}"}
    assert browser.handler.handle("POST", "/_/transcribe", h, never).status == 413


def test_an_accepted_content_type_never_reaches_the_multipart(browser, relay, tcompute):
    assert dictate(browser, ctype="audio/webm\r\nX-Evil: yes").status == 200
    sent = tcompute.calls("/audio/transcribe")[0][3]
    assert b"X-Evil" not in sent and b"Content-Type: audio/webm\r\n\r\n" in sent


def test_a_browser_that_is_not_signed_in_or_not_from_the_page_is_refused(browser, relay, tcompute):
    assert dictate(browser, cookie=False).status == 401
    assert dictate(browser, origin="http://evil.example").status == 403
    assert dictate(browser, key=True, cookie=False).status == 403          # the hub key is not a browser
    assert tcompute.calls("/audio/transcribe") == []


def test_no_relay_while_dictation_is_off(browser, relay, tcompute):
    tcompute.ready = False
    assert dictate(browser).status == 503 and tcompute.calls("/audio/transcribe") == []


def test_no_relay_without_the_table(browser):
    assert dictate(browser).status == 503


LEAK = "Traceback /srv/t-compute/secret/path.py"


@pytest.mark.parametrize("reply, status", [((200, {"text": "", "error": LEAK}), 502),
                                           ((200, {"text": "  ", "error": None}), 502),
                                           ((503, {"detail": LEAK}), 503),
                                           ((422, {"detail": LEAK}), 502),
                                           ((200, {"nope": 1}), 502)])
def test_a_failed_transcription_is_a_short_safe_answer(browser, relay, tcompute, reply, status):
    tcompute.reply = reply
    r = dictate(browser)
    assert r.status == status and "/srv" not in r.text and LEAK not in r.text and KEY not in r.text


def test_a_service_that_drops_out_takes_the_button_away_for_30_seconds(browser, relay, tcompute, clock):
    assert available(browser)
    tcompute.reply = (503, {})
    assert dictate(browser).status == 503
    tcompute.reply = (200, {"text": "back", "error": None})
    assert available(browser) is False
    clock.advance(31)
    assert available(browser) is True


def test_a_t_compute_that_hangs_up_takes_the_button_away_too(browser, relay, tcompute):
    assert available(browser)
    tcompute.truncate = True
    assert dictate(browser).status == 503
    tcompute.truncate = False
    assert available(browser) is False


def test_one_relay_at_a_time(browser, relay, tcompute):
    assert available(browser)
    with relay._busy:
        r = dictate(browser)
    assert r.status == 429 and tcompute.calls("/audio/transcribe") == []


def test_the_budget_per_minute_and_per_hour(browser, tcompute, key_file, clock):
    browser.hub.transcribe = transcribe.Relay(
        transcribe.parse(table(tcompute, key_file, per_minute=2, per_hour=3), "the test"), clock=clock)
    assert [dictate(browser).status for _ in range(3)] == [200, 200, 429]
    clock.advance(61)
    assert dictate(browser).status == 200
    clock.advance(61)
    assert dictate(browser).status == 429                                 # the hour's third came before this one
    clock.advance(3600)
    assert dictate(browser).status == 200


def test_the_default_budget_is_twelve_a_minute(browser, relay):
    assert [dictate(browser).status for _ in range(13)] == [200] * 12 + [429]


def test_a_relay_is_written_down_without_the_key_the_text_or_the_sound(browser, relay, tcompute):
    dictate(browser)
    row = [r for r in diagnostics.read() if r["kind"] == "transcribe"][0]
    assert row["bytes"] == len(AUDIO) and row["result"] == "ok"
    assert KEY not in json.dumps(diagnostics.read()) and "hello there" not in json.dumps(diagnostics.read())


# ── not on the proxy socket, and the page's policy ───────────────────────────

def test_the_proxy_socket_has_no_such_route(front, tcompute, key_file):
    front.hub.transcribe = transcribe.Relay(transcribe.parse(table(tcompute, key_file), "the test"))
    assert front.get("/_/transcribe").status == 404
    r = front.request("POST", "/_/transcribe", raw=AUDIO, headers={"Content-Type": "audio/webm", "X-Filename": "dictee.webm"})
    assert r.status == 404 and tcompute.seen == []


def test_a_page_allows_the_microphone_to_itself_and_its_csp_is_unchanged(browser, plan):
    r = browser.get("/work/plan.md")
    assert r.headers["Permissions-Policy"] == "microphone=(self), camera=(), geolocation=()"
    nonce = r.headers["Content-Security-Policy"].split("script-src 'nonce-")[1].split("'")[0]
    assert r.headers["Content-Security-Policy"] == (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; img-src data:; "
        "font-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    assert auth.csp(nonce) == r.headers["Content-Security-Policy"]
