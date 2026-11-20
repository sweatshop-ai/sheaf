"""A root moves to another tiroir when its `.sheaf.toml` changes (SPEC 13): the notice, the check that nothing leaves while
text is unpushed, and the file that keeps a move across a crash. No hub is started; local git repos only."""
import json
import subprocess

import pytest

from sheafmd.hub import root_moves

HERE = "https://here.example"
THERE = "https://there.example"


def git(at, *args):
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.com", "GIT_COMMITTER_NAME": "a",
                               "GIT_COMMITTER_EMAIL": "a@example.com", "PATH": "/usr/bin:/bin"}).stdout.strip()


@pytest.fixture
def pair(tmp_path):
    """A bare origin and a clone of it on `dev`, with one page committed and pushed."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(bare)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True, capture_output=True)
    git(clone, "checkout", "-q", "-b", "dev")
    (clone / "a.md").write_text("# A\n")
    git(clone, "add", "a.md")
    git(clone, "commit", "-qm", "a")
    git(clone, "push", "-q", "-u", "origin", "dev")
    return clone


def toml(clone, text):
    (clone / ".sheaf.toml").write_text(text)


# ── the notice ───────────────────────────────────────────────────────────────

def test_a_toml_naming_another_origin_is_a_pending_move_to_it(pair):
    toml(pair, f'tiroir = "{THERE}"\n')
    assert root_moves.target(pair, HERE) == THERE


@pytest.mark.parametrize("named", ["HTTPS://Here.Example", "https://here.example/", "https://here.example//"])
def test_a_toml_naming_this_hubs_own_origin_in_other_spelling_starts_no_move(pair, named):
    toml(pair, f'tiroir = "{named}"\n')
    assert root_moves.target(pair, HERE) is None


def test_a_toml_with_no_tiroir_key_starts_no_move(pair):
    toml(pair, 'theme = "plain"\n')
    assert root_moves.target(pair, HERE) is None


def test_a_clone_with_no_toml_starts_no_move(pair):
    assert root_moves.target(pair, HERE) is None


def test_a_hub_with_no_origin_never_starts_a_move(pair):
    toml(pair, f'tiroir = "{THERE}"\n')
    assert root_moves.target(pair, None) is None


def test_the_target_is_spelled_as_an_origin(pair):
    toml(pair, 'tiroir = "https://There.Example/"\n')
    assert root_moves.target(pair, HERE) == THERE


# ── nothing leaves while text is unpushed ────────────────────────────────────

def test_a_clone_with_everything_pushed_holds_nothing(pair):
    assert root_moves.held(pair, "dev", {"a.md"}) == {}


def test_a_commit_origin_lacks_holds_every_page(pair):
    (pair / "a.md").write_text("# A\n\nmore\n")
    git(pair, "commit", "-qam", "more")
    assert root_moves.held(pair, "dev", {"a.md"}) == {"a.md": "unpushed"}


def test_a_page_whose_file_differs_from_the_tip_is_held_alone(pair):
    (pair / "b.md").write_text("# B\n")
    git(pair, "add", "b.md")
    git(pair, "commit", "-qm", "b")
    git(pair, "push", "-q")
    (pair / "a.md").write_text("# A edited\n")
    assert root_moves.held(pair, "dev", {"a.md", "b.md"}) == {"a.md": "differs"}


def test_a_page_the_tip_lacks_is_held(pair):
    assert root_moves.held(pair, "dev", {"gone.md"}) == {"gone.md": "differs"}


# ── root_moves.json ──────────────────────────────────────────────────────────

def test_a_move_survives_a_restart(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    again = root_moves.Moves(tmp_path)
    assert again.get("o/r") == {"to": THERE, "id": "id1", "sent": [], "held": {}, "hashes": {}, "forwarded": []}


def test_starting_a_move_again_to_the_same_tiroir_keeps_its_id_and_progress(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md", "h1")
    moves.start("o/r", THERE, "id2")
    assert moves.get("o/r")["id"] == "id1" and moves.get("o/r")["sent"] == ["a.md"]


def test_a_toml_changed_to_another_tiroir_before_the_first_confirm_replaces_the_move(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.start("o/r", "https://third.example", "id2")
    assert moves.get("o/r")["to"] == "https://third.example"


def test_a_move_with_a_confirmed_page_runs_to_the_end_when_the_toml_changes_again(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md", "h1")
    moves.start("o/r", "https://third.example", "id2")
    assert moves.get("o/r")["to"] == THERE


def test_a_held_row_is_new_only_when_the_reason_changes(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    assert moves.hold("o/r", {"a.md": "unpushed"}) is True
    assert moves.hold("o/r", {"a.md": "unpushed"}) is False
    assert moves.hold("o/r", {"a.md": "differs"}) is True


def test_a_file_that_cannot_be_read_is_an_empty_list_of_moves(tmp_path):
    (tmp_path / "root_moves.json").write_text("{not json")
    assert root_moves.Moves(tmp_path).get("o/r") is None


def test_the_file_holds_no_text(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    assert set(json.loads((tmp_path / "root_moves.json").read_text())["o/r"]) == {"to", "id", "sent", "hashes", "forwarded", "held"}


# ── the retry clock ──────────────────────────────────────────────────────────

def test_a_move_is_due_at_a_pull_and_then_at_most_every_ten_minutes_from_the_poll():
    clock = root_moves.Clock()
    assert clock.due("o/r", 1000.0, pulled=False)               # never tried: due
    clock.tried("o/r", 1000.0)
    assert not clock.due("o/r", 1000.0 + 599, pulled=False)
    assert clock.due("o/r", 1000.0 + 600, pulled=False)
    assert clock.due("o/r", 1000.0 + 1, pulled=True)            # a pull always retries


def test_the_clock_counts_per_repo():
    clock = root_moves.Clock()
    clock.tried("o/r", 1000.0)
    assert clock.due("o/other", 1001.0, pulled=False)


# ── the diagnostics rows ─────────────────────────────────────────────────────

@pytest.fixture
def rows(monkeypatch):
    seen = []
    monkeypatch.setattr(root_moves.diagnostics, "record", lambda source, kind, doc=None, **d: seen.append((source, kind, d)))
    return seen


def test_each_state_change_is_one_hub_row_named_for_it(rows):
    d = root_moves.Diag()
    d.started("o/r", THERE)
    d.held("o/r", THERE, {"a.md": "unpushed"})
    d.done("o/r", THERE, 3)
    assert [(s, k) for s, k, _ in rows] == [("hub", "root-move-started"), ("hub", "root-move-held"), ("hub", "root-move-done")]
    assert rows[1][2] == {"repo": "o/r", "to": THERE, "pages": {"a.md": "unpushed"}}
    assert rows[2][2] == {"repo": "o/r", "to": THERE, "count": 3}


def test_a_row_holds_no_text_and_no_token(rows):
    d = root_moves.Diag()
    d.started("o/r", THERE)
    d.unpaired("o/r", THERE)
    d.held("o/r", THERE, {"a.md": "differs"})
    d.done("o/r", THERE, 1)
    for _, _, detail in rows:
        assert not {"text", "token", "body", "blob"} & set(detail)


def test_an_unpaired_tiroir_is_written_once_per_repo_and_origin(rows):
    d = root_moves.Diag()
    d.unpaired("o/r", THERE)
    d.unpaired("o/r", THERE)
    d.unpaired("o/r", "https://third.example")
    d.unpaired("o/other", THERE)
    assert len(rows) == 3


# ── which pages go ───────────────────────────────────────────────────────────

def test_a_page_with_a_record_or_versions_or_log_lines_is_in_the_inventory():
    owners = {"a.md": "alice", "b.md": "alice", "c.md": "alice", "plain.md": None}
    got = root_moves.inventory(owners.get, record={"a.md"}, versions={"b.md"}, logged={"c.md"})
    assert got.send == {"a.md": "alice", "b.md": "alice", "c.md": "alice"}
    assert got.ownerless == set()


def test_a_page_with_no_state_is_not_in_the_inventory():
    assert root_moves.inventory(lambda p: "alice", record=set(), versions=set(), logged=set()).send == {}


def test_a_page_with_no_owner_is_not_sent_and_gets_no_forward():
    got = root_moves.inventory({"a.md": "alice"}.get, record={"a.md", "x.md"}, versions=set(), logged=set())
    assert got.send == {"a.md": "alice"}
    assert got.ownerless == {"x.md"}


# ── the landing helpers ──────────────────────────────────────────────────────
# The owner match by e-mail is ticket 20's `incoming.owner_for` and `outgoing.owner_email`, tested in test_peer_transfer.py.

def test_the_blob_check_passes_when_the_tip_holds_the_page_with_that_blob(pair):
    blob = git(pair, "hash-object", "a.md")
    assert root_moves.tip_holds(pair, "dev", "a.md", blob)


def test_the_blob_check_fails_for_another_blob_or_a_page_the_tip_lacks(pair):
    assert not root_moves.tip_holds(pair, "dev", "a.md", "0" * 40)
    assert not root_moves.tip_holds(pair, "dev", "gone.md", git(pair, "hash-object", "a.md"))


# ── the unpaired rule ────────────────────────────────────────────────────────

class Keys(dict):
    def get(self, service, origin):
        return super().get((service, origin))


def test_a_tiroir_this_hub_holds_a_peer_token_for_is_paired():
    keys = Keys({(root_moves.connect.PEER_SERVICE, THERE): "tok"})
    assert root_moves.paired(THERE, keys)


def test_a_tiroir_with_no_peer_token_is_not_paired():
    assert not root_moves.paired(THERE, Keys())


def test_a_door_token_for_that_tiroir_is_not_a_peer_token():
    assert not root_moves.paired(THERE, Keys({(root_moves.connect.SERVICE, THERE): "tok"}))


def test_a_keyring_that_cannot_be_read_pairs_nothing():
    class Broken:
        def get(self, *_):
            raise root_moves.connect.ConnectError("no keyring")
    assert not root_moves.paired(THERE, Broken())


# ── forwarded, cancel, done (ticket 21 part 2) ───────────────────────────────

def test_a_confirmed_page_keeps_the_receivers_hash_and_waits_for_its_forward(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md", "h1")
    moves.sent("o/r", "b.md", "h2")
    assert moves.get("o/r")["hashes"] == {"a.md": "h1", "b.md": "h2"}
    assert moves.pending_forward("o/r") == {"a.md": "h1", "b.md": "h2"}


def test_a_forwarded_page_is_no_longer_pending_and_a_restart_keeps_it(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md", "h1")
    moves.sent("o/r", "b.md", "h2")
    moves.forwarded("o/r", "a.md")
    assert root_moves.Moves(tmp_path).pending_forward("o/r") == {"b.md": "h2"}


def test_a_crash_between_the_confirm_and_the_forward_leaves_the_page_pending(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md", "h1")
    assert root_moves.Moves(tmp_path).pending_forward("o/r") == {"a.md": "h1"}


def test_a_page_with_a_forward_is_forwarded_once(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md", "h1")
    moves.forwarded("o/r", "a.md")
    moves.forwarded("o/r", "a.md")
    assert moves.get("o/r")["forwarded"] == ["a.md"]


def test_pending_forward_of_no_move_is_empty(tmp_path):
    assert root_moves.Moves(tmp_path).pending_forward("o/r") == {}


def test_a_move_that_confirmed_nothing_is_cancelled(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    assert moves.cancel("o/r") is True
    assert moves.get("o/r") is None


def test_a_move_with_a_confirmed_page_is_not_cancelled(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md", "h1")
    assert moves.cancel("o/r") is False
    assert moves.get("o/r")["to"] == THERE


def test_a_finished_move_is_dropped_so_a_later_move_to_the_same_tiroir_starts_afresh(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md", "h1")
    moves.forwarded("o/r", "a.md")
    assert moves.done("o/r") is True
    assert moves.get("o/r") is None
    assert moves.start("o/r", THERE, "id2")["id"] == "id2"


def test_a_move_with_a_page_not_yet_forwarded_is_not_done(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md", "h1")
    assert moves.done("o/r") is False
    assert moves.get("o/r") is not None


def test_cancel_and_done_of_no_move_change_nothing(tmp_path):
    moves = root_moves.Moves(tmp_path)
    assert moves.cancel("o/r") is False and moves.done("o/r") is False


def test_a_sent_page_with_no_hash_goes_back_to_unsent_at_the_next_start(tmp_path):
    (tmp_path / "root_moves.json").write_text('{"o/r": {"to": "%s", "id": "id1", "sent": ["a.md", "b.md"], "held": {}}}' % THERE)
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id2")
    moves.sent("o/r", "c.md", "h3")
    moves.start("o/r", THERE, "id3")
    assert moves.get("o/r")["sent"] == ["c.md"] and moves.pending_forward("o/r") == {"c.md": "h3"}


def test_a_row_from_before_the_held_and_sent_lists_is_read_whole(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.path.write_text(json.dumps({"o/r": {"to": THERE, "id": "m1"}}))
    assert moves.hold("o/r", {"a.md": "unpushed"})
    moves.sent("o/r", "a.md", "h1")
    assert moves.get("o/r")["sent"] == ["a.md"] and moves.get("o/r")["held"] == {}
    moves.path.write_text(json.dumps({"o/r": {"to": THERE, "id": "m1"}}))
    assert moves.cancel("o/r")
    moves.path.write_text(json.dumps({"o/r": {"to": THERE, "id": "m1"}}))
    assert not moves.done("o/r") and moves.pending_forward("o/r") == {}
