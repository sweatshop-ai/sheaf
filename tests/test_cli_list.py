"""`sheaf list`, `sheaf roots` and `sheaf roots forget`, against a real hub process (SPEC 8.2, 13).

`list` says, for each document rendered since the hub started, whether a tab has it open, had it
open, or never did. `roots` says which folders the hub serves and what it calls them."""
import http.client
import json
import time

import pytest

from helpers import PLAN, brand_words_in, hub_alive, http_get, key, make_repo, write
from sheafmd import paths
from sheafmd.hub import client as hubclient
from sheafmd.hub import state as hubstate
from sheafmd.hub.roots import Roots


def doc_in(folder, name="plan.md", text=PLAN):
    return write(folder / name, text)


def open_keep_and_drop(sheaf, tmp_path):
    """Two documents, in the folders `keep` and `drop`, each opened once: two roots on the hub."""
    keep, drop = doc_in(tmp_path / "keep"), doc_in(tmp_path / "drop")
    sheaf("open", keep, "--no-browser")
    sheaf("open", drop, "--no-browser")
    return keep, drop


@pytest.fixture
def tab(port, opened_browser):
    """A browser tab on a document: opens its event stream with a cookie the way a page does.
    `tab(address)` -> the open stream; close it with `.close()`. The hub answers a stream with
    `Connection: close`, so `http.client` hands the socket to the response and closes it when the
    response is dropped: a tab is open for as long as the test holds the response, so that is
    what this returns and keeps. One browser signs in once, with the one-time link `sheaf open`
    gave it (9.3), and its tabs share the cookie it got."""
    opened = []
    cookies = []

    def open_tab(address):
        if not cookies:
            sign_in = opened_browser.opened[-1].split(str(port), 1)[1]
            resp, _ = http_get(port, sign_in)
            cookies.append(resp.getheader("Set-Cookie").split(";")[0])
        jar = cookies[0]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", f"/_/live?doc={address}", headers={"Cookie": jar})
        r = c.getresponse()
        r.fp.readline()
        opened.append(r)
        return r
    yield open_tab
    for r in opened:
        r.close()


def until_listed(sheaf, ending, seconds=5):
    """The output of `sheaf list` once it ends with `ending`: the hub notices a closed tab
    within a second, not at once."""
    deadline = time.time() + seconds
    out = sheaf("list").out
    while time.time() < deadline and not out.endswith(ending):
        time.sleep(0.1)
        out = sheaf("list").out
    return out


# ── sheaf list ───────────────────────────────────────────────────────────────

def test_list_with_no_hub_says_so_and_starts_none(sheaf, port):
    r = sheaf("list")
    assert r.code == 0 and r.out == "  no hub is running\n" and r.err == ""
    assert not hub_alive(port)


def test_list_on_a_hub_that_rendered_nothing_says_so(sheaf, port):
    assert sheaf("start").code == 0
    r = sheaf("list")
    assert r.code == 0 and r.out == "  nothing has been rendered since the hub started\n"


def test_a_document_nobody_has_opened_is_never_opened(sheaf, opened_browser, work, port):
    f = doc_in(work)
    sheaf("open", f, "--no-browser")
    r = sheaf("list")
    assert r.code == 0 and r.err == ""
    assert r.out == (f"  http://127.0.0.1:{port}/work/plan.md\n"
                     f"    {f.resolve()} · never opened\n")


def test_a_document_in_a_tab_says_how_many_tabs_have_it(sheaf, opened_browser, tab, work, port):
    f = doc_in(work)
    sheaf("open", f)
    first = tab("work/plan.md")
    assert sheaf("list").out.endswith(f"{f.resolve()} · 1 tab open\n")
    second = tab("work/plan.md")
    assert sheaf("list").out.endswith(f"{f.resolve()} · 2 tabs open\n")
    first.close()
    second.close()


def test_a_tab_stays_counted_for_as_long_as_the_test_holds_it_open(sheaf, opened_browser, tab, work, port):
    """The hub notices a closed tab within a second (`until_listed`), so a tab still counted when
    that second is over is held open, not merely not yet noticed; and `.close()` is what ends it."""
    f = doc_in(work)
    sheaf("open", f)
    held = tab("work/plan.md")
    deadline = time.time() + 1
    while time.time() < deadline:
        assert sheaf("list").out.endswith(f"{f.resolve()} · 1 tab open\n")
        time.sleep(0.05)
    held.close()
    assert until_listed(sheaf, "· opened, now closed\n").endswith(f"{f.resolve()} · opened, now closed\n")


def test_a_document_whose_tabs_were_closed_says_opened_now_closed(sheaf, opened_browser, tab, work, port):
    f = doc_in(work)
    sheaf("open", f)
    tab("work/plan.md").close()
    assert until_listed(sheaf, "· opened, now closed\n").endswith(f"{f.resolve()} · opened, now closed\n")


def test_a_new_render_makes_it_never_opened_again(sheaf, opened_browser, tab, work, port):
    f = doc_in(work)
    sheaf("open", f)
    tab("work/plan.md").close()
    until_listed(sheaf, "· opened, now closed\n")
    sheaf("open", f, "--no-browser")
    assert sheaf("list").out.endswith("· never opened\n")


def test_only_what_was_rendered_is_listed_not_everything_in_the_roots(sheaf, opened_browser, work, port):
    rendered = doc_in(work, "rendered.md")
    doc_in(work, "other.md")
    sheaf("open", rendered, "--no-browser")
    out = sheaf("list").out
    assert "rendered.md" in out and "other.md" not in out


def test_every_root_is_listed_and_a_gitignored_document_that_was_named_is_too(
        sheaf, opened_browser, tmp_path, port):
    repo = make_repo(tmp_path / "proj")
    doc_in(repo, ".gitignore", "drafts/\n")
    ignored = doc_in(repo, "drafts/x.md")
    loose = doc_in(tmp_path / "scratch", "z.md")
    sheaf("open", ignored, "--no-browser")
    sheaf("open", loose, "--no-browser")
    out = sheaf("list").out
    assert f"http://127.0.0.1:{port}/proj/drafts/x.md\n    {ignored.resolve()} · never opened" in out
    assert f"http://127.0.0.1:{port}/scratch/z.md\n    {loose.resolve()} · never opened" in out


def test_a_restarted_hub_lists_only_what_was_rendered_since(sheaf, opened_browser, work, port):
    before, after = doc_in(work, "before.md"), doc_in(work, "after.md")
    sheaf("open", before, "--no-browser")
    assert sheaf("stop").code == 0
    sheaf("open", after, "--no-browser")
    out = sheaf("list").out
    assert "after.md" in out and "before.md" not in out


def test_list_prints_no_key_and_none_of_the_brand_words(sheaf, opened_browser, work, tmp_path, port):
    sheaf("open", doc_in(work), "--no-browser")
    r = sheaf("list")
    assert key() not in r.out + r.err and brand_words_in(r.out + r.err, tmp_path) == []


# ── sheaf roots ──────────────────────────────────────────────────────────────

def test_roots_with_none_says_how_one_appears(sheaf, port):
    r = sheaf("roots")
    assert r.code == 0 and r.err == ""
    assert r.out == "  no roots yet; a folder becomes one when a document in it is opened\n"
    assert not hub_alive(port)


def test_roots_lists_each_root_with_its_folder_and_survives_a_restart(sheaf, opened_browser, tmp_path, port):
    one, two = make_repo(tmp_path / "a" / "site"), make_repo(tmp_path / "b" / "site")
    loose = tmp_path / "scratch"
    for f in (doc_in(one, "x.md"), doc_in(two, "y.md"), doc_in(loose, "z.md")):
        assert sheaf("open", f, "--no-browser").code == 0
    want = (f"  scratch  {loose.resolve()}\n"
            f"  site     {one.resolve()}\n"
            f"  site-2   {two.resolve()}\n")
    assert sheaf("roots").out == want
    assert sheaf("stop").code == 0 and not hub_alive(port)
    assert sheaf("roots").out == want                  # needs no hub, and the names are the same
    assert sheaf("start").code == 0
    assert sheaf("roots").out == want
    assert sheaf("open", doc_in(two, "again.md"), "--no-browser").code == 0
    assert sheaf("roots").out == want                  # a second document is the same root


def test_a_root_whose_folder_is_gone_says_so(sheaf, opened_browser, tmp_path, port):
    f = doc_in(tmp_path / "gone")
    folder = f.parent.resolve()
    sheaf("open", f, "--no-browser")
    f.unlink()
    folder.rmdir()
    assert sheaf("roots").out == f"  gone  {folder}  (folder missing)\n"


def test_a_root_behind_a_folder_that_may_not_be_entered_is_not_missing(sheaf, tmp_path, closed):
    f = doc_in(tmp_path / "srv" / "notes")
    Roots().for_document(f)
    closed(tmp_path / "srv")
    got = sheaf("roots")
    assert (got.code, got.err) == (0, "")
    assert got.out == f"  notes  {f.parent}  (folder cannot be entered: Permission denied)\n"


def test_roots_prints_no_brand_word(sheaf, opened_browser, work, tmp_path, port):
    sheaf("open", doc_in(work), "--no-browser")
    assert brand_words_in(sheaf("roots").out, tmp_path) == []


# ── sheaf roots forget ───────────────────────────────────────────────────────

def test_forget_takes_a_root_out_of_a_running_hub_and_leaves_the_documents(
        sheaf, opened_browser, tmp_path, port):
    keep, drop = open_keep_and_drop(sheaf, tmp_path)
    r = sheaf("roots", "forget", "drop")
    assert r.code == 0 and r.err == ""
    assert r.out == f"  forgot drop ({drop.parent.resolve()}); its documents are untouched\n"
    assert drop.read_text(encoding="utf-8") == PLAN and drop.exists()
    assert sheaf("roots").out == f"  keep  {keep.parent.resolve()}\n"
    listed = sheaf("list").out
    assert "/keep/plan.md" in listed and "/drop/" not in listed
    resp, body = http_get(port, "/_/index.json", {"X-Sheaf-Key": key()})
    assert [r["name"] for r in json.loads(body)["roots"]] == ["keep"]
    assert hub_alive(port)


def test_forget_with_no_hub_edits_the_files_the_hub_would_read(sheaf, opened_browser, tmp_path, port):
    keep, drop = open_keep_and_drop(sheaf, tmp_path)
    sheaf("stop")
    assert sheaf("roots", "forget", "drop").code == 0
    assert not hub_alive(port)
    assert [r.name for r in Roots().all()] == ["keep"]
    assert sheaf("start").code == 0
    assert sheaf("roots").out == f"  keep  {keep.parent.resolve()}\n"


def first_look_clean_then(monkeypatch, second):
    """Patch `HubClient.challenge`: the first look finds no hub (None), every later one is `second(client)`,
    which answers or raises. Returns the list of looks made so far."""
    looks = []

    def challenge(self):
        looks.append(time.monotonic())
        return None if len(looks) == 1 else second(self)
    monkeypatch.setattr(hubclient.HubClient, "challenge", challenge)
    return looks


def second_look(late):
    """The late look of the `late` cases: something else holds the port, or a hub answers."""
    def look(self):
        if late == "impostor":
            raise hubclient.Impostor(self.port)
        return {"ok": True}
    return look


def start_a_hub_once(monkeypatch, cls, name, *, too_late=False):
    """Patch `cls.name` so that its first call starts a hub and waits for it: a hub that another
    process starts at that instant. That call then does what it does, or, `too_late`, answers None,
    as a look made just before the hub bound its port does. Returns a list that is not empty once
    the hub has started."""
    real, started = getattr(cls, name), []

    def first_starts_a_hub(self, *a):
        if not started:
            started.append(True)
            hubclient.spawn_hub("cli")
            assert hubclient.wait_for_start(hubclient.client(), hubclient.START_WAIT) is not None
            if too_late:
                return None
        return real(self, *a)
    monkeypatch.setattr(cls, name, first_starts_a_hub)
    return started


def roots_held(port):
    resp, body = http_get(port, "/_/index.json", {"X-Sheaf-Key": key()})
    return [r["name"] for r in json.loads(body)["roots"]]


def test_forget_with_no_hub_tells_a_hub_that_started_after_it_looked(
        sheaf, opened_browser, tmp_path, port, monkeypatch):
    """No hub answered, then one started before the files were written: it read the root and
    holds it in memory, and would write it back with its next registry save."""
    keep, drop = open_keep_and_drop(sheaf, tmp_path)
    sheaf("stop")
    started = start_a_hub_once(monkeypatch, hubclient.HubClient, "challenge", too_late=True)
    r = sheaf("roots", "forget", "drop")
    assert started and r.code == 0, r.err
    assert r.out == f"  forgot drop ({drop.parent.resolve()}); its documents are untouched\n"
    assert roots_held(port) == ["keep"]
    sheaf("open", keep, "--no-browser", "--title", "Saved again")      # the hub writes its registry
    assert [x.name for x in Roots().all()] == ["keep"]


def test_forget_with_no_hub_leaves_no_entry_to_a_hub_that_starts_while_it_writes(
        sheaf, opened_browser, tmp_path, port, monkeypatch):
    """A hub reads roots.json first and docs.json after it. One that starts between the command's
    two writes must not find the root gone and its entries still there: it would never be told of
    them, and would write them back with its next save of docs.json."""
    keep, drop = doc_in(tmp_path / "keep"), doc_in(tmp_path / "drop")
    sheaf("open", keep, "--no-browser")
    sheaf("open", drop, "--no-browser", "--title", "Kept title")
    sheaf("stop")
    started = start_a_hub_once(monkeypatch, hubstate.Docs, "forget_prefix")
    assert sheaf("roots", "forget", "drop").code == 0
    assert started and roots_held(port) == ["keep"]
    sheaf("open", keep, "--no-browser", "--title", "Saved again")      # the hub writes docs.json
    assert "drop/plan.md" not in (paths.state_dir() / "docs.json").read_text()


@pytest.mark.parametrize("hub", [True, False], ids=["a hub", "no hub"])
def test_forget_drops_what_the_members_had_read_of_the_root(sheaf, opened_browser, tmp_path, port, hub):
    """A folder that takes the name must not start with the old members' read state (9.9)."""
    keep, drop = open_keep_and_drop(sheaf, tmp_path)
    sheaf("stop")
    members = hubstate.MemberSeen()
    members.mark("m-1", "drop/plan.md", "c1", 2)
    members.mark("m-1", "keep/plan.md", "c1", 3)
    if hub:
        assert sheaf("start").code == 0
    assert sheaf("roots", "forget", "drop").code == 0
    got = json.loads((paths.state_dir() / "seen-members.json").read_text())
    assert got == {"m-1": {"keep/plan.md": {"c1": 3}}}


def test_forget_with_no_hub_keeps_a_root_registered_while_it_wrote(
        sheaf, opened_browser, tmp_path, port, monkeypatch):
    """The command edits the entries and then roots.json: a root that a hub registered in between
    stays in the file, which is not the one the command read when it started."""
    keep, drop, new = doc_in(tmp_path / "keep"), doc_in(tmp_path / "drop"), doc_in(tmp_path / "new")
    sheaf("open", keep, "--no-browser")
    sheaf("open", drop, "--no-browser")
    sheaf("stop")
    real = hubstate.Docs.forget_prefix

    def a_hub_registers_a_root(self, prefix):
        Roots().for_document(new)
        return real(self, prefix)
    monkeypatch.setattr(hubstate.Docs, "forget_prefix", a_hub_registers_a_root)
    assert sheaf("roots", "forget", "drop").code == 0
    assert sorted(r.name for r in Roots().all()) == ["keep", "new"]


def test_forget_with_no_hub_says_the_files_were_forgotten_when_a_hub_that_starts_stays_silent(
        sheaf, opened_browser, tmp_path, port, monkeypatch):
    """The second look meets a hub that listens and does not answer within the start's wait: the
    files are edited already, and that hub was not told, so it may still hold the root."""
    keep, drop = open_keep_and_drop(sheaf, tmp_path)
    sheaf("stop")

    def silent(self):
        raise hubclient.HubSilent(self.port, hubclient.TIMEOUT)
    looks = first_look_clean_then(monkeypatch, silent)
    monkeypatch.setattr(hubclient, "START_WAIT", 0.3)
    r = sheaf("roots", "forget", "drop")
    assert len(looks) > 2                                    # it waited for the hub to start
    assert r.code == 1
    assert r.out == f"  forgot drop ({drop.parent.resolve()}); its documents are untouched\n"
    assert r.err == (f"  ! a hub that is starting on 127.0.0.1:{port} did not answer within 0.3 s, so it "
                     "was not told and may still hold drop: run sheaf roots forget drop again once it answers\n")
    assert [x.name for x in Roots().all()] == ["keep"]


@pytest.mark.parametrize("late", ["impostor", "hung up", "refused"])
def test_forget_with_no_hub_says_the_files_were_forgotten_when_the_late_look_fails(
        sheaf, opened_browser, tmp_path, port, monkeypatch, late):
    """The files are edited before the second look, so what fails after it (something else answers on
    the port, a hub that proved itself and then hung up, one that refused the forget) is said after
    the line that says they were forgotten, never in its place."""
    keep, drop = open_keep_and_drop(sheaf, tmp_path)
    sheaf("stop")
    looks = first_look_clean_then(monkeypatch, second_look(late))

    def call(self, method, path, body=None):
        if late == "hung up":
            raise hubclient.HubHungUp(self.port)
        return 500, {"ok": False, "error": "it broke"}
    monkeypatch.setattr(hubclient.HubClient, "call", call)
    r = sheaf("roots", "forget", "drop")
    assert r.code == 1 and len(looks) == 2
    assert r.out == f"  forgot drop ({drop.parent.resolve()}); its documents are untouched\n"
    assert r.err == {"impostor": f"  ! something else holds 127.0.0.1:{port}, not your sheaf hub\n",
                     "hung up": f"  ! the sheaf hub on 127.0.0.1:{port} proved itself and then ended the "
                                "connection, twice, and nothing was sent; try again, or run `sheaf restart`\n",
                     "refused": "sheaf: the hub refused: it broke\n"}[late]
    assert [x.name for x in Roots().all()] == ["keep"]


@pytest.mark.parametrize("late", ["impostor", "refused"])
def test_forget_of_a_name_the_files_do_not_hold_says_only_what_failed_at_the_late_look(
        sheaf, opened_browser, tmp_path, port, monkeypatch, late):
    """The control: when the files held no such root, nothing was forgotten, and the failure is all
    there is to say."""
    sheaf("open", doc_in(tmp_path / "keep"), "--no-browser")
    sheaf("stop")
    first_look_clean_then(monkeypatch, second_look(late))
    monkeypatch.setattr(hubclient.HubClient, "call",
                        lambda self, *a, **k: (500, {"ok": False, "error": "it broke"}))
    r = sheaf("roots", "forget", "drop")
    assert r.code == 1 and r.out == ""
    assert r.err == {"impostor": f"  ! something else holds 127.0.0.1:{port}, not your sheaf hub\n",
                     "refused": "sheaf: the hub refused: it broke\n"}[late]


def test_forget_removes_the_documents_entries_with_it(sheaf, opened_browser, tmp_path, port):
    drop = doc_in(tmp_path / "drop")
    sheaf("open", drop, "--no-browser", "--title", "Kept title")
    sheaf("stop")
    assert "drop/plan.md" in (paths.state_dir() / "docs.json").read_text()
    sheaf("roots", "forget", "drop")
    assert "drop/plan.md" not in (paths.state_dir() / "docs.json").read_text()


def test_forget_of_a_name_that_is_no_root_fails_and_says_which_roots_there_are(
        sheaf, opened_browser, work, port):
    sheaf("open", doc_in(work), "--no-browser")
    r = sheaf("roots", "forget", "nothing")
    assert r.code == 1 and r.out == ""
    assert r.err == "sheaf: no root is named nothing (sheaf roots lists them)\n"
    assert sheaf("roots", "forget", "nothing").code == 1       # with the hub running, the same
    sheaf("stop")
    assert sheaf("roots", "forget", "nothing").code == 1       # and with none


def test_forget_without_a_name_is_a_usage_error(sheaf, port):
    r = sheaf("roots", "forget")
    assert r.code == 2 and "NAME" in r.err


def test_the_folder_of_a_forgotten_root_is_a_root_again_under_the_same_name(
        sheaf, opened_browser, tmp_path, port):
    f = doc_in(tmp_path / "again")
    sheaf("open", f, "--no-browser")
    sheaf("roots", "forget", "again")
    assert sheaf("roots").out == "  no roots yet; a folder becomes one when a document in it is opened\n"
    sheaf("open", f, "--no-browser")
    assert sheaf("roots").out == f"  again  {f.parent.resolve()}\n"


def test_the_help_lists_both_commands(sheaf, tmp_path):
    out = sheaf("--help").out
    assert "sheaf list" in out and "sheaf roots [forget NAME]" in out
    assert brand_words_in(out, tmp_path) == []
