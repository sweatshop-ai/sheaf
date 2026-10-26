"""The diagnostics log: what goes wrong is written down where it happens (SPEC 15)."""
import json
import os
import stat
import subprocess
import sys
import time

import pytest

from sheafmd import diagnostics as dg


def rows(path=None):
    path = path or dg.log_path()
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def test_a_row_has_the_fixed_fields_and_the_detail(tmp_path):
    dg.record("hub", "save-409", tmp_path / "d.md", error="changed on disk", status=409)
    [r] = rows()
    assert list(r)[:6] == ["at", "source", "kind", "doc", "pid", "session"]
    assert (r["source"], r["kind"], r["doc"]) == ("hub", "save-409", str(tmp_path / "d.md"))
    assert r["pid"] == os.getpid() and r["session"] is None
    assert r["error"] == "changed on disk" and r["status"] == 409
    assert time.strptime(r["at"][:19], "%Y-%m-%dT%H:%M:%S")


def test_the_session_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc-123")
    dg.record("agent", "note", note="x")
    assert rows()[0]["session"] == "abc-123"


def test_empty_detail_is_left_out_and_a_detail_cannot_overwrite_a_fixed_field():
    dg.record("page", "toast", message="boom", error="", reason=None, pid=1, session="forged", at="then")
    [r] = rows()
    assert "error" not in r and "reason" not in r
    assert r["pid"] == os.getpid() and r["session"] is None and r["at"] != "then"


def test_every_field_is_clipped_to_2000_characters():
    dg.record("page", "k" * 5000, "/d/" + "x" * 5000, message="m" * 5000)
    [r] = rows()
    for k in ("kind", "doc", "message"):
        assert len(r[k]) == dg.MAX_FIELD + 1 and r[k].endswith("…"), k


def test_a_field_that_is_not_utf8_is_written_as_its_escape_and_the_row_is_kept():
    """Bytes that are not UTF-8, in a file name or a mail header, reach Python as a lone surrogate.
    The row keeps it as the text of its escape instead of being dropped."""
    assert dg.record("hub", "door-create", "work/\udcff.md", reason="by \udcff", n=1) is True
    [r] = rows()
    assert (r["doc"], r["reason"], r["n"]) == ("work/\\udcff.md", "by \\udcff", 1)
    assert "\\udcff" in dg.report()


def test_the_file_is_private():
    dg.record("hub", "start")
    assert stat.S_IMODE(dg.log_path().stat().st_mode) == 0o600
    assert stat.S_IMODE(dg.log_path().parent.stat().st_mode) == 0o700


def test_logging_never_raises(tmp_path, monkeypatch):
    dg.record("hub", "start", error=object())                 # a detail json cannot write
    assert not dg.log_path().exists()                         # and no half row either
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("SHEAF_HOME", str(blocker))
    dg.record("hub", "start")                                 # a state folder that cannot be made
    monkeypatch.setattr(dg, "log_path", lambda: 1 / 0)
    dg.record("hub", "start")                                 # anything else


def test_record_says_whether_the_row_was_written(tmp_path, monkeypatch):
    assert dg.record("agent", "note", note="x") is True
    assert len(rows()) == 1
    assert dg.record("hub", "start", error=object()) is False        # json cannot write it
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("SHEAF_HOME", str(blocker))
    assert dg.record("hub", "start") is False                        # a state folder that cannot be made


def test_the_file_becomes_diagnostics_1_at_the_limit_and_replaces_the_old_one(monkeypatch):
    monkeypatch.setattr(dg, "MAX_BYTES", 600)
    log = dg.log_path()
    for n in range(30):
        dg.record("hub", "row", n=n, pad="p" * 40)
    old = log.with_name("diagnostics.1.jsonl")
    assert old.exists()
    first = rows(old)
    assert [r["n"] for r in first] == sorted(r["n"] for r in first)
    all_n = [r["n"] for r in dg.read()]
    assert all_n == sorted(all_n) and all_n[-1] == 29
    assert len(all_n) < 30                     # the generation before the last one was replaced, not kept
    assert not log.with_name("diagnostics.2.jsonl").exists()


def test_read_and_report_span_the_rotated_file(monkeypatch):
    monkeypatch.setattr(dg, "MAX_BYTES", 400)
    for n in range(12):
        dg.record("hub", "early", n=n, pad="p" * 40)
    assert dg.log_path().with_name("diagnostics.1.jsonl").exists()
    dg.record("cli", "late", error="comment write failed")
    out = dg.report()
    assert "hub      early" in out and "cli      late" in out and "comment write failed" in out
    assert len(dg.read()) == len(dg.read(since_days=1))


def test_since_days_drops_older_rows():
    log = dg.log_path()
    log.parent.mkdir(parents=True)
    old = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - 10 * 86400))
    log.write_text(json.dumps({"at": old, "source": "hub", "kind": "old"}) + "\nnot json\n", encoding="utf-8")
    dg.record("hub", "new")
    assert [r["kind"] for r in dg.read()] == ["old", "new"]
    assert [r["kind"] for r in dg.read(since_days=2)] == ["new"]
    recent = dg.report(since_days=0.0001)
    assert "1 row(s)" in recent and "hub      new" in recent and "hub      old" not in recent


def test_the_report_counts_by_source_and_kind_and_lists_the_latest_40():
    for n in range(45):
        dg.record("hub", "save-409" if n % 3 else "job-failed", dg.log_path().parent / f"d{n}.md", error=f"e{n}")
    dg.record("page", "toast", message="save failed: boom")
    out = dg.report()
    assert out.startswith("46 row(s) in ")
    assert "hub      save-409" in out and "hub      job-failed" in out and "page     toast" in out
    latest = out.split("Latest 40:")[1].strip().splitlines()
    assert len(latest) == 40 and "save failed: boom" in latest[-1] and "d44.md" in latest[-2]


def test_the_json_report_is_the_rows():
    dg.record("agent", "note", note="waited 10 min, Tell never came")
    assert json.loads(dg.report(as_json=True)) == dg.read()
    assert json.loads(dg.report(as_json=True))[0]["note"].startswith("waited")


def test_an_empty_log_says_so():
    assert "nothing logged" in dg.report() and str(dg.log_path()) in dg.report()


WORKER = r'''
import sys
from sheafmd import diagnostics as dg
for n in range(int(sys.argv[2])):
    dg.record("hub", "burst", tag=sys.argv[1], n=n, a="a" * 2000, b="b" * 2000, c="c" * 2000, d="d" * 2000)
'''


def test_concurrent_writers_never_interleave_a_line():
    """Each row is about 8 KiB, past a buffered writer's chunk: one os.write keeps it whole."""
    procs = [subprocess.Popen([sys.executable, "-c", WORKER, tag, "60"]) for tag in "wxyz"]
    for p in procs:
        assert p.wait(timeout=120) == 0
    got = rows()
    assert len(got) == 240
    assert {(r["tag"], r["n"]) for r in got} == {(t, n) for t in "wxyz" for n in range(60)}
    assert all(len(r["a"]) == 2000 and r["d"] == "d" * 2000 for r in got)


@pytest.mark.parametrize("var, value, want", [
    ("CODEX_THREAD_ID", "thread-7", "thread-7"), ("CURSOR_CONVERSATION_ID", "conv-3", "conv-3"),
    ("OPENCODE", "1", None), ("GEMINI_CLI", "1", None),
])
def test_the_session_is_that_of_whichever_agent_is_detected(monkeypatch, var, value, want):
    monkeypatch.setenv(var, value)
    dg.record("agent", "note", note="x")
    assert rows()[0]["session"] == want


def test_reading_skips_lines_that_are_json_but_not_a_row():
    dg.record("hub", "start")
    with open(dg.log_path(), "a", encoding="utf-8") as f:
        f.write('123\n"text"\n[1, 2]\nnull\n')
    assert [r["kind"] for r in dg.read()] == ["start"]


def test_a_row_that_lacks_fields_is_still_reported():
    dg.log_path().parent.mkdir(parents=True)
    dg.log_path().write_text('{"at": "2026-10-14T10:00:00", "source": "hub"}\n{}\n{"kind": "k", "doc": 5}\n',
                              encoding="utf-8")
    out = dg.report()
    assert "3 row(s)" in out and "hub" in out and "?" in out


def test_a_since_further_back_than_a_clock_goes_means_everything():
    dg.record("hub", "start")
    assert [r["kind"] for r in dg.read(since_days=1e30)] == ["start"]
