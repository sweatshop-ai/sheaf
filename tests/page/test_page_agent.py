"""What the page says when there is no agent to Ask or Tell (SPEC 10.6): the buttons are there,
disabled, each with the hub's reason for it."""
import json
import os
import re
import sys

import pytest

from agent_fakes import PID, write_record
from pagehelp import DOC, P1, at, select, until
from sheafmd import comments as rdc
from sheafmd import paths
from sheafmd.agents.claude_code import proc_start
from sheafmd.source import update_file

pytestmark = pytest.mark.page

META = re.compile(r'(<script id="rd-edit-meta" type="application/json">)(.*?)(</script>)', re.S)
LINES = {"ask": "Ask is off: the reason of the hub.", "tell": "Tell is off: another reason."}


def with_lines(tab):
    """The page as the hub sends it, in its first render and in the /_/doc answer that refreshes
    it, but with a line of its own under each disabled button, so that the page's own fallback
    line cannot pass for the hub's."""
    def page(route):
        html = route.fetch().text()
        m = META.search(html)
        meta = json.loads(m.group(2))
        meta["agent"], meta["can"], meta["lines"] = None, [], LINES
        route.fulfill(status=200, content_type="text/html; charset=utf-8",
                      body=html[:m.start(2)] + json.dumps(meta).replace("<", "\\u003c") + html[m.end(2):])

    def doc(route):
        r = route.fetch()
        route.fulfill(response=r, json={**r.json(), "target": None, "capabilities": [], "lines": LINES})

    tab.page.route(tab.site.url, page)
    tab.page.route(re.compile(r"/_/doc\?"), doc)


def test_the_ask_and_tell_buttons_that_cannot_work_say_why_with_the_hubs_lines(tab):
    with_lines(tab)
    tab.open()
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.click("#rd-comment-btn")
    tab.page.wait_for_selector("#rd-popover textarea")
    ask, tell = (tab.page.query_selector(f"#rd-popover button.rd-{k}") for k in ("ask", "tell"))
    assert ask.is_disabled() and tell.is_disabled()
    assert ask.get_attribute("title") == LINES["ask"]
    assert tell.get_attribute("title") == LINES["tell"]
    assert tab.page.inner_text("#rd-popover .rd-agent-line:nth-of-type(1)") == LINES["ask"]
    assert tab.page.text_content("#rd-agent") == LINES["ask"]       # the menu says it too


def test_a_thread_and_its_reply_form_say_why_their_ask_and_tell_buttons_cannot_work(tab):
    update_file(tab.site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                         "Ada", "2026-10-14T10:00")[0])
    with_lines(tab)
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector("#rd-popover button[data-a=reply]")
    ask, tell = (tab.page.query_selector(f"#rd-popover .rd-actions button.rd-{k}") for k in ("ask", "tell"))
    assert ask.is_disabled() and tell.is_disabled()
    assert ask.get_attribute("title") == LINES["ask"]
    assert tell.get_attribute("title") == LINES["tell"]
    assert tab.page.locator("#rd-popover .rd-actions .rd-agent-line").all_inner_texts() == list(LINES.values())
    tab.page.click("#rd-popover button[data-a=reply]")
    tab.page.wait_for_selector("#rd-popover textarea")
    ask, tell = (tab.page.query_selector(f"#rd-popover .rd-form button.rd-{k}") for k in ("ask", "tell"))
    assert ask.is_disabled() and tell.is_disabled()
    assert ask.get_attribute("title") == LINES["ask"]
    assert tell.get_attribute("title") == LINES["tell"]
    assert tab.page.locator("#rd-popover .rd-form .rd-agent-line").all_inner_texts() == list(LINES.values())


def write_config(text):
    path = paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def buttons(tab):
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.click("#rd-comment-btn")
    tab.page.wait_for_selector("#rd-popover textarea")
    return [tab.page.inner_text(f"#rd-popover button.rd-{k}") for k in ("ask", "tell")]


def test_the_buttons_name_the_session_by_its_own_name(tab, agent):
    tab.open()
    assert buttons(tab) == ["Ask Cosima", "Tell Cosima"]


def test_a_session_with_no_name_is_called_by_its_display_name(tab, agent, tmp_path):
    write_record(tmp_path / "claude-config", name="")
    target = tab.site.hub.target(DOC).as_dict()
    tab.site.hub.render(tab.site.file, {}, {**target, "name": ""})
    tab.open()
    assert buttons(tab) == ["Ask Claude", "Tell Claude"]


def test_an_answer_and_an_action_are_labelled_with_the_name_but_stay_signed_as_they_were(tab, agent):
    update_file(tab.site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                         "Ada", "2026-10-14T10:00")[0])
    update_file(tab.site.file, lambda t: rdc.reply(t, "c1", "Because.", "Claude", "2026-10-14T10:01",
                                                   role="answer"))
    update_file(tab.site.file, lambda t: rdc.reply(t, "c1", "Done.", "Claude", "2026-10-14T10:02",
                                                   role="action"))
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector("#rd-popover .rd-who")
    whos = tab.page.eval_on_selector_all("#rd-popover .rd-who", "els => els.map(e => e.textContent)")
    assert "Cosima’s answer" in whos and "Cosima’s action" in whos
    assert "@Claude" in tab.site.file.read_text(encoding="utf-8")


def test_a_rename_during_an_outage_reaches_the_open_page_when_the_hub_comes_back(tab, agent, tmp_path):
    tab.open()
    assert "Cosima" in tab.page.text_content("#rd-agent")
    tab.site.kill()
    write_record(tmp_path / "claude-config", name="Beatrix")
    tab.site.reopen()
    tab.page.wait_for_function("() => document.getElementById('rd-agent').textContent.includes('Beatrix')",
                               timeout=30000)
    assert buttons(tab) == ["Ask Beatrix", "Tell Beatrix"]


PROBE = ("import json, os, sys\n"
         "tmp = sys.argv[1] + '.tmp'\n"
         "with open(tmp, 'w') as f:\n"
         "    f.write(json.dumps(sys.argv[2:]))\n"
         "os.replace(tmp, sys.argv[1])\n")


def waiting_tell(tab, tmp_path, jump):
    """A thread whose Tell is out and whose session now waits on its person; the page open on it."""
    update_file(tab.site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                         "Ada", "2026-10-14T10:00")[0])
    out = tmp_path / "jumped.json"
    if jump:
        probe = tmp_path / "probe.py"
        probe.write_text(PROBE, encoding="utf-8")
        cmd = json.dumps([sys.executable, str(probe), str(out), "{session}", "{name}"])
        write_config(f"[jump]\ncommand = {cmd}\n")
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.click("#rd-popover button[data-a=tell]")
    tab.page.wait_for_selector("#rd-popover .rd-pending-tell")
    write_record(tmp_path / "claude-config", name="Cosima", status="waiting", waitingFor="Which tagline?",
                 messagingSocketPath="", procStart=proc_start(PID))
    tab.site.hub.tick()
    tab.page.wait_for_selector("#rd-popover .rd-pending-tell .rd-text:has-text('Which tagline?')")
    return out


def test_a_tell_waiting_for_its_person_offers_a_button_that_jumps_to_the_session(tab, agent, tmp_path):
    out = waiting_tell(tab, tmp_path, jump=True)
    button = tab.page.locator("#rd-popover .rd-pending-tell button.rd-answer")
    assert button.inner_text() == "Answer Cosima"
    button.click()
    until(lambda: out.exists(), timeout=10, what="the fake agent's output")
    assert json.loads(out.read_text(encoding="utf-8")) == ["s-1", "Cosima"]


def test_a_tell_waiting_for_its_person_has_no_button_without_a_jump_command(tab, agent, tmp_path):
    waiting_tell(tab, tmp_path, jump=False)
    assert tab.page.locator("#rd-popover button.rd-answer").count() == 0


def test_a_jump_that_fails_says_why_in_a_toast(tab, agent, tmp_path):
    waiting_tell(tab, tmp_path, jump=False)
    write_config('[jump]\ncommand = ["/nonexistent/sheaf-jump"]\n')
    tab.page.reload()
    tab.page.click(".rd-badge")
    tab.page.click("#rd-popover button.rd-answer")
    tab.page.wait_for_function("() => document.body.textContent.includes('The jump command was not found.')")


def test_the_answer_button_follows_the_jump_command_without_a_reload(tab, agent, tmp_path):
    waiting_tell(tab, tmp_path, jump=True)
    assert tab.page.locator("#rd-popover button.rd-answer").count() == 1
    tab.site.kill()
    path = paths.config_file()
    path.unlink()
    tab.site.reopen()
    tab.page.wait_for_function("() => document.querySelectorAll('#rd-popover button.rd-answer').length === 0",
                               timeout=30000)
