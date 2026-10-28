"""Work on this (SPEC 9.12): a member downloads the transcript of a sheaf's box-hosted session, reports the
fork they made of it on their machine, and on a sheaf whose live session runs on the box sends Ask and Tell
to James's window by a file the hub drops. Through the handler in proxy mode, with the list's root as the
members' root: Thierry owns the sheaves, Hans is a member of the project, Bea is a member of another root."""
import os
import pwd

import pytest
from helpers import FRONT, Front, hub_rows

from sheafmd.hub import proxy, the_list

THIERRY = "503b2f77-83de-452c-817a-a357faf85929"
HANS = "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"
BEA = "9c1d2e3f-0000-4a51-8c0e-1f2a3b4c5d6e"
LIVE = "6f1c0e9a-2b3d-4c5e-8f70-1a2b3c4d5e6f"
OLDER = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
LAPTOP = "11111111-2222-4333-8444-555555555555"
DOC = "thinkingtoo/tiroir/2026-10-28-contract.md"
ADDRESS = f"work/{DOC}"
FOLDER = "-home-james-work-thinkingtoo-tiroir"

SHEAF = f"""---
client: thinkingtoo
project: tiroir
issue: thinkingtoo/tt-tiroir#8
assistant: James
owner: thierry
sources: [issue:thinkingtoo/tt-tiroir#8]
sessions:
  - {{id: {LIVE}, host: tiroir-tt, member: james, date: 2026-10-28T05:12:03Z}}
  - {{id: {LAPTOP}, host: thierry-laptop, member: thierry, date: 2026-10-27T09:00:00Z}}
  - {{id: {OLDER}, host: tiroir-tt, member: james, date: 2026-10-26T08:00:00Z}}
---
# What the contract says

A quote from the contract.
"""
TRANSCRIPT = b'{"type":"user","message":"hello"}\n{"type":"assistant","message":"hi"}\n'


@pytest.fixture
def team(hub, browser, work, plan, tmp_path):
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                             "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "members": {THIERRY: {"name": "Thierry", "short": "thierry", "roots": [str(work)],
                                                   "shell": True},
                                         HANS: {"name": "Hans", "short": "hans", "roots": [str(work)]},
                                         BEA: {"name": "Bea", "roots": [str(tmp_path / "other")]}}},
                            "the test")
    (tmp_path / "other").mkdir()
    (work / "projects.toml").write_text('[projects."thinkingtoo/tiroir"]\nmembers = ["thierry", "hans"]\n',
                                        encoding="utf-8")
    return Front(hub, browser.handler)


@pytest.fixture
def box(team, tmp_path, work):
    """The list on `work`, with the box's folders beside it: the transcripts' copy and the Tell drop."""
    sessions, tell = tmp_path / "sessions", tmp_path / "tell"
    (sessions / FOLDER).mkdir(parents=True)
    tell.mkdir()
    (sessions / FOLDER / f"{LIVE}.jsonl").write_bytes(TRANSCRIPT)
    (sessions / FOLDER / f"{OLDER}.jsonl").write_bytes(b'{"older":true}\n')
    cfg = the_list.parse({"root": str(work), "repo": "thinkingtoo/tt-tiroir", "project": 1,
                          "token_file": str(tmp_path / "token"), "sessions_dir": str(sessions),
                          "tell_dir": str(tell), "box": "tiroir-tt",
                          "attach": "ssh tiroir-tt -t tmux attach -t james \\; select-window -t {window}"},
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


def download(team, doc=ADDRESS, id=None, member=HANS):
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
    missing = download(team, doc="work/thinkingtoo/tiroir/nothing.md", member=HANS)
    assert got.status == missing.status == 404 and got.body == missing.body
    assert hub_rows("transcript-downloaded") == []


def test_on_an_owner_only_sheaf_only_its_owner_downloads(team, box, work):
    put(team, work, DOC, SHEAF.replace("sources: [issue:thinkingtoo/tt-tiroir#8]", "sources: [library:doc-1]"))
    got = download(team, member=HANS)
    assert got.status == 404 and got.json()["error"] == "no such document"
    assert download(team, member=THIERRY).body == TRANSCRIPT


def test_the_loopback_port_has_no_session_route(team, box, browser):
    assert browser.get(f"/_/session?doc={ADDRESS}").status == 404
    assert browser.post("/_/sessions", {"doc": ADDRESS, "id": LIVE, "machine": "x"}).status == 404


def test_a_document_outside_the_lists_root_or_not_at_project_depth_has_no_session(team, box, work):
    put(team, work, "thinkingtoo/2026-10-28-top.md", SHEAF)
    assert download(team, doc="work/thinkingtoo/2026-10-28-top.md").status == 404
    team.hub.the_list = None
    assert download(team).status == 404


# ── what the request may name (R11) ──────────────────────────────────────────

@pytest.fixture
def outside(tmp_path):
    """A transcript of the same id outside sessions_dir, which no request may reach."""
    f = tmp_path / "secret" / f"{LIVE}.jsonl"
    f.parent.mkdir()
    f.write_bytes(b'{"secret":true}\n')
    return f


@pytest.mark.parametrize("doc", [
    f"work/thinkingtoo/tiroir/../tiroir/{DOC.rsplit('/', 1)[1]}",
    f"work/thinkingtoo/tiroir/%2e%2e/tiroir/{DOC.rsplit('/', 1)[1]}",
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


def test_an_older_box_session_is_served_by_its_id(team, box):
    got = download(team, id=OLDER)
    assert got.status == 200 and got.body == b'{"older":true}\n' and got.headers["X-Sheaf-Session"] == OLDER


def test_a_transcript_that_is_a_link_out_of_sessions_dir_is_refused(team, box, outside):
    f = box["sessions"] / FOLDER / f"{LIVE}.jsonl"
    f.unlink()
    f.symlink_to(outside)
    assert download(team).status == 404


def test_a_folder_that_is_a_link_out_of_sessions_dir_is_refused(team, box, outside):
    (box["sessions"] / FOLDER / f"{LIVE}.jsonl").unlink()
    (box["sessions"] / "-elsewhere").symlink_to(outside.parent)
    assert download(team).status == 404


def test_without_sessions_dir_or_box_there_is_no_transcript(team, box, tmp_path, work):
    cfg = team.hub.the_list.cfg
    for change in ({"sessions_dir": None}, {"box": ""}):
        team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, **change}))
        assert download(team).status == 404


def test_a_session_item_that_does_not_parse_is_skipped(team, box, work):
    bad = SHEAF.replace(f"{{id: {LIVE}, host: tiroir-tt, member: james, date: 2026-10-28T05:12:03Z}}",
                        f"{{id: {LIVE}, host: tiroir-tt, member: james, date: yesterday}}")
    put(team, work, DOC, bad)
    got = download(team)
    assert got.status == 200 and got.headers["X-Sheaf-Session"] == OLDER


def test_a_download_writes_its_row(team, box):
    download(team)
    row, = hub_rows("transcript-downloaded")
    assert (row["doc"], row["transcript"], row["by"], row["issue"]) == (ADDRESS, LIVE, "hans", "thinkingtoo/tt-tiroir#8")


# ── config ───────────────────────────────────────────────────────────────────

def members(**extra):
    return {"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock", "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
            "members": {HANS: {"name": "Hans", "roots": ["/srv/work"], **extra}}}


def test_shell_is_false_unless_the_member_block_says_true():
    assert proxy.parse(members(), "t").members[HANS].shell is False
    assert proxy.parse(members(shell=True), "t").members[HANS].shell is True
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


@pytest.mark.parametrize("value", ["", "tiroir_tt", "a" * 64, "tiroir tt"])
def test_a_box_that_is_not_a_host_name_stops_the_start(tmp_path, value):
    with pytest.raises(the_list.ListError, match="'box' must be a host name"):
        listing(tmp_path, box=value)


def test_an_attach_of_two_lines_stops_the_start(tmp_path):
    with pytest.raises(the_list.ListError, match="'attach' must be one line"):
        listing(tmp_path, attach="ssh box\nrm -rf /")
    assert listing(tmp_path, box="tiroir-tt", attach="ssh {window}").attach == "ssh {window}"
