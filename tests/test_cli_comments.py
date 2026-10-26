"""`sheaf comments`, `comment`, `reply`, `resolve`, `reopen` (SPEC 13): the commands that
read and change the comments of a file, with no hub.

Run in this process through the `sheaf` fixture (conftest); a few at the end run
`python -m sheafmd` as a real process, so the environment's agent detection and the
stdout/stderr split are exercised end to end. Every test starts with no agent detected
and `SHEAF_NAME=Ada` (conftest).
"""
import json
import os

import pytest
from helpers import brand_words_in, run_module, write

from sheafmd import comments, diagnostics, paths

TEXT = "# T\n\nThe gap is **52%** and it matters.\n\nOther text.\n"
AT = "2026-10-14T10:00"


@pytest.fixture
def doc(work):
    return write(work / "doc.md", TEXT)


def rows():
    return diagnostics.read()


def parsed(path):
    return comments.parse(path.read_text(encoding="utf-8"))


def commented(work, *, marker="sheaf-comment", replies=(), status="open", name="c.md"):
    c = comments.Comment(id="c1", by="Grace", at=AT, status=status, quote="gap", body="Why?",
                         marker=marker, replies=list(replies))
    return write(work / name, f"# T\n\nThe gap{comments.format(c, one_line=False)} is wide.\n")


# ── the whole round trip, as the reference tested it ───────────────────────

def test_comment_reply_resolve_and_list(doc, sheaf):
    r = sheaf("comment", doc, "The gap is 52%", "Source?", "--as", "Grace")
    assert r.code == 0 and r.out == "  + c1 added to doc.md\n" and r.err == ""
    out = sheaf("comments", doc).out
    assert "c1" in out and "Grace" in out and "The gap is 52%" in out and "Source?" in out
    assert "line 3" in out and "[open]" in out
    r = sheaf("reply", doc, "c1", "Re-derived, holds.", "--resolve", "--as", "Claude")
    assert r.code == 0 and r.out == "  + replied to c1 and resolved it\n"
    assert "c1" not in sheaf("comments", doc).out
    data = json.loads(sheaf("comments", doc, "--all", "--json").out)
    [c] = data["comments"]
    assert c["status"] == "resolved" and c["replies"][0]["by"] == "Claude"
    assert c["quote"] == "The gap is 52%" and c["body"] == "Source?" and c["line"] == 3
    assert data["malformed"] == []


def test_the_comment_is_written_after_the_passage_with_the_new_marker(doc, sheaf):
    sheaf("comment", doc, "52%", "Source?", "--as", "Grace")
    text = doc.read_text(encoding="utf-8")
    assert text.startswith("# T\n\nThe gap is **52%**<!-- sheaf-comment id=c1 by=\"Grace\" at=")
    assert text.endswith("--> and it matters.\n\nOther text.\n")
    [c] = comments.parse(text).comments
    assert (c.id, c.by, c.status, c.quote, c.body) == ("c1", "Grace", "open", "52%", "Source?")


def test_the_next_comment_gets_the_next_id(doc, sheaf):
    sheaf("comment", doc, "Other text", "one")
    sheaf("comment", doc, "matters", "two")
    assert sorted(c.id for c in parsed(doc).comments) == ["c1", "c2"]


# ── comment: what it refuses ────────────────────────────────────────────────

def test_a_passage_that_occurs_twice_fails_and_says_why(work, sheaf):
    p = write(work / "doc.md", "Same words.\n\nSame words.\n")
    r = sheaf("comment", p, "Same words", "x")
    assert r.code == 1 and "2 places" in r.err and r.out == ""
    assert p.read_text(encoding="utf-8") == "Same words.\n\nSame words.\n"
    [row] = rows()
    assert (row["source"], row["kind"], row["doc"]) == ("cli", "comment-failed", str(p))
    assert row["error"].startswith("AnchorError") and "2 places" in row["error"]


def test_a_passage_that_does_not_occur_fails_and_writes_nothing(doc, sheaf):
    r = sheaf("comment", doc, "no such words", "x")
    assert r.code == 1 and "does not occur" in r.err
    assert doc.read_text(encoding="utf-8") == TEXT
    assert [r["kind"] for r in rows()] == ["comment-failed"]


def test_a_passage_inside_code_cannot_be_commented(work, sheaf):
    p = write(work / "doc.md", "Text.\n\n```\nsecret code\n```\n")
    r = sheaf("comment", p, "secret code", "x")
    assert r.code == 1 and "does not occur" in r.err


@pytest.mark.parametrize("argv", [["", "text"], ["  ", "text"], ["The gap", ""], ["The gap", " \n"]])
def test_an_empty_passage_or_text_is_a_usage_error_and_writes_nothing(doc, sheaf, argv):
    r = sheaf("comment", doc, *argv)
    assert r.code == 2 and "is empty" in r.err
    assert doc.read_text(encoding="utf-8") == TEXT and rows() == []


def test_a_missing_file_exits_1_names_it_and_is_not_a_failed_write(work, sheaf):
    for argv in (["comment", "nothere.md", "x", "y"], ["reply", "nothere.md", "c1", "y"],
                 ["resolve", "nothere.md", "c1"], ["reopen", "nothere.md", "c1"],
                 ["comments", "nothere.md"]):
        r = sheaf(argv[0], work / argv[1], *argv[2:])
        assert r.code == 1 and "nothere.md" in r.err and "no such file" in r.err, argv
    assert rows() == [] and list(work.iterdir()) == []


def test_a_folder_is_not_a_document(work, sheaf):
    r = sheaf("comments", work)
    assert r.code == 1 and str(work) in r.err


def test_a_document_that_is_not_utf8_exits_1_without_a_traceback(work, sheaf):
    p = work / "bad.md"
    p.write_bytes(b"caf\xe9 \xff\n")
    for argv in (["comments", p], ["comment", p, "caf", "x"], ["reply", p, "c1", "x"],
                 ["resolve", p, "c1"]):
        r = sheaf(*argv)
        assert r.code == 1 and "is not UTF-8 text" in r.err and "Traceback" not in r.err, argv
    assert p.read_bytes() == b"caf\xe9 \xff\n"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_a_folder_that_cannot_be_written_exits_1_and_records_it(work, doc, sheaf):
    work.chmod(0o500)
    try:
        r = sheaf("comment", doc, "Other text", "x")
    finally:
        work.chmod(0o700)
    assert r.code == 1 and "Traceback" not in r.err and "doc.md" in r.err
    assert doc.read_text(encoding="utf-8") == TEXT
    [row] = rows()
    assert row["kind"] == "comment-failed" and row["error"].startswith(("PermissionError", "OSError"))


# ── who signs ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("var, value, who", [
    ("CLAUDE_CODE_SESSION_ID", "s-1", "Claude"), ("CODEX_THREAD_ID", "t-1", "Codex"),
    ("CURSOR_CONVERSATION_ID", "c-1", "Cursor"), ("OPENCODE", "1", "opencode"),
    ("GEMINI_CLI", "1", "Gemini"),
])
def test_a_comment_is_signed_with_the_display_name_of_the_detected_agent(doc, sheaf, monkeypatch, var, value, who):
    monkeypatch.setenv(var, value)
    sheaf("comment", doc, "Other text", "x")
    assert parsed(doc).comments[0].by == who


def test_a_comment_is_signed_with_the_users_name_without_an_agent(doc, sheaf):
    sheaf("comment", doc, "Other text", "x")
    assert parsed(doc).comments[0].by == "Ada"                    # SHEAF_NAME, set by conftest


def test_the_users_name_comes_from_config_toml_without_sheaf_name(doc, sheaf, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    write(doc.parent / "sheaf-home" / "config.toml", 'name = "Barbara"\n')
    monkeypatch.setenv("SHEAF_HOME", str(doc.parent / "sheaf-home"))
    sheaf("comment", doc, "Other text", "x")
    assert parsed(doc).comments[0].by == "Barbara"


def test_as_wins_over_the_detected_agent(doc, sheaf, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "t-1")
    sheaf("comment", doc, "Other text", "x", "--as", "Grace Hopper")
    assert parsed(doc).comments[0].by == "Grace Hopper"


def test_a_name_with_a_newline_is_written_on_one_line_and_parses(doc, sheaf):
    r = sheaf("comment", doc, "Other text", "x", "--as", "Grace\nHopper \t Jr")
    assert r.code == 0
    [c] = parsed(doc).comments
    assert c.by == "Grace Hopper Jr" and parsed(doc).malformed == []


def test_a_name_that_is_blank_is_a_usage_error(doc, sheaf):
    r = sheaf("comment", doc, "Other text", "x", "--as", "  ")
    assert r.code == 2 and "is empty" in r.err and doc.read_text(encoding="utf-8") == TEXT


# ── reply: roles (D20) ──────────────────────────────────────────────────────

def reply_of(path):
    [c] = parsed(path).comments
    [r] = c.replies
    return c, r


def test_an_agents_reply_with_no_role_is_written_as_an_answer(work, sheaf, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    p = commented(work)
    r = sheaf("reply", p, "c1", "Because.")
    assert r.code == 0
    c, rep = reply_of(p)
    assert (rep.by, rep.role, rep.text) == ("Claude", "answer", "Because.")
    assert f"@Claude {rep.at} answer: Because." in p.read_text(encoding="utf-8")


def test_an_agents_reply_with_a_role_keeps_it(work, sheaf, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "t-1")
    p = commented(work)
    sheaf("reply", p, "c1", "Done.", "--role", "action")
    assert reply_of(p)[1].role == "action" and reply_of(p)[1].by == "Codex"


def test_a_persons_reply_has_no_role(work, sheaf):
    p = commented(work)
    sheaf("reply", p, "c1", "Thanks.")
    c, rep = reply_of(p)
    assert (rep.by, rep.role) == ("Ada", None)
    assert f"@Ada {rep.at}: Thanks." in p.read_text(encoding="utf-8")


def test_a_reply_signed_with_as_has_no_role_unless_one_is_given(work, sheaf, monkeypatch):
    """D20 applies when the author COMES FROM a detected agent; --as names the author."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    p = commented(work)
    sheaf("reply", p, "c1", "One.", "--as", "Claude")
    sheaf("reply", p, "c1", "Two.", "--as", "Claude", "--role", "action")
    c = parsed(p).comments[0]
    assert [(r.by, r.role) for r in c.replies] == [("Claude", None), ("Claude", "action")]


def test_a_person_may_give_a_role(work, sheaf):
    p = commented(work)
    sheaf("reply", p, "c1", "Handled.", "--role", "answer")
    assert reply_of(p)[1].role == "answer"


def test_an_unknown_role_is_a_usage_error_and_writes_nothing(work, sheaf):
    p = commented(work)
    before = p.read_bytes()
    r = sheaf("reply", p, "c1", "x", "--role", "tell")
    assert r.code == 2 and "--role" in r.err and p.read_bytes() == before


def test_the_effective_roles_the_listing_shows(work, sheaf, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    p = commented(work)
    sheaf("reply", p, "c1", "Because.")
    sheaf("reply", p, "c1", "Fixed.", "--role", "action")
    sheaf("reply", p, "c1", "Thanks.", "--as", "Grace")
    data = json.loads(sheaf("comments", p, "--json").out)
    assert [(r["display"], r["role"]) for r in data["comments"][0]["replies"]] == [
        ("Claude", "answer"), ("Claude", "action"), ("Grace", None)]
    out = sheaf("comments", p).out
    assert " answer: Because." in out and " action: Fixed." in out
    assert "Grace" in out and "Thanks." in out


def test_a_legacy_action_reply_is_listed_under_its_display_name_and_role(work, sheaf):
    p = commented(work, marker="rd-comment", replies=[comments.Reply("Claude (action)", AT, "Did it."),
                                                       comments.Reply("Claude", AT, "Because.")])
    out = sheaf("comments", p).out
    assert f"@Claude {AT} action: Did it." in out and f"@Claude {AT} answer: Because." in out
    assert "(action)" not in out


# ── reply: what it keeps and refuses ────────────────────────────────────────

def test_a_reply_keeps_the_marker_and_the_old_replies_byte_for_byte(work, sheaf):
    legacy = [comments.Reply("Claude (action)", AT, "Did it.")]
    p = commented(work, marker="rd-comment", replies=legacy)
    old = p.read_text(encoding="utf-8")
    old_reply_line = '@"Claude (action)" ' + AT + ": Did it."
    assert old_reply_line in old
    r = sheaf("reply", p, "c1", "Thanks.", "--as", "Grace")
    assert r.code == 0
    new = p.read_text(encoding="utf-8")
    assert "<!-- rd-comment id=c1" in new and old_reply_line in new
    c = parsed(p).comments[0]
    assert c.marker == "rd-comment" and [r.by for r in c.replies] == ["Claude (action)", "Grace"]
    assert [c.effective_role(r) for r in c.replies] == ["action", None]


def test_a_multi_line_reply_comes_back_whole(work, sheaf):
    p = commented(work)
    sheaf("reply", p, "c1", "First.\n\n- not a list\n--> and an arrow", "--as", "Grace")
    assert reply_of(p)[1].text == "First.\n\n- not a list\n--> and an arrow"


def test_a_reply_to_an_unknown_comment_fails_and_writes_nothing(work, sheaf):
    p = commented(work)
    before = p.read_bytes()
    r = sheaf("reply", p, "c9", "x")
    assert r.code == 1 and "no comment c9" in r.err and p.read_bytes() == before
    [row] = rows()
    assert (row["source"], row["kind"], row["doc"]) == ("cli", "reply-failed", str(p))


def test_an_empty_reply_is_a_usage_error(work, sheaf):
    p = commented(work)
    before = p.read_bytes()
    r = sheaf("reply", p, "c1", " ")
    assert r.code == 2 and p.read_bytes() == before and rows() == []


def test_reply_resolve_marks_the_comment_resolved_and_without_it_does_not(work, sheaf):
    p = commented(work)
    sheaf("reply", p, "c1", "One.")
    assert parsed(p).comments[0].status == "open"
    r = sheaf("reply", p, "c1", "Two.", "--resolve")
    assert r.out == "  + replied to c1 and resolved it\n" and parsed(p).comments[0].status == "resolved"


# ── resolve and reopen ──────────────────────────────────────────────────────

def test_resolve_and_reopen_flip_the_status(work, sheaf):
    p = commented(work)
    r = sheaf("resolve", p, "c1")
    assert (r.code, r.out) == (0, "  + c1 resolved\n") and parsed(p).comments[0].status == "resolved"
    r = sheaf("reopen", p, "c1")
    assert (r.code, r.out) == (0, "  + c1 reopened\n") and parsed(p).comments[0].status == "open"


def test_resolving_a_resolved_comment_says_so_and_leaves_the_file_alone(work, sheaf):
    p = commented(work, status="resolved")
    before, stamp = p.read_bytes(), p.stat().st_mtime_ns
    r = sheaf("resolve", p, "c1")
    assert (r.code, r.out) == (0, "  c1 was already resolved\n")
    assert p.read_bytes() == before and p.stat().st_mtime_ns == stamp
    q = commented(work, name="open.md")
    assert sheaf("reopen", q, "c1").out == "  c1 was already open\n"


def test_resolve_and_reopen_of_an_unknown_comment_fail_and_are_recorded(work, sheaf):
    p = commented(work)
    for verb in ("resolve", "reopen"):
        r = sheaf(verb, p, "c9")
        assert r.code == 1 and "no comment c9" in r.err
    assert [r["kind"] for r in rows()] == ["resolve-failed", "reopen-failed"]


def test_resolve_changes_only_the_status(work, sheaf):
    p = commented(work, replies=[comments.Reply("Grace", AT, "Hi.")])
    before = p.read_text(encoding="utf-8")
    sheaf("resolve", p, "c1")
    assert p.read_text(encoding="utf-8") == before.replace("status=open", "status=resolved")


# ── comments: the listing ───────────────────────────────────────────────────

def test_the_listing_hides_resolved_comments_until_all(work, sheaf):
    p = commented(work, status="resolved")
    assert sheaf("comments", p).out == "  no open comments\n"
    assert "c1" in sheaf("comments", p, "--all").out
    assert sheaf("comments", write(work / "plain.md", "Text.\n"), "--all").out == "  no comments\n"


def test_orphans_and_malformed_are_listed(work, sheaf):
    orphan = comments.format(comments.Comment(id="c1", by="T", at=AT, quote="gone", body="was here",
                                              orphan=True), False)
    p = write(work / "doc.md", f"Text.\n\n{orphan}\n\nMore<!-- rd-comment status=open -->\n")
    out = sheaf("comments", p).out
    assert "orphan" in out and "was here" in out
    assert "malformed" in out and "missing id" in out
    data = json.loads(sheaf("comments", p, "--json").out)
    assert data["comments"][0]["orphan"] is True
    assert data["malformed"] == [{"line": 7, "reason": "missing id"}]


def test_a_stray_closing_arrow_is_listed_as_malformed(work, sheaf):
    p = write(work / "doc.md", "Text.\n\nbody of a comment\n-->\n")
    out = sheaf("comments", p).out
    assert "malformed  line 4" in out and "closing -->" in out


def test_the_listing_is_read_only(work, sheaf):
    p = commented(work)
    before, stamp = p.read_bytes(), p.stat().st_mtime_ns
    sheaf("comments", p)
    sheaf("comments", p, "--all", "--json")
    assert p.read_bytes() == before and p.stat().st_mtime_ns == stamp
    assert sorted(x.name for x in work.iterdir()) == ["c.md"]


def test_json_keeps_non_ascii_text_readable(work, sheaf):
    p = commented(work)
    sheaf("reply", p, "c1", "Perché? — è così", "--as", "Zoë")
    out = sheaf("comments", p, "--json").out
    assert "Perché? — è così" in out and "Zoë" in out
    assert json.loads(out)["comments"][0]["replies"][0]["text"] == "Perché? — è così"


def test_a_multi_line_thread_is_indented_in_the_listing(work, sheaf):
    p = commented(work)
    sheaf("reply", p, "c1", "Line one\nline two", "--as", "Grace")
    out = sheaf("comments", p).out
    assert "    @Grace " in out and ": Line one\n      line two\n" in out


# ── nothing says the brand, and the help names every command ────────────────

COMMAND_LINES = ["comments FILE [--all] [--json]", "comment FILE PASSAGE TEXT [--as NAME]",
                 "reply FILE ID TEXT [--resolve] [--role answer|action] [--as NAME]",
                 "resolve FILE ID", "reopen FILE ID", "diag [--since DAYS] [--json]",
                 "diag note TEXT [FILE]", "version"]


@pytest.mark.parametrize("word", ["--help", "help"])
def test_help_lists_every_command_with_its_usage(sheaf, word):
    r = sheaf(word)
    assert r.code == 0
    for line in COMMAND_LINES:
        assert f"  sheaf {line}\n" in r.out, line


def test_no_arguments_prints_the_commands_too(sheaf):
    r = sheaf()
    assert r.code == 2 and all(f"sheaf {line}" in r.err for line in COMMAND_LINES)


@pytest.mark.parametrize("name", ["comments", "comment", "reply", "resolve", "reopen"])
def test_each_command_has_help_and_exits_0(name, sheaf, tmp_path):
    r = sheaf(name, "--help")
    assert r.code == 0 and f"usage: sheaf {name}" in r.out and r.err == ""
    assert brand_words_in(r.out, tmp_path) == []


@pytest.mark.parametrize("argv", [["comments"], ["comment", "f.md"], ["comment", "f.md", "p"],
                                  ["reply", "f.md", "c1"], ["resolve", "f.md"], ["reopen"],
                                  ["comments", "f.md", "--bogus"], ["reply", "f.md", "c1", "t", "--role"]])
def test_missing_arguments_are_a_usage_error(sheaf, work, argv):
    r = sheaf(*argv)
    assert r.code == 2 and "usage: sheaf" in r.err and list(work.iterdir()) == []


def test_every_output_of_a_comment_session_is_free_of_the_brand(work, doc, sheaf, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    seen = []
    for argv in (["comment", doc, "52%", "Source?"], ["reply", doc, "c1", "ok", "--resolve"],
                 ["comments", doc, "--all"], ["comments", doc, "--all", "--json"],
                 ["reply", doc, "c9", "x"], ["comment", doc, "nothing like it", "x"],
                 ["resolve", doc, "c1"], ["reopen", doc, "c1"], ["comments", work / "no.md"]):
        r = sheaf(*argv)
        seen.append(r.out + r.err)
    assert all(s.strip() for s in seen)
    assert brand_words_in("\n".join(seen), tmp_path) == []


# ── as a real process ───────────────────────────────────────────────────────

def test_a_real_process_signs_with_the_detected_agent_and_writes_an_answer(work, doc):
    r = run_module("comment", doc.name, "Other text", "Check this.", cwd=work,
                   env={"CODEX_THREAD_ID": "t-9"})
    assert r.returncode == 0 and r.stdout == "  + c1 added to doc.md\n" and r.stderr == ""
    r = run_module("reply", doc.name, "c1", "Checked.", cwd=work, env={"CODEX_THREAD_ID": "t-9"})
    assert r.returncode == 0
    c = parsed(doc).comments[0]
    assert (c.by, c.replies[0].by, c.replies[0].role) == ("Codex", "Codex", "answer")


def test_a_real_process_sends_a_failure_to_stderr_with_exit_1(work, doc):
    r = run_module("reply", doc.name, "c9", "x", cwd=work)
    assert r.returncode == 1 and r.stdout == "" and "no comment c9" in r.stderr
    assert "Traceback" not in r.stderr
    r = run_module("comments", "--bogus", cwd=work)
    assert r.returncode == 2 and r.stdout == ""


# ── what the review found ───────────────────────────────────────────────────

def test_a_broken_config_toml_stops_the_command_with_a_message_not_a_traceback(doc, sheaf, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    write(paths.config_file(), "port = \n")
    for argv in (["comment", doc, "Other text", "x"], ["reply", doc, "c1", "x"]):
        r = sheaf(*argv)
        assert r.code == 1 and "config.toml" in r.err and "Traceback" not in r.err, argv
    assert doc.read_text(encoding="utf-8") == TEXT


def test_a_broken_config_toml_does_not_stop_a_command_that_never_needs_the_name(doc, sheaf, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    write(paths.config_file(), "port = \n")
    assert sheaf("comment", doc, "Other text", "x", "--as", "Grace").code == 0
    assert sheaf("comments", doc).code == 0 and sheaf("resolve", doc, "c1").code == 0


def test_a_blank_name_in_config_toml_is_not_a_name(doc, sheaf, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    write(paths.config_file(), 'name = "   "\n')
    sheaf("comment", doc, "Other text", "x")
    assert parsed(doc).comments[0].by.strip() != ""


def test_a_failed_write_records_the_document_as_an_absolute_path(work, doc, sheaf, monkeypatch):
    monkeypatch.chdir(work)
    sheaf("reply", "doc.md", "c9", "x")
    sheaf("resolve", "./doc.md", "c9")
    assert [r["doc"] for r in rows()] == [str(doc)] * 2


def test_a_name_that_clean_display_changes_is_signed_cleaned(doc, sheaf):
    r = sheaf("comment", doc, "Other text", "x", "--as", "Gra\u200bce")
    assert r.code == 0
    assert parsed(doc).comments[0].by == "Grace"


def test_a_reply_name_that_clean_display_changes_is_signed_cleaned(doc, sheaf):
    sheaf("comment", doc, "Other text", "x", "--as", "Grace")
    r = sheaf("reply", doc, "c1", "Done.", "--as", "Cla\u200bude")
    assert r.code == 0
    _, r2 = reply_of(doc)
    assert r2.by == "Claude"


def test_a_name_of_unprintable_characters_only_is_not_a_name(doc, sheaf, monkeypatch, tmp_path):
    """It falls through to the next source (SPEC 4.3), here the login name."""
    empty_git = tmp_path / "git-global"
    empty_git.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_git))
    monkeypatch.chdir(tmp_path)         # not in a checkout whose own config names someone
    monkeypatch.setenv("USER", "login")
    monkeypatch.setenv("SHEAF_NAME", "​\x07")
    sheaf("comment", doc, "Other text", "x")
    assert parsed(doc).comments[0].by == "login"
