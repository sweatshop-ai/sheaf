"""A root that commits (SPEC 4.4 `commit`, `push`, `versions`; 8.11): every write on the page is one git
commit authored by whoever made it, pushed to the root's remote, with the document's versions kept inside
the root (`.sheaf/versions/`) and committed with it; the hub never serves `.sheaf/`; a sheaf folder that
`projects.toml` does not name is a warning. Through the handler in proxy mode, with a git repo as the root
and a bare repo as its remote."""
import os
import subprocess

import pytest
from helpers import BEA, CAL, FRONT, Front, PLAN

from sheafmd.blocks import split_md_blocks
from sheafmd.hub import proxy
from sheafmd.source import md_hash

DOC = "sheaves/acme/blog/2026-10-28-plan.md"


def git(at, *args):
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def remote(tmp_path):
    r = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(r)], check=True)
    return r


@pytest.fixture
def sheaves(tmp_path, remote):
    """A clone of `remote` that commits and pushes, with one sheaf, `acme/blog/2026-10-28-plan.md`,
    and its project in `projects.toml`. Committed and pushed as the box's first commit would be."""
    repo = tmp_path / "sheaves"
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "the box")
    git(repo, "config", "user.email", "box@example.com")
    (repo / ".sheaf.toml").write_text('versions = "root"\ncommit = true\npush = true\n', encoding="utf-8")
    (repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["bea"]\nstatus = "live"\n',
                                        encoding="utf-8")
    doc = repo / "acme" / "blog" / "2026-10-28-plan.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(PLAN, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    git(repo, "push", "-q", "origin", "HEAD:main")
    return repo


@pytest.fixture
def box(hub, browser, sheaves, other):
    """The hub in proxy mode with the sheaves repo as Bea's root; Bea's e-mail is in her member block,
    Cal has none."""
    import pwd
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                             "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "members": {BEA: {"name": "Bea", "email": "bea@example.com",
                                               "roots": [str(sheaves)]},
                                         CAL: {"name": "Cal", "roots": [str(sheaves)]}}}, "the test")
    hub.roots.for_document(sheaves / "acme" / "blog" / "2026-10-28-plan.md")
    return Front(hub, browser.handler)


def edit(box, sheaves, member=BEA, words="Second, edited on the page."):
    f = sheaves / "acme" / "blog" / "2026-10-28-plan.md"
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Second"))
    r = box.post("/_/save", {"doc": DOC, "hash": md_hash(text), "edits": [{"i": i, "html": f"<p>{words}</p>"}]},
                 member=member)
    assert r.status == 200, r.text
    return r


def pushed(box, remote):
    """The remote's commits, newest first, as `author name <email>|subject|files`, once the hub's
    commits have gone out."""
    box.hub.commits.settle()
    out = []
    for sha in git(remote, "rev-list", "main").split():
        who = git(remote, "log", "-1", "--format=%an <%ae>|%s", sha).strip()
        files = git(remote, "show", "--name-only", "--format=", sha).split()
        out.append((who, files))
    return out


def test_a_members_save_is_one_commit_on_the_remote_under_their_name(box, sheaves, remote):
    edit(box, sheaves)
    commits = pushed(box, remote)
    assert len(commits) == 2
    (who, files) = commits[0]
    assert who.startswith("Bea <bea@example.com>|")
    assert "acme/blog/2026-10-28-plan.md" in files
    assert any(f.startswith(".sheaf/versions/") for f in files)
    assert "Second, edited on the page." in git(remote, "show", "main:acme/blog/2026-10-28-plan.md")


def test_a_comment_is_a_commit_too_and_a_member_without_an_email_gets_one_at_the_fronts_host(box, sheaves, remote):
    f = sheaves / "acme" / "blog" / "2026-10-28-plan.md"
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("First"))
    r = box.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text), "block": i, "start": 0,
                                "end": 5, "quote": "First", "body": "Is this right?"}, member=CAL)
    assert r.status == 200, r.text
    (who, files), _ = pushed(box, remote)
    assert who.startswith(f"Cal <{CAL}@chat.example.com>|")
    assert "acme/blog/2026-10-28-plan.md" in files


def versions_files(sheaves):
    return sorted(p.relative_to(sheaves).as_posix() for p in (sheaves / ".sheaf").rglob("*.md"))


def test_the_versions_folder_is_never_served(box, browser, sheaves):
    edit(box, sheaves)
    kept = versions_files(sheaves)
    assert kept, "the save kept a version inside the root"
    for rel in kept:
        assert box.get(f"/sheaves/{rel}").status == 404, rel
        assert box.get(f"/_/doc?doc=sheaves/{rel}").status == 404, rel
        assert browser.get(f"/sheaves/{rel}").status == 404, rel
    docs = [d["doc"] for r in box.get("/_/index.json").json()["roots"] for d in r["docs"]]
    assert docs == [DOC]


def rows(kind):
    from sheafmd import diagnostics
    try:
        lines = diagnostics.log_path().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    import json
    return [r for r in map(json.loads, lines) if r["kind"] == kind]


def test_a_sheaf_folder_projects_toml_does_not_name_is_a_warning_once(box, sheaves, capsys):
    stray = sheaves / "globex" / "launch" / "2026-10-28-brief.md"
    stray.parent.mkdir(parents=True)
    stray.write_text(PLAN, encoding="utf-8")
    (sheaves / "README.md").write_text("# The sheaves\n", encoding="utf-8")      # the top: no project
    assert box.get("/_/index.json").status == 200
    assert box.get("/_/index.json").status == 200
    got = rows("project-unlisted")
    assert [(r["root"], r["folder"]) for r in got] == [("sheaves", "globex/launch")]
    err = capsys.readouterr().err
    assert err.count("globex/launch") == 1 and "projects.toml" in err


def test_a_projects_toml_that_cannot_be_read_is_a_warning_and_lists_as_before(box, sheaves):
    (sheaves / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["bea"]\nstatus = "maybe"\n', encoding="utf-8")
    docs = [d["doc"] for r in box.get("/_/index.json").json()["roots"] for d in r["docs"]]
    assert docs == [DOC]
    (row,) = rows("projects-invalid")
    assert row["root"] == "sheaves" and "status" in row["error"]


def test_a_push_that_fails_is_a_row_the_save_stands_and_the_next_push_carries_it(box, sheaves, remote, tmp_path):
    away = tmp_path / "away.git"
    remote.rename(away)
    edit(box, sheaves)
    assert box.hub.commits.settle()
    (row,) = rows("push-failed")
    assert row["doc"] == DOC and row["error"]
    away.rename(remote)
    edit(box, sheaves, words="Second, edited again.")
    assert [who.split("|")[0] for who, _ in pushed(box, remote)] == ["Bea <bea@example.com>"] * 2 + ["the box <box@example.com>"]


def test_the_hubs_person_saving_through_the_loopback_port_commits_as_the_repo_names_them(box, browser, sheaves, remote):
    f = sheaves / "acme" / "blog" / "2026-10-28-plan.md"
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Second"))
    assert browser.post("/_/save", {"doc": DOC, "hash": md_hash(text),
                                    "edits": [{"i": i, "html": "<p>Second, by the person.</p>"}]}).status == 200
    (who, _), _ = pushed(box, remote)
    assert who.startswith(f"{box.hub.person} <box@example.com>|")


def test_a_door_update_commits_under_the_callers_name(box, browser, sheaves, remote):
    from helpers import call
    is_error, got = call(browser, "read", doc=DOC)
    assert not is_error
    is_error, got = call(browser, "update", as_name="Claude", doc=DOC, text=got["text"] + "\nA line from the door.\n",
                         expected_hash=got["hash"])
    assert not is_error, got
    (who, files), _ = pushed(box, remote)
    assert who.startswith("Claude <box@example.com>|") and "acme/blog/2026-10-28-plan.md" in files


def test_a_root_that_does_not_commit_makes_no_commit(box, sheaves, remote):
    (sheaves / ".sheaf.toml").write_text('versions = "root"\n', encoding="utf-8")
    edit(box, sheaves)
    assert len(pushed(box, remote)) == 1
    assert "2026-10-28-plan.md" in git(sheaves, "status", "--porcelain")


def test_forgetting_the_root_leaves_its_versions_in_it(box, sheaves):
    edit(box, sheaves)
    kept = versions_files(sheaves)
    assert kept
    box.hub.forget_root("sheaves")
    assert versions_files(sheaves) == kept


def test_a_save_that_changes_nothing_commits_nothing_not_even_what_another_hand_left(box, sheaves, remote):
    f = sheaves / "acme" / "blog" / "2026-10-28-plan.md"
    f.write_text(f.read_text(encoding="utf-8") + "\nTyped in an editor, not saved by Bea.\n", encoding="utf-8")
    text = f.read_text(encoding="utf-8")
    r = box.post("/_/save", {"doc": DOC, "hash": md_hash(text), "edits": []}, member=BEA)
    assert r.status == 200, r.text
    assert len(pushed(box, remote)) == 1


def test_a_save_through_a_link_commits_the_document_it_wrote(box, sheaves, remote):
    (sheaves / "acme" / "blog" / "plan.md").symlink_to("2026-10-28-plan.md")
    git(sheaves, "add", "-A")
    git(sheaves, "commit", "-q", "-m", "a link")
    text = (sheaves / "acme" / "blog" / "2026-10-28-plan.md").read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Second"))
    r = box.post("/_/save", {"doc": "sheaves/acme/blog/plan.md", "hash": md_hash(text),
                             "edits": [{"i": i, "html": "<p>Second, through the link.</p>"}]}, member=BEA)
    assert r.status == 200, r.text
    (who, files), *_ = pushed(box, remote)
    assert who.startswith("Bea <bea@example.com>|") and "acme/blog/2026-10-28-plan.md" in files
    assert "through the link" in git(remote, "show", "main:acme/blog/2026-10-28-plan.md")


def test_a_sheaf_toml_that_cannot_be_read_when_the_commit_comes_is_a_row_not_an_error(box, sheaves):
    # The render reads it first and fails the request on its own (8.3); a write whose render went
    # through and whose `.sheaf.toml` broke in between still answers.
    (sheaves / ".sheaf.toml").write_text("commit = [\n", encoding="utf-8")
    box.hub.committed(DOC, by="Claude", what="update")
    (row,) = rows("commit-failed")
    assert row["doc"] == DOC and row["error"]


def test_a_stopping_hub_waits_for_the_push_of_the_last_write(box, sheaves, remote):
    edit(box, sheaves)
    box.hub.stop_jobs()
    assert "Second, edited on the page." in git(remote, "show", "main:acme/blog/2026-10-28-plan.md")


def test_a_link_planted_in_the_versions_store_is_never_written_through(box, sheaves, tmp_path):
    from sheafmd.hub import state
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n", encoding="utf-8")
    folder = sheaves / ".sheaf" / "versions" / state.doc_key("acme/blog/2026-10-28-plan.md")
    folder.mkdir(parents=True)
    (folder / ".address.tmp").symlink_to(victim)
    box.get(f"/{DOC}")
    edit(box, sheaves)
    assert victim.read_text(encoding="utf-8") == "untouched\n"


def test_a_sheaf_folder_that_is_a_link_out_of_the_root_gets_no_versions(box, sheaves, tmp_path):
    away = tmp_path / "away"
    away.mkdir()
    (sheaves / ".sheaf").symlink_to(away)
    box.get(f"/{DOC}")
    try:
        edit(box, sheaves)
    except AssertionError:
        pass
    assert list(away.iterdir()) == []


def test_a_slow_push_does_not_hold_up_the_next_save(box, sheaves, remote):
    import time
    git(sheaves, "config", "remote.origin.receivepack", "sleep 3; git-receive-pack")
    edit(box, sheaves)
    time.sleep(0.5)                                      # the push is under way
    t = time.monotonic()
    edit(box, sheaves, words="Second, edited while it pushed.")
    assert time.monotonic() - t < 2
    assert box.hub.commits.settle()


def test_a_commit_that_fails_leaves_nothing_staged(box, sheaves):
    head = git(sheaves, "rev-parse", "HEAD").strip()
    (sheaves / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")   # a merge under way
    edit(box, sheaves)
    (row,) = rows("commit-failed")
    assert row["doc"] == DOC
    assert git(sheaves, "diff", "--cached", "--name-only") == ""


def test_a_link_into_the_versions_store_is_not_listed(box, sheaves):
    edit(box, sheaves)
    target = next((sheaves / ".sheaf" / "versions").rglob("*.md"))
    (sheaves / "acme" / "blog" / "alias.md").symlink_to(target)
    docs = [d["doc"] for r in box.get("/_/index.json").json()["roots"] for d in r["docs"]]
    assert docs == [DOC]


def test_a_projects_toml_that_cannot_be_read_warns_once_however_it_changes(box, sheaves):
    (sheaves / "projects.toml").write_text('[projects."acme/blog"]\nstatus = "maybe"\n', encoding="utf-8")
    box.get("/_/index.json")
    (sheaves / "projects.toml").write_text('[projects."acme/blog"\n', encoding="utf-8")
    box.get("/_/index.json")
    assert len(rows("projects-invalid")) == 1


def test_a_versions_store_the_repo_ignores_stays_out_and_the_document_is_committed(box, sheaves, remote):
    (sheaves / ".git" / "info" / "exclude").write_text(".sheaf/\n", encoding="utf-8")
    edit(box, sheaves)
    (who, files), _ = pushed(box, remote)
    assert who.startswith("Bea <bea@example.com>|")
    assert files == ["acme/blog/2026-10-28-plan.md"]


def test_a_file_the_repo_ignores_inside_the_versions_folder_is_never_committed(box, sheaves, remote):
    from sheafmd.hub import state
    folder = sheaves / ".sheaf" / "versions" / state.doc_key("acme/blog/2026-10-28-plan.md")
    folder.mkdir(parents=True)
    (folder / "notes.key").write_text("not a version\n", encoding="utf-8")
    (sheaves / ".git" / "info" / "exclude").write_text("*.key\n", encoding="utf-8")
    edit(box, sheaves)
    (who, files), _ = pushed(box, remote)
    assert who.startswith("Bea <bea@example.com>|") and not any(f.endswith(".key") for f in files)


def test_a_commit_that_fails_puts_back_what_was_staged_before(box, sheaves):
    f = sheaves / "acme" / "blog" / "2026-10-28-plan.md"
    original = f.read_text(encoding="utf-8")
    f.write_text(original + "\nStaged by hand, never in the work tree again.\n", encoding="utf-8")
    git(sheaves, "add", "acme/blog/2026-10-28-plan.md")
    f.write_text(original, encoding="utf-8")
    head = git(sheaves, "rev-parse", "HEAD").strip()
    (sheaves / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")
    edit(box, sheaves)
    assert rows("commit-failed")
    assert "Staged by hand" in git(sheaves, "show", ":acme/blog/2026-10-28-plan.md")
    assert git(sheaves, "diff", "--cached", "--name-only") == "acme/blog/2026-10-28-plan.md\n"


def test_a_document_the_repo_ignores_is_never_committed_nor_its_versions(box, sheaves, remote):
    (sheaves / ".git" / "info" / "exclude").write_text("acme/blog/2026-10-28-plan.md\n", encoding="utf-8")
    git(sheaves, "rm", "-q", "--cached", "acme/blog/2026-10-28-plan.md")
    git(sheaves, "commit", "-q", "-m", "a private draft from now on")
    git(sheaves, "push", "-q", "origin", "HEAD:main")
    edit(box, sheaves)
    assert len(pushed(box, remote)) == 2
    assert rows("commit-failed") == []
    assert git(sheaves, "status", "--porcelain", "--", ".sheaf").strip().startswith("??")


def test_a_first_commit_that_fails_leaves_nothing_staged(browser, tmp_path):
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "init", "-q", "-b", "main", str(fresh)], check=True)
    git(fresh, "config", "commit.gpgsign", "true")
    git(fresh, "config", "gpg.program", "false")                # every commit fails
    (fresh / ".sheaf.toml").write_text('commit = true\n', encoding="utf-8")
    doc = fresh / "plan.md"
    doc.write_text(PLAN, encoding="utf-8")
    root = browser.hub.roots.for_document(doc)
    text = doc.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Second"))
    r = browser.post("/_/save", {"doc": f"{root.name}/plan.md", "hash": md_hash(text),
                                 "edits": [{"i": i, "html": "<p>Second, never committed.</p>"}]})
    assert r.status == 200, r.text
    assert rows("commit-failed")
    assert git(fresh, "diff", "--cached", "--name-only") == ""


def test_a_conflict_in_the_index_is_left_as_it_is(box, sheaves):
    f = sheaves / "acme" / "blog" / "2026-10-28-plan.md"
    original = f.read_text(encoding="utf-8")
    git(sheaves, "checkout", "-q", "-b", "other")
    f.write_text(original.replace("Last paragraph.", "Last paragraph, theirs."), encoding="utf-8")
    git(sheaves, "commit", "-q", "-am", "theirs")
    git(sheaves, "checkout", "-q", "-")
    f.write_text(original.replace("Last paragraph.", "Last paragraph, ours."), encoding="utf-8")
    git(sheaves, "commit", "-q", "-am", "ours")
    assert subprocess.run(["git", "-C", str(sheaves), "merge", "-q", "other"], capture_output=True).returncode
    unmerged = git(sheaves, "ls-files", "-u")
    assert unmerged.count("\n") == 3
    edit(box, sheaves)
    (row,) = rows("commit-failed")
    assert row["doc"] == DOC and "conflict" in row["error"]
    assert git(sheaves, "ls-files", "-u") == unmerged
