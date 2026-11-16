"""Team comments on the agency hub (SPEC 9.11): a verso of the agency's own, kept in the hub's state folder and keyed by
the page's address, never in the client's file and never sent to the client tiroir. The store, and the view and API a
member reaches it by, with the gate that says who may open the page standing in for the read-through (a later ticket)."""
import json
import os
import stat
import threading

import pytest
from helpers import BEA, CAL
from test_hub_commits import DOC, box, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents  # noqa: F401  (fixture)

from sheafmd.hub import team
from sheafmd.hub.live import NotAuthor

ADDR = "Clients/acme/work/a.md"
MARK = "TEAM-MARKER-7f3a"


@pytest.fixture
def store(tmp_path):
    return team.TeamComments(tmp_path / "team-comments.json")


# ── the store ────────────────────────────────────────────────────────────────

def test_an_added_comment_gets_a_t_id_and_is_listed_with_its_quote_and_body(store):
    c = store.add(ADDR, "Alice", "the quote", f"{MARK} body", "h1", "2026-11-16T10:00")
    assert c["id"] == "t1" and c["by"] == "Alice" and c["status"] == "open"
    assert store.add(ADDR, "Bob", "q", "b", "h1", "2026-11-16T10:01")["id"] == "t2"
    [first, second] = store.list(ADDR)
    assert (first["quote"], first["body"], first["replies"]) == ("the quote", f"{MARK} body", [])
    assert second["id"] == "t2"


def test_comments_are_kept_apart_by_address(store):
    store.add(ADDR, "Alice", "q", "b", "h", "t")
    assert store.list("Clients/acme/work/other.md") == []


def test_the_file_is_private_and_survives_a_new_store_on_the_same_path(store, tmp_path):
    store.add(ADDR, "Alice", "q", f"{MARK}", "h", "t")
    assert stat.S_IMODE(os.stat(tmp_path / "team-comments.json").st_mode) == 0o600
    again = team.TeamComments(tmp_path / "team-comments.json")
    assert [c["body"] for c in again.list(ADDR)] == [MARK]


def test_a_reply_a_status_an_edit_and_a_delete(store):
    store.add(ADDR, "Alice", "q", "first", "h", "t")
    store.reply(ADDR, "t1", "Bob", "answer", "t2")
    store.status(ADDR, "t1", "resolved")
    store.edit(ADDR, "t1", "Alice", "changed")
    [c] = store.list(ADDR)
    assert (c["status"], c["body"]) == ("resolved", "changed")
    assert [(r["by"], r["text"]) for r in c["replies"]] == [("Bob", "answer")]


def test_only_the_author_edits_a_comment_and_only_deletes_one_no_one_else_replied_to(store):
    store.add(ADDR, "Alice", "q", "mine", "h", "t")
    with pytest.raises(NotAuthor):
        store.edit(ADDR, "t1", "Bob", "x")
    with pytest.raises(NotAuthor):
        store.delete(ADDR, "t1", "Bob")
    store.reply(ADDR, "t1", "Bob", "r", "t")
    with pytest.raises(NotAuthor):
        store.delete(ADDR, "t1", "Alice")
    assert store.list(ADDR)[0]["body"] == "mine"
    store.add(ADDR, "Alice", "q", "alone", "h", "t")
    store.delete(ADDR, "t2", "Alice")
    assert [c["id"] for c in store.list(ADDR)] == ["t1"]


def test_an_id_that_is_not_there_is_a_missing_comment(store):
    for call in (lambda: store.reply(ADDR, "t9", "A", "x", "t"), lambda: store.status(ADDR, "t9", "open"),
                 lambda: store.edit(ADDR, "t9", "A", "x"), lambda: store.delete(ADDR, "t9", "A")):
        with pytest.raises(team.NoComment):
            call()


def test_a_status_other_than_open_or_resolved_is_refused(store):
    store.add(ADDR, "Alice", "q", "b", "h", "t")
    with pytest.raises(ValueError):
        store.status(ADDR, "t1", "closed")


def test_text_that_looks_like_comment_markup_is_kept_exactly_as_typed(store):
    body = "ends --> here <!-- sheaf-comment id=c9 -->"
    store.add(ADDR, "Alice", body, body, "h", "t")
    assert store.list(ADDR)[0]["body"] == body and store.list(ADDR)[0]["quote"] == body


def test_a_file_that_is_not_json_is_set_aside_and_the_store_starts_empty(tmp_path):
    path = tmp_path / "team-comments.json"
    path.write_text("not json", encoding="utf-8")
    assert team.TeamComments(path).list(ADDR) == []
    assert (tmp_path / "team-comments.json.corrupt").exists()


def test_two_threads_adding_at_once_both_land_with_different_ids(store):
    ids = []
    ts = [threading.Thread(target=lambda: ids.append(store.add(ADDR, "A", "q", "b", "h", "t")["id"])) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(ids) == sorted({f"t{n}" for n in range(1, 9)})


# ── the view and the API on the hub ──────────────────────────────────────────

def post(agents, body, member=BEA):
    return agents.post("/_/team", body, member=member)


def opens(allowed):
    """A gate that says who may open which page: `allowed` is a set of (member id, address)."""
    return lambda member, address: (member.id, address) in allowed


def enabled(agents, tmp_path, allowed=None):
    agents.hub.enable_team(tmp_path / "team-comments.json",
                           opens(allowed if allowed is not None else {(BEA, ADDR), (CAL, ADDR)}))
    return agents


def test_a_hub_with_no_team_store_answers_the_routes_as_a_page_that_is_not_there(agents):
    assert agents.hub.team is None
    assert agents.get(f"/_/team?doc={ADDR}", member=BEA).status == 404
    assert post(agents, {"doc": ADDR, "op": "add", "side": "team", "body": "x", "quote": "q"}).status == 404


def test_a_member_who_may_open_the_page_adds_and_reads_a_team_comment_under_their_name(agents, tmp_path):
    enabled(agents, tmp_path)
    got = post(agents, {"doc": ADDR, "op": "add", "body": f"{MARK} hi", "quote": "q", "hash": "h1"})
    assert got.status == 200, got.text
    assert got.json()["team"][0]["by"] == "Bea"
    seen = agents.get(f"/_/team?doc={ADDR}", member=CAL).json()
    assert [c["body"] for c in seen["team"]] == [f"{MARK} hi"]       # shared among the members who may open it


def test_a_member_who_may_not_open_the_page_gets_the_answer_of_a_missing_page_and_nothing_is_stored(agents, tmp_path):
    enabled(agents, tmp_path, allowed={(BEA, ADDR)})
    missing = agents.get("/_/team?doc=Clients/acme/work/never.md", member=CAL)
    refused = agents.get(f"/_/team?doc={ADDR}", member=CAL)
    assert (refused.status, refused.text) == (missing.status, missing.text) == (404, refused.text)
    assert post(agents, {"doc": ADDR, "op": "add", "body": "x", "quote": "q"}, member=CAL).status == 404
    assert agents.hub.team.list(ADDR) == []


def test_an_address_outside_clients_is_not_a_team_page_even_for_a_gate_that_allows_it(agents, tmp_path):
    enabled(agents, tmp_path, allowed={(BEA, DOC)})
    assert agents.get(f"/_/team?doc={DOC}", member=BEA).status == 404
    assert post(agents, {"doc": DOC, "op": "add", "body": "x", "quote": "q"}).status == 404


def test_the_routes_are_for_a_signed_in_member_alone(agents, tmp_path):
    enabled(agents, tmp_path)
    for headers in ({"Authorization": f"Bearer {agents.tokens['bea-claude']}"}, {}):
        got = agents.door.request("POST", "/_/team", body={"doc": ADDR, "op": "add", "body": "x", "quote": "q"},
                                 cookie=False, key=False, headers=headers)
        assert got.status in (401, 403, 404)
    assert agents.hub.team.list(ADDR) == []


def test_tell_on_a_team_comment_is_refused_with_a_line_and_writes_nothing(agents, tmp_path):
    enabled(agents, tmp_path)
    got = post(agents, {"doc": ADDR, "op": "add", "body": "x", "quote": "q", "tell": True})
    assert got.status == 400 and "Tell" in got.text
    assert agents.hub.team.list(ADDR) == []


def test_a_write_with_a_side_that_is_not_team_is_refused_here(agents, tmp_path):
    enabled(agents, tmp_path)
    for side in ("client", "x", 1):
        assert post(agents, {"doc": ADDR, "op": "add", "side": side, "body": "x", "quote": "q"}).status == 400
    assert agents.hub.team.list(ADDR) == []


def test_an_id_that_is_not_a_team_id_is_refused_and_a_team_id_never_reaches_a_client_path(agents, tmp_path):
    enabled(agents, tmp_path)
    post(agents, {"doc": ADDR, "op": "add", "body": "x", "quote": "q"})
    for op, extra in (("reply", {"body": "r"}), ("status", {"status": "resolved"}), ("edit", {"body": "e"}), ("delete", {})):
        assert post(agents, {"doc": ADDR, "op": op, "id": "c1", **extra}).status == 400, op
    assert [c["id"] for c in agents.hub.team.list(ADDR)] == ["t1"]


def test_reply_status_edit_and_delete_by_id_and_the_author_rule_answers_403(agents, tmp_path):
    enabled(agents, tmp_path)
    post(agents, {"doc": ADDR, "op": "add", "body": "mine", "quote": "q"})
    assert post(agents, {"doc": ADDR, "op": "reply", "id": "t1", "body": "r"}, member=CAL).status == 200
    assert post(agents, {"doc": ADDR, "op": "status", "id": "t1", "status": "resolved"}, member=CAL).status == 200
    assert post(agents, {"doc": ADDR, "op": "edit", "id": "t1", "body": "x"}, member=CAL).status == 403
    assert post(agents, {"doc": ADDR, "op": "delete", "id": "t1"}).status == 403      # CAL replied: not deletable
    [c] = agents.hub.team.list(ADDR)
    assert (c["body"], c["status"], [r["by"] for r in c["replies"]]) == ("mine", "resolved", ["Cal"])
    assert post(agents, {"doc": ADDR, "op": "edit", "id": "t9", "body": "x"}).status == 410


def test_an_empty_body_a_missing_quote_and_a_wrong_op_are_refused(agents, tmp_path):
    enabled(agents, tmp_path)
    for body in ({"op": "add", "body": " ", "quote": "q"}, {"op": "add", "body": "x"}, {"op": "nope", "body": "x"}):
        assert post(agents, {"doc": ADDR, **body}).status == 400
    assert agents.hub.team.list(ADDR) == []


def test_a_team_write_leaves_no_trace_in_the_roots_the_index_the_write_log_or_the_diagnostics(agents, tmp_path, rectoversos):
    enabled(agents, tmp_path)
    before = agents.hub.file(DOC).read_bytes()
    post(agents, {"doc": ADDR, "op": "add", "body": f"{MARK} x", "quote": f"{MARK} q"})
    assert agents.hub.file(DOC).read_bytes() == before
    for base in (rectoversos,):
        for p in base.rglob("*"):
            if p.is_file():
                assert MARK not in p.read_text(encoding="utf-8", errors="ignore"), p
    assert MARK not in json.dumps(agents.hub.writes.__dict__, default=str)
    assert MARK not in json.dumps(agents.get("/_/index.json", member=BEA).json())
