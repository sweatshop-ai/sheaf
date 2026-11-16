"""Saves on a repo page (SPEC 8.11, 14): the tiroir serves a clone as a root, a save or a door `update` commits and pushes
on `dev` where the remote has it, else on the branch the repo's `.sheaf.toml` names, and with neither the page is read-only
with a line. Everything runs against local bare repos and a fake App, as test_repo_pages.py does."""
import json
import subprocess

import pytest
from helpers import BEA, CAL, door, rpc
from test_send import keyring, local, no_real_keyring, run, scratch, tiroir  # noqa: F401  (fixtures)
from test_hub_commits import box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents, declared  # noqa: F401  (fixtures)
from test_repo_pages import (REPO, FakeApp, app, hub_repos, laptop_clone, report, sh, the_clone)  # noqa: F401

from sheafmd import config
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import commits as commits_mod
from sheafmd.hub import proxy as proxy_mod
from sheafmd.hub import repos as repos_mod
from sheafmd.hub.repos import Repos, root_name
from sheafmd.source import md_hash

ADDRESS = f"{root_name(REPO)}/docs/plan.md"


def push_branch(origin, tmp_path, name, toml=None, on="main"):
    """A branch `name` on the remote, off `on`; with `toml`, a `.sheaf.toml` of that text on it."""
    work = tmp_path / f"work-{name}"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    sh(work, "config", "user.name", "Dee Dev")
    sh(work, "config", "user.email", "dee@example.com")
    sh(work, "checkout", "-q", "-b", name, f"origin/{on}")
    if toml is not None:
        (work / ".sheaf.toml").write_text(toml, encoding="utf-8")
        sh(work, "add", "-A")
        sh(work, "commit", "-q", "-m", f"{name} toml")
    sh(work, "push", "-q", "origin", name)


@pytest.fixture
def origin(tmp_path, request):
    """The repo on 'GitHub' (as test_repo_pages makes it), with what the test's `shape` says: `dev` (a branch `dev`),
    `toml` (the text of a `.sheaf.toml` on `main`), `branches` (more branches off `main`)."""
    shape = getattr(request, "param", {})
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    sh(bare, "config", "uploadpack.allowFilter", "true")
    sh(bare, "config", "uploadpack.allowAnySHA1InWant", "true")
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
    sh(seed, "config", "user.name", "Dee Dev")
    sh(seed, "config", "user.email", "dee@example.com")
    files = {"docs/plan.md": "# Plan\n\nA plan.\n", "notes/idea.md": "# Idea\n\nAn idea.\n", "README.md": "# Site\n"}
    if "toml" in shape:
        files[".sheaf.toml"] = shape["toml"]
    for rel, text in files.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text, encoding="utf-8")
    sh(seed, "add", "-A")
    sh(seed, "commit", "-q", "-m", "first")
    sh(seed, "push", "-q", "origin", "HEAD:main")
    for name in ([*(["dev"] if shape.get("dev") else []), *shape.get("branches", [])]):
        push_branch(bare, tmp_path, name)
    return bare


DEV = pytest.mark.parametrize("origin", [{"dev": True}], indirect=True)
NAMED = pytest.mark.parametrize("origin", [{"toml": 'branch = "staging"\n', "branches": ["staging"]}], indirect=True)
NAMED_MISSING = pytest.mark.parametrize("origin", [{"toml": 'branch = "staging"\n'}], indirect=True)
NEITHER = pytest.mark.parametrize("origin", [{}], indirect=True)


def served(hub_repos, **kw):
    """The page's repo reported and cloned and served; the page's text."""
    bad, got = report(hub_repos, **kw)
    assert not bad, got
    assert hub_repos.hub.repos.settle()
    return hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8")


def save(hub_repos, member=BEA, words="A plan, saved on the page."):
    text = hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("A plan"))
    return hub_repos.post("/_/save", {"doc": ADDRESS, "hash": md_hash(text), "edits": [{"i": i, "html": f"<p>{words}</p>"}]},
                          member=member)


def remote_commits(hub_repos, branch):
    """`author|subject` of the commits on `branch` of the remote that `main` has not got, once the hub has pushed."""
    hub_repos.hub.commits.settle()
    return [line for line in sh(hub_repos.origin, "log", "--format=%an|%s", f"main..{branch}").splitlines()]


def door_call(hub_repos, who, tool, **args):
    res = door(hub_repos.door, rpc("tools/call", {"name": tool, "arguments": args}), token=hub_repos.tokens[who],
               as_name=None)
    assert res.status == 200, res.text
    out = res.json()["result"]
    return out["isError"], out["content"][0]["text"]


# ── the clone is served, and a save commits on dev ───────────────────────────

def test_a_clone_is_a_root_named_from_its_repo_and_its_page_opens(hub_repos):
    served(hub_repos)
    root = hub_repos.hub.roots.get(root_name(REPO))
    assert root is not None and root.clone == REPO and root_name(REPO) == "acme-org--site"
    assert hub_repos.get(f"/{ADDRESS}", member=BEA).status == 200


@DEV
def test_a_save_on_a_repo_page_is_one_commit_on_dev_under_the_members_name(hub_repos):
    served(hub_repos)
    main = sh(hub_repos.origin, "rev-parse", "main")
    assert sh(the_clone(hub_repos), "symbolic-ref", "--short", "HEAD") == "dev"
    r = save(hub_repos)
    assert r.status == 200, r.text
    assert remote_commits(hub_repos, "dev") == ["Bea|edit: docs/plan.md"]
    assert sh(hub_repos.origin, "rev-parse", "main") == main
    assert sh(hub_repos.origin, "show", "dev:docs/plan.md").endswith("A plan, saved on the page.")


@DEV
def test_the_repos_sheaf_toml_without_commit_or_push_does_not_stop_a_clone_saving(hub_repos):
    served(hub_repos)
    assert not (the_clone(hub_repos) / ".sheaf.toml").exists()
    assert save(hub_repos).status == 200
    assert len(remote_commits(hub_repos, "dev")) == 1


@DEV
def test_a_dev_branch_wins_over_a_branch_the_sheaf_toml_names(hub_repos, tmp_path):
    push_branch(hub_repos.origin, tmp_path, "staging")
    sh(hub_repos.origin, "config", "user.name", "x")
    served(hub_repos)
    assert hub_repos.hub.repos.saves_on(REPO) == ("dev", "")


@DEV
def test_the_hub_makes_no_commit_but_the_saves(hub_repos):
    served(hub_repos)
    report(hub_repos)
    hub_repos.hub.commits.settle()
    assert remote_commits(hub_repos, "dev") == []
    assert sh(the_clone(hub_repos), "rev-list", "--count", "origin/dev..HEAD") == "0"


@DEV
def test_the_installation_token_reaches_git_in_the_environment_only(hub_repos):
    served(hub_repos)
    env = commits_mod._env(None, the_clone(hub_repos))
    assert "ghs_faketoken" not in json.dumps({k: v for k, v in env.items() if not k.startswith("GIT_CONFIG_")})
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert "ghs_faketoken" not in (hub_repos.hub.repos.base / "reports.json").read_text(encoding="utf-8")
    assert "ghs_faketoken" not in subprocess.run(["git", "-C", str(the_clone(hub_repos)), "config", "--list"],
                                                 capture_output=True, text=True).stdout


# ── only main and a branch the .sheaf.toml names ─────────────────────────────

@NAMED
def test_a_repo_with_only_main_and_a_named_branch_saves_on_that_branch_and_never_on_main(hub_repos):
    served(hub_repos)
    main = sh(hub_repos.origin, "rev-parse", "main")
    assert save(hub_repos).status == 200
    assert remote_commits(hub_repos, "staging") == ["Bea|edit: docs/plan.md"]
    assert sh(hub_repos.origin, "rev-parse", "main") == main


@NAMED_MISSING
def test_a_named_branch_the_remote_does_not_have_opens_read_only_with_its_own_line(hub_repos):
    served(hub_repos)
    branch, line = hub_repos.hub.repos.saves_on(REPO)
    assert branch is None and "staging" in line and "does not have" in line
    assert sh(hub_repos.origin, "branch", "--list").split() == ["*", "main"] or "staging" not in sh(hub_repos.origin, "branch")


@NEITHER
def test_with_neither_the_page_opens_read_only_and_the_line_names_the_sheaf_toml_line(hub_repos):
    served(hub_repos)
    page = hub_repos.get(f"/{ADDRESS}", member=BEA).text
    assert '"readonly": true' in page
    assert ".sheaf.toml" in page and "branch =" in page


@NEITHER
def test_a_save_on_a_read_only_page_is_refused_and_writes_nothing(hub_repos):
    served(hub_repos)
    before = hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8")
    r = save(hub_repos)
    assert r.status == 403 and ".sheaf.toml" in r.text
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8") == before
    assert sh(the_clone(hub_repos), "rev-list", "--all", "--count") == sh(hub_repos.origin, "rev-list", "--all", "--count")


@NEITHER
def test_a_comment_on_a_read_only_page_is_refused_and_a_door_write_too(hub_repos):
    text = served(hub_repos)
    r = hub_repos.post("/_/comment", {"doc": ADDRESS, "op": "add", "hash": md_hash(text), "block": 1, "start": 0,
                                      "end": 1, "quote": "A", "body": "Why?"}, member=BEA)
    assert r.status == 403
    bad, said = door_call(hub_repos, "bea-claude", "update", doc=ADDRESS, expected_hash=md_hash(text), text=text + "\nx\n")
    assert bad and ".sheaf.toml" in said
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8") == text


@pytest.mark.parametrize("origin", [{"branches": ["release", "master"]}], indirect=True)
def test_the_hub_never_guesses_a_deploying_branch(hub_repos):
    served(hub_repos)
    assert hub_repos.hub.repos.saves_on(REPO)[0] is None


def test_branch_named_reads_a_branch_and_nothing_else():
    assert config.branch_named('branch = "staging"\n') == "staging"
    assert config.branch_named('branch = "../x"\n') is None
    assert config.branch_named("not toml [") is None
    assert config.branch_named("commit = true\n") is None


# ── the door ─────────────────────────────────────────────────────────────────

@DEV
def test_a_door_update_with_the_current_hash_lands_as_a_commit_on_dev_and_a_stale_one_is_refused(hub_repos):
    text = served(hub_repos)
    bad, said = door_call(hub_repos, "bea-claude", "update", doc=ADDRESS, expected_hash=md_hash(text),
                          text=text + "\nBy the door.\n")
    assert not bad, said
    assert json.loads(said)["hash"] == md_hash(hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8"))
    assert len(remote_commits(hub_repos, "dev")) == 1
    bad, said = door_call(hub_repos, "bea-claude", "update", doc=ADDRESS, expected_hash=md_hash(text),
                          text=text + "\nStale.\n")
    assert bad
    assert len(remote_commits(hub_repos, "dev")) == 1


@DEV
def test_a_page_with_no_owner_record_opens_to_nobody_and_one_with_it_to_its_member(hub_repos):
    served(hub_repos)
    assert hub_repos.get(f"/{ADDRESS}", member=BEA).status == 200      # Bea reported it
    assert hub_repos.get(f"/{ADDRESS}", member=CAL).status in (403, 404)
    assert hub_repos.get(f"/{root_name(REPO)}/notes/idea.md", member=BEA).status in (403, 404)    # nobody reported it


# ── the wiring ───────────────────────────────────────────────────────────────

def test_a_proxy_repos_table_builds_a_repos_whose_token_comes_from_its_command(tmp_path):
    cfg = {"dir": str(tmp_path / "clones"), "token_command": ["echo", "ghs_x"], "install_url": "https://example.com/add"}
    made = repos_mod.from_config(cfg)
    assert isinstance(made, Repos) and made.base == tmp_path / "clones"
    assert made.provider.token("acme-org/site") == "ghs_x acme-org/site"
    assert made.provider.install_url("acme-org/site") == "https://example.com/add"
    assert repos_mod.from_config({"dir": str(tmp_path)}).provider.token("a/b") is None


def test_the_proxy_table_checks_its_repos_table(tmp_path):
    import os, pwd
    base = {"origin": "https://chat.example.com", "socket": "/run/sheaf-proxy/hub.sock",
            "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
            "members": {BEA: {"name": "Bea", "roots": [str(tmp_path)]}}}
    assert proxy_mod.parse(base, "the test").repos is None
    assert proxy_mod.parse({**base, "repos": {"dir": str(tmp_path)}}, "the test").repos == {"dir": str(tmp_path)}
    for bad in ({"dir": "relative"}, {"dir": str(tmp_path), "other": 1}, {"dir": str(tmp_path), "token_command": "x"}):
        with pytest.raises(proxy_mod.ProxyError):
            proxy_mod.parse({**base, "repos": bad}, "the test")
