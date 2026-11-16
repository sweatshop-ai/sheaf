"""Repo pages and repo clones (SPEC 13, 14): `sheaf FILE.md` on a page inside a git repo sends a render report, never
text; the tiroir clones the repo the first time (blobless, sparse), widens the sparse set for a new folder, keeps the
owner of each page, and makes no clone of a member's private root. Everything runs against local bare repos and a fake
App behind `Repos`'s one seam, the token provider: no real token, no real GitHub."""
import base64
import dataclasses
import json
import subprocess
from pathlib import Path

import pytest
from helpers import BEA, CAL, FRONT, door, rpc
from helpers import call as door_call
from test_send import keyring, local, no_real_keyring, run, tiroir  # noqa: F401  (fixtures and helpers)
from test_hub_commits import box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents, declared  # noqa: F401  (fixtures and helpers)

from sheafmd import paths, send
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


def report(hub_repos, who="bea-claude", path="docs/plan.md", commit=None, **declares):
    """(is it an error, the answer) of a render report; `declares` is what the caller says in its headers."""
    commit = commit or sh(hub_repos.origin, "rev-parse", "main")
    res = door(hub_repos.door, rpc("tools/call", {"name": "render_report", "arguments": {
        "repo": REPO, "path": path, "commit": commit}}), token=hub_repos.tokens[who], as_name=None,
        headers=declared(**declares))
    assert res.status == 200, res.text
    out = res.json()["result"]
    text = out["content"][0]["text"]
    return out["isError"], (text if out["isError"] else json.loads(text))


def the_clone(hub_repos) -> Path:
    found = sorted(p for p in clones(hub_repos).glob("*/*") if (p / ".git").exists())
    assert len(found) == 1, found
    return found[0]


# ── the first report clones, blobless and sparse ─────────────────────────────

def test_the_first_report_for_a_repo_clones_it_blobless_and_sparse_with_the_pages_folder(hub_repos):
    bad, got = report(hub_repos)
    assert not bad, got
    assert got["clone"] == "made" and got["repo"] == REPO
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
    assert got["clone"] == "present" and got["widened"] == "notes"
    assert (clone / "notes" / "idea.md").is_file() and not (clone / "src").exists()
    assert report(hub_repos, path="notes/idea.md")[1]["widened"] is None


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


def test_a_repo_that_is_another_members_private_root_gets_no_clone_either(hub_repos, tmp_path, origin):
    private_root_of(hub_repos, BEA, tmp_path, origin)
    bad, got = report(hub_repos, who="cal-claude")
    assert not bad, got
    assert got["clone"] == "private-root"
    assert not list(clones(hub_repos).glob("*/*"))


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
    assert got["clone"] == "present"
    assert hub_repos.hub.repos.attribution(REPO, "docs/plan.md")["session"] == SESSION


def test_a_clone_that_fails_leaves_no_half_made_folder_and_the_next_report_tries_again(hub_repos, origin, tmp_path):
    hub_repos.hub.repos.remote_url = lambda repo: str(tmp_path / "does-not-exist.git")
    bad, got = report(hub_repos)
    assert bad and "failed" in got
    assert not list(clones(hub_repos).glob("*/*"))
    hub_repos.hub.repos.remote_url = lambda repo: str(origin)
    bad, got = report(hub_repos)
    assert not bad and got["clone"] == "made"


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
    assert got["clone"] == "present" and got["repo"] == REPO
    the_clone(hub_repos)
    assert hub_repos.hub.repos.owner_of(REPO, "docs/plan.md") == "bea"
