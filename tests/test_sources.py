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
        site.hub.sources.get("shop").checked = 0.0
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
