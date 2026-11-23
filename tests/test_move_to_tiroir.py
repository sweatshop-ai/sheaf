"""Moving a loose page to another shared Sheaf (ticket 20, part 2): the sending end, the Forward that stays, what the old address
answers, and the CLI that follows. Two hubs in memory, each with a state folder of its own, joined by a `Link` that stands in for
the tailnet (`helpers.two_hubs`): no socket, no thread. The page is moved by the owner's request to `/_/move-tiroir` (the row's
"Move to another tiroir…"), the call to the other hub goes through `outgoing.post`, and the Forward is written only after the other
hub says the page landed."""
import dataclasses
import json
import os

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
    with two.active():          # a door write keeps no version of its own: the hub keeps the texts it hands a page, so one is handed
        root = two.hub.roots.get("loose-alice")
        (two.hub._versions_of(root) or two.hub.versions).put(OLD, PLAN)
    moved(two)
    b = two.b
    with b.active():
        kept = b.hub.versions.texts(NEW)
        assert any("First paragraph." in t and "Second." not in t for t in kept), kept       # the older version came, as the hub kept it
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
    shared = two.post("/_/share", {"doc": OLD, "hash": md_hash(text), "with": ["bob"]}, member=ALICE_A)     # an update through the door cannot Share
    assert shared.status == 200, shared.text
    moved(two)
    landed = two.b.hub.file(NEW).read_text(encoding="utf-8")
    assert "shared:" not in landed and "[x] Share" not in landed


def test_a_page_open_in_the_hub_moves_without_a_store_failing_under_its_own_lock(two):
    with two.active():
        two.hub.entry(OLD)
    moved(two)
    with two.active():
        assert hub_rows("move-store-failed") == []
        assert OLD not in two.hub.entries


def test_the_page_is_marked_moving_for_the_whole_transfer_and_the_mark_is_cleared_after_it(two, monkeypatch):
    seen = []
    real = two.link.post

    def post(origin, verb, body, token, seconds=None):
        with two.active():
            seen.append(OLD in two.hub.moving)
        return real(origin, verb, body, token, seconds)
    monkeypatch.setattr(outgoing, "post", post)
    moved(two)
    assert seen == [True]
    with two.active():
        assert OLD not in two.hub.moving


@pytest.mark.parametrize("how", ["down", "refused"])
def test_the_moving_mark_is_cleared_when_the_move_does_not_complete(two, how):
    if how == "down":
        two.link.down = True
    else:
        with two.b.active():
            two.b.hub.proxy.members[ALICE_B] = dataclasses.replace(two.b.hub.proxy.members[ALICE_B], email="other@example.com")
    assert move(two).status >= 400
    with two.active():
        assert OLD not in two.hub.moving


def test_a_recipients_open_tab_is_told_gone_under_the_opaque_name_it_had_and_no_new_one_is_made(two):
    with two.active():
        text = two.hub.file(OLD).read_text(encoding="utf-8")
    shared = two.post("/_/share", {"doc": OLD, "hash": md_hash(text), "with": ["bob"]}, member=ALICE_A)
    assert shared.status == 200, shared.text
    with two.active():
        opaque = two.hub.alias(two.hub.proxy.members[BOB_A], OLD)
    sub = two.get(f"/_/live?doc={opaque}", member=BOB_A).stream
    sub.drain()
    moved(two)
    got = [(n, d) for n, d in sub.drain()]
    assert ("gone", {"doc": opaque}) in got
    with two.active():
        assert OLD not in two.hub.shared_ids._data.values()


def test_the_versions_of_a_root_that_keeps_them_inside_do_not_stay_under_the_old_address(two):
    from sheafmd.hub import state
    with two.active():
        folder = two.hub.loose.known(two.hub.proxy.members[ALICE_A])
    (folder / ".sheaf.toml").write_text('versions = "root"\n', encoding="utf-8")
    with two.active():
        two.hub._versions_of(two.hub.roots.get("loose-alice")).put(OLD, two.hub.file(OLD).read_text(encoding="utf-8"))
        inside = state.Versions(folder, "loose-alice")
        assert inside.texts(OLD)
    moved(two)
    with two.active():
        assert inside.texts(OLD) == []


def test_the_drop_waits_for_the_file_lock_a_save_takes_and_finds_what_the_save_wrote(two):
    import threading
    import time

    from sheafmd.source import file_lock
    held, release = threading.Event(), threading.Event()
    with two.active():
        path = two.hub.file(OLD)
        text = path.read_text(encoding="utf-8")

    def writer():
        with file_lock(path):
            held.set()
            release.wait(5)
            path.write_text(text + "\nWritten under the file lock.\n", encoding="utf-8")

    def edit(verb, res):
        two.link.between = None
        threading.Thread(target=writer, daemon=True).start()
        assert held.wait(5)
        threading.Timer(0.3, release.set).start()
    two.link.between = edit
    got = move(two)
    time.sleep(0.1)
    assert got.status == 409 and "changed" in got.json()["say"]
    with two.active():
        assert "Written under the file lock." in two.hub.file(OLD).read_text(encoding="utf-8")
        assert two.hub.forwards.follow(OLD) is None


def test_a_page_already_marked_moving_is_refused_as_busy_and_its_mark_is_left_to_the_move_that_made_it(two):
    with two.active():
        two.hub.moving.add(OLD)
    got = move(two)
    assert got.status == 409 and "being moved" in got.json()["say"]
    with two.active():
        assert OLD in two.hub.moving
        assert two.hub.file(OLD).exists() and two.hub.forwards.follow(OLD) is None
    assert two.link.calls == []


def test_a_tell_on_the_old_address_of_a_page_that_went_to_another_tiroir_is_not_followed_to_an_address_there(two):
    moved(two)
    looked = []

    class Stop(Exception):
        pass

    def entry(address):
        looked.append(address)
        raise Stop
    with two.active():
        two.hub.tell._entry = entry
        member = two.hub.proxy.members[ALICE_A]
        with pytest.raises(Stop):
            two.hub.tell.queue_agent(OLD, "c1", member)
    assert looked == [OLD]


def test_a_move_takes_the_hubs_lock_under_neither_the_pages_lock_nor_its_file_lock(lock_order, two):
    with two.active():
        two.hub.entry(OLD)
    moved(two)         # the lock-order checker raises at an acquisition against `lockorder.ORDER`, and again at the end of the test


def test_the_index_is_told_the_page_left_after_its_file_is_gone(two):
    with two.active():
        two.hub.entry(OLD)
        seen = []
        real = two.hub.index.touch

        def touch(address):
            seen.append((address, two.hub.file(OLD).exists()))
            return real(address)
        two.hub.index.touch = touch
    moved(two)
    assert (OLD, False) in seen and (OLD, True) not in seen


def test_a_page_moved_out_and_back_shows_each_write_log_line_once(two):
    moved(two)
    back = two.b.post("/_/move-tiroir", {"doc": NEW, "tiroir": A_ORIGIN}, member=ALICE_B)
    assert back.status == 200, back.text
    with two.active():
        seen = [(l.time, l.writer, l.place, l.via, l.session, l.host, l.link, l.chat) for l in two.hub.writes.lines(OLD)]
    assert seen and len(seen) == len(set(seen))


def test_a_reply_that_is_cut_short_is_no_answer_at_all(monkeypatch):
    import socket
    import threading
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(65536)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nContent-Type: application/json\r\n\r\n{\"ok\"")
        conn.close()
    threading.Thread(target=serve, daemon=True).start()
    with pytest.raises(OSError):
        outgoing.post(f"http://127.0.0.1:{srv.getsockname()[1]}", "transfer", {}, "tok", 5)
    srv.close()


def test_an_error_reply_that_is_cut_short_is_no_answer_at_all(monkeypatch):
    import socket
    import threading
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(65536)
        conn.sendall(b"HTTP/1.1 500 Oops\r\nContent-Length: 100\r\nContent-Type: application/json\r\n\r\n{\"ok\"")
        conn.close()
    threading.Thread(target=serve, daemon=True).start()
    with pytest.raises(OSError):
        outgoing.post(f"http://127.0.0.1:{srv.getsockname()[1]}", "transfer", {}, "tok", 5)
    srv.close()


def test_a_redirect_is_an_answer_and_the_peer_token_does_not_follow_it():
    import socket
    import threading
    seen = []

    def serve(srv, reply):
        conn, _ = srv.accept()
        seen.append(conn.recv(65536))
        conn.sendall(reply)
        conn.close()
    second = socket.socket()
    second.bind(("127.0.0.1", 0))
    second.listen(1)
    first = socket.socket()
    first.bind(("127.0.0.1", 0))
    first.listen(1)
    target = f"http://127.0.0.1:{second.getsockname()[1]}/_/tiroir/transfer"
    threading.Thread(target=serve, daemon=True, args=(first, f"HTTP/1.1 302 Found\r\nLocation: {target}\r\nContent-Length: 0\r\n\r\n".encode())).start()
    threading.Thread(target=serve, daemon=True, args=(second, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")).start()
    status, answer = outgoing.post(f"http://127.0.0.1:{first.getsockname()[1]}", "transfer", {}, "peer-secret", 5)
    second.settimeout(0.3)
    try:
        second.accept()
        reached = True
    except OSError:
        reached = False
    first.close()
    second.close()
    assert status == 302 and answer is None
    assert not reached and not any(b"peer-secret" in r for r in seen[1:])


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


def _intruder(two, tmp_path):
    """(the loose root's id, the real path of the moving page, the text, a folder of the same name that holds the same
    text at the same path, ready to take the name)."""
    with two.active():
        text = two.hub.file(OLD).read_text(encoding="utf-8")
        rid = two.hub.roots.get("loose-alice").id
        mine = os.path.realpath(two.hub.file(OLD))
    intruder = tmp_path / "again" / "loose-alice"
    (intruder / "notes").mkdir(parents=True)
    (intruder / "notes" / "plan.md").write_text(text, encoding="utf-8")
    (intruder / "top.md").write_text("# Top\n", encoding="utf-8")
    return rid, mine, text, intruder


def _take(two, intruder):
    """Another request's forget, and the other folder taking the name and keeping its page."""
    two.hub.forget_root("loose-alice")
    two.hub.roots.for_document(intruder / "top.md")
    loose.keep(intruder, "notes/plan.md")


def test_a_move_never_reads_or_drops_the_page_of_a_folder_that_took_the_loose_roots_name(two, tmp_path):
    """8.11: the move holds the loose root it found the page in. Forgotten, and its name taken by another folder that
    holds the same text at the same path, once the other tiroir answered, the other folder's page is never dropped: it
    is a page that changed."""
    import threading
    rid, mine, text, intruder = _intruder(two, tmp_path)

    def answered(verb, res):                # another request's, which holds none of the move's locks
        two.link.between = None
        t = threading.Thread(target=_take, args=(two, intruder))
        t.start()
        t.join(10)
        assert not t.is_alive() and two.hub.roots.get("loose-alice").id != rid
    two.link.between = answered
    got = move(two)
    assert got.status == 409 and "changed" in got.json()["say"], got.text
    assert (intruder / "notes" / "plan.md").read_text(encoding="utf-8") == text
    assert os.path.exists(mine)


def test_a_forget_waits_for_a_move_that_drops_the_page_and_leaves_the_folder_that_takes_the_name_its_own(two, tmp_path):
    """8.2, 9.11 (181 A box 24, the part left by name): `moved_remote` finds the root, and forgets the stores, by the root's name. A
    forget that comes while the page is dropped waits for the move (it takes the moves' lock): the move drops the moving
    root's file and what the hub keeps of it, and the folder that takes the name afterwards keeps its page and its keep
    mark."""
    import threading
    rid, mine, text, intruder = _intruder(two, tmp_path)
    real, taking = two.hub.moved_remote, []

    def dropping(*a, **k):
        two.hub.moved_remote = real
        t = threading.Thread(target=_take, args=(two, intruder), daemon=True)
        t.start()
        t.join(2)
        taking.append(t)
        return real(*a, **k)
    two.hub.moved_remote = dropping
    got = move(two)
    assert got.status == 200, got.text
    taking[0].join(10)
    assert not taking[0].is_alive()
    assert os.path.realpath(two.hub.roots.get("loose-alice").path) == os.path.realpath(intruder)
    assert (intruder / "notes" / "plan.md").read_text(encoding="utf-8") == text and not os.path.exists(mine)
    assert loose.marks(intruder) == ["notes/plan.md"]


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
        two.hub.roots.for_document(Path(root) / "work.md")
        address = two.hub.roots.address(Path(root) / "work.md")
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


@pytest.mark.parametrize("tool,args", [("threads", {}), ("reply", {"id": "c1", "text": "Done"}), ("resolve", {"id": "c1"})])
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
    assert [(r["via"], r.get("place", "")) for r in rows] == [("browser", ""), ("door", "laptop"), ("door", "chat client")]
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


def test_an_edit_made_on_the_old_tiroir_before_the_move_is_not_hidden_by_the_landed_hash(two, laptop, keyring, capsys):
    md, doc = laptop
    row = send.row_of(md)
    with two.active():
        text = two.hub.file(doc).read_text(encoding="utf-8")
    bad, got = two.ask("alice", "update", doc=doc, text=text + "\nEdited in the browser.\n", expected_hash=row["hash"])
    assert not bad, got
    moved(two, doc=doc)
    keyring.set("sheaf", B_ORIGIN, two.b.tokens["al"])
    md.write_text("# Plan\n\nLaptop's own edit.\n", encoding="utf-8")
    code, out, err = run(capsys, md)
    assert code != 0 and md.with_name("plan.tiroir.md").exists()
    assert "Edited in the browser." in md.with_name("plan.tiroir.md").read_text(encoding="utf-8")
    assert md.read_text(encoding="utf-8") == "# Plan\n\nLaptop's own edit.\n"


def test_a_move_lets_go_of_the_moves_lock_while_it_waits_for_a_render_of_its_page(two):
    """Ticket 182 line 55: the drop here waits for the page's lock, which a render holds for up to 120 s. It waits with the
    moves' lock let go, so a cancel (`/_/cancel`), another move or a forget does not wait behind that render."""
    import threading

    from sheafmd.hub import moves
    with two.active():
        e = two.hub.entry(OLD)
    held, release, got = threading.Event(), threading.Event(), []

    def render():
        with e.live.exclusive():
            held.set()
            release.wait(15)

    def other():
        ok = moves._LOCK.acquire(timeout=3)
        if ok:
            moves._LOCK.release()
        got.append(ok)
        release.set()

    def between(verb, res):
        two.link.between = None
        threading.Thread(target=render, daemon=True).start()
        assert held.wait(5)
        threading.Timer(0.3, other).start()
    two.link.between = between
    out = moved(two)
    assert got == [True], "the moves' lock is held while the move waits for a render of its page"
    assert out["doc"] == NEW
