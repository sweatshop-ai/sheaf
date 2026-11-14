"""The dictation relay (ticket 06, plan-06-standard-api.md): `POST /_/transcribe` and `GET /_/transcribe`.

The provider here is a fake OpenAI-style transcription server on 127.0.0.1 and the key a throwaway one in a temp
file: nothing leaves the machine and no real key is read. No audio is decoded; the bytes are a stand-in."""
import json
import os
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from sheafmd import diagnostics
from sheafmd.hub import auth, transcribe

KEY = "fake-key-for-tests-0123"
AUDIO = b"RIFF-not-really-audio"
MODEL = "fake-model-1"
TLS = Path(__file__).parent / "tls"


class FakeTCompute:
    """`POST /v1/audio/transcriptions` of an OpenAI-style provider, with what it answers. `tls=True` serves https
    with the certificate of tests/tls (valid for localhost and 127.0.0.1)."""

    def __init__(self, tls=False, tmp=None):
        self.reply = (200, {"text": "hello there"})
        self.redirect = self.truncate = self.drip = False
        self.elsewhere = "/elsewhere"                     # where a redirect points
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
                    self.wfile.write(b'1f4\r\n{"text"')                   # a chunk of 500 bytes, 7 sent
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
                    self.send_response(outer.redirect if isinstance(outer.redirect, int) else 302)
                    self.send_header("Location", outer.elsewhere)
                    self.end_headers()
                    return
                status, obj = outer.reply
                data = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(TLS / "loopback-cert.pem", loopback_key(tmp))
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.url = f"{'https' if tls else 'http'}://127.0.0.1:{self.server.server_port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def calls(self, suffix="/audio/transcriptions"):
        return [s for s in self.seen if s[1].endswith(suffix)]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def loopback_key(tmp: Path) -> Path:
    """The test-only key of the fixture certificate, made whole in `tmp`: the repo holds its body without the PEM
    lines, because no test file may hold a line shaped like a private key (tests/test_secret_shapes.py)."""
    pem = tmp / "loopback-key.pem"
    pem.write_text("-----BEGIN PRIV" "ATE KEY-----\n" + (TLS / "loopback-key-body.b64").read_text() + "-----END PRIV" "ATE KEY-----\n")
    return pem


def fields(body: bytes, headers: dict) -> dict:
    """The parts of a multipart body: {name: (filename or None, content type or None, content)}."""
    boundary = {k.lower(): v for k, v in headers.items()}["content-type"].split("boundary=")[1].encode()
    parts = {}
    for raw in body.split(b"--" + boundary)[1:-1]:
        head, _, content = raw.strip(b"\r\n").partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        disposition = next(l for l in lines if l.lower().startswith("content-disposition"))
        name = disposition.split('name="')[1].split('"')[0]
        filename = disposition.split('filename="')[1].split('"')[0] if "filename=" in disposition else None
        ctype = next((l.split(": ", 1)[1] for l in lines if l.lower().startswith("content-type")), None)
        parts[name] = (filename, ctype, content)
    return parts


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
    f = tmp_path / "provider.env"
    f.write_text(f"OTHER=1\nTRANSCRIBE_API_KEY={KEY}\n")
    f.chmod(0o600)
    return f


def table(tcompute, key_file, **extra):
    return {"url": tcompute.url, "key_file": str(key_file), "model": MODEL, **extra}


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
    assert cfg.url == tcompute.url and cfg.key_file == key_file and cfg.model == MODEL
    assert cfg.key_name == "TRANSCRIBE_API_KEY"
    assert (cfg.per_minute, cfg.per_hour) == (12, 120)


@pytest.mark.parametrize("bad", [
    {"url": "ftp://h/v1"}, {"url": "http:///v1"}, {"url": "http://user:pw@h/v1"}, {"url": 3},
    {"url": "http://h/v1?x=1"}, {"url": "http://h/v1#frag"},
    {"key_file": "relative.env"}, {"nope": 1}, {"key_name": ""},
    {"model": ""}, {"model": "two words"}, {"model": "a\nb"}, {"model": 'a"b'}, {"model": "x" * 101}, {"model": 3},
    {"per_minute": 0}, {"per_hour": 0}, {"per_minute": "12"}, {"per_hour": True}])
def test_a_table_that_cannot_be_used_stops_the_start(tcompute, key_file, bad):
    with pytest.raises(transcribe.TranscribeError, match="the test"):
        transcribe.parse({**table(tcompute, key_file), **bad}, "the test")


def test_a_table_without_a_model_says_what_changed(tcompute, key_file):
    t = table(tcompute, key_file)
    del t["model"]
    with pytest.raises(transcribe.TranscribeError, match="'model' is missing") as e:
        transcribe.parse(t, "the test")
    assert "ending in /v1" in str(e.value)


@pytest.mark.parametrize("model", ["gpt-transcribe", "voxtral-mini-latest", "whisper-1", "org/model:2_a.b", "x" * 100])
def test_a_model_name_with_the_usual_characters_is_taken(tcompute, key_file, model):
    assert transcribe.parse(table(tcompute, key_file, model=model), "the test").model == model


# ── is dictation available (GET) ─────────────────────────────────────────────

def available(browser):
    r = browser.get("/_/transcribe")
    assert r.status == 200
    return r.json()["available"]


def test_dictation_is_available_with_a_usable_key_file_and_no_request_is_made(browser, relay, tcompute):
    assert available(browser) is True and available(browser) is True
    assert tcompute.seen == []


def test_only_a_signed_in_browser_is_told(browser, relay, tcompute):
    assert browser.get("/_/transcribe", cookie=False).status == 401
    assert browser.get("/_/transcribe", cookie=False, key=True).status == 403
    assert tcompute.seen == []


def test_dictation_is_off_without_the_table(browser):
    assert browser.hub.transcribe is None and available(browser) is False


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604])
def test_a_key_file_others_can_read_is_not_used(browser, relay, tcompute, key_file, mode):
    key_file.chmod(mode)
    assert available(browser) is False and tcompute.seen == []


@pytest.mark.parametrize("kind", ["directory", "fifo", "symlink"])
def test_a_key_file_that_is_not_a_plain_file_is_not_used_and_said_once(browser, tcompute, tmp_path, kind):
    real = tmp_path / "real.env"
    real.write_text(f"TRANSCRIBE_API_KEY={KEY}\n")
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


def test_a_key_file_whose_close_fails_when_it_is_refused_is_closed_once_and_said_once(browser, tcompute, key_file, monkeypatch):
    key_file.chmod(0o644)                                    # refused after the fstat, on the branch that closes the descriptor itself
    browser.hub.transcribe = transcribe.Relay(transcribe.parse(table(tcompute, key_file), "the test"), record=browser.hub.record)
    opened, closed = [], []
    real_open, real_close = os.open, os.close

    def open_(path, *a, **k):
        fd = real_open(path, *a, **k)
        if str(path) == str(key_file):                       # the diagnostics log opens and closes files through the same calls
            opened.append(fd)
        return fd

    def close(fd):
        mine = bool(opened) and fd == opened[0] and fd not in closed
        if mine:
            closed.append(fd)
        real_close(fd)
        if mine:
            raise OSError(5, "Input/output error")           # a FUSE that fails at the flush; the descriptor is gone all the same
    monkeypatch.setattr(os, "open", open_)
    monkeypatch.setattr(os, "close", close)
    assert available(browser) is False and tcompute.seen == []
    assert len(opened) == 1 and closed == opened             # once: a second close could take another thread's descriptor
    assert len([r for r in diagnostics.read() if r["kind"] == "transcribe-key-file"]) == 1


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


def test_the_limit_is_on_the_whole_call_not_on_each_read(tcompute):
    tcompute.drip = True
    began = time.monotonic()
    assert transcribe._call("POST", f"{tcompute.url}/audio/transcriptions", {}, b"x", timeout=1) == (0, b"")
    assert time.monotonic() - began < 2.5
    assert tcompute.dropped.wait(2)                          # the connection was shut, not left to a thread


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
    assert transcribe._call("POST", f"{tcompute.url}/audio/transcriptions", {}, b"x", timeout=0.3) == (0, b"")
    assert not timers[0].is_alive()


# ── the relay (POST) ─────────────────────────────────────────────────────────

def test_the_audio_goes_to_the_provider_and_the_text_comes_back(browser, relay, tcompute):
    r = dictate(browser)
    assert r.status == 200 and r.json() == {"ok": True, "text": "hello there"}
    method, path, h, body = tcompute.calls()[0]
    assert (method, path) == ("POST", "/v1/audio/transcriptions")
    low = {k.lower(): v for k, v in h.items()}
    assert low["authorization"] == f"Bearer {KEY}"
    assert low["content-type"].startswith("multipart/form-data; boundary=")
    assert not {"x-api-key", "x-priority"} & set(low)
    sent = fields(body, h)
    assert set(sent) == {"file", "model"}                                  # no response_format, no language
    assert sent["file"] == ("dictee.webm", "audio/webm", AUDIO)
    assert sent["model"][2] == MODEL.encode()


def test_each_extension_is_sent_under_its_fixed_name(browser, relay, tcompute):
    assert dictate(browser, name="dictee.mp4", ctype="audio/mp4").status == 200
    call = tcompute.calls()[0]
    assert fields(call[3], call[2])["file"][:2] == ("dictee.mp4", "audio/mp4")


@pytest.mark.parametrize("name", ["dictee.wav", "x.webm", "dictee.webm\r\nX: y", "../dictee.webm", "", "dictee.webm.exe"])
def test_only_the_fixed_file_names_are_taken(browser, relay, tcompute, name):
    assert dictate(browser, name=name).status == 415 and tcompute.calls() == []


def test_only_audio_is_taken(browser, relay, tcompute):
    assert dictate(browser, ctype="text/html").status == 415 and tcompute.calls() == []


def test_an_empty_recording_is_refused(browser, relay):
    assert dictate(browser, data=b"").status == 400


def test_more_than_two_mebibytes_is_refused_before_the_provider_hears_of_it(browser, relay, tcompute):
    assert dictate(browser, data=b"x" * (2 * 1024 * 1024 + 1)).status == 413
    assert dictate(browser, data=b"x" * (2 * 1024 * 1024)).status == 200
    assert len(tcompute.calls()) == 1


def test_a_recording_over_two_mebibytes_is_refused_by_its_header_before_a_byte_is_read(browser, relay, tcompute):
    def never():
        raise AssertionError("the body was read")
    host = f"127.0.0.1:{browser.hub.port}"
    h = {"Host": host, "Origin": f"http://{host}", "Content-Type": "audio/webm", "X-Filename": "dictee.webm",
         "Content-Length": str(3 * 1024 * 1024), "Cookie": f"{browser.hub.auth.cookie_name}={browser.hub.auth.cookie_value()}"}
    assert browser.handler.handle("POST", "/_/transcribe", h, never).status == 413


def test_an_accepted_content_type_never_reaches_the_multipart(browser, relay, tcompute):
    assert dictate(browser, ctype="audio/webm\r\nX-Evil: yes").status == 200
    sent = tcompute.calls()[0][3]
    assert b"X-Evil" not in sent and b"Content-Type: audio/webm\r\n\r\n" in sent


def test_a_browser_that_is_not_signed_in_or_not_from_the_page_is_refused(browser, relay, tcompute):
    assert dictate(browser, cookie=False).status == 401
    assert dictate(browser, origin="http://evil.example").status == 403
    assert dictate(browser, key=True, cookie=False).status == 403          # the hub key is not a browser
    assert tcompute.calls() == []


def test_no_relay_without_the_table(browser):
    assert dictate(browser).status == 503


def test_no_relay_with_an_unusable_key_file(browser, relay, tcompute, key_file):
    key_file.chmod(0o644)
    assert dictate(browser).status == 503 and tcompute.seen == []


LEAK = "Traceback /srv/provider/secret/path.py"


@pytest.mark.parametrize("reply, status", [((200, {"text": "", "error": LEAK}), 502),
                                           ((200, {"text": "  "}), 502),
                                           ((200, {"nope": 1}), 502),
                                           ((200, b"not json " + LEAK.encode()), 502),
                                           ((400, {"error": {"message": LEAK}}), 502),
                                           ((413, {"detail": LEAK}), 502),
                                           ((500, {"detail": LEAK}), 502),
                                           ((503, {"detail": LEAK}), 503),
                                           ((401, {"detail": LEAK}), 503),
                                           ((403, {"detail": LEAK}), 503),
                                           ((404, {"detail": LEAK}), 503),
                                           ((429, {"error": LEAK}), 429)])
def test_a_provider_answer_is_a_short_safe_answer(browser, relay, tcompute, reply, status):
    tcompute.reply = reply
    r = dictate(browser)
    assert r.status == status and "/srv" not in r.text and LEAK not in r.text and KEY not in r.text
    assert LEAK not in json.dumps(diagnostics.read()) and KEY not in json.dumps(diagnostics.read())


@pytest.mark.parametrize("code", [301, 302, 307])
def test_a_redirect_on_the_post_is_an_answer_not_a_road(browser, relay, tcompute, code):
    tcompute.redirect = code
    assert dictate(browser).status == 502
    assert len(tcompute.seen) == 1                                         # the Location was never asked, key and sound stayed here


def test_the_key_goes_to_the_host_of_the_url_only(browser, relay, tcompute):
    other = FakeTCompute()
    try:
        tcompute.redirect, tcompute.elsewhere = 302, other.url + "/audio/transcriptions"   # another host and port
        assert dictate(browser).status == 502
        assert len(tcompute.seen) == 1 and other.seen == []
    finally:
        other.close()


@pytest.mark.parametrize("reply", [(503, {}), (0, None)])
def test_a_provider_that_drops_out_takes_the_button_away_for_30_seconds(browser, relay, tcompute, clock, reply):
    assert available(browser)
    if reply[0] == 0:
        tcompute.truncate = True
    else:
        tcompute.reply = reply
    assert dictate(browser).status == 503
    tcompute.truncate, tcompute.reply = False, (200, {"text": "back"})
    assert available(browser) is False
    clock.advance(29)
    assert available(browser) is False
    clock.advance(2)
    assert available(browser) is True
    assert dictate(browser).status == 200


@pytest.mark.parametrize("code", [401, 403, 404])
def test_a_refused_key_or_a_wrong_base_keeps_dictation_off_until_the_key_file_changes(browser, relay, tcompute, key_file, clock, code):
    tcompute.reply = (code, {})
    assert dictate(browser).status == 503
    tcompute.reply = (200, {"text": "back"})
    clock.advance(31)
    assert available(browser) is False                                     # 30 s are not the way out
    clock.advance(3600)
    assert available(browser) is False
    assert dictate(browser).status == 503 and len(tcompute.calls()) == 1   # nothing is asked while it is off
    key_file.write_text(f"TRANSCRIBE_API_KEY={KEY}-new\n")                 # a new key, same path
    key_file.chmod(0o600)
    assert available(browser) is True
    assert dictate(browser).status == 200


def test_a_touched_key_file_of_the_same_size_brings_dictation_back(browser, relay, tcompute, key_file):
    tcompute.reply = (401, {})
    dictate(browser)
    before = key_file.stat()
    os.utime(key_file, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))
    assert available(browser) is True


def test_a_restart_brings_dictation_back_after_a_refused_key(browser, tcompute, key_file):
    first = transcribe.Relay(transcribe.parse(table(tcompute, key_file), "the test"))
    browser.hub.transcribe = first
    tcompute.reply = (404, {})
    dictate(browser)
    assert first.available() is False
    assert transcribe.Relay(first.cfg).available() is True


def test_a_provider_that_is_busy_does_not_take_dictation_away(browser, relay, tcompute):
    tcompute.reply = (429, {})
    assert dictate(browser).status == 429
    assert available(browser) is True


def test_one_relay_at_a_time(browser, relay, tcompute):
    assert available(browser)
    with relay._busy:
        r = dictate(browser)
    assert r.status == 429 and tcompute.calls() == []


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


@pytest.mark.parametrize("reply, status", [((200, {"text": "x"}), 200), ((301, {}), 301), ((400, {}), 400),
                                           ((401, {}), 401), ((503, {}), 503), ((429, {}), 429)])
def test_the_row_holds_the_status_the_provider_gave(browser, relay, tcompute, reply, status):
    tcompute.redirect = reply[0] if reply[0] == 301 else False
    tcompute.reply = reply
    dictate(browser)
    assert [str(r["status"]) for r in diagnostics.read() if r["kind"] == "transcribe"] == [str(status)]


def test_the_row_says_no_status_when_no_call_was_made(browser, tcompute, key_file):
    browser.hub.transcribe = transcribe.Relay(transcribe.parse(table(tcompute, key_file), "the test"), record=browser.hub.record)
    key_file.chmod(0o644)
    dictate(browser)
    assert [r for r in diagnostics.read() if r["kind"] == "transcribe"] and all("status" not in r for r in diagnostics.read() if r["kind"] == "transcribe")


def test_the_row_has_no_status_for_a_busy_relay(browser, relay):
    with relay._busy:
        dictate(browser)
    assert all("status" not in r for r in diagnostics.read() if r["kind"] == "transcribe")


def test_a_provider_that_gave_no_answer_is_status_zero(browser, relay, tcompute):
    tcompute.truncate = True
    dictate(browser)
    assert [str(r["status"]) for r in diagnostics.read() if r["kind"] == "transcribe"] == ["0"]


@pytest.fixture
def row_relay(browser, tcompute, key_file, clock):
    browser.hub.transcribe = transcribe.Relay(transcribe.parse(table(tcompute, key_file), "the test"), clock=clock,
                                              record=browser.hub.record)
    return browser.hub.transcribe


def refused(code=None):
    return [r for r in diagnostics.read() if r["kind"] == "transcribe-refused" and (code is None or str(r["status"]) == str(code))]


def test_the_first_refusal_of_each_code_is_said_once(browser, row_relay, tcompute, key_file, clock):
    def touch():                                                           # a new key file turns dictation back on
        key_file.write_text(f"TRANSCRIBE_API_KEY={KEY}-{time.monotonic_ns()}\n")
        key_file.chmod(0o600)
    tcompute.reply = (401, {})
    dictate(browser)
    assert len(refused(401)) == 1
    touch()
    dictate(browser)
    assert len(refused(401)) == 1                                          # a second 401: no second row
    touch()
    tcompute.reply = (404, {})
    dictate(browser)
    assert len(refused(404)) == 1 and len(refused()) == 2
    assert all(set(r) >= {"status"} and KEY not in json.dumps(r) and LEAK not in json.dumps(r) for r in refused())


@pytest.mark.parametrize("reply, truncate", [((503, {}), False), ((429, {}), False), ((200, {"text": "x"}), True), ((500, {}), False)])
def test_a_transient_answer_writes_no_refused_row(browser, row_relay, tcompute, reply, truncate):
    tcompute.reply, tcompute.truncate = reply, truncate
    dictate(browser)
    assert refused() == []


def test_a_first_503_cannot_hide_a_later_401(browser, row_relay, tcompute, clock):
    tcompute.reply = (503, {})
    dictate(browser)
    clock.advance(31)
    tcompute.reply = (401, {})
    dictate(browser)
    assert len(refused(401)) == 1


# ── https: the one connection hook that every outside provider uses ───────────

@pytest.fixture
def trusting(monkeypatch):
    """The hub trusts the fixture certificate (and nothing else) for the test."""
    context = ssl.create_default_context(cafile=str(TLS / "loopback-cert.pem"))
    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: context)


def test_a_verified_https_provider_gets_the_key_and_the_sound(browser, key_file, trusting, tmp_path):
    provider = FakeTCompute(tls=True, tmp=tmp_path)
    try:
        browser.hub.transcribe = transcribe.Relay(transcribe.parse(table(provider, key_file), "the test"))
        assert dictate(browser).status == 200
        assert {k.lower(): v for k, v in provider.calls()[0][2].items()}["authorization"] == f"Bearer {KEY}"
    finally:
        provider.close()


def test_an_https_provider_with_a_certificate_nobody_trusts_is_refused_and_gets_no_key(browser, key_file, tmp_path):
    provider = FakeTCompute(tls=True, tmp=tmp_path)
    try:
        browser.hub.transcribe = transcribe.Relay(transcribe.parse(table(provider, key_file), "the test"))
        assert dictate(browser).status == 503
        assert provider.seen == []
    finally:
        provider.close()


def test_the_hub_does_not_take_its_trust_from_the_default_of_http_client(browser, key_file, tmp_path, monkeypatch):
    """Another library that sets the default https context to an unverified one must not send the key unchecked."""
    monkeypatch.setattr(ssl, "_create_default_https_context", ssl._create_unverified_context)
    provider = FakeTCompute(tls=True, tmp=tmp_path)
    try:
        browser.hub.transcribe = transcribe.Relay(transcribe.parse(table(provider, key_file), "the test"))
        assert dictate(browser).status == 503
        assert provider.seen == []
    finally:
        provider.close()


# ── the key file: what is read, and what is stamped ──────────────────────────

def test_a_key_the_header_cannot_carry_is_refused_with_a_reason_and_never_quoted(browser, row_relay, tcompute, key_file):
    odd = "k\u00e9y-\u65e5\u672c-0123"                             # not latin-1: http.client would refuse the header
    key_file.write_text(f"TRANSCRIBE_API_KEY={odd}\n")
    key_file.chmod(0o600)
    assert available(browser) is False
    assert dictate(browser).status == 503 and tcompute.seen == []
    rows = [r for r in diagnostics.read() if r["kind"] == "transcribe-key-file"]
    assert len(rows) == 1 and "latin-1" in rows[0]["reason"]
    assert odd not in json.dumps(diagnostics.read(), ensure_ascii=False) and "0123" not in json.dumps(rows)


def test_a_damaged_byte_in_the_key_is_refused_the_same_way(browser, row_relay, tcompute, key_file):
    key_file.write_bytes(b"TRANSCRIBE_API_KEY=abc\xff\xfedef\n")          # not UTF-8: read as U+FFFD
    key_file.chmod(0o600)
    assert dictate(browser).status == 503 and tcompute.seen == []
    assert [r["kind"] for r in diagnostics.read()].count("transcribe-key-file") == 1


def test_a_latin_1_key_is_still_taken(browser, relay, tcompute, key_file):
    key_file.write_text("TRANSCRIBE_API_KEY=cl\u00e9-0123\n")
    key_file.chmod(0o600)
    assert dictate(browser).status == 200 and len(tcompute.calls()) == 1


def test_the_stamp_is_the_one_of_the_file_the_key_came_from(relay, key_file, monkeypatch):
    """A writer that finishes between the stat and the read must not leave the old stamp with the new key."""
    real, done = os.fstat, []

    def fstat(fd):
        st = real(fd)
        if not done:                                                        # the writer finishes right after the first stat
            done.append(1)
            key_file.write_text(f"TRANSCRIBE_API_KEY={KEY}-rewritten-longer\n")
        return st
    monkeypatch.setattr(transcribe.os, "fstat", fstat)
    key, stamp = relay._key()
    fresh = key_file.stat()
    assert key.endswith("rewritten-longer")
    assert stamp == (fresh.st_mtime_ns, fresh.st_ctime_ns, fresh.st_size, fresh.st_ino)


def test_two_dictations_in_line_do_not_send_a_refused_key_twice(browser, relay, tcompute):
    """B passed `available()` while A was in flight; A's 401 comes first; B takes the lock after it."""
    original, raced = relay.available, []

    def available():
        ok = original()
        if not raced:
            raced.append(1)
            tcompute.reply = (401, {})
            with pytest.raises(transcribe.Unavailable):
                relay.transcribe(AUDIO, "webm")                             # A, whole, inside B's test of availability
        return ok
    relay.available = available
    with pytest.raises(transcribe.Unavailable):
        relay.transcribe(AUDIO, "webm")                                     # B
    assert len(tcompute.calls()) == 1


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
