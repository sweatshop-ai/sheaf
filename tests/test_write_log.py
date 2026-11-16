"""The Write log: one line per write to a page, whatever the path (door write, page save, pull of a repo clone, a file
written on disk and seen), read per address through the handler in proxy mode, in memory, several members per hub.
It is not the Diagnostics log."""
import os
import pwd

import pytest
from helpers import BEA, CAL, FRONT, door, rpc
from test_hub_commits import DOC, box, edit, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)

from sheafmd import diagnostics
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
    assert not agents.hub.writes.pulling(DOC)       # the pull's window closed with it: nothing waits to swallow a later line
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
