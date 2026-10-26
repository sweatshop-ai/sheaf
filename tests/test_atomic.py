"""sheafmd.atomic: a file that is either the old one or the whole new one."""
import os
import stat

import pytest

from sheafmd.atomic import write_text_atomic


def test_a_new_file_gets_the_text_and_the_mode_asked_for(tmp_path):
    target = tmp_path / "deep" / "file.json"
    write_text_atomic(target, "whole\n", mode=0o600)
    assert target.read_text(encoding="utf-8") == "whole\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert os.listdir(target.parent) == ["file.json"]


def test_with_no_mode_the_file_gets_what_the_umask_leaves(tmp_path):
    old = os.umask(0o027)
    try:
        write_text_atomic(tmp_path / "f", "x")
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "f").stat().st_mode) == 0o640


def test_a_check_that_refuses_keeps_the_old_file_and_leaves_no_temp_file(tmp_path):
    tmp_path = tmp_path / "dir"
    tmp_path.mkdir()
    target = tmp_path / "f"
    target.write_text("old")

    def refuse():
        raise RuntimeError("changed meanwhile")

    with pytest.raises(RuntimeError, match="changed meanwhile"):
        write_text_atomic(target, "new", check=refuse)
    assert target.read_text() == "old"
    assert os.listdir(tmp_path) == ["f"]


def test_the_check_runs_once_the_new_file_is_whole(tmp_path):
    tmp_path = tmp_path / "dir"
    tmp_path.mkdir()
    target = tmp_path / "f"
    target.write_text("old")
    seen = []
    write_text_atomic(target, "new", check=lambda: seen.append(
        [(p.name, p.read_text()) for p in tmp_path.iterdir()]))
    assert ("f", "old") in seen[0] and any(t == "new" for _, t in seen[0])
    assert target.read_text() == "new"
