"""This repository is public, so no client, person, company or host of ours may stand in a tracked file.

The names are not in the repository, not even as hashes: `tests/public_tree.py` reads them from the
environment (CI sets it from a secret). These tests hold the guard with terms of their own, then run it on
this checkout with the real ones.
"""
import io
import subprocess

import pytest

import public_tree
from public_tree import ALLOW, Hit, scan_text, scan_tree, terms_from

TERMS = ("leakguardcanary", "leak pair")
# Built, not written: this file is scanned too, and only the addresses public_tree names may stand in it.
V6 = "fd7a:115c:" + "a1e0"
HOST = "100." + "88.12.7"


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def scan(repo, allow=None, terms=TERMS):
    """A scratch repository has none of this one's allowances, so they are not looked for in it."""
    return scan_tree(repo, {} if allow is None else allow, terms)


def planted(repo, path, text):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")
    git(repo, "add", path)


def test_a_planted_name_in_a_tracked_file_is_found_with_its_line_and_no_text(repo):
    planted(repo, "docs/note.md", "one\ntwo leakguardcanary three\n")
    assert scan(repo) == [Hit("docs/note.md", 2, "term 1")]


@pytest.mark.parametrize("text", [
    "LEAKGUARDCANARY", "LeakGuardCanary", "leakguardcanary's", "x_leakguardcanary_y", "leakguardcanarys",
    "mac-leakguardcanary.local", "myleakguardcanary", "leakguardcanary.example",
])
def test_a_name_is_found_in_any_case_and_inside_a_longer_word_or_identifier(repo, text):
    planted(repo, "a.txt", text)
    assert [h.line for h in scan(repo)] == [1]


def test_a_name_of_two_words_is_found_however_it_is_joined_or_written_as_one_word(repo):
    planted(repo, "a.txt", "\n".join(["leak-pair", "leak_pair", "leak pair", "leak.pair", "LeakPair", "leakpair", "leak  -  pair"]))
    assert [h.line for h in scan(repo)] == [1, 2, 3, 4, 5, 6, 7]


def test_a_name_of_two_words_split_by_a_line_break_is_found_on_the_line_it_starts(repo):
    planted(repo, "a.md", "text that wraps after leak\npair and goes on\n")
    assert scan(repo) == [Hit("a.md", 1, "term 2")]


def test_a_term_with_an_equals_sign_is_found_as_whole_words_only(repo):
    planted(repo, "a.txt", "tiny\nmytiny\ntinyer\ntiny-mac\nTiny's\n")
    assert [h.line for h in scan(repo, terms=("=tiny",))] == [1, 4, 5]
    planted(repo, "b.txt", "tiny leak\ntiny leaks\n")
    assert [(h.path, h.line) for h in scan(repo, terms=("=tiny leak",))] == [("b.txt", 1)]


def test_two_words_in_the_other_order_are_not_the_name(repo):
    planted(repo, "a.txt", "pair leak\n")
    assert scan(repo) == []


def test_a_name_in_a_path_is_found(repo):
    planted(repo, "tests/leakguardcanary.txt", "nothing in here\n")
    assert [(h.path, h.line) for h in scan(repo)] == [("tests/leakguardcanary.txt", 0)]


def test_an_untracked_file_is_not_read(repo):
    (repo / "scratch.txt").write_text("leakguardcanary", encoding="utf-8")
    assert scan(repo) == []


def test_a_binary_file_does_not_stop_the_scan(repo):
    (repo / "b.bin").write_bytes(b"\xff\xfe\x00leakguardcanary\xff")
    git(repo, "add", "b.bin")
    planted(repo, "a.txt", "clean\n")
    assert [h.path for h in scan(repo)] == ["b.bin"]


def test_a_tailnet_address_is_found_and_a_dotted_version_is_not(repo):
    planted(repo, "a.txt", "host 100.64.1.2 here\nversion 1.100.2.3\n")
    assert [(h.line, h.key) for h in scan(repo)] == [(1, "100.64.1.2")]


def test_a_tailnet_v6_address_is_found_in_full_in_any_case(repo):
    planted(repo, "a.txt", f"{V6}::1\n{V6.upper()}:ab12::/48\nfd7a:115c:a1e1::1\n")
    assert [(h.line, h.key) for h in scan(repo)] == [(1, f"{V6}::1"), (2, f"{V6}:ab12::")]


def test_an_allowed_hit_is_not_reported_and_one_that_no_longer_matches_is(repo):
    planted(repo, "a.txt", "host 100.64.1.2\n")
    allow = {("a.txt", "100.64.1.2"): "documented test value"}
    assert scan(repo, allow) == []
    (repo / "a.txt").write_text("clean\n", encoding="utf-8")
    assert scan(repo, allow) == [Hit("a.txt", 0, "allowed but absent: 100.64.1.2")]


def test_the_allowance_for_a_hit_is_for_that_file_only(repo):
    planted(repo, "b.txt", "host 100.64.1.2\n")
    assert [h.path for h in scan(repo, {("a.txt", "100.64.1.2"): "x"})] == ["b.txt", "a.txt"]


def test_every_allowance_has_a_reason_and_an_address_for_a_key():
    assert ALLOW and all(len(reason) > 20 for reason in ALLOW.values())
    assert all(public_tree.ADDRESS.fullmatch(key) for _, key in ALLOW)


def test_the_guards_own_files_may_hold_the_addresses_they_allow_and_no_other(repo):
    planted(repo, "tests/public_tree.py", 'A = "100.64.0.0"\n')
    planted(repo, "tests/test_public_tree.py", "100.64.1.2\n")
    assert scan(repo, {("x", "100.64.0.0"): "r"}) == [Hit("x", 0, "allowed but absent: 100.64.0.0")]
    planted(repo, "tests/test_public_tree.py", f"{HOST} and 100.64.1.2\nleakguardcanary\n")
    hits = scan(repo, {("x", "100.64.0.0"): "r"})
    assert [(h.path, h.line, h.key) for h in hits if h.line] == [
        ("tests/test_public_tree.py", 1, HOST), ("tests/test_public_tree.py", 2, "term 1")]


def test_terms_are_read_from_a_comma_or_line_separated_list_and_a_term_is_its_words():
    assert terms_from("one, Two-Words\n  three_x ,, = four") == ("one", "two words", "three x", "=four")
    assert terms_from("") == () and terms_from(None) == ()


def test_a_term_with_a_character_the_scan_cannot_read_is_refused_not_cut_short():
    with pytest.raises(ValueError, match="term 2"):
        terms_from("fine, Zo\u00eb")


def test_the_scan_prints_hits_without_the_matched_text(repo, capsys, monkeypatch):
    planted(repo, "a.txt", "leakguardcanary\n")
    monkeypatch.setenv("SHEAF_PUBLIC_TREE_TERMS", "leakguardcanary")
    assert public_tree.main([str(repo)]) == 1
    out = capsys.readouterr().out
    assert "a.txt:1 term 1" in out and "canary" not in out


def test_without_terms_the_scan_refuses_to_call_a_tree_clean(repo, capsys, monkeypatch):
    monkeypatch.delenv("SHEAF_PUBLIC_TREE_TERMS", raising=False)
    assert public_tree.main([str(repo)]) == 2
    assert "SHEAF_PUBLIC_TREE_TERMS" in capsys.readouterr().err


def test_this_checkout_holds_no_address_that_is_not_allowed():
    assert scan_tree(public_tree.ROOT, terms=()) == []


def test_this_checkout_holds_no_name(monkeypatch):
    terms = terms_from(public_tree.os.environ.get("SHEAF_PUBLIC_TREE_TERMS"))
    if not terms:
        if public_tree.os.environ.get("CI"):
            pytest.fail("SHEAF_PUBLIC_TREE_TERMS is not set in CI: the names are a secret of the repository, "
                        "and a run that cannot read them must not pass")
        pytest.skip("SHEAF_PUBLIC_TREE_TERMS is not set; CI sets it from a secret")
    assert scan_tree(public_tree.ROOT, terms=terms) == []


@pytest.mark.parametrize("path, ignored", [
    ("handoff-example-2026-01-01.md", True),
    ("handoff-.md", True),
    ("docs/handoff-example-2026-01-01.md", False),
    ("handoff.md", False),
    ("handoff-example.txt", False),
])
def test_a_session_handoff_note_at_the_root_is_ignored_and_nothing_else_is(repo, path, ignored):
    """Handoff notes name people and work, so a broad `git add` must not pick one up."""
    (repo / ".gitignore").write_text((public_tree.ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=repo)
    assert (result.returncode == 0) is ignored
