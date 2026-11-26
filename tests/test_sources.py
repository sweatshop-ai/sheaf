"""`[sources.<name>]` and the hub that serves a source as a root (ADR 0006, block editor v1 ticket 21)."""
import dataclasses
import json
import os
from pathlib import Path

import pytest
from source_fakes import ReferenceService, Stand
from two_hubs import Site

from sheafmd import config, paths
from sheafmd import adapter as rda
from sheafmd.hub.sources import State

UID = "d1000000-0000-4000-8000-000000000001"
BEARER = "a-bearer-of-sixteen-plus-chars"


def write_config(text: str):
    path = paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def secret(tmp_path, text=BEARER + "\n", mode=0o600, name="bearer"):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    f.chmod(mode)
    return f


# ── the declaration ──────────────────────────────────────────────────────────

def test_a_source_is_declared_with_url_secrets_and_theme(tmp_path):
    f = secret(tmp_path)
    write_config(f'[sources.shop]\nurl = "unix:///run/shop/s.sock"\nsecrets = "{f}"\ntheme = "plain"\n')
    declared, problems = config.load_sources()
    assert problems == {}
    assert [(d.name, d.url, d.secrets, d.theme) for d in declared] == [("shop", "unix:///run/shop/s.sock", f, "plain")]


@pytest.mark.parametrize("key", ["bearer", "token", "key", "password", "site_key", "api_key"])
def test_a_key_to_the_site_or_a_bearer_in_the_config_is_refused_and_not_echoed(tmp_path, key):
    f = secret(tmp_path)
    write_config(f'[sources.shop]\nurl = "unix:///run/s.sock"\nsecrets = "{f}"\n{key} = "SEKRET-VALUE-0123456789"\n')
    declared, problems = config.load_sources()
    assert declared == [] and "shop" in problems
    assert key in problems["shop"] and "SEKRET-VALUE" not in problems["shop"]


def test_one_bad_source_leaves_the_others_declared(tmp_path):
    f = secret(tmp_path)
    write_config(f'[sources.a]\nurl = "unix:///run/a.sock"\nsecrets = "{f}"\n\n[sources.b]\nurl = "http://site.example"\nsecrets = "{f}"\n')
    declared, problems = config.load_sources()
    assert [d.name for d in declared] == ["a"] and "b" in problems and "https" in problems["b"]


@pytest.mark.parametrize("name", ["_x", ".x", "Clients", "a b", "a/b"])
def test_a_source_name_is_one_a_root_can_have(tmp_path, name):
    f = secret(tmp_path)
    write_config(f'[sources."{name}"]\nurl = "unix:///run/a.sock"\nsecrets = "{f}"\n')
    declared, problems = config.load_sources()
    assert declared == [] and problems


def test_a_url_with_a_credential_is_refused_without_echoing_it(tmp_path):
    f = secret(tmp_path)
    write_config(f'[sources.shop]\nurl = "https://user:hunter2hunter2@site.example"\nsecrets = "{f}"\n')
    _, problems = config.load_sources()
    assert "shop" in problems and "hunter2" not in problems["shop"]


# ── the bearer file ──────────────────────────────────────────────────────────

def decl(path):
    return config.SourceDecl("shop", "unix:///run/s.sock", Path(path))


def test_the_bearer_is_read_from_a_file_only_the_hubs_account_can_read(tmp_path):
    assert config.read_bearer(decl(secret(tmp_path))) == BEARER


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
def test_a_secrets_file_others_can_read_is_refused(tmp_path, mode):
    with pytest.raises(config.ConfigError) as e:
        config.read_bearer(decl(secret(tmp_path, mode=mode)))
    assert BEARER not in str(e.value)


@pytest.mark.parametrize("text", ["", "short\n", "two words in one line here\n", BEARER + "\nsecond line\n", "päss-" + "x" * 20,
                                  "x" * 600, "x" * 2000])
def test_a_secrets_file_that_does_not_hold_one_bearer_is_refused_and_not_echoed(tmp_path, text):
    with pytest.raises(config.ConfigError) as e:
        config.read_bearer(decl(secret(tmp_path, text=text)))
    assert "x" * 30 not in str(e.value) and "pass-" not in str(e.value)


def test_a_missing_file_and_a_link_are_refused(tmp_path):
    with pytest.raises(config.ConfigError):
        config.read_bearer(decl(tmp_path / "none"))
    real = secret(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(config.ConfigError):
        config.read_bearer(decl(link))


# ── the hub ──────────────────────────────────────────────────────────────────

THEME = "[theme]\nname = \"srctheme\"\nwordmark = \"SOURCEMARK\"\n"


def _theme(tmp_path):
    d = tmp_path / "srctheme"
    d.mkdir()
    (d / "theme.toml").write_text('name = "srctheme"\nwordmark = "SOURCEMARK"\n', encoding="utf-8")
    return d


def source_text(name, url, secrets_file, theme=None):
    """The `[sources.<name>]` table, written so that no line of it has the shape of a secret (the file's path is not one)."""
    lines = [f"[sources.{name}]", f"url = {json.dumps(url)}", f"secrets = {json.dumps(str(secrets_file))}"]
    if theme:
        lines.append(f"theme = {json.dumps(str(theme))}")
    return "\n".join(lines) + "\n"


def hub_with(tmp_path, request, decls):
    """A tiroir's hub whose config.toml declares `decls` (a list of `[sources.x]` texts)."""
    home = tmp_path / "client-home"
    home.mkdir()
    (home / "config.toml").write_text("\n".join(decls), encoding="utf-8")
    site = Site(tmp_path, "client", 27431, "https://t.example.com", {UID: ("Dora", "dora@example.com", False)})
    members = site.hub.proxy.members
    members[UID] = dataclasses.replace(members[UID], sources=("shop", "odd"))    # a source is a member's only when named
    return site


@pytest.fixture
def service(tmp_path, request):
    folder = tmp_path / "shop-docs"
    folder.mkdir()
    (folder / "home.md").write_text("# Shop home\n\nHello from the source.\n", encoding="utf-8")
    (tmp_path / "svc").mkdir()
    s = ReferenceService(folder, tmp_path / "svc")
    request.addfinalizer(s.stop)
    return s


def get(site, path):
    with site.inside():
        return site.front.get(path, member=UID)


def test_a_source_is_a_root_and_its_page_opens_with_the_theme_the_source_names(tmp_path, request, service):
    theme = _theme(tmp_path)
    hub_secret = secret(tmp_path, text=service.bearer + "\n", name="hubbearer")
    site = hub_with(tmp_path, request, [source_text("shop", service.url, hub_secret, theme)])
    page = get(site, "/shop/home.md")
    assert page.status == 200
    html = page.body.decode()
    assert "Hello from the source." in html and "SOURCEMARK" in html
    listing = get(site, "/shop/")
    assert listing.status == 200 and b"home.md" in listing.body
    assert get(site, "/shop/none.md").status == 404
    assert get(site, "/shop/home.txt").status == 404


def test_a_service_with_another_interface_leaves_only_its_own_root_unserved(tmp_path, request, service):
    odd = Stand(lambda verb, body, h: (200, {"interface": 2, "name": "x", "publish": False}))
    request.addfinalizer(odd.stop)
    good = secret(tmp_path, text=service.bearer + "\n", name="good")
    other = secret(tmp_path, name="other")
    site = hub_with(tmp_path, request, [
        f'[sources.shop]\nurl = "{service.url}"\nsecrets = "{good}"\n',
        f'[sources.odd]\nurl = "{odd.url}"\nsecrets = "{other}"\n'])
    bad = get(site, "/odd/x.md")
    assert bad.status == 503
    words = bad.body.decode()
    assert "odd" in words and "interface version 2" in words and f"this hub speaks {rda.INTERFACE_VERSION}" in words
    assert BEARER not in words
    assert get(site, "/shop/home.md").status == 200
    # the mismatch is not retried: the service is asked its info once
    get(site, "/odd/x.md")
    assert [v for v, _, _ in odd.seen] == ["info"]


def test_a_service_that_is_down_is_asked_again_and_serves_when_it_is_back(tmp_path, request, service):
    hub_secret = secret(tmp_path, text=service.bearer + "\n", name="hubbearer")
    url = service.url
    site = hub_with(tmp_path, request, [source_text("shop", "unix:///tmp/ss-none/gone.sock", hub_secret)])
    assert get(site, "/shop/home.md").status == 503
    with site.inside():
        site.hub.sources.get("shop").decl = config.SourceDecl("shop", url, hub_secret, None)
        site.hub.sources.get("shop").state = State()          # the retry delay has passed
    assert get(site, "/shop/home.md").status == 200


def test_a_laptops_hub_serves_no_source(tmp_path, request, service):
    hub_secret = secret(tmp_path, text=service.bearer + "\n", name="hubbearer")
    site = hub_with(tmp_path, request, [source_text("shop", service.url, hub_secret)])
    with site.inside():
        site.hub.proxy_was, site.hub.proxy = site.hub.proxy, None
        try:
            err = site.hub.sources.ensure("shop").error
        finally:
            site.hub.proxy = site.hub.proxy_was
    assert "laptop" in err and service.bearer not in err


def test_a_source_name_a_folder_root_holds_is_unserved_and_the_folder_stays(tmp_path, request, service):
    hub_secret = secret(tmp_path, text=service.bearer + "\n", name="hubbearer")
    site = hub_with(tmp_path, request, [source_text("shop", service.url, hub_secret)])
    with site.inside():
        folder = tmp_path / "folder-root"
        folder.mkdir()
        with pytest.raises(Exception):
            site.hub.roots._add(folder, False, name="shop")


def test_a_member_whose_sources_do_not_name_a_source_cannot_read_it(tmp_path, request, service):
    hub_secret = secret(tmp_path, text=service.bearer + "\n", name="hubbearer")
    site = hub_with(tmp_path, request, [source_text("shop", service.url, hub_secret)])
    members = site.hub.proxy.members
    members[UID] = dataclasses.replace(members[UID], sources=())
    assert get(site, "/shop/home.md").status == 404
    assert get(site, "/shop/").status == 404
    assert get(site, "/shop").status == get(site, "/nobody-has-this").status == 404     # the bare name does not tell it exists


def test_a_member_is_told_nothing_of_a_path_when_the_secrets_file_is_wrong(tmp_path, request, service):
    bad = secret(tmp_path, text=service.bearer + "\n", name="hubbearer", mode=0o644)
    site = hub_with(tmp_path, request, [source_text("shop", service.url, bad)])
    page = get(site, "/shop/home.md")
    assert page.status == 503 and str(bad) not in page.body.decode() and "hubbearer" not in page.body.decode()


def test_a_version_code_of_the_service_is_a_mismatch_until_restart(tmp_path, request, service):
    odd = Stand(lambda verb, body, h: (409, {"error": {"code": "version", "message": "other"}}))
    request.addfinalizer(odd.stop)
    other = secret(tmp_path, name="other")
    site = hub_with(tmp_path, request, [source_text("odd", odd.url, other)])
    assert get(site, "/odd/x.md").status == 503
    get(site, "/odd/x.md")
    assert [v for v, _, _ in odd.seen] == ["info"]


def test_a_source_named_like_a_members_folder_root_leaves_the_folder_served(tmp_path, request, service):
    hub_secret = secret(tmp_path, text=service.bearer + "\n", name="hubbearer")
    site = hub_with(tmp_path, request, [source_text("dora", service.url, hub_secret)])
    members = site.hub.proxy.members
    members[UID] = dataclasses.replace(members[UID], sources=("dora",))
    with site.inside():
        keep, site.hub.roots.reserved = site.hub.roots.reserved, tuple      # a folder root that was there before the source was declared
        try:
            site.hub.roots._add(site.roots["dora"], False, name="dora")
        finally:
            site.hub.roots.reserved = keep
        assert site.hub.roots.held("dora") is not None
    page = get(site, "/dora/")
    assert page.status != 503 and b"is not served" not in page.body


def test_a_probe_that_is_out_never_lifts_a_refusal_made_meanwhile(tmp_path):
    import threading
    from sheafmd.hub.sources import Sources
    f = secret(tmp_path)
    gate, started = threading.Event(), threading.Event()

    class Slow:
        def __init__(self, name, url, bearer):
            pass

        def info(self):
            started.set()
            gate.wait(5)

    srcs = Sources([config.SourceDecl("shop", "unix:///run/s.sock", f)], make=Slow)
    t = threading.Thread(target=srcs.ensure, args=("shop",))
    t.start()
    assert started.wait(5)
    srcs.refuse("shop", "a folder root already has this name")
    assert srcs.ensure("shop").error                 # no second probe is made while one is out
    gate.set()
    t.join(5)
    assert not srcs.get("shop").served and srcs.get("shop").error


def test_a_probe_that_raises_what_nobody_expected_does_not_leave_the_source_probing(tmp_path):
    from sheafmd.hub.sources import RETRY_AFTER, Sources
    f = secret(tmp_path)
    now, calls = [100.0], []

    class Odd:
        def __init__(self, name, url, bearer):
            pass

        def info(self):
            calls.append(1)
            raise AttributeError("a closed connection")

    srcs = Sources([config.SourceDecl("shop", "unix:///run/s.sock", f)], make=Odd, clock=lambda: now[0])
    with pytest.raises(AttributeError):
        srcs.ensure("shop")
    now[0] += RETRY_AFTER + 1
    with pytest.raises(AttributeError):
        srcs.ensure("shop")
    assert len(calls) == 2 and not srcs.get("shop").probing


def test_no_second_probe_starts_while_one_is_out_and_the_old_probe_ends_what_it_began(tmp_path):
    import threading
    from sheafmd.hub.sources import RETRY_AFTER, Sources
    f = secret(tmp_path)
    gate, started, calls, now = threading.Event(), threading.Event(), [], [100.0]

    class Slow:
        def __init__(self, name, url, bearer):
            pass

        def info(self):
            calls.append(1)
            started.set()
            gate.wait(5)

    srcs = Sources([config.SourceDecl("shop", "unix:///run/s.sock", f)], make=Slow, clock=lambda: now[0])
    t = threading.Thread(target=srcs.ensure, args=("shop",))
    t.start()
    assert started.wait(5)
    now[0] += RETRY_AFTER + 1                          # the retry interval passes while the first probe is still out
    assert not srcs.ensure("shop").served and len(calls) == 1
    gate.set()
    t.join(5)
    assert srcs.get("shop").served and srcs.get("shop").probing is None
    assert srcs.ensure("shop").served and len(calls) == 1


def _srcs(tmp_path, make, now):
    from sheafmd.hub.sources import Sources
    return Sources([config.SourceDecl("shop", "unix:///run/s.sock", secret(tmp_path))], make=make, clock=lambda: now[0])


def _fake(outcomes, gate=None):
    """A service whose `info` answers by `outcomes` in turn: "ok", "down" or "version"; it counts the calls out at once."""
    import threading
    from sheafmd import remote
    lock, box = threading.Lock(), {"out": 0, "most": 0, "calls": 0}

    class Fake:
        def __init__(self, name, url, bearer):
            pass

        def info(self):
            with lock:
                box["out"] += 1
                box["most"] = max(box["most"], box["out"])
                box["calls"] += 1
                what = outcomes[(box["calls"] - 1) % len(outcomes)]
            try:
                if gate:
                    gate.wait(5)
                if what == "down":
                    raise remote.Unreachable("down")
                if what == "version":
                    raise remote.VersionMismatch("shop", 2)
            finally:
                with lock:
                    box["out"] -= 1
    return Fake, box


def test_a_source_moves_only_the_ways_its_state_allows(tmp_path):
    from sheafmd.hub import sources as S
    now = [100.0]
    fake, box = _fake(["down", "ok"])
    srcs = _srcs(tmp_path, fake, now)
    s = srcs.get("shop")
    assert s.state.kind == S.IDLE
    assert srcs._move(s, S.SERVED, token=object()) is None and srcs._move(s, S.FAILED, token=object()) is None   # no probe, no result
    first = srcs._move(s, S.PROBING)
    assert first and s.state.kind == S.PROBING
    assert srcs._move(s, S.PROBING) is None                                           # not while one is out
    assert srcs._move(s, S.SERVED, token=object(), client=object()) is None           # not by a probe that is not the one out
    assert srcs._move(s, S.FAILED, token=first.token, error="e", shown="e").kind == S.FAILED
    assert srcs._move(s, S.PROBING) is None                                           # not before the retry delay
    now[0] += S.RETRY_AFTER
    second = srcs._move(s, S.PROBING)
    assert second
    assert srcs._move(s, S.SERVED, token=first.token, client=object()) is None        # the old probe's result is dropped
    assert srcs._move(s, S.SERVED, token=second.token, client=object()).kind == S.SERVED
    assert srcs._move(s, S.PROBING) is None                                           # a served source is not probed
    assert srcs._move(s, S.FAILED, token=second.token, error="e", shown="e") is None  # nor taken down by a late failure
    assert srcs._move(s, S.FAILED, error="laptop", shown="laptop") is None            # nor by the hub's "not a tiroir" answer
    assert srcs._move(s, S.REFUSED, error="r", shown="r").kind == S.REFUSED           # the hub's own refusal is for good
    now[0] += 10 * S.RETRY_AFTER
    assert srcs._move(s, S.PROBING) is None and srcs._move(s, S.SERVED, token=second.token, client=object()) is None


def test_many_callers_never_make_two_probes_at_once_and_a_served_source_stays_served(tmp_path):
    import itertools
    import threading
    from sheafmd.hub.sources import RETRY_AFTER
    tick = itertools.count()
    tlock = threading.Lock()

    class Clock:
        def __getitem__(self, _):
            with tlock:
                return next(tick) * RETRY_AFTER             # every look at the clock finds the retry delay passed
    fake, box = _fake(["down", "down", "ok", "down", "ok"])
    srcs = _srcs(tmp_path, fake, Clock())
    served_seen, lost = [], []

    def caller():
        for _ in range(60):
            s = srcs.ensure("shop")
            if served_seen and not s.served:
                lost.append(1)
            if s.served:
                served_seen.append(1)
    threads = [threading.Thread(target=caller) for _ in range(16)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert box["most"] == 1                                 # never more than one probe at a time
    assert served_seen and not lost and srcs.get("shop").served
    assert box["calls"] == 3                                # down, down, ok: a served source is never asked again


# ── round 8: what a member is told, what a refusal covers, the wire ────────────

LEAK = "Bearer SECRETBEARERVALUE123456 echoed by the service"


def test_a_members_page_never_holds_the_upstream_error_text_but_the_status(tmp_path, request):
    def answer(verb, body, h):
        if verb == "info":
            return 200, {"interface": rda.INTERFACE_VERSION, "name": "x", "publish": False}
        return 503, {"error": {"code": "unavailable", "message": LEAK}}
    stand = Stand(answer)
    request.addfinalizer(stand.stop)
    site = hub_with(tmp_path, request, [source_text("shop", stand.url, secret(tmp_path))])
    page = get(site, "/shop/")
    assert page.status == 503 and b"SECRETBEARERVALUE" not in page.body and b"echoed" not in page.body
    assert b"HTTP 503" in page.body


def test_the_log_text_of_an_upstream_error_has_the_bearer_and_authorization_taken_out():
    from sheafmd import remote
    out = remote.redact("echo: Authorization: Bearer abcdefghijklmnop1234 and abcdefghijklmnop1234 again", "abcdefghijklmnop1234")
    assert "abcdefghijklmnop1234" not in out and "echo:" in out


def test_a_source_page_is_never_rendered_as_a_share_copy(tmp_path, request, service, monkeypatch):
    from sheafmd.hub import handler
    seen = []
    real = handler.render_file
    monkeypatch.setattr(handler, "render_file", lambda *a, **k: (seen.append(k), real(*a, **k))[1])
    site = hub_with(tmp_path, request, [source_text("shop", service.url, secret(tmp_path, text=service.bearer + "\n", name="hubbearer"))])
    assert get(site, "/shop/home.md").status == 200
    assert seen and seen[0]["share"] is False


def test_a_secrets_path_of_an_account_that_does_not_exist_refuses_that_source_only(tmp_path):
    f = secret(tmp_path)
    write_config(source_text("bad", "unix:///run/a.sock", "~no-such-account-zz/bearer") + "\n"
                 + source_text("good", "unix:///run/b.sock", f))
    declared, problems = config.load_sources()
    assert [d.name for d in declared] == ["good"] and "bad" in problems


def test_a_secrets_file_that_is_a_fifo_is_refused_at_once(tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(config.ConfigError) as e:
        config.read_bearer(decl(fifo))
    assert "regular" in str(e.value)


def test_a_service_that_trickles_its_headers_is_cut_at_the_one_deadline(request):
    import socket as sk
    import threading
    import time
    from sheafmd import remote
    run = __import__("source_fakes").short_dir()
    path = str(run / "t.sock")
    srv = sk.socket(sk.AF_UNIX)
    srv.bind(path)
    srv.listen(1)
    stop = threading.Event()

    def trickle():
        c, _ = srv.accept()
        c.recv(65536)
        c.sendall(b"HTTP/1.1 200 OK\r\n")
        while not stop.is_set():
            try:
                c.sendall(b"X-A: b\r\n")
            except OSError:
                return
            time.sleep(0.1)
    t = threading.Thread(target=trickle, daemon=True)
    t.start()
    request.addfinalizer(lambda: (stop.set(), srv.close()))
    src = remote.RemoteSource("shop", f"unix://{path}", "b" * 20, timeout=1.0)
    started = time.monotonic()
    with pytest.raises(remote.Unreachable):
        src.ask("info", {})
    assert time.monotonic() - started < 3


def test_an_empty_cursor_is_sent_and_a_version_that_is_not_an_int_is_a_mismatch(request):
    from sheafmd import remote
    pages = {None: {"documents": [{"name": "a.md"}], "next": ""}, "": {"documents": [{"name": "b.md"}], "next": None}}

    def answer(verb, body, h):
        if verb == "documents":
            return 200, pages[body.get("cursor")]
        return 200, {"interface": 1.0, "name": "x", "publish": False}
    stand = Stand(answer)
    request.addfinalizer(stand.stop)
    src = remote.RemoteSource("shop", stand.url, "b" * 20)
    assert list(src.documents()) == ["a.md", "b.md"]
    with pytest.raises(remote.VersionMismatch):
        src.info()


# ── round 9: read-only pages, the mount route, one deadline from the name to the answer, no bearer in any text ─────

def _page_meta(body: bytes) -> dict:
    import re
    return json.loads(re.search(rb'<script id="rd-edit-meta" type="application/json"[^>]*>(.*?)</script>', body, re.S).group(1))


def test_a_source_page_is_read_only_for_the_browser(tmp_path, request, service):
    site = hub_with(tmp_path, request, [source_text("shop", service.url, secret(tmp_path, text=service.bearer + "\n", name="hubbearer"))])
    page = get(site, "/shop/home.md")
    assert page.status == 200
    meta = _page_meta(page.body)
    assert meta.get("readonly") is True and meta.get("why_readonly")


def test_the_mount_route_serves_a_source_page_as_the_page_route_does(tmp_path, request, service):
    site = hub_with(tmp_path, request, [source_text("shop", service.url, secret(tmp_path, text=service.bearer + "\n", name="hubbearer"))])
    got = get(site, "/_/mount?doc=shop/home.md")
    assert got.status == 200
    data = json.loads(got.body)
    assert "Hello from the source." in data["html"]
    assert data["config"]["readonly"] is True and data["config"]["why_readonly"]
    assert get(site, "/_/mount?doc=shop/none.md").status == 404
    assert get(site, "/_/mount?doc=other/home.md").status == 404


def test_a_member_without_the_source_gets_no_mount_of_it(tmp_path, request, service):
    site = hub_with(tmp_path, request, [source_text("shop", service.url, secret(tmp_path, text=service.bearer + "\n", name="hubbearer"))])
    members = site.hub.proxy.members
    members[UID] = dataclasses.replace(members[UID], sources=())
    assert get(site, "/_/mount?doc=shop/home.md").status == 404


def _hangs_in(monkeypatch, where, seconds):
    import socket as sk
    import time
    if where == "dns":
        monkeypatch.setattr(sk, "getaddrinfo", lambda *a, **k: time.sleep(seconds) or [])
    else:
        monkeypatch.setattr(sk, "getaddrinfo", lambda host, port, *a, **k: [(sk.AF_INET, sk.SOCK_STREAM, 6, "", ("127.0.0.1", port))] * 8)

        def slow_connect(self, address):
            time.sleep(min(self.gettimeout() or seconds, 0.4))
            raise TimeoutError("timed out")
        monkeypatch.setattr(sk.socket, "connect", slow_connect)


@pytest.mark.parametrize("where", ["dns", "attempts"])
def test_the_name_lookup_and_every_connect_attempt_are_inside_the_one_deadline(monkeypatch, where):
    import time
    from sheafmd import remote
    _hangs_in(monkeypatch, where, 4)
    src = remote.RemoteSource("shop", "https://shop.example.net:8080/", "b" * 20, connect_timeout=0.5, timeout=1.0)
    started = time.monotonic()
    with pytest.raises(remote.Unreachable):
        src.ask("info", {})
    assert time.monotonic() - started < 1.5


def test_the_connect_limit_holds_for_a_name_that_never_resolves(monkeypatch):
    import time
    from sheafmd import remote
    _hangs_in(monkeypatch, "dns", 4)
    src = remote.RemoteSource("shop", "https://shop.example.net:8080/", "b" * 20, connect_timeout=0.4, timeout=30.0)
    started = time.monotonic()
    with pytest.raises(remote.Unreachable):
        src.ask("info", {})
    assert time.monotonic() - started < 1.2


def test_no_text_the_adapter_raises_or_refuses_with_holds_the_bearer_the_service_echoes(request):
    from sheafmd import remote
    bearer = "SECRETBEARERVALUE123456"

    def echo(verb, body, headers):
        said = f"seen {headers.get('Authorization')} and {bearer} and Authorization: Bearer {bearer}"
        if verb == "write":
            return 403, {"error": {"code": "unknown_author", "message": said}}
        if verb == "read":
            return 404, {"error": {"code": "not_found", "message": said}}
        if verb == "documents":
            return 503, {"error": {"code": "unavailable", "message": said}}
        return 400, {"error": {"code": "bad_request", "message": said}}
    stand = Stand(echo)
    request.addfinalizer(stand.stop)
    src = remote.RemoteSource("shop", stand.url, bearer)
    out = src.adapter("d.md").write(rda.Tree("x\n"), "b", author="Mallory", note="")
    assert out["outcome"] == "refused" and bearer not in json.dumps(out)
    for call in (lambda: src.adapter("d.md").read(), lambda: list(src.documents()), lambda: src.ask("nothing", {}), lambda: src.info()):
        with pytest.raises(remote.SourceError) as e:
            call()
        assert bearer not in str(e.value) and bearer not in e.value.message
