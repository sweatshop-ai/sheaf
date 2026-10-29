"""The sign-in code (SPEC 9.13, tt-tiroir#60): a member asks for a code in a sheaf's Work on this, and the laptop
client spends it on the two routes of 9.12, the transcript and the fork, for that one sheaf, once each, in order,
within 10 minutes. The verifier hands the hub the code's sha256 as `X-Sheaf-Code` and no member header; the hub
alone knows whose it is. Through the handler in proxy mode, on the fixtures of test_hub_work.py."""
import hashlib
import os
import re
import stat

import pytest
from helpers import hub_rows
from test_hub_work import (ADDRESS, BEA, DOC, FORK, HANS, LAPTOP, LIVE, OLDER, SHEAF, THIERRY, TRANSCRIPT,  # noqa: F401
                           box, put, sessions_of, team)

from sheafmd.hub import codes as codes_mod
from sheafmd.hub import the_list
from sheafmd.hub import work as work_mod

NO_GOOD = "This sign-in code is no good: get a new one from Work on this."
NOT_OPEN = "This sheaf is not open to you with this code: get a code from this sheaf's Work on this."
OTHER = "thinkingtoo/tiroir/2026-10-29-other.md"


def issue(team, member=HANS, doc=ADDRESS, **kw):
    return team.post("/_/code", {"doc": doc}, member=member, **kw)


def code_of(team, member=HANS, doc=ADDRESS):
    got = issue(team, member, doc)
    assert got.status == 200, got.text
    return got.json()["code"]


def hashed(code):
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def with_code(team, method, path, code, body=None, **kw):
    """A request as Caddy sends it after the verifier took a code: `X-Sheaf-Code` and no `X-Sheaf-Member`."""
    h = {"X-Sheaf-Code": hashed(code) if code.startswith("sheaf_code_") else code, **kw.pop("headers", {})}
    if method == "GET":
        return team.get(path, member=None, headers=h, **kw)
    return team.post(path, body if body is not None else {}, member=None, headers=h, **kw)


def fetch(team, code, doc=ADDRESS, extra=""):
    return with_code(team, "GET", f"/_/session?doc={doc}{extra}", code)


def report(team, code, doc=ADDRESS, id=FORK, machine="hans-mac", **kw):
    return with_code(team, "POST", "/_/sessions", code, {"doc": doc, "id": id, "machine": machine}, **kw)


# ── asking for a code ─────────────────────────────────────────────────────────

def test_a_member_gets_a_code_of_the_right_shape_and_its_expiry(team, box):
    got = issue(team)
    assert got.status == 200, got.text
    j = got.json()
    assert re.fullmatch(r"sheaf_code_[A-Za-z0-9_-]{43}", j["code"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", j["expires"])
    assert re.fullmatch(r"[0-9a-f]{8}", j["id"])
    assert got.headers["Cache-Control"] == "no-store"


def test_two_codes_are_never_the_same(team, box):
    assert code_of(team) != code_of(team)


def test_a_code_is_asked_for_with_the_fronts_origin_only(team, box):
    assert issue(team, origin="https://evil.example").status == 403
    assert issue(team, origin=False).status == 403


def test_a_get_mints_nothing(team, box):
    assert team.get(f"/_/code?doc={ADDRESS}", member=HANS).status == 405


def test_no_code_for_a_sheaf_the_member_may_not_open(team, box):
    assert issue(team, member=BEA).status == 404


def test_no_code_for_a_page_that_is_not_a_sheaf(team, box, work):
    put(team, work, "thinkingtoo/notes.md", "# Notes\n")
    assert issue(team, doc="work/thinkingtoo/notes.md").status == 404


def test_no_code_while_the_live_session_runs_on_a_laptop(team, box, work):
    put(team, work, DOC, SHEAF.replace(f"  - {{id: {LIVE}", "  - {id: " + LAPTOP + ", host: hans-mac, member: hans, "
                                       "date: 2026-10-29T09:00:00Z}\n  - {id: " + LIVE, 1))
    assert issue(team).status == 404


def test_no_code_without_a_copy_of_the_boxs_transcripts(team, box):
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, "sessions_dir": None}))
    assert issue(team).status == 404


def test_the_twenty_first_code_in_an_hour_is_refused(team, box):
    for _ in range(20):
        assert issue(team).status == 200
    got = issue(team)
    assert got.status == 429
    assert got.json()["error"] == "Too many sign-in codes: wait a few minutes."
    assert issue(team, member=THIERRY).status == 200           # the cap is each member's own


def test_the_cap_is_a_rolling_hour(team, box, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(codes_mod, "_clock", lambda: now[0])
    for _ in range(20):
        assert issue(team).status == 200
    now[0] += 3599
    assert issue(team).status == 429
    now[0] += 2
    assert issue(team).status == 200


def test_issuing_writes_a_row_with_the_code_id_never_the_code(team, box):
    j = issue(team).json()
    row, = hub_rows("code-issued")
    assert (row["by"], row["doc"], row["code"], row["expires"], row["via"]) == ("hans", ADDRESS, j["id"], j["expires"],
                                                                                "popover")
    text = repr(hub_rows())
    assert j["code"] not in text and hashed(j["code"]) not in text


def test_a_code_cannot_mint_a_code(team, box):
    code = code_of(team)
    assert with_code(team, "POST", "/_/code", code, {"doc": ADDRESS}).status == 404


# ── the bootstrap on the box: the loopback port with the key ─────────────────

def test_the_key_mints_a_code_for_a_named_member(team, box, browser):
    got = browser.request("POST", "/_/code", body={"doc": ADDRESS, "member": HANS}, key=True, cookie=False)
    assert got.status == 200, got.text
    assert hub_rows("code-issued")[-1]["via"] == "cli"
    assert fetch(team, got.json()["code"]).status == 200


def test_the_key_mints_nothing_for_a_member_who_may_not_open_the_sheaf(team, box, browser):
    got = browser.request("POST", "/_/code", body={"doc": ADDRESS, "member": BEA}, key=True, cookie=False)
    assert got.status == 404


def test_the_key_mints_nothing_for_someone_who_is_no_member(team, box, browser):
    got = browser.request("POST", "/_/code", body={"doc": ADDRESS, "member": "nobody"}, key=True, cookie=False)
    assert got.status == 404


def test_the_hubs_own_cookie_mints_nothing(team, box, browser):
    got = browser.request("POST", "/_/code", body={"doc": ADDRESS, "member": HANS}, key=False, cookie=True)
    assert got.status == 403


# ── the transcript, with a code ───────────────────────────────────────────────

def test_a_code_downloads_the_live_box_session_once(team, box):
    code = code_of(team)
    got = fetch(team, code)
    assert got.status == 200, got.text
    assert got.body == TRANSCRIPT
    assert got.headers["X-Sheaf-Session"] == LIVE
    again = fetch(team, code)
    assert again.status == 401 and again.json()["error"] == NO_GOOD


def test_a_download_with_a_code_says_so_in_its_row(team, box):
    code = code_of(team)
    cid = hub_rows("code-issued")[-1]["code"]
    fetch(team, code)
    row = hub_rows("transcript-downloaded")[-1]
    assert (row["via"], row["code"], row["by"], row["member"]) == ("code", cid, "hans", HANS)
    assert hub_rows("code-used")[-1]["route"] == "session"


def test_a_code_takes_no_id(team, box):
    assert fetch(team, code_of(team), extra=f"&id={OLDER}").status == 400


def test_a_code_works_on_its_own_sheaf_only(team, box, work):
    other = put(team, work, OTHER, SHEAF)
    code = code_of(team)
    got = fetch(team, code, doc=other)
    assert got.status == 404 and got.json()["error"] == NOT_OPEN
    assert hub_rows("code-refused")[-1]["reason"] == "doc"


@pytest.mark.parametrize("path", ["/_/doc?doc=" + ADDRESS, "/_/index.json", "/" + ADDRESS, "/_/live"])
def test_a_code_opens_no_other_route(team, box, path):
    got = with_code(team, "GET", path, code_of(team))
    assert got.status == 404
    assert hub_rows("code-refused")[-1]["reason"] == "route"


def test_a_code_saves_comments_and_ticks_nothing(team, box):
    for path in ("/_/save", "/_/comment", "/_/tick", "/_/seen"):
        assert with_code(team, "POST", path, code_of(team), {"doc": ADDRESS}).status == 404


@pytest.mark.parametrize("value", ["", "zz", "a" * 64, hashlib.sha256(b"made up").hexdigest()])
def test_a_hash_the_hub_does_not_hold_gets_the_one_sentence(team, box, value):
    got = with_code(team, "GET", f"/_/session?doc={ADDRESS}", value)
    assert got.status == 401 and got.json()["error"] == NO_GOOD


def test_a_code_with_a_member_header_too_is_refused(team, box):
    code = code_of(team)
    got = team.get(f"/_/session?doc={ADDRESS}", member=HANS, headers={"X-Sheaf-Code": hashed(code)})
    assert got.status == 401
    assert hub_rows("code-refused")[-1]["reason"] == "two-credentials"
    assert fetch(team, code).status == 200                   # the refusal did not spend it


def test_a_code_past_its_ten_minutes_is_no_good(team, box, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(codes_mod, "_clock", lambda: now[0])
    code = code_of(team)
    now[0] += 600
    got = fetch(team, code)
    assert got.status == 401 and got.json()["error"] == NO_GOOD
    assert hub_rows("code-refused")[-1]["reason"] == "expired"


def test_a_code_within_its_ten_minutes_works(team, box, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(codes_mod, "_clock", lambda: now[0])
    code = code_of(team)
    now[0] += 599
    assert fetch(team, code).status == 200


def test_a_code_of_a_member_taken_out_of_the_members_is_no_good(team, box):
    code = code_of(team)
    team.hub.proxy.members.pop(HANS)
    got = fetch(team, code)
    assert got.status == 401 and got.json()["error"] == NO_GOOD
    assert hub_rows("code-refused")[-1]["reason"] == "member"


def test_a_code_acts_as_its_member_on_visibility(team, box, work):
    """A code of Hans's on a sheaf that is since Thierry's alone is refused as Hans's request is."""
    code = code_of(team)
    put(team, work, DOC, SHEAF.replace("sources: [issue:thinkingtoo/tt-tiroir#8]", "sources: [library:doc-1]"))
    assert fetch(team, code).status == 404


# ── the code serves the session it was made for, while it is the forkable one ──

def live_now(team, work, sid, host="tiroir-tt", member="james"):
    put(team, work, DOC, SHEAF.replace(f"  - {{id: {LIVE}", f"  - {{id: {sid}, host: {host}, member: {member}, "
                                       f"date: 2026-10-29T10:00:00Z}}\n  - {{id: {LIVE}", 1))


def test_a_newer_box_session_needs_a_new_code(team, box, work):
    code = code_of(team)
    (box["sessions"] / "-home-james-work-thinkingtoo-tiroir" / f"{FORK}.jsonl").write_bytes(b"{}\n")
    live_now(team, work, FORK)
    got = fetch(team, code)
    assert got.status == 404 and got.json()["error"] == NOT_OPEN
    assert hub_rows("code-refused")[-1]["reason"] == "moved"
    live_now(team, work, LIVE)                      # even back as it was: the code is spent
    assert fetch(team, code).status == 401


def test_a_fork_reported_meanwhile_ends_the_codes_download(team, box, work):
    code = code_of(team)
    live_now(team, work, FORK, host="thierry-laptop", member="thierry")
    assert fetch(team, code).status == 404


def test_the_post_refuses_a_code_whose_session_is_no_longer_the_forkable_one(team, box, work):
    code = code_of(team)
    assert fetch(team, code).status == 200
    live_now(team, work, LAPTOP, host="thierry-laptop", member="thierry")
    got = report(team, code)
    assert got.status == 404 and got.json()["error"] == NOT_OPEN
    assert sessions_of(work)[0].startswith(f"{{id: {LAPTOP}")


def test_one_function_judges_mint_get_and_post(team, box):
    st = work_mod.state(team.hub, ADDRESS, SHEAF)
    assert work_mod.code_session(st) == LIVE
    assert work_mod.code_session(st, LIVE) == LIVE
    assert work_mod.code_session(st, OLDER) is None
    assert work_mod.code_session(None) is None


# ── the fork, with a code ─────────────────────────────────────────────────────

def test_a_code_records_one_fork_after_its_download(team, box, work):
    code = code_of(team)
    assert fetch(team, code).status == 200
    got = report(team, code)
    assert got.status == 200, got.text
    assert sessions_of(work)[0].startswith(f"{{id: {FORK}, host: hans-mac, member: hans, ")
    row = hub_rows("session-forked")[-1]
    assert (row["via"], row["by"]) == ("code", "hans")
    assert hub_rows("code-used")[-1]["route"] == "sessions"
    again = report(team, code, id="8e8f9a0b-1c2d-4e3f-8a4b-5c6d7e8f9a0b")
    assert again.status == 401 and again.json()["error"] == NO_GOOD


def test_a_post_before_the_download_is_refused_and_ends_the_code(team, box, work):
    code = code_of(team)
    got = report(team, code)
    assert got.status == 401 and got.json()["error"] == NO_GOOD
    assert hub_rows("code-refused")[-1]["reason"] == "order"
    assert fetch(team, code).status == 401
    assert not sessions_of(work)[0].startswith(f"{{id: {FORK}")


def test_a_post_with_an_id_already_listed_is_409_and_ends_the_code(team, box, work):
    code = code_of(team)
    fetch(team, code)
    before = (work / DOC).read_text(encoding="utf-8")
    got = report(team, code, id=OLDER)
    assert got.status == 409 and got.json()["error"] == "That session is already listed on this sheaf"
    assert (work / DOC).read_text(encoding="utf-8") == before
    assert report(team, code).status == 401


def test_a_post_of_another_shape_ends_the_code(team, box, work):
    code = code_of(team)
    fetch(team, code)
    assert report(team, code, machine="tiroir-tt").status == 400
    assert report(team, code).status == 401


def test_a_post_for_another_sheaf_is_404_and_ends_the_code(team, box, work):
    other = put(team, work, OTHER, SHEAF)
    code = code_of(team)
    fetch(team, code)
    assert report(team, code, doc=other).status == 404
    assert report(team, code).status == 401


def test_a_post_with_a_code_still_needs_the_fronts_origin(team, box, work):
    code = code_of(team)
    fetch(team, code)
    assert report(team, code, origin="https://evil.example").status == 403
    assert report(team, code).status == 401


def test_the_fork_is_named_after_the_codes_member_whatever_the_body_says(team, box, work):
    code = code_of(team)
    fetch(team, code)
    got = with_code(team, "POST", "/_/sessions", code, {"doc": ADDRESS, "id": FORK, "machine": "m",
                                                         "member": THIERRY, "by": "thierry"})
    assert got.status == 200
    assert sessions_of(work)[0].startswith(f"{{id: {FORK}, host: m, member: hans, ")


# ── what is never written ─────────────────────────────────────────────────────

def test_neither_the_code_nor_its_hash_is_in_any_row(team, box, work):
    code = code_of(team)
    fetch(team, code)
    fetch(team, code)
    report(team, code)
    with_code(team, "GET", "/_/index.json", code)
    text = repr(hub_rows())
    assert code not in text and hashed(code) not in text and "sheaf_code_" not in text


def test_unknown_codes_are_counted_one_row_a_minute(team, box, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(codes_mod, "_clock", lambda: now[0])
    for n in range(50):
        with_code(team, "GET", f"/_/session?doc={ADDRESS}", hashlib.sha256(str(n).encode()).hexdigest())
    rows = [r for r in hub_rows("code-refused") if r["reason"] == "unknown"]
    assert len(rows) == 1 and rows[0]["count"] == 1
    now[0] += 61
    with_code(team, "GET", f"/_/session?doc={ADDRESS}", "f" * 64)
    rows = [r for r in hub_rows("code-refused") if r["reason"] == "unknown"]
    assert len(rows) == 2 and rows[1]["count"] == 50
    assert not hub_rows("session-401")


def test_a_restart_drops_every_code(team, box):
    from sheafmd.hub.handler import Handler
    code = code_of(team)
    team.handler = Handler(team.hub, peer_check=lambda conn: None)
    assert fetch(team, code).status == 401


def test_the_hub_never_writes_a_code_to_disk(team, box, tmp_path):
    code = code_of(team)
    for root, _, files in os.walk(tmp_path):
        for f in files:
            p = os.path.join(root, f)
            if stat.S_ISREG(os.lstat(p).st_mode):
                with open(p, "rb") as fh:
                    data = fh.read()
                assert code.encode() not in data and hashed(code).encode() not in data, p
