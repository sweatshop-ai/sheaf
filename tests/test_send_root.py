"""The sending end of a root's move (ticket 21): the pages cut into calls of at most 8 MiB, one `root` call per batch, what
each answer does to the move. The receiver is a function, not a hub."""
import json

import pytest

from sheafmd.hub import channel, outgoing, root_moves

THERE = "https://there.example"
HEAD = {"id": "m1", "repo": "o/r", "branch": "dev", "tip": "abc", "from": {"origin": "https://here.example", "by": "alice"}}


def row(path, size=10):
    return {"path": path, "owner_email": "a@example.com", "record": {}, "blob": "b" * 40, "versions": [{"text": "x" * size}], "writes": []}


@pytest.fixture
def move(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "m1")
    return moves


class Receiver:
    """Answers each call from `answers`, a list of (status, body) or an exception to raise; keeps the calls."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, to, verb, body):
        self.calls.append((to, verb, body))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def ok(*paths):
    return 200, {"pages": {p: {"ok": True, "hash": "h"} for p in paths}}


# ── cutting into batches ─────────────────────────────────────────────────────

def test_pages_that_fit_go_in_one_batch():
    assert len(outgoing.batches([row("a.md"), row("b.md")], limit=10_000)) == 1


def test_a_batch_over_the_limit_is_cut_in_two_calls_and_keeps_the_order():
    rows = [row(f"{i}.md", size=400) for i in range(4)]
    got = outgoing.batches(rows, limit=1500)
    assert len(got) == 2
    assert [r["path"] for b in got for r in b] == [r["path"] for r in rows]
    assert all(len(json.dumps(b)) <= 1500 for b in got)


def test_a_page_over_the_limit_alone_is_left_out_of_the_batches_and_reported():
    got = outgoing.batches([row("a.md"), row("big.md", size=5000), row("b.md")], limit=2000)
    assert [[r["path"] for r in b] for b in got] == [["a.md", "b.md"]]
    assert outgoing.too_big([row("a.md"), row("big.md", size=5000)], limit=2000) == {"big.md"}


def test_the_limit_is_the_channels_own():
    assert outgoing.BATCH_LIMIT < channel.MAX_TRANSFER


# ── send_root ────────────────────────────────────────────────────────────────

def test_each_confirmed_page_is_marked_sent_and_the_call_is_the_root_verb(move):
    receiver = Receiver(ok("a.md", "b.md"))
    done = outgoing.send_root(receiver, move, "o/r", THERE, HEAD, [row("a.md"), row("b.md")])
    assert done == {"a.md": "h", "b.md": "h"}
    assert move.get("o/r")["sent"] == ["a.md", "b.md"]
    assert move.get("o/r")["hashes"] == {"a.md": "h", "b.md": "h"}
    (to, verb, body), = receiver.calls
    assert (to, verb) == (THERE, "root")
    assert {k: body[k] for k in HEAD} == HEAD and [p["path"] for p in body["pages"]] == ["a.md", "b.md"]


def test_a_page_the_receiver_refuses_is_held_with_its_reason_and_the_others_still_go(move):
    answer = 200, {"pages": {"a.md": {"ok": True, "hash": "h"}, "b.md": {"ok": False, "why": "no_owner"}}}
    done = outgoing.send_root(Receiver(answer), move, "o/r", THERE, HEAD, [row("a.md"), row("b.md")])
    assert done == {"a.md": "h"}
    assert move.get("o/r")["held"] == {"b.md": "no_owner"}


def test_a_clone_being_made_holds_every_page_as_cloning(move):
    done = outgoing.send_root(Receiver((202, {"state": "cloning"})), move, "o/r", THERE, HEAD, [row("a.md")])
    assert done == {} and move.get("o/r")["held"] == {"a.md": "cloning"}


@pytest.mark.parametrize("why", ["no_app", "not_cloned", "private_root"])
def test_a_refusal_of_the_whole_root_holds_every_page_with_its_reason(move, why):
    outgoing.send_root(Receiver((409, {"why": why})), move, "o/r", THERE, HEAD, [row("a.md"), row("b.md")])
    assert move.get("o/r")["held"] == {"a.md": why, "b.md": why}


def test_a_peer_that_does_not_answer_holds_the_pages_as_unreachable(move):
    outgoing.send_root(Receiver(OSError("down")), move, "o/r", THERE, HEAD, [row("a.md")])
    assert move.get("o/r")["held"] == {"a.md": "unreachable"} and move.get("o/r")["sent"] == []


def test_a_server_error_is_a_failed_batch_and_sends_nothing_forward(move):
    outgoing.send_root(Receiver((500, {})), move, "o/r", THERE, HEAD, [row("a.md")])
    assert move.get("o/r")["held"] == {"a.md": "failed"} and move.get("o/r")["sent"] == []


def test_a_failure_in_the_first_batch_leaves_the_later_ones_unsent_and_held(move):
    rows = [row(f"{i}.md", size=400) for i in range(4)]
    receiver = Receiver(OSError("down"))
    outgoing.send_root(receiver, move, "o/r", THERE, HEAD, rows, limit=1500)
    assert len(receiver.calls) == 1
    assert set(move.get("o/r")["held"]) == {f"{i}.md" for i in range(4)}


def test_a_page_the_answer_does_not_mention_is_held_not_forwarded(move):
    done = outgoing.send_root(Receiver(ok("a.md")), move, "o/r", THERE, HEAD, [row("a.md"), row("b.md")])
    assert done == {"a.md": "h"} and move.get("o/r")["held"] == {"b.md": "failed"}


def test_a_page_already_sent_is_not_sent_again(move):
    move.sent("o/r", "a.md", "h1")
    receiver = Receiver(ok("b.md"))
    outgoing.send_root(receiver, move, "o/r", THERE, HEAD, [row("a.md"), row("b.md")])
    assert [p["path"] for p in receiver.calls[0][2]["pages"]] == ["b.md"]


def test_a_page_too_big_to_send_is_held_as_too_big(move):
    receiver = Receiver(ok("a.md"))
    outgoing.send_root(receiver, move, "o/r", THERE, HEAD, [row("a.md"), row("big.md", size=5000)], limit=2000)
    assert move.get("o/r")["held"] == {"big.md": "too_big"}


def test_the_held_row_is_written_only_when_the_reason_changes(move):
    rows, seen = [row("a.md")], []

    class Diag:
        def held(self, repo, to, pages):
            seen.append(pages)
    outgoing.send_root(Receiver((202, {})), move, "o/r", THERE, HEAD, rows, diag=Diag())
    outgoing.send_root(Receiver((202, {})), move, "o/r", THERE, HEAD, rows, diag=Diag())
    outgoing.send_root(Receiver((409, {"why": "no_app"})), move, "o/r", THERE, HEAD, rows, diag=Diag())
    assert seen == [{"a.md": "cloning"}, {"a.md": "no_app"}]


@pytest.mark.parametrize("why", [5, ["x"], "x" * 65, "has space", "", "Upper", "a\nb"])
def test_a_reason_the_peer_makes_up_is_held_as_failed_not_stored(move, why):
    receiver = Receiver((200, {"pages": {"a.md": {"ok": False, "why": why}}}), (409, {"why": why}))
    outgoing.send_root(receiver, move, "o/r", THERE, HEAD, [row("a.md")])
    assert move.get("o/r")["held"] == {"a.md": "failed"}
    outgoing.send_root(receiver, move, "o/r", THERE, HEAD, [row("a.md")])
    assert move.get("o/r")["held"] == {"a.md": "failed"}


@pytest.mark.parametrize("said", [5, ["x"], "x" * 129, "has space", "a\nb", None])
def test_a_confirmed_page_with_a_hash_the_peer_made_up_is_held_not_sent(move, said):
    done = outgoing.send_root(Receiver((200, {"pages": {"a.md": {"ok": True, "hash": said}}})), move, "o/r", THERE, HEAD, [row("a.md")])
    assert done == {}
    assert move.get("o/r")["sent"] == [] and move.get("o/r")["hashes"] == {}
    assert move.get("o/r")["held"] == {"a.md": "failed"}


def test_a_page_held_for_its_hash_goes_again_at_the_next_try(move):
    outgoing.send_root(Receiver((200, {"pages": {"a.md": {"ok": True}}})), move, "o/r", THERE, HEAD, [row("a.md")])
    again = Receiver(ok("a.md"))
    assert outgoing.send_root(again, move, "o/r", THERE, HEAD, [row("a.md")]) == {"a.md": "h"}
    assert len(again.calls) == 1


@pytest.mark.parametrize("said", [None, [], "ok"])
def test_an_answer_that_is_not_an_object_holds_the_batch_as_failed(move, said):
    done = outgoing.send_root(Receiver((200, said)), move, "o/r", THERE, HEAD, [row("a.md")])
    assert done == {} and move.get("o/r")["held"] == {"a.md": "failed"}
