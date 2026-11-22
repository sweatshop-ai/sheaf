"""The Write log: one line per write to a page, whatever the path (door write, page save, pull of a repo clone, a file
written on disk and seen), read per address through the handler in proxy mode, in memory, several members per hub.
It is not the Diagnostics log."""
import os
import pwd
import threading

import pytest
from helpers import BEA, CAL, FRONT, door, rpc
from test_hub_commits import DOC, box, edit, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)

from sheafmd import diagnostics
from sheafmd.mcp import Caller, written_from
from sheafmd.hub import proxy, writelog
from sheafmd.hub.state import Tokens
from sheafmd.hub.writelog import WriteLog
from sheafmd.source import md_hash

SESSION = "6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11"
LINK = "https://claude.ai/code/session_01ABC"


@pytest.fixture
def agents(box, rectoversos, browser):
    """Bea and Cal each with a Claude Code token of their own, on top of the `box` hub."""
    tokens = {"bea-claude": Tokens().add("bea-claude", client="Claude Code", write=True),
              "cal-claude": Tokens().add("cal-claude", client="Claude Code", write=True)}
    box.hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                                 "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                                 "members": {BEA: {"name": "Bea", "email": "bea@example.com", "short": "bea",
                                                   "roots": [str(rectoversos)], "tokens": ["bea-claude"]},
                                             CAL: {"name": "Cal", "short": "cal", "roots": [str(rectoversos)],
                                                   "tokens": ["cal-claude"]}}}, "the test")
    box.tokens, box.door = tokens, browser
    return box


def declared(**h):
    names = {"session": "X-Sheaf-Session", "host": "X-Sheaf-Host", "link": "X-Sheaf-Link", "chat": "X-Sheaf-Chat"}
    return {names[k]: v for k, v in h.items()}


def write(agents, who, tool="update", headers=None, **args):
    res = door(agents.door, rpc("tools/call", {"name": tool, "arguments": args}), token=agents.tokens[who],
               headers=headers or {}, as_name=None)
    assert res.status == 200, res.text
    out = res.json()["result"]
    assert not out["isError"], out["content"]
    return out


def plan_text(agents):
    return agents.hub.file(DOC).read_text(encoding="utf-8")


def update(agents, who, headers=None, words="Edited by the door."):
    text = plan_text(agents)
    return write(agents, who, headers=headers, doc=DOC, expected_hash=md_hash(text),
                 text=text + f"\n{words}\n")


def lines(agents, member=BEA, doc=DOC):
    got = agents.get(f"/_/writes?doc={doc}", member=member)
    assert got.status == 200, got.text
    return got.json()


def test_a_door_update_with_the_session_headers_leaves_a_line_naming_member_client_place_session_machine_and_link(agents):
    update(agents, "bea-claude", declared(session=SESSION, host="laptop-bea", link=LINK))
    got = lines(agents)
    assert len(got["lines"]) == 1
    line = got["lines"][0]
    assert line["writer"] == "Claude Code (Bea)"
    assert line["place"] == "laptop"
    assert (line["session"], line["host"], line["link"]) == (SESSION, "laptop-bea", LINK)
    assert line["address"] == DOC and line["via"] == "update" and line["time"]
    assert got["last"] == line and got["last_session"] == line


def test_a_door_create_leaves_a_line_too(agents):
    doc = "rectoversos/acme/blog/2026-11-16-new.md"
    write(agents, "bea-claude", tool="create", headers=declared(session=SESSION), doc=doc, text="# New\n")
    line = lines(agents, doc=doc)["lines"][0]
    assert (line["via"], line["writer"], line["session"]) == ("create", "Claude Code (Bea)", SESSION)


def test_a_door_write_with_a_chat_id_is_a_chat_client_and_with_no_header_at_all_too(agents):
    update(agents, "bea-claude", declared(chat="chat-42"), words="One.")
    update(agents, "bea-claude", words="Two.")
    first, second = lines(agents)["lines"]
    assert (first["place"], first["chat"], first["session"]) == ("chat client", "chat-42", "")
    assert (second["place"], second["chat"], second["session"]) == ("chat client", "", "")


def test_a_declared_value_is_kept_as_declared_but_cleaned_and_a_link_that_is_no_web_address_is_dropped(agents):
    update(agents, "bea-claude", declared(session="x" * 300, host="lap\ntop", link="javascript:alert(1)"))
    line = lines(agents)["lines"][0]
    assert len(line["session"]) == 100 and line["host"] == "lap top" and line["link"] == ""


def test_the_last_session_is_the_last_line_that_named_one_not_the_last_write(agents):
    update(agents, "bea-claude", declared(session=SESSION), words="One.")
    update(agents, "bea-claude", words="Two.")                      # a chat client write names no session
    got = lines(agents)
    assert got["last"]["session"] == "" and got["last_session"]["session"] == SESSION
    assert len(got["lines"]) == 2


def test_a_door_update_that_changed_nothing_leaves_no_line(agents):
    text = plan_text(agents)
    write(agents, "bea-claude", doc=DOC, expected_hash=md_hash(text), text=text)
    assert lines(agents)["lines"] == []


def test_a_refused_door_write_leaves_no_line(agents):
    res = door(agents.door, rpc("tools/call", {"name": "update", "arguments": {
        "doc": DOC, "expected_hash": "0" * 16, "text": "# other\n"}}), token=agents.tokens["bea-claude"], as_name=None)
    assert res.json()["result"]["isError"]
    assert lines(agents)["lines"] == []


def test_a_page_save_leaves_a_line_with_place_page_and_the_member(agents, rectoversos):
    edit(agents, rectoversos, member=CAL)
    line = lines(agents, member=BEA)["lines"][0]
    assert (line["writer"], line["place"], line["via"]) == ("Cal", "page", "save")
    assert (line["session"], line["host"], line["link"], line["chat"]) == ("", "", "", "")


def test_a_pull_leaves_a_git_line_with_the_commit_author_and_a_disk_write_a_tiroir_line_with_no_name(
        agents, rectoversos, remote, tmp_path):
    e = agents.hub.entry(DOC)                       # the page is open, so the pull and the disk write meet it
    text = plan_text(agents).replace("First paragraph, about apples.", "First, merged on the remote.")
    merged_on_github(tmp_path, remote, {"acme/blog/2026-10-28-plan.md": text}, "merged")
    agents.hub.tick()
    assert agents.hub.commits.settle()
    pulled = lines(agents)["lines"]
    assert [(l["writer"], l["place"], l["via"]) for l in pulled] == [("git · Ada", "tiroir", "pull")]
    # A file written on the disk, seen at the next render of its page.
    agents.hub.catch_up(e)                          # the pull took the page in already: its line, no disk line
    assert [l["via"] for l in lines(agents)["lines"]] == ["pull"]
    f = agents.hub.file(DOC)
    f.write_text(f.read_text(encoding="utf-8") + "\nWritten by an editor.\n", encoding="utf-8")
    agents.hub.catch_up(e)
    seen = lines(agents)["lines"]
    assert [(l["writer"], l["place"], l["via"]) for l in seen] == [("git · Ada", "tiroir", "pull"),
                                                                    ("?", "tiroir", "disk")]


def test_a_write_of_our_own_is_not_taken_for_a_disk_write(agents, rectoversos):
    e = agents.hub.entry(DOC)
    update(agents, "bea-claude")
    agents.hub.catch_up(e)
    agents.hub.tick()
    assert [l["via"] for l in lines(agents)["lines"]] == ["update"]


def test_a_member_reads_the_lines_of_their_own_pages_only(agents, rectoversos):
    update(agents, "bea-claude")
    assert agents.get("/_/writes?doc=elsewhere/acme/blog/plan.md", member=BEA).status == 404   # not on one of their roots
    assert agents.get("/_/writes", member=BEA).status == 400


def test_lines_are_kept_by_address_and_the_last_write_of_each_is_its_own(agents, rectoversos):
    edit(agents, rectoversos)
    update(agents, "bea-claude", declared(session=SESSION))
    got = lines(agents)
    assert [l["via"] for l in got["lines"]] == ["save", "update"]
    assert got["last"]["via"] == "update" and got["last_session"]["via"] == "update"
    log = agents.hub.writes
    assert log.last("other/doc.md") is None and log.last_session("other/doc.md") is None


def test_the_write_log_is_not_the_diagnostics_log(agents, rectoversos):
    update(agents, "bea-claude", declared(session=SESSION))
    assert not any(r["kind"] == "write" or r.get("session") == SESSION for r in diagnostics.read())
    assert writelog.log_path() != diagnostics.log_path()
    assert SESSION in writelog.log_path().read_text(encoding="utf-8")
    assert SESSION not in diagnostics.log_path().read_text(encoding="utf-8")


def test_two_members_writing_the_same_page_keep_their_own_lines(agents):
    update(agents, "bea-claude", declared(session=SESSION), words="Bea's.")
    update(agents, "cal-claude", words="Cal's.")
    got = lines(agents, member=BEA)
    assert [l["writer"] for l in got["lines"]] == ["Claude Code (Bea)", "Claude Code (Cal)"]
    assert got["last"]["writer"] == "Claude Code (Cal)" and got["last_session"]["writer"] == "Claude Code (Bea)"

def test_the_log_is_read_again_by_a_hub_that_starts_over(agents):
    update(agents, "bea-claude", declared(session=SESSION))
    again = WriteLog()                      # as a restarted hub builds it, from the file
    assert [l.session for l in again.lines(DOC)] == [SESSION]


def test_a_line_per_address_is_capped(tmp_path):
    log = WriteLog(keep=3)
    for i in range(5):
        log.add(address="a.md", writer=f"w{i}", place="page", via="save")
    assert [l.writer for l in log.lines("a.md")] == ["w2", "w3", "w4"]


def test_a_pull_that_the_page_never_matched_does_not_swallow_a_later_disk_write():
    log = WriteLog()
    log.expect_pull("a.md")
    assert log.is_pull("a.md", "h-any")             # while the pull is under way, any change a page sees is its
    log.end_pull("a.md", "h-left")
    assert not log.is_pull("a.md", "h-other")       # a different text is a disk write, and drops the record
    assert not log.is_pull("a.md", "h-left")
    log.end_pull("a.md", "h-left")
    assert log.is_pull("a.md", "h-left") and not log.is_pull("a.md", "h-left")


def test_the_box_s_james_is_a_tiroir_write_and_his_session_header_is_the_session():
    james = Caller("James", session=SESSION)
    assert written_from(james) == ("tiroir", {"session": SESSION})
    assert written_from(Caller("James", session="", declared={"session": "own"}))[1]["session"] == "own"
    assert written_from(Caller("James", session=""))[0] == "tiroir"
    token = object()                                  # a token's row; only that there is one matters here
    assert written_from(Caller("Bea", token, declared={"chat": "c", "session": "s"}))[0] == "chat client"
    assert written_from(Caller("Bea", token, declared={"host": "h"}))[0] == "laptop"
    assert written_from(Caller("Bea", token))[0] == "chat client"
    assert written_from(Caller("Bea"))[0] == "laptop"                                  # the stdio door


def test_a_pull_whose_author_lookup_fails_still_goes_through_with_an_unknown_author(agents, rectoversos, remote, tmp_path,
                                                                                   monkeypatch):
    import subprocess

    from sheafmd.hub import commits
    agents.hub.entry(DOC)
    text = plan_text(agents).replace("First paragraph, about apples.", "First, merged on the remote.")
    merged_on_github(tmp_path, remote, {"acme/blog/2026-10-28-plan.md": text}, "merged")
    real = commits._git

    def slow_log(folder, *args, **kw):
        if "log" in args and "--format=%an" in args:
            raise subprocess.TimeoutExpired("git", 20)
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", slow_log)
    agents.hub.tick()
    assert agents.hub.commits.settle()
    assert "merged on the remote" in plan_text(agents)                 # the pull went through
    assert [(l["writer"], l["via"]) for l in lines(agents)["lines"]] == [("git · ?", "pull")]


def test_a_door_write_the_watcher_sees_before_the_door_has_told_the_hub_leaves_no_disk_line(agents, monkeypatch):
    e = agents.hub.entry(DOC)
    real = agents.hub.wrote

    def watcher_first(address, moved=False):
        agents.hub.catch_up(e)                      # the watcher looks at the file between the write and `wrote()`
        real(address, moved)

    monkeypatch.setattr(agents.hub, "wrote", watcher_first)
    update(agents, "bea-claude")
    agents.hub.catch_up(e)
    assert [l["via"] for l in lines(agents)["lines"]] == ["update"]


def test_a_door_write_does_not_swallow_a_later_editor_write(agents):
    e = agents.hub.entry(DOC)
    update(agents, "bea-claude")
    f = agents.hub.file(DOC)
    f.write_text(f.read_text(encoding="utf-8") + "\nWritten by an editor.\n", encoding="utf-8")
    agents.hub.catch_up(e)
    assert [l["via"] for l in lines(agents)["lines"]] == ["update", "disk"]


def test_the_lines_of_a_page_that_is_gone_are_not_read_by_a_hub_that_never_saw_it(agents):
    update(agents, "bea-claude")
    assert agents.get(f"/_/writes?doc={DOC}", member=BEA).status == 200
    agents.hub.file(DOC).unlink()
    assert agents.get(f"/_/writes?doc={DOC}", member=BEA).status == 200      # known: judged as the hub last saw it
    agents.hub._front.clear()                                                 # as a restarted hub: it knows nothing of it
    assert agents.get(f"/_/writes?doc={DOC}", member=BEA).status == 404


# ── the tick and the page save, as the door ─────────────────────────────────────
def same_size_same_mtime(agents):
    """Another text of the file's length, written with the mtime it had: `(mtime, size)` sees nothing."""
    f = agents.hub.file(DOC)
    before = f.stat()
    text = f.read_text(encoding="utf-8")
    assert "apples" in text
    f.write_text(text.replace("apples", "pears_"), encoding="utf-8")
    os.utime(f, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert (f.stat().st_mtime_ns, f.stat().st_size) == (before.st_mtime_ns, before.st_size)
    return md_hash(f.read_text(encoding="utf-8"))


def test_a_disk_write_of_the_same_size_and_mtime_read_through_a_tick_leaves_one_disk_line(agents):
    agents.hub.entry(DOC)
    agents.hub.catch_up(agents.hub.entry(DOC))
    now = same_size_same_mtime(agents)
    agents.post("/_/tick", {"doc": DOC, "action": 0, "word": "Done", "hash": now, "where": "page"}, member=BEA)
    assert [l["via"] for l in lines(agents)["lines"]] == ["disk"]


def test_a_page_save_the_watcher_sees_before_the_hub_logs_it_leaves_the_page_line_only(agents, rectoversos, monkeypatch):
    from sheafmd.hub import live
    e = agents.hub.entry(DOC)
    real, pending = live.LiveDocument._after_write, []

    def watcher_first(self, *a, **kw):
        # The watcher is another thread: it looks at the file between the write and the hub's note of it.
        looked = threading.Thread(target=agents.hub.catch_up, args=(e,))
        looked.start()
        looked.join(0.3)
        out = real(self, *a, **kw)
        pending.append(looked)
        return out

    monkeypatch.setattr(live.LiveDocument, "_after_write", watcher_first)
    edit(agents, rectoversos, member=CAL)
    monkeypatch.undo()
    for looked in pending:
        looked.join()
    agents.hub.catch_up(e)
    assert [(l["via"], l["place"]) for l in lines(agents)["lines"]] == [("save", "page")]


def test_an_editor_write_after_a_page_save_still_leaves_its_disk_line(agents, rectoversos):
    e = agents.hub.entry(DOC)
    edit(agents, rectoversos, member=CAL)
    f = agents.hub.file(DOC)
    f.write_text(f.read_text(encoding="utf-8") + "\nWritten by an editor.\n", encoding="utf-8")
    agents.hub.catch_up(e)
    assert [l["via"] for l in lines(agents)["lines"]] == ["save", "disk"]


def test_a_write_that_fails_after_the_hub_expected_it_leaves_no_expectation_behind(agents, monkeypatch):
    from sheafmd import mcp
    real = mcp.update_beneath

    def fails_after(*a, **kw):
        real(*a, **kw)                              # the text was judged, and written
        raise OSError("disk full")

    monkeypatch.setattr(mcp, "update_beneath", fails_after)
    text = plan_text(agents)
    res = door(agents.door, rpc("tools/call", {"name": "update", "arguments": {
        "doc": DOC, "expected_hash": md_hash(text), "text": text + "\nLost.\n"}}), token=agents.tokens["bea-claude"], as_name=None)
    assert res.json()["result"]["isError"]
    assert agents.hub.writes._own == {}


def test_a_restore_keeps_the_lines_of_a_renamed_page_at_the_new_address_after_a_restart():
    log = WriteLog()
    log.add(address="old.md", writer="Bea", place="page", via="save")
    log.rename("old.md", "new.md")                  # the line now sits at new.md, still marked old.md in the file
    log.restore("new.md", log.lines("new.md"))
    again = WriteLog()
    assert [l.writer for l in again.lines("new.md")] == ["Bea"] and again.lines("old.md") == []


def test_a_restore_is_one_write_to_the_file_so_a_cut_one_takes_back_nothing(monkeypatch):
    log = WriteLog()
    log.add(address="a.md", writer="Bea", place="page", via="save")
    kept = log.lines("a.md")
    writes = []
    real = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: writes.append(data) or real(fd, data))
    log.restore("a.md", kept)
    assert len(writes) == 1                         # the retraction and the lines it keeps reach the file together


def test_an_undo_takes_back_only_the_lines_its_thread_added_and_keeps_another_writers_after_a_restart():
    import threading
    log = WriteLog()
    log.add(address="a.md", writer="Bea", place="page", via="save")
    with log.own_lines() as mine:
        log.add(address="a.md", writer="Claude", place="tiroir", via="create")
        other = threading.Thread(target=log.add, kwargs={"address": "a.md", "writer": "Cal", "place": "page", "via": "save"})
        other.start()
        other.join()
    log.undo("a.md", mine)
    assert [l.writer for l in log.lines("a.md")] == ["Bea", "Cal"]
    assert [l.writer for l in WriteLog().lines("a.md")] == ["Bea", "Cal"]


def test_an_undo_keeps_a_renamed_lines_address_and_brings_back_the_lines_the_landing_pushed_out():
    log = WriteLog(keep=3)
    log.add(address="old.md", writer="Bea", place="page", via="save")
    log.rename("old.md", "new.md")                  # the line sits at new.md, still marked old.md in memory
    log.add(address="new.md", writer="Cal", place="page", via="save")
    log.add(address="new.md", writer="Dan", place="page", via="save")
    with log.own_lines() as mine:
        for i in range(3):                          # the address holds 3: the landing pushes all three earlier lines out
            log.add(address="new.md", writer=f"landing {i}", place="tiroir", via="transfer")
    assert [l.writer for l in log.lines("new.md")] == ["landing 0", "landing 1", "landing 2"]
    log.undo("new.md", mine)
    assert [l.writer for l in log.lines("new.md")] == ["Bea", "Cal", "Dan"]
    assert {l.address for l in log.lines("new.md")} == {"new.md"}
    assert [l.writer for l in WriteLog(keep=3).lines("new.md")] == ["Bea", "Cal", "Dan"]


def test_a_restore_keeps_a_renamed_pages_lines_under_the_new_address_in_memory_too():
    log = WriteLog()
    log.add(address="old.md", writer="Bea", place="page", via="save")
    log.rename("old.md", "new.md")
    log.restore("new.md", log.lines("new.md"))
    assert [l.address for l in log.lines("new.md")] == ["new.md"]


def test_the_last_line_and_the_last_way_back_come_from_one_look_at_the_log():
    log = WriteLog()
    log.add(address="a.md", writer="Ada", place="page", via="save", session=SESSION)
    log.add(address="a.md", writer="Bea", place="page", via="save")
    last, way_back = log.last_and_way_back("a.md")
    assert (last, way_back) == (log.last("a.md"), log.last_way_back("a.md")) and (last.writer, way_back.writer) == ("Bea", "Ada")
    assert log.last_and_way_back("none.md") == (None, None)


def test_a_pull_that_ends_does_not_close_the_window_of_another_pull_of_the_same_page():
    log = WriteLog()
    log.expect_pull("a.md")
    log.expect_pull("a.md")
    log.end_pull("a.md", None)
    assert log.is_pull("a.md", "h-any")             # the second pull is still under way
    log.end_pull("a.md", None)
    assert not log.is_pull("a.md", "h-any")
