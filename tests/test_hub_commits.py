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

DOC = "sheaves/klium/blog/2026-10-28-plan.md"


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
    """A clone of `remote` that commits and pushes, with one sheaf, `klium/blog/2026-10-28-plan.md`,
    and its project in `projects.toml`. Committed and pushed as the box's first commit would be."""
    repo = tmp_path / "sheaves"
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "the box")
    git(repo, "config", "user.email", "box@example.com")
    (repo / ".sheaf.toml").write_text('versions = "root"\ncommit = true\npush = true\n', encoding="utf-8")
    (repo / "projects.toml").write_text('[projects."klium/blog"]\nmembers = ["bea"]\nstatus = "live"\n',
                                        encoding="utf-8")
    doc = repo / "klium" / "blog" / "2026-10-28-plan.md"
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
    hub.roots.for_document(sheaves / "klium" / "blog" / "2026-10-28-plan.md")
    return Front(hub, browser.handler)


def edit(box, sheaves, member=BEA, words="Second, edited on the page."):
    f = sheaves / "klium" / "blog" / "2026-10-28-plan.md"
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
    assert "klium/blog/2026-10-28-plan.md" in files
    assert any(f.startswith(".sheaf/versions/") for f in files)
    assert "Second, edited on the page." in git(remote, "show", "main:klium/blog/2026-10-28-plan.md")


def test_a_comment_is_a_commit_too_and_a_member_without_an_email_gets_one_at_the_fronts_host(box, sheaves, remote):
    f = sheaves / "klium" / "blog" / "2026-10-28-plan.md"
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("First"))
    r = box.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text), "block": i, "start": 0,
                                "end": 5, "quote": "First", "body": "Is this right?"}, member=CAL)
    assert r.status == 200, r.text
    (who, files), _ = pushed(box, remote)
    assert who.startswith(f"Cal <{CAL}@chat.example.com>|")
    assert "klium/blog/2026-10-28-plan.md" in files


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
    stray = sheaves / "tribeloo" / "launch" / "2026-10-28-brief.md"
    stray.parent.mkdir(parents=True)
    stray.write_text(PLAN, encoding="utf-8")
    (sheaves / "README.md").write_text("# The sheaves\n", encoding="utf-8")      # the top: no project
    assert box.get("/_/index.json").status == 200
    assert box.get("/_/index.json").status == 200
    got = rows("project-unlisted")
    assert [(r["root"], r["folder"]) for r in got] == [("sheaves", "tribeloo/launch")]
    err = capsys.readouterr().err
    assert err.count("tribeloo/launch") == 1 and "projects.toml" in err


def test_a_projects_toml_that_cannot_be_read_is_a_warning_and_lists_as_before(box, sheaves):
    (sheaves / "projects.toml").write_text('[projects."klium/blog"]\nmembers = ["bea"]\nstatus = "maybe"\n', encoding="utf-8")
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
    f = sheaves / "klium" / "blog" / "2026-10-28-plan.md"
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
    assert who.startswith("Claude <box@example.com>|") and "klium/blog/2026-10-28-plan.md" in files


def test_a_root_that_does_not_commit_makes_no_commit(box, sheaves, remote):
    (sheaves / ".sheaf.toml").write_text('versions = "root"\n', encoding="utf-8")
    edit(box, sheaves)
    assert len(pushed(box, remote)) == 1
    assert "2026-10-28-plan.md" in git(sheaves, "status", "--porcelain")
