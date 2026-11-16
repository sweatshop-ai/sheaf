"""Moving a loose page to another shared Sheaf (ticket 20, part 2): the sending end, the Forward that stays, what the old address
answers, and the CLI that follows. Two hubs in memory, each with a state folder of its own, joined by a `Link` that stands in for
the tailnet (`helpers.two_hubs`): no socket, no thread. The page is moved by the owner's request to `/_/move-tiroir` (the row's
"Move to another tiroir…"), the call to the other hub goes through `outgoing.post`, and the Forward is written only after the other
hub says the page landed."""
import json

import pytest
from helpers import Link, build_side, hub_rows, pair_peers
from test_peer_channel import FakeKeyring

from sheafmd import connect, send
from sheafmd.cli import main
from sheafmd.hub import loose, outgoing
from sheafmd.source import md_hash

A_ORIGIN, B_ORIGIN = "https://a.example.com", "https://b.example.com"
ALICE_A, BOB_A = "503b2f77-83de-452c-817a-a357faf85929", "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"
ALICE_B = "9a1f3c52-6d0e-4b7a-8c25-1e4f7b3d9a60"
OLD = "loose-alice/notes/plan.md"
NEW = "loose-al/notes/plan.md"          # her loose folder there has another name: the new address is not the old one
SESSION = "6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11"

PLAN = """# Plan

First paragraph.

<!-- comment c1: Bob, open
Why pears?
-->
"""


@pytest.fixture
def keyring(monkeypatch):
    k = FakeKeyring()
    monkeypatch.setattr(connect, "system_store", lambda: k)
    return k


@pytest.fixture
def two(tmp_path, keyring, monkeypatch):
    """Hub A (Alice, Bob) and hub B (Alice, with the same e-mail, under another short name), each holding a peer token for the
    other, and the link between them standing in for `outgoing.post`. Alice has a page in `notes/` on A with two versions, a
    comment, a keep mark and a Write log line from a session."""
    a = build_side(tmp_path, "a", A_ORIGIN, {ALICE_A: ("Alice", "alice", "alice@example.com"), BOB_A: ("Bob", "bob", "bob@example.com")})
    b = build_side(tmp_path, "b", B_ORIGIN, {ALICE_B: ("Alice", "al", "Alice@Example.com")})
    pair_peers(a, b, keyring)
    link = Link(a, b)
    monkeypatch.setattr(outgoing, "post", link.post)
    bad, got = a.ask("alice", "create", headers={"X-Sheaf-Session": "s-1", "X-Sheaf-Host": "laptop-alice"},
                     doc="plan.md", folder="notes", text=PLAN, keep=True)
    assert not bad and got["doc"] == OLD, got
    bad, got = a.ask("alice", "update", doc=OLD, text=PLAN + "\nSecond.\n", expected_hash=got["hash"])
    assert not bad, got
    a.link, a.b = link, b
    return a


def move(a, member=ALICE_A, doc=OLD, to=B_ORIGIN):
    return a.post("/_/move-tiroir", {"doc": doc, "tiroir": to}, member=member)


def moved(a, **kw):
    got = move(a, **kw)
    assert got.status == 200, got.text
    return got.json()


# ── the transfer and the Forward ─────────────────────────────────────────────

def test_a_move_lands_the_page_in_the_owners_loose_root_there_in_the_same_folder(two):
    out = moved(two)
    assert out["doc"] == NEW and out["origin"] == B_ORIGIN
    assert two.b.hub.file(NEW).read_text(encoding="utf-8").count("Why pears?") == 1


def test_the_copy_there_carries_the_versions_the_write_log_lines_and_the_keep_mark(two):
    moved(two)
    b = two.b
    with b.active():
        assert b.hub.versions.get(NEW, md_hash(PLAN)) is not None
        assert any(w.session == "s-1" for w in b.hub.writes.lines(NEW))
        assert loose.kept(b.hub.roots.get("loose-al").path, "notes/plan.md")


def test_the_forward_is_written_after_the_receiver_confirms_and_the_page_is_dropped_here(two):
    out = moved(two)
    with two.active():
        entry = two.hub.forwards.entry(OLD)
        assert entry["origin"] == B_ORIGIN and entry["to"] == NEW and entry["by"] == "Alice" and entry["at"]
        assert entry["hash"] == out["hash"] == md_hash(two.b.hub.file(NEW).read_text(encoding="utf-8"))
        assert not two.hub.file(OLD).exists()
        assert two.hub.versions.get(OLD, md_hash(PLAN)) is None


def test_a_move_ends_the_pages_tells_as_cancelled_page_moved_and_tells_the_open_tabs(two):
    from sheafmd.hub import tell  # noqa: F401  (the Tell path is the hub's own; the row is queued as it queues one)
    with two.active():
        row = next(r for r in two.hub.tokens.list() if r.name == "alice")
        member = two.hub.proxy.members[ALICE_A]
        two.hub.session_tells.queue(OLD, "c1", row, "s-1", "Alice", member, None)
        sub = two.hub.entry(OLD).bus.subscribe()
    moved(two)
    with two.active():
        assert not two.hub.session_tells.waits(OLD, member)
        ended = hub_rows("tell-cancelled")
        assert [r["reason"] for r in ended if r["doc"] == OLD] == ["page moved"]
    names = [n for n, d in sub.drain()]
    assert "moved" in names


def test_the_share_does_not_go_and_the_copy_there_is_private_to_its_owner(two):
    with two.active():
        path = two.hub.file(OLD)
        text = path.read_text(encoding="utf-8")
    bad, got = two.ask("alice", "update", doc=OLD, text=text.replace("# Plan\n", "# Plan\n\n- [x] Share with bob\n", 1),
                       expected_hash=md_hash(text))
    assert not bad, got
    moved(two)
    landed = two.b.hub.file(NEW).read_text(encoding="utf-8")
    assert "shared:" not in landed and "[x] Share" not in landed


# ── a move that does not complete leaves everything as it was ────────────────

def test_a_link_that_is_down_leaves_the_page_and_every_store_as_they_were(two):
    before = two.tree()
    two.link.down = True
    got = move(two)
    assert got.status >= 400 and got.json()["say"]
    assert two.tree() == before
    with two.active():
        assert two.hub.forwards.follow(OLD) is None


@pytest.mark.parametrize("why", ["no_owner", "name_taken"])
def test_a_receiver_that_refuses_leaves_the_page_in_place_and_says_why(two, why):
    if why == "no_owner":
        two.b.hub.proxy.members[ALICE_B] = type(two.b.hub.proxy.members[ALICE_B])(
            **{**two.b.hub.proxy.members[ALICE_B].__dict__, "email": "someone-else@example.com"})
    else:
        bad, got = two.b.ask("al", "create", doc="plan.md", folder="notes", text="# There already\n")
        assert not bad, got
    before_a, before_b = two.tree(), two.b.tree()
    got = move(two)
    assert got.status == 409 and got.json()["why"] == why and got.json()["say"]
    assert two.tree() == before_a and two.b.tree() == before_b
    with two.active():
        assert two.hub.forwards.follow(OLD) is None


def test_a_confirm_that_never_arrives_leaves_no_forward_and_a_retry_lands_one_page_and_forwards_once(two):
    two.link.lose_answer = True
    got = move(two)
    assert got.status >= 400
    with two.active():
        assert two.hub.file(OLD).exists() and two.hub.forwards.follow(OLD) is None
    two.link.lose_answer = False
    moved(two)
    with two.active():
        assert two.hub.forwards.follow(OLD) == NEW and not two.hub.file(OLD).exists()
    with two.b.active():
        assert sorted(p.name for p in two.b.hub.file(NEW).parent.iterdir()) == ["plan.md"]


def test_a_page_that_changed_while_the_transfer_ran_writes_no_forward_and_drops_nothing(two):
    def edit(verb, res):
        with two.active():
            text = two.hub.file(OLD).read_text(encoding="utf-8")
        bad, got = two.ask("alice", "update", doc=OLD, text=text + "\nAdded while it was away.\n", expected_hash=md_hash(text))
        assert not bad, got
        two.link.between = None
    two.link.between = edit
    got = move(two)
    assert got.status == 409 and "changed" in got.json()["say"]
    with two.active():
        assert "Added while it was away." in two.hub.file(OLD).read_text(encoding="utf-8")
        assert two.hub.forwards.follow(OLD) is None


def test_only_the_owner_moves_and_another_member_gets_the_answer_of_a_page_that_is_not_there(two):
    there = move(two, member=BOB_A)
    gone = move(two, member=BOB_A, doc="loose-alice/notes/never.md")
    assert there.status == gone.status >= 400
    assert there.json()["say"].replace(OLD, "X") == gone.json()["say"].replace("loose-alice/notes/never.md", "X")
    assert two.link.calls == []


def test_a_page_of_a_registered_root_does_not_move(two):
    root = next(f for m in two.hub.proxy.members.values() if m.id == ALICE_A for f in m.roots)
    from pathlib import Path
    (Path(root) / "work.md").write_text("# Work\n", encoding="utf-8")
    with two.active():
        address = [r for r in two.hub.roots.all() if str(r.path) == str(Path(root))][0].name + "/work.md"
    got = move(two, doc=address)
    assert got.status == 409 and two.link.calls == []


def test_a_tiroir_that_is_not_paired_is_refused_before_anything_is_sent(two, keyring):
    keyring.items.clear()
    got = move(two)
    assert got.status >= 400 and "peer" in got.json()["say"].lower() and two.link.calls == []


# ── the old address ──────────────────────────────────────────────────────────

def test_a_browser_on_the_old_address_gets_a_302_that_is_never_cached_to_the_full_new_address(two):
    moved(two)
    two.link.down = True                          # the Forward is this hub's own: the other being down changes nothing
    got = two.get(f"/{OLD}", member=ALICE_A)
    assert got.status == 302 and got.headers["Location"] == f"{B_ORIGIN}/{NEW}"
    assert got.headers["Cache-Control"] == "no-store"


def test_a_read_or_an_update_on_the_old_address_writes_nothing_and_says_where_the_page_went(two):
    moved(two)
    tree = two.tree()
    laptop = {"X-Sheaf-Session": "s-2", "X-Sheaf-Host": "laptop-alice"}
    for tool, args in (("read", {}), ("update", {"text": "# New\n", "expected_hash": "x" * 8})):
        bad, said = two.ask("alice", tool, headers=laptop, doc=OLD, **args)
        assert bad and B_ORIGIN in said and NEW in said and "Alice" in said, said
    assert two.tree() == tree
    with two.active():
        assert not two.hub.file(OLD).exists() and two.hub.writes.lines(OLD)[-1].session != "s-2"


def test_the_sentence_for_a_laptop_names_the_connect_line_and_the_one_for_a_chat_client_says_to_ask_the_owner(two):
    moved(two)
    _, laptop = two.ask("alice", "read", headers={"X-Sheaf-Session": "s-2", "X-Sheaf-Host": "laptop-alice"}, doc=OLD)
    _, chat = two.ask("alice", "read", headers={"X-Sheaf-Chat": "chat-1"}, doc=OLD)
    assert f"sheaf connect {B_ORIGIN}" in laptop
    assert "ask" in chat.lower() and "sheaf connect" not in chat


@pytest.mark.parametrize("tool,args", [("threads", {}), ("reply", {"id": "c1", "body": "Done"}), ("resolve", {"id": "c1"})])
def test_threads_reply_and_resolve_on_the_old_address_answer_moved_too(two, tool, args):
    moved(two)
    tree = two.tree()
    bad, said = two.ask("alice", tool, headers={"X-Sheaf-Session": "s-2"}, doc=OLD, **args)
    assert bad and B_ORIGIN in said and two.tree() == tree


def test_a_create_onto_the_old_address_is_refused_and_a_move_back_drops_the_forward(two):
    moved(two)
    bad, said = two.ask("alice", "create", doc="plan.md", folder="notes", text="# Another\n")
    assert bad and "moved" in said.lower()
    back = two.b.post("/_/move-tiroir", {"doc": NEW, "tiroir": A_ORIGIN}, member=ALICE_B)
    assert back.status == 200, back.text
    with two.active():
        assert two.hub.forwards.follow(OLD) is None and two.hub.file(OLD).exists()


# ── diagnostics ──────────────────────────────────────────────────────────────

def test_each_knock_on_the_old_address_is_one_moved_knock_line_with_no_text_and_no_token(two):
    moved(two)
    with two.active():
        before = len(hub_rows("moved-knock"))
    two.get(f"/{OLD}", member=ALICE_A)
    two.ask("alice", "read", headers={"X-Sheaf-Session": "s-2", "X-Sheaf-Host": "laptop-alice"}, doc=OLD)
    two.ask("alice", "read", headers={"X-Sheaf-Chat": "chat-1"}, doc=OLD)
    with two.active():
        rows = hub_rows("moved-knock")[before:]
    assert [(r["via"], r["place"]) for r in rows] == [("browser", ""), ("door", "laptop"), ("door", "chat client")]
    assert all(r["to"] == B_ORIGIN and r["doc"] == OLD and r["member"] for r in rows)
    flat = json.dumps(rows)
    assert "First paragraph" not in flat and two.tokens["alice"] not in flat


# ── the CLI ──────────────────────────────────────────────────────────────────

@pytest.fixture
def laptop(two, keyring, monkeypatch, tmp_path):
    """Alice's laptop: the page sent to A from a file, the way `sheaf FILE.md` sends it, the tiroir being A."""
    from sheafmd import paths
    monkeypatch.setattr(send, "post", two.link.door_post)
    monkeypatch.setattr(send, "get", two.link.door_get)
    monkeypatch.setattr(send, "declared", lambda environ=None, session=...: {"X-Sheaf-Session": SESSION, "X-Sheaf-Host": "laptop-alice"})
    keyring.set("sheaf", A_ORIGIN, two.tokens["alice"])
    config = paths.config_file()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f'tiroir = "{A_ORIGIN}"\n', encoding="utf-8")
    folder = tmp_path / "scratch"
    folder.mkdir()
    md = folder / "plan.md"
    md.write_text("# Plan\n\nOwn page.\n", encoding="utf-8")
    assert main([str(md)]) == 0
    row = send.row_of(md)
    assert row["tiroir"] == A_ORIGIN
    return md, row["doc"]


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_a_laptop_with_a_token_for_both_resends_to_the_new_one_and_says_so(two, laptop, keyring, capsys):
    md, doc = laptop
    capsys.readouterr()
    moved(two, doc=doc)
    keyring.set("sheaf", B_ORIGIN, two.b.tokens["al"])
    md.write_text("# Plan\n\nOwn page, edited.\n", encoding="utf-8")
    code, out, err = run(capsys, md)
    assert code == 0, err
    row = send.row_of(md)
    assert row["tiroir"] == B_ORIGIN and row["doc"].startswith("loose-al/")
    with two.b.active():
        assert "edited" in two.b.hub.file(row["doc"]).read_text(encoding="utf-8")
    assert B_ORIGIN.split("//")[1] in out + err
    assert md.read_text(encoding="utf-8").endswith("edited.\n")


def test_the_resend_declares_the_session_on_the_new_one(two, laptop, keyring, capsys):
    md, doc = laptop
    moved(two, doc=doc)
    keyring.set("sheaf", B_ORIGIN, two.b.tokens["al"])
    two.link.door_headers.clear()
    run(capsys, md)
    assert any(o == B_ORIGIN and h.get("X-Sheaf-Session") == SESSION for o, h in two.link.door_headers)


def test_a_page_that_changed_there_before_the_resend_goes_the_stale_way_and_leaves_beside_it(two, laptop, keyring, capsys):
    md, doc = laptop
    moved(two, doc=doc)
    keyring.set("sheaf", B_ORIGIN, two.b.tokens["al"])
    with two.b.active():
        address = [p for p in two.b.hub.roots.get("loose-al").path.rglob("*.md")][0].relative_to(two.b.hub.roots.get("loose-al").path).as_posix()
    text = two.b.hub.file(f"loose-al/{address}").read_text(encoding="utf-8")
    bad, got = two.b.ask("al", "update", doc=f"loose-al/{address}", text=text + "\nThere.\n", expected_hash=md_hash(text))
    assert not bad, got
    md.write_text("# Plan\n\nHere.\n", encoding="utf-8")
    code, out, err = run(capsys, md)
    assert code != 0 and md.with_name("plan.tiroir.md").exists()
    assert md.read_text(encoding="utf-8") == "# Plan\n\nHere.\n"


def test_a_laptop_without_a_token_for_the_new_one_prints_the_connect_line_and_changes_nothing(two, laptop, capsys):
    md, doc = laptop
    moved(two, doc=doc)
    state = send.read_state()
    code, out, err = run(capsys, md)
    assert code == 1 and f"sheaf connect {B_ORIGIN}" in out + err
    assert send.read_state() == state and md.read_text(encoding="utf-8") == "# Plan\n\nOwn page.\n"


def test_pull_follows_the_move_the_same_way(two, laptop, keyring, capsys):
    md, doc = laptop
    moved(two, doc=doc)
    code, out, err = run(capsys, "pull", md)
    assert code == 1 and f"sheaf connect {B_ORIGIN}" in out + err
    keyring.set("sheaf", B_ORIGIN, two.b.tokens["al"])
    code, out, err = run(capsys, "pull", md)
    assert code == 0, err
    assert send.row_of(md)["tiroir"] == B_ORIGIN
