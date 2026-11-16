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
    assert again.get("o/r") == {"to": THERE, "id": "id1", "sent": [], "held": {}}


def test_starting_a_move_again_to_the_same_tiroir_keeps_its_id_and_progress(tmp_path):
    moves = root_moves.Moves(tmp_path)
    moves.start("o/r", THERE, "id1")
    moves.sent("o/r", "a.md")
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
    moves.sent("o/r", "a.md")
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
    assert set(json.loads((tmp_path / "root_moves.json").read_text())["o/r"]) == {"to", "id", "sent", "held"}
