"""Saves on a repo page (SPEC 8.11, 14): the tiroir serves a clone as a root, a save or a door `update` commits and pushes
on `dev` where the remote has it, else on the branch the repo's `.sheaf.toml` names, and with neither the page is read-only
with a line. Everything runs against local bare repos and a fake App, as test_repo_pages.py does."""
import base64
import contextlib
import dataclasses
import json
import os
import pwd
import re
import subprocess
import sys
import threading

import pytest
from helpers import BEA, CAL, FRONT, door, hub_rows, mark_generated, rpc
from test_send import keyring, local, no_real_keyring, run, scratch, tiroir  # noqa: F401  (fixtures)
from test_hub_commits import DOC, box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents, declared  # noqa: F401  (fixtures)
from test_repo_pages import (REPO, FakeApp, app, hub_repos, laptop_clone, report, sh, the_clone)  # noqa: F401

from sheafmd import config
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import commits as commits_mod
from sheafmd.hub import proxy as proxy_mod
from sheafmd.hub import repos as repos_mod
from sheafmd.hub import visibility
from sheafmd.hub.repos import Repos, root_name
from sheafmd.hub.state import Tokens
from sheafmd.source import md_hash

ADDRESS = f"{root_name(REPO)}/docs/plan.md"
HEADER = base64.b64encode(b"x-access-token:ghs_faketoken").decode()     # how the token reaches git, in the environment


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
    files = {"docs/plan.md": ("---\nowner: bea\n---\n" if shape.get("owned") else "---\nvisibility: project\n---\n" if shape.get("shared") else "") + "# Plan\n\nA plan.\n", "notes/idea.md": "# Idea\n\nAn idea.\n", "README.md": "# Site\n"}
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
SHARED = pytest.mark.parametrize("origin", [{"dev": True, "shared": True}], indirect=True)
DEV_AND_NAMED = pytest.mark.parametrize(
    "origin", [{"dev": True, "toml": 'branch = "staging"\n', "branches": ["staging"]}], indirect=True)
NAMED_MISSING = pytest.mark.parametrize("origin", [{"toml": 'branch = "staging"\n'}], indirect=True)
NEITHER = pytest.mark.parametrize("origin", [{}], indirect=True)
NEITHER_OWNED = pytest.mark.parametrize("origin", [{"owned": True}], indirect=True)


def served(hub_repos, **kw):
    """The page's repo reported and cloned and served; the page's text."""
    bad, got = report(hub_repos, **kw)
    assert not bad, got
    assert hub_repos.hub.repos.settle()
    return hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8")


def save(hub_repos, member=BEA, words="A plan, saved on the page.", branch=None):
    """The page's save: it carries the branch the page was read on (its meta's `branch`), by default the clone's HEAD now;
    `branch=""` leaves it out."""
    text = hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("A plan"))
    read_on = sh(the_clone(hub_repos), "symbolic-ref", "--short", "HEAD") if branch is None else branch
    return hub_repos.post("/_/save", {"doc": ADDRESS, "hash": md_hash(text), "edits": [{"i": i, "html": f"<p>{words}</p>"}],
                                      **({"branch": read_on} if read_on else {})}, member=member)


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


@DEV_AND_NAMED
def test_a_dev_branch_wins_over_a_branch_the_sheaf_toml_names(hub_repos):
    served(hub_repos)
    assert config.branch_named(sh(hub_repos.origin, "show", "main:.sheaf.toml")) == "staging"     # the file does name one
    assert sh(hub_repos.origin, "rev-parse", "--verify", "staging")                               # and the remote has it
    assert hub_repos.hub.repos.saves_on(REPO) == ("dev", "")
    assert save(hub_repos).status == 200
    assert len(remote_commits(hub_repos, "dev")) == 1
    assert remote_commits(hub_repos, "staging") == []


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
    assert sh(hub_repos.origin, "branch", "--list", "staging") == ""                  # the hub made no branch of that name
    assert sh(hub_repos.origin, "for-each-ref", "--format=%(refname:short)", "refs/heads") == "main"   # nor any other


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


@DEV
def test_no_door_path_judges_a_clone_page_on_its_raw_front_matter(hub_repos):
    """A page of a clone with no `visibility:` line is its reporter's alone at the door as on the page: another member's
    agent and a token bound to nobody neither read, list nor update it (SPEC 14)."""
    text = served(hub_repos)
    assert "visibility" not in text
    loose = Tokens().add("loose", write=True)
    hub_repos.tokens["loose"] = loose
    bad, said = door_call(hub_repos, "bea-claude", "read", doc=ADDRESS)
    assert not bad, said
    for who in ("cal-claude", "loose"):
        bad, said = door_call(hub_repos, who, "read", doc=ADDRESS)
        assert bad and "By the door" not in said and "A plan" not in said, (who, said)
        bad, said = door_call(hub_repos, who, "documents", open_only=False)
        assert ADDRESS not in said, (who, said)
        bad, said = door_call(hub_repos, who, "update", doc=ADDRESS, expected_hash=md_hash(text), text=text + "\nTaken.\n")
        assert bad, (who, said)
    assert remote_commits(hub_repos, "dev") == []
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8") == text


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


# ── fix round over 87bb477 ───────────────────────────────────────────────────

def clone_log(hub_repos):
    """Every commit the clone and the remote hold, by ref: nothing was committed or pushed if this is as it was."""
    return (sh(the_clone(hub_repos), "for-each-ref", "--format=%(refname) %(objectname)"),
            sh(hub_repos.origin, "for-each-ref", "--format=%(refname) %(objectname)"))


@NEITHER_OWNED
def test_share_on_a_read_only_page_is_refused_before_anything_is_written(hub_repos):
    text = served(hub_repos)
    before = clone_log(hub_repos)
    r = hub_repos.post("/_/share", {"doc": ADDRESS, "hash": md_hash(text), "with": []}, member=BEA)
    hub_repos.hub.commits.settle()
    assert r.status == 403 and ".sheaf.toml" in r.text
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8") == text
    assert clone_log(hub_repos) == before            # no commit, no undo commit, nothing pushed to main


@NEITHER_OWNED
@pytest.mark.parametrize("endpoint", ["/_/save", "/_/tick", "/_/share"])
def test_a_generated_page_of_a_read_only_clone_is_refused_as_generated_with_its_row(hub_repos, endpoint):
    # 183 AV: the page's own reason comes first, so the refusal says the page is generated and the row is written.
    text = served(hub_repos)
    mark_generated(hub_repos.hub, ADDRESS)
    assert hub_repos.hub.read_only_line(ADDRESS) != ""
    body = {"/_/save": {"edits": []}, "/_/tick": {"action": 0, "word": "Approve"}, "/_/share": {"with": []}}[endpoint]
    r = hub_repos.post(endpoint, {"doc": ADDRESS, "hash": md_hash(text), **body}, member=BEA)
    assert r.status == 403 and "Generated by builder" in r.text and ".sheaf.toml" not in r.text
    assert hub_rows("generated-refused")[-1]["endpoint"] == endpoint
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8") == text


def broken_checkout(hub_repos):
    """The clone's git cannot move HEAD: a checkout that times out (the blob fetch of a blobless clone)."""
    repos = hub_repos.hub.repos
    real = repos._git

    def git(at, *args, **kw):
        if args and args[0] == "checkout":
            return subprocess.CompletedProcess(args, 124, "", "timed out")
        return real(at, *args, **kw)
    repos._git = git


@DEV
def test_a_clone_whose_checkout_failed_is_read_only_and_a_save_goes_nowhere(hub_repos):
    broken_checkout(hub_repos)
    served(hub_repos)
    assert sh(the_clone(hub_repos), "symbolic-ref", "--short", "HEAD") == "main"      # the switch failed
    assert hub_repos.hub.repos.saves_on(REPO)[0] == "dev"                              # and dev is what it should be on
    assert hub_repos.hub.read_only_line(ADDRESS) != ""
    assert '"readonly": true' in hub_repos.get(f"/{ADDRESS}", member=BEA).text
    before = clone_log(hub_repos)
    r = save(hub_repos)
    hub_repos.hub.commits.settle()
    assert r.status == 403
    assert clone_log(hub_repos) == before            # nothing went to main


@DEV
def test_a_clone_with_a_change_of_its_own_stays_where_it_is_read_only_and_a_save_goes_nowhere(hub_repos):
    served(hub_repos)
    clone = the_clone(hub_repos)
    assert hub_repos.hub.read_only_line(ADDRESS) == ""
    sh(clone, "checkout", "-q", "main")                                    # HEAD is off the save branch
    (clone / "docs/plan.md").write_text("# Plan\n\nA plan, with a change nobody saved.\n", encoding="utf-8")
    hub_repos.hub.repos.serve(REPO, "ghs_faketoken")                       # the next report settles it again
    assert sh(clone, "symbolic-ref", "--short", "HEAD") == "main"
    assert "change" in hub_repos.hub.read_only_line(ADDRESS)
    before = clone_log(hub_repos)
    r = save(hub_repos)
    hub_repos.hub.commits.settle()
    assert r.status == 403
    assert clone_log(hub_repos) == before
    assert (clone / "docs/plan.md").read_text(encoding="utf-8").endswith("with a change nobody saved.\n")


def dev_changes_the_plan(hub_repos, tmp_path):
    work = tmp_path / "work-dev-plan"
    subprocess.run(["git", "clone", "-q", str(hub_repos.origin), str(work)], check=True, capture_output=True)
    sh(work, "config", "user.name", "Dee Dev")
    sh(work, "config", "user.email", "dee@example.com")
    sh(work, "checkout", "-q", "-b", "dev", "origin/main")
    (work / "docs/plan.md").write_text("# Plan\n\nA plan, as dev has it.\n", encoding="utf-8")
    sh(work, "commit", "-q", "-am", "dev's plan")
    sh(work, "push", "-q", "origin", "dev")


@NAMED
def test_a_save_racing_the_switch_of_the_clone_is_held_and_never_carried_onto_the_new_branch(hub_repos, tmp_path):
    served(hub_repos)                                                      # on staging: the repo has no dev yet
    clone = the_clone(hub_repos)
    assert sh(clone, "symbolic-ref", "--short", "HEAD") == "staging"
    text = hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8")
    dev_changes_the_plan(hub_repos, tmp_path)
    sh(clone, "fetch", "-q", "origin")
    repos, real, raced = hub_repos.hub.repos, hub_repos.hub.repos._git, {}

    def git(at, *args, **kw):
        if args and args[0] == "checkout":                                 # the move of the files: a save now
            def go():
                raced["answer"] = save(hub_repos)
            raced["thread"] = t = threading.Thread(target=go)
            t.start()
            t.join(1.0)
            raced["held"] = t.is_alive() and "saved" not in (clone / "docs/plan.md").read_text(encoding="utf-8")
        return real(at, *args, **kw)
    repos._git = git
    assert repos.switch(REPO, "dev", "ghs_faketoken") == ""                # a save that began while the page was writable
    raced["thread"].join(30)
    hub_repos.hub.commits.settle()
    assert raced["held"], "the save wrote the page while the clone's files were being moved"
    assert sh(clone, "symbolic-ref", "--short", "HEAD") == "dev"
    assert remote_commits(hub_repos, "staging") == []                      # not on the branch it was made on
    dev = sh(hub_repos.origin, "log", "--format=%an|%s", "main..dev").splitlines()
    assert raced["answer"].status == 403        # read on staging, it reached the page's lock after the move: refused
    assert dev == ["Dee Dev|dev's plan"] and sh(hub_repos.origin, "show", "dev:docs/plan.md").endswith("as dev has it.")


@DEV
def test_a_clone_command_asks_for_the_token_once_a_call_and_never_keeps_it(hub_repos):
    served(hub_repos)
    asked, here, real = [], threading.local(), commits_mod._git

    def git(root, *args, **kw):
        here.cmd = args[0]
        try:
            return real(root, *args, **kw)
        finally:
            here.cmd = None
    given = hub_repos.app.token
    hub_repos.app.token = lambda repo: (asked.append(getattr(here, "cmd", None)), given(repo))[1]
    commits_mod._git, was = git, commits_mod._git
    try:
        assert save(hub_repos).status == 200
        hub_repos.hub.commits.settle()
    finally:
        commits_mod._git = was
    assert {"fetch", "push"} <= set(asked) and set(asked) - {"fetch", "push"}, asked    # a lazy blob fetch can come from any command
    assert len(remote_commits(hub_repos, "dev")) == 1


@DEV
def test_every_git_call_in_a_clone_gets_the_token_in_its_environment(hub_repos):
    """A blobless clone fetches missing blobs from any command (`read-tree`, `merge-tree`, ...): every git command run in
    the clone, or a folder of it, gets the credential for that one call (SPEC 14)."""
    served(hub_repos)
    clone = the_clone(hub_repos)
    for args in (("read-tree", "-m", "-u", "HEAD"), ("merge-tree", "--write-tree", "HEAD", "HEAD"), ("status",), ("log", "-1")):
        seen = {}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(commits_mod.subprocess, "run", lambda argv, **kw: seen.update(env=kw["env"]) or subprocess.CompletedProcess(argv, 0, "", ""))
            commits_mod._git(clone, *args)
        assert seen["env"].get("GIT_CONFIG_KEY_0") == "http.extraHeader", args
        assert HEADER in seen["env"]["GIT_CONFIG_VALUE_0"], args
    seen = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(commits_mod.subprocess, "run", lambda argv, **kw: seen.update(env=kw["env"]) or subprocess.CompletedProcess(argv, 0, "", ""))
        commits_mod._git(clone / "docs", "blame", "x")                     # a folder of the clone is the clone's
    assert HEADER in seen["env"].get("GIT_CONFIG_VALUE_0", "")


@DEV
def test_the_token_each_git_call_gets_is_in_no_file_after_a_save(hub_repos):
    served(hub_repos)
    assert save(hub_repos).status == 200
    hub_repos.hub.commits.settle()
    assert len(remote_commits(hub_repos, "dev")) == 1
    base = hub_repos.hub.repos.base
    for f in (p for p in base.rglob("*") if p.is_file() and "objects" not in p.parts):
        assert b"ghs_faketoken" not in f.read_bytes() and HEADER.encode() not in f.read_bytes(), f


def test_one_helper_names_the_owner_a_report_records_and_the_one_a_page_is_matched_by():
    with_short = proxy_mod.Member(id="id-1", name="Ann", roots=(), short="ann")
    without = proxy_mod.Member(id="id-2", name="Bob", roots=())
    assert visibility.owner_key(with_short) == "ann" and visibility.owner_key(without) == "id-2"
    assert visibility.owner_of({"owner": "id-2"}, [with_short, without]) == [without]
    assert visibility.owner_of({"owner": "Ann"}, [with_short, without]) == [with_short]


@DEV
def test_a_member_with_no_short_name_who_reported_a_page_can_open_it(hub_repos):
    members = hub_repos.hub.proxy.members
    members[BEA] = dataclasses.replace(members[BEA], short="")
    served(hub_repos)
    assert hub_repos.get(f"/{ADDRESS}", member=BEA).status == 200
    assert hub_repos.get(f"/{ADDRESS}", member=CAL).status in (403, 404)


# ── round 4: create, the sparse set, the credentials ─────────────────────────

@NEITHER
def test_a_create_in_a_read_only_clone_is_refused_for_a_token_bound_to_nobody_and_for_a_member(hub_repos):
    served(hub_repos)
    hub_repos.tokens["loose"] = Tokens().add("loose", write=True)
    clone = the_clone(hub_repos)
    before = (sh(hub_repos.origin, "rev-list", "--count", "main"), sh(clone, "rev-list", "--count", "HEAD"))
    for who in ("loose", "bea-claude"):
        bad, said = door_call(hub_repos, who, "create", doc=f"{root_name(REPO)}/docs/new.md", text="# New\n")
        assert bad, (who, said)
        assert not (clone / "docs" / "new.md").exists(), who
    hub_repos.hub.commits.settle()
    assert (sh(hub_repos.origin, "rev-list", "--count", "main"), sh(clone, "rev-list", "--count", "HEAD")) == before


@DEV
def test_every_sparse_checkout_change_runs_under_the_clones_commit_lock(hub_repos, tmp_path):
    """The clone's files move only under the commit lock `Commits.moved` and `_pull` take (SPEC 14): a widen, a sleep and
    a wake each hold it for the `git sparse-checkout` they run."""
    repos, now = hub_repos.hub.repos, [1_000_000.0]
    repos.clock = lambda: now[0]                                    # the clone is dated by this clock
    served(hub_repos)
    clone = the_clone(hub_repos)
    lock, real, unlocked = hub_repos.hub.commits._repo_lock(clone), repos._git, []

    def git(at, *args, **kw):
        if "sparse-checkout" in args and args[-1] != "list" and os.path.realpath(at) == os.path.realpath(clone):
            if lock.acquire(blocking=False):        # nobody holds it: the change runs outside the lock
                lock.release()
                unlocked.append(args)
        return real(at, *args, **kw)
    repos._git = git
    assert not report(hub_repos, path="notes/idea.md")[0]           # a folder the set lacks: widened
    now[0] += 31 * 86400
    assert repos.sleep_idle() == [REPO]                             # shrunk
    assert not report(hub_repos, path="docs/plan.md")[0]            # the folders come back: woken
    assert sh(clone, "sparse-checkout", "list").split() == ["docs", "notes"]
    assert unlocked == []


def test_the_credential_of_a_clone_is_read_from_a_copy_of_the_shared_dict(tmp_path, monkeypatch):
    """A clone's first serve adds a key to `CREDENTIALS` from its own thread while a commit or pull thread looks one up."""
    shared = {}

    class Key(str):
        def __eq__(self, other):
            shared.setdefault("/added/by/a/serving/thread", lambda: "t")      # the dict changes under the loop
            return str.__eq__(self, other)
        __hash__ = str.__hash__

    shared[Key("/a/clone")] = lambda: "one"
    shared[Key("/b/clone")] = lambda: "two"
    monkeypatch.setattr(commits_mod, "CREDENTIALS", shared)
    assert commits_mod._credential(tmp_path / "not-a-clone") is None


def test_a_member_whose_id_is_anothers_short_name_does_not_own_that_members_pages(box, rectoversos):
    """The hole round 1's fix (e) opened: the owner of a page matched a short name or, for a member with none, an id, so
    a member with id `nell` and no short name owned the pages of the member whose short name is `Nell`. That config no
    longer starts a hub; were it read, the member could not open or Share the page."""
    doc = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    doc.write_text("---\nowner: nell\n---\n" + doc.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        box.hub.proxy = proxy_mod.parse({
            "origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock", "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
            "members": {CAL: {"name": "Nell Y", "short": "Nell", "roots": [str(rectoversos)]},
                        "nell": {"name": "Nell X", "roots": [str(rectoversos)]}}}, "the test")
    except proxy_mod.ProxyError:
        return                                  # refused at the parse: no hub starts with it
    text = doc.read_text(encoding="utf-8")
    got = box.post("/_/share", {"doc": DOC, "hash": md_hash(text)}, member="nell")
    assert got.status != 200 and doc.read_text(encoding="utf-8") == text


# ── a write to a sleeping clone wakes it first ───────────────────────────────

def asleep(hub_repos):
    """The clone made by a report, its page opened, and thirty-one days without use: its folders are out of the work tree."""
    repos, now = hub_repos.hub.repos, [1_000_000.0]
    repos.clock = lambda: now[0]
    text = served(hub_repos)
    assert hub_repos.get(f"/{ADDRESS}", member=BEA).status == 200       # the page is open: the hub holds its entry
    now[0] += 31 * 86400
    assert repos.sleep_idle() == [REPO]
    assert not hub_repos.hub.file(ADDRESS).exists()
    return text


@DEV
def test_a_save_on_a_sleeping_clones_page_wakes_the_clone_and_commits_on_dev(hub_repos):
    text = asleep(hub_repos)
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("A plan"))
    r = hub_repos.post("/_/save", {"doc": ADDRESS, "hash": md_hash(text), "branch": "dev",
                                   "edits": [{"i": i, "html": "<p>A plan, saved on the page.</p>"}]}, member=BEA)
    assert r.status == 200, r.text
    assert not hub_repos.hub.repos.sleeping(REPO)
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8").endswith("A plan, saved on the page.\n")
    assert remote_commits(hub_repos, "dev") == ["Bea|edit: docs/plan.md"]


@DEV
def test_a_door_update_on_a_sleeping_clones_page_wakes_the_clone_and_commits_on_dev(hub_repos):
    text = asleep(hub_repos)
    bad, said = door_call(hub_repos, "bea-claude", "update", doc=ADDRESS, expected_hash=md_hash(text),
                          text=text + "\nA line the door added.\n")
    assert not bad, said
    assert not hub_repos.hub.repos.sleeping(REPO)
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8").endswith("A line the door added.\n")
    assert len(remote_commits(hub_repos, "dev")) == 1


@DEV
def test_a_write_to_a_clone_that_moved_to_another_tiroir_does_not_wake_it(hub_repos):
    text = served(hub_repos)
    assert hub_repos.hub.repos.sleep_moved(REPO, "https://there.example")
    hub_repos.post("/_/save", {"doc": ADDRESS, "hash": md_hash(text), "branch": "dev",       # whatever the answer: it stays asleep
                               "edits": [{"i": 1, "html": "<p>A plan, saved on the page.</p>"}]}, member=BEA)
    assert hub_repos.hub.repos.sleeping(REPO) and hub_repos.hub.repos.moved_to(REPO) == "https://there.example"


@DEV
def test_a_door_update_by_a_member_who_does_not_own_the_page_wakes_nothing(hub_repos):
    text = asleep(hub_repos)
    bad, said = door_call(hub_repos, "cal-claude", "update", doc=ADDRESS, expected_hash=md_hash(text), text=text + "\nx\n")
    assert bad, said
    assert hub_repos.hub.repos.sleeping(REPO)
    assert not hub_repos.hub.file(ADDRESS).exists()


@DEV
def test_a_clone_awake_by_its_flag_but_with_its_folders_out_is_widened_by_a_write(hub_repos):
    """A write that came while the clone went to sleep (or a widen that failed) leaves the flag awake and `restore` pending:
    the next write must still bring the folders back."""
    text = asleep(hub_repos)
    hub_repos.hub.repos._use(REPO)                  # awake by its flag; the folders are still out, `restore` is kept
    assert not hub_repos.hub.repos.sleeping(REPO) and not hub_repos.hub.file(ADDRESS).exists()
    bad, said = door_call(hub_repos, "bea-claude", "update", doc=ADDRESS, expected_hash=md_hash(text), text=text + "\nA line.\n")
    assert not bad, said
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8").endswith("A line.\n")


@DEV
def test_a_door_update_naming_a_sleeping_clones_page_by_its_url_wakes_it(hub_repos):
    text = asleep(hub_repos)
    bad, said = door_call(hub_repos, "bea-claude", "update", doc=hub_repos.hub.url(ADDRESS), expected_hash=md_hash(text),
                          text=text + "\nA line.\n")
    assert not bad, said
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8").endswith("A line.\n")


@DEV
def test_a_clone_going_to_sleep_records_what_to_restore_under_the_lock_of_the_shrink(hub_repos, monkeypatch):
    """The record of `restore` is made while the clone's lock is held, so a write that takes the lock sees the folders gone
    and the record together."""
    repos, held, seen = hub_repos.hub.repos, [0], []
    real, real_write = repos.holding, repos_mod.write_text_atomic

    class Counting:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            held[0] += 1
            return self.inner.__enter__()

        def __exit__(self, *a):
            held[0] -= 1
            return self.inner.__exit__(*a)

    repos.holding = lambda dest: Counting(real(dest))
    monkeypatch.setattr(repos_mod, "write_text_atomic",
                        lambda path, text, *a, **k: (seen.append(held[0]) if '"restore"' in text else None, real_write(path, text, *a, **k))[1])
    asleep(hub_repos)
    assert seen and all(n > 0 for n in seen), seen


@DEV
def test_the_owner_a_page_names_wakes_the_clone_whatever_the_case_and_the_reporter_does_not_when_another_is_named(hub_repos):
    text = asleep(hub_repos)
    repos = hub_repos.hub.repos
    data = repos._read()
    row = data[REPO]["docs/plan.md"]
    key = row["owner"]
    data[REPO]["docs/plan.md"] = {**row, "owner": "someone-else", "named": key.upper()}
    repos._write(data)
    bad, said = door_call(hub_repos, "bea-claude", "update", doc=ADDRESS, expected_hash=md_hash(text), text=text + "\nA line.\n")
    assert not bad, said
    assert not repos.sleeping(REPO)


@DEV
def test_a_clone_that_is_written_to_is_not_put_to_sleep_thirty_days_after_its_last_report(hub_repos):
    repos, now = hub_repos.hub.repos, [1_000_000.0]
    repos.clock = lambda: now[0]
    text = served(hub_repos)
    now[0] += 29 * 86400
    r = hub_repos.post("/_/save", {"doc": ADDRESS, "hash": md_hash(text), "branch": "dev",
                                   "edits": [{"i": 1, "html": "<p>A plan, saved on the page.</p>"}]}, member=BEA)
    assert r.status == 200, r.text
    now[0] += 29 * 86400
    assert repos.sleep_idle() == []
    assert not repos.sleeping(REPO)


@DEV
def test_a_write_to_an_awake_clone_asks_the_provider_for_no_token(hub_repos, monkeypatch):
    """The token may be a command run on the box: it is asked for only when folders are to come back."""
    served(hub_repos)
    repos, asked = hub_repos.hub.repos, []
    monkeypatch.setattr(repos.provider, "token", lambda repo: asked.append(sys._getframe(1).f_code.co_name) or "ghs_faketoken")
    assert repos.wake(REPO) is True
    assert "wake" not in asked          # other git work of the clone may ask; the wake does not


@DEV
def test_a_clone_that_moves_between_the_check_and_the_lock_is_not_marked_awake_by_a_write(hub_repos, monkeypatch):
    asleep(hub_repos)
    repos = hub_repos.hub.repos
    holding = repos.holding

    @contextlib.contextmanager
    def moved_on_entry(dest):                       # the move lands after `wake` checked, before it holds the lock
        with repos._records:
            data = repos._usage()
            data[REPO] = {**data[REPO], "moved": "https://there.example"}
            repos_mod.write_text_atomic(repos._usage_file, json.dumps(data))
        with holding(dest):
            yield

    monkeypatch.setattr(repos, "holding", moved_on_entry)
    assert repos.wake(REPO) is False
    assert repos.sleeping(REPO) and repos.moved_to(REPO) == "https://there.example"


@DEV
def test_a_clone_a_write_dated_a_moment_ago_is_not_shrunk_by_the_sleep_step_that_checked_before(hub_repos):
    """`sleep_idle` judged the clone idle outside the lock; a write took the lock first and dated a use. The shrink that
    follows re-reads the date under the lock and leaves the folders where they are."""
    served(hub_repos)
    repos = hub_repos.hub.repos
    assert repos.wake(REPO) is True
    slept = []
    repos._sleep_one(REPO, repos.clone_dir(REPO), slept)
    assert slept == [] and hub_repos.hub.file(ADDRESS).exists()
    assert not repos.sleeping(REPO)


@DEV
def test_the_owner_of_a_sleeping_clones_page_reads_it_with_the_editor_and_the_line_says_a_write_wakes_it(hub_repos):
    """The page a tab holds (`_fresh_meta`, which a mount and a reload send) of a clone that went to sleep."""
    hub = hub_repos.hub
    h = md_hash(served(hub_repos))
    e, bea = hub.entry(ADDRESS), hub.proxy.members.get(BEA)
    asleep(hub_repos)
    meta = hub._fresh_meta(e, {"hash": h, "branch": "dev"}, bea)
    assert not meta.get("readonly") and meta.get("branch") == "dev", meta
    line = hub.read_only_line(ADDRESS)                      # whoever may not wake it reads the line
    assert "asleep" in line and "write" in line, line


@DEV
def test_a_refused_sessions_report_on_a_clone_page_dates_no_use_and_wakes_nothing(hub_repos):
    """A clone page is never a rectoverso (the report's own check refuses it), so the route has nothing to wake: a refused
    report neither wakes the clone nor dates a use of it."""
    asleep(hub_repos)
    repos = hub_repos.hub.repos
    dated = repos._usage()[REPO]["last_used"]
    r = hub_repos.post("/_/sessions", {"doc": ADDRESS, "id": "7b0c1c2e-3d4f-4a5b-8c6d-9e0f1a2b3c4d", "machine": "bea-mac"},
                       member=BEA)
    assert r.status == 404, r.text
    assert repos.sleeping(REPO) and repos._usage()[REPO]["last_used"] == dated


@DEV
def test_a_fresh_get_of_a_sleeping_clones_page_by_its_owner_wakes_the_clone_and_serves_the_editor(hub_repos):
    asleep(hub_repos)
    r = hub_repos.get(f"/{ADDRESS}", member=BEA)
    assert r.status == 200, r.text
    assert "A plan." in r.text and '"branch": "dev"' in r.text
    assert not hub_repos.hub.repos.sleeping(REPO) and hub_repos.hub.file(ADDRESS).exists()


@SHARED
def test_a_fresh_get_of_a_sleeping_clones_page_by_another_member_says_it_sleeps_and_never_wakes_it(hub_repos):
    """Cal may see the page (`visibility: project`) but is not its owner: no 404 for a page that exists, no wake."""
    asleep(hub_repos)
    r = hub_repos.get(f"/{ADDRESS}", member=CAL)
    assert r.status == 503 and "asleep" in r.text and REPO in r.text, (r.status, r.text)
    assert hub_repos.hub.repos.sleeping(REPO) and not hub_repos.hub.file(ADDRESS).exists()


@DEV
def test_a_fresh_get_of_a_sleeping_clones_page_a_member_may_not_see_is_still_a_404(hub_repos):
    """The page is Bea's alone (no `visibility`): Cal is told nothing of it, asleep or not."""
    asleep(hub_repos)
    assert hub_repos.get(f"/{ADDRESS}", member=CAL).status == 404
    assert hub_repos.hub.repos.sleeping(REPO)


@DEV
def test_a_fresh_get_of_a_page_a_sleeping_clone_does_not_hold_is_a_404(hub_repos):
    asleep(hub_repos)
    assert hub_repos.get(f"/{root_name(REPO)}/docs/nothing.md", member=BEA).status == 404


@DEV
def test_a_door_reply_or_resolve_by_a_read_only_token_on_a_sleeping_clone_says_the_clone_sleeps(hub_repos, rectoversos):
    """Bea's own token that may not write: the page is hers, so she is told why it is not there, and nothing wakes."""
    asleep(hub_repos)
    hub_repos.tokens["bea-ro"] = Tokens().add("bea-ro", write=False)
    hub_repos.hub.proxy = proxy_mod.parse({
        "origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock", "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
        "members": {BEA: {"name": "Bea", "short": "bea", "roots": [str(rectoversos)], "tokens": ["bea-claude", "bea-ro"]},
                    CAL: {"name": "Cal", "short": "cal", "roots": [str(rectoversos)], "tokens": ["cal-claude"]}}}, "the test")
    for tool, args in (("resolve", {"id": "c1"}), ("reply", {"id": "c1", "text": "x"})):
        bad, said = door_call(hub_repos, "bea-ro", tool, doc=ADDRESS, **args)
        assert bad and "asleep" in said and REPO in said and "no document" not in said.lower(), (tool, said)
        assert hub_repos.hub.repos.sleeping(REPO), tool


@DEV
def test_a_door_call_on_a_sleeping_clones_page_by_a_token_that_may_not_see_it_says_no_such_document(hub_repos):
    asleep(hub_repos)
    bad, said = door_call(hub_repos, "cal-claude", "resolve", doc=ADDRESS, id="c1")
    assert bad and "no document" in said.lower() and "asleep" not in said, said


@DEV
def test_a_door_reply_or_resolve_by_a_token_that_may_not_write_wakes_nothing(hub_repos):
    asleep(hub_repos)
    hub_repos.tokens["ro"] = Tokens().add("ro", write=False)
    for tool, args in (("resolve", {"id": "c1"}), ("reply", {"id": "c1", "text": "x"})):
        door_call(hub_repos, "ro", tool, doc=ADDRESS, **args)           # refused, whatever the words
        assert hub_repos.hub.repos.sleeping(REPO), tool


# ── round 6: a save lands only on the branch it was read on ──────────────────

@NAMED
def test_a_save_read_on_one_branch_is_refused_once_the_clone_is_on_another_and_merges_nothing(hub_repos, tmp_path):
    """Read on staging, the clone then moved to dev, the save reaches the page's lock: refused as a read-only page is
    (403), nothing merged into dev's text, nothing committed on either branch. Deterministic: the switch is done first."""
    served(hub_repos)
    clone = the_clone(hub_repos)
    assert sh(clone, "symbolic-ref", "--short", "HEAD") == "staging"
    dev_changes_the_plan(hub_repos, tmp_path)
    sh(clone, "fetch", "-q", "origin")
    assert hub_repos.hub.repos.decide(REPO, "ghs_faketoken")[0] == "dev"      # as a report decides it, then moves the clone
    assert hub_repos.hub.repos.switch(REPO, "dev", "ghs_faketoken") == ""
    on_dev = (clone / "docs/plan.md").read_text(encoding="utf-8")
    assert "as dev has it" in on_dev
    r = save(hub_repos, branch="staging")
    assert r.status == 403 and "staging" in r.text and "dev" in r.text, r.text
    hub_repos.hub.commits.settle()
    assert (clone / "docs/plan.md").read_text(encoding="utf-8") == on_dev
    assert sh(clone, "status", "--porcelain", "--untracked-files=no") == ""
    assert remote_commits(hub_repos, "staging") == []
    assert sh(hub_repos.origin, "log", "--format=%an|%s", "main..dev").splitlines() == ["Dee Dev|dev's plan"]
    assert save(hub_repos, branch="dev").status == 200          # read on dev, it lands there


@DEV
def test_a_save_that_names_no_branch_on_a_clone_page_is_refused_and_writes_nothing(hub_repos):
    served(hub_repos)
    before = hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8")
    r = save(hub_repos, branch="")
    assert r.status == 400 and "branch" in r.text, r.text
    assert hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8") == before
    assert remote_commits(hub_repos, "dev") == []


@DEV
def test_the_page_of_a_clone_carries_the_branch_it_was_read_on(hub_repos):
    served(hub_repos)
    assert '"branch": "dev"' in hub_repos.get(f"/{ADDRESS}", member=BEA).text


@DEV
def test_a_sleeping_clones_read_only_line_names_the_sleeping_state_and_the_wake_clears_it(hub_repos):
    repos, now = hub_repos.hub.repos, [1_000_000.0]
    repos.clock = lambda: now[0]
    served(hub_repos)
    assert hub_repos.hub.read_only_line(ADDRESS) == ""
    now[0] += 31 * 86400
    assert repos.sleep_idle() == [REPO]
    line = hub_repos.hub.read_only_line(ADDRESS)
    assert "asleep" in line and REPO in line, line
    assert not report(hub_repos, path="docs/plan.md")[0]
    assert hub_repos.hub.read_only_line(ADDRESS) == ""


# ── round 7: the moved line, and the branch of the render ────────────────────

@DEV
def test_a_moved_clones_read_only_line_says_the_repo_moved_and_does_not_promise_a_wake(hub_repos):
    served(hub_repos)
    there = "https://there.example"
    assert hub_repos.hub.repos.sleep_moved(REPO, there)
    assert hub_repos.hub.repos.sleeping(REPO)
    line = hub_repos.hub.read_only_line(ADDRESS)
    assert "moved" in line and there in line, line
    assert "wakes" not in line and "asleep" not in line, line


def meta_branch(hub_repos):
    """The `branch` the page's meta carries as the hub serves the page now (None: it carries none), and its hash."""
    page = hub_repos.get(f"/{ADDRESS}", member=BEA).text
    m = re.search(r'"branch": ("[^"]*"|null)', page)
    return (json.loads(m.group(1)) if m else None), re.search(r'"hash": "([0-9a-f]+)"', page).group(1)


def the_page_moves_to_dev(hub_repos, tmp_path, identical):
    """A report's work: `dev` appears on the remote (with the same pages when `identical`), is decided and the clone moves."""
    if identical:
        push_branch(hub_repos.origin, tmp_path, "dev")
    else:
        dev_changes_the_plan(hub_repos, tmp_path)
    sh(the_clone(hub_repos), "fetch", "-q", "origin")
    assert hub_repos.hub.repos.decide(REPO, "ghs_faketoken")[0] == "dev"
    assert hub_repos.hub.repos.switch(REPO, "dev", "ghs_faketoken") == ""


@NAMED
def test_a_page_identical_on_both_branches_is_saveable_on_dev_after_a_switch_and_a_reload(hub_repos, tmp_path):
    """The file does not change in the switch, so no render is made again: the page must still be sent as read on dev."""
    served(hub_repos)
    assert meta_branch(hub_repos)[0] == "staging"
    the_page_moves_to_dev(hub_repos, tmp_path, identical=True)
    branch, h = meta_branch(hub_repos)             # the reload
    assert branch == "dev"
    r = hub_repos.post("/_/save", {"doc": ADDRESS, "hash": h, "branch": branch,
                                   "edits": [{"i": 1, "html": "<p>A plan, saved on the page.</p>"}]}, member=BEA)
    assert r.status == 200, r.text


@NEITHER
def test_a_page_rendered_read_only_is_saveable_once_the_clone_reaches_the_save_branch_and_the_page_is_reloaded(hub_repos, tmp_path):
    served(hub_repos)
    assert "readonly" in hub_repos.get(f"/{ADDRESS}", member=BEA).text
    the_page_moves_to_dev(hub_repos, tmp_path, identical=True)
    page = hub_repos.get(f"/{ADDRESS}", member=BEA).text
    assert '"readonly"' not in page, page
    branch, h = meta_branch(hub_repos)
    assert branch == "dev"
    r = hub_repos.post("/_/save", {"doc": ADDRESS, "hash": h, "branch": branch,
                                   "edits": [{"i": 1, "html": "<p>A plan, saved on the page.</p>"}]}, member=BEA)
    assert r.status == 200, r.text


@NAMED
def test_a_mounted_page_reads_its_hash_and_its_branch_from_one_render_whatever_the_clone_does_between(hub_repos, tmp_path):
    """The hash and the branch are one read (`live.current_read`): a switch between that read and the build of the mount
    answer gives the hash of staging's text with staging's name, never dev's."""
    served(hub_repos)
    e = hub_repos.hub.entry(ADDRESS)
    old_hash = md_hash(hub_repos.hub.file(ADDRESS).read_text(encoding="utf-8"))
    dev_changes_the_plan(hub_repos, tmp_path)
    sh(the_clone(hub_repos), "fetch", "-q", "origin")
    assert hub_repos.hub.repos.decide(REPO, "ghs_faketoken")[0] == "dev"
    assert hub_repos.hub.repos.switch(REPO, "dev", "ghs_faketoken") == ""
    got = hub_repos.hub.mount_doc(e)["config"]        # no catch_up: the entry's render is staging's
    assert (got["hash"], got["branch"]) == (old_hash, "staging"), got


@DEV
def test_the_reason_a_switch_failed_is_not_shown_for_another_save_branch(hub_repos, monkeypatch):
    broken_checkout(hub_repos)
    served(hub_repos)
    assert "could not be moved" in hub_repos.hub.read_only_line(ADDRESS)
    real = hub_repos.hub.repos.saves_on
    monkeypatch.setattr(hub_repos.hub.repos, "saves_on", lambda repo: ("release", "") if repo == REPO else real(repo))
    line = hub_repos.hub.read_only_line(ADDRESS)
    assert "could not be moved" not in line and "release" in line
