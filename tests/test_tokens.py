"""MCP tokens: made, stored as a hash, checked, revoked (SPEC 9.7, 4.2).

The store is a file the CLI writes and the hub reads, two processes, so every test that checks a
token builds a second `Tokens` over the same folder where it matters."""
import hashlib
import json
import re
import stat

import pytest

from sheafmd import mcp, paths
from sheafmd.hub import auth
from sheafmd.hub.auth import token_hash
from sheafmd.hub.state import TokenError, TokenRow, Tokens

TOKEN_RE = re.compile(r"sheaf_mcp_[A-Za-z0-9_-]{43}")


def the_file():
    return paths.state_dir() / "tokens.json"


def test_a_token_is_a_prefix_and_32_random_bytes_in_base64url():
    a, b = auth.new_token(), auth.new_token()
    assert TOKEN_RE.fullmatch(a) and TOKEN_RE.fullmatch(b) and a != b


def test_the_file_holds_the_sha256_of_the_token_and_never_the_token():
    token = Tokens().add("codex", "Codex")
    f = the_file()
    assert token not in f.read_text(encoding="utf-8")
    [row] = json.loads(f.read_text(encoding="utf-8"))
    assert row["sha256"] == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert row["name"] == "codex" and row["display"] == "Codex"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}", row["created"])
    assert row["last_used"] is None
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700


def test_the_display_name_defaults_to_the_name():
    Tokens().add("codex")
    assert Tokens().list()[0].display == "codex"


def test_the_longest_name_and_display_name_are_accepted():
    Tokens().add("x" * 40, "y" * 60)
    assert Tokens().list()[0].name == "x" * 40 and Tokens().list()[0].display == "y" * 60


@pytest.mark.parametrize("name", ["", " ", "a b", "a/b", "../x", "x" * 41, "é", "a\nb"])
def test_a_name_is_a_short_word(name):
    with pytest.raises(TokenError):
        Tokens().add(name)
    assert not the_file().exists()


@pytest.mark.parametrize("display", ["", "   ", "\x00", "\x07\u200b", "\n\t"])
def test_a_display_name_with_nothing_left_once_cleaned_is_refused(display):
    with pytest.raises(TokenError, match="display name"):
        Tokens().add("codex", display)
    assert not the_file().exists()


@pytest.mark.parametrize("display", ["x" * 61, "a\nb", "a\x00b", "  Claude   Code ", "a\u200b b", "é" * 70])
def test_a_display_name_is_cleaned_the_way_the_hub_cleans_one_from_a_header(display):
    """One rule for a display name, whoever gives it (SPEC 12): an agent's header, `--agent`, or a
    person's `--as`. What is left once it is cleaned is what the token signs with."""
    Tokens().add("codex", display)
    assert Tokens().list()[0].display == auth.clean_display(display) != ""


@pytest.mark.parametrize("given", ["a\u200b b", "a \u200b b", "\u00a0a\u00a0", "a\u200b\u200b  b\u200b",
                                   "x" * 59 + " y", "x" * 59 + " \u200by", "\x07 a \x07 b \x07"])
def test_a_name_that_is_cleaned_is_the_same_name_the_door_cleans_again(given):
    """`sheaf mcp --agent` cleans the name, and the hub cleans what arrives: the two must agree."""
    once = auth.clean_display(given)
    assert auth.clean_display(once) == once
    assert mcp.display_for(given, environ={}) == once


def test_cleaning_a_clean_name_never_changes_it():
    import random
    rng, pool = random.Random(93), ["a", "b", "é", " ", " ", "\t", "\n", "\u200b", "\x00", "\x07", "\u00a0", "😀"]
    for _ in range(3000):
        given = "".join(rng.choice(pool) for _ in range(rng.randint(0, 90)))
        once = auth.clean_display(given)
        assert auth.clean_display(once) == once, repr(given)


def test_a_name_is_taken_once():
    t = Tokens()
    t.add("codex")
    with pytest.raises(TokenError, match="already"):
        t.add("codex", "Other")
    assert len(t.list()) == 1


def test_a_token_that_was_made_is_known_to_another_process():
    token = Tokens().add("codex", "Codex")
    got = Tokens().verify(token)
    assert got.name == "codex" and got.display == "Codex"


@pytest.mark.parametrize("given", [None, "", "sheaf_mcp_", "nope", 12, "sheaf_mcp_" + "A" * 43,
                                   "x" * 5000])
def test_a_token_that_was_never_made_is_refused(given):
    Tokens().add("codex")
    assert Tokens().verify(given) is None


def test_a_revoked_token_stops_working_at_once_for_a_reader_that_already_ran():
    hub_side = Tokens()
    token = hub_side.add("codex")
    assert hub_side.verify(token)
    assert Tokens().revoke("codex") is True          # the CLI, in its own process
    assert hub_side.verify(token) is None
    assert the_file().read_text(encoding="utf-8").strip() == "[]"


def test_revoking_a_name_that_is_not_there_says_so():
    Tokens().add("codex")
    assert Tokens().revoke("gemini") is False
    assert [r.name for r in Tokens().list()] == ["codex"]


def test_only_the_revoked_one_goes():
    t = Tokens()
    a, b = t.add("codex"), t.add("gemini")
    t.revoke("codex")
    assert t.verify(a) is None and t.verify(b).name == "gemini"


def test_last_used_is_stamped_by_use_and_at_most_once_a_minute():
    clock = [1_800_000_000.0]
    t = Tokens(clock=lambda: clock[0])
    token = t.add("codex")
    assert Tokens().list()[0].last_used is None
    t.verify(token)
    first = Tokens().list()[0].last_used
    assert first
    clock[0] += 30
    t.verify(token)
    assert Tokens().list()[0].last_used == first
    clock[0] += 61
    t.verify(token)
    assert Tokens().list()[0].last_used != first


def test_a_wrong_token_leaves_the_file_alone():
    t = Tokens()
    t.add("codex")
    before = the_file().read_bytes()
    t.verify("sheaf_mcp_" + "B" * 43)
    assert the_file().read_bytes() == before


def test_a_file_that_is_not_a_list_of_tokens_is_set_aside_and_no_token_works():
    token = Tokens().add("codex")
    the_file().write_text('{"not": "a list"}', encoding="utf-8")
    assert Tokens().verify(token) is None
    assert the_file().with_name("tokens.json.corrupt").exists()


def test_a_file_set_aside_leaves_one_diagnostics_row_naming_it_and_where_it_went():
    from sheafmd import diagnostics
    token = Tokens().add("codex")
    the_file().write_text("[{not json", encoding="utf-8")
    assert Tokens().verify(token) is None
    aside = the_file().with_name("tokens.json.corrupt")
    [row] = [r for r in diagnostics.read() if r.get("kind") == "file-set-aside"]
    assert row["source"] == "hub"
    assert row["file"] == str(the_file()) and row["moved_to"] == str(aside)
    assert aside.read_text(encoding="utf-8") == "[{not json"


def test_a_token_file_python_cannot_parse_is_set_aside_with_a_row_like_any_malformed_file():
    from sheafmd import diagnostics
    token = Tokens().add("codex")
    # more digits than Python's integer-string limit (4300) lets json.loads read
    the_file().write_text('[{"name":"x","created":1' + "0" * 4400 + "}]", encoding="utf-8")
    assert Tokens().verify(token) is None
    assert the_file().with_name("tokens.json.corrupt").exists()
    [row] = [r for r in diagnostics.read() if r.get("kind") == "file-set-aside"]
    assert row["file"] == str(the_file())


def test_a_file_that_cannot_be_moved_aside_leaves_a_row_that_says_so(monkeypatch):
    from sheafmd import diagnostics
    from sheafmd.hub import state
    token = Tokens().add("codex")
    the_file().write_text("[{not json", encoding="utf-8")

    def refuse(src, dst):
        raise PermissionError("no")
    monkeypatch.setattr(state.os, "replace", refuse)
    assert Tokens().verify(token) is None
    assert the_file().exists()
    kinds = [r.get("kind") for r in diagnostics.read()]
    assert "file-set-aside" not in kinds
    [row] = [r for r in diagnostics.read() if r.get("kind") == "file-set-aside-failed"]
    assert row["source"] == "hub" and row["file"] == str(the_file())
    assert "PermissionError" in row["error"]


def test_a_file_another_reader_already_moved_aside_leaves_no_failure_row(monkeypatch):
    from sheafmd import diagnostics
    from sheafmd.hub import state
    token = Tokens().add("codex")
    the_file().write_text("[{not json", encoding="utf-8")

    def gone(src, dst):
        raise FileNotFoundError(src)
    monkeypatch.setattr(state.os, "replace", gone)
    assert Tokens().verify(token) is None
    assert [r for r in diagnostics.read() if r.get("kind", "").startswith("file-set-aside")] == []


# ── the right to write pages (9.7) ───────────────────────────────────────────

def test_a_token_writes_pages_only_when_it_was_made_to():
    reader, writer = Tokens().add("codex"), Tokens().add("writer", write=True)
    assert Tokens().verify(reader) == TokenRow("codex", "codex", False)
    assert Tokens().verify(writer) == TokenRow("writer", "writer", True)
    rows = {r["name"]: r for r in json.loads(the_file().read_text(encoding="utf-8"))}
    assert rows["codex"]["write"] is False and rows["writer"]["write"] is True


def test_a_token_made_before_the_right_existed_cannot_write():
    """Its row has no `write`: it keeps the rights it was made with, to read and answer."""
    token = Tokens().add("codex")
    rows = json.loads(the_file().read_text(encoding="utf-8"))
    del rows[0]["write"]
    the_file().write_text(json.dumps(rows), encoding="utf-8")
    assert Tokens().verify(token).write is False


@pytest.mark.parametrize("value", ["true", 1, "yes", None, [True]])
def test_only_a_real_true_gives_the_right(value):
    token = Tokens().add("codex")
    rows = json.loads(the_file().read_text(encoding="utf-8"))
    rows[0]["write"] = value
    the_file().write_text(json.dumps(rows), encoding="utf-8")
    assert Tokens().verify(token).write is False


def test_list_shows_which_tokens_may_write():
    Tokens().add("codex")
    Tokens().add("writer", write=True)
    assert [(r.name, r.write) for r in Tokens().list()] == [("codex", False), ("writer", True)]

# ── the Authorization header ─────────────────────────────────────────────────

@pytest.mark.parametrize("header,want", [
    ("Bearer sheaf_mcp_abc", "sheaf_mcp_abc"),
    ("bearer sheaf_mcp_abc", "sheaf_mcp_abc"),
    ("BEARER   sheaf_mcp_abc ", "sheaf_mcp_abc"),
    ("Basic sheaf_mcp_abc", None),
    ("Bearer", None),
    ("Bearer ", None),
    ("Bearer a b", None),
    ("sheaf_mcp_abc", None),
    (None, None),
    (7, None),
])
def test_the_bearer_token_is_read_from_the_authorization_header(header, want):
    assert auth.bearer(header) == want


# ── what a reply is signed with ──────────────────────────────────────────────

@pytest.mark.parametrize("given,want", [
    ("Claude", "Claude"),
    ("  Claude   Code ", "Claude Code"),
    ("a\nb\tc", "a b c"),
    ("x" * 100, "x" * 60),
    ("", ""),                        # nothing is left: the handler refuses, it does not invent a name
    ("   ", ""),
    (None, ""),
    ("\x00\x07", ""),
    ("a\x00b\x07c", "abc"),
])
def test_a_display_name_from_a_header_is_made_safe_for_a_reply_line(given, want):
    assert auth.clean_display(given) == want


def test_add_hands_back_the_token_with_the_display_name_it_signs_with():
    plain, named = Tokens().add("codex"), Tokens().add("gem", "  Gemini  ")
    assert TOKEN_RE.fullmatch(plain) and plain.display == "codex"
    assert TOKEN_RE.fullmatch(named) and named.display == "Gemini"
    assert {t.name: t.display for t in Tokens().list()} == {"codex": "codex", "gem": "Gemini"}


def test_a_new_token_survives_a_copy_and_a_pickle_as_the_plain_secret():
    import copy
    import pickle
    token = Tokens().add("codex", "Codex")
    assert copy.copy(token) == token and pickle.loads(pickle.dumps(token)) == token


# ── a row `add` could not have written (9.7) ──────────────────────

def _edit_rows(change):
    rows = json.loads(the_file().read_text(encoding="utf-8"))
    change(rows)
    the_file().write_text(json.dumps(rows), encoding="utf-8")


@pytest.mark.parametrize("display", [
    "", "   ", "​", "\x00", 7, None, ["Codex"], {"a": 1},   # blank, zero-width, not a string, absent
    "  Codex  ", "a\nb", "x" * 61, "a\x00b",                      # `add` would have cleaned these
])
def test_a_row_whose_display_add_could_not_have_written_is_refused(display):
    token = Tokens().add("codex", "Codex")
    _edit_rows(lambda rows: rows[0].__setitem__("display", display))
    assert Tokens().verify(token) is None


def test_a_row_with_no_display_is_refused_not_signed_with_its_name():
    token = Tokens().add("codex", "Codex")
    _edit_rows(lambda rows: rows[0].pop("display"))
    assert Tokens().verify(token) is None


@pytest.mark.parametrize("given", ["Codex", "  Claude   Code ", "é" * 70, "x" * 61])
def test_a_row_add_wrote_is_still_accepted_whatever_it_was_given(given):
    token = Tokens().add("codex", given)
    assert Tokens().verify(token).display == auth.clean_display(given)


def _same_hash_twice(name_a, name_b):
    token = Tokens().add("bad", "Bad")
    Tokens().add("codex", "Codex")
    def change(rows):
        rows[1]["sha256"] = rows[0]["sha256"]
        rows[0]["name"], rows[1]["name"] = name_a, name_b
    _edit_rows(change)
    return token


def test_a_hash_that_two_rows_hold_is_refused_and_nothing_is_written():
    token = _same_hash_twice("bad name", "codex")
    before = the_file().read_bytes()
    assert Tokens().verify(token) is None
    assert the_file().read_bytes() == before


def test_a_hash_that_two_good_rows_hold_is_refused_too():
    token = _same_hash_twice("one", "two")
    assert Tokens().verify(token) is None
    assert all(r["last_used"] is None for r in json.loads(the_file().read_text(encoding="utf-8")))


def test_the_stamp_is_refused_for_a_row_that_stopped_being_one_add_could_have_written():
    """verify read the row and found it good; the file changed before the stamp took the lock."""
    token = Tokens().add("codex", "Codex")
    _edit_rows(lambda rows: rows[0].__setitem__("display", " "))
    assert Tokens()._touch(token_hash(token)) is False
    assert json.loads(the_file().read_text(encoding="utf-8"))[0]["last_used"] is None
