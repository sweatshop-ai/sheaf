"""The hub-to-hub channel (ticket 20): `/_/tiroir/*` on the proxy socket, reached by a peer tiroir with a peer
token and by nobody else; the peer token and its scopes; `sheaf peer add | use`. In memory through the handler
(`front`), a temp home and a fake keyring: no real token is in a fixture, a log or an output."""
import errno
import json
import os
import re
from dataclasses import replace

import pytest
from helpers import BEA, CAL

from sheafmd import connect, paths
from sheafmd.hub import channel as chan
from sheafmd.hub.state import Tokens

PEER = "https://other.example.com"
TAILNET = {"X-Forwarded-For": "100.101.102.103"}
TOKEN = re.compile(r"sheaf_mcp_[A-Za-z0-9_-]{43}")


class FakeKeyring:
    def __init__(self):
        self.items = {}

    def get(self, service, user):
        return self.items.get((service, user))

    def set(self, service, user, secret):
        self.items[(service, user)] = secret


@pytest.fixture
def keyring(monkeypatch):
    k = FakeKeyring()
    monkeypatch.setattr(connect, "system_store", lambda: k)
    return k


@pytest.fixture
def members(front):
    """Bea, with her e-mail; Cal, with none."""
    front.hub.proxy.members[BEA] = replace(front.hub.proxy.members[BEA], email="bea@example.com")
    return front


def peer_token(scopes=None, origin=PEER):
    """A peer token as `sheaf peer add` makes it, made through the store."""
    return Tokens().add_peer(f"peer-{len(Tokens().list())}", origin, scopes)


def channel(front, verb, body=None, token=None, headers=None, **kw):
    h = {**TAILNET, **({"Authorization": f"Bearer {token}"} if token else {}), **(headers or {})}
    return front.post(f"/_/tiroir/{verb}", body or {}, member=kw.pop("member", None), headers=h, **kw)


# ── the narrow rule: this prefix, from the tailnet, with a peer token; nothing else ──────────────

def test_a_peer_with_its_token_from_the_tailnet_reaches_the_channel_without_a_member(members):
    token = peer_token()
    res = channel(members, "resolve", {"owner_email": "bea@example.com"}, token)
    assert res.status == 200 and res.json() == {"ok": True}


@pytest.mark.parametrize("headers", [{"X-Forwarded-For": "203.0.113.9"}, {"X-Forwarded-For": "100.1.1.1, 203.0.113.9"},
                                      {"X-Forwarded-For": "not an address"}, {"X-Forwarded-For": ""}, {}],
                         ids=["public", "tailnet-looking-first", "garbage", "empty", "none"])
def test_a_source_that_is_not_on_the_tailnet_gets_the_answer_of_an_unknown_route(members, headers):
    token = peer_token()
    res = members.post("/_/tiroir/resolve", {"owner_email": "bea@example.com"}, member=None,
                       headers={"Authorization": f"Bearer {token}", **headers})
    unknown = members.post("/_/tiroir/nothing", {}, member=None, headers={**TAILNET})
    assert res.status == unknown.status == 404 and res.body == unknown.body


def test_the_tailnet_ranges_of_both_families_are_let_in(members):
    token = peer_token()
    for source in ("100.64.0.1", "100.127.255.254", "fd7a:115c:a1e0::1"):
        res = channel(members, "resolve", {"owner_email": "bea@example.com"}, token, {"X-Forwarded-For": source})
        assert res.status == 200, source
    for source in ("100.63.255.255", "100.128.0.1", "fd7a:115c:a1e1::1"):
        res = channel(members, "resolve", {"owner_email": "bea@example.com"}, token, {"X-Forwarded-For": source})
        assert res.status == 404, source


def test_without_a_token_with_a_wrong_one_or_a_revoked_one_the_answer_is_an_unknown_route(members):
    token = peer_token()
    unknown = channel(members, "nothing", {})
    assert channel(members, "resolve", {}).body == unknown.body
    assert channel(members, "resolve", {}, "sheaf_mcp_" + "x" * 43).body == unknown.body
    Tokens().revoke(Tokens().list()[0].name)
    assert channel(members, "resolve", {"owner_email": "bea@example.com"}, token).body == unknown.body


def test_a_member_header_does_not_open_the_channel_and_does_not_replace_the_token(members):
    token = peer_token()
    unknown = channel(members, "nothing", {})
    assert channel(members, "resolve", {}, member=BEA).body == unknown.body
    res = channel(members, "resolve", {"owner_email": "bea@example.com"}, token, member=CAL)
    assert res.status == 200                       # the token decides; a member header on this route changes nothing


def test_a_door_token_is_no_peer_token_and_a_peer_token_is_no_door_token(members, browser):
    door = Tokens().add("agent", client="Claude Code", write=True)
    unknown = channel(members, "nothing", {})
    assert channel(members, "resolve", {}, door).body == unknown.body
    peer = peer_token()
    res = browser.post("/_/mcp", {}, cookie=False, headers={"Authorization": f"Bearer {peer}"})
    assert res.status in (401, 403)


def test_every_other_path_without_a_member_header_stays_behind_the_sign_in(members):
    token = peer_token()
    for path in ("/", "/_/doc?doc=work/plan.md", "/_/tirior/resolve", "/_/tiroir", "/work/plan.md"):
        res = members.request("GET", path, member=None, headers={**TAILNET, "Authorization": f"Bearer {token}"})
        assert res.status == 401, path


def test_only_a_post_reaches_a_verb(members):
    token = peer_token()
    res = members.request("GET", "/_/tiroir/resolve", member=None, headers={**TAILNET, "Authorization": f"Bearer {token}"})
    unknown = channel(members, "nothing", {})
    assert res.status == 404 and res.body == unknown.body


def test_the_loopback_port_has_no_channel(browser):
    res = browser.post("/_/tiroir/resolve", {}, cookie=False, headers={**TAILNET, "Authorization": f"Bearer {peer_token()}"})
    assert res.status in (401, 404)


# ── the scopes ───────────────────────────────────────────────────────────────

def test_a_peer_token_with_no_scopes_field_transfers(members):
    peer_token()
    rows = json.loads(Tokens.path().read_text())
    token = Tokens().add_peer("old", PEER)
    rows = json.loads(Tokens.path().read_text())
    for row in rows:
        row.pop("scopes", None)
    Tokens.path().write_text(json.dumps(rows))
    row = Tokens().verify_peer(token)
    assert row is not None and row.allows("transfer") and not row.allows("read")
    assert channel(members, "resolve", {"owner_email": "bea@example.com"}, token).status == 200


def test_a_token_whose_scopes_lack_transfer_does_not_resolve_or_transfer(members):
    token = peer_token(["read"])
    unknown = channel(members, "nothing", {})
    for verb in ("resolve", "transfer"):
        assert channel(members, verb, {"owner_email": "bea@example.com"}, token).body == unknown.body


def test_the_store_keeps_the_scopes_and_never_the_token(members):
    token = peer_token(["transfer", "read"])
    [row] = [r for r in json.loads(Tokens.path().read_text())]
    assert row["peer"] == PEER and row["scopes"] == ["transfer", "read"] and "display" not in row
    assert token not in Tokens.path().read_text()


def test_a_scope_that_does_not_exist_is_refused():
    with pytest.raises(Exception, match="scope"):
        Tokens().add_peer("p", PEER, ["write"])


# ── sheaf peer add | use ─────────────────────────────────────────────────────

def test_peer_add_does_not_tell_the_token_onto_a_command_line(sheaf):
    """The hint a person copies must not put the token in `ps` and the shell history: it pipes it in."""
    r = sheaf("peer", "add", PEER)
    [token] = TOKEN.findall(r.out)
    hint = next(ln for ln in r.out.splitlines() if "peer use" in ln)
    assert "<token>" not in hint and token not in hint
    assert "standard input" in hint

def test_peer_add_prints_the_token_once_and_stores_transfer_only(sheaf):
    r = sheaf("peer", "add", PEER)
    assert r.code == 0 and r.err == ""
    [token] = TOKEN.findall(r.out)
    assert r.out.count(token) == 1
    row = Tokens().verify_peer(token)
    assert row.peer == PEER and row.allows("transfer") and not row.allows("read")
    assert "transfer" in r.out
    for f in paths.state_dir().rglob("*"):
        if f.is_file():
            assert token.encode() not in f.read_bytes(), f


def test_peer_add_with_scope_read_grants_read_and_the_default_does_not(sheaf):
    token = TOKEN.search(sheaf("peer", "add", PEER, "--scope", "read").out).group(0)
    assert Tokens().verify_peer(token).allows("read")
    assert not Tokens().verify_peer(token).allows("transfer")       # a scope asked for is the list: no transfer unless named
    both = TOKEN.search(sheaf("peer", "add", "https://third.example.com", "--scope", "transfer", "--scope", "read").out).group(0)
    assert Tokens().verify_peer(both).allows("read") and Tokens().verify_peer(both).allows("transfer")


def test_peer_add_refuses_an_origin_that_is_not_one_and_a_scope_that_is_not_one(sheaf):
    assert sheaf("peer", "add", "http://other.example.com").code != 0
    assert sheaf("peer", "add", "https://other.example.com/path").code != 0
    assert sheaf("peer", "add", PEER, "--scope", "admin").code != 0
    assert Tokens().list() == []


def test_a_peer_token_is_listed_by_origin_and_scopes_and_never_shown(sheaf):
    token = TOKEN.search(sheaf("peer", "add", PEER).out).group(0)
    out = sheaf("token", "list").out
    assert PEER in out and "transfer" in out and token not in out


def test_peer_use_keeps_the_token_in_the_keyring_and_prints_nothing_of_it(sheaf, keyring):
    token = "sheaf_mcp_" + "a" * 43
    r = sheaf("peer", "use", PEER, token)
    assert r.code == 0 and token not in r.out + r.err
    assert keyring.get("sheaf-peer", PEER) == token
    assert keyring.get("sheaf", PEER) is None                       # a laptop's credential for the tiroir is another thing


def test_peer_use_refuses_something_that_is_not_a_token_or_an_origin(sheaf, keyring):
    assert sheaf("peer", "use", PEER, "hunter2").code != 0
    assert sheaf("peer", "use", "other.example.com", "sheaf_mcp_" + "a" * 43).code != 0
    assert keyring.items == {}


def test_peer_use_without_a_keyring_says_so(sheaf, monkeypatch):
    def none():
        raise connect.ConnectError("no login keyring on this computer")
    monkeypatch.setattr(connect, "system_store", none)
    r = sheaf("peer", "use", PEER, "sheaf_mcp_" + "a" * 43)
    assert r.code != 0 and "keyring" in r.err and "sheaf_mcp_" not in r.err


# ── peer use: the token on stdin, and the file store a service reads from $CREDENTIALS_DIRECTORY ─────────────────

FAKE = "sheaf_mcp_" + "b" * 43


@pytest.fixture
def stdin(monkeypatch):
    """Put `text` on the standard input of the next command; it is a pipe, never a terminal."""
    import io
    def put(text, tty=False):
        s = io.StringIO(text)
        s.isatty = lambda: tty
        monkeypatch.setattr("sys.stdin", s)
    return put


def test_peer_use_reads_the_token_from_stdin_when_none_is_given(sheaf, keyring, stdin):
    stdin(FAKE + "\n")
    r = sheaf("peer", "use", PEER)
    assert r.code == 0 and FAKE not in r.out + r.err
    assert keyring.get("sheaf-peer", PEER) == FAKE


def test_peer_use_on_a_terminal_without_a_token_asks_for_a_pipe_and_keeps_nothing(sheaf, keyring, stdin):
    stdin(FAKE + "\n", tty=True)
    r = sheaf("peer", "use", PEER)
    assert r.code == 2 and "pipe" in r.err and FAKE not in r.out + r.err
    assert keyring.items == {}


@pytest.mark.parametrize("text", ["", "\n", "hunter2\n", FAKE + "\nsecond line\n", FAKE[:-1] + "\n"])
def test_peer_use_refuses_a_stdin_that_is_not_exactly_one_token(sheaf, keyring, stdin, text):
    stdin(text)
    r = sheaf("peer", "use", PEER)
    assert r.code != 0 and keyring.items == {} and FAKE not in r.out + r.err


def test_the_help_of_peer_use_names_the_argument_form_as_discouraged(sheaf):
    r = sheaf("peer", "use", "--help")
    assert "discouraged" in r.out and "standard input" in " ".join(r.out.split())


def test_peer_use_into_a_file_store_writes_one_0600_file_in_a_0700_folder_and_prints_no_token(sheaf, keyring, stdin, tmp_path):
    folder = tmp_path / "creds"
    stdin(FAKE + "\n")
    r = sheaf("peer", "use", PEER, "--store", "file", "--dir", folder)
    assert r.code == 0 and FAKE not in r.out + r.err
    name = connect.peer_credential_name(PEER)
    assert [f.name for f in folder.iterdir()] == [name]
    assert (folder / name).read_text().strip() == FAKE
    assert (folder / name).stat().st_mode & 0o777 == 0o600 and folder.stat().st_mode & 0o777 == 0o700
    assert keyring.items == {}                                      # the file store never touches the keyring


def test_the_file_store_needs_a_folder_and_a_folder_needs_the_file_store(sheaf, stdin, tmp_path):
    stdin(FAKE + "\n")
    assert sheaf("peer", "use", PEER, "--store", "file").code == 2
    stdin(FAKE + "\n")
    assert sheaf("peer", "use", PEER, "--dir", tmp_path / "x").code == 2
    assert not (tmp_path / "x").exists()


def test_a_failed_close_does_not_hide_the_write_that_failed_first(tmp_path, monkeypatch):
    real_fsync, real_close = os.fsync, os.close

    def no_sync(fd):
        raise OSError(errno.EIO, "the disk said no")

    def no_close(fd):
        real_close(fd)
        raise OSError(errno.EBADF, "close said no")
    monkeypatch.setattr(os, "fsync", no_sync)
    monkeypatch.setattr(os, "close", no_close)
    with pytest.raises(connect.ConnectError) as e:
        connect.use_peer_file(PEER, FAKE, tmp_path / "creds")
    assert "the disk said no" in str(e.value) and "close said no" not in str(e.value)
    assert not list((tmp_path / "creds").iterdir())


def test_a_failed_cleanup_does_not_hide_the_write_that_failed_first(tmp_path, monkeypatch):
    from pathlib import Path

    def no_sync(fd):
        raise OSError(errno.EIO, "the disk said no")

    def no_unlink(self, missing_ok=False):
        raise OSError(errno.EROFS, "read-only now")
    monkeypatch.setattr(os, "fsync", no_sync)
    monkeypatch.setattr(Path, "unlink", no_unlink)
    with pytest.raises(connect.ConnectError) as e:
        connect.use_peer_file(PEER, FAKE, tmp_path / "creds")
    assert "the disk said no" in str(e.value) and "read-only now" not in str(e.value)


def test_a_failed_cleanup_does_not_hide_an_interrupt(tmp_path, monkeypatch):
    from pathlib import Path

    def interrupted(fd):
        raise KeyboardInterrupt

    def no_unlink(self, missing_ok=False):
        raise OSError(errno.EROFS, "read-only now")
    monkeypatch.setattr(os, "fsync", interrupted)
    monkeypatch.setattr(Path, "unlink", no_unlink)
    with pytest.raises(KeyboardInterrupt):
        connect.use_peer_file(PEER, FAKE, tmp_path / "creds")


def test_the_file_store_replaces_a_token_and_leaves_other_peers_alone(sheaf, stdin, tmp_path):
    tmp_path = tmp_path / "creds"
    other = "sheaf_mcp_" + "c" * 43
    for origin, token in ((PEER, FAKE), ("https://third.example.com", other), (PEER, other)):
        stdin(token + "\n")
        assert sheaf("peer", "use", origin, "--store", "file", "--dir", tmp_path).code == 0
    assert (tmp_path / connect.peer_credential_name(PEER)).read_text().strip() == other
    assert len(list(tmp_path.iterdir())) == 2


def test_a_credential_name_is_one_safe_word_per_origin_and_port():
    a, b = connect.peer_credential_name(PEER), connect.peer_credential_name("https://other.example.com:8443")
    assert a != b and re.fullmatch(r"[A-Za-z0-9._-]+", a + b)
    assert connect.peer_credential_name("HTTPS://Other.Example.com") == a


def test_no_two_peer_origins_share_a_credential_name():
    # A shared file name would send the token kept for one peer to the other (ticket 190 E).
    origins = ["https://a.example:8443", "https://a.example-8443", "https://a.example_p8443", "https://a.example",
               "https://[::1]:8443", "https://[::1]", "https://a_3a.example",
               "https://a.example:443", "https://a.example:44"]
    names = [connect.peer_credential_name(o) for o in origins]
    assert len(set(names)) == len({connect.origin_of(o) for o in origins})
    assert all(re.fullmatch(r"[A-Za-z0-9._-]+", n) for n in names)


def test_a_credential_file_of_the_old_port_name_is_not_read_for_the_other_peer(monkeypatch, tmp_path):
    (tmp_path / "sheaf-peer-a.example-8443").write_text(FAKE)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert connect._credential_file("https://a.example:8443") is None
    assert connect._credential_file("https://a.example-8443") == FAKE



def test_a_credential_file_left_under_the_old_port_name_is_said_once(monkeypatch, tmp_path, capsys):
    (tmp_path / "sheaf-peer-b.example-8443").write_text(FAKE)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert connect._credential_file("https://b.example:8443") is None
    assert connect._credential_file("https://b.example:8443") is None
    err = capsys.readouterr().err
    assert err.count("sheaf-peer-b.example-8443") == 1 and "sheaf-peer-b.example_p8443" in err and FAKE not in err


def test_the_hub_reads_the_peer_token_from_the_credentials_folder_before_the_keyring(keyring, monkeypatch, tmp_path):
    keyring.set("sheaf-peer", PEER, "sheaf_mcp_" + "k" * 43)
    (tmp_path / connect.peer_credential_name(PEER)).write_text(FAKE + "\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert connect.peer_token_for(PEER) == FAKE


def test_with_a_credential_file_the_keyring_is_never_asked(monkeypatch, tmp_path):
    (tmp_path / connect.peer_credential_name(PEER)).write_text(FAKE)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    def refuse():
        raise AssertionError("the keyring was asked although the credential file holds the token")
    monkeypatch.setattr(connect, "system_store", refuse)
    assert connect.peer_token_for(PEER) == FAKE


def test_without_a_credential_file_or_with_one_that_is_no_token_the_keyring_answers(keyring, monkeypatch, tmp_path):
    keyring.set("sheaf-peer", PEER, FAKE)
    assert connect.peer_token_for(PEER) == FAKE                    # no CREDENTIALS_DIRECTORY at all
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert connect.peer_token_for(PEER) == FAKE                    # a folder with no file for this origin
    (tmp_path / connect.peer_credential_name(PEER)).write_text("not a token\n")
    assert connect.peer_token_for(PEER) == FAKE                    # a file that is no token is no credential
    assert connect.peer_token_for("https://third.example.com") is None


def test_a_credential_file_for_one_origin_is_not_used_for_another(monkeypatch, tmp_path):
    (tmp_path / connect.peer_credential_name(PEER)).write_text(FAKE)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(connect, "system_store", lambda: FakeKeyring())
    assert connect.peer_token_for("https://third.example.com") is None


def test_the_file_the_command_writes_is_the_file_the_hub_reads(sheaf, stdin, monkeypatch, tmp_path):
    stdin(FAKE + "\n")
    assert sheaf("peer", "use", PEER, "--store", "file", "--dir", tmp_path).code == 0
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert connect.peer_token_for(PEER) == FAKE


# ── the two findings of the review of the file store ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def warned_nothing_yet():
    connect._WARNED.clear()


@pytest.mark.parametrize("how", ["a file", "a closed folder", "a leftover link"])
def test_a_file_store_that_cannot_be_written_is_a_message_and_not_a_traceback(sheaf, stdin, tmp_path, how, request):
    folder = tmp_path / "creds"
    if how == "a file":
        folder.write_text("x")
    elif how == "a closed folder":
        request.getfixturevalue("closed")(folder)     # only this case needs the folder shut: root enters any folder and skips it
    else:
        folder.mkdir()
        (folder / (connect.peer_credential_name(PEER) + ".new")).symlink_to(tmp_path / "elsewhere")
    stdin(FAKE + "\n")
    r = sheaf("peer", "use", PEER, "--store", "file", "--dir", folder)
    assert r.code == 1 and r.err.startswith("sheaf: ") and "Traceback" not in r.err
    assert str(folder) in r.err and FAKE not in r.out + r.err
    assert not (tmp_path / "elsewhere").exists()


def test_an_unreadable_credential_file_is_a_warning_without_its_content_and_the_keyring_answers(keyring, monkeypatch, tmp_path, capsys):
    keyring.set("sheaf-peer", PEER, FAKE)
    (tmp_path / connect.peer_credential_name(PEER)).write_bytes(b"\xff\xfe" + FAKE.encode() + b"\x80")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert connect.peer_token_for(PEER) == FAKE
    err = capsys.readouterr().err
    assert len(err.strip().splitlines()) == 1 and connect.peer_credential_name(PEER) in err
    assert FAKE not in err and "\xff" not in err and "sheaf_mcp_" not in err


def test_a_missing_credential_file_says_nothing(keyring, monkeypatch, tmp_path, capsys):
    keyring.set("sheaf-peer", PEER, FAKE)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert connect.peer_token_for(PEER) == FAKE
    assert capsys.readouterr().err == ""


def test_a_failure_after_the_token_was_written_leaves_no_temp_file_and_the_message_stays_true(sheaf, stdin, tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(connect.os, "replace", refuse)
    stdin(FAKE + "\n")
    r = sheaf("peer", "use", PEER, "--store", "file", "--dir", tmp_path / "creds")
    assert r.code == 1 and "nothing was written" in r.err and FAKE not in r.out + r.err
    assert list((tmp_path / "creds").iterdir()) == []               # neither the file nor its temp: the token is nowhere


def test_a_leftover_temp_that_is_not_ours_is_left_alone_when_the_open_refuses_it(sheaf, stdin, tmp_path):
    folder = tmp_path / "creds"
    folder.mkdir()
    link = folder / (connect.peer_credential_name(PEER) + ".new")
    link.symlink_to(tmp_path / "elsewhere")
    stdin(FAKE + "\n")
    assert sheaf("peer", "use", PEER, "--store", "file", "--dir", folder).code == 1
    assert link.is_symlink() and not (tmp_path / "elsewhere").exists()


def test_a_corrupt_credential_file_is_warned_about_once_per_process(keyring, monkeypatch, tmp_path, capsys):
    keyring.set("sheaf-peer", PEER, FAKE)
    (tmp_path / connect.peer_credential_name(PEER)).write_bytes(b"\xff\xfe")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    for _ in range(3):
        assert connect.peer_token_for(PEER) == FAKE
    assert len(capsys.readouterr().err.strip().splitlines()) == 1
    (tmp_path / connect.peer_credential_name("https://third.example.com")).write_bytes(b"\xff")
    keyring.set("sheaf-peer", "https://third.example.com", FAKE)
    connect.peer_token_for("https://third.example.com")               # another peer's file is another warning
    assert len(capsys.readouterr().err.strip().splitlines()) == 1


# ── the root verb ────────────────────────────────────────────────

ROOT_BODY = {"id": "m1", "repo": "o/r", "branch": "dev", "tip": "abc", "from": {"origin": "https://third.example", "by": "bea"},
             "pages": []}


@pytest.fixture
def landed(monkeypatch):
    """What `incoming.land_root` is called with; it answers an empty landing."""
    seen = []
    monkeypatch.setattr("sheafmd.hub.incoming.land_root",
                        lambda hub, body, peer=None: (seen.append((body, peer)), (200, {"pages": {}}))[1])
    return seen


def test_a_peer_with_the_transfer_scope_reaches_the_root_verb_and_is_the_peer_the_token_names(members, landed):
    res = channel(members, "root", ROOT_BODY, peer_token())
    assert res.status == 200 and res.json() == {"pages": {}}
    assert landed == [(ROOT_BODY, PEER)]          # the body says the root comes from third.example: only the token's origin counts


def test_anyone_else_gets_the_answer_of_an_unknown_route_on_the_root_verb(members, landed):
    unknown = channel(members, "nothing", {})
    assert channel(members, "root", ROOT_BODY).body == unknown.body
    assert channel(members, "root", ROOT_BODY, "sheaf_mcp_" + "x" * 43).body == unknown.body
    assert channel(members, "root", ROOT_BODY, peer_token(), headers={"X-Forwarded-For": "8.8.8.8"}).body == unknown.body
    assert channel(members, "root", ROOT_BODY, peer_token(["read"])).body == unknown.body
    assert landed == []


def test_a_root_body_may_be_as_big_as_a_transfer_and_no_bigger(members, landed):
    token = peer_token()
    h = {**TAILNET, "Authorization": f"Bearer {token}"}
    ok = json.dumps({**ROOT_BODY, "pad": "x" * (64 * 1024)}).encode()
    assert members.request("POST", "/_/tiroir/root", member=None, raw=ok, headers=h).status == 200
    big = json.dumps({**ROOT_BODY, "pad": "x" * (chan.MAX_TRANSFER + 1)}).encode()
    assert members.request("POST", "/_/tiroir/root", member=None, raw=big, headers=h).status == 413
    assert len(landed) == 1


def test_a_body_that_is_not_a_root_is_a_400(members):
    res = channel(members, "root", {"id": "m1"}, peer_token())
    assert res.status == 400
