"""Repo pages and repo clones (SPEC 13, 14): `sheaf FILE.md` on a page inside a git repo sends a render report, never
text; the tiroir clones the repo the first time (blobless, sparse), widens the sparse set for a new folder, keeps the
owner of each page, and makes no clone of a member's private root. Everything runs against local bare repos and a fake
App behind `Repos`'s one seam, the token provider: no real token, no real GitHub."""
import base64
import dataclasses
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from helpers import BEA, CAL, FRONT, door, rpc
from helpers import call as door_call
from test_send import keyring, local, no_real_keyring, run, tiroir  # noqa: F401  (fixtures and helpers)
from test_hub_commits import box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents, declared  # noqa: F401  (fixtures and helpers)

from sheafmd import paths, send
from sheafmd.hub import proxy as proxy_mod
from sheafmd.hub import repos as repos_mod
from sheafmd.hub.repos import Repos

REPO = "acme-org/site"
INSTALL = "https://github.com/apps/the-app/installations/new"
SESSION = "6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11"


class FakeApp:
    """The tiroir's GitHub App: a token for each repo it is installed on, none for the others."""

    def __init__(self, installed=(REPO,)):
        self.installed, self.asked = set(installed), []

    def token(self, repo):
        self.asked.append(repo)
        return "ghs_faketoken" if repo in self.installed else None

    def install_url(self, repo):
        return INSTALL


def sh(at, *args):
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def origin(tmp_path):
    """The repo on 'GitHub': a bare repo that allows a blobless clone, with pages in two folders and a big file."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    sh(bare, "config", "uploadpack.allowFilter", "true")
    sh(bare, "config", "uploadpack.allowAnySHA1InWant", "true")
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
    sh(seed, "config", "user.name", "Dee Dev")
    sh(seed, "config", "user.email", "dee@example.com")
    for rel, text in {"docs/plan.md": "# Plan\n\nA plan.\n", "notes/idea.md": "# Idea\n\nAn idea.\n",
                      "src/big.bin": "x" * 5000, "README.md": "# Site\n"}.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text, encoding="utf-8")
    sh(seed, "add", "-A")
    sh(seed, "commit", "-q", "-m", "first")
    sh(seed, "push", "-q", "origin", "HEAD:main")
    return bare


@pytest.fixture
def app():
    return FakeApp()


@pytest.fixture
def hub_repos(agents, origin, app, tmp_path):  # noqa: F811
    """The tiroir's clone store, wired to Bea's and Cal's hub with the fake App."""
    agents.hub.repos = Repos(tmp_path / "clones", app, remote_url=lambda repo: str(origin))
    agents.hub.repos.FETCH_EVERY = 0.0              # the rate limit has its own test
    agents.app, agents.origin = app, origin
    return agents


def laptop_clone(tmp_path, origin, name="laptop"):
    path = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(origin), str(path)], check=True, capture_output=True)
    sh(path, "config", "user.name", "Bea")
    sh(path, "config", "user.email", "bea@example.com")
    return path


def clones(hub_repos) -> Path:
    return hub_repos.hub.repos.base / "clones"


def report_once(hub_repos, who="bea-claude", path="docs/plan.md", commit=None, repo=REPO, **declares):
    """(is it an error, the answer) of one render report, as the door gave it; `declares` is what the caller says in its
    headers."""
    commit = commit or sh(hub_repos.origin, "rev-parse", "main")
    res = door(hub_repos.door, rpc("tools/call", {"name": "render_report", "arguments": {
        "repo": repo, "path": path, "commit": commit}}), token=hub_repos.tokens[who], as_name=None,
        headers=declared(**declares))
    assert res.status == 200, res.text
    out = res.json()["result"]
    text = out["content"][0]["text"]
    return out["isError"], (text if out["isError"] else json.loads(text))


def report(hub_repos, **kw):
    """The answer of a render report once the tiroir has done its work: the first report of a repo is answered
    `cloning` and the clone is made behind it, so this waits for that and asks again."""
    bad, got = report_once(hub_repos, **kw)
    if not bad and (got["clone"] == "cloning" or got.get("commit_known") is False):
        assert hub_repos.hub.repos.settle(), "the tiroir's thread did not finish"
        bad, got = report_once(hub_repos, **kw)
    elif hub_repos.hub.repos is not None:
        assert hub_repos.hub.repos.settle()
    return bad, got


def the_clone(hub_repos) -> Path:
    found = sorted(p for p in clones(hub_repos).glob("*/*") if (p / ".git").exists())
    assert len(found) == 1, found
    return found[0]


# ── the first report clones, blobless and sparse ─────────────────────────────

def test_the_first_report_for_a_repo_clones_it_blobless_and_sparse_with_the_pages_folder(hub_repos):
    bad, got = report(hub_repos)
    assert not bad, got
    assert got["clone"] == "ok" and got["repo"] == REPO
    clone = the_clone(hub_repos)
    assert sh(clone, "config", "remote.origin.partialclonefilter") == "blob:none"
    assert sh(clone, "config", "core.sparseCheckout") == "true"
    assert (clone / "docs" / "plan.md").read_text(encoding="utf-8") == "# Plan\n\nA plan.\n"
    assert not (clone / "notes").exists() and not (clone / "src").exists()


def test_a_page_from_a_new_folder_widens_the_sparse_set_and_a_second_from_the_same_folder_changes_nothing(hub_repos):
    report(hub_repos)
    clone = the_clone(hub_repos)
    bad, got = report(hub_repos, path="notes/idea.md")
    assert not bad, got
    assert got["clone"] == "ok"
    assert (clone / "notes" / "idea.md").is_file() and not (clone / "src").exists()
    assert sh(clone, "sparse-checkout", "list").split() == ["docs", "notes"]
    report(hub_repos, path="notes/idea.md")
    assert sh(clone, "sparse-checkout", "list").split() == ["docs", "notes"]


def test_there_is_one_clone_per_repo_whoever_reports(hub_repos):
    report(hub_repos, who="bea-claude")
    report(hub_repos, who="cal-claude", path="notes/idea.md")
    the_clone(hub_repos)                    # exactly one


def test_a_commit_pushed_after_the_clone_is_fetched_when_a_report_names_it(hub_repos, tmp_path, origin):
    report(hub_repos)
    pusher = laptop_clone(tmp_path, origin, "pusher")
    (pusher / "docs" / "plan.md").write_text("# Plan\n\nChanged.\n", encoding="utf-8")
    sh(pusher, "commit", "-qam", "change")
    sh(pusher, "push", "-q", "origin", "HEAD:main")
    new = sh(pusher, "rev-parse", "HEAD")
    bad, got = report(hub_repos, commit=new)
    assert not bad, got
    assert got["commit_known"] is True


def test_a_commit_the_remote_does_not_hold_is_reported_unknown_and_nothing_else_changes(hub_repos):
    report(hub_repos)
    bad, got = report(hub_repos, commit="a" * 40)
    assert not bad, got
    assert got["commit_known"] is False


# ── the token ────────────────────────────────────────────────────────────────

def test_the_token_reaches_git_in_the_environment_never_in_an_argument_a_file_or_an_answer(hub_repos, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(argv, *a, **k):
        seen.append((list(argv), dict(k.get("env") or {})))
        return real(argv, *a, **k)

    monkeypatch.setattr(repos_mod.subprocess, "run", spy)
    bad, got = report(hub_repos)
    assert not bad
    assert seen and all("ghs_faketoken" not in " ".join(argv) for argv, _ in seen)
    header = "Authorization: Basic " + base64.b64encode(b"x-access-token:ghs_faketoken").decode()
    assert any(header in env.values() for _, env in seen)
    assert "ghs_faketoken" not in json.dumps(got)
    for f in clones(hub_repos).rglob("*"):
        if f.is_file() and ".git/objects" not in str(f):
            assert b"ghs_faketoken" not in f.read_bytes(), f


# ── the owner of a page ──────────────────────────────────────────────────────

def test_two_members_pages_in_one_repo_stay_apart_by_the_owner_record(hub_repos):
    report(hub_repos, who="bea-claude", path="docs/plan.md")
    report(hub_repos, who="cal-claude", path="notes/idea.md")
    repos = hub_repos.hub.repos
    assert repos.owner_of(REPO, "docs/plan.md") == "bea"
    assert repos.owner_of(REPO, "notes/idea.md") == "cal"


def test_the_first_report_keeps_the_page_a_later_report_by_another_member_does_not_take_it(hub_repos):
    report(hub_repos, who="bea-claude")
    bad, got = report(hub_repos, who="cal-claude")
    assert not bad, got
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "bea"


def test_front_matter_owner_wins_over_the_record(hub_repos, tmp_path, origin):
    pusher = laptop_clone(tmp_path, origin, "pusher")
    (pusher / "docs" / "plan.md").write_text("---\nowner: cal\n---\n# Plan\n", encoding="utf-8")
    sh(pusher, "commit", "-qam", "owner")
    sh(pusher, "push", "-q", "origin", "HEAD:main")
    report(hub_repos, who="bea-claude")
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "cal"


def test_the_owner_record_survives_a_new_hub_and_is_written_nowhere_in_the_repo(hub_repos, tmp_path, origin, app):
    report(hub_repos)
    again = Repos(tmp_path / "clones", app, remote_url=lambda repo: str(origin))
    assert again.owner_of(REPO, "docs/plan.md") == "bea"
    assert sh(the_clone(hub_repos), "status", "--porcelain") == ""


# ── a member's private root gets no clone ────────────────────────────────────

def private_root_of(hub_repos, who_id, tmp_path, origin):
    own = laptop_clone(tmp_path, origin, "private-root")
    proxy = hub_repos.hub.proxy
    members = dict(proxy.members)
    members[who_id] = dataclasses.replace(members[who_id], private_root=str(own))
    hub_repos.hub.proxy = dataclasses.replace(proxy, members=members)
    return own


def test_a_repo_that_is_the_members_private_root_gets_no_clone_and_says_so(hub_repos, tmp_path, origin):
    private_root_of(hub_repos, BEA, tmp_path, origin)
    bad, got = report(hub_repos, who="bea-claude")
    assert not bad, got
    assert got["clone"] == "private-root"
    assert not list(clones(hub_repos).glob("*/*")) and hub_repos.app.asked == []


def test_a_repo_that_is_another_members_private_root_is_not_cloned_and_the_answer_names_no_one(
        hub_repos, tmp_path, origin):
    private_root_of(hub_repos, BEA, tmp_path, origin)
    bad, got = report(hub_repos, who="cal-claude")
    assert not bad, got
    assert got == {"repo": REPO, "path": "docs/plan.md", "clone": "not-cloned", "commit_known": None}
    assert not list(clones(hub_repos).glob("*/*")) and not (hub_repos.hub.repos.base / "scratch").exists()
    assert hub_repos.app.asked == []
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") is None
    assert "private" not in json.dumps(got) and "bea" not in json.dumps(got)


def test_a_private_root_report_records_no_owner(hub_repos, tmp_path, origin):
    private_root_of(hub_repos, BEA, tmp_path, origin)
    report(hub_repos)
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") is None


# ── the App cannot reach the repo ────────────────────────────────────────────

def test_a_repo_the_app_is_not_installed_on_answers_with_the_link_and_makes_no_clone(hub_repos):
    hub_repos.app.installed.clear()
    bad, got = report(hub_repos)
    assert not bad, got
    assert got["clone"] == "no-app" and got["install"] == INSTALL
    assert not list(clones(hub_repos).glob("*/*"))
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") is None


def test_a_tiroir_with_no_clone_store_says_it_makes_no_repo_clones(agents):
    bad, got = door_call(agents.door, "render_report", token=agents.tokens["bea-claude"], repo=REPO,
                         path="docs/plan.md", commit="a" * 40)
    assert not bad and got["clone"] == "none"


@pytest.mark.parametrize("repo,path,commit", [
    ("../x/y", "docs/plan.md", "a" * 40), ("a/b/c", "docs/plan.md", "a" * 40), ("a", "docs/plan.md", "a" * 40),
    (REPO, "../plan.md", "a" * 40), (REPO, "/etc/passwd.md", "a" * 40), (REPO, "docs/plan.txt", "a" * 40),
    (REPO, "docs/plan.md", "--upload-pack=x"), (REPO, "docs/plan.md", "zz")])
def test_a_report_with_a_malformed_name_is_refused_and_runs_no_git(hub_repos, repo, path, commit):
    bad, got = door_call(hub_repos.door, "render_report", token=hub_repos.tokens["bea-claude"], repo=repo, path=path,
                         commit=commit)
    assert bad, got
    assert not list(clones(hub_repos).glob("*")) and hub_repos.app.asked == []


# ── what a row says about its writer ─────────────────────────────────────────

def test_a_row_shows_the_session_of_the_report(hub_repos):
    report(hub_repos, session=SESSION, host="bea-laptop")
    got = hub_repos.hub.repos.attribution(REPO, "docs/plan.md")
    assert got["session"] == SESSION and got["host"] == "bea-laptop"


def test_without_a_report_session_the_commit_trailers_name_it(hub_repos, tmp_path, origin):
    pusher = laptop_clone(tmp_path, origin, "pusher")
    (pusher / "docs" / "plan.md").write_text("# Plan\n\nTrailed.\n", encoding="utf-8")
    sh(pusher, "commit", "-qam", f"change\n\nSheaf-Session: {SESSION}\nSheaf-Host: bea-laptop")
    sh(pusher, "push", "-q", "origin", "HEAD:main")
    report(hub_repos)
    got = hub_repos.hub.repos.attribution(REPO, "docs/plan.md")
    assert got["session"] == SESSION and got["host"] == "bea-laptop"


def test_without_either_a_row_says_git_and_the_author(hub_repos):
    report(hub_repos)
    got = hub_repos.hub.repos.attribution(REPO, "docs/plan.md")
    assert got["session"] is None and got["label"] == "git · Dee Dev"


# ── the CLI: the render report ───────────────────────────────────────────────

@pytest.fixture
def laptop(tmp_path, origin):
    """Bea's laptop: a clone of the origin, the page committed and pushed, GitHub the remote's name."""
    path = laptop_clone(tmp_path, origin)
    sh(path, "remote", "set-url", "origin", f"https://github.com/{REPO}.git")
    sh(path, "config", f"url.{origin}.insteadOf", f"https://github.com/{REPO}.git")
    return path


def seen_calls(tiroir):
    return [(m or {}).get("params", {}).get("name") for _, _, m in tiroir.seen if m]


def test_sheaf_on_a_repo_page_sends_a_report_and_never_its_text(tiroir, hub_repos, laptop, local, capsys):
    page = laptop / "docs" / "plan.md"
    page.write_text("# Plan\n\nEdited, committed, pushed.\n", encoding="utf-8")
    sh(laptop, "commit", "-qam", "edit")
    sh(laptop, "push", "-q", "origin", "HEAD:main")
    report(hub_repos, commit=sh(laptop, "rev-parse", "HEAD"))       # the tiroir has cloned the repo and fetched the commit
    code, out, err = run(capsys, page)
    assert code == 0, err
    assert local == []
    assert "render_report" in seen_calls(tiroir)
    sent = [m for _, _, m in tiroir.seen if m and m.get("params", {}).get("name") == "render_report"][0]
    arguments = sent["params"]["arguments"]
    assert arguments == {"repo": REPO, "path": "docs/plan.md", "commit": sh(laptop, "rev-parse", "HEAD"),
                         **{k: v for k, v in arguments.items() if k in ("session", "host", "link")}}
    assert "Edited, committed, pushed" not in json.dumps(tiroir.seen)
    assert "create" not in seen_calls(tiroir) and "update" not in seen_calls(tiroir)
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "bea"
    assert "docs/plan.md" in out


def test_an_unpushed_commit_prints_the_warning_and_uploads_nothing(tiroir, hub_repos, laptop, local, capsys):
    page = laptop / "docs" / "plan.md"
    page.write_text("# Plan\n\nLocal only.\n", encoding="utf-8")
    sh(laptop, "commit", "-qam", "not pushed")
    code, out, err = run(capsys, page)
    assert code == 0, err
    assert "not on the remote" in err and "git push" in err
    assert tiroir.seen == [] and local == [str(page)]
    assert not list(clones(hub_repos).glob("*/*"))


def test_an_uncommitted_edit_is_said_and_the_report_names_the_committed_text(tiroir, hub_repos, laptop, local, capsys):
    page = laptop / "docs" / "plan.md"
    page.write_text("# Plan\n\nNot committed.\n", encoding="utf-8")
    code, out, err = run(capsys, page)
    assert code == 0, err
    assert "uncommitted" in err
    assert "Not committed" not in json.dumps(tiroir.seen)


def test_a_repo_with_no_remote_renders_on_the_laptop_hub_with_a_warning(tiroir, tmp_path, local, capsys):
    repo = tmp_path / "bare-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    page = repo / "plan.md"
    page.write_text("# Plan\n", encoding="utf-8")
    code, out, err = run(capsys, page)
    assert code == 0 and local == [str(page)] and tiroir.seen == []
    assert "no remote" in err


def test_a_repo_the_app_cannot_reach_falls_back_to_the_laptop_hub_with_the_install_link(tiroir, hub_repos, laptop,
                                                                                    local, capsys):
    hub_repos.app.installed.clear()
    page = laptop / "docs" / "plan.md"
    code, out, err = run(capsys, page)
    assert code == 0, err
    assert local == [str(page)]
    assert INSTALL in err and REPO in err
    assert not list(clones(hub_repos).glob("*/*"))


def test_a_report_to_a_tiroir_that_cannot_be_reached_is_dropped_not_queued_and_the_page_renders_here(
        tiroir, laptop, local, monkeypatch, capsys):
    def down(url, token, message, headers):
        raise send.Unreachable("cannot reach chat.example.com: timed out. Nothing was sent.")
    monkeypatch.setattr(send, "post", down)
    page = laptop / "docs" / "plan.md"
    code, out, err = run(capsys, page)
    assert code == 0 and local == [str(page)]
    assert "dropped" in err
    assert not (paths.state_dir() / "sends.json").exists()


def test_a_revoked_token_on_a_repo_page_fails_loudly_and_renders_nothing(tiroir, laptop, local, keyring, capsys):
    keyring.set("sheaf", FRONT, "sheaf_mcp_" + "A" * 43)
    code, out, err = run(capsys, laptop / "docs" / "plan.md")
    assert code == 1 and local == [] and "refused" in err


def test_local_on_a_repo_page_sends_no_report(tiroir, laptop, local, capsys):
    page = laptop / "docs" / "plan.md"
    assert run(capsys, page, "--local")[0] == 0
    assert tiroir.seen == [] and local == [str(page)]


def test_a_repo_page_takes_no_folder_or_keep_and_nothing_is_sent(tiroir, laptop, local, capsys):
    code, out, err = run(capsys, laptop / "docs" / "plan.md", "--keep")
    assert code == 2 and tiroir.seen == [] and local == []


# ── review fixes ─────────────────────────────────────────────────────────────

def test_a_clone_already_held_still_takes_the_report_when_the_app_has_since_lost_the_repo(hub_repos):
    report(hub_repos, who="bea-claude")
    hub_repos.app.installed.clear()
    bad, got = report(hub_repos, who="bea-claude", session=SESSION)
    assert not bad, got
    assert got["clone"] == "ok"
    assert hub_repos.hub.repos.attribution(REPO, "docs/plan.md")["session"] == SESSION


def test_a_clone_that_fails_leaves_no_half_made_folder_and_the_report_that_hears_of_it_clones_again(
        hub_repos, origin, tmp_path):
    hub_repos.hub.repos.remote_url = lambda repo: str(tmp_path / "does-not-exist.git")
    bad, got = report_once(hub_repos)
    assert not bad and got["clone"] == "cloning"
    assert hub_repos.hub.repos.settle()
    assert not list(clones(hub_repos).glob("*/*"))
    hub_repos.hub.repos.remote_url = lambda repo: str(origin)
    bad, got = report_once(hub_repos)               # one report: it is refused, and it starts the new clone
    assert bad and "failed" in got
    assert hub_repos.hub.repos.settle()
    the_clone(hub_repos)
    bad, got = report_once(hub_repos)
    assert not bad and got["clone"] == "ok"


# ── second round ─────────────────────────────────────────────────────────────

def test_every_git_that_can_fetch_blobs_carries_the_token_the_sparse_set_included(hub_repos, monkeypatch):
    """A blobless clone fetches the blobs of a folder when it is checked out: a private repo needs the token there."""
    real, calls = subprocess.run, []

    def spy(argv, *a, **k):
        calls.append((list(argv), dict(k.get("env") or {})))
        return real(argv, *a, **k)

    monkeypatch.setattr(repos_mod.subprocess, "run", spy)
    report(hub_repos)
    report(hub_repos, path="notes/idea.md")
    for needle in ("clone", "sparse-checkout"):
        mine = [env for argv, env in calls if needle in argv and argv[-1] != "list"]
        assert mine and all("GIT_CONFIG_VALUE_0" in env for env in mine), needle


def test_a_newer_commit_brings_the_clones_files_with_it_so_a_new_owner_line_is_read(hub_repos, tmp_path, origin):
    report(hub_repos, who="bea-claude")
    pusher = laptop_clone(tmp_path, origin, "pusher")
    (pusher / "docs" / "plan.md").write_text("---\nowner: cal\n---\n# Plan\n", encoding="utf-8")
    sh(pusher, "commit", "-qam", "hand it over")
    sh(pusher, "push", "-q", "origin", "HEAD:main")
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "bea"
    report(hub_repos, who="bea-claude", commit=sh(pusher, "rev-parse", "HEAD"))
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "cal"


def test_a_repo_named_in_another_case_is_the_same_repo_and_the_same_clone(hub_repos):
    report(hub_repos)
    commit = sh(hub_repos.origin, "rev-parse", "main")
    res = door(hub_repos.door, rpc("tools/call", {"name": "render_report", "arguments": {
        "repo": REPO.upper(), "path": "docs/plan.md", "commit": commit}}), token=hub_repos.tokens["cal-claude"],
        as_name=None)
    got = json.loads(res.json()["result"]["content"][0]["text"])
    assert got["clone"] == "ok" and got["repo"] == REPO
    the_clone(hub_repos)
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "bea"


# ── after round two ──────────────────────────────────────────────────────────

def test_a_report_the_door_refuses_still_renders_the_page_on_the_laptop_hub(tiroir, hub_repos, laptop, local, capsys):
    hub_repos.hub.proxy = None                  # the token acts for nobody: the door refuses the report
    page = laptop / "docs" / "plan.md"
    code, out, err = run(capsys, page)
    assert code == 0 and local == [str(page)]
    assert "render report" in err


@pytest.mark.parametrize("first", [True, False], ids=["the clone's sparse set", "the widening"])
def test_a_folder_that_looks_like_a_git_option_is_never_read_as_one(hub_repos, monkeypatch, first):
    seen = []
    real = repos_mod.Repos._git

    def spy(self, at, *args, **k):
        seen.append(args)
        return real(self, at, *args, **k)

    monkeypatch.setattr(repos_mod.Repos, "_git", spy)
    if not first:
        report(hub_repos)
    seen.clear()
    bad, got = report(hub_repos, path="--stdin/x.md")
    assert not bad, got
    folders = [a for a in seen if a[:1] == ("sparse-checkout",) and a[1] in ("set", "add")]
    assert folders and all(a[-2:] == ("--", "--stdin") for a in folders), folders
    assert sh(the_clone(hub_repos), "status", "--porcelain") == ""


def test_a_page_that_is_not_in_the_commit_and_a_commit_that_is_unknown_leave_no_owner_record(hub_repos):
    report(hub_repos)
    bad, got = report(hub_repos, who="cal-claude", path="docs/ghost.md")
    assert not bad, got
    assert hub_repos.hub.repos.owner_of(REPO, "docs/ghost.md") is None
    bad, got = report(hub_repos, who="cal-claude", path="notes/idea.md", commit="a" * 40)
    assert got["commit_known"] is False
    assert hub_repos.hub.repos.owner_of(REPO, "notes/idea.md") is None
    report(hub_repos, who="bea-claude", path="notes/idea.md")
    assert hub_repos.hub.repos.owner_of(REPO, "notes/idea.md") == "bea"


def test_a_private_root_whose_github_remote_is_not_named_origin_is_still_private(hub_repos, tmp_path, origin):
    own = private_root_of(hub_repos, BEA, tmp_path, origin)
    sh(own, "remote", "rename", "origin", "github")
    bad, got = report(hub_repos, who="bea-claude")
    assert not bad, got
    assert got["clone"] == "private-root" and not list(clones(hub_repos).glob("*/*"))


def test_a_private_root_that_pushes_to_the_repo_but_fetches_from_elsewhere_is_still_private(
        hub_repos, tmp_path, origin):
    own = private_root_of(hub_repos, BEA, tmp_path, origin)
    sh(own, "remote", "set-url", "origin", str(tmp_path / "somewhere-else.git"))
    sh(own, "remote", "set-url", "--push", "origin", str(origin))
    bad, got = report(hub_repos, who="bea-claude")
    assert not bad, got
    assert got["clone"] == "private-root" and not list(clones(hub_repos).glob("*/*"))


def test_a_private_root_that_is_another_repo_does_not_block_the_clone(hub_repos, tmp_path, origin):
    own = private_root_of(hub_repos, BEA, tmp_path, origin)
    sh(own, "remote", "set-url", "origin", str(tmp_path / "somewhere-else.git"))
    bad, got = report(hub_repos, who="cal-claude")
    assert not bad, got
    assert got["clone"] == "ok"


@pytest.mark.parametrize("breakage", ["missing", "unreadable-git-dir", "git-gives-no-answer"])
def test_a_private_root_that_cannot_be_looked_at_blocks_the_clone_rather_than_letting_it_through(
        hub_repos, tmp_path, origin, monkeypatch, breakage):
    own = private_root_of(hub_repos, BEA, tmp_path, origin)
    if breakage == "missing":
        shutil.rmtree(own)
    elif breakage == "unreadable-git-dir":
        shutil.rmtree(own / ".git")
        (own / ".git").write_text("not a git dir\n", encoding="utf-8")
    else:
        monkeypatch.setattr(proxy_mod, "_git", lambda folder, *args: None)
    bad, got = report(hub_repos, who="bea-claude")
    assert not bad, got
    assert got["clone"] == "private-root" and not list(clones(hub_repos).glob("*/*"))


# ── a commit on a branch other than the default one ──────────────────────────

def test_a_commit_pushed_on_a_feature_branch_is_known_to_the_tiroir_as_the_cli_takes_it(hub_repos, tmp_path, origin):
    report(hub_repos)
    pusher = laptop_clone(tmp_path, origin, "pusher")
    sh(pusher, "checkout", "-q", "-b", "feature")
    (pusher / "docs" / "plan.md").write_text("# Plan\n\nOn a branch.\n", encoding="utf-8")
    sh(pusher, "commit", "-qam", "branch work")
    sh(pusher, "push", "-q", "origin", "feature")
    bad, got = report(hub_repos, commit=sh(pusher, "rev-parse", "HEAD"))
    assert not bad, got
    assert got["commit_known"] is True


def test_a_commit_on_a_feature_branch_is_known_to_the_first_report_of_a_repo_too(hub_repos, tmp_path, origin):
    pusher = laptop_clone(tmp_path, origin, "pusher")
    sh(pusher, "checkout", "-q", "-b", "feature")
    (pusher / "docs" / "plan.md").write_text("# Plan\n\nOn a branch.\n", encoding="utf-8")
    sh(pusher, "commit", "-qam", "branch work")
    sh(pusher, "push", "-q", "origin", "feature")
    bad, got = report(hub_repos, commit=sh(pusher, "rev-parse", "HEAD"))
    assert not bad, got
    assert got["clone"] == "ok" and got["commit_known"] is True
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "bea"


# ── another member's private root: not cloned, said once and the same for everyone (SPEC 9.11) ──

OTHER = "acme-org/elsewhere"


@pytest.mark.parametrize("what", ["a real commit", "a commit that does not exist"])
def test_another_members_private_root_is_answered_the_same_whatever_the_commit_or_the_app(
        hub_repos, tmp_path, origin, what):
    private_root_of(hub_repos, BEA, tmp_path, origin)
    commit = sh(origin, "rev-parse", "main") if what == "a real commit" else "a" * 40
    first = report(hub_repos, who="cal-claude", commit=commit)[1]
    hub_repos.app.installed.clear()
    assert report(hub_repos, who="cal-claude", commit=commit)[1] == first
    assert first["clone"] == "not-cloned" and not list(clones(hub_repos).glob("*/*"))


def test_the_owner_of_a_private_root_is_told_so_and_the_answer_is_not_the_probers(hub_repos, tmp_path, origin):
    private_root_of(hub_repos, BEA, tmp_path, origin)
    _, mine = report(hub_repos, who="bea-claude", repo=REPO)
    _, theirs = report(hub_repos, who="cal-claude", repo=REPO)
    assert mine["clone"] == "private-root" and theirs["clone"] == "not-cloned"


def test_an_answer_never_tells_what_the_tiroir_already_holds(hub_repos):
    _, first = report(hub_repos, who="bea-claude")
    _, second = report(hub_repos, who="cal-claude")
    _, third = report(hub_repos, who="cal-claude", path="notes/idea.md")
    assert first == second == third | {"path": "docs/plan.md"}
    assert set(first) == {"repo", "path", "clone", "commit_known"}


# ── the CLI falls back to the laptop hub, with one line to say why ───────────

def test_a_page_of_a_repo_that_is_your_private_root_renders_on_the_laptop_with_one_line(
        tiroir, hub_repos, laptop, local, capsys, tmp_path, origin):
    private_root_of(hub_repos, BEA, tmp_path, origin)
    page = laptop / "docs" / "plan.md"
    code, out, err = run(capsys, page)
    assert code == 0 and local == [str(page)]
    assert err.count("\n") == 1 and "your private root" in err


def test_a_page_of_a_repo_that_is_anothers_private_root_renders_on_the_laptop_with_one_line_naming_no_one(
        tiroir, hub_repos, laptop, local, capsys, tmp_path, origin):
    private_root_of(hub_repos, CAL, tmp_path, origin)
    page = laptop / "docs" / "plan.md"
    code, out, err = run(capsys, page)
    assert code == 0 and local == [str(page)]
    assert err.count("\n") == 1 and "not cloned" in err and "private" not in err and "cal" not in err.lower()


def test_a_page_whose_commit_the_tiroir_cannot_find_renders_on_the_laptop_with_one_line(
        tiroir, hub_repos, laptop, local, capsys, monkeypatch):
    report(hub_repos)                                                   # the clone is made
    monkeypatch.setattr(repos_mod.Repos, "_on_branch", lambda self, dest, commit, seconds=0: False)
    page = laptop / "docs" / "plan.md"
    code, out, err = run(capsys, page)
    assert code == 0 and local == [str(page)]
    assert err.count("\n") == 1 and "pushed to GitHub" in err


# ── third fix round ──────────────────────────────────────────────────────────

def test_a_private_root_that_exists_without_a_git_dir_is_still_private(hub_repos, tmp_path, origin):
    own = private_root_of(hub_repos, BEA, tmp_path, origin)
    shutil.rmtree(own / ".git")
    _, mine = report(hub_repos, who="bea-claude")
    _, theirs = report(hub_repos, who="cal-claude")
    assert mine["clone"] == "private-root" and theirs["clone"] == "not-cloned"
    assert not list(clones(hub_repos).glob("*/*"))


def test_a_private_root_without_a_git_dir_inside_another_repo_is_still_private(hub_repos, tmp_path, origin):
    parent = laptop_clone(tmp_path, origin, "parent")           # git walks up from the root to this repo
    root = parent / "work"
    root.mkdir()
    members = dict(hub_repos.hub.proxy.members)
    members[BEA] = dataclasses.replace(members[BEA], private_root=str(root))
    hub_repos.hub.proxy = dataclasses.replace(hub_repos.hub.proxy, members=members)
    hub_repos.hub.repos.remote_url = lambda repo: str(tmp_path / "unrelated.git")      # not the parent's remote
    _, got = report(hub_repos, who="bea-claude", repo="acme-org/unrelated")
    assert got["clone"] == "private-root"


def test_a_slow_clone_never_holds_a_report_and_one_repo_does_not_hold_another(hub_repos, origin, tmp_path, monkeypatch):
    twin = tmp_path / "twin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(origin), str(twin)], check=True, capture_output=True)
    sh(twin, "config", "uploadpack.allowFilter", "true")
    hub_repos.app.installed.add(OTHER)
    repos = hub_repos.hub.repos
    repos.remote_url = lambda repo: str({REPO: origin, OTHER: twin}[repo])
    release, real = threading.Event(), Repos._clone

    def slow(self, repo, token, folder, dest):
        if repo == REPO:
            assert release.wait(30)
        return real(self, repo, token, folder, dest)

    monkeypatch.setattr(Repos, "_clone", slow)
    try:
        for who, repo in (("bea-claude", REPO), ("cal-claude", REPO), ("cal-claude", OTHER)):
            began = time.monotonic()
            bad, got = report_once(hub_repos, who=who, repo=repo)
            assert not bad and got["clone"] == "cloning" and time.monotonic() - began < 0.5, (got, time.monotonic() - began)
        end = time.monotonic() + 20           # the other repo's clone is made while the first one is still held
        while time.monotonic() < end and not (clones(hub_repos) / "acme-org" / "elsewhere" / ".git").exists():
            time.sleep(0.05)
        assert (clones(hub_repos) / "acme-org" / "elsewhere" / ".git").exists()
        assert not (clones(hub_repos) / "acme-org" / "site" / ".git").exists()
    finally:
        release.set()
        assert repos.settle()


def test_a_hundred_made_up_commits_cost_one_fetch(hub_repos, monkeypatch):
    report(hub_repos)
    repos = hub_repos.hub.repos
    repos.FETCH_EVERY, fetches, real = 3600.0, [], Repos._git

    def spy(self, at, *args, **kw):
        fetches.append(args) if "fetch" in args else None
        return real(self, at, *args, **kw)

    monkeypatch.setattr(Repos, "_git", spy)
    for i in range(100):
        bad, got = report_once(hub_repos, commit=f"{i:040x}")
        assert not bad and got["commit_known"] is False
    assert repos.settle()
    assert len(fetches) <= 1, fetches


@pytest.mark.parametrize("url,hostname,private", [
    ("ssh://git@ssh.github.com:443/acme-org/site.git", None, True),
    ("git@github-work:acme-org/site.git", "github.com", True),
    ("git@github-work:acme-org/site.git", None, True),                      # ssh cannot say: fail closed on the path
    ("git@mystery:acme-org/site.git", "mystery", True),                      # a name that is no domain: the same
    ("git@gitlab-alias:acme-org/site.git", "gitlab.example.com", False),    # a real other host is another repo
    ("git@github-work:acme-org/other.git", "github.com", False)])
def test_a_private_root_reaching_github_by_another_host_name_is_still_private(
        hub_repos, tmp_path, origin, url, hostname, private):
    own = private_root_of(hub_repos, BEA, tmp_path, origin)
    sh(own, "remote", "set-url", "origin", url)
    hub_repos.hub.repos.remote_url = lambda repo: f"https://github.com/{repo}.git"
    hub_repos.hub.repos.ssh_hostname = lambda host: hostname
    got = report_once(hub_repos, who="cal-claude")[1]
    assert (got["clone"] == "not-cloned") is private


def test_ssh_hostname_resolves_an_alias_of_a_config_file(tmp_path):
    config = tmp_path / "ssh_config"
    config.write_text("Host github-work\n  HostName ssh.github.com\n  Port 443\n", encoding="utf-8")
    assert repos_mod.ssh_hostname("github-work", str(config)) == "ssh.github.com"
    assert repos_mod.ssh_hostname("plain.example.com", str(config)) == "plain.example.com"


def test_a_page_git_cannot_read_keeps_the_owner_record_it_had(hub_repos, tmp_path, origin, monkeypatch):
    pusher = laptop_clone(tmp_path, origin, "pusher")
    (pusher / "docs" / "plan.md").write_text("---\nowner: cal\n---\n# Plan\n", encoding="utf-8")
    sh(pusher, "commit", "-qam", "owned")
    sh(pusher, "push", "-q", "origin", "HEAD:main")
    commit = sh(pusher, "rev-parse", "HEAD")
    report(hub_repos, who="bea-claude", commit=commit)
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "cal"
    monkeypatch.setattr(Repos, "_named_owner", lambda self, *a, **kw: (False, None))
    report(hub_repos, who="cal-claude", commit=commit, session=SESSION)
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "cal"


def test_a_first_report_whose_page_git_cannot_read_makes_no_record(hub_repos, monkeypatch):
    monkeypatch.setattr(Repos, "_named_owner", lambda self, *a, **kw: (False, None))
    report(hub_repos)
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") is None


def test_a_repo_that_became_a_private_root_after_it_was_cloned_takes_no_more_records(hub_repos, tmp_path, origin):
    report(hub_repos, who="bea-claude")
    clone, records = the_clone(hub_repos), (hub_repos.hub.repos.base / "reports.json").read_text(encoding="utf-8")
    pusher = laptop_clone(tmp_path, origin, "pusher")
    (pusher / "notes" / "idea.md").write_text("# Idea\n\nChanged.\n", encoding="utf-8")
    sh(pusher, "commit", "-qam", "more")
    sh(pusher, "push", "-q", "origin", "HEAD:main")
    private_root_of(hub_repos, CAL, tmp_path, origin)
    _, got = report(hub_repos, who="bea-claude", path="notes/idea.md", commit=sh(pusher, "rev-parse", "HEAD"))
    assert got["clone"] == "not-cloned"
    assert (hub_repos.hub.repos.base / "reports.json").read_text(encoding="utf-8") == records
    assert clone.exists()


def test_the_owner_of_a_page_is_read_at_the_reported_commit_not_at_the_default_branch(hub_repos, tmp_path, origin):
    pusher = laptop_clone(tmp_path, origin, "pusher")
    sh(pusher, "checkout", "-q", "-b", "feature")
    (pusher / "docs" / "plan.md").write_text("---\nowner: cal\n---\n# Plan\n", encoding="utf-8")
    sh(pusher, "commit", "-qam", "owned")
    sh(pusher, "push", "-q", "origin", "feature")
    _, got = report(hub_repos, who="bea-claude", commit=sh(pusher, "rev-parse", "HEAD"))
    assert got["commit_known"] is True
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "cal"
    main = sh(origin, "rev-parse", "main")                       # a later report at main, whose page names no owner
    report(hub_repos, who="bea-claude", commit=main)
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "bea"


# ── round eight: a door that does not answer a report ────────────────────────

def _door_that(monkeypatch, tiroir, answer):
    """The CLI's network is the in-memory tiroir, except that `answer(message)` may replace what the door says: None
    keeps the tiroir's own answer."""
    real = tiroir.calls[0]

    def post(url, bearer, message, headers):
        return answer(message) or real(url, bearer, message, headers)

    monkeypatch.setattr(send, "post", post)


def _no_tool(message):
    if message.get("method") == "tools/call":
        return 200, {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32602, "message": "unknown tool"}}, {}


def _no_initialize(message):
    if message.get("method") == "initialize":
        return 404, None, {}


def _garbage(message):
    if message.get("method") == "tools/call":
        return 200, {"jsonrpc": "2.0", "id": message["id"], "result": {"content": [{"type": "text", "text": "<html>"}]}}, {}


def _empty(message):
    if message.get("method") == "tools/call":
        return 200, {"jsonrpc": "2.0", "id": message["id"], "result": {}}, {}


@pytest.mark.parametrize("answer", [_no_tool, _no_initialize, _garbage, _empty],
                         ids=["no render_report tool", "initialize fails", "garbage", "no content"])
def test_a_door_that_does_not_answer_a_report_renders_the_page_on_the_laptop(
        answer, tiroir, hub_repos, laptop, local, monkeypatch, capsys):
    _door_that(monkeypatch, tiroir, answer)
    page = laptop / "docs" / "plan.md"
    code, out, err = run(capsys, page)
    assert code == 0, err
    assert local == [str(page)] and out == ""
    assert "on this laptop" in err and "Traceback" not in err


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_token_on_a_report_still_fails_loudly(status, tiroir, hub_repos, laptop, local, monkeypatch, capsys):
    _door_that(monkeypatch, tiroir, lambda message: (status, None, {}))
    code, out, err = run(capsys, laptop / "docs" / "plan.md")
    assert code == 1 and local == []
    assert "refused the token" in err
