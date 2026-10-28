"""The list (SPEC 9.10): a member's sheaves that wait on someone and the ones in progress, per
`<client>/<project>`, at `/<root>` of the root `[list]` names. Status and owner come from the record (an
issues repo and its GitHub Project), the rest from each sheaf's front matter. Through the handler in proxy
mode, with three hand-made sheaves, a documentation sheaf and a fake GitHub that answers GraphQL from the
issues a test gives it."""
import json
import os
import pwd
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from bs4 import BeautifulSoup
from helpers import FRONT, Front, hub_rows

from sheafmd.hub import proxy, the_list

NELL = "503b2f77-83de-452c-817a-a357faf85929"       # the front's ids of two members
DORA = "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"
TOKEN = "ghs_fake_installation_token"
NOW = 1_761_640_000                                    # 2025-10-28 08:26:40 UTC
ISO = "%Y-%m-%dT%H:%M:%SZ"


def ago(seconds):
    import time
    return time.strftime(ISO, time.gmtime(NOW - seconds))


SHEAVES = {
    "globex/black-friday/2026-10-28-reply-to-joey.md": """---
client: globex
project: black-friday
issue: acme/record#5
assistant: James
kind: mail
visibility: project
opened: 2026-10-28
---
# Reply to Joey about column L

- [ ] Approve

The draft.
""",
    "initech/website/2026-10-27-ga4-property.md": """---
client: initech
project: website
issue: acme/record#7
assistant: James
kind: question
---
# James needs the GA4 property id

- [ ] Done @dora
""",
    "initech/website/2026-10-26-prep-thursday.md": """---
client: initech
project: website
issue: acme/record#6
assistant: James
kind: prep
---
# Prep for the call of Thursday
""",
    "globex/black-friday/2026-10-20-how-we-tag.md": """---
client: globex
project: black-friday
issue:
kind: documentation
---
# How we tag the Black Friday pages
""",
}


class FakeGitHub:
    """GitHub's GraphQL endpoint for the issues in `issues` ({number: fields}), on a port of
    127.0.0.1. It answers only a request with the installation token, and counts the requests."""

    ALIAS = re.compile(r'(\w+): repository\(owner: "([^"]+)", name: "([^"]+)"\) \{ issue\(number: (\d+)\)')

    def __init__(self):
        self.issues = {}
        self.requests = 0
        self.errors = None              # GraphQL errors to answer with, and no data, still with a 200
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests += 1
                if self.path != "/graphql" or self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self.send_response(401)
                    self.end_headers()
                    return
                data = {}
                for alias, owner, name, number in fake.ALIAS.findall(body["query"]):
                    data[alias] = {"issue": fake.issue(owner, name, int(number))}
                answer = {"data": data} if fake.errors is None else {"data": None, "errors": fake.errors}
                out = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def issue(self, owner, name, number):
        i = self.issues.get(number) if (owner, name) == ("acme", "record") else None
        if i is None:
            return None
        status = i.get("status")
        items = [] if status is None else [{
            "project": {"number": 1, "owner": {"login": "acme"}},
            "status": {"name": status}}]
        return {"number": number, "state": i.get("state", "OPEN"), "stateReason": i.get("reason"),
                "updatedAt": i["updated"], "assignees": {"nodes": [{"login": a} for a in i["assignees"]]},
                "projectItems": {"nodes": items}}

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def github():
    g = FakeGitHub()
    g.issues = {
        5: {"status": "Waiting on member", "assignees": ["nell-l"], "updated": ago(2 * 3600)},
        7: {"status": "Waiting on member", "assignees": ["dora-k"], "updated": ago(3 * 3600)},
        6: {"status": "In progress at TT", "assignees": ["dora-k"], "updated": ago(40 * 60)},
    }
    yield g
    g.close()


@pytest.fixture
def sheaves(tmp_path):
    root = tmp_path / "list"
    for rel, text in SHEAVES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    (root / "projects.toml").write_text(
        '[projects."globex/black-friday"]\nmembers = ["nell"]\nstatus = "live"\n\n'
        '[projects."initech/website"]\nmembers = ["nell", "dora"]\nstatus = "live"\n', encoding="utf-8")
    return root


@pytest.fixture
def box(hub, browser, sheaves, github, tmp_path):
    """The hub in proxy mode with the sheaves as Nell's and Dora's root, and its `[list]` on that root,
    the fake GitHub and a token file; polled once."""
    token = tmp_path / "installation-token"
    token.write_text(TOKEN + "\n", encoding="utf-8")
    hub.clock = lambda: NOW
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                             "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "members": {NELL: {"name": "Nell", "short": "nell", "github": "nell-l",
                                                   "roots": [str(sheaves)]},
                                         DORA: {"name": "Dora", "short": "dora", "github": "dora-k",
                                                "roots": [str(sheaves)]}}}, "the test")
    hub.the_list = the_list.TheList(hub, the_list.parse({
        "root": str(sheaves), "repo": "acme/record", "project": 1,
        "token_file": str(token), "api": github.url, "in_progress": "In progress at TT"}, "the test"))
    hub.the_list.poll()
    return Front(hub, browser.handler)


def read(res):
    """The list as a member reads it: each section's heading, then each group's heading with its rows'
    titles and the line under each title."""
    assert res.status == 200, res.text
    soup = BeautifulSoup(res.text, "html.parser")
    out = {}
    for section in soup.select("section.list-section"):
        heading = " ".join(section.find("h2").get_text(" ", strip=True).split())
        groups = {}
        for group in section.select(".list-group"):
            rows = []
            for row in group.select(".list-row"):
                rows.append((row.select_one(".list-title").get_text(" ", strip=True),
                             " ".join(row.select_one(".list-meta").get_text(" ", strip=True).split())))
            groups[group.find("h3").get_text(strip=True)] = rows
        out[heading] = groups
    return out


def test_nell_sees_her_projects_waiting_then_in_progress(box):
    assert read(box.get("/list", member=NELL)) == {
        "Waiting on you 2": {
            "globex/black-friday": [("Reply to Joey about column L Approve James", "mail · you · #5 · 2 h")],
            "initech/website": [("James needs the GA4 property id Done @dora James", "question · @dora · #7 · 3 h")],
        },
        "In progress 1": {
            "initech/website": [("Prep for the call of Thursday James", "prep · @dora · #6 · 40 min")],
        },
    }


def test_dora_sees_only_initech_and_the_action_that_names_her_is_hers(box):
    assert read(box.get("/list", member=DORA)) == {
        "Waiting on you 1": {
            "initech/website": [("James needs the GA4 property id Done James", "question · you · #7 · 3 h")],
        },
        "In progress 1": {
            "initech/website": [("Prep for the call of Thursday James", "prep · you · #6 · 40 min")],
        },
    }


def test_only_mine_keeps_what_the_member_owns_or_what_names_them(box):
    assert read(box.get("/list?show=mine", member=NELL)) == {
        "Waiting on you 1": {
            "globex/black-friday": [("Reply to Joey about column L Approve James", "mail · you · #5 · 2 h")],
        },
        "In progress 0": {},
    }
    assert list(read(box.get("/list?show=mine", member=DORA))["Waiting on you 1"]) == ["initech/website"]


def test_all_of_the_team_shows_the_projects_a_member_is_not_in(box):
    page = read(box.get("/list?show=all", member=DORA))
    assert list(page) == ["Waiting on you 2", "In progress 1"]
    assert page["Waiting on you 2"]["globex/black-friday"] == [
        ("Reply to Joey about column L Approve James", "mail · @nell · #5 · 2 h")]


def test_all_of_the_team_leaves_out_a_sheaf_with_a_private_source_for_all_but_its_owner(box, sheaves):
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    assert "globex/black-friday" not in read(box.get("/list?show=all", member=DORA))["Waiting on you 1"]
    assert read(box.get("/list?show=all", member=NELL))["Waiting on you 2"]["globex/black-friday"] == [
        ("Reply to Joey about column L Approve James", "mail · you · #5 · 2 h")]


def test_the_filters_are_links_to_real_addresses_and_the_one_shown_is_marked(box):
    soup = BeautifulSoup(box.get("/list?show=mine", member=NELL).text, "html.parser")
    links = [(a.get_text(strip=True), a["href"], a.get("aria-current")) for a in soup.select("a.list-filter")]
    assert links == [("My projects", "/list", None), ("Only mine", "/list?show=mine", "page"),
                     ("All of the team", "/list?show=all", None)]


def test_a_status_moved_on_github_shows_at_the_next_poll(box, github):
    github.issues[6]["status"] = "Waiting on member"
    assert "In progress 1" in read(box.get("/list", member=DORA))       # the last poll's rows until the next
    box.hub.the_list.poll()
    assert list(read(box.get("/list", member=DORA))) == ["Waiting on you 2", "In progress 0"]


def test_a_done_issue_leaves_the_list_and_its_sheaf_still_opens_at_its_address(box, github):
    github.issues[5]["status"] = "Done"
    github.issues[7].update(state="CLOSED", reason="NOT_PLANNED")
    box.hub.the_list.poll()
    page = read(box.get("/list?show=all", member=NELL))
    assert list(page) == ["Waiting on you 0", "In progress 1"]
    assert box.get("/list/globex/black-friday/2026-10-28-reply-to-joey.md", member=NELL).status == 200


def test_an_issue_the_record_no_longer_answers_leaves_the_list(box, github):
    del github.issues[5]                        # deleted, transferred, or the App lost its repo
    box.hub.the_list.poll()
    assert list(read(box.get("/list", member=NELL))) == ["Waiting on you 1", "In progress 1"]
    assert not hub_rows("list-poll-failed")


def test_an_answer_with_errors_and_no_data_is_a_poll_that_could_not_read_the_record(box, github):
    github.errors = [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]
    github.issues[5]["status"] = "Done"
    box.hub.the_list.poll()
    assert "Waiting on you 2" in read(box.get("/list", member=NELL))
    rows = hub_rows("list-poll-failed")
    assert rows and "errors" in rows[-1]["error"]
    assert TOKEN not in json.dumps(rows)


def test_the_owner_is_the_login_of_an_assignee_who_is_no_member_and_nobody_without_one(box, github):
    github.issues[6]["assignees"] = ["zed-x"]
    github.issues[7]["assignees"] = []
    box.hub.the_list.poll()
    page = read(box.get("/list", member=NELL))
    assert page["In progress 1"]["initech/website"] == [("Prep for the call of Thursday James", "prep · zed-x · #6 · 40 min")]
    assert page["Waiting on you 2"]["initech/website"] == [
        ("James needs the GA4 property id Done @dora James", "question · nobody · #7 · 3 h")]


def test_my_projects_reads_the_members_of_projects_toml_without_case(box, sheaves):
    (sheaves / "projects.toml").write_text(
        '[projects."globex/black-friday"]\nmembers = ["Nell"]\nstatus = "live"\n', encoding="utf-8")
    box.hub.the_list.poll()
    assert list(read(box.get("/list", member=NELL))["Waiting on you 1"]) == ["globex/black-friday"]


def test_a_row_links_to_its_sheafs_own_address_which_opens_and_reloads(box):
    for path in ("/list", "/list/"):
        soup = BeautifulSoup(box.get(path, member=NELL).text, "html.parser")
        hrefs = [a["href"] for a in soup.select("a.list-title")]
        assert hrefs == ["/list/globex/black-friday/2026-10-28-reply-to-joey.md",
                         "/list/initech/website/2026-10-27-ga4-property.md",
                         "/list/initech/website/2026-10-26-prep-thursday.md"]
    for href in hrefs:
        for _ in range(2):                                              # opened, then reloaded
            r = box.get(href, member=NELL)
            assert r.status == 200, (href, r.text)


def test_a_documentation_sheaf_is_never_on_the_list(box):
    for show in ("projects", "mine", "all"):
        r = box.get(f"/list?show={show}", member=NELL)
        assert "How we tag" not in r.text
        assert "2026-10-20-how-we-tag" not in r.text
    assert box.get("/list/globex/black-friday/2026-10-20-how-we-tag.md", member=NELL).status == 200


def test_the_record_is_read_as_the_app_and_a_poll_that_cannot_read_it_keeps_the_last_rows(box, github, tmp_path):
    (tmp_path / "installation-token").write_text("", encoding="utf-8")
    github.issues[5]["status"] = "Done"
    box.hub.the_list.poll()
    assert "Waiting on you 2" in read(box.get("/list", member=NELL))
    rows = hub_rows("list-poll-failed")
    assert rows and "holds no token" in rows[-1]["error"]
    assert TOKEN not in json.dumps(rows)
    (tmp_path / "installation-token").write_text("ghs_another_token\n", encoding="utf-8")
    box.hub.the_list.poll()
    assert "answered 401" in hub_rows("list-poll-failed")[-1]["error"]


def test_a_member_whose_roots_do_not_hold_the_list_gets_404(box, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    cfg = box.hub.proxy
    box.hub.proxy = proxy.parse({"origin": FRONT, "socket": str(cfg.socket), "proxy_user": cfg.proxy_user,
                                 "members": {DORA: {"name": "Dora", "short": "dora", "roots": [str(other)]}}},
                                "the test")
    assert box.get("/list", member=DORA).status == 404


# ── the hub as a process: `[list]` in config.toml ──────────────────────────────

def configure_list(sock, root, extra):
    from helpers import proxy_table
    from sheafmd import paths
    p = paths.config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    members = proxy_table(sock, {NELL: ("Nell", [str(root)])})
    p.write_text(members + 'short = "nell"\ngithub = "nell-l"\n\n[list]\n' + extra, encoding="utf-8")


@pytest.mark.parametrize("extra, words", [
    ('repo = "acme/record"\nproject = 1\ntoken_file = "/run/t"\n', "'root' is missing"),
    ('root = "list"\nrepo = "acme/record"\nproject = 1\ntoken_file = "/run/t"\n',
     "'root' must be an absolute path"),
    ('root = "/srv/list"\nrepo = "acme"\nproject = 1\ntoken_file = "/run/t"\n', "'repo' must be owner/name"),
    ('root = "/srv/list"\nrepo = "a/b"\nproject = "1"\ntoken_file = "/run/t"\n', "'project' must be a number"),
    ('root = "/srv/list"\nrepo = "a/b"\nproject = 1\ntoken_file = "/run/t"\napi = "http://evil.example"\n',
     "'api' must be an https:// address"),
    ('root = "/srv/list"\nrepo = "a/b"\nproject = 1\ntoken_file = "/run/t"\ntoken = "x"\n', "unknown key 'token'"),
])
def test_a_list_table_the_hub_cannot_use_stops_its_start(proxy_folder, extra, words):
    from test_proxy_start import refused_start
    configure_list(f"{proxy_folder}/hub.sock", "/srv/list", extra)
    code, err, rows = refused_start()
    assert code == 1
    assert [r["kind"] for r in rows] == ["list-config"], rows
    assert words in rows[0]["reason"] and words in err


@pytest.mark.parametrize("key", ["stop_dir", "tell_dir", "sessions_dir"])
def test_a_box_folder_inside_a_members_root_stops_the_start(proxy_folder, key):
    from test_proxy_start import refused_start
    configure_list(f"{proxy_folder}/hub.sock", "/srv/nell",
                   f'root = "/srv/list"\nrepo = "a/b"\nproject = 1\ntoken_file = "/run/t"\n{key} = "/srv/nell/box"\n')
    code, err, rows = refused_start()
    assert code == 1
    assert [r["kind"] for r in rows] == ["list-config"], rows
    assert f"'{key}' of [list]" in rows[0]["reason"] and "inside a root of Nell" in rows[0]["reason"]


def test_the_hub_polls_the_record_from_its_start_and_serves_the_list_on_its_proxy_socket(
        proxy_folder, sheaves, github, tmp_path):
    from test_proxy_start import HOST, ask, run_hub, stop, wait_up
    token = tmp_path / "installation-token"
    token.write_text(TOKEN + "\n", encoding="utf-8")
    sock = f"{proxy_folder}/hub.sock"
    configure_list(sock, sheaves, f'root = "{sheaves}"\nrepo = "acme/record"\nproject = 1\n'
                                  f'token_file = "{token}"\napi = "{github.url}"\npoll = 1\n'
                                  'in_progress = "In progress at TT"\n')
    p = run_hub()
    try:
        wait_up(None, sock)
        github.issues[5]["status"] = "Done"
        seen = github.requests
        for _ in range(200):
            if github.requests >= seen + 2:          # one whole poll after the change
                break
            threading.Event().wait(0.05)
        status, body = ask(sock, "/list", headers={"X-Sheaf-Member": NELL, "Host": HOST})
        assert status == 200, body
        assert b"Prep for the call of Thursday" in body and b"Reply to Joey" not in body
    finally:
        assert stop(p) == 0


# ── the tick on the row ────────────────────────────────────────────────────────

JOEY = "list/globex/black-friday/2026-10-28-reply-to-joey.md"


def boxes(res):
    """Each row's box as (title link, data-doc, data-action, data-word), for the rows that have one."""
    soup = BeautifulSoup(res.text, "html.parser")
    out = []
    for row in soup.select(".list-row"):
        box = row.select_one("input[type=checkbox]")
        if box is not None:
            assert not box.has_attr("disabled")
            out.append((row.select_one("a.list-title")["href"], box["data-doc"], box["data-action"], box["data-word"]))
    return out


def test_a_row_with_an_action_carries_a_box_that_names_its_sheaf_and_its_action(box):
    assert boxes(box.get("/list", member=NELL)) == [
        ("/list/globex/black-friday/2026-10-28-reply-to-joey.md", JOEY, "0", "Approve"),
        ("/list/initech/website/2026-10-27-ga4-property.md", "list/initech/website/2026-10-27-ga4-property.md",
         "0", "Done")]


def test_a_tick_on_the_row_is_answered_in_the_sheaf_and_the_row_leaves_waiting_on_you(box, sheaves, github):
    before = (sheaves / JOEY[5:]).read_text(encoding="utf-8")
    r = box.post("/_/tick", {"doc": JOEY, "action": 0, "word": "Approve"}, member=NELL)
    assert r.status == 200, r.text
    assert (sheaves / JOEY[5:]).read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")
    page = read(box.get("/list", member=NELL))
    assert list(page["Waiting on you 1"]) == ["initech/website"]
    box.hub.the_list.poll()                     # the record has not moved yet: still not waiting on anyone
    assert "Waiting on you 1" in read(box.get("/list", member=NELL))
    github.issues[5].update(status="In progress at TT", updated=ago(60))   # the record routine moved it
    box.hub.the_list.poll()
    page = read(box.get("/list", member=NELL))
    assert page["In progress 2"]["globex/black-friday"] == [("Reply to Joey about column L James", "mail · you · #5 · 1 min")]


def test_a_tick_of_an_action_the_sheaf_no_longer_holds_is_refused_and_writes_nothing(box, sheaves):
    before = (sheaves / JOEY[5:]).read_text(encoding="utf-8")
    for body in ({"doc": JOEY, "action": 0, "word": "Done"}, {"doc": JOEY, "action": 1, "word": "Approve"}):
        r = box.post("/_/tick", body, member=NELL)
        assert r.status == 409, r.text
        assert "reload the list" in r.json()["error"]
    assert box.post("/_/tick", {"doc": JOEY, "action": 0, "word": "Approve"}, member=NELL).status == 200
    assert box.post("/_/tick", {"doc": JOEY, "action": 0, "word": "Approve"}, member=NELL).status == 409
    assert (sheaves / JOEY[5:]).read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


@pytest.mark.parametrize("body", [{"doc": JOEY, "word": "Approve"}, {"doc": JOEY, "action": "0", "word": "Approve"},
                                  {"doc": JOEY, "action": True, "word": "Approve"}, {"doc": JOEY, "action": 0},
                                  {"doc": JOEY, "action": 0, "word": ""}])
def test_a_tick_that_does_not_name_an_action_is_refused(box, body):
    assert box.post("/_/tick", body, member=NELL).status == 400


def test_a_member_cannot_tick_a_sheaf_outside_their_roots(box, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    cfg = box.hub.proxy
    box.hub.proxy = proxy.parse({"origin": FRONT, "socket": str(cfg.socket), "proxy_user": cfg.proxy_user,
                                 "members": {DORA: {"name": "Dora", "short": "dora", "roots": [str(other)]}}},
                                "the test")
    assert box.post("/_/tick", {"doc": JOEY, "action": 0, "word": "Approve"}, member=DORA).status == 404


def test_the_tick_inside_a_list_of_other_boxes_flips_that_one_line(box, sheaves):
    path = sheaves / "initech/website/2026-10-27-ga4-property.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Done @dora\n", "- [x] Read the brief\n- [ ] Done @dora\n- [ ] Share\n"), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    doc = "list/initech/website/2026-10-27-ga4-property.md"
    assert box.post("/_/tick", {"doc": doc, "action": 1, "word": "Share"}, member=DORA).status == 200
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Share", "- [x] Share")


def test_the_list_page_script_posts_the_tick_with_the_pages_nonce(box):
    r = box.get("/list", member=NELL)
    soup = BeautifulSoup(r.text, "html.parser")
    script = soup.select_one("script")
    assert script is not None and script.get("nonce") and f"'nonce-{script['nonce']}'" in r.headers["Content-Security-Policy"]
    assert "/_/tick" in script.string


def test_a_tick_beside_a_comment_in_the_same_list_keeps_the_comment(box, sheaves):
    from helpers import thread
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Approve\n", f"- [x] Read the thread{thread('c1', 'Dora')}\n- [ ] Approve\n"), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert box.post("/_/tick", {"doc": JOEY, "action": 0, "word": "Approve"}, member=NELL).status == 200
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


def test_an_action_above_a_rule_after_the_front_matter_is_still_read():
    s = the_list.read_sheaf("a/b/c.md", SHEAVES["globex/black-friday/2026-10-28-reply-to-joey.md"] + "\n---\n\nMore.\n")
    assert [(w, short) for w, short, _ in s.actions] == [("Approve", "")]
    assert s.title == "Reply to Joey about column L"


def test_a_list_table_without_a_proxy_table_stops_the_start(proxy_folder):
    from test_proxy_start import refused_start

    from sheafmd import paths
    p = paths.config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('[list]\nroot = "/srv/list"\nrepo = "acme/record"\nproject = 1\ntoken_file = "/run/t"\n', encoding="utf-8")
    code, err, rows = refused_start()
    assert code == 1
    assert [r["kind"] for r in rows] == ["list-config"], rows
    assert "needs a [proxy] table" in rows[0]["reason"] and "needs a [proxy] table" in err


@pytest.mark.parametrize("sep", [" ", "\x0c", "\x85", "\x0b"])
def test_a_line_separator_markdown_does_not_break_on_leaves_the_tick_on_its_own_box(box, sheaves, sep):
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Approve\n", f"Two lines{sep}in one paragraph.\n\n- [ ] Approve\n- [ ] Done\n"), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert box.post("/_/tick", {"doc": JOEY, "action": 0, "word": "Approve"}, member=NELL).status == 200
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


def test_a_list_root_inside_a_git_work_tree_is_refused_at_each_poll_and_lists_nothing(box, sheaves, tmp_path):
    import shutil
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    shutil.copytree(sheaves, repo / "list")
    cfg = box.hub.proxy
    box.hub.proxy = proxy.parse({"origin": FRONT, "socket": str(cfg.socket), "proxy_user": cfg.proxy_user,
                                 "members": {NELL: {"name": "Nell", "short": "nell", "github": "nell-l",
                                                    "roots": [str(repo)]}}}, "the test")
    box.hub.the_list.cfg = the_list.ListConfig(**{**box.hub.the_list.cfg.__dict__, "root": repo / "list"})
    box.hub.the_list.poll()
    rows = hub_rows("list-poll-failed")
    assert rows and f"{repo / 'list'} is not the top folder of its root" in rows[-1]["error"], rows
    # The git top's own page stays its index: a refused list root does not take it over.
    res = box.get("/repo", member=NELL)
    assert res.status == 301 and res.headers["Location"] == "/repo/", res.status


def test_a_ticked_sheaf_moved_out_of_waiting_and_back_without_a_new_change_is_waiting_again(box, github):
    # A Project's Status is not the issue's: moving it leaves the issue's last change where it was.
    assert box.post("/_/tick", {"doc": JOEY, "action": 0, "word": "Approve"}, member=NELL).status == 200
    github.issues[5]["status"] = "In progress at TT"
    box.hub.the_list.poll()
    assert "globex/black-friday" in read(box.get("/list", member=NELL))["In progress 2"]
    github.issues[5]["status"] = "Waiting on member"
    box.hub.the_list.poll()
    assert "globex/black-friday" in read(box.get("/list", member=NELL))["Waiting on you 2"]


@pytest.mark.parametrize("fence", ["````\n```\n- [ ] Approve\n```\n````\n", "~~~~\n~~~\n- [ ] Approve\n~~~~ more\n~~~~~\n",
                                   "```\n~~~\n- [ ] Approve\n```\n"])
def test_an_action_inside_a_fence_that_holds_a_shorter_or_other_fence_is_no_action(fence):
    s = the_list.read_sheaf("a/b/c.md", f"# A sheaf\n\n{fence}\n- [ ] Done\n")
    assert [(w, short) for w, short, _ in s.actions] == [("Done", "")]


def test_an_action_inside_an_html_comment_is_no_action():
    s = the_list.read_sheaf("a/b/c.md", "# A sheaf\n\n<!--\n- [ ] Approve\n-->\n\n- [ ] Done\n")
    assert [(w, line) for w, _, line in s.actions] == [("Done", 6)]


def test_an_indented_code_line_holding_a_fence_opens_no_fence():
    s = the_list.read_sheaf("a/b/c.md", "# A sheaf\n\n    ```\n\n- [ ] Approve\n")
    assert [(w, line) for w, _, line in s.actions] == [("Approve", 4)]


def test_a_box_the_render_draws_past_the_blocks_marks_cannot_be_ticked():
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import ticked_html
    block = split_md_blocks('- [ ] Approve <input type="checkbox">\n')[0]
    assert ticked_html(block, 1) is None        # the raw box in the line: no mark of the source is it


def test_a_sheaf_of_a_root_nested_in_the_list_root_is_on_no_list(box, sheaves):
    import subprocess
    nested = sheaves / "acme" / "site"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(nested)], check=True)
    (nested / "2026-10-28-nested.md").write_text(
        SHEAVES["initech/website/2026-10-27-ga4-property.md"].replace("# James needs the GA4 property id", "# Nested"),
        encoding="utf-8")
    box.hub.the_list.poll()
    assert "Nested" not in box.get("/list?show=all", member=NELL).text


def test_a_front_matter_closed_only_by_a_line_break_markdown_does_not_count_is_none():
    for text in ("---\rissue: acme/record#7\r---\r# Odd\r- [ ] Approve\r",       # read_text() turns \r into \n
                 "---\nissue: acme/record#7\nk: v\u2028---\n# Odd\n- [ ] Approve\n"):
        assert the_list.read_sheaf("a/b/c.md", text).issue is None


def test_a_sheaf_whose_front_matter_closes_only_on_another_line_break_leaves_the_rest_of_the_list(box, sheaves):
    text = "---\nissue: acme/record#7\nk: v\u2028---\n# Odd\n- [ ] Approve\n"
    (sheaves / "initech/website/2026-10-28-odd.md").write_text(text, encoding="utf-8")
    box.hub.the_list.poll()
    page = read(box.get("/list", member=NELL))
    assert "Waiting on you 2" in page and "Odd" not in json.dumps(page)
    path = sheaves / "initech/website/2026-10-28-odd.md"
    before = path.read_text(encoding="utf-8")
    r = box.post("/_/tick", {"doc": "list/initech/website/2026-10-28-odd.md", "action": 0, "word": "Approve"},
                 member=NELL)
    assert r.status in (200, 409), r.text       # no sheaf, still a document: its one box, or nothing
    assert path.read_text(encoding="utf-8") in (before, before.replace("- [ ] Approve", "- [x] Approve"))


def test_all_of_the_team_leaves_out_a_sheaf_closed_since_the_last_poll(box, sheaves):
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    assert all("globex/black-friday" not in groups for groups in read(box.get("/list?show=all", member=DORA)).values())


def test_a_link_to_a_sheaf_has_the_owner_of_the_sheaf_it_names(box, sheaves):
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n",
                                                             "sources: [library:4711]\nowner: dora\n"),
                    encoding="utf-8")
    (sheaves / "globex/black-friday/joey.md").symlink_to(joey.name)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    assert box.get(f"/{root}/globex/black-friday/2026-10-28-reply-to-joey.md", member=DORA).status == 404
    assert box.get(f"/{root}/globex/black-friday/joey.md", member=DORA).status == 404
    assert box.get(f"/{root}/globex/black-friday/joey.md", member=NELL).status == 200


def test_a_link_the_poll_does_not_read_has_the_owner_of_the_sheaf_it_names(box, sheaves):
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n",
                                                             "sources: [library:4711]\nowner: dora\n"),
                    encoding="utf-8")
    (sheaves / ".kept").mkdir()
    (sheaves / ".kept/joey.md").symlink_to(joey)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    assert box.get(f"/{root}/.kept/joey.md", member=DORA).status == 404
    assert box.get(f"/{root}/.kept/joey.md", member=NELL).status == 200


@pytest.mark.parametrize("issue", ["issue:\n", "issue: acme/record#7\n"], ids=["removed", "changed"])
def test_a_sheaf_whose_issue_changed_since_the_poll_is_not_its_old_assignees(box, sheaves, issue):
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    address = f"/{root}/globex/black-friday/2026-10-28-reply-to-joey.md"
    assert box.get(address, member=NELL).status == 200          # the assignee of #5 owns it
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", issue + "owner: dora\n"),
                    encoding="utf-8")
    assert box.get(address, member=NELL).status == 404          # before the next poll
    assert box.get(address, member=DORA).status == 200


@pytest.mark.parametrize("issue", ["issue:\n", "issue: acme/record#7\n"], ids=["removed", "changed"])
def test_a_tick_after_the_issue_changed_does_not_give_the_old_assignees_back(box, sheaves, issue):
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    address = f"/{root}/globex/black-friday/2026-10-28-reply-to-joey.md"
    assert box.get(address, member=NELL).status == 200          # the assignee of #5 owns it
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", issue + "owner: dora\n"),
                    encoding="utf-8")
    r = box.post("/_/tick", {"doc": address[1:], "action": 0, "word": "Approve"}, member=DORA)
    assert r.status == 200, r.text
    assert box.get(address, member=NELL).status == 404          # the tick, before the next poll
    assert box.get(address, member=DORA).status == 200
    assert "globex/black-friday" not in str(read(box.get("/list", member=NELL)))


def titles(page):
    return [t for groups in page.values() for rows in groups.values() for t, _ in rows]


@pytest.mark.parametrize("issue", ["issue:\n", "issue: acme/record#7\n"], ids=["removed", "changed"])
def test_a_tick_after_the_issue_changed_takes_the_row_off_the_list_until_the_next_poll(box, sheaves, github, issue):
    github.issues[5].update(status="In progress at TT")         # drawn, not left out as answered
    box.hub.the_list.poll()
    joey = sheaves / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", issue), encoding="utf-8")
    r = box.post("/_/tick", {"doc": JOEY, "action": 0, "word": "Approve"}, member=NELL)
    assert r.status == 200, r.text
    for m in (NELL, DORA):
        assert "Reply to Joey about column L James" not in titles(read(box.get("/list?show=all", member=m)))
    box.hub.the_list.poll()
    listed = "Reply to Joey about column L James" in titles(read(box.get("/list?show=all", member=DORA)))
    assert listed == (issue != "issue:\n")                      # back under #7; with no issue, on no list (9.10)


def test_an_issue_without_assignees_has_the_owner_its_sheaf_names(box, sheaves, github):
    github.issues[6]["assignees"] = []
    prep = sheaves / "initech/website/2026-10-26-prep-thursday.md"
    prep.write_text(prep.read_text(encoding="utf-8").replace("kind: prep\n", "kind: prep\nowner: nell\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    assert read(box.get("/list?show=mine", member=NELL))["In progress 1"] == {
        "initech/website": [("Prep for the call of Thursday James", "prep · you · #6 · 40 min")]}
    assert read(box.get("/list", member=DORA))["In progress 1"] == {
        "initech/website": [("Prep for the call of Thursday James", "prep · @nell · #6 · 40 min")]}


def test_the_lists_owner_is_the_one_the_file_names_now_not_at_the_poll(box, sheaves, github):
    github.issues[6]["assignees"] = []
    prep = sheaves / "initech/website/2026-10-26-prep-thursday.md"
    prep.write_text(prep.read_text(encoding="utf-8").replace("kind: prep\n", "kind: prep\nowner: nell\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    prep.write_text(prep.read_text(encoding="utf-8").replace("owner: nell\n", "owner: dora\n"), encoding="utf-8")
    assert read(box.get("/list?show=mine", member=NELL))["In progress 0"] == {}
    assert read(box.get("/list?show=mine", member=DORA))["In progress 1"] == {
        "initech/website": [("Prep for the call of Thursday James", "prep · you · #6 · 40 min")]}


def test_the_owner_shown_is_the_issues_first_assignee_even_when_no_member(box, github):
    github.issues[6]["assignees"] = ["zed-x", "dora-k"]
    box.hub.the_list.poll()
    assert read(box.get("/list", member=NELL))["In progress 1"] == {
        "initech/website": [("Prep for the call of Thursday James", "prep · zed-x · #6 · 40 min")]}


def test_an_owner_only_sheaf_deleted_after_a_poll_is_told_to_its_assignee_alone(box, sheaves, monkeypatch):
    from sheafmd.hub.index import SWEEP_SECONDS
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n",
                                                             "sources: [library:4711]\nowner: dora\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    now = [NOW]
    box.hub.clock = lambda: now[0]
    monkeypatch.setattr(box.hub.index, "_start_sweep", lambda run: run())
    nell, dora = (box.get("/_/live", member=m).stream for m in (NELL, DORA))
    for m in (NELL, DORA):
        box.get("/_/index.json", member=m)
    now[0] += SWEEP_SECONDS
    box.hub.tick()
    nell.drain(), dora.drain()
    joey.unlink()
    box.hub.the_list.poll()                             # the poll sees no sheaf there before the sweep does
    now[0] += SWEEP_SECONDS
    box.hub.tick()
    doc = f"{box.hub.roots.lookup(sheaves / 'projects.toml').name}/globex/black-friday/2026-10-28-reply-to-joey.md"
    assert [d["doc"] for name, d in nell.drain() if name == "status"] == [doc]
    assert [d for name, d in dora.drain() if name == "status"] == []


def test_an_issue_written_in_another_case_is_still_the_issue_the_list_polled(box, sheaves):
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n",
                                                             "sources: [library:4711]\nowner: dora\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5", "issue: Acme/Record#5"),
                    encoding="utf-8")
    root = box.hub.roots.lookup(joey).name
    address = f"/{root}/globex/black-friday/2026-10-28-reply-to-joey.md"
    assert box.get(address, member=NELL).status == 200
    assert box.get(address, member=DORA).status == 404
