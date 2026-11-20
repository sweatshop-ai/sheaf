"""The list (SPEC 9.10): a member's rectoversos that wait on someone and the ones in progress, per
`<client>/<project>`, at `/<root>` of the root `[list]` names. Status and owner come from the record (an
issues repo and its GitHub Project), the rest from each rectoverso's front matter. Through the handler in proxy
mode, with three hand-made rectoversos, a documentation rectoverso and a fake GitHub that answers GraphQL from the
issues a test gives it."""
import contextlib
import json
import os
import pwd
import re
import subprocess
import threading
import time
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from bs4 import BeautifulSoup
from helpers import FRONT, Front, call, hub_rows, page_meta

from sheafmd import comments as rdc
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import place, proxy, the_list
from sheafmd.hub.state import Tokens
from sheafmd.hub.visibility import front_matter
from sheafmd.source import md_hash

NELL = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"       # the front's ids of two members
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
def rectoversos(tmp_path):
    root = tmp_path / "list"
    for rel, text in SHEAVES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    (root / "projects.toml").write_text(
        '[projects."globex/black-friday"]\nmembers = ["nell"]\nstatus = "live"\n\n'
        '[projects."initech/website"]\nmembers = ["nell", "dora"]\nstatus = "live"\n', encoding="utf-8")
    return root


@pytest.fixture
def box(hub, browser, rectoversos, github, tmp_path):
    """The hub in proxy mode with the rectoversos as Nell's and Dora's root, and its `[list]` on that root,
    the fake GitHub and a token file; polled once."""
    token = tmp_path / "installation-token"
    token.write_text(TOKEN + "\n", encoding="utf-8")
    hub.clock = lambda: NOW
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                             "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "members": {NELL: {"name": "Nell", "short": "nell", "github": "nell-l",
                                                   "roots": [str(rectoversos)]},
                                         DORA: {"name": "Dora", "short": "dora", "github": "dora-k",
                                                "roots": [str(rectoversos)]}}}, "the test")
    hub.the_list = the_list.TheList(hub, the_list.parse({
        "root": str(rectoversos), "repo": "acme/record", "project": 1,
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


def test_my_projects_reads_projects_toml_as_it_is_now_not_as_the_last_poll_read_it(box, rectoversos):
    """My projects judges by the file the hub grants by (8.12, #53): a member just added to a project has its rows
    there at their next request, as All of the team has, and one just taken off has them no more."""
    toml = rectoversos / "projects.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('members = ["nell"]', 'members = ["nell", "dora"]'),
                    encoding="utf-8")
    assert "globex/black-friday" in read(box.get("/list", member=DORA))["Waiting on you 2"]
    toml.write_text(toml.read_text(encoding="utf-8").replace('members = ["nell", "dora"]', 'members = ["dora"]', 1),
                    encoding="utf-8")
    assert "globex/black-friday" not in read(box.get("/list", member=NELL))["Waiting on you 1"]


def test_all_of_the_team_leaves_out_a_sheaf_with_a_private_source_for_all_but_its_owner(box, rectoversos):
    joey = rectoversos / "globex/black-friday/2026-10-28-reply-to-joey.md"
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


def test_my_projects_reads_the_members_of_projects_toml_without_case(box, rectoversos):
    (rectoversos / "projects.toml").write_text(
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


def test_a_sheaf_added_since_joins_the_list_only_at_a_poll_that_reads_the_record(box, rectoversos, github, tmp_path):
    before = read(box.get("/list", member=NELL))
    # A new rectoverso whose issue the last poll read: the record it would be listed by is not read this poll.
    (rectoversos / "initech/website/2026-10-29-new.md").write_text(
        "---\nissue: acme/record#7\n---\n# A new one\n\n- [ ] Done\n", encoding="utf-8")
    (tmp_path / "installation-token").write_text("", encoding="utf-8")
    box.hub.the_list.poll()
    assert "holds no token" in hub_rows("list-poll-failed")[-1]["error"]
    assert read(box.get("/list", member=NELL)) == before
    (tmp_path / "installation-token").write_text(TOKEN + "\n", encoding="utf-8")
    box.hub.the_list.poll()
    assert "A new one" in json.dumps(read(box.get("/list", member=NELL)))


def test_a_poll_that_cannot_read_the_record_still_places_its_sheaves_on_the_last_records_read(box, rectoversos, tmp_path):
    """A failed read keeps the list as it was, but a rectoverso made owner-only since goes to its owner's private folder, the
    owner judged on the records the last good poll read (#45, agreed with #43's placement): here #5's assignee, Nell."""
    joey = rectoversos / JOEY[5:]
    (tmp_path / "installation-token").write_text("", encoding="utf-8")
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    assert "holds no token" in hub_rows("list-poll-failed")[-1]["error"]
    assert (rectoversos / "globex/black-friday/private/nell/2026-10-28-reply-to-joey.md").exists() and not joey.exists()


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
        proxy_folder, rectoversos, github, tmp_path):
    from test_proxy_start import HOST, ask, run_hub, stop, wait_up
    token = tmp_path / "installation-token"
    token.write_text(TOKEN + "\n", encoding="utf-8")
    sock = f"{proxy_folder}/hub.sock"
    configure_list(sock, rectoversos, f'root = "{rectoversos}"\nrepo = "acme/record"\nproject = 1\n'
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


def test_every_action_of_a_row_is_a_button_one_off_but_share_which_is_a_toggle(box, rectoversos):
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Approve\n", "- [ ] Approve\n- [x] Read the brief\n- [ ] Done\n- [ ] Share\n"), encoding="utf-8")
    box.hub.the_list.poll()
    res = box.get("/list", member=NELL)
    assert [(b.action, b.word, b.kind) for b in buttons(res) if b.doc == JOEY] == [
        ("0", "Approve", "one-off"), ("1", "Done", "one-off"), ("2", "Share", "toggle")]
    share = BeautifulSoup(res.text, "html.parser").select_one(f'button[data-doc="{JOEY}"][data-word="Share"]')
    assert share["aria-pressed"] == "false"


def test_the_row_keeps_its_share_button_for_a_box_that_says_shared_with_the_team(box, rectoversos):
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Approve\n", "- [ ] Approve\n- [ ] Shared with the team\n"), encoding="utf-8")
    box.hub.the_list.poll()
    res = box.get("/list", member=NELL)
    assert [(b.action, b.word, b.kind) for b in buttons(res) if b.doc == JOEY] == [
        ("0", "Approve", "one-off"), ("1", "Share", "toggle")]
    share = BeautifulSoup(res.text, "html.parser").select_one(f'button[data-doc="{JOEY}"][data-word="Share"]')
    assert share["aria-pressed"] == "false"


def test_the_rows_second_button_ticks_the_second_action_and_no_other(box, rectoversos):
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [ ] Approve\n- [ ] Done\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    before = path.read_text(encoding="utf-8")
    r = box.post("/_/tick", row_press(box.get("/list", member=NELL), JOEY, "Done"), member=NELL)
    assert r.status == 200, r.text
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Done", "- [x] Done")


def test_a_tick_leaves_a_line_in_the_write_log(box, rectoversos, github):
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
    assert r.status == 200, r.text
    line = box.hub.writes.last(JOEY)
    assert (line.via, line.place, line.writer) == ("tick", "page", "Nell")


def test_a_tick_on_the_row_is_answered_in_the_sheaf_and_the_row_leaves_waiting_on_you(box, rectoversos, github):
    before = (rectoversos / JOEY[5:]).read_text(encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
    assert r.status == 200, r.text
    assert (rectoversos / JOEY[5:]).read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")
    page = read(box.get("/list", member=NELL))
    assert list(page["Waiting on you 1"]) == ["initech/website"]
    box.hub.the_list.poll()                     # the record has not moved yet: still not waiting on anyone
    assert "Waiting on you 1" in read(box.get("/list", member=NELL))
    github.issues[5].update(status="In progress at TT", updated=ago(60))   # the record routine moved it
    box.hub.the_list.poll()
    page = read(box.get("/list", member=NELL))
    assert page["In progress 2"]["globex/black-friday"] == [("Reply to Joey about column L Approve ✓ James", "mail · you · #5 · 1 min")]


def test_a_tick_of_an_action_the_sheaf_no_longer_holds_is_refused_and_writes_nothing(box, rectoversos):
    before = (rectoversos / JOEY[5:]).read_text(encoding="utf-8")
    for body in ({"doc": JOEY, "action": 0, "word": "Done"}, {"doc": JOEY, "action": 1, "word": "Approve"}):
        r = box.post("/_/tick", now(box, body), member=NELL)
        assert r.status == 409, r.text
        assert "reload the list" in r.json()["error"]
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL).status == 200
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL).status == 409
    assert (rectoversos / JOEY[5:]).read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


def now(box, body):
    """`body` with the hash of its rectoverso's text as it is now: the tick of a list read just now. The file is the one
    that holds the rectoverso's name, wherever it is placed (9.11)."""
    top = box.hub.the_list.root().path
    rel = place.file_rel(box.hub, box.hub.the_list.root(), body["doc"].split("/", 1)[1])
    return {**body, "hash": md_hash((top / rel).read_text(encoding="utf-8"))}


def row_press(res, doc, word=None):
    """The tick the row of `doc` would post on a press of its button for `word` (its first button without one):
    the button's doc, action, word and hash, and `release` for a pressed toggle (#110)."""
    found = BeautifulSoup(res.text, "html.parser").select(f'button.list-act[data-doc="{doc}"]')
    b = next(b for b in found if (word is None or b["data-word"] == word) and b.has_attr("data-action"))
    press = {"doc": b["data-doc"], "action": int(b["data-action"]), "word": b["data-word"], "hash": b["data-hash"]}
    return {**press, "release": True} if b.has_attr("data-release") else press


def test_a_tick_from_a_stale_row_does_not_tick_the_next_action_with_the_same_word(box, rectoversos):
    tick = row_press(box.get("/list", member=NELL), JOEY)
    joey = rectoversos / JOEY[5:]
    # Since the list was read, the first Approve was ticked in the page and a second one added below it.
    joey.write_text(joey.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [x] Approve\n- [ ] Approve\n"),
                    encoding="utf-8")
    before = joey.read_text(encoding="utf-8")
    r = box.post("/_/tick", tick, member=NELL)
    assert r.status == 409, r.text
    assert "reload the list" in r.json()["error"]
    assert joey.read_text(encoding="utf-8") == before


def test_the_rows_tick_of_a_sheaf_the_poll_placed_in_a_private_folder_lands_in_that_file(box, rectoversos):
    """Opus gate on #45, P3: the row's hash is of the text the poll read, wherever the file sits (9.11)."""
    joey = rectoversos / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    home = rectoversos / "globex/black-friday/private/nell/2026-10-28-reply-to-joey.md"
    assert home.exists() and not joey.exists()
    before = home.read_text(encoding="utf-8")
    r = box.post("/_/tick", row_press(box.get("/list", member=NELL), JOEY), member=NELL)
    assert r.status == 200, r.text
    assert home.read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


def test_a_tick_ticks_the_action_the_row_showed_though_the_hubs_copy_of_a_page_no_tab_holds_is_older(box, rectoversos):
    """Opus gate on #45, P1: a rectoverso opened once and closed keeps its entry, which the watcher no longer refreshes. A
    question written above its Approve since is the row's action 0: the tick lands there, not on the old Approve."""
    joey = rectoversos / JOEY[5:]
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


def test_a_tick_after_a_write_the_hubs_stat_check_cannot_see_still_lands(box, rectoversos):
    """Opus delta check on #45, P3: a write of the same size in the same clock tick leaves (mtime, size) as it was, so
    catch_up keeps the old copy; the tick reads the file once more rather than refusing every retry."""
    joey = rectoversos / JOEY[5:]
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


def test_the_tick_inside_a_list_of_other_boxes_flips_that_one_line(box, rectoversos):
    path = rectoversos / "initech/website/2026-10-27-ga4-property.md"
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


def test_a_tick_beside_a_comment_in_the_same_list_keeps_the_comment(box, rectoversos):
    from helpers import thread
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Approve\n", f"- [x] Read the thread{thread('c1', 'Dora')}\n- [ ] Approve\n"), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL).status == 200
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


def test_an_action_above_a_rule_after_the_front_matter_is_still_read():
    s = the_list.read_rectoverso("a/b/c.md", SHEAVES["globex/black-friday/2026-10-28-reply-to-joey.md"] + "\n---\n\nMore.\n")
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
def test_a_line_separator_markdown_does_not_break_on_leaves_the_tick_on_its_own_box(box, rectoversos, sep):
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Approve\n", f"Two lines{sep}in one paragraph.\n\n- [ ] Approve\n- [ ] Done\n"), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL).status == 200
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Approve", "- [x] Approve")


def test_a_list_root_inside_a_git_work_tree_is_refused_at_each_poll_and_lists_nothing(box, rectoversos, tmp_path):
    import shutil
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    shutil.copytree(rectoversos, repo / "list")
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
    s = the_list.read_rectoverso("a/b/c.md", f"# A rectoverso\n\n{fence}\n- [ ] Done\n")
    assert [(w, short) for w, short, _, _ in s.actions] == [("Done", "")]


@pytest.mark.parametrize("inner", ["  ```\n  - [ ] Approve\n  ```\n", "  <!--\n  - [ ] Approve\n  -->\n",
                                   "\n      - [ ] Approve\n"])
def test_an_action_inside_code_in_a_list_item_is_no_action_and_the_real_one_ticks(inner):
    text = f"# T\n\n- item\n{inner}- [ ] Done\n"
    s = the_list.read_rectoverso("a.md", text)
    assert [w for w, *_ in s.actions] == ["Done"]
    edit = the_list.tick_edit(text, 0, "Done")
    assert edit is not None and "checked" in edit["html"]


def test_an_action_inside_an_html_comment_is_no_action():
    s = the_list.read_rectoverso("a/b/c.md", "# A rectoverso\n\n<!--\n- [ ] Approve\n-->\n\n- [ ] Done\n")
    assert [(w, line) for w, _, line, _ in s.actions] == [("Done", 6)]


def test_an_indented_code_line_holding_a_fence_opens_no_fence():
    s = the_list.read_rectoverso("a/b/c.md", "# A rectoverso\n\n    ```\n\n- [ ] Approve\n")
    assert [(w, line) for w, _, line, _ in s.actions] == [("Approve", 4)]


def test_a_box_the_render_draws_past_the_blocks_marks_cannot_be_ticked():
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import ticked_html
    block = split_md_blocks('- [ ] Approve <input type="checkbox">\n')[0]
    assert ticked_html(block, 1) is None        # the raw box in the line: no mark of the source is it


def test_a_sheaf_of_a_root_nested_in_the_list_root_is_on_no_list(box, rectoversos):
    import subprocess
    nested = rectoversos / "acme" / "site"
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
        assert the_list.read_rectoverso("a/b/c.md", text).issue is None


def test_a_sheaf_whose_front_matter_closes_only_on_another_line_break_leaves_the_rest_of_the_list(box, rectoversos):
    text = "---\nissue: acme/record#7\nk: v\u2028---\n# Odd\n- [ ] Approve\n"
    (rectoversos / "initech/website/2026-10-28-odd.md").write_text(text, encoding="utf-8")
    box.hub.the_list.poll()
    page = read(box.get("/list", member=NELL))
    assert "Waiting on you 2" in page and "Odd" not in json.dumps(page)
    path = rectoversos / "initech/website/2026-10-28-odd.md"
    before = path.read_text(encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": "list/initech/website/2026-10-28-odd.md", "action": 0, "word": "Approve"}),
                 member=NELL)
    assert r.status in (200, 409), r.text       # no rectoverso, still a document: its one box, or nothing
    assert path.read_text(encoding="utf-8") in (before, before.replace("- [ ] Approve", "- [x] Approve"))


def test_all_of_the_team_leaves_out_a_sheaf_closed_since_the_last_poll(box, rectoversos):
    joey = rectoversos / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    assert all("globex/black-friday" not in groups for groups in read(box.get("/list?show=all", member=DORA)).values())


JOEY_NAME = "globex/black-friday/2026-10-28-reply-to-joey.md"
JOEY_HOME = "globex/black-friday/private/nell/2026-10-28-reply-to-joey.md"


def closed_joey(rectoversos, sources="sources: [library:4711]\n"):
    """Joey's sheaf made its owner's alone (`sources` in the place of `visibility: project`), its file at its home
    (9.11): the private folder of its issue's assignee, Nell, where the poll would move it. Its address stays
    `JOEY_NAME`."""
    joey = rectoversos / "globex/black-friday/2026-10-28-reply-to-joey.md"
    home = rectoversos / JOEY_HOME
    home.parent.mkdir(parents=True)
    home.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", sources), encoding="utf-8")
    joey.unlink()
    return home


def test_a_link_at_a_sheafs_path_is_no_document_even_to_the_owner_of_the_sheaf_it_names(box, rectoversos):
    """A link holds no name (9.11): a second name of one file would be a second name lock over its one file lock.
    The rectoverso is its owner's by its own name; the link answers as a document that does not exist, to everyone."""
    joey = closed_joey(rectoversos, "sources: [library:4711]\nowner: dora\n")
    (rectoversos / "globex/black-friday/joey.md").symlink_to(f"private/nell/{joey.name}")
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    assert box.get(f"/{root}/{JOEY_NAME}", member=DORA).status == 404
    assert box.get(f"/{root}/{JOEY_NAME}", member=NELL).status == 200
    assert box.get(f"/{root}/globex/black-friday/joey.md", member=DORA).status == 404
    assert box.get(f"/{root}/globex/black-friday/joey.md", member=NELL).status == 404


def test_a_link_the_poll_does_not_read_is_no_document_even_to_the_owner_of_the_sheaf_it_names(box, rectoversos):
    """No address of the list's root reaches a file through a link, at any depth (9.11, Opus round 8)."""
    joey = closed_joey(rectoversos, "sources: [library:4711]\nowner: dora\n")
    (rectoversos / ".kept").mkdir()
    (rectoversos / ".kept/joey.md").symlink_to(joey)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    assert box.get(f"/{root}/.kept/joey.md", member=DORA).status == 404
    assert box.get(f"/{root}/.kept/joey.md", member=NELL).status == 404


@pytest.mark.parametrize("issue", ["issue:\n", "issue: acme/record#7\n"], ids=["removed", "changed"])
def test_a_sheaf_whose_issue_changed_since_the_poll_is_not_its_old_assignees(box, rectoversos, issue):
    joey = closed_joey(rectoversos)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    address = f"/{root}/{JOEY_NAME}"
    assert box.get(address, member=NELL).status == 200          # the assignee of #5 owns it
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", issue + "owner: dora\n"),
                    encoding="utf-8")
    assert box.get(address, member=NELL).status == 404          # before the next poll
    assert box.get(address, member=DORA).status == 200


@pytest.mark.parametrize("issue", ["issue:\n", "issue: acme/record#7\n"], ids=["removed", "changed"])
def test_a_tick_after_the_issue_changed_does_not_give_the_old_assignees_back(box, rectoversos, issue):
    joey = closed_joey(rectoversos)
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
def test_a_tick_after_the_issue_changed_takes_the_row_off_the_list_until_the_next_poll(box, rectoversos, github, issue):
    github.issues[5].update(status="In progress at TT")         # drawn, not left out as answered
    box.hub.the_list.poll()
    joey = rectoversos / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", issue), encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
    assert r.status == 200, r.text
    for m in (NELL, DORA):
        assert "Reply to Joey about column L Approve ✓ James" not in titles(read(box.get("/list?show=all", member=m)))
    box.hub.the_list.poll()
    listed = "Reply to Joey about column L Approve ✓ James" in titles(read(box.get("/list?show=all", member=DORA)))
    assert listed == (issue != "issue:\n")                      # back under #7; with no issue, on no list (9.10)


def test_an_issue_without_assignees_has_the_owner_its_sheaf_names(box, rectoversos, github):
    github.issues[6]["assignees"] = []
    prep = rectoversos / "initech/website/2026-10-26-prep-thursday.md"
    prep.write_text(prep.read_text(encoding="utf-8").replace("kind: prep\n", "kind: prep\nowner: nell\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    assert read(box.get("/list?show=mine", member=NELL))["In progress 1"] == {
        "initech/website": [("Prep for the call of Thursday James", "prep · you · #6 · 40 min")]}
    assert read(box.get("/list", member=DORA))["In progress 1"] == {
        "initech/website": [("Prep for the call of Thursday James", "prep · @nell · #6 · 40 min")]}


def test_the_lists_owner_is_the_one_the_file_names_now_not_at_the_poll(box, rectoversos, github):
    github.issues[6]["assignees"] = []
    prep = rectoversos / "initech/website/2026-10-26-prep-thursday.md"
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


def test_an_owner_only_sheaf_deleted_after_a_poll_is_told_to_its_assignee_alone(box, rectoversos, monkeypatch):
    from sheafmd.hub.index import SWEEP_SECONDS
    joey = closed_joey(rectoversos, "sources: [library:4711]\nowner: dora\n")
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
    box.hub.the_list.poll()                             # the poll sees no rectoverso there before the sweep does
    now[0] += SWEEP_SECONDS
    box.hub.tick()
    doc = f"{box.hub.roots.lookup(rectoversos / 'projects.toml').name}/{JOEY_NAME}"
    assert [d["doc"] for name, d in nell.drain() if name == "status"] == [doc]
    assert [d for name, d in dora.drain() if name == "status"] == []


def test_an_issue_written_in_another_case_is_still_the_issue_the_list_polled(box, rectoversos):
    joey = closed_joey(rectoversos, "sources: [library:4711]\nowner: dora\n")
    box.hub.the_list.poll()
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5", "issue: Acme/Record#5"),
                    encoding="utf-8")
    root = box.hub.roots.lookup(joey).name
    address = f"/{root}/{JOEY_NAME}"
    assert box.get(address, member=NELL).status == 200
    assert box.get(address, member=DORA).status == 404


def bind_tokens(box, rectoversos):
    """Nell's and Dora's door tokens, `nell-door` and `dora-door`, bound to them (9.11), both members of both
    projects (8.12): what these tests judge is a rectoverso's own visibility, not the grant."""
    text = (rectoversos / "projects.toml").read_text(encoding="utf-8")
    (rectoversos / "projects.toml").write_text(text.replace('members = ["nell"]', 'members = ["nell", "dora"]'),
                                           encoding="utf-8")
    box.hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                                 "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                                 "members": {NELL: {"name": "Nell", "short": "nell", "github": "nell-l",
                                                    "roots": [str(rectoversos)], "tokens": ["nell-door"]},
                                             DORA: {"name": "Dora", "short": "dora", "github": "dora-k",
                                                    "roots": [str(rectoversos)], "tokens": ["dora-door"]}}}, "the test")
    return {name: Tokens().add(name, write=True) for name in ("nell-door", "dora-door")}


def hidden_joey(rectoversos):
    """Joey's sheaf, its owner's alone and with no `owner`: its issue's assignee, Nell, owns it."""
    return closed_joey(rectoversos)


def test_a_door_update_of_a_sheaf_its_assignee_alone_owns_keeps_it_theirs_once_the_issue_is_not_polled(
        box, browser, rectoversos, github):
    """#33: the record names the owner only while the list polls the issue; the `owner` the write gives
    it is the one after."""
    tokens = bind_tokens(box, rectoversos)
    joey = hidden_joey(rectoversos)
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
        box, browser, rectoversos, issue):
    """#34: until the next poll the list still has the deleted sheaf's row; neither the create's answer nor
    a read after it tells which issue that rectoverso named."""
    tokens = bind_tokens(box, rectoversos)
    joey = hidden_joey(rectoversos)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    doc = f"{root}/globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.unlink()
    text = f"---\nissue: {issue}\nsources: [library:1]\n---\n# A guess\n"
    is_error, got = call(browser, "create", token=tokens["dora-door"], doc=doc, text=text)
    assert not is_error, got
    assert got["doc"] == doc                                    # its name; its file is in Dora's folder (9.11)
    dora = rectoversos / f"globex/black-friday/private/dora/{joey.name}"
    assert front_matter(dora.read_text(encoding="utf-8"))["owner"] == "dora"
    is_error, got = call(browser, "read", token=tokens["dora-door"], doc=doc)
    assert not is_error, got


@pytest.mark.parametrize("issue", ["acme/record#5", "acme/record#7"], ids=["its-issue", "another"])
def test_an_unbound_create_where_a_hidden_sheaf_was_deleted_is_refused_whatever_issue_it_names(
        box, browser, rectoversos, issue):
    """#34: a token bound to nobody gives no owner, so the stale row of the deleted sheaf is no owner either."""
    joey = hidden_joey(rectoversos)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    joey.unlink()
    is_error, got = call(browser, "create", token=Tokens().add("mistral", write=True),
                         doc=f"{root}/globex/black-friday/2026-10-28-reply-to-joey.md",
                         text=f"---\nissue: {issue}\nsources: [library:1]\n---\n# A guess\n")
    assert is_error and "no member as its owner" in got, got
    assert not joey.exists()


def test_a_poll_that_read_a_hidden_sheaf_before_it_went_does_not_bring_its_row_back(
        box, browser, rectoversos, monkeypatch):
    """#34, Codex: the rectoverso goes and a door create takes its address while a poll that read it asks GitHub;
    the snapshot that poll publishes judges the new rectoverso without the row."""
    tokens = bind_tokens(box, rectoversos)
    joey = hidden_joey(rectoversos)
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
    box.hub.the_list.poll()                             # a poll that read the new rectoverso: its issue's assignee owns it
    is_error, got = call(browser, "read", token=tokens["dora-door"], doc=doc)
    assert is_error, got


@pytest.mark.parametrize("through", ["its-address", "a-link"])
def test_a_sheaf_made_where_a_hidden_one_went_is_listed_by_what_it_says_not_what_that_one_said(
        box, browser, rectoversos, through):
    """Codex, Opus: a row the poll read from a hidden sheaf goes with its file, a link's row to it too; the
    sheaf made at its address, open to the project, is listed by its own text from the next poll."""
    tokens = bind_tokens(box, rectoversos)
    joey = hidden_joey(rectoversos)
    joey.write_text(joey.read_text(encoding="utf-8").replace("# Reply to Joey about column L", "# Secret title"),
                    encoding="utf-8")
    if through == "a-link":
        (rectoversos / "globex/black-friday/joey.md").symlink_to(f"private/nell/{joey.name}")
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
        box, browser, rectoversos, issue):
    """Opus: a create open to the project drops the row of the rectoverso that went too, so an update that closes it
    is owned by the token's member, whatever issue it names, and the list shows it to nobody before a poll."""
    tokens = bind_tokens(box, rectoversos)
    joey = hidden_joey(rectoversos)
    box.hub.the_list.poll()
    root = box.hub.roots.lookup(joey).name
    doc = f"{root}/globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.unlink()
    is_error, got = call(browser, "create", token=tokens["dora-door"], doc=doc,
                         text=f"---\nissue: {issue}\nvisibility: project\n---\n# A guess\n\n- [ ] Approve\n")
    assert not is_error, got
    assert "A guess" not in str(read(box.get("/list?show=all", member=DORA)))
    now = (rectoversos / "globex/black-friday" / joey.name).read_text(encoding="utf-8")
    is_error, got = call(browser, "update", token=tokens["dora-door"], doc=doc, expected_hash=md_hash(now),
                         text=now.replace("visibility: project\n", "sources: [library:1]\n"))
    assert not is_error, got
    assert got["doc"] == doc                                    # its name; its file moved to Dora's folder (9.11)
    dora = rectoversos / f"globex/black-friday/private/dora/{joey.name}"
    assert front_matter(dora.read_text(encoding="utf-8"))["owner"] == "dora"


def joey_with_a_figure(rectoversos):
    """Joey's sheaf, which names an image of its project, `globex/black-friday/fig.png`."""
    from PIL import Image
    Image.new("RGB", (4, 4), (200, 30, 30)).save(rectoversos / "globex/black-friday/fig.png")
    joey = rectoversos / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace("The draft.", "The draft. ![the figure](fig.png)"),
                    encoding="utf-8")
    return joey


def test_a_sheaf_whose_issue_is_assigned_outside_its_project_embeds_none_of_its_images(box, rectoversos, github):
    """On the list's root a rectoverso's owner is its issue's assignee (9.11), and an owner the project's `members` do
    not hold leaves out the project's images (#81, #91): the record moves them, the file does not."""
    joey = joey_with_a_figure(rectoversos)
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


def test_renders_that_ask_the_list_for_owners_and_a_poll_that_drops_a_row_all_finish(box, rectoversos, github):
    """`_build` judges the images by the owners, so a render asks `the_list.assignees` under the document's lock,
    which takes the name's lock and `_off_lock` (#81, #91). Renders of a list sheaf beside a poll and asks that
    drop the row of a file gone since all finish, with no deadlock and no exception."""
    joey_with_a_figure(rectoversos)
    assert box.get(f"/{JOEY}", member=NELL).status == 200
    e = box.hub.entries[JOEY]
    gone_rel = "initech/website/2026-10-27-ga4-property.md"
    gone = rectoversos / gone_rel
    kept = gone.read_text(encoding="utf-8")
    errors, stop, steps = [], threading.Event(), [0]

    def rows():
        return {r.rectoverso.rel for r in box.hub.the_list._snap.rows}

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
        box, rectoversos, github, monkeypatch, issue):
    """#27 (2): the file loses its issue and a member ticks while a poll that read it asks GitHub; the snapshot
    that poll publishes holds no row of the issue the rectoverso no longer names, until the next poll."""
    github.issues[5].update(status="In progress at TT")         # drawn, not left out as answered
    box.hub.the_list.poll()
    joey = rectoversos / JOEY[5:]
    fetch = the_list.fetch

    def meanwhile(cfg, wanted):
        joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", issue), encoding="utf-8")
        r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
        assert r.status == 200, r.text
        assert JOEY[5:] not in {r.rectoverso.rel for r in box.hub.the_list._snap.rows}    # the tick took it off
        return fetch(cfg, wanted)
    monkeypatch.setattr(the_list, "fetch", meanwhile)
    box.hub.the_list.poll()
    monkeypatch.setattr(the_list, "fetch", fetch)
    for m in (NELL, DORA):
        assert "Reply to Joey about column L Approve ✓ James" not in titles(read(box.get("/list?show=all", member=m)))
    assert JOEY[5:] not in {r.rectoverso.rel for r in box.hub.the_list._snap.rows}
    box.hub.the_list.poll()
    listed = "Reply to Joey about column L Approve ✓ James" in titles(read(box.get("/list?show=all", member=DORA)))
    assert listed == (issue != "issue:\n")                      # back under #7; with no issue, on no list (9.10)


def _move_twice_during_a_poll(box, rectoversos, github, monkeypatch, issue):
    """#102: the last poll read JOEY at its project path (P1); a 9.11 move takes it to its owner's folder (P2) and the
    poll that is in flight reads it there; during that poll's fetch a second move takes it back (P3) and a member ticks
    after the file's issue changed to `issue`."""
    github.issues[5].update(status="In progress at TT")         # drawn, not left out as answered
    joey = rectoversos / JOEY[5:]
    the_list_ = box.hub.the_list
    old_row = next(r for r in the_list_._snap.rows if r.rectoverso.rel == JOEY[5:])
    assert old_row.file == os.path.realpath(rectoversos / JOEY[5:])                # P1
    joey.write_text(joey.read_text(encoding="utf-8").replace("visibility: project\n", "sources: [library:4711]\n"),
                    encoding="utf-8")
    place.place(box.hub, JOEY)                                  # P2: private/nell/
    p2 = rectoversos / "globex/black-friday/private/nell/2026-10-28-reply-to-joey.md"
    assert p2.exists() and not joey.exists()
    fetch = the_list.fetch
    seen = {}

    def meanwhile(cfg, wanted):
        text = p2.read_text(encoding="utf-8").replace("sources: [library:4711]\n", "visibility: project\n")
        p2.write_text(text.replace("issue: acme/record#5\n", issue), encoding="utf-8")
        place.place(box.hub, JOEY)                              # P3: back at the project path
        assert joey.exists() and not p2.exists()
        r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
        assert r.status == 200, r.text
        seen["rows"] = {r.rectoverso.rel for r in the_list_._snap.rows}
        return fetch(cfg, wanted)
    monkeypatch.setattr(the_list, "fetch", meanwhile)
    the_list_.poll()
    monkeypatch.setattr(the_list, "fetch", fetch)
    assert JOEY[5:] not in seen["rows"]                         # the tick took it off; P1 and P3 are one path, P2 is not it
    return the_list_


@pytest.mark.parametrize("issue", ["issue:\n", "issue: acme/record#7\n"], ids=["removed", "changed"])
def test_a_poll_that_read_a_sheaf_moved_twice_during_its_fetch_does_not_put_its_row_back(
        box, rectoversos, github, monkeypatch, issue):
    """#102 (1): the take-off names the rectoverso by its name too, so the row read at P2, a path neither the last poll
    nor the tick's file now names, stays off until the next poll."""
    the_list_ = _move_twice_during_a_poll(box, rectoversos, github, monkeypatch, issue)
    assert JOEY[5:] not in {r.rectoverso.rel for r in the_list_._snap.rows}
    the_list_.poll()
    listed = JOEY[5:] in {r.rectoverso.rel for r in the_list_._snap.rows}
    assert listed == (issue != "issue:\n")                      # back under #7; with no issue, on no list (9.10)


def test_a_row_the_poll_read_after_the_issue_changed_is_kept_though_the_tick_took_the_old_one_off(
        box, rectoversos, github, monkeypatch):
    """#102 (2): only a row that still names the issue the tick saw replaced is left out; one read under the new issue
    is already right."""
    github.issues[5].update(status="In progress at TT")
    joey = rectoversos / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", "issue: acme/record#7\n"),
                    encoding="utf-8")                           # changed before the in-flight poll reads it
    fetch = the_list.fetch

    def meanwhile(cfg, wanted):
        r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
        assert r.status == 200, r.text
        assert JOEY[5:] not in {r.rectoverso.rel for r in box.hub.the_list._snap.rows}     # the old row went at once
        return fetch(cfg, wanted)
    monkeypatch.setattr(the_list, "fetch", meanwhile)
    box.hub.the_list.poll()
    monkeypatch.setattr(the_list, "fetch", fetch)
    rows = {r.rectoverso.rel: r.rectoverso.issue for r in box.hub.the_list._snap.rows}
    assert rows.get(JOEY[5:]) == ("acme", "record", 7), rows


def test_a_row_that_still_names_the_replaced_issue_stays_off_though_it_was_read_after_the_tick_began(
        box, rectoversos, github, monkeypatch):
    """#102 (2), the other side: the in-flight poll read the file before the issue changed, so it lists #5."""
    github.issues[5].update(status="In progress at TT")
    joey = rectoversos / JOEY[5:]
    fetch = the_list.fetch

    def meanwhile(cfg, wanted):
        joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", "issue: acme/record#7\n"),
                        encoding="utf-8")
        r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
        assert r.status == 200, r.text
        return fetch(cfg, wanted)
    monkeypatch.setattr(the_list, "fetch", meanwhile)
    box.hub.the_list.poll()
    monkeypatch.setattr(the_list, "fetch", fetch)
    assert JOEY[5:] not in {r.rectoverso.rel for r in box.hub.the_list._snap.rows}
    box.hub.the_list.poll()
    assert JOEY[5:] in {r.rectoverso.rel for r in box.hub.the_list._snap.rows}


def test_a_row_naming_a_third_issue_stays_off_when_the_file_changed_again_after_the_poll_read_it(
        box, rectoversos, github, monkeypatch):
    """#102 review: the poll read #6 (5 became 6 before it), then the file became #7 and a tick found 5 against 7:
    the poll's row names neither the old issue nor the one the file names now, so it is stale."""
    github.issues[5].update(status="In progress at TT")
    joey = rectoversos / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#5\n", "issue: acme/record#6\n"),
                    encoding="utf-8")
    fetch = the_list.fetch

    def meanwhile(cfg, wanted):
        joey.write_text(joey.read_text(encoding="utf-8").replace("issue: acme/record#6\n", "issue: acme/record#7\n"),
                        encoding="utf-8")
        r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve"}), member=NELL)
        assert r.status == 200, r.text
        return fetch(cfg, wanted)
    monkeypatch.setattr(the_list, "fetch", meanwhile)
    box.hub.the_list.poll()
    monkeypatch.setattr(the_list, "fetch", fetch)
    assert JOEY[5:] not in {r.rectoverso.rel for r in box.hub.the_list._snap.rows}
    box.hub.the_list.poll()
    assert {r.rectoverso.rel: r.rectoverso.issue for r in box.hub.the_list._snap.rows}[JOEY[5:]] == ("acme", "record", 7)


def test_a_tick_reads_the_file_under_the_names_lock_taken_before_the_lists_own(box, rectoversos, monkeypatch):
    """#102 note: a move may be mid-way when `ticked` reads; the name's lock (9.11) keeps it from resolving a missing
    path, and is taken first, as `assignees` takes it."""
    held = []
    real = place.held

    @contextlib.contextmanager
    def spy(hub, address):
        held.append((address, box.hub.the_list._off_lock.locked()))
        with real(hub, address) as got:
            yield got
    monkeypatch.setattr(place, "held", spy)
    box.hub.the_list.ticked(JOEY)
    assert held == [(JOEY, False)]


def test_a_take_off_of_a_file_that_went_is_not_narrowed_by_a_later_tick_of_the_same_file(box):
    """#102: `_take_off` for a gone file leaves every row of it off; a tick's take-off of the same file, naming the
    issue it saw replaced, does not turn that into a take-off of the rows that name that issue only."""
    the_list_ = box.hub.the_list
    key = ("file", "/x/y.md")
    with the_list_._off_lock:
        the_list_._take_off({"/x/y.md"})
        the_list_._take_off({"/x/y.md"}, {"a/b/c.md"}, ("acme", "record", 5))
        assert the_list_._off[key][1] is None
        assert the_list_._off[("name", "a/b/c.md")][1] == ("acme", "record", 5)


# ── Move to: the eighth word, and the pointer a move leaves (agency-tiroir#211) ──

CLIENT = """
## Client

The sender writes from dexis.be, which Dexis and Klium share. Which client is this thread for?

- [ ] Move to dexis (ref 18f3a9c2)
- [ ] Move to klium (ref 18f3a9c2)
- [ ] Move to acme (ref 18f3a9c2)
"""


def test_a_move_to_box_with_its_slug_and_ref_is_an_action_with_the_word_move_to():
    s = the_list.read_rectoverso("a/b/c.md", "# A rectoverso\n\n- [ ] Move to klium (ref 18f3a9c2)\n")
    assert s.actions == (("Move to", "", 2, "klium"),)


def test_a_client_section_of_three_boxes_gives_three_actions_in_its_order():
    s = the_list.read_rectoverso("a/b/c.md", "# A rectoverso\n" + CLIENT)
    assert [(w, line, arg) for w, _, line, arg in s.actions] == [
        ("Move to", 6, "dexis"), ("Move to", 7, "klium"), ("Move to", 8, "acme")]


def test_a_move_to_the_hub_gave_back_escaped_reads_its_slug_unescaped():
    s = the_list.read_rectoverso("a/b/c.md", "# A rectoverso\n\n- [ ] Move to newtrition\\-coach (ref 18f\\_3a)\n")
    assert [(w, arg) for w, _, _, arg in s.actions] == [("Move to", "newtrition-coach")]


@pytest.mark.parametrize("line", ["- [ ] Move to", "- [ ] Move to klium", "- [ ] Move to (ref 18f3a9c2)",
                                  "- [ ] Move to klium (ref 18f3a9c2) now", "- [ ] Move klium (ref 18f3a9c2)",
                                  "- [ ] Archive", "- [ ] Undo skip (ref 18f3a9c2)", "- [ ] Approve klium"])
def test_a_line_with_an_unknown_word_or_a_move_to_without_its_argument_is_still_no_action(line):
    assert the_list.read_rectoverso("a/b/c.md", f"# A rectoverso\n\n{line}\n").actions == ()


def test_tick_edit_ticks_the_move_to_box_of_its_index():
    from sheafmd.blocks import split_md_blocks
    text = "# A rectoverso\n" + CLIENT
    edit = the_list.tick_edit(text, 1, "Move to")
    block = split_md_blocks(text)[edit["i"]]
    assert block.kind == "list"
    assert edit["html"].count("checked") == 1
    soup = BeautifulSoup(edit["html"], "html.parser")
    ticked = [" ".join(li.get_text(" ").split()) for li in soup.select("li") if li.find("input", checked=True)]
    assert ticked == ["Move to klium (ref 18f3a9c2)"]
    assert the_list.tick_edit(text, 1, "Approve") is None


@pytest.mark.parametrize("quoted", ["tests.yml:100: command -v ssh-keygen",
                                    # pandoc wraps this one between the span's class and its data-emoji
                                    ".github/workflows/tests.yml:100: command -v ssh-keygen"])
def test_tick_edit_ticks_a_box_in_a_list_that_holds_an_emoji_shortcode(quoted):
    # The merge desk quotes workflow lines as `tests.yml:100: ...`: pandoc draws `:100:` as a span the save's
    # sanitizer strips of its data-emoji, and every box of that list was refused (2026-11-19).
    text = f"# Merge desk\n\n- [ ] Deploy a/b#1: one\n  - {quoted}\n- [ ] Merge a/b#2: two\n"
    edit = the_list.tick_edit(text, 1, "Merge")
    assert edit is not None
    soup = BeautifulSoup(edit["html"], "html.parser")
    assert [" ".join(box.find_parent("li").get_text(" ").split())
            for box in soup.find_all("input", checked=True)] == ["Merge a/b#2: two"]


def unsure(rectoversos):
    """Joey's sheaf with the Client section of an unsure thread in place of its Approve."""
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", CLIENT.lstrip("\n")), encoding="utf-8")
    return path


def test_a_tick_of_the_second_move_to_ticks_that_box_and_no_other(box, rectoversos):
    path = unsure(rectoversos)
    box.hub.the_list.poll()
    before = path.read_text(encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 1, "word": "Move to"}), member=NELL)
    assert r.status == 200, r.text
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Move to klium", "- [x] Move to klium")


def test_a_row_of_move_to_boxes_draws_one_one_off_button_per_candidate_named_by_its_slug(box, rectoversos):
    unsure(rectoversos)
    box.hub.the_list.poll()
    res = box.get("/list", member=NELL)
    assert read(res)["Waiting on you 2"]["globex/black-friday"] == [
        ("Reply to Joey about column L Move to dexis Move to klium Move to acme James", "mail · you · #5 · 2 h")]
    href = "/list/globex/black-friday/2026-10-28-reply-to-joey.md"
    assert [b for b in buttons(res) if b.doc == JOEY] == [
        (href, JOEY, str(n), "Move to", "one-off", f"Move to {slug}") for n, slug in enumerate(("dexis", "klium",
                                                                                                 "acme"))]


@pytest.mark.parametrize("mark", ["x", "X"])
def test_once_a_move_to_is_ticked_the_other_candidates_are_no_actions_and_other_words_stay(mark):
    s = the_list.read_rectoverso("a/b/c.md", "# A rectoverso\n" + CLIENT.replace("- [ ] Move to klium", f"- [{mark}] Move to klium")
                            + "\n- [ ] Done\n")
    assert [(w, arg) for w, _, _, arg in s.actions] == [("Done", "")]


def test_a_row_whose_move_to_is_ticked_draws_no_move_to_button_to_press(box, rectoversos):
    path = unsure(rectoversos)
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Move to klium", "- [x] Move to klium"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    soup = BeautifulSoup(box.get("/list?show=all", member=NELL).text, "html.parser")
    # The ticked candidate stays, locked (#110); the others are gone.
    assert [(b.get_text(" ", strip=True), b.has_attr("disabled"))
            for b in soup.select('button.list-act[data-word="Move to"]')] == [("Move to klium ✓", True)]


def test_a_tick_of_another_candidate_once_one_is_ticked_is_refused_and_one_tick_stays(box, rectoversos):
    """Even on the text as it is now: the other candidates are no actions, so no tick can reach them."""
    path = unsure(rectoversos)
    box.hub.the_list.poll()
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 1, "word": "Move to"}), member=NELL).status == 200
    after = path.read_text(encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Move to"}), member=NELL)
    assert r.status == 409, r.text
    assert path.read_text(encoding="utf-8") == after and after.count("- [x] Move to") == 1


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
    assert the_list.ticks_another_move(f"# A rectoverso\n\n{old}", f"# A rectoverso\n\n{new}") == slug


@pytest.mark.parametrize("old, new", [
    ("- [ ] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n",
     "- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n"),                    # the first tick
    ("- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n",
     "- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n\nText.\n"),          # another edit
    ("- [x] Move to klium (ref t1)\n", "- [x] Move to klium (ref t1)\n- [ ] Approve\n"),    # another word added
    ("- [ ] Move to newtrition-coach (ref t1)\n", "- [x] Move to newtrition\\-coach (ref t1)\n"),  # ticked escaped
    ("- [x] Move to newtrition-coach (ref t1)\n", "- [x] Move to newtrition\\-coach (ref t1)\n"),  # escaped back
    ("```\n- [x] Move to klium (ref t1)\n```\n- [ ] Move to acme (ref t1)\n",
     "```\n- [x] Move to klium (ref t1)\n```\n- [x] Move to acme (ref t1)\n"),         # in a fence: no box
])
def test_a_write_that_ticks_no_other_move_to_names_none(old, new):
    assert the_list.ticks_another_move(f"# A rectoverso\n\n{old}", f"# A rectoverso\n\n{new}") is None


def pointer(rectoversos):
    """Joey's sheaf as the pointer a move leaves: its front matter with `moved_to:`, and one line."""
    path = rectoversos / JOEY[5:]
    text = path.read_text(encoding="utf-8")
    head = text[:text.index("---\n", 4)]
    path.write_text(head + "moved_to: klium/inbox/2026-10-28-reply-to-joey.md\n---\n"
                    "Moved to `klium/inbox/2026-10-28-reply-to-joey.md` on 2026-10-30.\n", encoding="utf-8")


def test_a_sheaf_whose_front_matter_has_moved_to_is_not_a_row(box, rectoversos):
    pointer(rectoversos)
    box.hub.the_list.poll()
    page = read(box.get("/list", member=NELL))
    assert "globex/black-friday" not in page["Waiting on you 1"]
    assert JOEY[5:] not in {r.rectoverso.rel for r in box.hub.the_list._snap.rows}


def test_a_sheaf_that_became_a_pointer_since_the_poll_leaves_the_page_at_once(box, rectoversos):
    assert "globex/black-friday" in read(box.get("/list", member=NELL))["Waiting on you 2"]
    pointer(rectoversos)
    page = read(box.get("/list", member=NELL))
    assert not any("joey" in t.lower() for t in titles(page)), page


def test_a_row_whose_move_to_boxes_come_before_another_action_carries_the_button_of_each(box, rectoversos):
    path = unsure(rectoversos)
    path.write_text(path.read_text(encoding="utf-8").replace("The draft.\n", "The draft.\n\n- [ ] Approve\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    assert [(b.action, b.word, b.label) for b in buttons(box.get("/list", member=NELL)) if b.doc == JOEY] == [
        ("0", "Move to", "Move to dexis"), ("1", "Move to", "Move to klium"),
        ("2", "Move to", "Move to acme"), ("3", "Approve", "Approve")]


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
    assert the_list.unticks_one_off(f"# A rectoverso\n\n{old}", f"# A rectoverso\n\n{new}") == word


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
    assert the_list.unticks_one_off(f"# A rectoverso\n\n{old}", f"# A rectoverso\n\n{new}") is None


# ── Merge, Deploy and Install take the rest of the line (action-buttons 04) ──────────────────────────────

MERGE = "- [ ] Merge sweatshop-ai/sheaf#272: Tickets: buttons on their own line\n"


@pytest.mark.parametrize("word", ["Merge", "Deploy", "Install"])
def test_merge_deploy_and_install_are_actions_that_take_the_rest_of_the_line(word):
    sheaf = the_list.read_rectoverso("x.md", f"# A rectoverso\n\n- [ ] {word} a/b#1: text @nell, more\n- [x] {word} a/b#2: done\n")
    assert [(a[0], a[1]) for a in sheaf.actions] == [(word, "")]
    assert [p[0] for p in sheaf.pressed] == [word]


@pytest.mark.parametrize("line", ["- [ ] Merge\n", "- [ ] Deploy   \n", "- [ ] Rebase a/b#1\n", "- [ ] merge a/b#1\n"])
def test_a_bare_or_unlisted_word_is_no_action(line):
    assert the_list.read_rectoverso("x.md", f"# A rectoverso\n\n{line}").actions == ()


def test_a_write_that_unticks_a_pressed_merge_names_its_word():
    old = "# A rectoverso\n\n" + MERGE.replace("[ ]", "[x]") + "- [ ] Merge a/b#9: other\n"
    assert the_list.unticks_one_off(old, old.replace("[x]", "[ ]")) == "Merge"


def test_a_pressed_merge_writes_only_its_tick_and_the_hub_refuses_to_untick_it_but_an_outside_write_is_taken(
        committing, box, rectoversos, github):
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8") + "\n" + MERGE, encoding="utf-8")
    box.hub.the_list.poll()
    before = path.read_text(encoding="utf-8")
    assert row_buttons(box.get("/list", member=NELL), JOEY)[-1][0] == "Merge"
    press = row_press(box.get("/list", member=NELL), JOEY, "Merge")
    r = box.post("/_/tick", press, member=NELL)
    assert r.status == 200, r.text
    assert path.read_text(encoding="utf-8") == before.replace("- [ ] Merge", "- [x] Merge")
    pressed = path.read_text(encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Merge", "release": True}), member=NELL)
    assert r.status == 409 and r.json()["error"] == "Merge is pressed once: its tick cannot be taken back."
    assert path.read_text(encoding="utf-8") == pressed
    path.write_text(pressed.replace("- [x] Merge", "- [ ] Merge"), encoding="utf-8")      # AgentView, not the hub
    in_progress(box, github, 5)
    assert row_buttons(box.get("/list", member=NELL), JOEY)[-1][0] == "Merge"


# ── a pressed one-off shows locked, with who and when (#110) ─────────────────

def git(at, *args):
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def committing(rectoversos, monkeypatch):
    """The rectoversos as a git repo whose root commits (8.11), every rectoverso in its first commit, by "the box"; every
    commit from here on is dated 27 Oct 2025 at noon UTC, the same day in every time zone of the hub. Dora is a member
    of Joey's project too. Asked before `box`, so the hub registers the root as a git work tree."""
    (rectoversos / "projects.toml").write_text(
        '[projects."globex/black-friday"]\nmembers = ["nell", "dora"]\nstatus = "live"\n\n'
        '[projects."initech/website"]\nmembers = ["nell", "dora"]\nstatus = "live"\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(rectoversos)], check=True)
    git(rectoversos, "config", "user.name", "the box")
    git(rectoversos, "config", "user.email", "box@example.com")
    (rectoversos / ".sheaf.toml").write_text("commit = true\n", encoding="utf-8")
    git(rectoversos, "add", "-A")
    git(rectoversos, "commit", "-q", "-m", "first")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2025-10-27T12:00:00Z")
    return rectoversos


def row_buttons(res, doc):
    """The buttons of the row of `doc`, in row order: (label, data-action or None, disabled, aria-pressed or None)."""
    soup = BeautifulSoup(res.text, "html.parser")
    return [(b.get_text(" ", strip=True), b.get("data-action"), b.has_attr("disabled"), b.get("aria-pressed"))
            for b in soup.select(f'button.list-act[data-doc="{doc}"]')]


def in_progress(box, github, number):
    """The record routine moved the issue on: its rectoverso shows again, under In progress."""
    github.issues[number].update(status="In progress at TT", updated=ago(60))
    box.hub.the_list.poll()


def test_a_one_off_pressed_on_the_row_shows_locked_with_who_pressed_it_and_when(committing, box, rectoversos, github):
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [ ] Approve\n- [ ] Done\n"),
                    encoding="utf-8")
    git(rectoversos, "commit", "-q", "-am", "Done too")
    box.hub.the_list.poll()
    r = box.post("/_/tick", row_press(box.get("/list", member=NELL), JOEY, "Approve"), member=NELL)
    assert r.status == 200, r.text
    in_progress(box, github, 5)
    assert row_buttons(box.get("/list", member=NELL), JOEY) == [
        ("Approve ✓ you, 27 Oct", None, True, None), ("Done", "0", False, None)]
    assert row_buttons(box.get("/list", member=DORA), JOEY) == [
        ("Approve ✓ @nell, 27 Oct", None, True, None), ("Done", "0", False, None)]


def page_buttons(res):
    """The buttons at the top of a rectoverso's page (10.11, #111), from its meta block: (label, `by`, n, may, box)."""
    return [(a["label"], a["by"], a["n"], a["may"], a["box"]) for a in page_meta(res.text)["actions"]]


def test_the_page_of_a_sheaf_names_the_rows_buttons_with_who_pressed_a_one_off_and_where_each_box_is(
        committing, box, rectoversos, github):
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [ ] Approve\n- [ ] Done\n- [ ] Share\n"),
                    encoding="utf-8")
    git(rectoversos, "commit", "-q", "-am", "Done and Share too")
    box.hub.the_list.poll()
    r = box.post("/_/tick", row_press(box.get("/list", member=NELL), JOEY, "Approve"), member=NELL)
    assert r.status == 200, r.text
    text = path.read_text(encoding="utf-8")
    i = next(k for k, b in enumerate(split_md_blocks(text)) if "- [x] Approve" in b.content)
    # Nell owns the rectoverso (her issue): she may press its Share; Dora reads it and cannot.
    assert page_buttons(box.get(f"/{JOEY}", member=NELL)) == [
        ("Approve", "you, 27 Oct", None, False, [i, 0]), ("Done", "", 0, True, [i, 1]),
        ("Share", "", 1, True, [i, 2])]
    assert page_buttons(box.get(f"/{JOEY}", member=DORA)) == [
        ("Approve", "@nell, 27 Oct", None, False, [i, 0]), ("Done", "", 0, True, [i, 1]),
        ("Share", "", 1, False, [i, 2])]


def test_a_press_from_the_page_that_went_stale_says_to_reload_the_page(box, rectoversos):
    tick = {**row_press(box.get("/list", member=NELL), JOEY), "where": "page"}
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("The draft.", "The draft, changed."), encoding="utf-8")
    r = box.post("/_/tick", tick, member=NELL)
    assert r.status == 409 and r.json()["error"].endswith("(Approve): reload the page"), r.text
    assert box.post("/_/tick", {**tick, "where": "box"}, member=NELL).status == 400


def test_a_box_no_commit_holds_shows_pressed_without_who_or_when_and_a_ticked_move_to_is_one(box, rectoversos):
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Approve\n", "- [x] Approve\n- [ ] Done\n- [x] Move to klium (ref t1)\n- [ ] Move to acme (ref t1)\n"),
        encoding="utf-8")
    box.hub.the_list.poll()
    assert row_buttons(box.get("/list", member=NELL), JOEY) == [
        ("Approve ✓", None, True, None), ("Done", "0", False, None), ("Move to klium ✓", None, True, None)]


def test_a_box_ticked_by_someone_who_is_no_member_shows_their_name(committing, box, rectoversos):
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [x] Approve @dora\n"),
                    encoding="utf-8")
    git(rectoversos, "-c", "user.name=Ada Byron", "-c", "user.email=ada@example.com", "commit", "-q", "-am", "by hand")
    box.hub.the_list.poll()
    assert row_buttons(box.get("/list", member=NELL), JOEY) == [("Approve @dora ✓ Ada Byron, 27 Oct", None, True, None)]
    # The page reads the file again when it changed since the poll: a tick not committed yet says no one.
    path.write_text(path.read_text(encoding="utf-8") + "\n- [x] Done\n", encoding="utf-8")
    assert row_buttons(box.get("/list", member=NELL), JOEY) == [
        ("Approve @dora ✓ Ada Byron, 27 Oct", None, True, None), ("Done ✓", None, True, None)]


def shared_joey(rectoversos):
    """Joey's sheaf with Approve and a pressed Share, committed."""
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [ ] Approve\n- [x] Share\n"),
                    encoding="utf-8")
    git(rectoversos, "commit", "-q", "-am", "shared")
    return path


def test_a_pressed_share_shows_pressed_and_only_its_owner_may_press_it(committing, box, rectoversos):
    shared_joey(rectoversos)
    box.hub.the_list.poll()
    assert row_buttons(box.get("/list", member=NELL), JOEY) == [("Approve", "0", False, None), ("Share", "0", False, "true")]
    assert row_buttons(box.get("/list", member=DORA), JOEY) == [("Approve", "0", False, None), ("Share", "0", True, "true")]
    path = rectoversos / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [x] Share", "- [ ] Share"), encoding="utf-8")
    assert row_buttons(box.get("/list", member=NELL), JOEY)[1] == ("Share", "1", False, "false")
    assert row_buttons(box.get("/list", member=DORA), JOEY)[1] == ("Share", "1", True, "false")


def test_the_owner_releases_a_pressed_share_from_the_row(committing, box, rectoversos):
    shared_joey(rectoversos)
    box.hub.the_list.poll()
    press = row_press(box.get("/list", member=NELL), JOEY, "Share")
    assert press["release"] is True
    r = box.post("/_/tick", press, member=NELL)
    assert r.status == 200, r.text
    top = box.hub.the_list.root().path
    text = (top / place.file_rel(box.hub, box.hub.the_list.root(), JOEY[5:])).read_text(encoding="utf-8")
    assert "- [ ] Share\n" in text and front_matter(text)["visibility"] == "owner"
    assert git(rectoversos, "log", "-1", "--format=%an|%s").startswith("Nell|")
    assert row_buttons(box.get("/list", member=NELL), JOEY)[1] == ("Share", "1", False, "false")


def test_a_release_by_another_member_or_of_a_one_off_is_refused_and_writes_nothing(committing, box, rectoversos):
    path = shared_joey(rectoversos)
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve", "- [x] Approve"), encoding="utf-8")
    box.hub.the_list.poll()
    before = path.read_text(encoding="utf-8")
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 1, "word": "Share", "release": True}), member=DORA)
    assert r.status == 409, r.text
    assert "Only the owner" in r.json()["error"]
    r = box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Approve", "release": True}), member=NELL)
    assert r.status == 409, r.text
    assert r.json()["error"] == "Approve is pressed once: its tick cannot be taken back."
    assert box.post("/_/tick", now(box, {"doc": JOEY, "action": 0, "word": "Share", "release": "yes"}),
                    member=NELL).status == 400
    assert path.read_text(encoding="utf-8") == before


def test_a_one_off_ticked_in_the_page_shows_who_ticked_it_there_through_a_later_edit_of_another_block(
        committing, box, rectoversos, github):
    path = rectoversos / JOEY[5:]
    text = path.read_text(encoding="utf-8")
    edit = the_list.tick_edit(text, 0, "Approve")
    r = box.post("/_/save", {"doc": JOEY, "hash": md_hash(text), "edits": [edit]}, member=NELL)   # an `edit:` commit
    assert r.status == 200, r.text
    text = path.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("The draft."))
    r = box.post("/_/save", {"doc": JOEY, "hash": md_hash(text), "edits": [{"i": i, "html": "<p>The draft, again.</p>"}]},
                 member=DORA)
    assert r.status == 200, r.text
    assert git(rectoversos, "log", "-2", "--format=%an|%s").splitlines() == [
        f"Dora|edit: {JOEY[5:]}", f"Nell|edit: {JOEY[5:]}"]
    in_progress(box, github, 5)
    assert row_buttons(box.get("/list", member=DORA), JOEY) == [("Approve ✓ @nell, 27 Oct", None, True, None)]


# ── A review comment anchored in the H1 is no part of the row's title ─────────────────────────────────────

def h1_comment(status="open"):
    """A comment anchored in a heading, as `sheaf comment` writes one there: on one line, its lines joined by `<br>`."""
    return f'<!-- sheaf-comment id=c1 by="Ada" at=2026-10-29T15:43 status={status} quote="sheaf"<br>Why this name? -->'


@pytest.mark.parametrize("status", ["open", "resolved"])
def test_a_comment_anchored_in_the_h1_is_left_out_of_the_title(status):
    text = f"---\nissue: o/r#1\n---\n\n# Test sheaf{h1_comment(status)} tail\n\n- [ ] Done\n"
    assert the_list.read_rectoverso("x/y/z.md", text).title == "Test sheaf tail"


def test_a_comment_that_sheaf_comment_anchors_in_the_h1_is_left_out_of_the_title():
    text = "---\nissue: o/r#1\n---\n\n# Test sheaf tail\n\n- [ ] Done\n"
    heading = next(i for i, b in enumerate(split_md_blocks(text)) if b.kind == "heading")
    start = rdc.projection(split_md_blocks(text)[heading].content).text.index("sheaf")    # as the page counts
    text, _ = rdc.add_comment(text, heading, start, start + 5, "sheaf",
                              'Why "this" name?\n\nA <b>second</b> line & -- more', 'A "B"', "2026-10-29T15:43")
    assert "sheaf-comment" in text.split("\n")[4]
    assert the_list.read_rectoverso("x/y/z.md", text).title == "Test sheaf tail"


def test_a_comment_mark_in_a_code_span_of_the_h1_stays_in_the_title():
    text = "# Use `<!--` and `-->` here\n"
    assert the_list.read_rectoverso("x/y/z.md", text).title == "Use `<!--` and `-->` here"


def test_an_h1_that_is_only_a_comment_gives_the_file_name_as_for_none():
    text = f"---\nissue: o/r#1\n---\n\n# {h1_comment()}\n\n- [ ] Done\n"
    assert the_list.read_rectoverso("x/y/2026-10-29-z.md", text).title == "2026-10-29-z"


def test_an_h1_that_is_only_a_comment_gives_the_file_name_not_a_later_h1s_text():
    # As the page's title: the first `# ` heading is the title, and one left empty gives the file name.
    text = f"# {h1_comment()}\n\n# Second\n"
    assert the_list.read_rectoverso("x/y/2026-10-29-z.md", text).title == "2026-10-29-z"


def test_the_rows_title_holds_no_comment_of_the_h1(box, rectoversos):
    joey = rectoversos / "globex/black-friday/2026-10-28-reply-to-joey.md"
    joey.write_text(joey.read_text(encoding="utf-8").replace(
        "# Reply to Joey about column L", f"# Reply to Joey{h1_comment()} about column L"), encoding="utf-8")
    box.hub.the_list.poll()
    soup = BeautifulSoup(box.get("/list", member=NELL).text, "html.parser")
    titles = [a.get_text() for a in soup.select("a.list-title")]
    assert "Reply to Joey about column L" in titles
    assert not any("sheaf-comment" in t for t in titles)


@pytest.mark.parametrize("heading, title", [("x\\<!-- y -->z", "x\\<!-- y -->z"),          # an escaped `<` opens none
                                            ("x\\\\<!-- y -->z", "x\\\\z"),                  # an escaped backslash does
                                            ("a <!--> b --> c", "a b --> c"),               # `<!-->` is a whole comment
                                            ("a <!---> b --> c", "a b --> c"),
                                            ("a <!-- x `y --> b `<!-- z` c", "a b `<!-- z` c")])  # a comment owns its backtick
def test_only_what_commonmark_reads_as_a_comment_leaves_the_title(heading, title):
    assert the_list.read_rectoverso("x/y/z.md", f"# {heading}\n").title == title


# ── the list mounted in the front's document (#116 step 2, slice iv) ──────────────

def mounted(res):
    """The mounted list's data read the way `read` reads the page: each section's heading, then each group's rows."""
    assert res.status == 200, res.text
    got = res.json()
    out = {}
    for section in got["list"]["sections"]:
        groups = {}
        for group in section["groups"]:
            groups[group["name"]] = [
                (" ".join([r["title"]] + [a["label"] for a in r["actions"]] + ([r["assistant"]] if r["assistant"] else [])),
                 r["meta"]) for r in group["rows"]]
        out[f'{section["title"]} {section["count"]}'] = groups
    return out


@pytest.mark.parametrize("show", ["", "mine", "all"])
def test_the_mounted_list_is_the_rows_the_page_shows_as_data(box, show):
    page = box.get("/list" + (f"?show={show}" if show else ""), member=NELL)
    got = box.get("/_/mount?list=list" + (f"&show={show}" if show else ""), member=NELL)
    assert mounted(got) == read(page)
    j = got.json()
    assert j["kind"] == "list" and j["title"] == "Actions" and j["version"] == box.hub.version
    assert j["assets"] == {n: a.tag for n, a in box.hub.assets.items()}      # the names mount.js uses (#179)
    assert j["script"] == box.hub.assets["mount.js"].source                   # the scripts the hub serves (#179)
    assert "html" not in j                       # no markup: the front builds every node from text (layer b)
    assert got.headers["X-Content-Type-Options"] == "nosniff"


def test_the_mounted_lists_buttons_and_links_are_the_pages(box):
    j = box.get("/_/mount?list=list", member=NELL).json()["list"]
    rows = [r for s in j["sections"] for g in s["groups"] for r in g["rows"]]
    assert [r["href"] for r in rows] == ["/list/globex/black-friday/2026-10-28-reply-to-joey.md",
                                         "/list/initech/website/2026-10-27-ga4-property.md",
                                         "/list/initech/website/2026-10-26-prep-thursday.md"]
    page = buttons(box.get("/list", member=NELL))
    data = [(r["href"], a["doc"], str(a["n"]), a["word"], "toggle" if a["toggle"] else "one-off", a["label"])
            for r in rows for a in r["actions"]]
    assert data == [tuple(b) for b in page]
    assert all(a["hash"] for r in rows for a in r["actions"])
    assert [(f["label"], f["href"], f["on"]) for f in j["filters"]] == [
        ("My projects", "/list", True), ("Only mine", "/list?show=mine", False), ("All of the team", "/list?show=all", False)]


def test_the_mounted_list_is_a_members_alone_and_only_of_the_lists_root(box, browser, tmp_path):
    assert box.get("/_/mount?list=nolist", member=NELL).status == 404
    assert browser.get("/_/mount?list=list", cookie=False, key=True).status == 404      # the hub's key is no member
    other = tmp_path / "other"
    other.mkdir()
    cfg = box.hub.proxy
    box.hub.proxy = proxy.parse({"origin": FRONT, "socket": str(cfg.socket), "proxy_user": cfg.proxy_user,
                                 "members": {DORA: {"name": "Dora", "short": "dora", "roots": [str(other)]}}},
                                "the test")
    assert box.get("/_/mount?list=list", member=DORA).status == 404


def test_a_title_with_markup_reaches_the_mount_as_its_text(box, rectoversos):
    joey = rectoversos / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace(
        "# Reply to Joey about column L", "# Reply <img src=/x onerror=alert(1)> & co"), encoding="utf-8")
    box.hub.the_list.poll()
    j = box.get("/_/mount?list=list", member=NELL).json()["list"]
    titles = [r["title"] for s in j["sections"] for g in s["groups"] for r in g["rows"]]
    assert "Reply <img src=/x onerror=alert(1)> & co" in titles


def test_the_list_script_and_style_are_files_the_mount_assets_carry(box, browser):
    page = box.get("/list", member=NELL).text
    js = browser.get("/_/mount.js", cookie=False).text
    css = browser.get("/_/mount.css", cookie=False).text
    assert "sheafList" in js and "sheafList" in page
    assert ".sheaf-list" in css and ".sheaf-list" in page


def test_a_member_on_the_proxy_gets_the_mount_assets(box):
    """The front loads `/_/mount.js` and `/_/mount.css` through the proxy, as a member: the open routes the proxy
    otherwise refuses to members."""
    for name, kind in (("mount.js", "text/javascript"), ("mount.css", "text/css")):
        path = f"/_/{name}"
        r = box.get(f"{path}?v={box.hub.assets[name].tag}", member=NELL)
        assert "immutable" in r.headers.get("Cache-Control", ""), (path, r.headers)
        assert r.status == 200 and r.headers["Content-Type"].startswith(kind), (path, r.status)
    assert box.get("/_/health", member=NELL).status == 404          # the other open routes stay off the proxy


def test_a_list_made_by_its_leading_crs_has_its_marks_found():
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import ticked_html
    block = split_md_blocks('\r\r\r\r- [ ] Approve\n')[0]
    frag = ticked_html(block, 0)
    assert frag is not None and 'checked' in frag


@pytest.mark.parametrize("src", [' \r- [ ] Approve\n', '  \r- [ ] Approve\n', '\r \r- [ ] Approve\n'])
def test_a_cr_among_the_indent_of_a_list_keeps_its_marks(src):
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import ticked_html
    block = split_md_blocks(src)[0]
    assert ticked_html(block, 0) is not None


def _page_with_box_flipped(block, k):
    """The block as the page would send it after a click on its `k`th box: the render, that box flipped. Built
    from the render alone, so it does not depend on `task_marks` or `ticked_html`."""
    from bs4 import BeautifulSoup
    from sheafmd import copyblock
    from sheafmd.edit import _render_source
    # The render is the cached one, as in production: it is the same text, and a cache hit changes nothing here.
    soup = BeautifulSoup(copyblock.mark(_render_source(block.content), page=True), "html.parser")
    box = soup.select('input[type="checkbox"]')[k]
    if box.has_attr("checked"):
        del box["checked"]
    else:
        box["checked"] = ""
    return str(soup)


@pytest.mark.parametrize("src, k", [
    ('- x\n  ```\n  - [ ] A\n  ```\n- \r[ ] B\n', 0),
    ('- x\n  ```\n \r - [ ] A\n  ```\n- \r[ ] B\n', 0),
])
def test_a_cr_never_makes_the_tick_land_on_a_mark_in_a_code_block(src, k):
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes
    block = split_md_blocks(src)[0]
    out = _toggle_boxes(block, _page_with_box_flipped(block, k))
    assert out is None or out == src.replace("- \r[ ] B", "- \r[x] B")


@pytest.mark.parametrize("src, ticked", [
    # pandoc 3.9 draws no box for the empty item; `- - [ ] x` is the box. Before ticket 135 the save refused (the marks
    # were not the boxes one for one); it is written now, on the box's own line and on no other.
    ('- [ ]\n- - [ ] x\n', '- [ ]\n- - [x] x\n'),
    ('- [ ]\r\n- - [ ] x\r\n', '- [ ]\r\n- - [x] x\r\n'),
    ('- [ ]\n-\r - [ ] x\n', '- [ ]\n-\r - [x] x\n'),
])
def test_a_tick_beside_an_empty_task_item_is_written_on_the_boxs_own_line(src, ticked):
    # The marks and the boxes drawn were the same in number and state, but not the same items: the tick
    # of "x" was written on the empty item's line (measured on pandoc 3.9, no CR needed).
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes
    block = split_md_blocks(src)[0]
    assert _toggle_boxes(block, _page_with_box_flipped(block, 0)) == ticked


@pytest.mark.parametrize("src, ticked", [
    ('- [ ]\n-\r [ ] b\n', '- [ ]\n-\r [x] b\n'),          # c2 of ticket 113: the page ticks b, the save used to tick the other line
    ('- [ ]\n- [ ]\r b\n', '- [ ]\n- [x]\r b\n'),
    ('- [ ]\n- [ ] b\n', '- [ ]\n- [x] b\n'),
])
def test_an_empty_task_item_next_to_a_box_never_takes_its_tick(src, ticked):
    # One box over two marks: the render says which mark the box is (ticket 135), so the tick is written on b's
    # line, never on the empty item's (before, the count check refused it).
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes
    block = split_md_blocks(src)[0]
    assert _toggle_boxes(block, _page_with_box_flipped(block, 0)) == ticked


def test_a_task_mark_read_through_crs_refuses_a_group_it_does_not_have():
    from sheafmd.edit import task_marks
    m = task_marks("\r- [ ] a\n")[0]
    assert (m.start(), m.start(2), m.end(2), m.group(2)) == (0, 4, 5, " ")
    assert m.end() == m.end(0) == 6                  # as `re.Match.end()`: after the `]`, not after the state character
    for call in (lambda: m.group(1), lambda: m.start(1), lambda: m.end(1)):
        with pytest.raises(IndexError):
            call()


def test_a_task_mark_read_through_crs_ends_where_a_match_does():
    from sheafmd.edit import task_marks
    for crs in ("", "\r", "\r\r"):
        plain = task_marks("- [ ] a\n")[0]
        read = task_marks(f"{crs}- [ ] a\n")[0] if crs else plain
        assert read.end() == len(crs) + plain.end()


def test_a_tick_save_renders_the_source_once_and_the_result_once(monkeypatch):
    # d3 of ticket 120: `_unchanged` and `_toggle_boxes` each rendered the same source, so a tick ran pandoc 3 times
    # (1.28 s -> 2.86 s for 200 items). The source render is shared; the result's own render stays, it is the check.
    from sheafmd import _pandoc
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _rendered, _toggle_boxes, _unchanged, ticked_html
    block = split_md_blocks("".join(f"- [ ] item {i}\n" for i in range(5)))[0]
    fragment = ticked_html(block, 2)
    _rendered.cache_clear()
    runs = []
    real = _pandoc.run
    monkeypatch.setattr(_pandoc, "run", lambda *a, **k: runs.append(1) or real(*a, **k))
    assert not _unchanged(block, fragment)
    assert _toggle_boxes(block, fragment) is not None
    assert len(runs) == 2


def test_a_render_that_failed_is_not_kept_for_the_next_tick(monkeypatch):
    # Opus review of PR 353, b1: a timeout once (pandoc's 124) must not send every later tick of that block through
    # the general path, which rewrites the whole list.
    import subprocess
    from sheafmd import _pandoc
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _rendered, _toggle_boxes, ticked_html
    block = split_md_blocks("* [ ] one\n* [ ] two\n* [ ] three\n")[0]
    fragment = _page_with_box_flipped(block, 1)
    _rendered.cache_clear()
    real = _pandoc.run
    monkeypatch.setattr(_pandoc, "run", lambda args, text: subprocess.CompletedProcess(args, 124, "", "timeout"))
    assert ticked_html(block, 1) is None and _toggle_boxes(block, fragment) is None
    monkeypatch.setattr(_pandoc, "run", real)
    assert _toggle_boxes(block, fragment) == "* [ ] one\n* [x] two\n* [ ] three\n"
    assert ticked_html(block, 1) is not None


def test_a_task_mark_with_a_cr_inside_its_brackets_ends_after_the_bracket():
    from sheafmd.edit import task_marks
    src = "- [ \r] a\n"
    m = task_marks(src)[0]
    assert src[m.start():m.end()] == "- [ \r]"


@pytest.mark.parametrize("src", ["1. [ ] a\n", "1) [x] a\n", "1. [ \r] a\n", "7.\r [ ] a\n"])
def test_an_ordered_item_is_no_task_mark_because_pandoc_draws_it_no_box(src):
    # c1 of ticket 128, measured on pandoc 3.9: `1. [ ] a` has no box, with a CR or without. The review put it on the
    # CR in `1. [ \r] d`; the CR changes nothing, the marks only have to be the ones pandoc draws a box for.
    from sheafmd import _pandoc
    from sheafmd.edit import task_marks
    assert "checkbox" not in _pandoc.run(["-f", "gfm", "-t", "html5"], src).stdout
    assert task_marks(src) == []


@pytest.mark.parametrize("src, k, want", [
    ("- x\n  1. [ ] b\n- [ ] c\n", 0, "- x\n  1. [ ] b\n- [x] c\n"),
    ("- x\r\n  1. [ ] b\r\n- [ ] c\r\n", 0, "- x\r\n  1. [ ] b\r\n- [x] c\r\n"),
])
def test_a_tick_beside_an_ordered_item_flips_its_line_and_leaves_the_rest(src, k, want):
    # The ordered item drew no box, so the marks and the boxes had different counts and the tick went through pandoc,
    # which rewrites the whole list.
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes
    block = split_md_blocks(src)[0]
    assert _toggle_boxes(block, _page_with_box_flipped(block, k)) == want


@pytest.mark.parametrize("src", ["- - [ ] o\n", "1. - [ ] g\n", "1. > - [ ] x\n", "- > - [x] x\n"])
def test_a_bullet_task_behind_another_marker_has_its_mark(src):
    # Ticket 128, b1 of its review: pandoc draws a box for the bullet behind another marker, and the mark must be
    # there or the block's counts of marks and boxes differ and every tick of it rewrites the list.
    from sheafmd import _pandoc
    from sheafmd.edit import task_marks
    assert _pandoc.run(["-f", "gfm", "-t", "html5"], src).stdout.count("checkbox") == 1
    assert len(task_marks(src)) == 1 and src[task_marks(src)[0].start(2)] in " x"


@pytest.mark.parametrize("src, k, want", [
    ("- [ ]\n  text\n1. [ ]\n- - [ ] o\n", 0, "- [x]\n  text\n1. [ ]\n- - [ ] o\n"),
    ("- [ ] a\n1. - [ ] g\n", 1, "- [ ] a\n1. - [x] g\n"),
])
def test_a_tick_in_a_block_with_a_box_behind_another_marker_is_written_in_place(src, k, want):
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes
    block = split_md_blocks(src)[0]
    assert _toggle_boxes(block, _page_with_box_flipped(block, k)) == want


@pytest.mark.parametrize("src, k, want", [
    # An empty item has a mark and no box, and a box behind another marker has a box and (since ticket 128) a mark:
    # the first reading has three marks for two boxes. The reading by box (ticket 132) has two, and the render of
    # the result confirms it.
    ("* [X] c\n- [ ]\n1. - [ ] g\n", 0, "* [ ] c\n- [ ]\n1. - [ ] g\n"),
    ("- [ ]\n- - [ ] o\n  - [ ] i\n", 1, "- [ ]\n- - [ ] o\n  - [x] i\n"),
    ("+ [ ] d\n- [ ]\n- - [ ] o\n", 0, "+ [x] d\n- [ ]\n- - [ ] o\n"),
])
def test_a_tick_that_the_second_reading_made_in_place_is_still_made_in_place(src, k, want):
    # Ticket 128, b1 again (Rhea): a PR never makes a case worse than b90b6a0.
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes
    block = split_md_blocks(src)[0]
    out = _toggle_boxes(block, _page_with_box_flipped(block, k))
    assert (out is not None) == (want is not None)
    assert want is None or out == want


def test_a_long_run_of_quote_marks_is_read_in_linear_time():
    # Re-read of the b1 fix, b2: the chain accepted `>` twice over (the leading quotes and the chain), so a line of
    # n `>` cost n squared: 14.6 s at 5000 against 3 ms before ticket 128.
    import time
    from sheafmd.edit import task_marks
    t = time.perf_counter()
    assert task_marks("> " * 5000 + "x\n") == [] and task_marks("> " * 5000 + "- [ ] x\n") != []
    assert time.perf_counter() - t < 1


def test_a_list_tick_made_through_the_second_reading_is_offered_and_written():
    # d3 of the re-read: ticked_html goes through the reading by box too (an empty item beside a box behind a marker).
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes, ticked_html
    block = split_md_blocks("* [X] c\n- [ ]\n1. - [ ] g\n")[0]
    fragment = ticked_html(block, 0, tick=False)
    assert fragment is not None and _toggle_boxes(block, fragment) == "* [ ] c\n- [ ]\n1. - [ ] g\n"


def _list_tick(body: str, word: str = "Approve"):
    """What the list's button does with the first `word` box of a rectoverso: (the block's text after the tick as the save
    writes it or None when the save would go through pandoc, the box the page is told, the edit or None)."""
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes
    text = "# A rectoverso\n\n" + body
    sheaf = the_list.read_rectoverso("x.md", text)
    n = [a[0] for a in sheaf.actions].index(word)
    at = the_list.box_place(text, sheaf.actions[n][2])
    edit = the_list.tick_edit(text, n, word)
    block = split_md_blocks(text)[edit["i"]] if edit else None
    return (None if edit is None else _toggle_boxes(block, edit["html"])), at, edit


@pytest.mark.parametrize("body, ticked", [
    # F2 of the gate review of PR 360: Approve is the 2nd box drawn but the 3rd mark of the first reading
    # (the empty `- [ ]` has a mark and no box); it was refused, and written in place before ticket 128.
    ("- [ ]\n- - [ ] o\n- [ ] Approve\n", "- [ ]\n- - [ ] o\n- [x] Approve\n"),
    ("- - [ ]\n- [ ] Approve\n", "- - [ ]\n- [x] Approve\n"),
])
def test_the_lists_button_ticks_in_place_where_an_empty_item_stands_before_it(body, ticked):
    out, at, edit = _list_tick(body)
    assert out == ticked


def test_the_lists_button_never_ticks_another_box_than_its_own():
    # F1 of the gate review of PR 360: the box number was the mark's, and a mark and a box are not the same count
    # (an empty item draws no box). Approve was number 4 and the 5th box of the block was `+ [ ] d`.
    body = "> 1. > - [ ] x\n- - [ ]\n  - [ ] Approve\n+ [ ] d\n"
    out, at, edit = _list_tick(body)
    assert out == "- - [ ]\n  - [x] Approve\n+ [ ] d\n"      # the quote is a block of its own


@pytest.mark.parametrize("body, k", [
    ("- [ ]\n- - [ ] o\n- [ ] Approve\n", 1),        # the box the page draws second
    ("1. [ ] e\n- [ ] Approve\n", 0),                 # an ordered item draws no box
    ("- - [ ]\n  - [ ] Approve\n", 0),                # an empty item draws none
    ("- [ ] a\n- [ ] Approve\n", 1),
])
def test_the_box_the_page_is_told_is_the_one_the_page_draws(body, k):
    # The page ticks `boxesOf(block)[k]` (page.js): `k` counts the boxes drawn, not the marks of the source.
    out, at, edit = _list_tick(body)
    assert at is not None and at[1] == k


def test_the_page_asks_a_boxs_number_once_per_text(monkeypatch):
    # Re-read of the fix of PR 360, b: box_place ran one pandoc render per button on every serve of the page.
    from sheafmd import _pandoc
    from sheafmd.edit import _rendered, box_number
    src = "- [ ] zq-once-a\n- [ ] zq-once-b\n"
    at = src.index("[ ]") + 1
    box_number(src, at)
    _rendered.cache_clear()             # the render's own cache of 8 would answer alone: the answer's is the test
    runs = []
    real = _pandoc.run
    monkeypatch.setattr(_pandoc, "run", lambda *a, **k: runs.append(1) or real(*a, **k))
    assert box_number(src, at) == 0 and runs == []


@pytest.mark.parametrize("body, ticked", [
    # Ticket 135 (d of the re-read of PR 360): the marks of the first reading are not the boxes one for one, and
    # the list's button refused each of these, as main did. The mark of the action has a box: it is written in place.
    ("- [ ] Approve\n- [ ]\n- [ ] Done\n", "- [x] Approve\n- [ ]\n- [ ] Done\n"),
    ("- [ ]\n  - [ ] Approve\n", "- [ ]\n  - [x] Approve\n"),
    ("- [ ]\r\n- [ ] Approve\r\n", "- [ ]\r\n- [x] Approve\r\n"),
    ("- [ ] Approve\n- <input type=\"checkbox\"> x\n", "- [x] Approve\n- <input type=\"checkbox\"> x\n"),
    ("- <input type=\"checkbox\"> x\n- [ ] Approve\n", "- <input type=\"checkbox\"> x\n- [x] Approve\n"),
    # an empty item between marks, a box behind a chain, and an ordered item that draws no box, all in one list
    ("- [ ]\n- - [ ] o\n1. [ ] e\n- [ ]\n- [ ] Approve\n", "- [ ]\n- - [ ] o\n1. [ ] e\n- [ ]\n- [x] Approve\n"),
])
def test_the_lists_button_ticks_in_place_where_marks_and_boxes_do_not_follow_one_for_one(body, ticked):
    out, at, edit = _list_tick(body)
    assert out == ticked


@pytest.mark.parametrize("body, ticked", [
    # Ticket 132 (c1 of the review of ticket 128): the page's own save of a tick, where the first reading's marks
    # are not the boxes: the reading by box (the render says which mark is which box) writes it in place.
    ("- [ ] a\n- [ ]\n- [ ] b\n", "- [x] a\n- [ ]\n- [ ] b\n"),
    ("- [ ]\n  - [ ] a\n", "- [ ]\n  - [x] a\n"),
])
def test_the_pages_tick_is_written_in_place_where_an_empty_item_stands_among_the_marks(body, ticked):
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes, ticked_html
    block = split_md_blocks(body)[0]
    fragment = ticked_html(block, 0)
    assert fragment is not None and _toggle_boxes(block, fragment) == ticked


def test_a_box_with_no_mark_is_never_flipped_by_the_save():
    # A raw `<input>` draws a box and has no mark: a page that ticked it has no mark to write, so the save is
    # the general one (None), whatever the other marks of the block are.
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes, ticked_html
    block = split_md_blocks('- [ ] a\n- <input type="checkbox"> x\n')[0]
    assert ticked_html(block, 1) is None
    assert _toggle_boxes(block, _page_with_box_flipped(block, 1)) is None
    assert _toggle_boxes(block, _page_with_box_flipped(block, 0)) == '- [x] a\n- <input type="checkbox"> x\n'


def test_ticked_html_of_a_box_the_block_does_not_draw_is_none():
    # Re-read of ticket 132, c1: it raised IndexError (found[k]) where main answered None.
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import ticked_html
    assert ticked_html(split_md_blocks("- [ ] a\n- [x] b\n")[0], 2) is None
    assert ticked_html(split_md_blocks("just a paragraph\n")[0], 0) is None


def _renders(monkeypatch):
    from sheafmd import _pandoc
    from sheafmd.edit import _rendered
    _rendered.cache_clear()
    runs = []
    real = _pandoc.run
    monkeypatch.setattr(_pandoc, "run", lambda *a, **k: runs.append(1) or real(*a, **k))
    return runs


def test_a_text_edit_of_a_long_task_list_costs_no_render_of_marks(monkeypatch):
    # Re-read of ticket 132, b1: the reading by box ran one render per mark on every text edit (200 marks: 200
    # renders, 11 s). The check that the page changed only ticks comes first now, and the reading lays the marks
    # out in about log2 of them renders.
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes
    block = split_md_blocks("- [ ]\n" + "".join(f"- [ ] item {i}\n" for i in range(200)))[0]
    edited = _page_with_box_flipped(block, 0).replace("item 7<", "item seven<")
    runs = _renders(monkeypatch)
    assert _toggle_boxes(block, edited) is None
    assert len(runs) <= 3


def test_a_tick_in_a_long_task_list_with_an_empty_item_costs_a_fixed_number_of_renders(monkeypatch):
    # Ticket 140, c2: the reading by box rendered the list once per bit of its marks (17 s at 4,100 items). The
    # empty items are told from the text, so a tick costs the source's render and the check of the result, however
    # long the list. d1: the count is the same at 200 and at 800 items.
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import _toggle_boxes
    counts = []
    for n in (200, 800):
        src = "- [ ]\n" + "".join(f"- [ ] item {i}\n" if i % 50 else "- [ ]  \n" for i in range(n))
        block = split_md_blocks(src)[0]
        page = _page_with_box_flipped(block, 5)
        runs = _renders(monkeypatch)
        want = src.replace("- [ ] item 6\n", "- [x] item 6\n")   # two empty items before it
        assert _toggle_boxes(block, page) == want
        counts.append(len(runs))
    assert counts[0] == counts[1] <= 3


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_ticked_html_in_a_long_list_with_empty_items_and_a_continued_item_costs_a_fixed_number_of_renders(monkeypatch, eol):
    # Ticket 140, review c2/c3: the same cost through the list's button and with CRLF, and an empty mark with an
    # indented line under it (pandoc draws that one as a box) is kept by the text reading.
    from sheafmd.blocks import split_md_blocks
    from sheafmd.edit import ticked_html
    counts = []
    for n in (200, 800):
        src = eol.join(["- [ ]", "- [ ] ", "  continued"] + [f"- [ ] item {i}" for i in range(n)]) + eol
        block = split_md_blocks(src)[0]
        runs = _renders(monkeypatch)
        html = ticked_html(block, 6)                 # box 0 is the continued item, so box 6 is item 5
        assert html is not None and html.count("checked") == 1
        counts.append(len(runs))
    assert counts[0] == counts[1] <= 3


# Ticket 145, c1 of the review of PR 374: shapes the reading of the marks from the text alone guesses wrong. Each is
# (source, the lines whose mark pandoc draws a box for, in box order). The first two guess wrong but harmlessly: the
# reading of every mark already matches the boxes there, so it serves and `_boxed_marks` is not reached (review of
# PR 378). The other six send the tick to `_boxed_marks`.
_MISGUESSED_SHAPES = {
    "nbsp after the mark": ("- [ ] \xa0\n- [ ] b\n- [ ] c\n", [0, 1, 2]),
    "quoted continuation": ("> - [ ]\n>   more\n> - [ ] b\n> - [ ] c\n", [0, 2, 3]),
    "empty parent with a sublist": ("- [ ]\n  - [ ] c\n- [ ] d\n", [1, 2]),
    "heading under an empty mark": ("- [ ]\n  # h\n- [ ] b\n- [ ] c\n", [2, 3]),
    "fence under an empty mark": ("- [ ]\n  ```\n  x\n  ```\n- [ ] b\n- [ ] c\n", [4, 5]),
    "indented code under an empty mark": ("- [ ]\n      code\n\n- [ ] b\n- [ ] c\n", [3, 4]),
    "html comment after the mark": ("- [ ] <!-- c -->\n- [ ] b\n- [ ] c\n", [1, 2]),
    "lazy line of one space": ("- [ ]\n foo\n- [ ] b\n- [ ] c\n", [2, 3]),
}


@pytest.mark.parametrize("shape", _MISGUESSED_SHAPES)
def test_a_tick_in_a_list_the_text_reading_guesses_wrong_still_lands_on_the_right_line(shape, monkeypatch):
    # The guess is only a candidate: `_toggle_boxes` renders what it writes and refuses a reading that draws other
    # boxes, then `_boxed_marks` serves. So a wrong guess costs renders and never a wrong write: every box ticks
    # its own mark and nothing else changes.
    from sheafmd.blocks import split_md_blocks
    from sheafmd import edit
    from sheafmd.edit import _drawing_marks, _toggle_boxes, task_marks, ticked_html
    src, real = _MISGUESSED_SHAPES[shape]
    lines = src.split("\n")
    marks = task_marks(src)
    guess = [m.start() for m in _drawing_marks(src, marks)]
    truth = [sum(len(x) + 1 for x in lines[:i]) for i in real]
    assert guess != truth                        # the shape is one the guess misreads
    block = split_md_blocks(src)[0]
    reached = []
    real_boxed = edit._boxed_marks
    monkeypatch.setattr(edit, "_boxed_marks", lambda c: reached.append(1) or real_boxed(c))
    for k, i in enumerate(real):
        want = "\n".join(l.replace("[ ]", "[x]", 1) if j == i else l for j, l in enumerate(lines))
        assert _toggle_boxes(block, _page_with_box_flipped(block, k)) == want, k
        html = ticked_html(block, k)
        assert html is not None
        from bs4 import BeautifulSoup
        boxes = BeautifulSoup(html, "html.parser").select('input[type="checkbox"]')
        assert [b.has_attr("checked") for b in boxes] == [j == k for j in range(len(real))], k
    if shape not in ("nbsp after the mark", "quoted continuation"):
        assert reached                               # the slow fallback served, not a lucky first reading
