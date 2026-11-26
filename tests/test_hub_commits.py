"""A root that commits (SPEC 4.4 `commit`, `push`, `versions`; 8.11): every write on the page is one git
commit authored by whoever made it, pushed to the root's remote, with the document's versions kept inside
the root (`.sheaf/versions/`) and committed with it; the hub never serves `.sheaf/`; a rectoverso folder that
`projects.toml` does not name is a warning. Through the handler in proxy mode, with a git repo as the root
and a bare repo as its remote."""
import os
import random
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
from helpers import BEA, CAL, FRONT, Front, PLAN, undecodable_names_or_skip

from sheafmd import signals
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import proxy, the_list
from sheafmd.source import md_hash

DOC = "rectoversos/acme/blog/2026-10-28-plan.md"


def git(at, *args):
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def remote(tmp_path):
    r = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(r)], check=True)
    return r


@pytest.fixture
def rectoversos(tmp_path, remote):
    """A clone of `remote` that commits and pushes, with one rectoverso, `acme/blog/2026-10-28-plan.md`,
    and its project in `projects.toml`. Committed and pushed as the box's first commit would be."""
    repo = tmp_path / "rectoversos"
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "the box")
    git(repo, "config", "user.email", "box@example.com")
    (repo / ".sheaf.toml").write_text('versions = "root"\ncommit = true\npush = true\n', encoding="utf-8")
    (repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["bea", "cal"]\nstatus = "live"\n',
                                        encoding="utf-8")
    doc = repo / "acme" / "blog" / "2026-10-28-plan.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(PLAN, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    git(repo, "push", "-q", "origin", "HEAD:main")
    return repo


@pytest.fixture
def box(hub, browser, rectoversos, other):
    """The hub in proxy mode with the rectoversos repo as Bea's root; Bea's e-mail is in her member block,
    Cal has none."""
    import pwd
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                             "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "members": {BEA: {"name": "Bea", "email": "bea@example.com", "short": "bea",
                                               "roots": [str(rectoversos)]},
                                         CAL: {"name": "Cal", "short": "cal", "roots": [str(rectoversos)]}}}, "the test")
    hub.roots.for_document(rectoversos / "acme" / "blog" / "2026-10-28-plan.md")
    return Front(hub, browser.handler)


def edit(box, rectoversos, member=BEA, words="Second, edited on the page."):
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
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


def test_a_members_save_is_one_commit_on_the_remote_under_their_name(box, rectoversos, remote):
    edit(box, rectoversos)
    commits = pushed(box, remote)
    assert len(commits) == 2
    (who, files) = commits[0]
    assert who.startswith("Bea <bea@example.com>|")
    assert "acme/blog/2026-10-28-plan.md" in files
    assert any(f.startswith(".sheaf/versions/") for f in files)
    assert "Second, edited on the page." in git(remote, "show", "main:acme/blog/2026-10-28-plan.md")


def test_a_comment_is_a_commit_too_and_a_member_without_an_email_gets_one_at_the_fronts_host(box, rectoversos, remote):
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("First"))
    r = box.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text), "block": i, "start": 0,
                                "end": 5, "quote": "First", "body": "Is this right?"}, member=CAL)
    assert r.status == 200, r.text
    (who, files), _ = pushed(box, remote)
    assert who.startswith(f"Cal <{CAL}@chat.example.com>|")
    assert "acme/blog/2026-10-28-plan.md" in files


def versions_files(rectoversos):
    return sorted(p.relative_to(rectoversos).as_posix() for p in (rectoversos / ".sheaf").rglob("*.md"))


def test_the_versions_folder_is_never_served(box, browser, rectoversos):
    edit(box, rectoversos)
    kept = versions_files(rectoversos)
    assert kept, "the save kept a version inside the root"
    for rel in kept:
        assert box.get(f"/rectoversos/{rel}").status == 404, rel
        assert box.get(f"/_/doc?doc=rectoversos/{rel}").status == 404, rel
        assert browser.get(f"/rectoversos/{rel}").status == 404, rel
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


def test_a_sheaf_folder_projects_toml_does_not_name_is_a_warning_once(box, rectoversos, capsys):
    stray = rectoversos / "globex" / "launch" / "2026-10-28-brief.md"
    stray.parent.mkdir(parents=True)
    stray.write_text(PLAN, encoding="utf-8")
    (rectoversos / "README.md").write_text("# The rectoversos\n", encoding="utf-8")      # the top: no project
    assert box.get("/_/index.json").status == 200
    assert box.get("/_/index.json").status == 200
    got = rows("project-unlisted")
    assert [(r["root"], r["folder"]) for r in got] == [("rectoversos", "globex/launch")]
    err = capsys.readouterr().err
    assert err.count("globex/launch") == 1 and "projects.toml" in err


def test_a_projects_toml_that_cannot_be_read_is_a_warning_and_closes_every_project(box, rectoversos):
    """It grants (8.12, #44): one the hub cannot read opens no project to a member, and says why once."""
    (rectoversos / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["bea"]\nstatus = "maybe"\n', encoding="utf-8")
    docs = [d["doc"] for r in box.get("/_/index.json").json()["roots"] for d in r["docs"]]
    assert docs == []
    (row,) = rows("projects-invalid")
    assert row["root"] == "rectoversos" and "status" in row["error"]


def test_a_push_that_fails_is_a_row_the_save_stands_and_the_next_push_carries_it(box, rectoversos, remote, tmp_path):
    away = tmp_path / "away.git"
    remote.rename(away)
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    (row,) = rows("push-failed")
    assert row["doc"] == DOC and row["error"]
    away.rename(remote)
    edit(box, rectoversos, words="Second, edited again.")
    assert [who.split("|")[0] for who, _ in pushed(box, remote)] == ["Bea <bea@example.com>"] * 2 + ["the box <box@example.com>"]


def test_the_hubs_person_saving_through_the_loopback_port_commits_as_the_repo_names_them(box, browser, rectoversos, remote):
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Second"))
    assert browser.post("/_/save", {"doc": DOC, "hash": md_hash(text),
                                    "edits": [{"i": i, "html": "<p>Second, by the person.</p>"}]}).status == 200
    (who, _), _ = pushed(box, remote)
    assert who.startswith(f"{box.hub.person} <box@example.com>|")


def test_a_door_update_commits_under_the_callers_name(box, browser, rectoversos, remote):
    from helpers import call
    is_error, got = call(browser, "read", doc=DOC)
    assert not is_error
    is_error, got = call(browser, "update", as_name="Claude", doc=DOC, text=got["text"] + "\nA line from the door.\n",
                         expected_hash=got["hash"])
    assert not is_error, got
    (who, files), _ = pushed(box, remote)
    assert who.startswith("Claude <box@example.com>|") and "acme/blog/2026-10-28-plan.md" in files


def test_a_root_that_does_not_commit_makes_no_commit(box, rectoversos, remote):
    (rectoversos / ".sheaf.toml").write_text('versions = "root"\n', encoding="utf-8")
    edit(box, rectoversos)
    assert len(pushed(box, remote)) == 1
    assert "2026-10-28-plan.md" in git(rectoversos, "status", "--porcelain")


def test_forgetting_the_root_leaves_its_versions_in_it(box, rectoversos):
    edit(box, rectoversos)
    kept = versions_files(rectoversos)
    assert kept
    box.hub.forget_root("rectoversos")
    assert versions_files(rectoversos) == kept


def test_a_save_that_changes_nothing_commits_nothing_not_even_what_another_hand_left(box, rectoversos, remote):
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    f.write_text(f.read_text(encoding="utf-8") + "\nTyped in an editor, not saved by Bea.\n", encoding="utf-8")
    text = f.read_text(encoding="utf-8")
    r = box.post("/_/save", {"doc": DOC, "hash": md_hash(text), "edits": []}, member=BEA)
    assert r.status == 200, r.text
    assert len(pushed(box, remote)) == 1


def test_a_save_through_a_link_commits_the_document_it_wrote(box, rectoversos, remote):
    (rectoversos / "acme" / "blog" / "plan.md").symlink_to("2026-10-28-plan.md")
    git(rectoversos, "add", "-A")
    git(rectoversos, "commit", "-q", "-m", "a link")
    text = (rectoversos / "acme" / "blog" / "2026-10-28-plan.md").read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Second"))
    r = box.post("/_/save", {"doc": "rectoversos/acme/blog/plan.md", "hash": md_hash(text),
                             "edits": [{"i": i, "html": "<p>Second, through the link.</p>"}]}, member=BEA)
    assert r.status == 200, r.text
    (who, files), *_ = pushed(box, remote)
    assert who.startswith("Bea <bea@example.com>|") and "acme/blog/2026-10-28-plan.md" in files
    assert "through the link" in git(remote, "show", "main:acme/blog/2026-10-28-plan.md")


def test_a_sheaf_toml_that_cannot_be_read_when_the_commit_comes_is_a_row_not_an_error(box, rectoversos):
    # The render reads it first and fails the request on its own (8.3); a write whose render went
    # through and whose `.sheaf.toml` broke in between still answers.
    (rectoversos / ".sheaf.toml").write_text("commit = [\n", encoding="utf-8")
    box.hub.committed(DOC, by="Claude", what="update")
    (row,) = rows("commit-failed")
    assert row["doc"] == DOC and row["error"]


def test_a_stopping_hub_waits_for_the_push_of_the_last_write(box, rectoversos, remote):
    edit(box, rectoversos)
    box.hub.stop_jobs()
    assert "Second, edited on the page." in git(remote, "show", "main:acme/blog/2026-10-28-plan.md")


# ── a stop while git runs (#95) ───────────────────────────────────────────────
# A sleep of its own per test run: another session on the machine running these tests has another.
HANG = f"61.{random.randrange(10 ** 6):06d}"


# `setsid PROGRAM`, which macOS has no command for: a session of its own, then the program
SETSID = shlex.join([sys.executable, "-c", "import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])"])


def hanging(rectoversos):
    """The remote's upload-pack waits first: the pull's fetch hangs as on a remote that drops packets."""
    git(rectoversos, "config", "remote.origin.uploadpack", f"sleep {HANG}; git-upload-pack")


def sleepers() -> list:
    """The pids of the `sleep HANG` processes: from /proc where there is one, from `ps` on macOS."""
    if not Path("/proc/self").is_dir():
        ps = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True, text=True).stdout
        return [int(f[0]) for f in (ln.split() for ln in ps.splitlines()) if f[1:3] == ["sleep", HANG]]
    out = []
    for d in Path("/proc").iterdir():
        try:
            if d.name.isdigit() and (d / "cmdline").read_bytes().split(b"\0")[:2] == [b"sleep", HANG.encode()]:
                out.append(int(d.name))
        except OSError:
            pass
    return out


def until(look, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if got := look():
            return got
        time.sleep(0.05)
    return look()


def test_a_stop_ends_a_fetch_that_hangs_within_its_bound_and_calls_it_stopped_not_failed(box, rectoversos, remote, monkeypatch):
    """#95: an upgrade stop left `push-failed "git exited -15"`, a git the stop itself ended. The hub ends its
    git within a bound it sets, the git's own children with it, and says so as `push-stopped`; the commit stays
    for the next hub's push."""
    from sheafmd.hub import commits
    monkeypatch.setattr(commits, "STOP_SECONDS", 1)
    hanging(rectoversos)
    edit(box, rectoversos)
    assert until(sleepers), "the fetch never started"
    t = time.monotonic()
    box.hub.stop_jobs()
    assert time.monotonic() - t < 1 + 2 * commits.END_GRACE + 1
    assert until(lambda: not sleepers(), 5)
    assert rows("push-failed") == []
    (row,) = rows("push-stopped")
    assert row["doc"] == DOC
    assert git(rectoversos, "rev-parse", "HEAD") != git(remote, "rev-parse", "main")


def test_the_hubs_git_runs_in_a_session_of_its_own(box, rectoversos, monkeypatch):
    """A Ctrl-C at the terminal of a hub run in the foreground goes to its whole group: git is not in it, the hub
    ends it (#95)."""
    from sheafmd.hub import commits
    monkeypatch.setattr(commits, "STOP_SECONDS", 0)
    hanging(rectoversos)
    edit(box, rectoversos)
    (pid,) = until(sleepers)
    assert os.getsid(pid) != os.getsid(0)
    box.hub.stop_jobs()


def test_a_stop_ends_a_fetch_of_the_poll_before_the_fetch_gives_up_on_its_own():
    """A poll's fetch that the stop meets would otherwise time out first and be a `push-failed` (#95)."""
    from sheafmd.hub import commits
    assert commits.STOP_SECONDS < commits.GIT_SECONDS


def test_a_git_that_failed_before_the_stop_signalled_it_is_a_failure_and_one_its_descendant_holds_never_holds_the_pusher(
        monkeypatch):
    """Gate P3-1 and P2-1 of #95: the stop's word goes only to a git it signalled; and a timed-out git whose pipes a
    process outside its group keeps open is given up at its time, as `subprocess.run` gives it up."""
    import signal
    from sheafmd.hub import commits
    kids = commits.Children()
    real = subprocess.Popen.communicate

    def then_the_stop(self, *args, **kw):
        out = real(self, *args, **kw)
        if self.args[:2] == ["sh", "-c"] and self.args[2] == "exit 1":
            kids.end(signal.SIGTERM)                      # the stop comes just after the git failed on its own
        return out
    monkeypatch.setattr(subprocess.Popen, "communicate", then_the_stop)
    assert kids.run(["sh", "-c", "exit 1"], 5, os.environ).returncode == 1
    kids._ended = False
    t = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        kids.run(["sh", "-c", f"{SETSID} sleep {HANG} & sleep 30"], 1, os.environ)
    assert time.monotonic() - t < 4
    for pid in sleepers():
        signals.send(pid, 15)


def test_a_poll_that_meets_a_stopped_hub_with_nothing_owed_writes_no_row(box, rectoversos, monkeypatch):
    from sheafmd.hub import commits
    monkeypatch.setattr(commits, "STOP_SECONDS", 0)
    box.hub.stop_jobs()
    monkeypatch.setattr(commits, "FETCH_SECONDS", 0)
    poll(box)
    assert rows("push-stopped") == [] and rows("push-failed") == []


def test_a_push_that_ends_within_the_stops_bound_goes_out(box, rectoversos, remote, monkeypatch):
    from sheafmd.hub import commits
    monkeypatch.setattr(commits, "STOP_SECONDS", 15)
    git(rectoversos, "config", "remote.origin.receivepack", "sleep 1; git-receive-pack")
    edit(box, rectoversos)
    box.hub.stop_jobs()
    assert git(rectoversos, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert rows("push-stopped") == [] and rows("push-failed") == []


def test_a_push_due_once_the_hub_ended_its_git_starts_no_git(box, rectoversos, remote, monkeypatch):
    """After the stop ended the running git, a push still due is never started: it would run past the bound."""
    from sheafmd.hub import commits
    monkeypatch.setattr(commits, "STOP_SECONDS", 0)
    seen = fetches(monkeypatch)
    box.hub.stop_jobs()
    edit(box, rectoversos)
    assert box.hub.commits.settle(5)
    assert seen == [] and rows("push-failed") == []
    (row,) = rows("push-stopped")
    assert row["doc"] == DOC


def test_a_link_planted_in_the_versions_store_is_never_written_through(box, rectoversos, tmp_path):
    from sheafmd.hub import state
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n", encoding="utf-8")
    folder = rectoversos / ".sheaf" / "versions" / state.doc_key("acme/blog/2026-10-28-plan.md")
    folder.mkdir(parents=True)
    (folder / ".address.tmp").symlink_to(victim)
    box.get(f"/{DOC}")
    edit(box, rectoversos)
    assert victim.read_text(encoding="utf-8") == "untouched\n"


def test_a_sheaf_folder_that_is_a_link_out_of_the_root_gets_no_versions(box, rectoversos, tmp_path):
    away = tmp_path / "away"
    away.mkdir()
    (rectoversos / ".sheaf").symlink_to(away)
    box.get(f"/{DOC}")
    try:
        edit(box, rectoversos)
    except AssertionError:
        pass
    assert list(away.iterdir()) == []


def test_a_slow_push_does_not_hold_up_the_next_save(box, rectoversos, remote, tmp_path):
    # The push is held at a gate the test opens, not timed: a save is some 16 git runs in a row, and on a
    # loaded macOS runner (ticket 173 S, run 45262482442) they alone took 3.9 s, over a bound of 2 s.
    import threading
    started, gate = tmp_path / "push-started", tmp_path / "push-gate"
    git(rectoversos, "config", "remote.origin.receivepack",
        f"touch {shlex.quote(str(started))}; until [ -e {shlex.quote(str(gate))} ]; do sleep 0.05; done; "
        "git-receive-pack")
    edit(box, rectoversos)
    done = []
    def second_save():
        try:
            done.append(edit(box, rectoversos, words="Second, edited while it pushed."))
        except BaseException as e:                        # the test's thread reads it, not the thread's own hook
            done.append(e)
    try:
        end = time.monotonic() + 60
        while not started.exists():                       # the push is under way, and held
            assert time.monotonic() < end, "the push never started"
            time.sleep(0.01)
        second = threading.Thread(target=second_save, daemon=True)
        second.start()
        second.join(60)
        assert not second.is_alive(), "the save waited for the push"
        assert not isinstance(done[0], BaseException), done[0]
    finally:
        gate.touch()                                      # lets the push go on, whatever happened above
    assert box.hub.commits.settle()


def test_a_commit_that_fails_leaves_nothing_staged(box, rectoversos):
    head = git(rectoversos, "rev-parse", "HEAD").strip()
    (rectoversos / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")   # a merge under way
    edit(box, rectoversos)
    (row,) = rows("commit-failed")
    assert row["doc"] == DOC
    assert git(rectoversos, "diff", "--cached", "--name-only") == ""


def test_a_link_into_the_versions_store_is_not_listed(box, rectoversos):
    edit(box, rectoversos)
    target = next((rectoversos / ".sheaf" / "versions").rglob("*.md"))
    (rectoversos / "acme" / "blog" / "alias.md").symlink_to(target)
    docs = [d["doc"] for r in box.get("/_/index.json").json()["roots"] for d in r["docs"]]
    assert docs == [DOC]


def test_a_projects_toml_that_cannot_be_read_warns_once_however_it_changes(box, rectoversos):
    (rectoversos / "projects.toml").write_text('[projects."acme/blog"]\nstatus = "maybe"\n', encoding="utf-8")
    box.get("/_/index.json")
    (rectoversos / "projects.toml").write_text('[projects."acme/blog"\n', encoding="utf-8")
    box.get("/_/index.json")
    assert len(rows("projects-invalid")) == 1


def test_a_versions_store_the_repo_ignores_stays_out_and_the_document_is_committed(box, rectoversos, remote):
    (rectoversos / ".git" / "info" / "exclude").write_text(".sheaf/\n", encoding="utf-8")
    edit(box, rectoversos)
    (who, files), _ = pushed(box, remote)
    assert who.startswith("Bea <bea@example.com>|")
    assert files == ["acme/blog/2026-10-28-plan.md"]


def test_a_file_the_repo_ignores_inside_the_versions_folder_is_never_committed(box, rectoversos, remote):
    from sheafmd.hub import state
    folder = rectoversos / ".sheaf" / "versions" / state.doc_key("acme/blog/2026-10-28-plan.md")
    folder.mkdir(parents=True)
    (folder / "notes.key").write_text("not a version\n", encoding="utf-8")
    (rectoversos / ".git" / "info" / "exclude").write_text("*.key\n", encoding="utf-8")
    edit(box, rectoversos)
    (who, files), _ = pushed(box, remote)
    assert who.startswith("Bea <bea@example.com>|") and not any(f.endswith(".key") for f in files)


def test_a_commit_that_fails_puts_back_what_was_staged_before(box, rectoversos):
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    original = f.read_text(encoding="utf-8")
    f.write_text(original + "\nStaged by hand, never in the work tree again.\n", encoding="utf-8")
    git(rectoversos, "add", "acme/blog/2026-10-28-plan.md")
    f.write_text(original, encoding="utf-8")
    head = git(rectoversos, "rev-parse", "HEAD").strip()
    (rectoversos / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")
    edit(box, rectoversos)
    assert rows("commit-failed")
    assert "Staged by hand" in git(rectoversos, "show", ":acme/blog/2026-10-28-plan.md")
    assert git(rectoversos, "diff", "--cached", "--name-only") == "acme/blog/2026-10-28-plan.md\n"


@pytest.mark.parametrize("versions", ["ignored", "in state"])
def test_a_write_that_brings_the_document_back_to_head_keeps_what_was_staged(box, rectoversos, remote, versions):
    # Versions out of the commit make no diff of their own: the write alone decides there is nothing to commit.
    if versions == "ignored":
        (rectoversos / ".git" / "info" / "exclude").write_text(".sheaf/\n", encoding="utf-8")
    else:
        (rectoversos / ".sheaf.toml").write_text('commit = true\npush = true\n', encoding="utf-8")
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    original = f.read_text(encoding="utf-8")
    f.write_text(original + "\nStaged by hand, never in the work tree again.\n", encoding="utf-8")
    git(rectoversos, "add", "acme/blog/2026-10-28-plan.md")
    f.write_text(original.replace("Second paragraph, about pears.", "Second, changed by hand."), encoding="utf-8")
    edit(box, rectoversos, words="Second paragraph, about pears.")
    assert f.read_text(encoding="utf-8") == original
    assert len(pushed(box, remote)) == 1
    assert rows("commit-failed") == []
    assert "Staged by hand" in git(rectoversos, "show", ":acme/blog/2026-10-28-plan.md")


def test_a_write_with_nothing_to_commit_keeps_the_flags_of_the_index(box, rectoversos, remote):
    (rectoversos / ".git" / "info" / "exclude").write_text(".sheaf/\n", encoding="utf-8")
    git(rectoversos, "update-index", "--assume-unchanged", "acme/blog/2026-10-28-plan.md")
    edit(box, rectoversos)
    assert len(pushed(box, remote)) == 1                 # the first commit alone: git add passed the file by
    assert git(rectoversos, "ls-files", "-v", "--", "acme/blog/2026-10-28-plan.md").startswith("h ")


@pytest.mark.parametrize("flag, letter", [("--assume-unchanged", "h "), ("--skip-worktree", "S ")])
def test_a_commit_that_fails_keeps_the_flags_of_the_version_entries_it_did_not_touch(box, rectoversos, flag, letter):
    # #49: putting the index back rewrote every entry of the versions folder, which drops their flags.
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    (kept, *_) = git(rectoversos, "ls-files", "--", ".sheaf/versions").split()
    git(rectoversos, "update-index", flag, kept)
    head = git(rectoversos, "rev-parse", "HEAD").strip()
    (rectoversos / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")   # a merge under way
    edit(box, rectoversos, words="Second, edited again.")
    assert rows("commit-failed")
    assert git(rectoversos, "ls-files", "-v", "--", kept).startswith(letter)
    assert git(rectoversos, "diff", "--cached", "--name-only") == ""


def test_a_document_the_repo_ignores_is_never_committed_nor_its_versions(box, rectoversos, remote):
    (rectoversos / ".git" / "info" / "exclude").write_text("acme/blog/2026-10-28-plan.md\n", encoding="utf-8")
    git(rectoversos, "rm", "-q", "--cached", "acme/blog/2026-10-28-plan.md")
    git(rectoversos, "commit", "-q", "-m", "a private draft from now on")
    git(rectoversos, "push", "-q", "origin", "HEAD:main")
    edit(box, rectoversos)
    assert len(pushed(box, remote)) == 2
    assert rows("commit-failed") == []
    assert git(rectoversos, "status", "--porcelain", "--", ".sheaf").strip().startswith("??")


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


def test_a_conflict_in_the_index_is_left_as_it_is(box, rectoversos):
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    original = f.read_text(encoding="utf-8")
    git(rectoversos, "checkout", "-q", "-b", "other")
    f.write_text(original.replace("Last paragraph.", "Last paragraph, theirs."), encoding="utf-8")
    git(rectoversos, "commit", "-q", "-am", "theirs")
    git(rectoversos, "checkout", "-q", "-")
    f.write_text(original.replace("Last paragraph.", "Last paragraph, ours."), encoding="utf-8")
    git(rectoversos, "commit", "-q", "-am", "ours")
    assert subprocess.run(["git", "-C", str(rectoversos), "merge", "-q", "other"], capture_output=True).returncode
    unmerged = git(rectoversos, "ls-files", "-u")
    assert unmerged.count("\n") == 3
    edit(box, rectoversos)
    (row,) = rows("commit-failed")
    assert row["doc"] == DOC and "conflict" in row["error"]
    assert git(rectoversos, "ls-files", "-u") == unmerged


PRIVATE = """---
client: acme
project: blog
owner: bea
sources: [library:doc-123]
---
# What the contract says

- [ ] Share

A quote from the contract.
"""


def test_a_share_is_one_commit_by_the_signed_in_owner_whatever_name_the_request_carries(box, rectoversos, remote):
    import dataclasses
    box.hub.proxy.members[BEA] = dataclasses.replace(box.hub.proxy.members[BEA], short="bea")
    rel = "acme/blog/2026-10-28-contract.md"
    (rectoversos / rel).write_text(PRIVATE, encoding="utf-8")
    git(rectoversos, "add", rel)
    git(rectoversos, "commit", "-q", "-m", "the contract")
    git(rectoversos, "push", "-q", "origin", "HEAD:main")

    def share(member):
        text = (rectoversos / rel).read_text(encoding="utf-8")
        edit = the_list.tick_edit(text, 0, "Share")
        return box.post("/_/save", {"doc": f"rectoversos/{rel}", "hash": md_hash(text), "edits": [edit],
                                    "by": "Bea", "author": "Bea <bea@example.com>", "short": "bea"}, member=member)

    assert share(CAL).status == 404                         # not his to open, let alone to share
    assert share(BEA).status == 200
    (who, files), *_ = pushed(box, remote)
    assert who == f"Bea <bea@example.com>|edit: {rel}"
    assert rel in files and all(f == rel or f.startswith(".sheaf/versions/") for f in files)
    on_remote = git(remote, "show", f"main:{rel}")
    assert "- [x] Share" in on_remote and "visibility: project" in on_remote and "shared: bea " in on_remote
    assert len(pushed(box, remote)) == 3                    # the first, the contract, the share: Cal wrote nothing


# ── what the remote got meanwhile (#62) ──────────────────────────────────────
def merged_on_github(tmp_path, remote, files: dict, subject: str):
    """A commit made away from the box and pushed to `remote`, as a PR merged on GitHub would be: `files` maps
    a path to its new text. Gives the new commit."""
    away = tmp_path / "github"
    if not away.exists():
        subprocess.run(["git", "clone", "-q", str(remote), str(away)], check=True, capture_output=True)
        git(away, "config", "user.name", "Ada")
        git(away, "config", "user.email", "ada@example.com")
    git(away, "pull", "-q", "--ff-only", "origin", "main")
    for rel, text in files.items():
        (away / rel).write_text(text, encoding="utf-8")
    git(away, "add", "-A")
    git(away, "commit", "-q", "-m", subject)
    git(away, "push", "-q", "origin", "HEAD:main")
    return git(away, "rev-parse", "HEAD").strip()


ONLY_BEA = '[projects."acme/blog"]\nmembers = ["bea"]\nstatus = "live"\n'


def test_a_projects_toml_change_merged_on_the_remote_reaches_the_hub_at_its_next_push_and_the_grant_follows(
        box, rectoversos, remote, tmp_path):
    assert box.get(f"/{DOC}", member=CAL).status == 200
    merged_on_github(tmp_path, remote, {"projects.toml": ONLY_BEA}, "Cal leaves acme/blog")
    edit(box, rectoversos)
    subjects = [who.split("|")[1] for who, _ in pushed(box, remote)]
    assert subjects == ["edit: acme/blog/2026-10-28-plan.md", "Cal leaves acme/blog", "first"]
    assert (rectoversos / "projects.toml").read_text(encoding="utf-8") == ONLY_BEA
    assert git(rectoversos, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert git(rectoversos, "status", "--porcelain", "--untracked-files=no") == ""
    assert box.get(f"/{DOC}", member=CAL).status == 404
    assert rows("push-diverged") == [] and rows("push-failed") == []


def test_the_hubs_commits_keep_their_author_and_subject_on_top_of_the_remotes(box, rectoversos, remote, tmp_path):
    edit(box, rectoversos)
    pushed(box, remote)
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    edit(box, rectoversos, member=CAL, words="Second, by Cal.")
    commits = pushed(box, remote)
    cal = git(rectoversos, "log", "-1", "--format=%an <%ae>", "HEAD").strip()
    assert cal.startswith("Cal <")
    assert [who for who, _ in commits] == [f"{cal}|edit: acme/blog/2026-10-28-plan.md", "Ada <ada@example.com>|a README",
                                           "Bea <bea@example.com>|edit: acme/blog/2026-10-28-plan.md",
                                           "the box <box@example.com>|first"]
    assert (rectoversos / "README.md").read_text(encoding="utf-8") == "# The rectoversos\n"
    assert "Second, by Cal." in git(remote, "show", "main:acme/blog/2026-10-28-plan.md")


def test_a_conflict_with_the_remote_leaves_the_checkout_as_it_was_pushes_nothing_and_is_a_row(
        box, rectoversos, remote, tmp_path):
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    theirs = f.read_text(encoding="utf-8").replace("Second", "Second, rewritten on GitHub")
    remote_head = merged_on_github(tmp_path, remote, {"acme/blog/2026-10-28-plan.md": theirs}, "a rewrite")
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    head = git(rectoversos, "rev-parse", "HEAD").strip()
    assert git(rectoversos, "log", "-1", "--format=%s", head).strip() == "edit: acme/blog/2026-10-28-plan.md"
    assert "Second, edited on the page." in f.read_text(encoding="utf-8")
    assert git(rectoversos, "status", "--porcelain", "--untracked-files=no") == ""
    assert not (rectoversos / ".git" / "rebase-merge").exists() and not (rectoversos / ".git" / "MERGE_HEAD").exists()
    assert git(remote, "rev-parse", "main").strip() == remote_head
    (row,) = rows("push-diverged")
    assert row["doc"] == DOC and row["paths"] == ["acme/blog/2026-10-28-plan.md"]
    # A person settles it once, on GitHub here; the next push goes through.
    merged_on_github(tmp_path, remote, {"acme/blog/2026-10-28-plan.md": PLAN}, "back as it was")
    edit(box, rectoversos, words="Second, edited again.")
    assert box.hub.commits.settle()
    assert git(rectoversos, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert "Second, edited again." in git(remote, "show", "main:acme/blog/2026-10-28-plan.md")
    assert len(rows("push-diverged")) == 1


def test_a_change_of_the_person_on_a_file_the_remote_changed_stops_the_pull_and_stays(box, rectoversos, remote, tmp_path):
    merged_on_github(tmp_path, remote, {"projects.toml": ONLY_BEA}, "Cal leaves acme/blog")
    mine = '[projects."acme/blog"]\nmembers = ["bea", "cal", "dan"]\nstatus = "live"\n'
    (rectoversos / "projects.toml").write_text(mine, encoding="utf-8")       # by hand on the box, not committed
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    assert (rectoversos / "projects.toml").read_text(encoding="utf-8") == mine
    (row,) = rows("push-diverged")
    assert row["doc"] == DOC and row["error"]
    assert git(remote, "log", "-1", "--format=%s", "main").strip() == "Cal leaves acme/blog"


def test_a_root_that_does_not_push_does_not_fetch(box, rectoversos, remote, tmp_path):
    (rectoversos / ".sheaf.toml").write_text('versions = "root"\ncommit = true\n', encoding="utf-8")
    merged_on_github(tmp_path, remote, {"projects.toml": ONLY_BEA}, "Cal leaves acme/blog")
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    assert git(rectoversos, "log", "-1", "--format=%s", "HEAD~1").strip() == "first"
    assert "cal" in (rectoversos / "projects.toml").read_text(encoding="utf-8")


def test_the_pull_holds_the_file_lock_of_what_it_changes(box, rectoversos, remote, tmp_path, monkeypatch):
    """A page's write never lands between the pull's look at a file and its writing of it (9.11's locks)."""
    from sheafmd.hub import commits
    seen = []
    real = commits._git

    def spy(folder, *args, **kw):
        if args[:1] == ("read-tree",):
            from sheafmd import source
            lock = source.file_lock(rectoversos / "projects.toml")
            import fcntl
            f = open(lock.paths[0], "a+")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen.append("free")
            except BlockingIOError:
                seen.append("held")
            finally:
                f.close()
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", spy)
    merged_on_github(tmp_path, remote, {"projects.toml": ONLY_BEA}, "Cal leaves acme/blog")
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    assert seen == ["held"]


def test_a_link_and_its_file_both_changed_on_the_remote_take_one_lock_and_the_push_goes(box, rectoversos, remote, tmp_path):
    """Two paths of one file are one file lock: the pull never waits on itself."""
    (rectoversos / "notes").mkdir()
    (rectoversos / "notes" / "b.md").write_text("# B\n", encoding="utf-8")
    (rectoversos / "notes" / "a.md").symlink_to("b.md")
    git(rectoversos, "add", "-A")
    git(rectoversos, "commit", "-q", "-m", "a link")
    git(rectoversos, "push", "-q", "origin", "HEAD:main")
    away = tmp_path / "github"
    merged_on_github(tmp_path, remote, {"notes/b.md": "# B, on GitHub\n"}, "b")
    git(away, "rm", "-q", "notes/a.md")
    git(away, "commit", "-q", "-m", "no link")
    git(away, "push", "-q", "origin", "HEAD:main")
    edit(box, rectoversos)
    assert box.hub.commits.settle(timeout=10)
    assert git(rectoversos, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert (rectoversos / "notes" / "b.md").read_text(encoding="utf-8") == "# B, on GitHub\n"


def test_a_file_name_that_is_not_utf8_on_the_remote_is_taken_in(box, rectoversos, remote, tmp_path):
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    away = tmp_path / "github"
    undecodable_names_or_skip(away)
    (away / os.fsdecode(b"caf\xe9.txt")).write_text("x\n", encoding="utf-8")
    git(away, "add", "-A")
    git(away, "commit", "-q", "-m", "a latin-1 name")
    git(away, "push", "-q", "origin", "HEAD:main")
    edit(box, rectoversos)
    assert box.hub.commits.settle(timeout=10)
    assert git(rectoversos, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert (rectoversos / os.fsdecode(b"caf\xe9.txt")).exists()


def test_a_hub_commit_the_remote_already_holds_is_not_pushed_again_empty(box, rectoversos, remote, tmp_path):
    (rectoversos / "README.md").write_text("# The rectoversos\n", encoding="utf-8")
    git(rectoversos, "add", "README.md")
    git(rectoversos, "commit", "-q", "-m", "a README, on the box")         # not pushed
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README, on GitHub")
    edit(box, rectoversos)
    subjects = [who.split("|")[1] for who, _ in pushed(box, remote)]
    assert subjects == ["edit: acme/blog/2026-10-28-plan.md", "a README, on GitHub", "first"]


def test_two_roots_of_one_repo_share_its_commit_lock_and_a_commit_of_one_never_lands_inside_the_others_pull(
        tmp_path, remote, monkeypatch):
    """Two roots in one git repo share one index and one HEAD, so one commit lock (#73): a commit of root B waits
    while root A's pull moves HEAD, and comes after it, on top."""
    import inspect
    import sys
    import threading
    import time

    from sheafmd.hub import commits
    from sheafmd.hub.roots import Root
    repo = tmp_path / "rectoversos"
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "the box")
    git(repo, "config", "user.email", "box@example.com")
    for name in ("acme", "globex"):
        (repo / name).mkdir()
        (repo / name / ".sheaf.toml").write_text("commit = true\npush = true\n", encoding="utf-8")
        (repo / name / "plan.md").write_text(f"# {name}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    git(repo, "push", "-q", "origin", "HEAD:main")
    a, b = (Root(name, repo / name, True) for name in ("acme", "globex"))
    made = []
    hub_commits = commits.Commits(lambda kind, doc, **detail: made.append((kind, doc, detail)))
    real, racer = commits._git, []

    # The line of `saved` that takes the commit lock: a thread whose innermost frame stays there waits on it.
    lines, first = inspect.getsourcelines(commits.Commits.saved)
    at_lock = first + next(i for i, line in enumerate(lines) if "_lock(root.path)" in line)

    def waiting(t):
        frame = sys._current_frames().get(t.ident)
        return frame is not None and frame.f_code is commits.Commits.saved.__code__ and frame.f_lineno == at_lock

    def spy(folder, *args, **kw):
        if args[:1] == ("update-ref",) and not racer:
            (repo / "globex" / "plan.md").write_text("# globex, on the page\n", encoding="utf-8")
            racer.append(threading.Thread(target=hub_commits.saved,
                                          args=(b, "plan.md", commits.Author("Cal", "cal@example.com"), "edit")))
            racer[0].start()
            # B's commit lands between A's read-tree and HEAD, or waits on A's lock: whichever, not a timing.
            seen, end = 0, time.monotonic() + 30
            while racer[0].is_alive() and seen < 5 and time.monotonic() < end:
                seen = seen + 1 if waiting(racer[0]) else 0
                time.sleep(0.02)
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", spy)
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    (repo / "acme" / "plan.md").write_text("# acme, on the page\n", encoding="utf-8")
    hub_commits.saved(a, "plan.md", commits.Author("Bea", "bea@example.com"), "edit")
    assert hub_commits.settle()
    racer[0].join(30)
    assert not racer[0].is_alive()
    assert hub_commits.settle()
    assert made == []
    assert git(repo, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert git(remote, "log", "--format=%an|%s", "main").splitlines() == [
        "Cal|edit: plan.md", "Bea|edit: plan.md", "Ada|a README", "the box|first"]
    assert git(remote, "show", "--name-only", "--format=", "main").split() == ["globex/plan.md"]


# ── the poll's fetch (#75) ─────────────────────────────────────────────────────
def poll(box):
    """One pass of the watcher, then the pusher's work it handed on."""
    box.hub.tick()
    assert box.hub.commits.settle()


def fetches(monkeypatch):
    from sheafmd.hub import commits
    seen, real = [], commits._git

    def spy(folder, *args, **kw):
        if args[:1] == ("fetch",):
            seen.append(folder)
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", spy)
    return seen


def test_a_projects_toml_merged_on_the_remote_lands_at_the_next_poll_with_no_save_and_the_grant_follows(
        box, rectoversos, remote, tmp_path):
    assert box.get(f"/{DOC}", member=CAL).status == 200
    head = merged_on_github(tmp_path, remote, {"projects.toml": ONLY_BEA}, "Cal leaves acme/blog")
    poll(box)
    assert (rectoversos / "projects.toml").read_text(encoding="utf-8") == ONLY_BEA
    # The page Cal opened made a version: the poll commits it on top of the remote's (#92), and pushes it.
    assert git(rectoversos, "log", "-2", "--format=%H %s") == f"{git(rectoversos, 'rev-parse', 'HEAD').strip()} " \
        f"versions: acme/blog/2026-10-28-plan.md\n{head} Cal leaves acme/blog\n"
    assert git(rectoversos, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert git(rectoversos, "status", "--porcelain", "--untracked-files=no") == ""
    assert box.get(f"/{DOC}", member=CAL).status == 404
    assert rows("push-diverged") == [] and rows("push-failed") == []


def test_two_polls_within_a_minute_fetch_once(box, rectoversos, remote, monkeypatch):
    seen = fetches(monkeypatch)
    poll(box)
    poll(box)
    assert len(seen) == 1


def test_a_poll_fetches_again_once_the_interval_passed(box, rectoversos, remote, tmp_path, monkeypatch):
    from sheafmd.hub import commits
    seen = fetches(monkeypatch)
    poll(box)
    monkeypatch.setattr(commits, "FETCH_SECONDS", 0)
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    poll(box)
    assert len(seen) == 2
    assert (rectoversos / "README.md").read_text(encoding="utf-8") == "# The rectoversos\n"


def test_a_root_that_does_not_push_is_never_fetched_by_the_poll(box, rectoversos, remote, tmp_path, monkeypatch):
    (rectoversos / ".sheaf.toml").write_text('versions = "root"\ncommit = true\n', encoding="utf-8")
    seen = fetches(monkeypatch)
    poll(box)
    assert seen == []


def test_a_fetch_the_poll_cannot_make_is_one_row_however_many_polls_meet_it(box, rectoversos, remote, tmp_path, monkeypatch):
    from sheafmd.hub import commits
    monkeypatch.setattr(commits, "FETCH_SECONDS", 0)
    remote.rename(tmp_path / "away.git")
    poll(box)
    poll(box)
    poll(box)
    (row,) = rows("push-failed")
    assert row["doc"] == "rectoversos" and row["error"]


def test_a_hub_commit_whose_push_failed_goes_out_at_the_next_poll(box, rectoversos, remote, tmp_path, monkeypatch):
    from sheafmd.hub import commits
    away = tmp_path / "away.git"
    remote.rename(away)
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    away.rename(remote)
    monkeypatch.setattr(commits, "FETCH_SECONDS", 0)
    poll(box)
    assert git(rectoversos, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")


def test_an_idle_poll_pushes_nothing(box, rectoversos, remote, monkeypatch):
    from sheafmd.hub import commits
    pushes, real = [], commits._git

    def spy(folder, *args, **kw):
        if args[:1] == ("push",):
            pushes.append(folder)
        return real(folder, *args, **kw)

    seen = fetches(monkeypatch)
    poll(box)
    assert len(seen) == 1 and pushes == []


def test_a_poll_never_pushes_a_commit_or_a_branch_made_by_hand(box, rectoversos, remote, monkeypatch):
    """The poll takes in the remote; what it pushes is a write's push that failed, never a person's own commit."""
    from sheafmd.hub import commits
    (rectoversos / "README.md").write_text("# by hand\n", encoding="utf-8")
    git(rectoversos, "add", "README.md")
    git(rectoversos, "commit", "-q", "-m", "by hand")
    first = git(remote, "rev-parse", "main")
    poll(box)
    git(rectoversos, "checkout", "-q", "-b", "experiment")
    monkeypatch.setattr(commits, "FETCH_SECONDS", 0)
    poll(box)
    assert git(remote, "rev-parse", "main") == first
    assert git(remote, "branch", "--list", "experiment") == ""


def test_the_polls_row_for_one_cause_is_one_however_its_numbers_move():
    from sheafmd.hub import commits
    made = []
    once = commits.Commits(lambda kind, doc, **detail: made.append(detail))._once("/r")
    once("push-failed", "r", error="Failed to connect to 127.0.0.1 port 9 after 3012 ms: No route to host")
    once("push-failed", "r", error="Failed to connect to 127.0.0.1 port 9 after 2987 ms: No route to host")
    assert len(made) == 1


def test_a_pull_of_one_root_waits_on_the_name_of_a_sheaf_another_root_of_the_repo_moves(hub, tmp_path, monkeypatch):
    """A pull of root A that changes both files of a move in root B, where the hub places B's rectoversos, waits on the
    sheaf's name before any file lock, as B's writer does (#76): the writer that holds the name and the move's first
    file takes its second, and neither waits on the other for ever."""
    import fcntl
    import threading
    import time

    from sheafmd import source
    from sheafmd.hub import place
    repo = tmp_path / "rectoversos"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "globex").mkdir()
    b = hub.roots._add(repo, git=True)
    a = hub.roots._add(repo / "globex", git=False)
    monkeypatch.setattr(place, "applies", lambda hub, name: name == b.name)
    # The move of the sheaf `acme/blog/plan.md` out to Bea's private folder: the writer holds the file it leaves
    # and takes the one it goes to. Whichever sorts first is the one the pull would take first.
    p, q = repo / "acme" / "blog" / "plan.md", repo / "acme" / "blog" / "private" / "bea" / "plan.md"
    first, second = sorted((p, q), key=source.lock_key)
    name = (str(os.path.realpath(b.path)), "acme/blog/plan.md")

    def free(f):
        with open(source._lock_path(f), "a+") as fd:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True

    holding, go, got, entered = threading.Event(), threading.Event(), [], []

    def writer():
        with place.held(hub, f"{b.name}/acme/blog/plan.md"), source.file_lock(second):
            holding.set()
            go.wait(30)
            end = time.monotonic() + 3          # bounded: the deadlock is a failure here, not a hang
            while time.monotonic() < end and not free(first):
                time.sleep(0.02)
            if free(first):
                with source.file_lock(first):
                    got.append(first)

    def pull():
        with hub._writers_out(a, [p, q]):
            entered.append(True)

    w = threading.Thread(target=writer)
    w.start()
    assert holding.wait(30)
    g = threading.Thread(target=pull)
    g.start()
    # The pull has settled: waiting on the name (a second thread counted on its lock), or on a file lock it reached.
    end = time.monotonic() + 30
    while time.monotonic() < end and place._LOCKS.get(name, [None, 0])[1] < 2 and free(first):
        time.sleep(0.02)
    go.set()
    w.join(30)
    g.join(30)
    assert not w.is_alive() and not g.is_alive()
    assert got == [first]
    assert entered == [True]


# ── two roots of one repo: the repo pulls and pushes as a whole (#89) ─────────
def one_repo(tmp_path, remote, acme="commit = true\npush = true\n", globex="commit = true\npush = true\n"):
    """A clone of `remote` holding two roots, `acme/` and `globex/`, each with its own `.sheaf.toml` (`None`: none)
    and a `plan.md`, committed and pushed. Gives (the repo, root acme, root globex)."""
    from sheafmd.hub.roots import Root
    repo = tmp_path / "rectoversos"
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "the box")
    git(repo, "config", "user.email", "box@example.com")
    for name, settings in (("acme", acme), ("globex", globex)):
        (repo / name).mkdir()
        if settings is not None:
            (repo / name / ".sheaf.toml").write_text(settings, encoding="utf-8")
        (repo / name / "plan.md").write_text(f"# {name}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    git(repo, "push", "-q", "origin", "HEAD:main")
    return repo, Root("acme", repo / "acme", True), Root("globex", repo / "globex", True)


def git_spy(monkeypatch, on_fetch=None):
    """The folders the hub fetched in and pushed from, in order; `on_fetch()` runs before each fetch."""
    from sheafmd.hub import commits
    seen, real = {"fetch": [], "push": []}, commits._git

    def spy(folder, *args, **kw):
        if args[:1] in (("fetch",), ("push",)):
            if args[0] == "fetch" and on_fetch:
                on_fetch()
            seen[args[0]].append(folder)
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", spy)
    return seen


def on_the_page(repo, root, words):
    from sheafmd.hub import commits
    (repo / root.name / "plan.md").write_text(f"# {root.name}, {words}\n", encoding="utf-8")
    return commits.Author("Bea", "bea@example.com")


def test_a_poll_fetches_a_repo_once_however_many_of_its_roots_push(tmp_path, remote, monkeypatch):
    from sheafmd.hub import commits
    repo, a, b = one_repo(tmp_path, remote)
    made = []
    hub_commits = commits.Commits(lambda kind, doc, **detail: made.append(kind))
    seen = git_spy(monkeypatch)
    hub_commits.poll([a, b])
    assert hub_commits.settle()
    assert len(seen["fetch"]) == 1
    assert made == []


def test_a_pull_names_the_author_of_a_file_of_a_root_that_is_a_folder_of_its_repo(tmp_path, remote):
    """The changed paths git gives are relative to the top of the repo, so the author is looked up from there."""
    from sheafmd.hub import commits
    repo, a, b = one_repo(tmp_path, remote)
    merged_on_github(tmp_path, remote, {"acme/plan.md": "# acme, on GitHub\n"}, "on GitHub")
    told = []
    hub_commits = commits.Commits(lambda kind, doc, **detail: None,
                                  pulled=lambda folder, files, ok, left=None, named=None: told.append((files, ok)))
    hub_commits.poll([a, b])
    assert hub_commits.settle()
    assert told == [([(repo / "acme" / "plan.md", "Ada")], True)]


def test_one_cause_in_a_repo_of_two_roots_is_one_push_diverged_row(tmp_path, remote, monkeypatch):
    """A remote that changed what the box committed meets the poll of each root of the repo: one cause, one row."""
    from sheafmd.hub import commits
    repo, a, b = one_repo(tmp_path, remote)
    (repo / "acme" / "plan.md").write_text("# acme, on the box\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "on the box")                      # not pushed
    merged_on_github(tmp_path, remote, {"acme/plan.md": "# acme, on GitHub\n"}, "on GitHub")
    made = []
    hub_commits = commits.Commits(lambda kind, doc, **detail: made.append((kind, doc)))
    hub_commits.poll([a, b])
    assert hub_commits.settle()
    assert [kind for kind, _ in made] == ["push-diverged"]


def test_writes_in_both_roots_of_a_repo_while_a_push_runs_make_one_pull_and_push_after_it(tmp_path, remote, monkeypatch):
    """The repo is due once, whichever of its roots asked: a push carries every commit of its HEAD."""
    import threading

    from sheafmd.hub import commits
    repo, a, b = one_repo(tmp_path, remote)
    fetching, go = threading.Event(), threading.Event()

    def hold():
        if not fetching.is_set():
            fetching.set()
            assert go.wait(30)

    seen = git_spy(monkeypatch, on_fetch=hold)
    made = []
    hub_commits = commits.Commits(lambda kind, doc, **detail: made.append(kind))
    hub_commits.saved(a, "plan.md", on_the_page(repo, a, "first"), "edit")
    assert fetching.wait(30)                                            # the pusher took acme's push
    hub_commits.saved(a, "plan.md", on_the_page(repo, a, "second"), "edit")
    hub_commits.saved(b, "plan.md", on_the_page(repo, b, "first"), "edit")
    go.set()
    assert hub_commits.settle()
    # The first push carries the three commits, made while its fetch ran; the one pull after it finds nothing to push.
    assert len(seen["fetch"]) == 2 and len(seen["push"]) == 1
    assert made == []
    assert git(repo, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")


@pytest.mark.parametrize("globex", ["commit = true\n", "commit = true\npush = false\n"])
def test_roots_of_one_repo_that_disagree_on_push_push_nothing_until_they_agree(tmp_path, remote, monkeypatch,
                                                                              capsys, globex):
    """acme pushes and globex, which commits, does not: acme's push would carry globex's commits, so the repo
    pushes and pulls nothing, says so once, and a write's push goes out once the two agree."""
    from sheafmd.hub import commits
    repo, a, b = one_repo(tmp_path, remote, globex=globex)
    first = git(remote, "rev-parse", "main")
    made = []
    hub_commits = commits.Commits(lambda kind, doc, **detail: made.append((kind, doc, detail)), roots=lambda: [a, b])
    seen = git_spy(monkeypatch)
    hub_commits.saved(b, "plan.md", on_the_page(repo, b, "first"), "edit")
    hub_commits.saved(a, "plan.md", on_the_page(repo, a, "first"), "edit")
    hub_commits.poll([a, b])
    assert hub_commits.settle()
    assert seen == {"fetch": [], "push": []}
    assert git(remote, "rev-parse", "main") == first
    assert git(repo, "log", "--format=%s", "-2").splitlines() == ["edit: plan.md", "edit: plan.md"]
    assert made == [("push-settings-differ", "acme/plan.md", {"push": ["acme"], "no_push": ["globex"]})]
    assert capsys.readouterr().err.count("pushes nothing until they agree") == 1
    (repo / "globex" / ".sheaf.toml").write_text("commit = true\npush = true\n", encoding="utf-8")
    monkeypatch.setattr(commits, "FETCH_SECONDS", 0)
    hub_commits.poll([a, b])
    assert hub_commits.settle()
    assert git(repo, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert len(made) == 1


def test_a_root_that_does_not_commit_leaves_the_push_of_its_repo_to_the_roots_that_do(tmp_path, remote):
    """The hub never commits a path of a root that does not commit, so the push of the others carries none of its
    writes: no disagreement."""
    from sheafmd.hub import commits
    repo, a, b = one_repo(tmp_path, remote, globex=None)
    made = []
    hub_commits = commits.Commits(lambda kind, doc, **detail: made.append(kind), roots=lambda: [a, b])
    hub_commits.saved(b, "plan.md", on_the_page(repo, b, "first"), "edit")
    hub_commits.saved(a, "plan.md", on_the_page(repo, a, "first"), "edit")
    assert hub_commits.settle()
    assert made == []
    assert git(remote, "log", "--format=%s", "main").splitlines() == ["edit: plan.md", "first"]
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == " M globex/plan.md\n"


def test_a_write_made_while_a_push_runs_and_the_roots_part_goes_out_once_they_agree(tmp_path, remote, monkeypatch):
    """A save after the push read HEAD, meeting a mix that came meanwhile, is a write's push not gone: the poll after
    the roots agree again pushes it (the gate on PR 90)."""
    from sheafmd.hub import commits
    repo, a, b = one_repo(tmp_path, remote)
    made = []
    hub_commits = commits.Commits(lambda kind, doc, **detail: made.append(kind), roots=lambda: [a, b])
    real, done = commits._git, []

    def spy(folder, *args, **kw):
        r = real(folder, *args, **kw)
        if args[:1] == ("push",) and not done:
            done.append(True)
            (repo / "globex" / ".sheaf.toml").write_text("commit = true\npush = false\n", encoding="utf-8")
            hub_commits.saved(a, "plan.md", on_the_page(repo, a, "second"), "edit")
        return r

    monkeypatch.setattr(commits, "_git", spy)
    hub_commits.saved(a, "plan.md", on_the_page(repo, a, "first"), "edit")
    assert hub_commits.settle()
    assert made == ["push-settings-differ"]
    (repo / "globex" / ".sheaf.toml").write_text("commit = true\npush = true\n", encoding="utf-8")
    monkeypatch.setattr(commits, "FETCH_SECONDS", 0)
    hub_commits.poll([a, b])
    assert hub_commits.settle()
    assert git(repo, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")


def test_a_push_queued_while_the_roots_agreed_is_judged_again_when_its_turn_comes(tmp_path, remote, monkeypatch):
    """The mix is judged when the pusher takes the repo, not when a write queued it: a root that stops pushing while
    its push waits is not pushed (the gate on PR 90). What a push already carried was committed while they agreed."""
    from sheafmd.hub import commits
    repo, a, b = one_repo(tmp_path, remote)
    made = []
    hub_commits = commits.Commits(lambda kind, doc, **detail: made.append(kind), roots=lambda: [a, b])
    real, seen = commits._git, []

    def spy(folder, *args, **kw):
        if args[:1] == ("fetch",):
            seen.append(folder)
        r = real(folder, *args, **kw)
        if args[:1] == ("push",) and len(seen) == 1:
            hub_commits.saved(b, "plan.md", on_the_page(repo, b, "first"), "edit")   # queued while the two agree
            (repo / "globex" / ".sheaf.toml").write_text("commit = true\npush = false\n", encoding="utf-8")
        return r

    monkeypatch.setattr(commits, "_git", spy)
    hub_commits.saved(a, "plan.md", on_the_page(repo, a, "first"), "edit")
    assert hub_commits.settle()
    assert len(seen) == 1 and made == ["push-settings-differ"]
    assert git(remote, "log", "--format=%s", "main").splitlines() == ["edit: plan.md", "first"]
    assert git(repo, "log", "--format=%s", "-3").splitlines() == ["edit: plan.md", "edit: plan.md", "first"]


# ── versions written without a write (#92) ─────────────────────────────────────
def untracked_versions(rectoversos):
    return git(rectoversos, "status", "--porcelain", "--untracked-files=all", "--", ".sheaf/versions")


def test_a_version_the_remote_gained_while_the_hub_held_it_untracked_is_taken_in(box, rectoversos, remote, tmp_path):
    """A page opened makes a version with no write behind it. Another clone's hub keeps the same text under the
    same name and commits it: git refuses to write over an untracked file even when it is the same, so the pull
    must find none."""
    assert box.get(f"/{DOC}", member=BEA).status == 200
    kept = {p.relative_to(rectoversos).as_posix(): p.read_text(encoding="utf-8")
            for p in (rectoversos / ".sheaf" / "versions").rglob("*") if p.is_file()}
    assert kept, "opening the page kept a version inside the root"
    away = tmp_path / "github"
    subprocess.run(["git", "clone", "-q", str(remote), str(away)], check=True, capture_output=True)
    git(away, "config", "user.name", "Ada")
    git(away, "config", "user.email", "ada@example.com")
    for rel in kept:
        (away / rel).parent.mkdir(parents=True, exist_ok=True)
    head = merged_on_github(tmp_path, remote, kept, "the other clone's versions")
    poll(box)
    assert rows("push-diverged") == [] and rows("push-failed") == []
    assert git(remote, "merge-base", "--is-ancestor", head, "main") == ""
    assert git(rectoversos, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert untracked_versions(rectoversos) == ""
    assert not [a for a in box.hub.writes._lines if "/.sheaf/" in a]   # a version is no page (a README is one: test_write_log_places)


def opened(box, rectoversos):
    assert box.get(f"/{DOC}", member=BEA).status == 200


def changed_from_outside(box, rectoversos):
    opened(box, rectoversos)
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    f.write_text(f.read_text(encoding="utf-8") + "\nAn agent's line.\n", encoding="utf-8")
    opened(box, rectoversos)


def pinned(box, rectoversos):
    opened(box, rectoversos)
    text = (rectoversos / "acme" / "blog" / "2026-10-28-plan.md").read_text(encoding="utf-8")
    r = box.post("/_/pin", {"doc": DOC, "hash": md_hash(text)}, member=BEA)
    assert r.status == 200, r.text


@pytest.mark.parametrize("push", [True, False], ids=["pushes", "does not push"])
@pytest.mark.parametrize("made", [opened, changed_from_outside, pinned], ids=lambda f: f.__name__)
def test_a_version_made_with_no_write_is_committed_by_the_next_poll(box, rectoversos, remote, made, push):
    if not push:
        (rectoversos / ".sheaf.toml").write_text('versions = "root"\ncommit = true\n', encoding="utf-8")
    made(box, rectoversos)
    assert untracked_versions(rectoversos) != ""
    poll(box)
    assert untracked_versions(rectoversos) == ""
    assert git(rectoversos, "log", "-1", "--format=%an|%s") == "sheaf|versions: acme/blog/2026-10-28-plan.md\n"
    assert git(remote, "rev-parse", "main") == git(rectoversos, "rev-parse", "HEAD") if push else \
        git(remote, "rev-list", "--count", "main") == "1\n"
    assert rows("commit-failed") == []


def test_the_versions_of_a_document_the_repo_ignores_stay_out_when_the_poll_commits(box, rectoversos, remote):
    (rectoversos / ".git" / "info" / "exclude").write_text("acme/blog/2026-10-28-plan.md\n", encoding="utf-8")
    git(rectoversos, "rm", "-q", "--cached", "acme/blog/2026-10-28-plan.md")
    git(rectoversos, "commit", "-q", "-m", "a private draft from now on")
    opened(box, rectoversos)
    poll(box)
    assert git(rectoversos, "log", "-1", "--format=%s") == "a private draft from now on\n"
    assert untracked_versions(rectoversos).startswith("??")


def test_a_version_half_written_is_never_committed_by_the_poll(box, rectoversos, remote):
    from sheafmd.hub import state
    opened(box, rectoversos)
    folder = rectoversos / ".sheaf" / "versions" / state.doc_key("acme/blog/2026-10-28-plan.md")
    (folder / f".{'0' * 16}.md.tmp").write_text("half a ver", encoding="utf-8")
    poll(box)
    assert git(rectoversos, "log", "-1", "--format=%s") == "versions: acme/blog/2026-10-28-plan.md\n"
    assert not any(f.endswith(".tmp") for f in git(rectoversos, "show", "--name-only", "--format=", "HEAD").split())
    assert untracked_versions(rectoversos).splitlines() == [f"?? .sheaf/versions/{folder.name}/.{'0' * 16}.md.tmp"]


def test_a_version_the_pull_commits_is_pushed(box, rectoversos, remote, tmp_path, monkeypatch):
    """A page opened while the poll fetches: the pull commits its version just before the work tree moves, and
    that commit goes out with the pull, not with the next write."""
    from sheafmd.hub import commits
    real, once = commits._git, []

    def spy(folder, *args, **kw):
        r = real(folder, *args, **kw)
        if args[:1] == ("fetch",) and not once:
            once.append(1)
            opened(box, rectoversos)
        return r

    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    monkeypatch.setattr(commits, "_git", spy)
    poll(box)
    assert once and untracked_versions(rectoversos) == ""
    assert git(remote, "log", "-1", "--format=%s", "main") == "versions: acme/blog/2026-10-28-plan.md\n"
    assert git(rectoversos, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")


def test_a_sweep_that_fails_is_a_row_and_the_pull_still_comes(box, rectoversos, remote, tmp_path, monkeypatch):
    from sheafmd.hub import commits
    real = commits._git

    def spy(folder, *args, **kw):
        if args[:2] == ("ls-files", "-z"):
            raise subprocess.TimeoutExpired(args, 20)
        return real(folder, *args, **kw)

    opened(box, rectoversos)
    head = merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    monkeypatch.setattr(commits, "_git", spy)
    poll(box)
    monkeypatch.setattr(commits, "FETCH_SECONDS", 0)
    poll(box)                                           # a pull that went through forgets nothing of the sweep's row
    assert (rectoversos / "README.md").read_text(encoding="utf-8") == "# The rectoversos\n"
    assert git(rectoversos, "rev-parse", "HEAD").strip() == head
    assert rows("push-failed") == [] and [r["doc"] for r in rows("commit-failed")] == ["rectoversos"]


def test_an_address_that_is_a_link_never_reaches_a_commit(box, rectoversos, remote, tmp_path):
    from sheafmd.hub import state
    secret = tmp_path / "token.env"
    secret.write_text("TOKEN=s3cr3t\n", encoding="utf-8")
    folder = rectoversos / ".sheaf" / "versions" / state.doc_key("acme/blog/2026-10-28-plan.md")
    folder.mkdir(parents=True)
    (folder / "address").symlink_to(secret)
    opened(box, rectoversos)                                # the version written: the link is written over
    assert not (folder / "address").is_symlink() and secret.read_text(encoding="utf-8") == "TOKEN=s3cr3t\n"
    (folder / "address").unlink()
    (folder / "address").symlink_to(secret)             # and planted again after it, before the sweep
    poll(box)
    assert "s3cr3t" not in git(remote, "log", "--format=%B", "main")
    assert git(remote, "log", "-1", "--format=%s", "main") == f"versions: {folder.name}\n"


def test_a_forged_address_names_no_commit(box, rectoversos, remote):
    """An `address` that is not the folder's key (written by hand, or merged on the remote) is not believed."""
    from sheafmd.hub import state
    opened(box, rectoversos)
    folder = rectoversos / ".sheaf" / "versions" / state.doc_key("acme/blog/2026-10-28-plan.md")
    (folder / "address").write_text("TOKEN=s3cr3t", encoding="utf-8")
    poll(box)
    assert git(remote, "log", "-1", "--format=%s", "main") == f"versions: {folder.name}\n"


def test_a_forged_address_is_written_over_at_the_next_version(box, rectoversos, remote):
    from sheafmd.hub import state
    opened(box, rectoversos)
    folder = rectoversos / ".sheaf" / "versions" / state.doc_key("acme/blog/2026-10-28-plan.md")
    (folder / "address").write_text("TOKEN=s3cr3t", encoding="utf-8")
    changed_from_outside(box, rectoversos)
    poll(box)
    assert (folder / "address").read_text(encoding="utf-8") == "acme/blog/2026-10-28-plan.md"
    assert git(remote, "log", "-1", "--format=%s", "main") == "versions: acme/blog/2026-10-28-plan.md\n"


def test_an_address_that_is_a_fifo_never_holds_the_pusher(box, rectoversos, remote):
    from sheafmd.hub import state
    opened(box, rectoversos)
    folder = rectoversos / ".sheaf" / "versions" / state.doc_key("acme/blog/2026-10-28-plan.md")
    (folder / "address").unlink()
    os.mkfifo(folder / "address")
    box.hub.tick()
    assert box.hub.commits.settle(10)
    assert git(remote, "log", "-1", "--format=%s", "main") == f"versions: {folder.name}\n"


@pytest.mark.parametrize("step", ["add", "commit"])
def test_a_git_that_times_out_puts_back_what_was_staged_and_leaves_no_lock(box, rectoversos, monkeypatch, step):
    """#38: a git the hub killed on its bound leaves its `index.lock`, and the index as it had made it."""
    from sheafmd.hub import commits
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    original = f.read_text(encoding="utf-8")
    f.write_text(original + "\nStaged by hand, never in the work tree again.\n", encoding="utf-8")
    git(rectoversos, "add", "acme/blog/2026-10-28-plan.md")
    f.write_text(original, encoding="utf-8")
    real = commits._git

    def killed(folder, *args, **kw):
        if step in args and "--" in args:
            if step == "add":
                real(folder, *args, **kw)                  # killed after it staged the write
            (rectoversos / ".git" / "index.lock").write_text("", encoding="utf-8")   # what a SIGKILL leaves
            raise subprocess.TimeoutExpired(args, 20)
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", killed)
    edit(box, rectoversos)
    (row,) = rows("commit-failed")
    assert row["doc"] == DOC
    assert not (rectoversos / ".git" / "index.lock").exists()
    assert "Staged by hand" in git(rectoversos, "show", ":acme/blog/2026-10-28-plan.md")
    assert git(rectoversos, "diff", "--cached", "--name-only") == "acme/blog/2026-10-28-plan.md\n"


def test_a_lock_another_git_took_after_the_add_is_left_where_it_is(box, rectoversos, monkeypatch):
    """#38: only the add and the commit take the index lock; a later git that times out never made one."""
    from sheafmd.hub import commits
    real = commits._git
    lock = rectoversos / ".git" / "index.lock"

    def slow_fetch(folder, *args, **kw):
        if args[:2] == ("diff", "--cached"):
            lock.write_text("", encoding="utf-8")       # a person's `git commit`, its editor open
            raise subprocess.TimeoutExpired(args, 20)
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", slow_fetch)
    edit(box, rectoversos)
    assert rows("commit-failed")
    assert lock.exists()


def test_a_git_commit_killed_once_the_commit_is_made_counts_as_made(box, rectoversos, remote, monkeypatch):
    """#38: the branch moved before the kill, so the index is not put back under it and no row says it failed."""
    from sheafmd.hub import commits
    real = commits._git

    def killed(folder, *args, **kw):
        r = real(folder, *args, **kw)
        if "commit" in args and "--" in args:
            (rectoversos / ".git" / "index.lock").write_text("", encoding="utf-8")
            raise subprocess.TimeoutExpired(args, 20)
        return r

    monkeypatch.setattr(commits, "_git", killed)
    edit(box, rectoversos)
    assert rows("commit-failed") == []
    assert not (rectoversos / ".git" / "index.lock").exists()
    assert git(rectoversos, "log", "-1", "--format=%s") == f"edit: acme/blog/2026-10-28-plan.md\n"
    assert git(rectoversos, "diff", "--cached", "--name-only") == ""


def test_a_repo_with_an_email_but_no_name_commits_as_sheaf(box, rectoversos, remote):
    """#38: the hub's committer stood in only for a missing `user.email`; with no `user.name` either git refused."""
    git(rectoversos, "config", "--unset", "user.name")
    git(rectoversos, "config", "user.useConfigOnly", "true")
    edit(box, rectoversos)
    assert rows("commit-failed") == []
    (who, _), _ = pushed(box, remote)
    assert who.startswith("Bea <bea@example.com>|")
    assert git(remote, "log", "-1", "--format=%cn <%ce>", "main") == "sheaf <sheaf@localhost>\n"


def test_a_comment_request_that_changes_nothing_commits_nothing(box, rectoversos):
    """A status set to the status it has leaves the file as it was: the person's own uncommitted edit of the
    document stays theirs to commit, never taken into a commit under the requester's name."""
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("First"))
    r = box.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text), "block": i, "start": 0,
                                "end": 5, "quote": "First", "body": "Is this right?"}, member=CAL)
    assert r.status == 200, r.text
    box.hub.commits.settle()
    cid = r.json()["id"]
    f.write_text(f.read_text(encoding="utf-8") + "\nBea's own edit, not yet committed.\n", encoding="utf-8")
    head = git(rectoversos, "rev-parse", "HEAD")
    r = box.post("/_/comment", {"doc": DOC, "op": "status", "id": cid, "status": "open",
                                "hash": md_hash(text)}, member=CAL)
    assert r.status == 200, r.text
    box.hub.commits.settle()
    assert git(rectoversos, "rev-parse", "HEAD") == head
    assert "Bea's own edit" in git(rectoversos, "diff", "--", "acme/blog/2026-10-28-plan.md")



def test_a_door_resolve_that_lost_the_race_to_a_resolve_commits_nothing_not_even_what_another_hand_left(
        box, browser, rectoversos, monkeypatch):
    """The door checks the thread is open before it writes; a page resolved it in between, so its write changes
    nothing (8.11)."""
    import types
    from helpers import call
    from sheafmd import mcp
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("First"))
    cid = box.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text), "block": i, "start": 0,
                                  "end": 5, "quote": "First", "body": "Is this right?"}, member=CAL).json()["id"]
    assert box.post("/_/comment", {"doc": DOC, "op": "status", "id": cid, "status": "resolved",
                                   "hash": md_hash(text)}, member=CAL).status == 200
    box.hub.commits.settle()
    f.write_text(f.read_text(encoding="utf-8") + "\nTyped in an editor, not saved by Bea.\n", encoding="utf-8")
    head = git(rectoversos, "rev-parse", "HEAD")
    monkeypatch.setattr(mcp.Door, "_comment", lambda self, *a, **k: types.SimpleNamespace(status="open"))
    is_error, got = call(browser, "resolve", as_name="Claude", doc=DOC, id=cid)
    assert not is_error, got
    box.hub.commits.settle()
    assert git(rectoversos, "rev-parse", "HEAD") == head
    assert "Typed in an editor" in git(rectoversos, "diff", "--", "acme/blog/2026-10-28-plan.md")


def _first_comment(box, rectoversos):
    f = rectoversos / "acme" / "blog" / "2026-10-28-plan.md"
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("First"))
    cid = box.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text), "block": i, "start": 0,
                                  "end": 5, "quote": "First", "body": "Is this right?"}, member=CAL).json()["id"]
    box.hub.commits.settle()
    return text, cid


def test_a_comment_request_that_changes_something_commits_it(box, rectoversos):
    """The twin of the no-op test: a status that really changes, and an edit of the body, each take a commit.
    A `wrote` that was always false would pass the no-op tests and fail here."""
    text, cid = _first_comment(box, rectoversos)
    for payload in ({"op": "status", "id": cid, "status": "resolved"},
                    {"op": "edit", "id": cid, "body": "Is this really right?"}):
        head = git(rectoversos, "rev-parse", "HEAD")
        r = box.post("/_/comment", {"doc": DOC, "hash": md_hash(text), **payload}, member=CAL)
        assert r.status == 200, r.text
        box.hub.commits.settle()
        assert git(rectoversos, "rev-parse", "HEAD") != head, payload


@pytest.mark.parametrize("open_in_hub", [True, False], ids=["page open", "no live entry"])
def test_a_door_reply_and_a_door_resolve_that_change_something_commit_them(box, browser, rectoversos, open_in_hub):
    from helpers import call
    _, cid = _first_comment(box, rectoversos)
    if not open_in_hub:
        box.hub.entries.clear()         # the door then writes the file itself, with no live document
    for tool, args in (("reply", {"text": "Yes, it is."}), ("resolve", {})):
        head = git(rectoversos, "rev-parse", "HEAD")
        is_error, got = call(browser, tool, as_name="Claude", doc=DOC, id=cid, **args)
        assert not is_error, got
        box.hub.commits.settle()
        assert git(rectoversos, "rev-parse", "HEAD") != head, tool


# ── a remote branch that was rewritten (the rewrite guard) ───────────────────
SAW = "the remote's branch no longer holds what it held"


def last_seen(repo):
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", "refs/sheaf/last-seen/main"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def force_pushed(tmp_path, remote, name="rewriter"):
    """The remote's `main` rewritten away from the box: back to its first commit, which it keeps, and one commit
    of its own on it. Gives the new tip."""
    away = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(remote), str(away)], check=True, capture_output=True)
    git(away, "config", "user.name", "Ada")
    git(away, "config", "user.email", "ada@example.com")
    git(away, "reset", "-q", "--hard", git(away, "rev-list", "--max-parents=0", "HEAD").strip())
    (away / "rewritten.txt").write_text("after the rewrite\n", encoding="utf-8")
    git(away, "add", "-A")
    git(away, "commit", "-q", "-m", "after the rewrite")
    git(away, "push", "-q", "--force", "origin", "HEAD:main")
    return git(away, "rev-parse", "HEAD").strip()


@pytest.fixture
def guarded(box, rectoversos, remote):
    """`box` with the guard on, as a hub with a private root has it, after one save that went out: the hub has seen
    the remote's tip."""
    box.hub.commits._refuse = lambda: True
    edit(box, rectoversos)
    assert len(pushed(box, remote)) == 2
    assert last_seen(rectoversos) == git(remote, "rev-parse", "main").strip()
    return box


def poll_now(box, rectoversos):
    root = next(r for r in box.hub.roots.all() if r.path == rectoversos)
    box.hub.commits._push_later(git(rectoversos, "rev-parse", "--absolute-git-dir").strip(), root, root.name, wrote=False)
    assert box.hub.commits.settle()


def test_rewrite_that_shares_a_base_is_refused(guarded, rectoversos, remote, tmp_path):
    tip = force_pushed(tmp_path, remote)
    edit(guarded, rectoversos, words="Second, after the rewrite.")
    assert guarded.hub.commits.settle()
    assert git(remote, "rev-parse", "main").strip() == tip                 # nothing replayed on it, nothing pushed
    assert "Second, after the rewrite." in (rectoversos / "acme/blog/2026-10-28-plan.md").read_text(encoding="utf-8")
    assert not (rectoversos / "rewritten.txt").exists()                         # and nothing taken in
    (row,) = rows("push-diverged")
    assert row["error"] == SAW and row["doc"] == DOC


def test_a_rewrite_is_replayed_when_the_guard_is_off(box, rectoversos, remote, tmp_path):
    edit(box, rectoversos)
    assert len(pushed(box, remote)) == 2
    tip = force_pushed(tmp_path, remote)
    edit(box, rectoversos, words="Second, after the rewrite.")
    assert box.hub.commits.settle()
    assert git(remote, "rev-parse", "main").strip() != tip and rows("push-diverged") == []
    assert last_seen(rectoversos) == ""


def test_rewrite_refused_on_second_poll(guarded, rectoversos, remote, tmp_path):
    before = last_seen(rectoversos)
    tip = force_pushed(tmp_path, remote)
    for _ in range(2):
        poll_now(guarded, rectoversos)
        assert git(remote, "rev-parse", "main").strip() == tip
        assert not (rectoversos / "rewritten.txt").exists()
    edit(guarded, rectoversos, words="Second, a third try.")
    assert guarded.hub.commits.settle()
    assert git(remote, "rev-parse", "main").strip() == tip
    assert rows("push-diverged") and all(r["error"] == SAW for r in rows("push-diverged"))
    assert last_seen(rectoversos) == before


def test_rewrite_refusal_is_per_repo(guarded, rectoversos, remote, tmp_path):
    other_remote = tmp_path / "other.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(other_remote)], check=True)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(other_remote), str(other)], check=True, capture_output=True)
    git(other, "config", "user.name", "the box")
    git(other, "config", "user.email", "box@example.com")
    (other / ".sheaf.toml").write_text('commit = true\npush = true\n', encoding="utf-8")
    (other / "a.md").write_text("one\n", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "other first")
    git(other, "push", "-q", "origin", "HEAD:main")
    root = guarded.hub.roots.for_document(other / "a.md")
    guarded.hub.commits.seed([root])
    assert last_seen(other) == git(other_remote, "rev-parse", "main").strip()
    tip = force_pushed(tmp_path, remote)
    (other / "a.md").write_text("two\n", encoding="utf-8")
    git(other, "commit", "-q", "-am", "other second")
    guarded.hub.commits._push_later(git(other, "rev-parse", "--absolute-git-dir").strip(), root, root.name)
    poll_now(guarded, rectoversos)
    assert git(other_remote, "log", "-1", "--format=%s", "main").strip() == "other second"
    assert git(remote, "rev-parse", "main").strip() == tip


def test_manual_fetch_does_not_disarm_guard(guarded, rectoversos, remote, tmp_path):
    tip = force_pushed(tmp_path, remote)
    git(rectoversos, "fetch", "-q", "origin")                                   # a person's fetch: origin/main is the tip
    assert git(rectoversos, "rev-parse", "origin/main").strip() == tip
    poll_now(guarded, rectoversos)
    edit(guarded, rectoversos, words="Second, after a fetch.")
    assert guarded.hub.commits.settle()
    assert git(remote, "rev-parse", "main").strip() == tip and not (rectoversos / "rewritten.txt").exists()
    assert rows("push-diverged")[0]["error"] == SAW


def test_guard_seeded_at_start(box, rectoversos, remote, tmp_path):
    box.hub.commits._refuse = lambda: True
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    git(rectoversos, "fetch", "-q", "origin")
    assert last_seen(rectoversos) == ""                                         # no pull has passed yet
    box.hub.commits.seed(box.hub.roots.all())
    assert last_seen(rectoversos) == git(remote, "rev-parse", "main").strip()
    tip = force_pushed(tmp_path, remote)
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    assert git(remote, "rev-parse", "main").strip() == tip
    assert rows("push-diverged")[0]["error"] == SAW


def test_deleted_remote_branch_guarded(guarded, rectoversos, remote):
    git(remote, "update-ref", "-d", "refs/heads/main")
    edit(guarded, rectoversos, words="Second, with no branch to push to.")
    assert guarded.hub.commits.settle()
    assert subprocess.run(["git", "-C", str(remote), "rev-parse", "-q", "--verify", "refs/heads/main"],
                          capture_output=True).returncode != 0            # not pushed back
    assert rows("push-diverged")[0]["error"] == SAW


def test_fast_forward_unaffected(guarded, rectoversos, remote, tmp_path):
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    edit(guarded, rectoversos, words="Second, over a README.")                   # the remote moved on, the hub too
    assert len(pushed(guarded, remote)) == 4
    assert (rectoversos / "README.md").exists() and rows("push-diverged") == []
    assert last_seen(rectoversos) == git(remote, "rev-parse", "main").strip() == git(rectoversos, "rev-parse", "HEAD").strip()
    merged_on_github(tmp_path, remote, {"README.md": "# Rectoversos\n"}, "a README, again")
    poll_now(guarded, rectoversos)                                              # and a remote ahead alone
    assert (rectoversos / "README.md").read_text(encoding="utf-8") == "# Rectoversos\n" and rows("push-diverged") == []
    assert last_seen(rectoversos) == git(remote, "rev-parse", "main").strip()


def test_a_branch_switched_after_the_push_gets_the_ref_of_the_branch_pushed(guarded, rectoversos, remote, monkeypatch):
    from sheafmd.hub import commits
    git(rectoversos, "branch", "draft")
    real = commits._git

    def then_switch(folder, *args, **kw):
        r = real(folder, *args, **kw)
        if args[:1] == ("push",):
            git(rectoversos, "checkout", "-q", "draft")             # after the push, before the ref is written
        return r
    monkeypatch.setattr(commits, "_git", then_switch)
    edit(guarded, rectoversos, words="Second, on the way to a branch switch.")
    assert guarded.hub.commits.settle()
    assert last_seen(rectoversos) == git(remote, "rev-parse", "main").strip()
    assert subprocess.run(["git", "-C", str(rectoversos), "rev-parse", "-q", "--verify", "refs/sheaf/last-seen/draft"],
                          capture_output=True).returncode != 0


def test_a_remote_rewound_between_the_fetch_and_the_push_is_not_pushed_over(guarded, rectoversos, remote, monkeypatch):
    """Rewound to an ancestor of what the hub sends: a plain push would be a fast-forward and put it all back."""
    pulled = guarded.hub.commits._pull
    rewound = []

    def then_rewind(root, *args, **kw):
        go = pulled(root, *args, **kw)
        if go and not rewound:
            git(remote, "update-ref", "refs/heads/main", "main~1")
            rewound.append(git(remote, "rev-parse", "main").strip())
        return go
    monkeypatch.setattr(guarded.hub.commits, "_pull", then_rewind)
    edit(guarded, rectoversos, words="Second, over a rewind.")
    assert guarded.hub.commits.settle()
    assert git(remote, "rev-parse", "main").strip() == rewound[0]
    assert rows("push-failed")


def test_what_is_pushed_is_the_commit_read_not_where_head_has_moved_to(guarded, rectoversos, remote, monkeypatch):
    from sheafmd.hub import commits
    first = git(rectoversos, "rev-list", "--max-parents=0", "HEAD").strip()
    git(rectoversos, "branch", "draft", first)
    real = commits._git
    moved = []

    def then_switch(folder, *args, **kw):
        if args[:1] == ("push",) and not moved:
            moved.append(git(rectoversos, "rev-parse", "HEAD").strip())
            git(rectoversos, "checkout", "-q", "draft")             # between the read of HEAD and the push
        return real(folder, *args, **kw)
    monkeypatch.setattr(commits, "_git", then_switch)
    edit(guarded, rectoversos, words="Second, with a switch before the push.")
    assert guarded.hub.commits.settle()
    assert git(remote, "rev-parse", "main").strip() == moved[0]            # main got main's commit, not draft's


def test_a_ref_behind_an_unchanged_remote_catches_up_at_the_next_poll(guarded, rectoversos, remote):
    git(rectoversos, "update-ref", "refs/sheaf/last-seen/main", "main~1")
    poll_now(guarded, rectoversos)
    assert last_seen(rectoversos) == git(remote, "rev-parse", "main").strip()


def test_a_root_registered_after_the_start_is_guarded_from_what_the_clone_had_fetched(box, rectoversos, remote, tmp_path):
    box.hub.commits._refuse = lambda: True
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    git(rectoversos, "fetch", "-q", "origin")
    tip = force_pushed(tmp_path, remote)
    assert last_seen(rectoversos) == ""
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    assert git(remote, "rev-parse", "main").strip() == tip
    assert rows("push-diverged")[0]["error"] == SAW


def test_a_repo_met_after_the_start_is_refused_on_its_second_poll_too(box, rectoversos, remote, tmp_path):
    box.hub.commits._refuse = lambda: True
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    git(rectoversos, "fetch", "-q", "origin")
    tip = force_pushed(tmp_path, remote)
    for _ in range(2):
        poll_now(box, rectoversos)
        assert not (rectoversos / "rewritten.txt").exists()
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    assert git(remote, "rev-parse", "main").strip() == tip
    assert last_seen(rectoversos) not in ("", tip)                       # kept where it was seeded


def test_a_reset_between_the_pull_and_the_push_is_not_forced_over_the_remote(guarded, rectoversos, remote, tmp_path,
                                                                            monkeypatch):
    first = git(rectoversos, "rev-list", "--max-parents=0", "HEAD").strip()
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    pulled = guarded.hub.commits._pull

    def then_reset(root, *args, **kw):
        go = pulled(root, *args, **kw)
        git(rectoversos, "reset", "-q", "--hard", first)
        (rectoversos / "own.txt").write_text("a person's own\n", encoding="utf-8")
        git(rectoversos, "add", "-A")
        git(rectoversos, "commit", "-q", "-m", "a person's own")
        return go
    monkeypatch.setattr(guarded.hub.commits, "_pull", then_reset)
    edit(guarded, rectoversos, words="Second, over a reset.")
    assert guarded.hub.commits.settle()
    assert git(remote, "log", "-1", "--format=%s", "main").strip() == "a README"       # not forced over
    assert rows("push-failed")


NEW = "rectoversos/acme/blog/2026-10-30-plan.md"


def roomy_git(monkeypatch, seconds=600):
    """Every git of the hub given `seconds` instead of `GIT_SECONDS` and `PUSH_SECONDS`, and the poll the same to settle
    (ticket 208): on a loaded machine a git that runs out of time ends a pull, and one in the rename look (`_renames`)
    drops the Forward without a row. A limit, never a timing: nothing here reads the clock to time a computation."""
    from sheafmd.hub import commits
    monkeypatch.setattr(commits, "GIT_SECONDS", seconds)
    monkeypatch.setattr(commits, "PUSH_SECONDS", seconds)
    monkeypatch.setitem(commits._git.__kwdefaults__, "seconds", seconds)   # bound when `_git` was defined

    def poll(box, rectoversos):
        root = next(r for r in box.hub.roots.all() if r.path == rectoversos)
        box.hub.commits._push_later(git(rectoversos, "rev-parse", "--absolute-git-dir").strip(), root, root.name,
                                    wrote=False)
        assert box.hub.commits.settle(timeout=seconds * 2)
    return poll


def renamed_on_github(tmp_path, remote, old: str, new: str):
    """`old` renamed to `new` away from the box and pushed to `remote`, as a PR merged on GitHub would."""
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")    # makes the away clone
    away = tmp_path / "github"
    git(away, "mv", old, new)
    git(away, "commit", "-q", "-m", "rename the plan")
    git(away, "push", "-q", "origin", "HEAD:main")


def test_a_rename_that_arrives_on_a_pull_writes_a_forward_and_carries_the_versions(box, rectoversos, remote, tmp_path, lock_order,
                                                                                    monkeypatch):
    """Ticket 17: a repo page moves only by git; when a pull shows the rename, the hub writes a Forward from the old
    address to the new one, and the versions kept under the old address are the new page's."""
    poll = roomy_git(monkeypatch)
    edit(box, rectoversos)
    assert box.hub.commits.settle(timeout=1200)  # ticket 208: the edit is out before the rename is pushed
    pushed(box, remote)
    root = box.hub.roots.get("rectoversos")
    versions = box.hub._versions_of(root) or box.hub.versions
    kept = md_hash((rectoversos / "acme" / "blog" / "2026-10-28-plan.md").read_text(encoding="utf-8"))
    assert versions.get(DOC, kept) is not None
    renamed_on_github(tmp_path, remote, "acme/blog/2026-10-28-plan.md", "acme/blog/2026-10-30-plan.md")
    poll(box, rectoversos)                      # ticket 208: no git runs out of time under load
    assert (rectoversos / "acme" / "blog" / "2026-10-30-plan.md").exists()
    assert box.hub.forwards.follow(DOC) == NEW
    assert versions.get(NEW, kept) is not None and versions.get(DOC, kept) is None
    assert box.hub.forwards.entry(DOC)["by"] == "git"


def test_a_pull_without_a_rename_writes_no_forward(box, rectoversos, remote, tmp_path):
    merged_on_github(tmp_path, remote, {"README.md": "# The rectoversos\n"}, "a README")
    poll_now(box, rectoversos)
    assert box.hub.forwards.snapshot() == {}


def test_a_rename_of_a_file_that_is_not_a_page_writes_no_forward(box, rectoversos, remote, tmp_path):
    merged_on_github(tmp_path, remote, {"notes.txt": "x\n"}, "a note")
    away = tmp_path / "github"
    git(away, "mv", "notes.txt", "notes-2.txt")
    git(away, "commit", "-q", "-m", "rename the note")
    git(away, "push", "-q", "origin", "HEAD:main")
    poll_now(box, rectoversos)
    assert box.hub.forwards.snapshot() == {}


def test_a_rename_in_a_pull_the_hub_refuses_writes_no_forward(box, rectoversos, remote, tmp_path):
    (rectoversos / "projects.toml").write_text(ONLY_BEA + "# the person's own change\n", encoding="utf-8")
    renamed_on_github(tmp_path, remote, "acme/blog/2026-10-28-plan.md", "acme/blog/2026-10-30-plan.md")
    away = tmp_path / "github"
    (away / "projects.toml").write_text(ONLY_BEA, encoding="utf-8")
    git(away, "commit", "-qam", "Cal leaves")
    git(away, "push", "-q", "origin", "HEAD:main")
    poll_now(box, rectoversos)
    assert (rectoversos / "acme" / "blog" / "2026-10-28-plan.md").exists()
    assert box.hub.forwards.snapshot() == {}


def rename_pull(box, rectoversos, remote, tmp_path):
    renamed_on_github(tmp_path, remote, "acme/blog/2026-10-28-plan.md", "acme/blog/2026-10-30-plan.md")
    poll_now(box, rectoversos)


def test_a_git_rename_carries_the_page_under_the_name_locks_of_both_addresses(box, rectoversos, remote, tmp_path, monkeypatch):
    """As a Move does (moves.py): what the hub keeps of the page is carried with both names held, so a save on either does not
    come between the pull and the carrying."""
    import contextlib
    from sheafmd.hub import place
    held, seen, real = [], [], place.held

    @contextlib.contextmanager
    def spy(hub, address):
        with real(hub, address) as got:
            held.append(address)
            yield got
        held.remove(address)

    monkeypatch.setattr(place, "held", spy)
    moved = box.hub.moved_page
    monkeypatch.setattr(box.hub, "moved_page", lambda old, new, by: (seen.append(sorted(held)), moved(old, new, by)))
    rename_pull(box, rectoversos, remote, tmp_path)
    assert seen == [sorted([DOC, NEW])]


def test_a_git_rename_under_a_running_tell_marks_the_address_and_says_so_in_the_diagnostics(box, rectoversos, remote, tmp_path, monkeypatch):
    """A rename cannot be refused, as a Move is: no Tell starts on the old address meanwhile, the Forward is written all the
    same, and a Tell already running is a row, since its answer then meets a page that is gone from where it began."""
    seen = []
    monkeypatch.setattr(box.hub, "tell_live", lambda address: address == DOC)
    moved = box.hub.moved_page
    monkeypatch.setattr(box.hub, "moved_page", lambda old, new, by: (seen.append(DOC in box.hub.moving), moved(old, new, by)))
    rename_pull(box, rectoversos, remote, tmp_path)
    assert seen == [True] and DOC not in box.hub.moving
    assert box.hub.forwards.follow(DOC) == NEW
    (row,) = rows("rename-under-tell")
    assert row["doc"] == DOC


def test_a_git_rename_onto_an_address_that_forwards_elsewhere_is_a_row(box, rectoversos, remote, tmp_path):
    """A Forward at the new address is dropped, the page being there (Forwards.add); old links to it then open this page, which
    a git rename cannot be refused for: it is written down."""
    box.hub.forwards.add(NEW, "rectoversos/elsewhere.md", "someone")
    rename_pull(box, rectoversos, remote, tmp_path)
    assert box.hub.forwards.follow(DOC) == NEW and box.hub.forwards.follow(NEW) is None
    (row,) = rows("forward-replaced")
    assert row["doc"] == NEW and row["was"] == "rectoversos/elsewhere.md"


def test_the_write_log_of_a_renamed_page_is_at_its_new_address_alone(box, rectoversos, remote, tmp_path):
    edit(box, rectoversos)
    pushed(box, remote)
    rename_pull(box, rectoversos, remote, tmp_path)
    assert box.hub.writes.lines(DOC) == []
    assert [w.via for w in box.hub.writes.lines(NEW)][-1] == "pull"


def test_a_read_of_the_renames_that_times_out_is_no_renames_and_the_pull_goes_through(box, rectoversos, remote, tmp_path, monkeypatch):
    """The Write log's window of a pull closes however the pull ends: the look for renames is no reason to leave it open."""
    from sheafmd.hub import commits
    real = commits._git

    def slow(folder, *args, **kw):
        if "--diff-filter=R" in args:
            raise subprocess.TimeoutExpired(args, 1)
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", slow)
    rename_pull(box, rectoversos, remote, tmp_path)
    assert (rectoversos / "acme" / "blog" / "2026-10-30-plan.md").exists()
    assert box.hub.forwards.snapshot() == {}
    assert not box.hub.writes._pulling


def test_a_git_rename_between_two_roots_of_a_repo_writes_no_forward_and_is_a_row(box, rectoversos, remote, tmp_path, monkeypatch):
    """9.11: no move between roots. A repo may hold several roots; a rename from one to another is no Forward, and the stores
    of the page stay where they are."""
    real = box.hub._page_of
    monkeypatch.setattr(box.hub, "_page_of", lambda path: real(path).replace("rectoversos/", "elsewhere/", 1)
                        if path.name == "2026-10-30-plan.md" else real(path))
    rename_pull(box, rectoversos, remote, tmp_path)
    assert box.hub.forwards.snapshot() == {}
    (row,) = rows("rename-between-roots")
    assert row["doc"] == DOC and row["to"].startswith("elsewhere/")


# ── ticket 162: what a commit is made against, read when it is made ──────────────────────────────

def side_repo(parent, name="side", toml='commit = true\n', init=True):
    """A folder with one document, `a.md`, of two blocks; a git repo with that committed when `init`."""
    folder = parent / name
    folder.mkdir(parents=True)
    (folder / ".sheaf.toml").write_text(toml, encoding="utf-8")
    (folder / "a.md").write_text("One.\n\nTwo.\n", encoding="utf-8")
    if init:
        git_init(folder)
    return folder


def git_init(folder):
    subprocess.run(["git", "init", "-q", "-b", "main", str(folder)], check=True)
    git(folder, "config", "user.name", "the box")
    git(folder, "config", "user.email", "box@example.com")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")


def save_two(box, address, folder, words="Two, edited."):
    text = (folder / "a.md").read_text(encoding="utf-8")
    r = box.post("/_/save", {"doc": address, "hash": md_hash(text), "edits": [{"i": 1, "html": f"<p>{words}</p>"}]},
                 member=BEA)
    assert r.status == 200, r.text


def test_a_commit_never_lands_in_a_root_that_took_the_name_of_one_forgotten_under_the_write(
        box, rectoversos, remote, tmp_path, monkeypatch):
    """8.11: the root a write went to is the one its commit goes to. `sheaf roots forget` and a new root of the same name,
    between the write and its commit, commit and push the same path of the other repo."""
    from sheafmd.hub import place
    intruder = tmp_path / "again" / "rectoversos"
    intruder.mkdir(parents=True)
    (intruder / ".sheaf.toml").write_text("commit = true\n", encoding="utf-8")
    doc = intruder / "acme" / "blog" / "2026-10-28-plan.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("Not the plan.\n", encoding="utf-8")
    git_init(intruder)
    doc.write_text("Not the plan, changed by hand.\n", encoding="utf-8")        # a commit of this path would take it
    first = git(intruder, "rev-parse", "HEAD")
    real = place.owns

    def swapped(hub, address):
        monkeypatch.setattr(place, "owns", real)
        hub.forget_root("rectoversos")
        assert hub.roots.for_document(doc).name == "rectoversos"
        return real(hub, address)

    monkeypatch.setattr(place, "owns", swapped)
    edit(box, rectoversos)
    assert box.hub.commits.settle()
    assert git(intruder, "rev-parse", "HEAD") == first
    assert git(intruder, "log", "--oneline").count("\n") == 1
    assert len(pushed(box, remote)) == 1                     # nor was the page's own root committed after it was forgotten
    assert rows("commit-refused")


def test_a_folder_registered_before_git_init_commits_once_it_is_a_repo(box, rectoversos, tmp_path):
    """The root's `git` is read when the write is committed, not kept from the day it was registered."""
    side = side_repo(tmp_path, init=False)
    box.hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                                 "proxy_user": box.hub.proxy.proxy_user,
                                 "members": {BEA: {"name": "Bea", "email": "bea@example.com", "short": "bea",
                                                   "roots": [str(rectoversos), str(side)]}}}, "the test")
    root = box.hub.roots.for_document(side / "a.md")
    assert not root.git
    git_init(side)
    save_two(box, "side/a.md", side)
    assert box.hub.commits.settle()
    assert git(side, "log", "-1", "--format=%s").strip() == "edit: a.md"
    assert not rows("commit-not-git")


def test_a_page_open_when_versions_moves_into_the_root_keeps_its_versions_where_the_root_now_says(
        box, rectoversos, remote):
    """4.4: `versions` is read at each write. The commit stages the folder the config names now, so the page writes it."""
    (rectoversos / ".sheaf.toml").write_text("commit = true\npush = true\n", encoding="utf-8")
    git(rectoversos, "commit", "-q", "-am", "versions in the state folder")
    edit(box, rectoversos, words="Second, with the versions in the state folder.")
    (rectoversos / ".sheaf.toml").write_text('versions = "root"\ncommit = true\npush = true\n', encoding="utf-8")
    git(rectoversos, "commit", "-q", "-am", "versions in the root")
    edit(box, rectoversos, words="Second, with the versions in the root.")
    assert box.hub.commits.settle()
    assert versions_files(rectoversos)
    assert any(f.startswith(".sheaf/") for f in pushed(box, remote)[0][1])


def test_a_rename_whose_stores_fail_before_the_move_is_one_row_for_its_pair_and_the_pull_goes_on(box, rectoversos, remote, tmp_path, monkeypatch):
    """The checks and the mark of an address are inside the pair's own try: a failure there is `move-store-failed` for that
    pair, never `write-log-failed` of the whole pull, and nothing stays marked as moving."""
    def broken(address):
        raise RuntimeError("tell state unreadable")
    monkeypatch.setattr(box.hub, "tell_live", broken)
    rename_pull(box, rectoversos, remote, tmp_path)
    (row,) = rows("move-store-failed")
    assert row["doc"] == NEW
    assert rows("write-log-failed") == []
    assert DOC not in box.hub.moving


# ── ticket 181 A: a create commits to the root it captured, not to the one its name now names ────────

def test_a_create_never_commits_into_a_root_that_took_the_name_of_the_one_it_wrote_in(
        box, browser, rectoversos, remote, tmp_path, monkeypatch):
    """8.11: `create` writes into the root it resolved first. Forgotten, and its name taken by another folder, between
    that and the read of the commit's root id, the commit must not go into the other repo."""
    from helpers import call

    from sheafmd import mcp as mcp_mod
    intruder = tmp_path / "again" / "rectoversos"
    intruder.mkdir(parents=True)
    (intruder / ".sheaf.toml").write_text("commit = true\n", encoding="utf-8")
    other = intruder / "acme" / "blog" / "new.md"
    other.parent.mkdir(parents=True)
    other.write_text("Not this page.\n", encoding="utf-8")
    git_init(intruder)
    other.write_text("Not this page, changed by hand.\n", encoding="utf-8")     # a commit of this path would take it
    first = git(intruder, "rev-parse", "HEAD")
    real = mcp_mod._check_comments

    def swapped(*a, **k):
        monkeypatch.setattr(mcp_mod, "_check_comments", real)
        box.hub.forget_root("rectoversos")
        assert box.hub.roots.for_document(other).name == "rectoversos"
        return real(*a, **k)

    monkeypatch.setattr(mcp_mod, "_check_comments", swapped)
    is_error, got = call(browser, "create", doc="rectoversos/acme/blog/new.md", text="A new page.\n")
    assert not is_error, got
    assert box.hub.commits.settle()
    assert git(intruder, "rev-parse", "HEAD") == first
    assert rows("commit-refused")


def _an_intruder_after_the_root_id(box, rectoversos, tmp_path, monkeypatch):
    """A folder that holds the same page, under the same root name; it takes the name of the rectoversos root just
    after a writer reads its root id (8.11). Gives the intruder's copy of the page, its text and its head."""
    intruder = tmp_path / "again" / "rectoversos"
    other = intruder / "acme" / "blog" / "2026-10-28-plan.md"
    other.parent.mkdir(parents=True)
    other.write_text((rectoversos / "acme" / "blog" / "2026-10-28-plan.md").read_text(encoding="utf-8"),
                     encoding="utf-8")
    (intruder / ".sheaf.toml").write_text("commit = true\n", encoding="utf-8")
    (intruder / "projects.toml").write_text((rectoversos / "projects.toml").read_text(encoding="utf-8"),
                                            encoding="utf-8")
    git_init(intruder)
    real = box.hub.root_id_of

    def swapped(address):
        monkeypatch.setattr(box.hub, "root_id_of", real)
        rid = real(address)
        box.hub.forget_root("rectoversos")
        assert box.hub.roots.for_document(other).name == "rectoversos"
        return rid

    monkeypatch.setattr(box.hub, "root_id_of", swapped)
    return other, other.read_text(encoding="utf-8"), git(intruder, "rev-parse", "HEAD")


@pytest.mark.parametrize("tool", ["reply", "update"])
def test_a_door_write_never_lands_in_a_root_that_took_the_name_after_its_root_id_was_read(
        box, browser, rectoversos, tmp_path, monkeypatch, tool):
    """8.2, 8.11: a door write reads the id of its root, then writes under the name's lock. A root forgotten and its name
    taken by another folder in between must not take the write: its file stays as it was, and nothing is left there
    uncommitted."""
    from helpers import call
    _, cid = _first_comment(box, rectoversos)
    box.hub.entries.clear()         # the door writes the file itself, as the root is forgotten with its entries anyway
    is_error, got = call(browser, "read", doc=DOC)
    assert not is_error, got
    other, before, head = _an_intruder_after_the_root_id(box, rectoversos, tmp_path, monkeypatch)
    if tool == "reply":
        is_error, got = call(browser, "reply", as_name="Claude", doc=DOC, id=cid, text="Yes, it is.")
    else:
        is_error, got = call(browser, "update", as_name="Claude", doc=DOC, text=got["text"] + "\nA line.\n",
                             expected_hash=got["hash"])
    assert box.hub.commits.settle()
    assert other.read_text(encoding="utf-8") == before, got
    assert git(other.parents[2], "rev-parse", "HEAD") == head
    assert is_error, got
