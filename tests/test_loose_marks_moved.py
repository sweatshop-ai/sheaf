"""The marks a loose root holds about a page (keep, archived, seen) follow the page when it moves (SPEC 9.11, "a Move does
not count as activity for archive"). The function alone, on a plain folder: no hub."""
import json

import pytest

from sheafmd.hub import loose


def put(root, name, data):
    (root / ".sheaf").mkdir(exist_ok=True)
    (root / ".sheaf" / name).write_text(json.dumps(data))


def get(root, name):
    return json.loads((root / ".sheaf" / name).read_text())


def test_the_three_marks_go_to_the_new_path_and_none_stays_at_the_old(tmp_path):
    put(tmp_path, "keep.json", ["a/p.md", "a/q.md"])
    put(tmp_path, "archived.json", {"a/p.md": 20.0, "a/q.md": 21.0})
    put(tmp_path, "seen.json", {"a/p.md": 10.0, "a/q.md": 11.0})
    loose.marks_moved(tmp_path, "a/p.md", "b/p.md")
    assert get(tmp_path, "keep.json") == ["a/q.md", "b/p.md"]
    assert get(tmp_path, "archived.json") == {"b/p.md": 20.0, "a/q.md": 21.0}
    assert get(tmp_path, "seen.json") == {"b/p.md": 10.0, "a/q.md": 11.0}


def test_a_page_moved_away_and_back_is_archived_only_if_it_was(tmp_path):
    put(tmp_path, "archived.json", {"a/p.md": 20.0})
    loose.marks_moved(tmp_path, "a/p.md", "b/p.md")
    loose.marks_moved(tmp_path, "b/p.md", "a/p.md")
    assert get(tmp_path, "archived.json") == {"a/p.md": 20.0}


def test_a_stale_mark_at_the_new_path_does_not_outlive_a_page_that_has_none(tmp_path):
    put(tmp_path, "archived.json", {"b/p.md": 20.0})
    put(tmp_path, "seen.json", {"b/p.md": 10.0})
    loose.marks_moved(tmp_path, "a/p.md", "b/p.md")
    assert get(tmp_path, "archived.json") == {} and get(tmp_path, "seen.json") == {}


def test_a_page_with_no_marks_writes_no_file(tmp_path):
    loose.marks_moved(tmp_path, "a/p.md", "b/p.md")
    assert not (tmp_path / ".sheaf").exists()


def test_an_unreadable_mark_file_refuses_the_lot_and_changes_nothing(tmp_path):
    put(tmp_path, "keep.json", ["a/p.md"])
    (tmp_path / ".sheaf" / "seen.json").write_text("not json")
    with pytest.raises(loose.Refused):
        loose.marks_moved(tmp_path, "a/p.md", "b/p.md")
    assert get(tmp_path, "keep.json") == ["a/p.md"]
