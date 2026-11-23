"""Work on this (SPEC 9.12): a member downloads the transcript of a rectoverso's box-hosted session, reports the
fork they made of it on their machine, and on a rectoverso whose live session runs on the box sends Tell
to James's window by a file the hub drops. Through the handler in proxy mode, with the list's root as the
members' root: Alice owns the rectoversos, Bob is a member of the project, Bea is a member of another root."""
import json
import os
import pwd
import re
import shutil
import subprocess
import uuid

import pytest
from helpers import FRONT, Front, hub_rows

from sheafmd.hub import proxy, the_list
from sheafmd.hub import work as work_mod

ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BOB = "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"
BEA = "9c1d2e3f-0000-4a51-8c0e-1f2a3b4c5d6e"
LIVE = "6f1c0e9a-2b3d-4c5e-8f70-1a2b3c4d5e6f"
OLDER = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
LAPTOP = "11111111-2222-4333-8444-555555555555"
DOC = "acme/tiroir/2026-10-28-contract.md"
ADDRESS = f"work/{DOC}"
FOLDER = "-home-james-work-acme-tiroir"

SHEAF = f"""---
client: acme
project: tiroir
issue: acme/agency-tiroir#8
assistant: James
owner: alice
sources: [issue:acme/agency-tiroir#8]
sessions:
  - {{id: {LIVE}, host: agency-tiroir, member: james, date: 2026-10-28T05:12:03Z}}
  - {{id: {LAPTOP}, host: alice-laptop, member: alice, date: 2026-10-27T09:00:00Z}}
  - {{id: {OLDER}, host: agency-tiroir, member: james, date: 2026-10-26T08:00:00Z}}
---
# What the contract says

A quote from the contract.
"""
CWD = "/home/james/work/acme/tiroir"
# As Claude Code writes them: the first line naming a cwd names the project's folder and the session (#146).
TRANSCRIPT = (b'{"type":"user","cwd":"%s","sessionId":"%s","message":"hello"}\n'
              b'{"type":"assistant","message":"hi"}\n') % (CWD.encode(), LIVE.encode())
OLDER_TRANSCRIPT = b'{"older":true,"cwd":"%s","sessionId":"%s"}\n' % (CWD.encode(), OLDER.encode())


def the_team(work, tmp_path, alices_tokens=()):
    """The `[proxy]` table of the three members; `alices_tokens` are the door tokens bound to Alice."""
    return proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                        "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                        "members": {ALICE: {"name": "Alice", "short": "alice", "roots": [str(work)],
                                              "shell": True, "tokens": list(alices_tokens)},
                                    BOB: {"name": "Bob", "short": "bob", "roots": [str(work)]},
                                    BEA: {"name": "Bea", "roots": [str(tmp_path / "other")]}}},
                       "the test")


@pytest.fixture
def team(hub, browser, work, plan, tmp_path):
    hub.proxy = the_team(work, tmp_path)
    (tmp_path / "other").mkdir()
    (work / "projects.toml").write_text('[projects."acme/tiroir"]\nmembers = ["alice", "bob"]\n'
                                        'status = "live"\n', encoding="utf-8")
    return Front(hub, browser.handler)


@pytest.fixture
def box(team, tmp_path, work):
    """The list on `work`, with the box's folders beside it: the transcripts' copy and the Tell drop."""
    sessions, tell = tmp_path / "sessions", tmp_path / "tell"
    (sessions / FOLDER).mkdir(parents=True)
    tell.mkdir()
    (sessions / FOLDER / f"{LIVE}.jsonl").write_bytes(TRANSCRIPT)
    (sessions / FOLDER / f"{OLDER}.jsonl").write_bytes(OLDER_TRANSCRIPT)
    cfg = the_list.parse({"root": str(work), "repo": "acme/agency-tiroir", "project": 1,
                          "token_file": str(tmp_path / "token"), "sessions_dir": str(sessions),
                          "tell_dir": str(tell), "box": "agency-tiroir", "work_dir": "/home/james/work",
                          "attach": "ssh agency-tiroir -t tmux attach -t james \\; select-window -t ={window}"},
                         "the test")
    team.hub.the_list = the_list.TheList(team.hub, cfg)
    put(team, work, DOC, SHEAF)
    return {"sessions": sessions, "tell": tell}


def put(team, work, rel, text):
    f = work / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    team.hub.roots.for_document(f)
    return f"work/{rel}"


def download(team, doc=ADDRESS, id=None, member=BOB):
    q = f"/_/session?doc={doc}" + (f"&id={id}" if id is not None else "")
    return team.get(q, member=member)


def test_a_member_downloads_the_transcript_of_the_sheafs_newest_box_session(team, box):
    got = download(team)
    assert got.status == 200, got.text
    assert got.body == TRANSCRIPT
    assert got.headers["Content-Type"] == "application/x-ndjson"
    assert got.headers["Content-Disposition"] == f'attachment; filename="{LIVE}.jsonl"'
    assert got.headers["Cache-Control"] == "no-store"
    assert got.headers["X-Sheaf-Session"] == LIVE


# ── who may download (R10) ───────────────────────────────────────────────────

def test_a_member_of_another_root_gets_the_404_of_a_missing_document(team, box):
    got = download(team, member=BEA)
    missing = download(team, doc="work/acme/tiroir/nothing.md", member=BOB)
    assert got.status == missing.status == 404 and got.body == missing.body
    assert hub_rows("transcript-downloaded") == []


def test_on_an_owner_only_sheaf_only_its_owner_downloads(team, box, work):
    put(team, work, DOC, SHEAF.replace("sources: [issue:acme/agency-tiroir#8]", "sources: [library:doc-1]"))
    got = download(team, member=BOB)
    assert got.status == 404 and got.json()["error"] == "no such document"
    assert download(team, member=ALICE).body == TRANSCRIPT


def test_the_loopback_port_has_no_session_route(team, box, browser):
    assert browser.get(f"/_/session?doc={ADDRESS}").status == 404
    assert browser.post("/_/sessions", {"doc": ADDRESS, "id": LIVE, "machine": "x"}).status == 404


def test_a_document_outside_the_lists_root_or_not_at_project_depth_has_no_session(team, box, work):
    put(team, work, "acme/2026-10-28-top.md", SHEAF)
    assert download(team, doc="work/acme/2026-10-28-top.md").status == 404
    team.hub.the_list = None
    assert download(team).status == 404


# ── what the request may name (R11) ──────────────────────────────────────────

@pytest.fixture
def outside(tmp_path):
    """A transcript of the same id outside sessions_dir, which no request may reach: the project's as far as its first
    line goes, so only the refusal to follow a link keeps it out (#146)."""
    f = tmp_path / "secret" / f"{LIVE}.jsonl"
    f.parent.mkdir()
    f.write_text(json.dumps({"secret": True, "cwd": CWD, "sessionId": LIVE}) + "\n", encoding="utf-8")
    return f


@pytest.mark.parametrize("doc", [
    f"work/acme/tiroir/../tiroir/{DOC.rsplit('/', 1)[1]}",
    f"work/acme/tiroir/%2e%2e/tiroir/{DOC.rsplit('/', 1)[1]}",
    f"work//{DOC}",
    f"/work/{DOC}",
    f"work/{DOC}%00",
    "work/%2e%2e/secret/x.md",
])
def test_a_doc_that_climbs_or_holds_a_nul_is_refused(team, box, doc, outside):
    got = download(team, doc=doc)
    assert got.status == 404 and got.body != TRANSCRIPT


@pytest.mark.parametrize("id", [
    "../secret/" + LIVE, "%2e%2e%2fsecret%2f" + LIVE, "/" + LIVE, LIVE + "%00", LIVE.upper(),
    LIVE + ".jsonl", LIVE[:-1], "not-a-uuid",
])
def test_an_id_of_another_shape_is_refused_with_400(team, box, id, outside):
    got = download(team, id=id)
    assert got.status == 400 and "id" in got.json()["error"]


def test_an_id_the_sheaf_does_not_list_is_refused_even_when_its_file_is_there(team, box):
    stray = "22222222-3333-4444-8555-666666666666"
    (box["sessions"] / FOLDER / f"{stray}.jsonl").write_bytes(b"{}\n")
    assert download(team, id=stray).status == 404


def test_a_laptop_hosted_session_is_never_served(team, box):
    (box["sessions"] / FOLDER / f"{LAPTOP}.jsonl").write_bytes(b"{}\n")
    assert download(team, id=LAPTOP).status == 404


def test_on_a_sheaf_live_on_a_laptop_no_box_session_is_served_without_its_id(team, box, work):
    # agency-tiroir#165: without an id the transcript is the live session's, and a laptop's is never served; the box's
    # older copy is not handed out in its place (`tiroir work` would fork it).
    put(team, work, DOC, SHEAF.replace("host: agency-tiroir, member: james, date: 2026-10-28T05:12:03Z",
                                       "host: alice-laptop, member: alice, date: 2026-10-28T05:12:03Z"))
    assert download(team).status == 404
    assert hub_rows("transcript-downloaded") == []
    got = download(team, id=OLDER)
    assert got.status == 200 and got.body == OLDER_TRANSCRIPT


def test_an_older_box_session_is_served_by_its_id(team, box):
    got = download(team, id=OLDER)
    assert got.status == 200 and got.body == OLDER_TRANSCRIPT and got.headers["X-Sheaf-Session"] == OLDER


# ── only the project's own folder of the copy is looked in (sheaf#146) ───────
STRAY = "33333333-4444-4555-8666-777777777777"


def listed(team, work, sid):
    """The rectoverso with `sid` as an older box session of its own, as a push to the root's remote could list it."""
    put(team, work, DOC, SHEAF.replace(f"  - {{id: {OLDER}", f"  - {{id: {sid}, host: agency-tiroir, member: james, "
                                       f"date: 2026-10-27T08:00:00Z}}\n  - {{id: {OLDER}", 1))


def planted(box, folder, cwd, sid, session=None):
    f = box["sessions"] / folder / f"{sid}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"type": "user", "cwd": cwd, "sessionId": session or sid}) + "\n", encoding="utf-8")


def test_a_listed_id_whose_transcript_is_the_projects_is_served(team, box, work):
    listed(team, work, STRAY)
    planted(box, FOLDER, CWD, STRAY)
    assert download(team, id=STRAY).status == 200


def test_a_listed_id_whose_transcript_is_another_projects_is_not_served(team, box, work):
    listed(team, work, STRAY)
    planted(box, "-home-james-work-acme-site", "/home/james/work/acme/site", STRAY)
    assert download(team, id=STRAY).status == 404
    assert hub_rows("transcript-downloaded") == []


def test_a_transcript_in_the_projects_folder_whose_cwd_is_another_path_is_not_served(team, box, work):
    # Claude's folder name is lossy: acme-tiroir and acme/tiroir share one.
    listed(team, work, STRAY)
    planted(box, FOLDER, "/home/james/work/acme-tiroir", STRAY)
    assert download(team, id=STRAY).status == 404


def test_a_transcript_whose_session_id_is_not_its_name_is_not_served(team, box, work):
    listed(team, work, STRAY)
    planted(box, FOLDER, CWD, STRAY, session=OLDER)
    assert download(team, id=STRAY).status == 404


def test_without_work_dir_no_transcript_is_served(team, box):
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, "work_dir": None}))
    assert download(team).status == 404
    assert download(team, id=OLDER).status == 404


def test_a_transcript_that_is_a_link_out_of_sessions_dir_is_refused(team, box, outside):
    f = box["sessions"] / FOLDER / f"{LIVE}.jsonl"
    f.unlink()
    f.symlink_to(outside)
    assert download(team).status == 404


def test_a_folder_that_is_a_link_out_of_sessions_dir_is_refused(team, box, outside):
    # The project's own folder is the link (#146): no other folder of the copy is looked in at all.
    shutil.rmtree(box["sessions"] / FOLDER)
    (box["sessions"] / FOLDER).symlink_to(outside.parent)
    assert download(team).status == 404


def test_without_sessions_dir_or_box_there_is_no_transcript(team, box, tmp_path, work):
    cfg = team.hub.the_list.cfg
    for change in ({"sessions_dir": None}, {"box": ""}):
        team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, **change}))
        assert download(team).status == 404


def test_a_session_item_that_does_not_parse_is_skipped(team, box, work):
    bad = SHEAF.replace(f"{{id: {LIVE}, host: agency-tiroir, member: james, date: 2026-10-28T05:12:03Z}}",
                        f"{{id: {LIVE}, host: agency-tiroir, member: james, date: yesterday}}")
    put(team, work, DOC, bad)
    # Its file is in the copy, and it is no session: the live one is the laptop's that follows it.
    assert download(team, id=LIVE).status == 404
    assert download(team).status == 404
    got = download(team, id=OLDER)
    assert got.status == 200 and got.headers["X-Sheaf-Session"] == OLDER


def test_a_download_writes_its_row(team, box):
    download(team)
    row, = hub_rows("transcript-downloaded")
    assert (row["doc"], row["transcript"], row["by"], row["issue"]) == (ADDRESS, LIVE, "bob", "acme/agency-tiroir#8")


# ── config ───────────────────────────────────────────────────────────────────

def members(**extra):
    return {"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock", "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
            "members": {BOB: {"name": "Bob", "roots": ["/srv/work"], **extra}}}


def test_shell_is_false_unless_the_member_block_says_true():
    assert proxy.parse(members(), "t").members[BOB].shell is False
    assert proxy.parse(members(shell=True), "t").members[BOB].shell is True
    with pytest.raises(proxy.ProxyError, match="'shell' must be true or false"):
        proxy.parse(members(shell="yes"), "t")


def listing(tmp_path, **keys):
    return the_list.parse({"root": str(tmp_path / "list"), "repo": "a/b", "project": 1, "token_file": "/t", **keys},
                          "the test")


@pytest.mark.parametrize("key", ["tell_dir", "sessions_dir"])
def test_a_box_folder_inside_the_lists_root_or_relative_stops_the_start(tmp_path, key):
    with pytest.raises(the_list.ListError, match=f"'{key}' must not be inside the list's root"):
        listing(tmp_path, **{key: str(tmp_path / "list" / "x")})
    with pytest.raises(the_list.ListError, match=f"'{key}' must be an absolute path"):
        listing(tmp_path, **{key: "run/james"})
    assert str(getattr(listing(tmp_path, **{key: "/run/james/x/"}), key)) == "/run/james/x"


@pytest.mark.parametrize("value", ["", "agency_tiroir", "a" * 64, "agency tiroir"])
def test_a_box_that_is_not_a_host_name_stops_the_start(tmp_path, value):
    with pytest.raises(the_list.ListError, match="'box' must be a host name"):
        listing(tmp_path, box=value)


def test_an_attach_of_two_lines_stops_the_start(tmp_path):
    with pytest.raises(the_list.ListError, match="'attach' must be one line"):
        listing(tmp_path, attach="ssh box\nrm -rf /")
    assert listing(tmp_path, box="agency-tiroir", attach="ssh {window}").attach == "ssh {window}"


def test_a_root_holder_the_project_does_not_name_gets_the_404_of_a_missing_document(team, box, work):
    """agency-tiroir #116: the download and the fork report are judged as the page is, by `projects.toml` too (8.12):
    Bob holds the root but the project names Alice alone, so the shared rectoverso is not there for him."""
    missing = download(team, doc="work/acme/tiroir/nothing.md", member=BOB)
    assert download(team, member=BOB).status == 200                # named, he downloads; the hub has read the file
    (work / "projects.toml").write_text('[projects."acme/tiroir"]\nmembers = ["alice"]\nstatus = "live"\n',
                                        encoding="utf-8")
    downloaded = len(hub_rows("transcript-downloaded"))
    before = (work / DOC).read_text(encoding="utf-8")
    got = download(team, member=BOB)
    assert got.status == missing.status == 404 and got.body == missing.body
    forked = team.post("/_/sessions", {"doc": ADDRESS, "id": "7e8f9a0b-1c2d-4e3f-8a4b-5c6d7e8f9a0b",
                                        "machine": "bob-mac"}, member=BOB)
    assert forked.status == 404 and forked.json()["error"] == "no such document"
    assert (work / DOC).read_text(encoding="utf-8") == before
    assert len(hub_rows("transcript-downloaded")) == downloaded and hub_rows("session-forked") == []
    assert team.get(f"/{ADDRESS}", member=BOB).status == 404
    assert download(team, member=ALICE).body == TRANSCRIPT


# ── the fork report ──────────────────────────────────────────────────────────

FORK = "7e8f9a0b-1c2d-4e3f-8a4b-5c6d7e8f9a0b"


def sessions_of(work):
    from sheafmd.hub.visibility import front_matter
    return list(front_matter((work / DOC).read_text(encoding="utf-8")).get("sessions", ()))


def test_a_fork_is_the_first_session_named_by_the_signed_in_member(team, box, work):
    before = (work / DOC).read_text(encoding="utf-8")
    got = team.post("/_/sessions", {"doc": ADDRESS, "id": FORK, "machine": "bob-mac.local"}, member=BOB)
    assert got.status == 200, got.text
    after = (work / DOC).read_text(encoding="utf-8")
    first = sessions_of(work)[0]
    assert first.startswith(f"{{id: {FORK}, host: bob-mac.local, member: bob, date: 20")
    assert after.replace(f"  - {first}\n", "", 1) == before
    from sheafmd.source import md_hash
    assert got.json() == {"ok": True, "hash": md_hash(after)}


def fork(team, id=FORK, as_=BOB, **extra):
    return team.post("/_/sessions", {"doc": ADDRESS, "id": id, "machine": "bob-mac", **extra}, member=as_)


def test_an_id_already_listed_moves_to_the_top_and_is_listed_once(team, box, work):
    assert fork(team, id=OLDER).status == 200
    got = sessions_of(work)
    assert [s.split(",")[0] for s in got] == [f"{{id: {OLDER}", f"{{id: {LIVE}", f"{{id: {LAPTOP}"]
    assert got[0].startswith(f"{{id: {OLDER}, host: bob-mac, member: bob, ")


def test_a_sheaf_with_no_sessions_yet_gets_the_key(team, box, work):
    put(team, work, DOC, SHEAF.split("sessions:\n")[0] + "---\n# Bare\n")
    assert fork(team).status == 200
    assert sessions_of(work)[0].startswith(f"{{id: {FORK}, host: bob-mac, member: bob, ")
    assert (work / DOC).read_text(encoding="utf-8").endswith("---\n# Bare\n")


def unindented(text):
    return text.replace("\n  - {id: ", "\n- {id: ")


def test_an_unindented_list_takes_the_fork_at_its_own_indent_and_lists_an_id_once(team, box, work):
    put(team, work, DOC, unindented(SHEAF))
    assert fork(team, id=OLDER).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    assert [s.split(",")[0] for s in sessions_of(work)] == [f"{{id: {OLDER}", f"{{id: {LIVE}", f"{{id: {LAPTOP}"]
    assert "\n  - {id: " not in text and text.count(f"{{id: {OLDER}") == 1


def test_a_blank_or_comment_line_inside_the_list_does_not_end_it(team, box, work):
    put(team, work, DOC, SHEAF.replace(f"  - {{id: {LAPTOP}", f"\n  # older ones\n  - {{id: {LAPTOP}"))
    assert fork(team, id=OLDER).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    assert text.count(f"{{id: {OLDER}") == 1 and "  # older ones\n" in text


def test_an_empty_flow_list_becomes_the_list_of_the_fork(team, box, work):
    put(team, work, DOC, SHEAF.split("sessions:\n")[0] + "sessions: []\n---\n# T\n")
    assert fork(team).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    assert text.count("sessions:") == 1 and sessions_of(work)[0].startswith(f"{{id: {FORK}, host: bob-mac, ")


def test_sessions_written_on_one_line_are_not_rewritten(team, box, work):
    put(team, work, DOC, SHEAF.split("sessions:\n")[0] + f"sessions: [{{id: {LIVE}}}]\n---\n# T\n")
    before = (work / DOC).read_text(encoding="utf-8")
    got = fork(team)
    assert got.status == 409 and "one item per line" in got.json()["error"]
    assert (work / DOC).read_text(encoding="utf-8") == before and hub_rows("session-forked") == []


def test_the_fork_is_the_signed_in_members_whatever_the_body_names(team, box, work):
    assert fork(team, member="alice", by="alice", name="Alice", email="t@example.com").status == 200
    assert ", member: bob, " in sessions_of(work)[0]
    row, = hub_rows("session-forked")
    assert (row["doc"], row["transcript"], row["by"], row["machine"], row["issue"]) == \
        (ADDRESS, FORK, "bob", "bob-mac", "acme/agency-tiroir#8")


@pytest.mark.parametrize("body, words", [
    ({"id": LIVE.upper()}, "id must be"), ({"id": "../x"}, "id must be"), ({"id": 7}, "id must be"),
    ({"machine": ""}, "machine must be"), ({"machine": "a b"}, "machine must be"), ({"machine": "x" * 64}, "machine must be"),
    ({"machine": "../etc"}, "machine must be"), ({"machine": "box\n"}, "machine must be"),
])
def test_a_fork_report_of_another_shape_is_refused_and_writes_nothing(team, box, work, body, words):
    before = (work / DOC).read_text(encoding="utf-8")
    got = team.post("/_/sessions", {"doc": ADDRESS, "id": FORK, "machine": "bob-mac", **body}, member=BOB)
    assert got.status == 400 and words in got.json()["error"]
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_a_fork_report_from_another_origin_is_refused(team, box, work):
    before = (work / DOC).read_text(encoding="utf-8")
    got = team.post("/_/sessions", {"doc": ADDRESS, "id": FORK, "machine": "m"}, member=BOB,
                    origin="https://evil.example")
    assert got.status == 403
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_a_fork_report_on_a_sheaf_bob_may_not_open_is_404(team, box, work):
    put(team, work, DOC, SHEAF.replace("sources: [issue:acme/agency-tiroir#8]", "sources: [library:doc-1]"))
    before = (work / DOC).read_text(encoding="utf-8")
    assert fork(team).status == 404
    assert fork(team, as_=BEA).status == 404
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_an_open_tab_hears_the_fork(team, box, work):
    sub = team.get(f"/_/live?doc={ADDRESS}", member=ALICE).stream
    sub.drain()
    h = fork(team).json()["hash"]
    events = [(name, data) for name, data in sub.drain() if name == "changed"]
    assert len(events) == 1 and events[0][1]["hash"] == h


def git(at, *args):
    import subprocess
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def committing(hub, browser, tmp_path):
    """The list's root a git repo that commits, as on the box; Bob's member block names no e-mail."""
    repo = tmp_path / "rectoversos"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "the box")
    git(repo, "config", "user.email", "box@example.com")
    (repo / ".sheaf.toml").write_text('commit = true\n', encoding="utf-8")
    (repo / "projects.toml").write_text('[projects."acme/tiroir"]\nmembers = ["bob"]\nstatus = "live"\n', encoding="utf-8")
    (repo / DOC).parent.mkdir(parents=True)
    (repo / DOC).write_text(SHEAF, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                             "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "members": {BOB: {"name": "Bob", "short": "bob", "roots": [str(repo)]}}}, "the test")
    hub.roots.for_document(repo / DOC)
    hub.the_list = the_list.TheList(hub, the_list.parse(
        {"root": str(repo), "repo": "acme/agency-tiroir", "project": 1, "token_file": str(tmp_path / "t"),
         "box": "agency-tiroir"}, "the test"))
    return repo, Front(hub, browser.handler)


def test_the_fork_is_committed_as_the_signed_in_member(committing):
    repo, team = committing
    got = team.post("/_/sessions", {"doc": f"rectoversos/{DOC}", "id": FORK, "machine": "bob-mac",
                                    "member": "alice", "by": "Alice", "name": "Alice",
                                    "email": "alice@example.com"}, member=BOB)
    assert got.status == 200, got.text
    team.hub.commits.settle()
    assert git(repo, "log", "-1", "--format=%an <%ae>|%s").strip() == \
        f"Bob <{proxy.default_email(BOB, FRONT)}>|fork: {DOC}"
    assert ", member: bob, " in git(repo, "show", f"HEAD:{DOC}")


def test_a_write_that_landed_before_the_fork_is_kept(team, box, work):
    team.hub.entry(ADDRESS)                          # a tab has the page
    f = work / DOC
    f.write_text(f.read_text(encoding="utf-8") + "\nA paragraph from another hand.\n", encoding="utf-8")
    assert fork(team).status == 200
    text = f.read_text(encoding="utf-8")
    assert text.endswith("\nA paragraph from another hand.\n") and f"{{id: {FORK}, " in text


# ── Tell to James's window ───────────────────────────────────────────

def comment(team, work, kind, as_=BOB, body="Can you send the draft to Joey?", **extra):
    from sheafmd.blocks import split_md_blocks
    from sheafmd.source import md_hash
    text = (work / DOC).read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("A quote"))
    return team.post("/_/comment", {"doc": ADDRESS, "op": "add", "hash": md_hash(text), "block": i, "start": 0,
                                    "end": 6, "quote": "A quote", "body": body, kind: True, **extra}, member=as_)


def drops(box):
    return sorted(box["tell"].iterdir())


def test_tell_on_a_box_sheaf_writes_the_comment_and_drops_it_for_james(team, box, work):
    got = comment(team, work, "tell")
    assert got.status == 200, got.text
    assert got.json()["telling"] == [{"id": got.json()["id"], "to": "James", "state": "sent"}] and "tellError" not in got.json()
    assert "Can you send the draft to Joey?" in (work / DOC).read_text(encoding="utf-8")
    f, = drops(box)
    assert f.name.startswith("acme--tiroir-20") and f.name.endswith("Z")
    d = json.loads(f.read_bytes())
    tell_keys = {"id": d.get("id"), "message": d.get("message")}
    assert d == {"project": "acme/tiroir", "member": "bob", "sheaf": ADDRESS,
                 "text": "Can you send the draft to Joey?", "kind": "tell", "thread": got.json()["id"],
                 "address": ADDRESS, "abs_path": str(work / DOC), **tell_keys}
    assert list(f.read_bytes().decode()) == list(json.dumps(json.loads(f.read_bytes())))
    row, = hub_rows("tell-dropped")
    assert (row["what"], row["project"], row["by"], row["drop"]) == ("tell", "acme/tiroir", "bob", "written")
    assert team.hub.runner.active("tell", ADDRESS) == []


def test_the_text_dropped_for_james_is_cut_at_3000_characters(team, box, work):
    body = "x" * 2990 + "é" * 20
    assert comment(team, work, "tell", body=body).status == 200
    f, = drops(box)
    assert json.loads(f.read_bytes())["text"] == body[:3000]
    assert body in (work / DOC).read_text(encoding="utf-8")       # the comment itself is written whole


@pytest.mark.parametrize("mask", [0o077, 0o000])
def test_the_drop_is_0640_whatever_the_hubs_umask(team, box, work, mask):
    old = os.umask(mask)
    try:
        assert comment(team, work, "tell").status == 200
    finally:
        os.umask(old)
    f, = drops(box)
    assert f.stat().st_mode & 0o777 == 0o640


def test_the_drop_is_written_as_a_dot_file_then_renamed(team, box, work, monkeypatch):
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (seen.append((os.path.basename(a), os.path.basename(b),
                                                                  os.path.exists(a))), real(a, b))[1])
    assert comment(team, work, "tell").status == 200
    (src, dst, existed), = [x for x in seen if x[1].startswith("acme--")]
    assert src == "." + dst and existed


def test_a_second_drop_in_the_same_second_takes_the_next_name(team, box, work, monkeypatch):
    import time as time_mod
    monkeypatch.setattr(time_mod, "gmtime", lambda *a: time_mod.struct_time((2026, 10, 28, 5, 12, 3, 2, 301, 0)))
    for _ in range(3):
        assert comment(team, work, "tell").status == 200
    assert [f.name for f in drops(box)] == ["acme--tiroir-20261028T051203Z",
                                            "acme--tiroir-20261028T051203Z-1",
                                            "acme--tiroir-20261028T051203Z-2"]


def test_on_a_sheaf_whose_live_session_is_on_a_laptop_tell_stays_refused(team, box, work):
    put(team, work, DOC, SHEAF.replace("host: agency-tiroir, member: james, date: 2026-10-28T05:12:03Z",
                                       "host: alice-laptop, member: alice, date: 2026-10-28T05:12:03Z"))
    before = (work / DOC).read_text(encoding="utf-8")
    got = comment(team, work, "tell")
    assert got.status == 400 and got.json()["error"] == proxy.PROXY_LINE
    assert (work / DOC).read_text(encoding="utf-8") == before and drops(box) == []


def test_without_a_tell_dir_or_outside_the_list_tell_stays_refused(team, box, work, tmp_path):
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, "tell_dir": None}))
    assert comment(team, work, "tell").json()["error"] == proxy.PROXY_LINE
    team.hub.the_list = None
    assert comment(team, work, "tell").json()["error"] == proxy.PROXY_LINE
    assert hub_rows("tell-dropped") == []


def test_ask_is_refused_on_the_box_before_anything_is_written(team, box, work):
    before = (work / DOC).read_text(encoding="utf-8")
    got = comment(team, work, "ask")
    assert got.status == 400 and got.json()["error"] == "Ask was retired: use Tell, or reply."
    assert (work / DOC).read_text(encoding="utf-8") == before and drops(box) == []


def test_a_request_sent_again_drops_once(team, box, work):
    rid = "r" * 20
    assert comment(team, work, "tell", rid=rid).status == 200
    assert comment(team, work, "tell", rid=rid).status == 200
    assert len(drops(box)) == 1


def test_a_reply_with_tell_drops_the_reply(team, box, work):
    cid = comment(team, work, "tell").json()["id"]
    got = team.post("/_/comment", {"doc": ADDRESS, "op": "reply", "id": cid, "body": "And the invoice.",
                                   "tell": True}, member=ALICE)
    assert got.status == 200, got.text
    texts = [(json.loads(f.read_bytes())["text"], json.loads(f.read_bytes())["member"]) for f in drops(box)]
    assert ("And the invoice.", "alice") in texts


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a folder of mode 0500")
def test_a_drop_that_fails_keeps_the_comment_says_so_and_leaves_no_dot_file(team, box, work):
    box["tell"].chmod(0o500)
    try:
        got = comment(team, work, "tell")
    finally:
        box["tell"].chmod(0o700)
    assert got.status == 200 and "James" in got.json()["tellError"]
    assert "Can you send the draft" in (work / DOC).read_text(encoding="utf-8")
    assert hub_rows("tell-dropped")[0]["drop"].startswith("failed: ") and drops(box) == []


# ── the drop's wait (#115) ───────────────────────────────────────────────────

def sent(team, member=BOB):
    got = team.get(f"/_/doc?doc={ADDRESS}", member=member)
    assert got.status == 200, got.text
    return got.json()["sent"]


def test_a_drop_for_james_is_sent_on_every_members_page_until_a_reply_lands_in_its_thread(team, box, work):
    cid = comment(team, work, "tell").json()["id"]
    assert sent(team) == sent(team, ALICE) == [{"id": cid, "kind": "tell", "state": "sent"}]
    got = team.post("/_/comment", {"doc": ADDRESS, "op": "reply", "id": cid, "body": "Sent it."}, member=ALICE)
    assert got.status == 200, got.text
    assert sent(team) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a folder of mode 0500")
def test_a_drop_that_fails_is_not_sent(team, box, work):
    box["tell"].chmod(0o500)
    try:
        assert "tellError" in comment(team, work, "tell").json()
    finally:
        box["tell"].chmod(0o700)
    assert sent(team) == []


def test_a_drop_with_no_reply_after_the_tell_wait_fails_on_the_members_page(team, box, work):
    now = [1_000_000.0]
    team.hub.clock = lambda: now[0]
    tab = team.get(f"/_/live?doc={ADDRESS}", member=BOB).stream
    cid = comment(team, work, "tell").json()["id"]
    now[0] += team.hub.tell_wait - 1
    team.hub.tick()
    assert sent(team) == [{"id": cid, "kind": "tell", "state": "sent"}]
    now[0] += 2
    team.hub.tick()
    assert sent(team) == []
    data = next(d for n, d in tab.drain() if n == "box-failed")
    assert data == {"id": cid, "kind": "tell", "minutes": team.hub.tell_wait // 60}
    row, = hub_rows("box-expired")
    assert (row["what"], row["project"], row["thread"]) == ("tell", "acme/tiroir", cid)



def test_a_drop_answered_before_the_tell_wait_is_never_given_up_on_though_no_page_asked(team, box, work):
    # The reply ends the wait when it lands, not when a page next asks /_/doc (#115).
    now = [1_000_000.0]
    team.hub.clock = lambda: now[0]
    tab = team.get(f"/_/live?doc={ADDRESS}", member=BOB).stream
    cid = comment(team, work, "tell").json()["id"]
    got = team.post("/_/comment", {"doc": ADDRESS, "op": "reply", "id": cid, "body": "Sent it."}, member=ALICE)
    assert got.status == 200, got.text
    now[0] += team.hub.tell_wait + 1
    team.hub.tick()
    assert [n for n, _ in tab.drain() if n == "box-failed"] == []
    assert hub_rows("box-expired") == []



def test_a_drop_answered_in_the_file_from_outside_is_never_given_up_on(team, box, work):
    # `sheaf reply` writes the file without the hub: the tick reads the file, not the hub's copy (#115).
    from sheafmd import comments as rdc
    now = [1_000_000.0]
    team.hub.clock = lambda: now[0]
    cid = comment(team, work, "tell").json()["id"]
    f = work / DOC
    f.write_text(rdc.reply(f.read_text(encoding="utf-8"), cid, "Sent it.", "James", "2026-10-31T15:00"),
                 encoding="utf-8")
    now[0] += team.hub.tell_wait + 1
    team.hub.tick()
    assert hub_rows("box-expired") == []


# ── the member's `telling` holds their own drops (SPEC 9.9, 9.12) ──────────

def telling(team, member=BOB):
    return team.get(f"/_/doc?doc={ADDRESS}", member=member).json()["telling"]


def test_a_members_telling_holds_their_own_drop_for_james_and_no_other_members(team, box, work):
    cid = comment(team, work, "tell").json()["id"]
    assert telling(team) == [{"id": cid, "to": "James", "state": "sent"}]
    assert telling(team, ALICE) == []                                   # `sent` stays every member's (9.12)
    assert sent(team, ALICE) == [{"id": cid, "kind": "tell", "state": "sent"}]


def test_the_drops_telling_follows_the_supervisors_word_and_ends_with_the_reply(team, box, work):
    cid = comment(team, work, "tell").json()["id"]
    status(box, "delivered")
    team.hub.tick()
    assert telling(team) == [{"id": cid, "to": "James", "state": "delivered"}]
    team.post("/_/comment", {"doc": ADDRESS, "op": "reply", "id": cid, "body": "Sent it."}, member=ALICE)
    assert telling(team) == []


def test_the_answer_of_a_comment_and_a_later_changed_event_carry_the_drop_in_telling_to_its_member_only(team, box, work):
    mine, theirs = (team.get(f"/_/live?doc={ADDRESS}", member=m).stream for m in (BOB, ALICE))
    got = comment(team, work, "tell")
    cid = got.json()["id"]
    assert got.json()["telling"] == [{"id": cid, "to": "James", "state": "sent"}]
    mine.drain(), theirs.drain()
    comment(team, work, "note", as_=ALICE, body="Another thread.")                      # a change of the rectoverso
    last = lambda sub: [d for n, d in sub.drain() if n == "changed"][-1]["telling"]
    assert last(mine) == [{"id": cid, "to": "James", "state": "sent"}] and last(theirs) == []
    team.post("/_/comment", {"doc": ADDRESS, "op": "reply", "id": cid, "body": "Done."}, member=ALICE)
    assert last(mine) == [] and telling(team) == []


# ── the drop's status, from the box's supervisor (#139) ──────────────────────

def status(box, state, **extra):
    """The supervisor's word on the one drop: `<drop>.status` beside it, written whole and renamed."""
    f, = [f for f in drops(box) if not f.name.endswith(".status")]
    tmp = box["tell"] / f".{f.name}.status.tmp"
    tmp.write_text(json.dumps({"state": state, **extra}), encoding="utf-8")
    tmp.replace(box["tell"] / f"{f.name}.status")


def test_the_supervisors_answered_is_told_to_the_page_and_ends_the_working_dot(team, box, work):
    # A Starter that answers in the thread writes `answered`: the drop is no longer being worked on.
    tab = team.get(f"/_/live?doc={ADDRESS}", member=BOB).stream
    cid = comment(team, work, "tell").json()["id"]
    status(box, "delivered")
    team.hub.tick()
    assert team.hub.box_waits.working(ADDRESS)
    status(box, "answered")
    team.hub.tick()
    assert sent(team) == []                       # answered ends the drop: no Tell-wait toast later
    assert [d["state"] for n, d in tab.drain() if n == "box-status"] == ["delivered", "answered"]
    assert not team.hub.box_waits.working(ADDRESS)
    assert hub_rows("drop-status-ignored") == []


def test_the_supervisors_picked_up_then_delivered_is_told_to_the_page_once_each(team, box, work):
    tab = team.get(f"/_/live?doc={ADDRESS}", member=BOB).stream
    cid = comment(team, work, "tell").json()["id"]
    assert sent(team) == [{"id": cid, "kind": "tell", "state": "sent"}]
    status(box, "picked-up")
    team.hub.tick()
    team.hub.tick()
    assert sent(team) == [{"id": cid, "kind": "tell", "state": "picked-up"}]
    status(box, "delivered")
    team.hub.tick()
    assert sent(team) == [{"id": cid, "kind": "tell", "state": "delivered"}]
    told = [d for n, d in tab.drain() if n == "box-status"]
    assert told == [{"id": cid, "kind": "tell", "state": "picked-up"}, {"id": cid, "kind": "tell", "state": "delivered"}]
    assert [r["state"] for r in hub_rows("drop-status")] == ["picked-up", "delivered"]


def test_a_failed_drop_ends_with_the_supervisors_error_cut_to_one_line_of_200(team, box, work):
    tab = team.get(f"/_/live?doc={ADDRESS}", member=BOB).stream
    cid = comment(team, work, "tell").json()["id"]
    status(box, "failed", error="the window would not open\n" + "x" * 300)
    team.hub.tick()
    assert sent(team) == []
    data = next(d for n, d in tab.drain() if n == "box-failed")
    assert data["id"] == cid and data["kind"] == "tell"
    assert data["error"] == ("the window would not open " + "x" * 300)[:200]
    row, = hub_rows("drop-status")
    assert row["state"] == "failed"


@pytest.mark.parametrize("bad", ["not json", "[1]", '{"state": "done"}', '{"state": 1}'])
def test_a_status_of_another_shape_is_ignored_once_and_the_drop_stays_open(team, box, work, bad):
    cid = comment(team, work, "tell").json()["id"]
    f, = drops(box)
    (box["tell"] / f"{f.name}.status").write_text(bad, encoding="utf-8")
    team.hub.tick()
    team.hub.tick()
    assert sent(team) == [{"id": cid, "kind": "tell", "state": "sent"}]
    assert len(hub_rows("drop-status-ignored")) == 1 and hub_rows("drop-status") == []


def test_a_status_that_is_a_link_is_never_followed(team, box, work, tmp_path):
    cid = comment(team, work, "tell").json()["id"]
    f, = drops(box)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text('{"state": "delivered"}', encoding="utf-8")
    (box["tell"] / f"{f.name}.status").symlink_to(elsewhere)
    team.hub.tick()
    assert sent(team) == [{"id": cid, "kind": "tell", "state": "sent"}]
    assert len(hub_rows("drop-status-ignored")) == 1


def test_a_status_for_a_name_the_hub_did_not_drop_is_not_read(team, box, work):
    (box["tell"] / "acme--tiroir-20260101T000000Z.status").write_text('{"state": "failed", "error": "x"}')
    cid = comment(team, work, "tell").json()["id"]
    team.hub.tick()
    assert sent(team) == [{"id": cid, "kind": "tell", "state": "sent"}]
    assert hub_rows("drop-status") == hub_rows("drop-status-ignored") == []


def test_a_reply_ends_a_delivered_drop_whatever_the_status_says_next(team, box, work):
    cid = comment(team, work, "tell").json()["id"]
    status(box, "delivered")
    team.hub.tick()
    assert team.post("/_/comment", {"doc": ADDRESS, "op": "reply", "id": cid, "body": "Done."},
                     member=ALICE).status == 200
    status(box, "failed", error="late")
    team.hub.tick()
    assert sent(team) == [] and [r["state"] for r in hub_rows("drop-status")] == ["delivered"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file of mode 0000")
def test_a_status_the_hub_cannot_read_is_ignored_once(team, box, work):
    cid = comment(team, work, "tell").json()["id"]
    status(box, "delivered")
    f, = [f for f in drops(box) if f.name.endswith(".status")]
    f.chmod(0)
    try:
        team.hub.tick()
        team.hub.tick()
    finally:
        f.chmod(0o644)
    assert sent(team) == [{"id": cid, "kind": "tell", "state": "sent"}]
    assert len(hub_rows("drop-status-ignored")) == 1


def test_a_reply_before_the_supervisor_says_delivered_ends_the_drop_first(team, box, work):
    cid = comment(team, work, "tell").json()["id"]
    assert team.post("/_/comment", {"doc": ADDRESS, "op": "reply", "id": cid, "body": "Done already."},
                     member=ALICE).status == 200
    status(box, "delivered")
    team.hub.tick()
    assert sent(team) == [] and hub_rows("drop-status") == []



def test_a_status_nested_too_deep_for_the_parser_is_ignored(team, box, work, monkeypatch):
    # Python 3.11's json recurses on 2048 nested brackets: RecursionError, not ValueError (#139).
    from sheafmd.hub import boxwait

    def deep(_):
        raise RecursionError("maximum recursion depth exceeded")
    cid = comment(team, work, "tell").json()["id"]
    status(box, "delivered")
    from types import SimpleNamespace
    with monkeypatch.context() as m:
        m.setattr(boxwait, "json", SimpleNamespace(loads=deep))
        team.hub.tick()
    assert sent(team) == [{"id": cid, "kind": "tell", "state": "sent"}]
    assert len(hub_rows("drop-status-ignored")) == 1 and hub_rows("drops-failed") == []



# ── a member's index dot (#139) ──────────────────────────────────────────────

def dot(team, member=BOB):
    """The dot of the rectoverso on `member`'s index."""
    got = team.get("/_/index.json", member=member)
    assert got.status == 200, got.text
    return next(d["dot"] for r in got.json()["roots"] for d in r["docs"] if d["doc"] == ADDRESS)


def test_a_delivered_drop_turns_the_members_dot_orange_and_tells_their_index_alone(team, box, work):
    # The member's dot is the supervisor's word, never the hub account's session (9.9, #139).
    mine = team.get("/_/live", member=BOB).stream
    hubs = team.hub.index_bus.subscribe(None, team.hub.index.accepting(None))
    cid = comment(team, work, "tell").json()["id"]
    assert dot(team) != "orange"
    mine.drain(), hubs.drain()
    status(box, "delivered")
    team.hub.tick()
    assert dot(team) == "orange"
    assert ("status", {"doc": ADDRESS, "root": "work"}) in mine.drain()
    assert [d for n, d in hubs.drain() if n == "status" and d.get("doc") == ADDRESS and "dot" not in d] == []



def test_a_delivered_drop_turns_the_orange_of_the_member_who_sent_it_and_no_other_members(team, box, work):
    # 9.9: a member's orange is James working on a drop of theirs, never on another member's.
    cid = comment(team, work, "tell", as_=ALICE).json()["id"]
    assert team.post("/_/seen", {"doc": ADDRESS, "id": cid, "count": 1}, member=BOB).status == 200   # no red to outrank it
    status(box, "delivered")
    team.hub.tick()
    assert dot(team, ALICE) == "orange" and dot(team, BOB) == "blue"


def test_a_members_drop_that_fails_tells_their_index_while_another_members_drop_still_works(team, box, work):
    # The orange of each is their own (9.9): the end of Bob's must reach his index stream although Alice's goes on.
    h = comment(team, work, "tell", as_=BOB).json()["id"]
    t = comment(team, work, "tell", as_=ALICE, body="And the second draft?").json()["id"]
    for who, cid in ((BOB, t), (ALICE, h)):
        assert team.post("/_/seen", {"doc": ADDRESS, "id": cid, "count": 1}, member=who).status == 200
    first, second = [f for f in drops(box) if not f.name.endswith(".status")]
    for f, state in ((first, "delivered"), (second, "delivered")):
        (box["tell"] / f"{f.name}.status").write_text(json.dumps({"state": state}), encoding="utf-8")
    team.hub.tick()
    assert dot(team, BOB) == dot(team, ALICE) == "orange"
    mine = team.get("/_/live", member=BOB).stream
    mine.drain()
    (box["tell"] / f"{first.name}.status").write_text(json.dumps({"state": "failed", "error": "no"}), encoding="utf-8")
    team.hub.tick()
    assert ("status", {"doc": ADDRESS, "root": "work"}) in mine.drain()
    assert dot(team, BOB) == "blue" and dot(team, ALICE) == "orange"


def test_a_delivered_drop_answered_while_a_page_asks_still_clears_the_members_orange(team, box, work):
    # A page's /_/doc settles the drop before the pass does: the pass still tells the members' indexes (#139).
    from sheafmd.hub.index import Status
    cid = comment(team, work, "tell").json()["id"]
    status(box, "delivered")
    team.hub.tick()
    raw = team.hub.index_bus.subscribe()
    assert team.post("/_/comment", {"doc": ADDRESS, "op": "reply", "id": cid, "body": "Done."},
                     member=BOB).status == 200
    assert sent(team) == []
    team.hub.tick()
    assert dot(team) == "blue"
    assert any(isinstance(d, Status) and d.members_only and d["doc"] == ADDRESS for n, d in raw.drain())


# ── the meta block (10.1) ────────────────────────────────────────────────────

def meta(team, member=BOB, doc=DOC):
    from helpers import page_meta
    got = team.get(f"/work/{doc}", member=member)
    assert got.status == 200, got.text
    return page_meta(got.text)


def test_the_meta_block_of_a_box_sheaf_carries_the_fork_command_the_sessions_and_box_tell(team, box):
    m = meta(team)
    assert m["work"] == {"fork": f"uvx --from {work_mod.FORK_CLIENT} tiroir work {FRONT}/{ADDRESS}", "live": "box", "sessions": [
        {"id": LIVE, "host": "agency-tiroir", "member": "james", "date": "2026-10-28T05:12:03Z"},
        {"id": LAPTOP, "host": "alice-laptop", "member": "alice", "date": "2026-10-27T09:00:00Z"},
        {"id": OLDER, "host": "agency-tiroir", "member": "james", "date": "2026-10-26T08:00:00Z"}]}
    assert m["can"] == ["box-tell"]


def test_the_fork_client_is_pinned_to_one_exact_version():
    # agency-tiroir#170: the copied command runs code that holds the member's sign-in; a range (>=, ~=) or a bare
    # name would run whatever is uploaded next.
    assert re.fullmatch(r"tiroir==[0-9]+\.[0-9]+\.[0-9]+", work_mod.FORK_CLIENT)


def test_a_member_with_a_shell_gets_the_attach_command_for_the_projects_window(team, box):
    assert meta(team, ALICE)["work"]["attach"] == \
        r"ssh agency-tiroir -t tmux attach -t james \; select-window -t =acme_tiroir"


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
def test_the_attach_command_takes_the_projects_window_and_never_one_its_name_is_a_prefix_of(team, box):
    # James names a project's window <client>_<project> (agency-tiroir f606f9a), and tmux takes a bare name as a
    # prefix: `-t acme_tiroir` would select acme_tiroir2, another project's window.
    server = f"sheaf-test-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{
        **cfg.__dict__, "attach": f"tmux -L {server} select-window -t ={{window}}"}))
    attach = meta(team, ALICE)["work"]["attach"]

    def tmux(*args):
        return subprocess.run(["tmux", "-L", server, *args], capture_output=True, text=True, timeout=10)

    def active():
        return tmux("display-message", "-p", "-t", "james", "#{window_name}").stdout.strip()
    try:
        assert tmux("new-session", "-d", "-s", "james", "-n", "inbox").returncode == 0
        assert tmux("new-window", "-d", "-t", "james:", "-n", "acme_tiroir2").returncode == 0
        assert subprocess.run(attach, shell=True, capture_output=True, timeout=10).returncode != 0
        assert active() == "inbox"
        assert tmux("new-window", "-d", "-t", "james:", "-n", "acme_tiroir").returncode == 0
        got = subprocess.run(attach, shell=True, capture_output=True, text=True, timeout=10)
        assert got.returncode == 0, got.stderr
        assert active() == "acme_tiroir"
    finally:
        tmux("kill-server")


def test_a_sheaf_live_on_a_laptop_says_so_and_can_nothing(team, box, work):
    put(team, work, DOC, SHEAF.replace("host: agency-tiroir, member: james, date: 2026-10-28T05:12:03Z",
                                       "host: alice-laptop, member: alice, date: 2026-10-28T05:12:03Z"))
    m = meta(team)
    assert m["work"]["live"] == "laptop" and m["can"] == []


def test_without_a_tell_dir_a_box_sheaf_can_nothing_and_without_attach_none_is_offered(team, box):
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, "tell_dir": None,
                                                                        "attach": ""}))
    m = meta(team, ALICE)
    assert m["work"]["live"] == "box" and m["can"] == [] and "attach" not in m["work"]


def test_a_sheaf_with_no_session_has_work_with_no_live_one_and_nothing_to_fork(team, box, work):
    put(team, work, DOC, SHEAF.split("sessions:\n")[0] + "---\n# T\n")
    assert meta(team)["work"] == {"live": "", "sessions": []}


def test_a_sheaf_with_only_laptop_sessions_has_nothing_to_fork(team, box, work):
    put(team, work, DOC, SHEAF.replace("host: agency-tiroir", "host: alice-laptop"))
    w = meta(team)["work"]
    assert "fork" not in w and w["live"] == "laptop"


def test_a_sheaf_live_on_a_laptop_with_an_older_box_session_offers_no_fork_of_that_copy(team, box, work):
    # agency-tiroir#165: the live session is the laptop's, which the hub never serves; a fork of the box's older copy
    # would start a second line of work beside it, and lose what was done on the laptop since.
    put(team, work, DOC, SHEAF.replace("host: agency-tiroir, member: james, date: 2026-10-28T05:12:03Z",
                                       "host: alice-laptop, member: alice, date: 2026-10-28T05:12:03Z"))
    w = meta(team)["work"]
    assert "fork" not in w and w["live"] == "laptop"


def test_a_page_that_is_not_a_sheaf_of_the_list_has_no_work(team, box, work):
    put(team, work, "acme/notes.md", SHEAF)
    assert "work" not in meta(team, doc="acme/notes.md")
    assert "work" not in meta(team, doc="plan.md")


@pytest.mark.parametrize("owner, member, attach", [("alice", ALICE, True), ("bob", BOB, False)])
def test_an_owner_only_sheaf_in_its_owners_private_folder_has_work_at_its_name(team, box, work, owner, member,
                                                                              attach):
    # 9.11: the file lives at <client>/<project>/private/<short>/, but the rectoverso's address stays its name, so its
    # owner gets Work on this as on a project sheaf: the fork, and the attach only with a shell.
    (work / DOC).unlink()
    client, project, name = DOC.split("/")
    put(team, work, f"{client}/{project}/private/{owner}/{name}",
        SHEAF.replace("owner: alice", f"owner: {owner}").replace("sources: [issue:acme/agency-tiroir#8]",
                                                                   "sources: [library:doc-1]"))
    w = meta(team, member)["work"]
    assert w["fork"] == f"uvx --from {work_mod.FORK_CLIENT} tiroir work {FRONT}/{ADDRESS}" and w["live"] == "box"
    assert ("attach" in w) is attach
    assert download(team, member=member).body == TRANSCRIPT
    other = BOB if member == ALICE else ALICE
    assert team.get(f"/{ADDRESS}", member=other).status == download(team, member=other).status == 404
    # The fork report writes the private file and makes no shared copy, which the project would read.
    assert fork(team, as_=member).status == 200
    assert not (work / DOC).exists() and FORK in (work / client / project / "private" / owner / name).read_text()


# ── the /_/doc answer (10.5): the same work and can as the meta block ────────

def doc_answer(team, member=BOB, doc=ADDRESS):
    got = team.get(f"/_/doc?doc={doc}", member=member)
    assert got.status == 200, got.text
    return got.json()


def test_the_doc_answer_of_a_box_sheaf_keeps_box_tell_and_the_work(team, box):
    j = doc_answer(team)
    assert j["capabilities"] == ["box-tell"]
    assert j["work"] == meta(team)["work"]


def test_the_doc_answer_follows_a_fork_to_a_laptop(team, box, work):
    put(team, work, DOC, SHEAF.replace("host: agency-tiroir, member: james, date: 2026-10-28T05:12:03Z",
                                       "host: alice-laptop, member: alice, date: 2026-10-28T05:12:03Z"))
    j = doc_answer(team)
    assert j["capabilities"] == [] and j["work"]["live"] == "laptop"


def test_the_doc_answer_of_a_page_that_is_not_a_sheaf_has_no_work(team, box):
    j = doc_answer(team, doc="work/plan.md")
    assert j["capabilities"] == [] and "work" not in j


# ── review round 1 (Opus): the fork's write, the box, the loopback ───────────

def test_a_fork_cannot_name_the_box_as_its_machine(team, box, work):
    got = fork(team, machine="agency-tiroir")
    assert got.status == 400 and "box" in got.json()["error"]
    assert sessions_of(work)[0].startswith(f"{{id: {LIVE}, ")


def test_a_fork_on_a_sheaf_closed_after_the_gate_is_404_and_writes_nothing(team, box, work, monkeypatch):
    put(team, work, DOC, SHEAF.replace("sources: [issue:acme/agency-tiroir#8]", "sources: [library:doc-1]"))
    before = (work / DOC).read_text(encoding="utf-8")
    monkeypatch.setattr(team.hub, "visible", lambda member, address, **kw: True)     # the gate saw it open
    got = fork(team)
    assert got.status == 404 and (work / DOC).read_text(encoding="utf-8") == before
    assert hub_rows("session-forked") == []


def test_the_fork_line_keeps_every_other_line_ending():
    # with_session itself; the file's own read (source.update_file) reads universal newlines, as every save does.
    from sheafmd.hub import work
    mixed = SHEAF.replace("\n", "\r\n").replace("# What the contract says\r\n", "# What the contract says\n")
    after = work.with_session(mixed, "{NEW}", FORK)
    assert after == mixed.replace("sessions:\r\n", "sessions:\r\n  - {NEW}\r\n", 1)


def test_a_sessions_key_written_twice_is_409(team, box, work):
    put(team, work, DOC, SHEAF.replace("sources:", f"sessions:\n  - {{id: {OLDER}, host: x, member: y, "
                                                  f"date: 2026-10-01T00:00:00Z}}\nsources:"))
    before = (work / DOC).read_text(encoding="utf-8")
    got = fork(team)
    assert got.status == 409 and (work / DOC).read_text(encoding="utf-8") == before


def test_a_comment_after_the_key_is_kept_and_is_no_list(team, box, work):
    put(team, work, DOC, SHEAF.replace("sessions:\n", "sessions:  # newest first\n"))
    assert fork(team).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    assert "sessions:  # newest first\n" in text and sessions_of(work)[0].startswith(f"{{id: {FORK}, ")


def test_a_comment_line_naming_the_same_id_is_kept(team, box, work):
    note = f"  # - {{id: {OLDER}, host: agency-tiroir, member: james, date: 2026-10-26T08:00:00Z}} kept note\n"
    put(team, work, DOC, SHEAF.replace(f"  - {{id: {LAPTOP}", note + f"  - {{id: {LAPTOP}"))
    assert fork(team, id=OLDER).status == 200
    assert note in (work / DOC).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["&Co", "*star", "!tag", "|bar", ">gt", "%pc", "@at", "`tick", "- dash", "? q"])
def test_a_member_word_never_opens_with_a_yaml_indicator(name):
    from sheafmd.hub import work
    word = work.member_word(proxy.Member(BEA, name, ("/x",)))
    assert word[0] not in "&*!|>%@`-?" and word.strip() == word


def test_the_loopback_port_answers_404_not_405_for_a_member_route(team, box, browser):
    assert browser.get("/_/sessions").status == 404
    assert browser.post("/_/session", {"doc": ADDRESS}).status == 404


def test_a_members_save_cannot_write_a_front_matter_onto_a_sheaf(team, box, work):
    # The page cannot edit a front matter (5): a save of `---` paragraphs would list any transcript id as the
    # sheaf's box session, of another project or of a rectoverso the member cannot open. A line of dashes typed on
    # the page is written as its text, `\---` (ticket 137), so the save opens no front matter.
    from sheafmd.source import md_hash
    bare = put(team, work, "acme/tiroir/bare.md", "Hello world\n\nSecond para\n")
    before = (work / "acme/tiroir/bare.md").read_text(encoding="utf-8")
    html = (f"<p>---</p><p>sessions:</p><ul><li>{{id: {OLDER}, host: agency-tiroir, member: james, "
            f"date: 2026-10-28T05:12:03Z}}</li></ul><p>---</p>")
    got = team.post("/_/save", {"doc": bare, "hash": md_hash(before), "edits": [{"i": 0, "html": html}]},
                    member=BOB)
    after = (work / "acme/tiroir/bare.md").read_text(encoding="utf-8")
    assert got.status == 200 and after.startswith("\\---\n\nsessions:")
    assert download(team, doc=bare, id=OLDER).status == 404


def test_a_fork_on_a_file_with_a_bom_keeps_the_bom_first():
    from sheafmd.hub import work
    after = work.with_session("﻿# Title\n", "{NEW}", FORK)
    assert after == "﻿---\nsessions:\n  - {NEW}\n---\n# Title\n"


def test_a_window_name_tmux_or_a_shell_would_read_otherwise_gets_no_attach(team, box, work):
    put(team, work, "acme/site.v2/2026-10-28-a.md", SHEAF)      # tmux reads `.` as a pane
    assert "attach" not in meta(team, ALICE, doc="acme/site.v2/2026-10-28-a.md")["work"]


@pytest.mark.parametrize("rel", ["a_b/c", "a/b_c", "Acme/tiroir", "-a/b", "a/-b", "a/B"])
def test_a_part_james_would_not_name_a_window_for_gets_no_attach(team, box, work, rel):
    # James's SLUG is [a-z0-9][a-z0-9-]* (`project_window` in agency-tiroir): he makes no window for
    # another part, and a_b/c and a/b_c would name one window for two projects.
    doc = f"{rel}/2026-10-28-a.md"
    put(team, work, doc, SHEAF)
    assert "attach" not in meta(team, ALICE, doc=doc)["work"]


@pytest.mark.parametrize("rel, window", [("a-b/c", "a-b_c"), ("a--b/c", "a--b_c"), ("a/b--c", "a_b--c")])
def test_a_part_of_dashes_and_letters_gets_its_own_window(team, box, work, rel, window):
    doc = f"{rel}/2026-10-28-a.md"
    put(team, work, doc, SHEAF)
    assert meta(team, ALICE, doc=doc)["work"]["attach"].endswith(f"select-window -t ={window}")


# ── `sessions` is the hub's (9.12): no door write and no save sets it ─────────
@pytest.fixture
def james_token():
    from sheafmd.hub.state import Tokens
    return Tokens().add("james", write=True)


def door(browser, token, tool, text, doc=ADDRESS):
    """An assistant's door write through the hub: `update` of the text it read, or `create`."""
    from helpers import call
    if tool == "create":
        return call(browser, "create", token=token, doc=doc, text=text)
    is_error, got = call(browser, "read", token=token, doc=doc)
    assert not is_error, got
    return call(browser, "update", token=token, doc=doc, text=text(got["text"]), expected_hash=got["hash"])


A_BOX_ITEM = f"  - {{id: {FORK}, host: agency-tiroir, member: james, date: 2026-10-28T06:00:00Z}}\n"


@pytest.mark.parametrize("change", [
    lambda t: t.replace("sessions:\n", "sessions:\n" + A_BOX_ITEM),                      # adds a box item
    lambda t: t.replace(f"{OLDER}, host: agency-tiroir", f"{FORK}, host: agency-tiroir"),         # changes an id
    lambda t: "".join(line for line in t.splitlines(True) if LAPTOP not in line),         # drops an item
    lambda t: t.replace("sessions:\n", "").replace("  - {", "# - {"),                     # drops the key
], ids=["adds", "changes", "drops-an-item", "drops-the-key"])
def test_a_door_update_that_changes_sessions_is_refused_and_writes_nothing(team, box, browser, work, change, james_token):
    (box["sessions"] / FOLDER / f"{FORK}.jsonl").write_bytes(b'{"another":"project"}\n')
    before = (work / DOC).read_text(encoding="utf-8")
    is_error, said = door(browser, james_token, "update", lambda t: change(t) + "\nMore.\n")
    assert is_error and "sessions" in said
    assert (work / DOC).read_text(encoding="utf-8") == before
    assert download(team, id=FORK).status == 404


def test_a_door_update_that_keeps_sessions_as_read_is_written(team, box, browser, work, james_token):
    is_error, got = door(browser, james_token, "update", lambda t: t + "\nMore.\n")
    assert not is_error, got
    assert (work / DOC).read_text(encoding="utf-8").endswith("More.\n")
    assert LIVE in sessions_of(work)[0]


def test_a_door_create_cannot_list_a_session_but_may_write_an_empty_list(team, box, browser, work, james_token):
    head = "---\nclient: acme\nproject: tiroir\nassistant: James\n"
    new = "work/acme/tiroir/new.md"
    is_error, said = door(browser, james_token, "create", head + "sessions:\n" + A_BOX_ITEM + "---\n# New\n", doc=new)
    assert is_error and "sessions" in said and not (work / "acme/tiroir/new.md").exists()
    is_error, got = door(browser, james_token, "create", head + "sessions: []\n---\n# New\n", doc=new)
    assert not is_error, got


# ── the hub records James's session from its own Tell (9.12) ─────────
NEW = "abcdef01-2345-4678-89ab-cdef01234567"


def james_wrote(box, id, cwd=CWD, folder=FOLDER, at=None):
    """A transcript of James's in the box's copy, newer than the others unless `at` says when."""
    f = box["sessions"] / folder / f"{id}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"type": "summary", "summary": "x"}) + "\n"
                 + json.dumps({"type": "user", "cwd": cwd, "sessionId": id, "message": "hi"}) + "\n", encoding="utf-8")
    at = at or 2_000_000_000
    os.utime(f, (at, at))
    return f


@pytest.fixture
def at_work(team, box):
    """The box's list knows the folder James works in: `<work_dir>/<client>/<project>`."""
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__,
                                                                         "work_dir": "/home/james/work"}))
    return box


@pytest.mark.parametrize("tool", ["reply", "update"])
def test_james_s_door_write_records_his_session_as_the_live_one_and_keeps_the_others(team, browser, work, james_writes,
                                                                                    tool):
    cid = a_thread(team, work)
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    if tool == "reply":
        got = james_door(browser, james_writes, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")
    else:
        read = json.loads(james_door(browser, james_writes, "read", doc=ADDRESS)[1])
        got = james_door(browser, james_writes, "update", session=NEW, doc=ADDRESS, text=read["text"] + "\nMore.\n",
                         expected_hash=read["hash"])
    assert not got[0], got[1]
    first = sessions_of(work)[0]
    assert first.startswith(f"{{id: {NEW}, host: agency-tiroir, member: james, date: 20") and first.endswith("Z}")
    assert [s for s in sessions_of(work) if LIVE in s]          # the others stay, as written
    row, = hub_rows("session-recorded")
    assert (row["transcript"], row["by"]) == (NEW, "james")
    assert download(team).headers["X-Sheaf-Session"] == NEW


def test_a_session_of_the_same_folder_name_from_another_path_is_not_recorded(team, at_work, work):
    # Claude's folder name is lossy: /home/james/work/acme-tiroir lands in the same folder.
    james_wrote(at_work, NEW, cwd="/home/james/work/acme-tiroir")
    assert comment(team, work, "tell").status == 200
    assert LIVE in sessions_of(work)[0] and not [s for s in sessions_of(work) if NEW in s]
    assert hub_rows("session-recorded") == []


def test_a_transcript_whose_session_id_is_not_its_name_is_not_recorded(team, at_work, work):
    f = james_wrote(at_work, NEW)
    f.write_text(f.read_text(encoding="utf-8").replace(f'"sessionId": "{NEW}"', f'"sessionId": "{OLDER}"'),
                 encoding="utf-8")
    os.utime(f, (2_000_000_000, 2_000_000_000))
    assert comment(team, work, "tell").status == 200
    assert LIVE in sessions_of(work)[0] and not [s for s in sessions_of(work) if NEW in s]


def test_when_the_live_session_is_still_the_newest_the_file_keeps_its_front_matter(team, at_work, work):
    james_wrote(at_work, LIVE)
    head = (work / DOC).read_text(encoding="utf-8").split("---\n# ")[0]
    assert comment(team, work, "tell").status == 200
    assert (work / DOC).read_text(encoding="utf-8").split("---\n# ")[0] == head
    assert hub_rows("session-recorded") == []


def test_a_sheaf_of_james_with_no_session_yet_takes_tell_and_records_his_when_he_writes(team, browser, work,
                                                                                              james_writes):
    put(team, work, DOC, SHEAF.split("sessions:\n")[0] + "---\n# T\n\nA quote from the contract.\n")
    assert meta(team)["can"] == ["box-tell"]
    cid = a_thread(team, work)
    assert len(drops({"tell": team.hub.the_list.cfg.tell_dir})) == 1
    assert sessions_of(work) == []                              # James has not answered yet
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    assert not james_door(browser, james_writes, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert NEW in sessions_of(work)[0]


def test_a_sheaf_of_another_assistant_with_no_session_keeps_the_400(team, at_work, work):
    put(team, work, DOC, SHEAF.split("sessions:\n")[0].replace("assistant: James", "assistant: Mistral")
        + "---\n# T\n\nA quote from the contract.\n")
    assert comment(team, work, "tell").json()["error"] == proxy.PROXY_LINE


def test_without_work_dir_a_tell_drops_and_records_nothing(team, box, work):
    james_wrote(box, NEW)
    assert comment(team, work, "tell").status == 200 and len(drops(box)) == 1
    assert LIVE in sessions_of(work)[0]


def test_a_work_dir_that_is_not_absolute_stops_the_start(tmp_path):
    with pytest.raises(the_list.ListError, match="'work_dir' must be an absolute path"):
        listing(tmp_path, work_dir="home/james/work")
    assert str(listing(tmp_path, work_dir="/home/james/work/").work_dir) == "/home/james/work"


def test_the_recorded_session_is_committed_as_james_s_door_token(committing, browser, tmp_path, james_token):
    repo, team = committing
    sessions, tell = tmp_path / "copy", tmp_path / "tell"
    tell.mkdir()
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{
        **cfg.__dict__, "sessions_dir": sessions, "tell_dir": tell, "work_dir": the_list.Path("/home/james/work"),
        "james_tokens": ("james",)}))
    james_wrote({"sessions": sessions}, NEW)
    read = json.loads(james_door(browser, james_token, "read", doc=f"rectoversos/{DOC}")[1])
    got = james_door(browser, james_token, "update", session=NEW, doc=f"rectoversos/{DOC}",
                     text=read["text"] + "\nMore.\n", expected_hash=read["hash"])
    assert not got[0], got[1]
    team.hub.commits.settle()
    log = git(repo, "log", "--format=%an|%s").splitlines()
    assert f"james|session: {DOC}" in log, log
    assert f"{{id: {NEW}, host: agency-tiroir, member: james, " in git(repo, "show", f"HEAD:{DOC}")


# ── review round 3 (Codex) ───────────────────────────────────────────────────
ON_A_LAPTOP = SHEAF.replace("host: agency-tiroir, member: james, date: 2026-10-28T05:12:03Z",
                            "host: alice-laptop, member: alice, date: 2026-10-28T05:12:03Z")


def test_a_fork_that_lands_after_the_gate_keeps_the_tell_from_james(team, box, work, monkeypatch):
    # The gate read the box as live; a fork moved the session to a laptop before the comment took the lock.
    from sheafmd.hub import handler as handler_mod
    put(team, work, DOC, ON_A_LAPTOP)
    before = (work / DOC).read_text(encoding="utf-8")
    real = handler_mod.Handler._work_route
    seen = []

    def box_at_the_gate(self, address, text, member=None):
        seen.append(1)
        return "box" if len(seen) == 1 else real(self, address, text, member)
    monkeypatch.setattr(handler_mod.Handler, "_work_route", box_at_the_gate)
    got = comment(team, work, "tell")
    assert got.status == 400 and got.json()["error"] == proxy.PROXY_LINE
    assert (work / DOC).read_text(encoding="utf-8") == before and drops(box) == []


def test_a_fork_that_lands_while_the_hub_looks_for_james_session_stays_live(team, browser, work, james_writes,
                                                                          monkeypatch):
    from sheafmd.hub import work as work_mod
    cid = a_thread(team, work)
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    found = work_mod.james_has

    def a_fork_lands_meanwhile(cfg, project, id, member=None):
        (work / DOC).write_text(ON_A_LAPTOP, encoding="utf-8")
        return found(cfg, project, id, member)
    monkeypatch.setattr(work_mod, "james_has", a_fork_lands_meanwhile)
    assert not james_door(browser, james_writes, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert "alice-laptop" in sessions_of(work)[0] and not [s for s in sessions_of(work) if NEW in s]
    assert hub_rows("session-recorded") == []


def test_james_s_write_on_a_sheaf_of_another_assistant_records_none(team, browser, work, james_writes):
    put(team, work, DOC, SHEAF.replace("assistant: James", "assistant: Mistral"))
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    read = json.loads(james_door(browser, james_writes, "read", doc=ADDRESS)[1])
    assert not james_door(browser, james_writes, "update", session=NEW, doc=ADDRESS, text=read["text"] + "\nMore.\n",
                          expected_hash=read["hash"])[0]
    assert LIVE in sessions_of(work)[0] and hub_rows("session-recorded") == []


def test_an_empty_list_keeps_the_comment_on_its_key_line():
    from sheafmd.hub import work as work_mod
    text = "---\nclient: a\nsessions: [] # newest first\n---\n# T\n"
    assert work_mod.with_session(text, "{NEW}", FORK) == \
        "---\nclient: a\nsessions: # newest first\n  - {NEW}\n---\n# T\n"


# ── narrow check of round 3 (Codex, be22023): a rewrite cannot wake a line the reader skipped ────
HIDDEN = f"  - {{id: {FORK}, host: agency-tiroir, member: james, date: 2026-10-28T06:00:00Z}}\n"


def test_a_door_create_whose_rewrite_would_join_a_hidden_item_to_sessions_is_refused(team, box, browser, work,
                                                                                    james_token):
    (box["sessions"] / FOLDER / f"{FORK}.jsonl").write_bytes(b'{"another":"project"}\n')
    new = "work/acme/tiroir/new.md"
    text = ("---\nclient: acme\nproject: tiroir\nsources: [mail:t-1]\nsessions:\nshared: bogus\n"
            + HIDDEN + "---\n# New\n")
    is_error, said = door(browser, james_token, "create", text, doc=new)
    assert is_error and "sessions" in said and not (work / "acme/tiroir/new.md").exists()


# ── #36: the owner `_owned` gives cannot join an item to `sessions` either ─────────
OWNER_THEN_SESSIONS = "owner:\nsessions:\nowner: []\n" + HIDDEN     # the issue's own front matter


def test_a_door_create_whose_owner_rewrite_would_join_an_item_to_sessions_is_refused(team, box, browser, work,
                                                                                    james_token, tmp_path):
    team.hub.proxy = the_team(work, tmp_path, alices_tokens=["james"])     # so `_owned` gives it `owner: alice`
    (box["sessions"] / FOLDER / f"{FORK}.jsonl").write_bytes(b'{"another":"project"}\n')
    new = "work/acme/tiroir/new.md"
    text = "---\nclient: acme\nproject: tiroir\nsources: [mail:t-1]\n" + OWNER_THEN_SESSIONS + "---\n# New\n"
    is_error, said = door(browser, james_token, "create", text, doc=new)
    assert is_error and "sessions" in said and not (work / "acme/tiroir/new.md").exists()
    assert download(team, id=FORK).status == 404


def test_a_door_update_whose_owner_rewrite_would_join_an_item_to_sessions_is_refused(team, box, browser, work,
                                                                                    james_token, tmp_path):
    team.hub.proxy = the_team(work, tmp_path, alices_tokens=["james"])
    (box["sessions"] / FOLDER / f"{FORK}.jsonl").write_bytes(b'{"another":"project"}\n')
    new = "work/acme/tiroir/new.md"
    head = "---\nclient: acme\nproject: tiroir\n"
    is_error, got = door(browser, james_token, "create", head + "sources: [issue:x/y#1]\nsessions: []\n---\n# New\n",
                         doc=new)
    assert not is_error, got
    before = (work / "acme/tiroir/new.md").read_text(encoding="utf-8")
    closed = head + "sources: [mail:t-1]\n" + OWNER_THEN_SESSIONS + "---\n# New\n"
    is_error, said = door(browser, james_token, "update", lambda t: closed, doc=new)
    assert is_error and "sessions" in said
    assert (work / "acme/tiroir/new.md").read_text(encoding="utf-8") == before
    assert download(team, id=FORK).status == 404


def test_a_fork_onto_an_empty_list_does_not_wake_a_line_under_it():
    from sheafmd.hub import work as work_mod
    with pytest.raises(work_mod.NotRewritten):
        work_mod.with_session("---\nclient: a\nsessions: []\n" + HIDDEN + "---\n# T\n",
                              f"{{id: {NEW}, host: bob-mac, member: bob, date: 2026-10-28T06:00:00Z}}", NEW)


def test_a_project_folder_that_is_a_link_out_of_sessions_dir_is_not_looked_in(team, at_work, work, tmp_path):
    away = tmp_path / "away"
    james_wrote({"sessions": away}, NEW, folder="x")
    (at_work["sessions"] / FOLDER).rename(tmp_path / "moved")
    (at_work["sessions"] / FOLDER).symlink_to(away / "x")
    assert comment(team, work, "tell").status == 200
    assert not [s for s in sessions_of(work) if NEW in s]


def test_a_share_whose_rewrite_would_join_a_hidden_item_to_sessions_writes_nothing(team, box, work):
    from sheafmd.source import md_hash
    (box["sessions"] / FOLDER / f"{FORK}.jsonl").write_bytes(b'{"another":"project"}\n')
    text = ("---\nclient: acme\nproject: tiroir\nowner: alice\nsources: [library:doc-1]\nshared: old\n"
            "sessions:\nshared: other\n" + HIDDEN + "---\n# T\n\n- [ ] Share\n")
    put(team, work, DOC, text)
    n = [a[0] for a in the_list.read_rectoverso(DOC, text).actions].index("Share")
    got = team.post("/_/save", {"doc": ADDRESS, "hash": md_hash(text), "edits": [the_list.tick_edit(text, n, "Share")]},
                    member=ALICE)
    assert got.status != 200 and (work / DOC).read_text(encoding="utf-8") == text
    assert download(team, id=FORK, member=ALICE).status == 404


def test_the_hub_persons_share_on_the_loopback_port_is_written(team, box, browser, work):
    # Narrow check of 62a9324 (Codex): the Share check of `sessions` read a front matter only a member's save had.
    from sheafmd.source import md_hash
    text = SHEAF.replace("sources: [issue:acme/agency-tiroir#8]", "sources: [library:doc-1]") + "\n- [ ] Share\n"
    put(team, work, DOC, text)
    n = [a[0] for a in the_list.read_rectoverso(DOC, text).actions].index("Share")
    got = browser.post("/_/save", {"doc": ADDRESS, "hash": md_hash(text), "edits": [the_list.tick_edit(text, n, "Share")]})
    assert got.status == 200, got.text
    assert "visibility: project" in (work / DOC).read_text(encoding="utf-8")


# ── the fork without sessions_dir, work_dir "/" (9.12) ─────────────────────

def test_with_work_dir_the_filesystem_root_james_s_write_records_his_session(team, box, browser, work, tmp_path,
                                                                            james_token):
    # `work_dir = "/"` is accepted; James then works in /<client>/<project>, never //<client>/<project>.
    cfg = listing(tmp_path, work_dir="/")
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{
        **team.hub.the_list.cfg.__dict__, "work_dir": cfg.work_dir, "james_tokens": ("james",)}))
    james_wrote(box, NEW, cwd="/acme/tiroir", folder="-acme-tiroir")
    cid = a_thread(team, work)
    assert not james_door(browser, james_token, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert NEW in sessions_of(work)[0]
    row, = hub_rows("session-recorded")
    assert row["transcript"] == NEW


@pytest.mark.parametrize("key", ["sessions_dir", "work_dir"])
def test_without_sessions_dir_or_work_dir_a_box_sheaf_offers_no_fork(team, box, key):
    # The fork fetches the transcript from /_/session, which is a 404 without either (#146).
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, key: None}))
    w = meta(team)["work"]
    assert "fork" not in w and w["live"] == "box"


# ── the hub records James's session from his own door write (sweatshop-ai/sheaf#57) ─────────
# The door's `X-James-Session` names the session of the claude that writes, from its headersHelper; the hub takes it
# from `[list]`'s `james_token` alone, and only an id whose transcript is James's in that project's folder of the copy.


@pytest.fixture
def james_writes(team, at_work, james_token):
    """`[list]` names the token James's door writes with."""
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, "james_tokens": ("james",)}))
    return james_token


def james_door(browser, token, tool, session=None, **args):
    """(is_error, text) of one door call, with the session header when `session` is given."""
    from helpers import door as post, rpc
    headers = {"X-James-Session": session} if session is not None else {}
    res = post(browser, rpc("tools/call", {"name": tool, "arguments": args}), token=token, as_name=None,
               headers=headers)
    assert res.status == 200, res.text
    out = res.json()["result"]
    return out["isError"], out["content"][0]["text"]


def a_thread(team, work):
    got = comment(team, work, "tell")
    assert got.status == 200, got.text
    return got.json()["id"]


def test_james_s_door_reply_records_the_session_it_names_as_the_live_one(team, browser, work, james_writes):
    cid = a_thread(team, work)
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    is_error, said = james_door(browser, james_writes, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")
    assert not is_error, said
    first = sessions_of(work)[0]
    assert first.startswith(f"{{id: {NEW}, host: agency-tiroir, member: james, date: 20")
    row, = hub_rows("session-recorded")
    assert row["transcript"] == NEW


def test_a_tell_drop_no_longer_records_a_session(team, at_work, work):
    # the hub guessed at the drop, before James acted (agency-tiroir #136): only his own write names it now
    james_wrote(at_work, NEW)
    assert comment(team, work, "tell").status == 200
    assert LIVE in sessions_of(work)[0] and not [s for s in sessions_of(work) if NEW in s]
    assert hub_rows("session-recorded") == []


def test_a_door_write_without_the_header_records_nothing(team, browser, work, james_writes):
    cid = a_thread(team, work)
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    assert not james_door(browser, james_writes, "reply", doc=ADDRESS, id=cid, text="Sent.")[0]
    assert LIVE in sessions_of(work)[0]


def test_the_header_of_another_token_is_not_read(team, browser, work, james_writes):
    from sheafmd.hub.state import Tokens
    other = Tokens().add("mistral", write=True)
    cid = a_thread(team, work)
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    assert not james_door(browser, other, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert LIVE in sessions_of(work)[0]


@pytest.mark.parametrize("session", ["not-a-uuid", "ABCDEF01-2345-4678-89AB-CDEF01234567", ""])
def test_a_header_that_is_no_session_id_records_nothing_and_the_write_stands(team, browser, work, james_writes,
                                                                             session):
    cid = a_thread(team, work)
    is_error, said = james_door(browser, james_writes, "reply", session=session, doc=ADDRESS, id=cid, text="Sent.")
    assert not is_error, said
    assert LIVE in sessions_of(work)[0] and hub_rows("session-recorded") == []


def test_an_id_that_is_no_transcript_of_the_project_is_not_recorded_and_says_why(team, browser, work, james_writes):
    cid = a_thread(team, work)
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW, cwd="/home/james/work/acme-tiroir")
    assert not james_door(browser, james_writes, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert LIVE in sessions_of(work)[0]
    row, = hub_rows("session-not-recorded")
    assert row["transcript"] == NEW


def test_a_member_s_fork_stays_live_after_james_writes(team, browser, work, james_writes):
    cid = a_thread(team, work)
    assert fork(team).status == 200
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    assert not james_door(browser, james_writes, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert FORK in sessions_of(work)[0]


def test_an_id_the_copy_does_not_hold_yet_is_recorded_at_james_s_next_door_call(team, browser, work, james_writes):
    # his transcript reaches the copy about a minute after he writes
    cid = a_thread(team, work)
    assert not james_door(browser, james_writes, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert LIVE in sessions_of(work)[0]
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    assert not james_door(browser, james_writes, "read", session=NEW, doc=ADDRESS)[0]
    assert NEW in sessions_of(work)[0]


# ── Stop James clears the project's Tells that wait for his window (sweatshop-ai/sheaf#57) ────────


def test_a_drop_names_the_thread_it_came_from(team, box, work):
    got = comment(team, work, "tell")
    assert got.status == 200, got.text
    drop, = drops(box)
    assert json.loads(drop.read_text(encoding="utf-8"))["thread"] == got.json()["id"]


@pytest.fixture
def stoppable(team, box, work, tmp_path):
    """The box's list with a `stop_dir`, and the rectoverso holding a Stop James action."""
    stop = tmp_path / "stop"
    stop.mkdir()
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, "stop_dir": stop}))
    put(team, work, DOC, SHEAF + "\n- [ ] Stop James\n")
    return {**box, "stop": stop}


def stop_james(team, work, member=BOB):
    from sheafmd.source import md_hash
    text = (work / DOC).read_text(encoding="utf-8")
    n = [a[0] for a in the_list.read_rectoverso(DOC, text).actions].index("Stop James")
    return team.post("/_/save", {"doc": ADDRESS, "hash": md_hash(text),
                                 "edits": [the_list.tick_edit(text, n, "Stop James")]}, member=member)


def replies(team, cid):
    doc = team.get(f"/_/doc?doc={ADDRESS}", member=BOB).json()
    thread, = [c for c in doc["comments"] if c["id"] == cid]
    return thread["replies"]


def test_stop_james_removes_the_project_s_waiting_tells_and_says_so_in_each_thread(team, work, stoppable):
    first = comment(team, work, "tell", body="Send the draft.").json()["id"]
    second = comment(team, work, "tell", body="Which draft?").json()["id"]
    # named with the project's prefix, but another project's: only `project` tells them apart
    other = stoppable["tell"] / "acme--tiroir-x-20261029T200000Z"
    other.write_text(json.dumps({"project": "acme/tiroir-x", "member": "bob",
                                 "sheaf": "work/acme/tiroir-x/x.md", "text": "not this one", "kind": "tell",
                                 "thread": "c9"}), encoding="utf-8")
    assert len(drops(stoppable)) == 3
    assert stop_james(team, work).status == 200
    assert drops(stoppable) == [other]
    for cid in (first, second):
        said, = [r for r in replies(team, cid) if "Stopped before delivery" in r["text"]]
        assert said["by"] == "Bob"
    rows = hub_rows("tell-stopped")
    assert sorted(r["thread"] for r in rows) == sorted([first, second])
    assert all(r["project"] == "acme/tiroir" and r["by"] == "bob" for r in rows)
    assert "Send the draft" not in json.dumps(rows)
    assert [f.read_text(encoding="utf-8") for f in stoppable["stop"].iterdir()] == ["acme/tiroir\n"]


def test_a_waiting_tell_whose_thread_is_gone_is_still_removed_and_says_why(team, work, stoppable):
    cid = comment(team, work, "tell").json()["id"]
    drop, = drops(stoppable)
    body = json.loads(drop.read_text(encoding="utf-8"))
    drop.write_text(json.dumps({**body, "thread": "c999"}), encoding="utf-8")
    assert stop_james(team, work).status == 200
    assert drops(stoppable) == []
    row, = hub_rows("tell-stopped")
    assert row["thread"] == "c999" and row["said"] != "written"
    assert not [r for r in replies(team, cid) if "Stopped before delivery" in r["text"]]


# ── the gate's round 1 on PR 59 ─────────────────────────────────────────────


def test_without_a_box_in_the_list_james_s_write_records_nothing(team, browser, work, james_writes):
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, "box": ""}))
    put(team, work, DOC, SHEAF.split("sessions:\n")[0] + "---\n# T\n\nA quote from the contract.\n")
    james_wrote({"sessions": cfg.sessions_dir}, NEW)
    read = json.loads(james_door(browser, james_writes, "read", doc=ADDRESS)[1])
    assert not james_door(browser, james_writes, "update", session=NEW, doc=ADDRESS, text=read["text"] + "\nMore.\n",
                          expected_hash=read["hash"])[0]
    assert sessions_of(work) == [] and "host: ," not in (work / DOC).read_text(encoding="utf-8")
    assert hub_rows("session-recorded") == []


def test_an_id_the_copy_never_gets_says_so_once_it_has_waited_long_enough(team, browser, work, james_writes,
                                                                           monkeypatch):
    from sheafmd.hub import handler as handler_mod
    cid = a_thread(team, work)
    assert not james_door(browser, james_writes, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert hub_rows("session-not-recorded") == []
    monkeypatch.setattr(handler_mod, "PENDING_S", 0)
    assert not james_door(browser, james_writes, "read", session=NEW, doc=ADDRESS)[0]
    row, = hub_rows("session-not-recorded")
    assert row["transcript"] == NEW and "copy" in row["reason"]
    assert not james_door(browser, james_writes, "read", session=NEW, doc=ADDRESS)[0]
    assert len(hub_rows("session-not-recorded")) == 1                  # said once, then forgotten


def test_a_stop_whose_reply_fails_still_drops_the_stop_and_says_why(team, work, stoppable, monkeypatch):
    from sheafmd.hub import live
    comment(team, work, "tell")

    def a_failing_reply(self, op, *a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr(live.LiveDocument, "comment", a_failing_reply)
    assert stop_james(team, work).status == 200
    assert drops(stoppable) == []
    assert [f.read_text(encoding="utf-8") for f in stoppable["stop"].iterdir()] == ["acme/tiroir\n"]
    row, = hub_rows("tell-stopped")
    assert row["said"] == "not written: the hub failed on it (sheaf diag)"


def test_a_drop_file_written_with_kind_tell_is_still_read_and_recorded_as_a_tell(team, work, stoppable):
    # A file dropped before `BoxWaits` lost its kind, still in the box's folder when the hub restarts: written by
    # hand here, as the old hub wrote it, and read by Stop James for what it says.
    stoppable["tell"].joinpath("acme--tiroir-20261029T200000Z").write_text(json.dumps(
        {"project": "acme/tiroir", "member": "bob", "sheaf": ADDRESS, "text": "Send the draft.",
         "kind": "tell", "thread": "c1"}), encoding="utf-8")
    assert len(drops(stoppable)) == 1
    assert stop_james(team, work).status == 200
    assert drops(stoppable) == []
    row, = hub_rows("tell-stopped")
    assert row["thread"] == "c1" and row["what"] == "tell" and row["project"] == "acme/tiroir"


def test_a_waiting_tell_naming_a_sheaf_of_another_project_is_removed_with_no_reply_there(team, work, stoppable):
    elsewhere = put(team, work, "acme/site/x.md", SHEAF.replace("project: tiroir", "project: site"))
    stoppable["tell"].joinpath("acme--tiroir-20261029T200000Z").write_text(json.dumps(
        {"project": "acme/tiroir", "member": "bob", "sheaf": elsewhere, "text": "x", "kind": "tell",
         "thread": "c1"}), encoding="utf-8")
    before = (work / "acme/site/x.md").read_text(encoding="utf-8")
    assert stop_james(team, work).status == 200
    assert drops(stoppable) == []
    assert (work / "acme/site/x.md").read_text(encoding="utf-8") == before
    row, = hub_rows("tell-stopped")
    assert row["said"] == "the drop names a rectoverso of another root or project"


# ── the gate's round 2 on PR 59: the newest session James names wins ─────────────────────────
S1 = "11111111-aaaa-4aaa-8aaa-111111111111"
S2 = "22222222-bbbb-4bbb-8bbb-222222222222"


def test_an_older_waiting_session_never_replaces_a_newer_one_recorded_since(team, browser, work, james_writes):
    cid = a_thread(team, work)
    copy = {"sessions": team.hub.the_list.cfg.sessions_dir}
    assert not james_door(browser, james_writes, "reply", session=S1, doc=ADDRESS, id=cid, text="One.")[0]
    james_wrote(copy, S2)
    assert not james_door(browser, james_writes, "reply", session=S2, doc=ADDRESS, id=cid, text="Two.")[0]
    assert S2 in sessions_of(work)[0]
    james_wrote(copy, S1, at=1_900_000_000)
    assert not james_door(browser, james_writes, "read", session=S2, doc=ADDRESS)[0]
    assert S2 in sessions_of(work)[0]


def test_of_two_sessions_waiting_for_the_copy_the_newest_is_recorded(team, browser, work, james_writes):
    cid = a_thread(team, work)
    copy = {"sessions": team.hub.the_list.cfg.sessions_dir}
    assert not james_door(browser, james_writes, "reply", session=S1, doc=ADDRESS, id=cid, text="One.")[0]
    assert not james_door(browser, james_writes, "reply", session=S2, doc=ADDRESS, id=cid, text="Two.")[0]
    james_wrote(copy, S1, at=1_900_000_000)
    james_wrote(copy, S2)
    assert not james_door(browser, james_writes, "documents", session=S2)[0]
    assert S2 in sessions_of(work)[0] and not [s for s in sessions_of(work) if S1 in s]


def test_the_wait_of_a_session_that_keeps_writing_still_ends_after_its_time(team, browser, work, james_writes,
                                                                             monkeypatch):
    from sheafmd.hub import handler as handler_mod
    clock = [1000.0]
    monkeypatch.setattr(handler_mod, "_clock", lambda: clock[0])
    cid = a_thread(team, work)
    for t in (0, 200):
        clock[0] = 1000.0 + t
        assert not james_door(browser, james_writes, "reply", session=S1, doc=ADDRESS, id=cid, text=f"At {t}.")[0]
    assert hub_rows("session-not-recorded") == []
    clock[0] = 1000.0 + 400                             # 400 s since its first write, not 200 since its last
    assert not james_door(browser, james_writes, "reply", session=S1, doc=ADDRESS, id=cid, text="At 400.")[0]
    row, = hub_rows("session-not-recorded")
    assert row["transcript"] == S1


def test_a_sessions_list_the_hub_cannot_rewrite_says_so_once_not_at_every_later_call(team, browser, work,
                                                                                     james_writes):
    # gate round 3 on PR 59: the waiting entry goes with the row
    put(team, work, DOC, SHEAF.split("sessions:\n")[0] + f"sessions: [{{id: {LIVE}}}]\n---\n# T\n")
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    read = json.loads(james_door(browser, james_writes, "read", doc=ADDRESS)[1])
    assert not james_door(browser, james_writes, "update", session=NEW, doc=ADDRESS, text=read["text"] + "\nMore.\n",
                          expected_hash=read["hash"])[0]
    for _ in range(2):
        assert not james_door(browser, james_writes, "documents", session=NEW)[0]
    row, = hub_rows("session-not-recorded")
    assert row["transcript"] == NEW and "one item per line" in row["reason"]


# --- path traversal in the project and session ids (agency-tiroir #8, #9) -------------------------------------

def list_cfg(sessions_dir, work_dir):
    return the_list.ListConfig(root=the_list.Path("/"), repo="a/b", project=1, token_file=the_list.Path("/t"),
                               sessions_dir=sessions_dir, work_dir=the_list.Path(work_dir))


def _transcript(folder, cwd, id):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{id}.jsonl").write_text(json.dumps({"cwd": cwd, "sessionId": id}) + "\n", encoding="utf-8")


@pytest.mark.parametrize("project", ["../../outside", "../../outside/../outside", "/OUTSIDE"])
def test_james_has_with_a_project_that_climbs_never_reads_outside_sessions_dir(tmp_path, project):
    from types import SimpleNamespace
    sid, sessions, work_dir = str(uuid.uuid4()), tmp_path / "sessions", tmp_path / "work" / "james"
    sessions.mkdir()
    work_dir.mkdir(parents=True)
    project = project.replace("/OUTSIDE", str(tmp_path / "outside"))
    cfg = list_cfg(sessions, str(work_dir))
    # A transcript that matches if `<work_dir>/<project>` were opened as a path: the kernel would land in tmp_path/outside.
    _transcript(tmp_path / "outside", os.path.join(cfg.work_dir, project), sid)
    assert os.path.isdir(os.path.join(cfg.work_dir, project, ""))
    assert work_mod.james_has(cfg, project, sid) is None


def test_james_has_refuses_a_session_id_that_is_not_a_uuid(tmp_path):
    from types import SimpleNamespace
    sessions = tmp_path / "sessions"
    cfg = list_cfg(sessions, "/home/james/work")
    cwd = "/home/james/work/acme/tiroir"
    _transcript(sessions / re.sub(r"[^A-Za-z0-9]", "-", cwd), cwd, "x")
    for sid in ("../x", "x", "%2e%2e%2fx", "x\0", str(uuid.uuid4()) + "/../x"):
        assert work_mod.james_has(cfg, "acme/tiroir", sid) is False


def test_james_has_refuses_a_projects_folder_that_is_a_link(tmp_path):
    from types import SimpleNamespace
    sid, sessions = str(uuid.uuid4()), tmp_path / "sessions"
    sessions.mkdir()
    cwd = "/home/james/work/acme/tiroir"
    _transcript(tmp_path / "elsewhere", cwd, sid)
    (sessions / re.sub(r"[^A-Za-z0-9]", "-", cwd)).symlink_to(tmp_path / "elsewhere")
    cfg = list_cfg(sessions, "/home/james/work")
    assert work_mod.james_has(cfg, "acme/tiroir", sid) is False


def test_open_transcript_refuses_an_id_that_is_not_a_uuid(tmp_path):
    from types import SimpleNamespace
    (tmp_path / "s" / FOLDER).mkdir(parents=True)
    cfg = list_cfg(tmp_path / "s", "/home/james/work")
    # Each id below names one of these, a transcript of the project's as far as its first line goes, without the guard.
    for sid, planted in (("../../x", tmp_path / "x.jsonl"), ("../x", tmp_path / "s" / "x.jsonl"),
                         ("x", tmp_path / "s" / FOLDER / "x.jsonl")):
        planted.write_text(json.dumps({"cwd": CWD, "sessionId": sid}) + "\n", encoding="utf-8")
    for sid in ("../x", "../../x", "x", "%2e%2e%2fx", "x\0"):
        assert work_mod.open_transcript(cfg, "acme/tiroir", sid) is None


def test_a_drop_for_a_project_that_climbs_stays_in_its_folder(tmp_path):
    folder = tmp_path / "case" / "tell"
    folder.mkdir(parents=True)
    for project in ("../../outside", "acme/../../x", "/etc/passwd"):
        said, name = work_mod.drop_named(folder, project, b"{}", "missing")
        assert said == "written" and "/" not in name and (folder / name).is_file()
    assert [p.name for p in (tmp_path / "case").iterdir()] == ["tell"]


def test_a_drop_never_writes_through_a_link_planted_at_its_name(tmp_path, monkeypatch):
    import time as time_mod
    monkeypatch.setattr(time_mod, "gmtime", lambda *a: time_mod.struct_time((2026, 10, 31, 17, 0, 0, 5, 304, 0)))
    folder, target = tmp_path / "tell", tmp_path / "target"
    folder.mkdir()
    name = "acme--tiroir-20261031T170000Z"
    (folder / ("." + name)).symlink_to(target)            # dangling: exists() is False, O_EXCL refuses it
    (folder / name).symlink_to(target)
    said, wrote = work_mod.drop_named(folder, "acme/tiroir", b"{}", "missing")
    assert said == "written" and not target.exists()
    assert not (folder / wrote).is_symlink() and (folder / wrote).read_bytes() == b"{}"


# ── `[list]` names several door tokens: the header is read on each, only the named own one is James's ─────
def test_an_old_james_token_key_still_parses(tmp_path):
    assert listing(tmp_path, james_token="james").james_tokens == ("james",)
    assert listing(tmp_path).james_tokens == ()


def test_james_tokens_parse_as_a_list_and_stop_the_start_when_malformed(tmp_path):
    assert listing(tmp_path, james_tokens=["james", "james-shared"], own_james_token="james").james_tokens == ("james", "james-shared")
    for bad in ([], ["a", "a"], ["a", ""], ["a", 1], ["a/b"], [" james"]):
        with pytest.raises(the_list.ListError, match="'james_tokens' must be a list of different token names"):
            listing(tmp_path, james_tokens=bad)
    with pytest.raises(the_list.ListError, match="'james_tokens' must be a list"):
        listing(tmp_path, james_tokens="james")
    with pytest.raises(the_list.ListError, match="both in"):
        listing(tmp_path, james_token="james", james_tokens=["james"])


# ── the own-token rule (SPEC 9.12): one table, one test per row ─────────────────────────────────────────
def refused(tmp_path, match, **keys):
    with pytest.raises(the_list.ListError, match=match):
        listing(tmp_path, **keys)


def test_no_token_key_starts_as_today(tmp_path):
    cfg = listing(tmp_path)
    assert cfg.james_tokens == () and cfg.own_token == ""


def test_old_james_token_alone_is_own(tmp_path):
    assert listing(tmp_path, james_token="james").own_token == "james"


def test_own_james_token_with_the_old_key_stops_the_start(tmp_path):
    refused(tmp_path, "needs 'james_tokens'", james_token="james", own_james_token="james")


def test_a_single_token_is_the_own_one_without_the_key(tmp_path):
    assert listing(tmp_path, james_tokens=["james"]).own_token == "james"


def test_own_james_token_on_a_single_token_must_name_it(tmp_path):
    assert listing(tmp_path, james_tokens=["james"], own_james_token="james").own_token == "james"
    refused(tmp_path, "must name one of", james_tokens=["james"], own_james_token="other")


def test_list_order_does_not_pick_the_own_token(tmp_path):
    for names in (["james", "james-shared"], ["james-shared", "james"]):
        cfg = listing(tmp_path, james_tokens=names, own_james_token="james")
        assert cfg.own_token == "james"


def test_two_tokens_without_own_james_token_stop_the_start(tmp_path):
    refused(tmp_path, "'own_james_token' is needed", james_tokens=["james", "james-shared"])


def test_own_james_token_outside_the_list_stops_the_start(tmp_path):
    refused(tmp_path, "must name one of", james_tokens=["james", "james-shared"], own_james_token="mistral")


def test_both_token_keys_stop_the_start(tmp_path):
    for own in ({}, {"own_james_token": "james"}):
        refused(tmp_path, "both in", james_token="james", james_tokens=["james"], **own)


def test_own_james_token_without_any_token_list_stops_the_start(tmp_path):
    refused(tmp_path, "needs 'james_tokens'", own_james_token="james")


def test_an_empty_old_james_token_counts_as_absent(tmp_path):
    assert listing(tmp_path, james_token="").own_token == ""


def test_an_empty_old_james_token_beside_james_tokens_stops_the_start(tmp_path):
    refused(tmp_path, "both in", james_token="", james_tokens=["james"])


def test_an_empty_own_james_token_counts_as_absent(tmp_path):
    assert listing(tmp_path, own_james_token="").own_token == ""
    assert listing(tmp_path, james_token="james", own_james_token="").own_token == "james"


def test_an_empty_own_james_token_beside_one_token_is_absent(tmp_path):
    assert listing(tmp_path, james_tokens=["james"], own_james_token="").own_token == "james"


def test_an_empty_own_james_token_beside_two_tokens_stops_the_start(tmp_path):
    refused(tmp_path, "'own_james_token' is needed", james_tokens=["james", "james-shared"], own_james_token="")


def test_own_james_token_must_be_text(tmp_path):
    refused(tmp_path, "'own_james_token' must be text", james_tokens=["james"], own_james_token=1)


@pytest.fixture(params=[("james", "james-shared"), ("james-shared", "james")], ids=["own-first", "own-second"])
def two_james_tokens(request, team, at_work, browser):
    """`[list]` names an own and a shared door token; (own, shared, the callers the hub heard of)."""
    from sheafmd.hub.state import Tokens
    tokens = Tokens()
    own, shared = tokens.add("james", write=True), tokens.add("james-shared", write=True)
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{
        **cfg.__dict__, "james_tokens": request.param, "own_james_token": "james"}))
    heard, hook = [], browser.handler.door.called
    browser.handler.door.called = lambda caller, address: (heard.append(caller), hook(caller, address))
    return own, shared, heard


def test_session_header_read_on_both_tokens(team, browser, work, two_james_tokens):
    own, shared, heard = two_james_tokens
    cid = a_thread(team, work)
    for token in (own, shared):
        assert not james_door(browser, token, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert [c.session for c in heard] == [NEW, NEW]
    assert [c.own_session for c in heard] == [True, False]      # the same in either list order


def test_a_header_on_the_shared_token_never_resolves_an_own_session(team, browser, work, two_james_tokens):
    own, shared, heard = two_james_tokens
    cid = a_thread(team, work)
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)      # NEW is a transcript of the own copy
    assert not james_door(browser, shared, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert LIVE in sessions_of(work)[0] and not [s for s in sessions_of(work) if NEW in s]
    assert hub_rows("session-recorded") == [] and hub_rows("session-not-recorded") == []
    assert not james_door(browser, own, "reply", session=NEW, doc=ADDRESS, id=cid, text="Again.")[0]
    assert NEW in sessions_of(work)[0]


def test_a_token_outside_james_tokens_is_not_read(team, browser, work, two_james_tokens):
    from sheafmd.hub.state import Tokens
    other = Tokens().add("mistral", write=True)
    cid = a_thread(team, work)
    assert not james_door(browser, other, "reply", session=NEW, doc=ADDRESS, id=cid, text="Sent.")[0]
    assert two_james_tokens[2] == [] or two_james_tokens[2][0].session is None


def test_a_shared_call_leaves_the_own_token_s_waiting_session_alone(team, browser, work, two_james_tokens):
    own, shared, heard = two_james_tokens
    cid = a_thread(team, work)
    assert not james_door(browser, own, "reply", session=NEW, doc=ADDRESS, id=cid, text="One.")[0]   # NEW not in the copy yet
    assert LIVE in sessions_of(work)[0]
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    assert not james_door(browser, shared, "reply", session=NEW, doc=ADDRESS, id=cid, text="Two.")[0]
    assert LIVE in sessions_of(work)[0] and hub_rows("session-recorded") == []
    assert not james_door(browser, own, "reply", session=NEW, doc=ADDRESS, id=cid, text="Three.")[0]
    assert NEW in sessions_of(work)[0]


GENERATED = "Generated by builder. Edits are not kept; comment instead."


def generated(team):
    """Mark the rectoverso as a page a job generates (SPEC 8.3), as the door's `update` with `generated: true` does."""
    team.hub.docs.put(ADDRESS, {**team.hub.docs.get(ADDRESS),
                                "generated": {"by": "builder", "id": "tok1", "at": "2026-11-22T10:00:00+0100"}})


def test_a_fork_reported_on_a_generated_rectoverso_is_refused_and_writes_nothing(team, box, work):
    # The next rebuild would drop the session line without a word (ticket 156): refused at the hub, as a save is.
    generated(team)
    before = (work / DOC).read_text(encoding="utf-8")
    got = fork(team)
    assert got.status == 403 and GENERATED in got.text
    assert (work / DOC).read_text(encoding="utf-8") == before
    row = hub_rows("generated-refused")[-1]
    assert row["doc"] == ADDRESS and row["endpoint"] == "/_/sessions" and FORK not in str(row)


def test_a_fork_on_a_generated_rectoverso_that_is_also_read_only_is_refused_as_generated(team, box, work, monkeypatch):
    # 183 BE (AV for the fork): the page's own reason comes before the clone's, so the row is written.
    generated(team)
    monkeypatch.setattr(team.hub, "read_only_line", lambda address: "Read-only: set `save` in .sheaf.toml.")
    got = fork(team)
    assert got.status == 403 and GENERATED in got.text and ".sheaf.toml" not in got.text
    assert hub_rows("generated-refused")[-1]["endpoint"] == "/_/sessions"


def test_a_fork_on_a_rectoverso_marked_generated_after_the_first_look_is_refused_and_writes_nothing(team, box, work,
                                                                                                    monkeypatch):
    # 183 BE: a door write marks the page between the fork's first look and its write; the look under the file's lock
    # sees it (182 G for the fork).
    from helpers import marked_after_the_look
    marked_after_the_look(team.hub, monkeypatch, ADDRESS)
    before = (work / DOC).read_text(encoding="utf-8")
    got = fork(team)
    assert got.status == 403 and GENERATED in got.text
    assert (work / DOC).read_text(encoding="utf-8") == before
    assert hub_rows("generated-refused")[-1]["endpoint"] == "/_/sessions"


def test_james_s_session_on_a_generated_rectoverso_is_never_dropped_by_the_setter_s_next_update(team, browser, work,
                                                                                                 james_writes):
    # Ticket 156: the hub writes `sessions` into a generated rectoverso after its setter's door write (9.12). The
    # setter's next `update` cannot take the line out without a word: a door write that changes `sessions` is refused.
    james_wrote({"sessions": team.hub.the_list.cfg.sessions_dir}, NEW)
    read = json.loads(james_door(browser, james_writes, "read", doc=ADDRESS)[1])
    got = james_door(browser, james_writes, "update", session=NEW, doc=ADDRESS, text=read["text"] + "\nMore.\n",
                     expected_hash=read["hash"], generated=True)
    assert not got[0], got[1]
    assert json.loads(james_door(browser, james_writes, "read", doc=ADDRESS)[1])["generated"]
    assert NEW in sessions_of(work)[0]
    now = json.loads(james_door(browser, james_writes, "read", doc=ADDRESS)[1])
    is_error, said = james_door(browser, james_writes, "update", doc=ADDRESS, text=read["text"] + "\nRebuilt.\n",
                                expected_hash=now["hash"])
    assert is_error and "sessions" in said
    assert NEW in sessions_of(work)[0]
