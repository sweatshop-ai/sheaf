"""`sheaf code issue --member --doc --out` (SPEC 9.13): the box's bootstrap of a sign-in code, with the hub key on the
loopback port. The code goes to a new 0600 file as the header line `curl -H @<file>` sends, and never to the
terminal. The hub is the handler in memory, behind a client that holds the key."""
import os
import re
import stat

from test_hub_code import fetch
from test_hub_work import ADDRESS, BEA, HANS, box, team  # noqa: F401

from sheafmd.hub import client as hubclient


class Key:
    """Stands in for `hubclient.client()`: each call goes to the handler with the key header."""

    def __init__(self, browser):
        self.browser = browser

    def call(self, method, path, body=None):
        got = self.browser.request(method, path, body=body, key=True, cookie=False)
        return got.status, got.json()


def run(sheaf, monkeypatch, browser, *args):
    monkeypatch.setattr(hubclient, "client", lambda: Key(browser))
    return sheaf("code", "issue", *args)


def test_the_code_goes_to_a_new_0600_file_as_a_header_line_and_never_to_the_terminal(
        team, box, browser, sheaf, monkeypatch, tmp_path):
    out = tmp_path / "code"
    r = run(sheaf, monkeypatch, browser, "--member", HANS, "--doc", ADDRESS, "--out", out)
    assert r.code == 0, r.err
    line = out.read_text()
    m = re.fullmatch(r"Authorization: Bearer (sheaf_code_[A-Za-z0-9_-]{43})\n", line)
    assert m
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    assert "sheaf_code_" not in r.out + r.err
    assert re.search(r"\b[0-9a-f]{8}\b", r.out) and re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", r.out)
    assert fetch(team, m.group(1)).status == 200


def test_a_file_that_is_there_already_is_never_written_over_and_no_code_is_made(
        team, box, browser, sheaf, monkeypatch, tmp_path):
    out = tmp_path / "code"
    out.write_text("keep me")
    r = run(sheaf, monkeypatch, browser, "--member", HANS, "--doc", ADDRESS, "--out", out)
    assert r.code == 1 and "already" in r.err
    assert out.read_text() == "keep me"
    from helpers import hub_rows
    assert hub_rows("code-issued") == []


def test_a_link_is_never_followed(team, box, browser, sheaf, monkeypatch, tmp_path):
    target = tmp_path / "elsewhere"
    (tmp_path / "code").symlink_to(target)
    r = run(sheaf, monkeypatch, browser, "--member", HANS, "--doc", ADDRESS, "--out", tmp_path / "code")
    assert r.code == 1
    assert not target.exists()


def test_a_refusal_leaves_no_file_and_says_why(team, box, browser, sheaf, monkeypatch, tmp_path):
    out = tmp_path / "code"
    r = run(sheaf, monkeypatch, browser, "--member", BEA, "--doc", ADDRESS, "--out", out)
    assert r.code == 1 and "404" in r.err
    assert not out.exists()
