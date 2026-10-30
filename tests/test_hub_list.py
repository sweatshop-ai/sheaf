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
import time
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from bs4 import BeautifulSoup
from helpers import FRONT, Front, call, hub_rows

from sheafmd.hub import place, proxy, the_list
from sheafmd.hub.state import Tokens
from sheafmd.hub.visibility import front_matter
from sheafmd.source import md_hash

NELL = "503b2f77-83de-452c-817a-a357faf85929"       # the front's ids of two members
DORA = "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"
TOKEN = "ghs_fake_" "installation_token"
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
    PAGE = re.compile(r'projectItems\(first: (\d+)(?:, after: "(\d+)")?\)')

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
                query = body["query"]
                found = list(fake.ALIAS.finditer(query))
                for k, m in enumerate(found):
                    alias, owner, name, number = m.groups()
                    part = query[m.end():found[k + 1].start() if k + 1 < len(found) else len(query)]
                    page = fake.PAGE.search(part)
                    first, after = (int(page.group(1)), int(page.group(2) or 0)) if page else (20, 0)
                    data[alias] = {"issue": fake.issue(owner, name, int(number), first, after)}
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

    def issue(self, owner, name, number, first=20, after=0):
        """The issue's fields, with the page of its Project items from item `after`, `first` of them; the
        items are those of `others` ((project number, Status), ...) then the item in Project 1 when it has a status."""
        i = self.issues.get(number) if (owner, name) == ("acme", "record") else None
        if i is None:
            return None
        status = i.get("status")
        items = [{"project": {"number": n, "owner": {"login": "acme"}}, "status": {"name": st}}
                 for n, st in i.get("others", ())]
        if status is not None:
            items.append({"project": {"number": 1, "owner": {"login": "acme"}}, "status": {"name": status}})
        page = items[after:after + first]
        return {"number": number, "state": i.get("state", "OPEN"), "stateReason": i.get("reason"),
                "updatedAt": i["updated"], "assignees": {"nodes": [{"login": a} for a in i["assignees"]]},
                "projectItems": {"nodes": page, "pageInfo": {"hasNextPage": after + first < len(items),
                                                             "endCursor": str(after + len(page))}}}

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
                # The title, then its action buttons and its assistant, as a reader scans the row.
                said = [row.select_one(".list-title")] + row.select(".list-actions > *") + row.select(".list-assistant")
                rows.append((" ".join(x.get_text(" ", strip=True) for x in said),
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


def test_all_of_the_team_leaves_out_the_projects_a_member_is_not_in(box):
    """`projects.toml` grants (8.12, #44): All of the team is what the reader may open, so a project that does
    not name them is not on it."""
    page = read(box.get("/list?show=all", member=DORA))
    assert list(page) == ["Waiting on you 1", "In progress 1"]
    assert "globex/black-friday" not in page["Waiting on you 1"]
    assert read(box.get("/list?show=all", member=NELL))["Waiting on you 2"]["globex/black-friday"] == [
        ("Reply to Joey about column L Approve James", "mail · you · #5 · 2 h")]


def test_my_projects_reads_projects_toml_as_it_is_now_not_as_the_last_poll_read_it(box, sheaves):
    """My projects judges by the file the hub grants by (8.12, #53): a member just added to a project has its rows
    there at their next request, as All of the team has, and one just taken off has them no more."""
    toml = sheaves / "projects.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('members = ["nell"]', 'members = ["nell", "dora"]'),
                    encoding="utf-8")
    assert "globex/black-friday" in read(box.get("/list", member=DORA))["Waiting on you 2"]
    toml.write_text(toml.read_text(encoding="utf-8").replace('members = ["nell", "dora"]', 'members = ["dora"]', 1),
                    encoding="utf-8")
    assert "globex/black-friday" not in read(box.get("/list", member=NELL))["Waiting on you 1"]


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


def test_a_sheaf_added_since_joins_the_list_only_at_a_poll_that_reads_the_record(box, sheaves, github, tmp_path):
    before = read(box.get("/list", member=NELL))
    # A new sheaf whose issue the last poll read: the record it would be listed by is not read this poll.
    (sheaves / "initech/website/2026-10-29-new.md").write_text(
        "---\nissue: acme/record#7\n---\n# A new one\n\n- [ ] Done\n", encoding="utf-8")
    (tmp_path / "installation-token").write_text("", encoding="utf-8")
    box.hub.the_list.poll()
    assert "holds no token" in hub_rows("list-poll-failed")[-1]["error"]
    assert read(box.get("/list", member=NELL)) == before
    (tmp_path / "installation-token").write_text(TOKEN + "\n", encoding="utf-8")
    box.hub.the_list.poll()
    assert "A new one" in json.dumps(read(box.get("/list", member=NELL)))


def test_a_poll_that_cannot_read_the_record_still_places_its_sheaves_on_the_last_records_read(box, sheaves, tmp_path):
    """A failed read keeps the list as it was, but a sheaf made owner-only since goes to its owner's private folder, the
    owner judged on the records the last good poll read (#45, agreed with #43's placement): here #5's assignee, Nell."""
    joey = sheaves / JOEY[5:]
    (tmp_path / "installation-token").write_text("", encoding="utf-8")
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    assert "holds no token" in hub_rows("list-poll-failed")[-1]["error"]
    assert (sheaves / "globex/black-friday/private/nell/2026-10-28-reply-to-joey.md").exists() and not joey.exists()


def test_an_issue_in_more_projects_than_one_page_still_has_the_status_of_its_item_in_the_lists_project(box, github):
    github.issues[5]["others"] = [(100 + k, "Waiting on member") for k in range(120)]
    github.issues[7]["others"] = [(300 + k, "In progress at TT") for k in range(30)]
    box.hub.the_list.poll()
    assert read(box.get("/list", member=NELL)) == {
        "Waiting on you 2": {
            "globex/black-friday": [("Reply to Joey about column L Approve James", "mail · you · #5 · 2 h")],
            "initech/website": [("James needs the GA4 property id Done @dora James", "question · @dora · #7 · 3 h")]},
        "In progress 1": {
            "initech/website": [("Prep for the call of Thursday James", "prep · @dora · #6 · 40 min")]}}


def test_the_pages_of_an_issues_project_items_end_at_ten_however_many_github_names(box, github):
    """Opus gate on #45, P3: the poll holds `_poll_lock` while it pages, so an answer that never ends must not hold it."""
    github.issues[5]["others"] = [(1000 + k, "Waiting on member") for k in range(2000)]
    before = github.requests
    box.hub.the_list.poll()
    assert github.requests - before == the_list.PAGES          # the first page with the rest, then nine of #5's
    assert "Reply to Joey" not in json.dumps(read(box.get("/list", member=NELL)))    # its item was never read


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


Button = namedtuple("Button", "href doc action word kind label")


def buttons(res):
    """Each row's action buttons, in row order: its title link, data-doc, data-action, data-word, its kind
    (`one-off` or `toggle`, by its class) and its label."""
    soup = BeautifulSoup(res.text, "html.parser")
    out = []
    for row in soup.select(".list-row"):
        assert row.select_one("input[type=checkbox]") is None      # the row's one box is gone (#107)
        for b in row.select("button.list-act"):
            assert not b.has_attr("disabled")
            kind = next(k for k in ("one-off", "toggle") if k in b["class"])
            assert b.has_attr("aria-pressed") == (kind == "toggle")      # a one-off is no toggle to a screen reader
            out.append(Button(row.select_one("a.list-title")["href"], b["data-doc"], b["data-action"], b["data-word"],
                              kind, b.get_text(" ", strip=True)))
    return out


def test_a_row_carries_a_button_for_its_action_that_names_its_sheaf_and_the_member_it_names(box):
    assert buttons(box.get("/list", member=NELL)) == [
        ("/list/globex/black-friday/2026-10-28-reply-to-joey.md", JOEY, "0", "Approve", "one-off", "Approve"),
        ("/list/initech/website/2026-10-27-ga4-property.md", "list/initech/website/2026-10-27-ga4-property.md",
         "0", "Done", "one-off", "Done @dora")]


def test_every_action_of_a_row_is_a_button_one_off_but_share_which_is_a_toggle(box, sheaves):
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Approve\n", "- [ ] Approve\n- [x] Read the brief\n- [ ] Done\n- [ ] Share\n"), encoding="utf-8")
    box.hub.the_list.poll()
    res = box.get("/list", member=NELL)
    assert [(b.action, b.word, b.kind) for b in buttons(res) if b.doc == JOEY] == [
        ("0", "Approve", "one-off"), ("1", "Done", "one-off"), ("2", "Share", "toggle")]
    share = BeautifulSoup(res.text, "html.parser").select_one(f'button[data-doc="{JOEY}"][data-word="Share"]')
    assert share["aria-pressed"] == "false"


def test_the_rows_second_button_ticks_the_second_action_and_no_other(box, sheaves):
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [ ] Approve\n- [ ] Done\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    before = path.read_text(encoding="utf-8")
    r = box.post("/_/tick", row_press(box.get("/list", member=NELL), JOEY, "Done"), member=NELL)
    assert r.status == 200, r.text
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Done", "- [x] Done")


def test_a_tick_on_the_row_is_answered_in_the_sheaf_and_the_row_leaves_waiting_on_you(box, sheaves, github):
    before = (sheaves / JOEY[5:]).read_text(encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
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
        r = box.post("/_/tick", now(box, body), member=NELL)
        assert r.status == 409, r.text
        assert "reload the list" in r.json()["error"]
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL).status == 200
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL).status == 409
    assert (sheaves / JOEY[5:]).read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


def now(box, body):
    """`body` with the hash of its sheaf's text as it is now: the tick of a list read just now. The file is the one
    that holds the sheaf's name, wherever it is placed (9.11)."""
    top = box.hub.the_list.root().path
    rel = place.file_rel(top, body["doc"].split("/", 1)[1])
    return {**body, "hash": md_hash((top / rel).read_text(encoding="utf-8"))}


def row_press(res, doc, word=None):
    """The tick the row of `doc` would post on a press of its button for `word` (its first button without one):
    the button's doc, action, word and hash."""
    found = BeautifulSoup(res.text, "html.parser").select(f'button.list-act[data-doc="{doc}"]')
    b = next(b for b in found if word is None or b["data-word"] == word)
    return {"doc": b["data-doc"], "action": int(b["data-action"]), "word": b["data-word"], "hash": b["data-hash"]}


def test_a_tick_from_a_stale_row_does_not_tick_the_next_action_with_the_same_word(box, sheaves):
    tick = row_press(box.get("/list", member=NELL), JOEY)
    joey = sheaves / JOEY[5:]
    # Since the list was read, the first Approve was ticked in the page and a second one added below it.
    joey.write_text(joey.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [x] Approve\n- [ ] Approve\n"),
                    encoding="utf-8")
    before = joey.read_text(encoding="utf-8")
    r = box.post("/_/tick", tick, member=NELL)
    assert r.status == 409, r.text
    assert "reload the list" in r.json()["error"]
    assert joey.read_text(encoding="utf-8") == before


def test_the_rows_tick_of_a_sheaf_the_poll_placed_in_a_private_folder_lands_in_that_file(box, sheaves):
    """Opus gate on #45, P3: the row's hash is of the text the poll read, wherever the file sits (9.11)."""
    joey = sheaves / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    home = sheaves / "globex/black-friday/private/nell/2026-10-28-reply-to-joey.md"
    assert home.exists() and not joey.exists()
    before = home.read_text(encoding="utf-8")
    r = box.post("/_/tick", row_press(box.get("/list", member=NELL), JOEY), member=NELL)
    assert r.status == 200, r.text
    assert home.read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


def test_a_tick_ticks_the_action_the_row_showed_though_the_hubs_copy_of_a_page_no_tab_holds_is_older(box, sheaves):
    """Opus gate on #45, P1: a sheaf opened once and closed keeps its entry, which the watcher no longer refreshes. A
    question written above its Approve since is the row's action 0: the tick lands there, not on the old Approve."""
    joey = sheaves / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [ ] Approve @nell\n"),
                    encoding="utf-8")
    assert box.get("/" + JOEY, member=NELL).status == 200          # opened once; no tab listens now
    joey.write_text(joey.read_text(encoding="utf-8").replace(
        "# Reply to Joey about column L\n\n", "# Reply to Joey about column L\n\n- [ ] Approve\n\nA second question.\n\n"),
        encoding="utf-8")
    box.hub.the_list.poll()
    before = joey.read_text(encoding="utf-8")
    r = box.post("/_/tick", row_press(box.get("/list", member=NELL), JOEY), member=NELL)
    assert r.status == 200, r.text
    assert joey.read_text(encoding="utf-8") == before.replace("- [ ] Approve\n", "- [x] Approve\n", 1)


def test_a_tick_after_a_write_the_hubs_stat_check_cannot_see_still_lands(box, sheaves):
    """Opus delta check on #45, P3: a write of the same size in the same clock tick leaves (mtime, size) as it was, so
    catch_up keeps the old copy; the tick reads the file once more rather than refusing every retry."""
    joey = sheaves / JOEY[5:]
    assert box.get("/" + JOEY, member=NELL).status == 200          # the hub's copy, then no tab
    st = joey.stat()
    joey.write_text(joey.read_text(encoding="utf-8").replace("The draft.", "Our draft."), encoding="utf-8")
    os.utime(joey, ns=(st.st_atime_ns, st.st_mtime_ns))
    box.hub.the_list.poll()
    before = joey.read_text(encoding="utf-8")
    r = box.post("/_/tick", row_press(box.get("/list", member=NELL), JOEY), member=NELL)
    assert r.status == 200, r.text
    assert joey.read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


@pytest.mark.parametrize("body", [{"doc": JOEY, "word": "Approve"}, {"doc": JOEY, "action": "0", "word": "Approve"},
                                  {"doc": JOEY, "action": True, "word": "Approve"}, {"doc": JOEY, "action": 0},
                                  {"doc": JOEY, "action": 0, "word": ""},
                                  {"doc": JOEY, "action": 0, "word": "Approve"},
                                  {"doc": JOEY, "action": 0, "word": "Approve", "hash": 7}])
def test_a_tick_that_does_not_name_an_action_is_refused(box, body):
    assert box.post("/_/tick", body, member=NELL).status == 400


def test_a_member_cannot_tick_a_sheaf_outside_their_roots(box, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    cfg = box.hub.proxy
    box.hub.proxy = proxy.parse({"origin": FRONT, "socket": str(cfg.socket), "proxy_user": cfg.proxy_user,
                                 "members": {DORA: {"name": "Dora", "short": "dora", "roots": [str(other)]}}},
                                "the test")
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=DORA).status == 404


def test_the_tick_inside_a_list_of_other_boxes_flips_that_one_line(box, sheaves):
    path = sheaves / "initech/website/2026-10-27-ga4-property.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Done @dora\n", "- [x] Read the brief\n- [ ] Done @dora\n- [ ] Share\n"), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    doc = "list/initech/website/2026-10-27-ga4-property.md"
    assert box.post("/_/tick", now(box, {"doc": doc, "action": 1, "word": "Share"}), member=DORA).status == 200
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
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL).status == 200
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


def test_an_action_above_a_rule_after_the_front_matter_is_still_read():
    s = the_list.read_sheaf("a/b/c.md", SHEAVES["globex/black-friday/2026-10-28-reply-to-joey.md"] + "\n---\n\nMore.\n")
    assert [(w, short) for w, short, _, _ in s.actions] == [("Approve", "")]
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
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL).status == 200
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
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL).status == 200
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
    assert [(w, short) for w, short, _, _ in s.actions] == [("Done", "")]


def test_an_action_inside_an_html_comment_is_no_action():
    s = the_list.read_sheaf("a/b/c.md", "# A sheaf\n\n<!--\n- [ ] Approve\n-->\n\n- [ ] Done\n")
    assert [(w, line) for w, _, line, _ in s.actions] == [("Done", 6)]


def test_an_indented_code_line_holding_a_fence_opens_no_fence():
    s = the_list.read_sheaf("a/b/c.md", "# A sheaf\n\n    ```\n\n- [ ] Approve\n")
    assert [(w, line) for w, _, line, _ in s.actions] == [("Approve", 4)]


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
    r = box.post("/_/tick", now(box, {"doc": "list/initech/website/2026-10-28-odd.md", "action": 0, "word": "Approve"}),
                 member=NELL)
    assert r.status in (200, 409), r.text       # no sheaf, still a document: its one box, or nothing
    assert path.read_text(encoding="utf-8") in (before, before.replace("- [ ] Approve", "- [x] Approve"))


def test_all_of_the_team_leaves_out_a_sheaf_closed_since_the_last_poll(box, sheaves):
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    assert all("globex/black-friday" not in groups for groups in read(box.get("/list?show=all", member=DORA)).values())


JOEY_NAME = "globex/black-friday/2026-10-28-reply-to-joey.md"
JOEY_HOME = "globex/black-friday/private/nell/2026-10-28-reply-to-joey.md"


def closed_joey(sheaves, sources="sources: [library:4711]\n"):
    """Joey's sheaf made its owner's alone (`sources` in the place of `visibility: project`), its file at its home
    (9.11): the private folder of its issue's assignee, Nell, where the poll would move it. Its address stays
    `JOEY_NAME`."""
    joey = sheaves / "globex/black-friday/2026-10-28-reply-to-joey.md"
    home = sheaves / JOEY_HOME
    home.parent.mkdir(parents=True)
    home.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", sources), encoding="utf-8")
    joey.unlink()
    return home


def test_a_link_at_a_sheafs_path_is_no_document_even_to_the_owner_of_the_sheaf_it_names(box, sheaves):
    """A link holds no name (9.11): a second name of one file would be a second name lock over its one file lock.
    The sheaf is its owner's by its own name; the link answers as a document that does not exist, to everyone."""
    joey = closed_joey(sheaves, "sources: [library:4711]\nowner: dora\n")
    (sheaves / "globex/black-friday/joey.md").symlink_to(f"private/nell/{joey.name}")
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    assert box.get(f"/{root}/{JOEY_NAME}", member=DORA).status == 404
    assert box.get(f"/{root}/{JOEY_NAME}", member=NELL).status == 200
    assert box.get(f"/{root}/globex/black-friday/joey.md", member=DORA).status == 404
    assert box.get(f"/{root}/globex/black-friday/joey.md", member=NELL).status == 404


def test_a_link_the_poll_does_not_read_is_no_document_even_to_the_owner_of_the_sheaf_it_names(box, sheaves):
    """No address of the list's root reaches a file through a link, at any depth (9.11, Opus round 8)."""
    joey = closed_joey(sheaves, "sources: [library:4711]\nowner: dora\n")
    (sheaves / ".kept").mkdir()
    (sheaves / ".kept/joey.md").symlink_to(joey)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    assert box.get(f"/{root}/.kept/joey.md", member=DORA).status == 404
    assert box.get(f"/{root}/.kept/joey.md", member=NELL).status == 404


@pytest.mark.parametrize("issue", ["issue:\n", "issue: acme/record#7\n"], ids=["removed", "changed"])
def test_a_sheaf_whose_issue_changed_since_the_poll_is_not_its_old_assignees(box, sheaves, issue):
    joey = closed_joey(sheaves)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    address = f"/{root}/{JOEY_NAME}"
    assert box.get(address, member=NELL).status == 200          # the assignee of #5 owns it
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", issue + "owner: dora\n"),
                    encoding="utf-8")
    assert box.get(address, member=NELL).status == 404          # before the next poll
    assert box.get(address, member=DORA).status == 200


@pytest.mark.parametrize("issue", ["issue:\n", "issue: acme/record#7\n"], ids=["removed", "changed"])
def test_a_tick_after_the_issue_changed_does_not_give_the_old_assignees_back(box, sheaves, issue):
    joey = closed_joey(sheaves)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    address = f"/{root}/{JOEY_NAME}"
    assert box.get(address, member=NELL).status == 200          # the assignee of #5 owns it
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", issue + "owner: dora\n"),
                    encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": address[1:], "action": 0, "word": "Approve"}), member=DORA)
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
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
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
    joey = closed_joey(sheaves, "sources: [library:4711]\nowner: dora\n")
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
    doc = f"{box.hub.roots.lookup(sheaves / 'projects.toml').name}/{JOEY_NAME}"
    assert [d["doc"] for name, d in nell.drain() if name == "status"] == [doc]
    assert [d for name, d in dora.drain() if name == "status"] == []


def test_an_issue_written_in_another_case_is_still_the_issue_the_list_polled(box, sheaves):
    joey = closed_joey(sheaves, "sources: [library:4711]\nowner: dora\n")
    box.hub.the_list.poll()
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5", "issue: Acme/Record#5"),
                    encoding="utf-8")
    root = box.hub.roots.lookup(joey).name
    address = f"/{root}/{JOEY_NAME}"
    assert box.get(address, member=NELL).status == 200
    assert box.get(address, member=DORA).status == 404


def bind_tokens(box, sheaves):
    """Nell's and Dora's door tokens, `nell-door` and `dora-door`, bound to them (9.11), both members of both
    projects (8.12): what these tests judge is a sheaf's own visibility, not the grant."""
    text = (sheaves / "projects.toml").read_text(encoding="utf-8")
    (sheaves / "projects.toml").write_text(text.replace('members = ["nell"]', 'members = ["nell", "dora"]'),
                                           encoding="utf-8")
    box.hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                                 "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                                 "members": {NELL: {"name": "Nell", "short": "nell", "github": "nell-l",
                                                    "roots": [str(sheaves)], "tokens": ["nell-door"]},
                                             DORA: {"name": "Dora", "short": "dora", "github": "dora-k",
                                                    "roots": [str(sheaves)], "tokens": ["dora-door"]}}}, "the test")
    return {name: Tokens().add(name, write=True) for name in ("nell-door", "dora-door")}


def hidden_joey(sheaves):
    """Joey's sheaf, its owner's alone and with no `owner`: its issue's assignee, Nell, owns it."""
    return closed_joey(sheaves)


def test_a_door_update_of_a_sheaf_its_assignee_alone_owns_keeps_it_theirs_once_the_issue_is_not_polled(
        box, browser, sheaves, github):
    """#33: the record names the owner only while the list polls the issue; the `owner` the write gives
    it is the one after."""
    tokens = bind_tokens(box, sheaves)
    joey = hidden_joey(sheaves)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    doc = f"{root}/{JOEY_NAME}"
    before = joey.read_text(encoding="utf-8")
    is_error, got = call(browser, "update", token=tokens["nell-door"], doc=doc, expected_hash=md_hash(before),
                         text=before.replace("The draft.", "The draft, again."))
    assert not is_error, got
    assert front_matter(joey.read_text(encoding="utf-8"))["owner"] == "nell"
    del github.issues[5]                                # moved to another repo: the list no longer knows it
    box.hub.the_list.poll()
    assert box.get(f"/{doc}", member=NELL).status == 200
    assert box.get(f"/{doc}", member=DORA).status == 404


@pytest.mark.parametrize("issue", ["acme/record#5", "acme/record#7"], ids=["its-issue", "another"])
def test_a_door_create_where_a_hidden_sheaf_was_deleted_answers_the_same_whatever_issue_it_names(
        box, browser, sheaves, issue):
    """#34: until the next poll the list still has the deleted sheaf's row; neither the create's answer nor
    a read after it tells which issue that sheaf named."""
    tokens = bind_tokens(box, sheaves)
    joey = hidden_joey(sheaves)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    doc = f"{root}/globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.unlink()
    text = f"---\nissue: {issue}\nsources: [library:1]\n---\n# A guess\n"
    is_error, got = call(browser, "create", token=tokens["dora-door"], doc=doc, text=text)
    assert not is_error, got
    assert got["doc"] == doc                                    # its name; its file is in Dora's folder (9.11)
    dora = sheaves / f"globex/black-friday/private/dora/{joey.name}"
    assert front_matter(dora.read_text(encoding="utf-8"))["owner"] == "dora"
    is_error, got = call(browser, "read", token=tokens["dora-door"], doc=doc)
    assert not is_error, got


@pytest.mark.parametrize("issue", ["acme/record#5", "acme/record#7"], ids=["its-issue", "another"])
def test_an_unbound_create_where_a_hidden_sheaf_was_deleted_is_refused_whatever_issue_it_names(
        box, browser, sheaves, issue):
    """#34: a token bound to nobody gives no owner, so the stale row of the deleted sheaf is no owner either."""
    joey = hidden_joey(sheaves)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    joey.unlink()
    is_error, got = call(browser, "create", token=Tokens().add("mistral", write=True),
                         doc=f"{root}/globex/black-friday/2026-10-28-reply-to-joey.md",
                         text=f"---\nissue: {issue}\nsources: [library:1]\n---\n# A guess\n")
    assert is_error and "no member as its owner" in got, got
    assert not joey.exists()


def test_a_poll_that_read_a_hidden_sheaf_before_it_went_does_not_bring_its_row_back(
        box, browser, sheaves, monkeypatch):
    """#34, Codex: the sheaf goes and a door create takes its address while a poll that read it asks GitHub;
    the snapshot that poll publishes judges the new sheaf without the row."""
    tokens = bind_tokens(box, sheaves)
    joey = hidden_joey(sheaves)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    doc = f"{root}/globex/black-friday/2026-10-28-reply-to-joey.md"
    fetch = the_list.fetch

    def meanwhile(cfg, wanted):
        joey.unlink()
        is_error, got = call(browser, "create", token=tokens["dora-door"], doc=doc,
                             text="---\nissue: acme/record#5\nsources: [library:1]\n---\n# A guess\n")
        assert not is_error, got
        return fetch(cfg, wanted)
    monkeypatch.setattr(the_list, "fetch", meanwhile)
    box.hub.the_list.poll()
    monkeypatch.setattr(the_list, "fetch", fetch)
    is_error, got = call(browser, "read", token=tokens["dora-door"], doc=doc)
    assert not is_error, got
    box.hub.the_list.poll()                             # a poll that read the new sheaf: its issue's assignee owns it
    is_error, got = call(browser, "read", token=tokens["dora-door"], doc=doc)
    assert is_error, got


@pytest.mark.parametrize("through", ["its-address", "a-link"])
def test_a_sheaf_made_where_a_hidden_one_went_is_listed_by_what_it_says_not_what_that_one_said(
        box, browser, sheaves, through):
    """Codex, Opus: a row the poll read from a hidden sheaf goes with its file, a link's row to it too; the
    sheaf made at its address, open to the project, is listed by its own text from the next poll."""
    tokens = bind_tokens(box, sheaves)
    joey = hidden_joey(sheaves)
    joey.write_text(joey.read_text(encoding="utf-8").replace("# Reply to Joey about column L", "# Secret title"),
                    encoding="utf-8")
    if through == "a-link":
        (sheaves / "globex/black-friday/joey.md").symlink_to(f"private/nell/{joey.name}")
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    joey.unlink()
    is_error, got = call(browser, "create", token=tokens["dora-door"],
                         doc=f"{root}/globex/black-friday/2026-10-28-reply-to-joey.md",
                         text="---\nissue: acme/record#5\nvisibility: project\n---\n# Open title\n\n- [ ] Approve\n")
    assert not is_error, got
    shown = str(read(box.get("/list?show=all", member=DORA)))
    assert "Secret title" not in shown and "Open title" not in shown, shown   # the row waits for the next poll
    box.hub.the_list.poll()
    shown = str(read(box.get("/list?show=all", member=DORA)))
    assert "Secret title" not in shown and "Open title" in shown, shown


@pytest.mark.parametrize("issue", ["acme/record#5", "acme/record#7"], ids=["its-issue", "another"])
def test_an_open_create_where_a_hidden_sheaf_went_then_closed_answers_the_same_whatever_issue_it_names(
        box, browser, sheaves, issue):
    """Opus: a create open to the project drops the row of the sheaf that went too, so an update that closes it
    is owned by the token's member, whatever issue it names, and the list shows it to nobody before a poll."""
    tokens = bind_tokens(box, sheaves)
    joey = hidden_joey(sheaves)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    doc = f"{root}/globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.unlink()
    is_error, got = call(browser, "create", token=tokens["dora-door"], doc=doc,
                         text=f"---\nissue: {issue}\nvisibility: project\n---\n# A guess\n\n- [ ] Approve\n")
    assert not is_error, got
    assert "A guess" not in str(read(box.get("/list?show=all", member=DORA)))
    now = (sheaves / "globex/black-friday" / joey.name).read_text(encoding="utf-8")
    is_error, got = call(browser, "update", token=tokens["dora-door"], doc=doc, expected_hash=md_hash(now),
                         text=now.replace("visibility: project\n", "sources: [library:1]\n"))
    assert not is_error, got
    assert got["doc"] == doc                                    # its name; its file moved to Dora's folder (9.11)
    dora = sheaves / f"globex/black-friday/private/dora/{joey.name}"
    assert front_matter(dora.read_text(encoding="utf-8"))["owner"] == "dora"


def joey_with_a_figure(sheaves):
    """Joey's sheaf, which names an image of its project, `globex/black-friday/fig.png`."""
    from PIL import Image
    Image.new("RGB", (4, 4), (200, 30, 30)).save(sheaves / "globex/black-friday/fig.png")
    joey = sheaves / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace("The draft.", "The draft. ![the figure](fig.png)"),
                    encoding="utf-8")
    return joey


def test_a_sheaf_whose_issue_is_assigned_outside_its_project_embeds_none_of_its_images(box, sheaves, github):
    """On the list's root a sheaf's owner is its issue's assignee (9.11), and an owner the project's `members` do
    not hold leaves out the project's images (#81, #91): the record moves them, the file does not."""
    joey = joey_with_a_figure(sheaves)
    before = joey.read_text(encoding="utf-8")
    assert "data:image/png" in box.get(f"/{JOEY}", member=NELL).text      # #5 is Nell's, in the project
    github.issues[5]["assignees"] = ["dora-k"]                          # Dora is in initech/website only
    box.hub.the_list.poll()
    assert "data:image/png" not in box.get(f"/{JOEY}", member=NELL).text
    github.issues[5]["assignees"] = ["nell-l"]
    box.hub.the_list.poll()
    assert "data:image/png" in box.get(f"/{JOEY}", member=NELL).text
    github.issues[5]["assignees"] = ["dora-k"]
    box.hub.the_list.poll()
    assert "data:image/png" not in box.get(f"/{JOEY}", member=NELL).text
    assert joey.read_text(encoding="utf-8") == before


def test_renders_that_ask_the_list_for_owners_and_a_poll_that_drops_a_row_all_finish(box, sheaves, github):
    """`_build` judges the images by the owners, so a render asks `the_list.assignees` under the document's lock,
    which takes the name's lock and `_off_lock` (#81, #91). Renders of a list sheaf beside a poll and asks that
    drop the row of a file gone since all finish, with no deadlock and no exception."""
    joey_with_a_figure(sheaves)
    assert box.get(f"/{JOEY}", member=NELL).status == 200
    e = box.hub.entries[JOEY]
    gone_rel = "initech/website/2026-10-27-ga4-property.md"
    gone = sheaves / gone_rel
    kept = gone.read_text(encoding="utf-8")
    errors, stop, steps = [], threading.Event(), [0]

    def rows():
        return {r.sheaf.rel for r in box.hub.the_list._snap.rows}

    def render():
        try:
            while not stop.is_set():
                e.live.rebuild()
                assert box.get(f"/{JOEY}", member=NELL).status == 200
        except Exception as ex:                 # noqa: BLE001 - every failure is the test's
            errors.append(ex)

    def drop():
        try:
            for _ in range(10):
                assert gone_rel in rows()
                gone.unlink()
                assert box.hub.the_list.assignees(f"list/{gone_rel}", "acme/record#7") is None
                assert gone_rel not in rows()                                                    # its row dropped
                box.hub.the_list.poll()
                gone.write_text(kept, encoding="utf-8")
                box.hub.the_list.poll()
                steps[0] += 1
        except Exception as ex:                 # noqa: BLE001
            errors.append(ex)
        finally:
            stop.set()

    threads = [threading.Thread(target=render, daemon=True) for _ in range(3)] + \
              [threading.Thread(target=drop, daemon=True)]
    for t in threads:
        t.start()
    # Stuck is a drop that takes no step for 30 s, not a run that takes 30 s: a 3-core macOS runner took
    # 30.7 s for what takes 4 s on Linux.
    seen, still = steps[0], time.monotonic()
    while any(t.is_alive() for t in threads) and time.monotonic() - still < 30:
        threads[-1].join(timeout=0.5)
        if steps[0] != seen:
            seen, still = steps[0], time.monotonic()
    stop.set()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a render or the poll is stuck: a deadlock"
    assert errors == []
    assert "data:image/png" in e.html


@pytest.mark.parametrize("issue", ["issue:\n", "issue: acme/record#7\n"], ids=["removed", "changed"])
def test_a_poll_that_read_a_sheaf_before_a_tick_took_its_row_off_does_not_put_it_back(
        box, sheaves, github, monkeypatch, issue):
    """#27 (2): the file loses its issue and a member ticks while a poll that read it asks GitHub; the snapshot
    that poll publishes holds no row of the issue the sheaf no longer names, until the next poll."""
    github.issues[5].update(status="In progress at TT")         # drawn, not left out as answered
    box.hub.the_list.poll()
    joey = sheaves / JOEY[5:]
    fetch = the_list.fetch

    def meanwhile(cfg, wanted):
        joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", issue), encoding="utf-8")
        r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
        assert r.status == 200, r.text
        assert JOEY[5:] not in {r.sheaf.rel for r in box.hub.the_list._snap.rows}    # the tick took it off
        return fetch(cfg, wanted)
    monkeypatch.setattr(the_list, "fetch", meanwhile)
    box.hub.the_list.poll()
    monkeypatch.setattr(the_list, "fetch", fetch)
    for m in (NELL, DORA):
        assert "Reply to Joey about column L James" not in titles(read(box.get("/list?show=all", member=m)))
    assert JOEY[5:] not in {r.sheaf.rel for r in box.hub.the_list._snap.rows}
    box.hub.the_list.poll()
    listed = "Reply to Joey about column L James" in titles(read(box.get("/list?show=all", member=DORA)))
    assert listed == (issue != "issue:\n")                      # back under #7; with no issue, on no list (9.10)


# ── Move to: the eighth word, and the pointer a move leaves (tt-tiroir#211) ──

CLIENT = """
## Client

The sender writes from dexis.be, which Dexis and Klium share. Which client is this thread for?

- [ ] Move to dexis (ref 18f3a9c2)
- [ ] Move to klium (ref 18f3a9c2)
- [ ] Move to thinkingtoo (ref 18f3a9c2)
"""


def test_a_move_to_box_with_its_slug_and_ref_is_an_action_with_the_word_move_to():
    s = the_list.read_sheaf("a/b/c.md", "# A sheaf\n\n- [ ] Move to klium (ref 18f3a9c2)\n")
    assert s.actions == (("Move to", "", 2, "klium"),)


def test_a_client_section_of_three_boxes_gives_three_actions_in_its_order():
    s = the_list.read_sheaf("a/b/c.md", "# A sheaf\n" + CLIENT)
    assert [(w, line, arg) for w, _, line, arg in s.actions] == [
        ("Move to", 6, "dexis"), ("Move to", 7, "klium"), ("Move to", 8, "thinkingtoo")]


def test_a_move_to_the_hub_gave_back_escaped_reads_its_slug_unescaped():
    s = the_list.read_sheaf("a/b/c.md", "# A sheaf\n\n- [ ] Move to newtrition\\-coach (ref 18f\\_3a)\n")
    assert [(w, arg) for w, _, _, arg in s.actions] == [("Move to", "newtrition-coach")]


@pytest.mark.parametrize("line", ["- [ ] Move to", "- [ ] Move to klium", "- [ ] Move to (ref 18f3a9c2)",
                                  "- [ ] Move to klium (ref 18f3a9c2) now", "- [ ] Move klium (ref 18f3a9c2)",
                                  "- [ ] Archive", "- [ ] Undo skip (ref 18f3a9c2)", "- [ ] Approve klium"])
def test_a_line_with_an_unknown_word_or_a_move_to_without_its_argument_is_still_no_action(line):
    assert the_list.read_sheaf("a/b/c.md", f"# A sheaf\n\n{line}\n").actions == ()


def test_tick_edit_ticks_the_move_to_box_of_its_index():
    from sheafmd.blocks import split_md_blocks
    text = "# A sheaf\n" + CLIENT
    edit = the_list.tick_edit(text, 1, "Move to")
    block = split_md_blocks(text)[edit["i"]]
    assert block.kind == "list"
    assert edit["html"].count("checked") == 1
    soup = BeautifulSoup(edit["html"], "html.parser")
    ticked = [" ".join(li.get_text(" ").split()) for li in soup.select("li") if li.find("input", checked=True)]
    assert ticked == ["Move to klium (ref 18f3a9c2)"]
    assert the_list.tick_edit(text, 1, "Approve") is None


def unsure(sheaves):
    """Joey's sheaf with the Client section of an unsure thread in place of its Approve."""
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", CLIENT.lstrip("\n")), encoding="utf-8")
    return path


def test_a_tick_of_the_second_move_to_ticks_that_box_and_no_other(box, sheaves):
    path = unsure(sheaves)
    box.hub.the_list.poll()
    before = path.read_text(encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 1, "word": "Move to"}), member=NELL)
    assert r.status == 200, r.text
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Move to klium", "- [x] Move to klium")


def test_a_row_of_move_to_boxes_draws_one_one_off_button_per_candidate_named_by_its_slug(box, sheaves):
    unsure(sheaves)
    box.hub.the_list.poll()
    res = box.get("/list", member=NELL)
    assert read(res)["Waiting on you 2"]["globex/black-friday"] == [
        ("Reply to Joey about column L Move to dexis Move to klium Move to thinkingtoo James", "mail · you · #5 · 2 h")]
    href = "/list/globex/black-friday/2026-10-28-reply-to-joey.md"
    assert [b for b in buttons(res) if b.doc == JOEY] == [
        (href, JOEY, str(n), "Move to", "one-off", f"Move to {slug}") for n, slug in enumerate(("dexis", "klium",
                                                                                                 "thinkingtoo"))]


@pytest.mark.parametrize("mark", ["x", "X"])
def test_once_a_move_to_is_ticked_the_other_candidates_are_no_actions_and_other_words_stay(mark):
    s = the_list.read_sheaf("a/b/c.md", "# A sheaf\n" + CLIENT.replace("- [ ] Move to klium", f"- [{mark}] Move to klium")
                            + "\n- [ ] Done\n")
    assert [(w, arg) for w, _, _, arg in s.actions] == [("Done", "")]


def test_a_row_whose_move_to_is_ticked_draws_no_move_to_button(box, sheaves):
    path = unsure(sheaves)
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Move to klium", "- [x] Move to klium"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    assert [b for b in buttons(box.get("/list?show=all", member=NELL)) if b.word == "Move to"] == []


@pytest.mark.parametrize("old, new, slug", [
    ("- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n",
     "- [x] Move to klium (ref t1)\n- [x] Move to acme (ref t1)\n", "klium"),           # a second tick
    ("- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n",
     "- [ ] Move to klium (ref t1)\n- [x] Move to acme (ref t1)\n", "klium"),           # the two swapped
    ("- [x] Move to klium (ref t1)\n", "- [x] Move to acme (ref t1)\n", "klium"),       # its slug rewritten
    ("- [ ] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n",
     "- [x] Move to klium (ref t1)\n- [x] Move to acme (ref t1)\n", "klium"),           # two in one save
])
def test_a_write_that_ticks_another_move_to_names_the_one_ticked(old, new, slug):
    assert the_list.ticks_another_move(f"# A sheaf\n\n{old}", f"# A sheaf\n\n{new}") == slug


@pytest.mark.parametrize("old, new", [
    ("- [ ] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n",
     "- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n"),                    # the first tick
    ("- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n",
     "- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n\nText.\n"),          # another edit
    ("- [x] Move to klium (ref t1)\n", "- [x] Move to klium (ref t1)\n- [ ] Approve\n"),
    ("- [ ] Move to newtrition-coach (ref t1)\n", "- [x] Move to newtrition\\-coach (ref t1)\n"),
    ("- [x] Move to newtrition-coach (ref t1)\n", "- [x] Move to newtrition\\-coach (ref t1)\n"),  # escaped back
    ("```\n- [x] Move to klium (ref t1)\n```\n- [ ] Move to acme (ref t1)\n",
     "```\n- [x] Move to klium (ref t1)\n```\n- [x] Move to acme (ref t1)\n"),         # in a fence: no box
])
def test_a_write_that_ticks_no_other_move_to_names_none(old, new):
    assert the_list.ticks_another_move(f"# A sheaf\n\n{old}", f"# A sheaf\n\n{new}") is None


def pointer(sheaves):
    """Joey's sheaf as the pointer a move leaves: its front matter with `moved_to:`, and one line."""
    path = sheaves / JOEY[5:]
    text = path.read_text(encoding="utf-8")
    head = text[:text.index("---\n", 4)]
    path.write_text(head + "moved_to: klium/inbox/2026-10-28-reply-to-joey.md\n---\n"
                    "Moved to `klium/inbox/2026-10-28-reply-to-joey.md` on 2026-10-30.\n", encoding="utf-8")


def test_a_sheaf_whose_front_matter_has_moved_to_is_not_a_row(box, sheaves):
    pointer(sheaves)
    box.hub.the_list.poll()
    page = read(box.get("/list", member=NELL))
    assert "globex/black-friday" not in page["Waiting on you 1"]
    assert JOEY[5:] not in {r.sheaf.rel for r in box.hub.the_list._snap.rows}


def test_a_sheaf_that_became_a_pointer_since_the_poll_leaves_the_page_at_once(box, sheaves):
    assert "globex/black-friday" in read(box.get("/list", member=NELL))["Waiting on you 2"]
    pointer(sheaves)
    page = read(box.get("/list", member=NELL))
    assert not any("joey" in t.lower() for t in titles(page)), page


def test_a_row_whose_move_to_boxes_come_before_another_action_carries_the_button_of_each(box, sheaves):
    path = unsure(sheaves)
    path.write_text(path.read_text(encoding="utf-8").replace("The draft.\n", "The draft.\n\n- [ ] Approve\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    assert [(b.action, b.word, b.label) for b in buttons(box.get("/list", member=NELL)) if b.doc == JOEY] == [
        ("0", "Move to", "Move to dexis"), ("1", "Move to", "Move to klium"),
        ("2", "Move to", "Move to thinkingtoo"), ("3", "Approve", "Approve")]


# ── a one-off stays pressed (#108) ────────────────────────────────────────────

@pytest.mark.parametrize("old, new, word", [
    ("- [x] Approve\n", "- [ ] Approve\n", "Approve"),
    ("- [X] Done @nell\n", "- [ ] Done @nell\n", "Done"),
    ("- [x] Don’t run\n", "- [ ] Don't run\n", "Don't run"),
    ("- [x] Stop James\n", "* [ ] Stop James\n", "Stop James"),
    ("- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n",
     "- [ ] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n", "Move to"),
    ("- [x] Approve\n- [x] Approve\n", "- [x] Approve\n- [ ] Approve\n", "Approve"),
    ("- [x] Approve @nell\n", "- [ ] Approve\n", "Approve"),                # the member it names dropped
    ("- [x] Done @nell\n", "- [ ] Done @dora\n", "Done"),                   # or changed
    ("- [x] Approve\n\nText.\n\n- [ ] Approve\n", "- [ ] Approve\n\nText.\n", "Approve"),   # another box taken out
])
def test_a_write_that_unticks_a_one_off_names_its_word(old, new, word):
    assert the_list.unticks_one_off(f"# A sheaf\n\n{old}", f"# A sheaf\n\n{new}") == word


@pytest.mark.parametrize("old, new", [
    ("- [x] Share\n", "- [ ] Share\n"),                                 # the toggle
    ("- [ ] Approve\n", "- [x] Approve\n"),                             # a tick
    ("- [x] Approve\n", "Approved.\n"),                                 # the box taken out, not unticked
    ("- [x] Approve\n", "- [x] Approve\n- [ ] Approve\n"),              # a box added beside it
    ("- [x] Approve\n- [ ] Done\n", "- [ ] Done\n"),                    # and another word's box stays
    ("```\n- [x] Approve\n```\n", "```\n- [ ] Approve\n```\n"),         # in a fence: no box
    ("- [x] Approve the plan\n", "- [ ] Approve the plan\n"),           # no action's word alone
])
def test_a_write_that_unticks_no_one_off_names_none(old, new):
    assert the_list.unticks_one_off(f"# A sheaf\n\n{old}", f"# A sheaf\n\n{new}") is None
