"""`sheaf token add | list | revoke` (SPEC 9.7, 13). They need no hub: they work on tokens.json,
and the hub reads that file afresh on every request."""
import json
import re

import pytest

from sheafmd import paths
from sheafmd.hub.state import TokenRow, Tokens

TOKEN = re.compile(r"sheaf_mcp_[A-Za-z0-9_-]{43}")


def test_add_prints_the_token_once_and_the_hub_knows_it_at_once(sheaf):
    r = sheaf("token", "add", "codex", "--as", "Codex")
    assert r.code == 0 and r.err == ""
    [token] = TOKEN.findall(r.out)
    assert r.out.count(token) == 1
    assert "codex" in r.out and "Codex" in r.out
    assert Tokens().verify(token) == TokenRow("codex", "Codex", False)
    assert "write" not in r.out                     # a token reads and answers unless told more


def test_add_says_how_and_where_the_token_is_sent(sheaf):
    out = sheaf("token", "add", "codex").out
    assert "`Authorization: Bearer <token>`" in out
    assert re.search(r"http://127\.0\.0\.1:\d+/_/mcp\b", out)


def test_the_token_is_nowhere_in_the_state_folder(sheaf):
    token = TOKEN.search(sheaf("token", "add", "codex").out).group(0)
    for f in paths.state_dir().rglob("*"):
        if f.is_file():
            assert token.encode() not in f.read_bytes(), f


def test_list_shows_names_display_names_created_and_last_used_and_nothing_secret(sheaf):
    token = TOKEN.search(sheaf("token", "add", "codex", "--as", "Codex").out).group(0)
    sheaf("token", "add", "gemini")
    first = sheaf("token", "list")
    assert first.code == 0
    lines = first.out.strip().splitlines()
    assert len(lines) == 3 and lines[2] == f"  read from {Tokens.path()}"
    lines = lines[:2]
    assert lines[0].split()[:2] == ["codex", "Codex"] and "never" in lines[0]
    assert lines[1].split()[:2] == ["gemini", "gemini"]
    assert re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d", lines[0])
    Tokens().verify(token)
    second = sheaf("token", "list").out.strip().splitlines()[0]
    assert "never" not in second and re.search(r"last used \d{4}-\d\d-\d\dT", second)
    everything = first.out + second + sheaf("token", "list").out
    assert "sheaf_mcp_" not in everything
    assert not re.search(r"[0-9a-f]{40,}", everything)         # no hash either


@pytest.mark.parametrize("display", [None, "", 5, ["a"], "a\x00b"], ids=["missing", "empty", "number", "list", "uncleaned"])
def test_list_shows_a_row_verify_refuses_and_says_so(sheaf, display):
    """A hand-edited row `verify` refuses (no usable display) is still listed, flagged, never a crash."""
    token = TOKEN.search(sheaf("token", "add", "codex", "--as", "Codex").out).group(0)
    sheaf("token", "add", "gemini")
    row = {"name": "edited", "sha256": "0" * 64, "created": "2026-10-23T01:00:00", "last_used": None}
    if display is not None:
        row["display"] = display
    tokens_json = paths.state_dir() / "tokens.json"
    tokens_json.write_text(json.dumps(json.loads(tokens_json.read_text()) + [row]))
    r = sheaf("token", "list")
    assert r.code == 0 and r.err == ""
    lines = r.out.strip().splitlines()[:-1]                 # the last line names the file read
    assert len(lines) == 3
    assert lines[2].split()[:2] == ["edited", "(invalid)"] and "refused" in lines[2]
    assert "refused" not in lines[0] + lines[1]             # a good row is listed as before
    assert Tokens().verify(token) == TokenRow("codex", "Codex", False)


def test_list_with_no_tokens_says_so(sheaf):
    r = sheaf("token", "list")
    assert r.code == 0 and "no tokens" in r.out


def test_revoke_ends_the_token(sheaf):
    token = TOKEN.search(sheaf("token", "add", "codex").out).group(0)
    r = sheaf("token", "revoke", "codex")
    assert r.code == 0 and "codex" in r.out
    assert Tokens().verify(token) is None
    assert "no tokens" in sheaf("token", "list").out


def test_revoking_a_name_that_is_not_there_fails(sheaf):
    r = sheaf("token", "revoke", "codex")
    assert r.code == 1 and "no token named codex" in r.err and r.out == ""


@pytest.mark.parametrize("args,why", [
    (["add", "codex", "--as", "  \x07 "], "display name"),
    (["add", "a b"], "token name"),
    (["add", ""], "token name"),
])
def test_add_refuses_a_bad_name_and_makes_nothing(sheaf, args, why):
    r = sheaf("token", *args)
    assert r.code == 1 and why in r.err and r.out == ""
    assert Tokens().list() == []


def test_add_cleans_a_display_name_and_says_what_it_signs_with(sheaf):
    r = sheaf("token", "add", "codex", "--as", "  Codex \x07  CLI " + "x" * 70)
    assert r.code == 0
    assert f"signed {'Codex CLI ' + 'x' * 50!r}" in r.out
    assert Tokens().list()[0].display == "Codex CLI " + "x" * 50


def test_add_refuses_a_name_that_is_taken_and_keeps_the_first_token(sheaf):
    token = TOKEN.search(sheaf("token", "add", "codex").out).group(0)
    r = sheaf("token", "add", "codex")
    assert r.code == 1 and "already exists" in r.err and "sheaf_mcp_" not in r.out + r.err
    assert Tokens().verify(token)


@pytest.mark.parametrize("args", [[], ["add"], ["revoke"], ["frobnicate"], ["list", "extra"]])
def test_a_usage_mistake_is_exit_2(sheaf, args):
    assert sheaf("token", *args).code == 2


def test_the_help_says_what_a_token_is_in_the_glossarys_words(sheaf):
    """GLOSSARY: an MCP token is a named, revocable secret for the HTTP MCP door; it is not a key
    (the hub key is another thing)."""
    token_help = sheaf("token", "--help").out.lower()
    assert "secret" in token_help and "mcp door" in token_help and not re.search(r"\bkey\b", token_help)


def test_the_help_lists_the_command(sheaf):
    out = sheaf("--help").out
    assert "token add NAME [--as DISPLAY] [--write]" in out and "token revoke NAME" in out


# ── the right to write pages (9.7) ───────────────────────────────────────────

def test_add_with_write_makes_a_token_that_may_work_on_pages_and_says_so(sheaf):
    r = sheaf("token", "add", "writer", "--write")
    assert r.code == 0 and r.err == ""
    token = TOKEN.search(r.out).group(0)
    assert Tokens().verify(token) == TokenRow("writer", "writer", True)
    assert "may read, make and change pages" in r.out


def test_list_says_which_tokens_may_write(sheaf):
    sheaf("token", "add", "codex")
    sheaf("token", "add", "writer", "--write")
    codex, writer, _folder = sheaf("token", "list").out.strip().splitlines()
    assert codex.split()[0] == "codex" and "write" not in codex
    assert writer.split()[0] == "writer" and writer.rstrip().endswith("may write")


def test_the_help_of_add_names_the_write_right(sheaf):
    out = sheaf("token", "add", "--help").out
    assert "--write" in out and "pages" in out


# ── a member's name of proxy mode (SPEC 9.9) ─────────────────────────────────

def proxy_config(name="Ada"):
    import getpass
    p = paths.config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('[proxy]\norigin = "https://chat.example.com"\nsocket = "/run/x/hub.sock"\n'
                 f'proxy_user = "{getpass.getuser()}"\n[proxy.members."m1"]\nname = "{name}"\n'
                 'roots = ["/srv/x"]\n', encoding="utf-8")


@pytest.mark.parametrize("args", [("ada", "--as", "Ada"), ("helper", "--as", " ada "), ("Ada",)])
def test_add_refuses_a_display_name_a_member_has_and_makes_nothing(sheaf, args):
    proxy_config()
    r = sheaf("token", "add", *args)
    assert r.code == 1 and "member" in r.err and "Ada" in r.err
    assert Tokens().list() == []


def test_add_takes_a_name_no_member_has(sheaf):
    proxy_config()
    assert sheaf("token", "add", "codex", "--as", "Codex helper").code == 0


def test_list_shows_a_row_with_a_bad_name_escaped_on_one_line(sheaf):
    row = {"name": "bad\x1b[31m\nname", "display": "Ada", "sha256": "0" * 64, "created": 5, "last_used": ["x"]}
    paths.state_dir().mkdir(parents=True, exist_ok=True)
    (paths.state_dir() / "tokens.json").write_text(json.dumps([row]))
    r = sheaf("token", "list")
    assert r.code == 0 and r.err == ""
    [line, _folder] = r.out.strip().splitlines()
    assert "\x1b" not in r.out and line.startswith("bad\\x1b[31m\\nname  (invalid)") and "refused by verify" in line


@pytest.fixture
def hand_run(monkeypatch, tmp_path):
    """The hub's unit sets SHEAF_HOME (folder A) and holds a token; a hand run of the
    same account has no SHEAF_HOME and reads folder B. Returns the file the hand run reads."""
    hub_file = Tokens.path()
    Tokens().add("page-writer", None, write=True)
    assert hub_file.is_file()
    monkeypatch.delenv("SHEAF_HOME")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "hand-state"))
    assert Tokens.path() != hub_file
    return Tokens.path()


def test_a_hand_run_that_finds_no_tokens_names_the_folder_it_read(sheaf, hand_run):
    r = sheaf("token", "list")
    assert r.code == 0 and f"no tokens in {hand_run}" in r.out


def test_a_hand_run_that_revokes_nothing_names_the_folder_it_read(sheaf, hand_run):
    r = sheaf("token", "revoke", "page-writer")
    assert r.code == 1 and f"no token named page-writer in {hand_run}" in r.err


def test_every_action_names_the_tokens_file(sheaf):
    where = str(Tokens.path())
    assert f"Written to {where}" in sheaf("token", "add", "codex").out
    assert f"read from {where}" in sheaf("token", "list").out
    assert f"revoked, in {where}" in sheaf("token", "revoke", "codex").out


def test_add_names_the_file_even_when_the_port_cannot_be_read(sheaf, monkeypatch):
    """The token is written before the port is resolved."""
    monkeypatch.setenv("SHEAF_PORT", "not-a-port")
    r = sheaf("token", "add", "codex")
    assert Tokens.path().is_file() and str(Tokens.path()) in r.out
