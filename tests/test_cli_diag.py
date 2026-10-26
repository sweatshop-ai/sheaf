"""`sheaf diag`, `sheaf diag note` and `sheaf version` (SPEC 13, 15): no hub needed."""
import json
import time

import pytest
from helpers import brand_words_in, run_module, write

import sheafmd
from sheafmd import cli, diagnostics


def rows():
    return diagnostics.read()


def old_row(days, kind="old-row"):
    """A row written `days` days ago, put straight into the log file."""
    at = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - days * 86400))
    log = diagnostics.log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": at, "source": "hub", "kind": kind, "doc": None, "pid": 1,
                            "session": None}) + "\n")


# ── diag ────────────────────────────────────────────────────────────────────

def test_an_empty_log_says_so_and_names_the_file(sheaf):
    r = sheaf("diag")
    assert r.code == 0 and r.err == ""
    assert "nothing logged" in r.out and str(diagnostics.log_path()) in r.out


def test_diag_counts_by_source_and_kind_and_lists_the_latest_rows(work, sheaf):
    doc = write(work / "doc.md", "Text.\n")
    sheaf("reply", doc, "c1", "x")
    sheaf("reply", doc, "c2", "x")
    sheaf("comment", doc, "nothing like it", "x")
    out = sheaf("diag").out
    assert "3 row(s)" in out
    assert "   2  cli      reply-failed" in out and "   1  cli      comment-failed" in out
    assert "Latest 40:" in out and "doc.md" in out and "no comment c1 in this document" in out


def test_diag_json_prints_the_rows(work, sheaf):
    doc = write(work / "doc.md", "Text.\n")
    sheaf("resolve", doc, "c7")
    r = sheaf("diag", "--json")
    [row] = json.loads(r.out)
    assert (row["source"], row["kind"], row["doc"]) == ("cli", "resolve-failed", str(doc))
    assert json.loads(sheaf("diag", "--json", "--since", "1").out) == [row]


def test_diag_json_with_an_empty_log_is_an_empty_list(sheaf):
    assert json.loads(sheaf("diag", "--json").out) == []


def test_since_keeps_only_the_recent_rows(sheaf):
    old_row(10, "ten-days-ago")
    old_row(0.5, "half-a-day-ago")
    kinds = lambda *a: [r["kind"] for r in json.loads(sheaf("diag", "--json", *a).out)]
    assert kinds() == ["ten-days-ago", "half-a-day-ago"]
    assert kinds("--since", "2") == ["half-a-day-ago"]
    assert kinds("--since", "0.25") == []
    assert "nothing logged in the last 0.25 days" in sheaf("diag", "--since", "0.25").out


@pytest.mark.parametrize("bad", ["0", "-3", "abc", "nan", "inf", ""])
def test_a_since_that_is_not_a_number_of_days_is_a_usage_error(sheaf, bad):
    r = sheaf("diag", "--since", bad)
    assert r.code == 2 and "--since" in r.err and r.out == ""


def test_diag_reads_the_rotated_file_too(sheaf, monkeypatch):
    monkeypatch.setattr(diagnostics, "MAX_BYTES", 300)
    for n in range(8):
        diagnostics.record("hub", f"kind-{n}", error="e" * 80)
    kinds = lambda f: [json.loads(ln)["kind"] for ln in f.read_text(encoding="utf-8").splitlines()]
    rotated, current = kinds(diagnostics.log_path().with_name(diagnostics.ROTATED)), kinds(diagnostics.log_path())
    assert rotated and current
    assert [r["kind"] for r in json.loads(sheaf("diag", "--json").out)] == rotated + current


def test_diag_is_read_only(sheaf):
    sheaf("diag")
    assert not diagnostics.log_path().exists()


# ── diag note ───────────────────────────────────────────────────────────────

def test_a_note_is_recorded_as_an_agent_row(sheaf):
    r = sheaf("diag", "note", "waited 10 min, the Tell never came")
    assert r.code == 0 and r.out == f"  + noted in {diagnostics.log_path()}\n" and r.err == ""
    [row] = rows()
    assert (row["source"], row["kind"], row["doc"]) == ("agent", "note", None)
    assert row["note"] == "waited 10 min, the Tell never came"
    assert "waited 10 min" in sheaf("diag").out and "agent" in sheaf("diag").out


def test_a_note_about_a_file_records_its_absolute_path(work, sheaf, monkeypatch):
    doc = write(work / "doc.md", "Text.\n")
    monkeypatch.chdir(work)
    sheaf("diag", "note", "the page lost its tab", "doc.md")
    sheaf("diag", "note", "and again", doc)
    assert [r["doc"] for r in rows()] == [str(doc.resolve())] * 2


def test_a_note_about_a_file_that_is_not_there_is_still_recorded(work, sheaf):
    r = sheaf("diag", "note", "it was deleted under me", work / "gone.md")
    assert r.code == 0 and rows()[0]["doc"] == str((work / "gone.md").resolve())


def test_a_note_carries_the_session_of_an_agent(sheaf, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-42")
    sheaf("diag", "note", "x")
    assert rows()[0]["session"] == "sess-42"


@pytest.mark.parametrize("argv", [["diag", "note"], ["diag", "note", ""], ["diag", "note", "  \n"]])
def test_a_note_with_no_text_is_a_usage_error_and_writes_nothing(sheaf, argv):
    r = sheaf(*argv)
    assert r.code == 2 and rows() == []


def test_a_note_that_cannot_be_written_exits_1_and_says_so(sheaf, tmp_path, monkeypatch):
    blocker = write(tmp_path / "in-the-way", "a file, not a folder")
    monkeypatch.setenv("SHEAF_HOME", str(blocker))
    r = sheaf("diag", "note", "x")
    assert r.code == 1 and "could not be written" in r.err and "Traceback" not in r.err
    assert r.out == ""


def test_a_note_longer_than_the_field_limit_warns_that_it_was_cut(sheaf):
    r = sheaf("diag", "note", "n" * (diagnostics.MAX_FIELD + 50))
    assert r.code == 0 and "longer than 2000" in r.err
    assert len(rows()[0]["note"]) == diagnostics.MAX_FIELD + 1


def test_note_is_the_only_word_diag_takes(sheaf):
    r = sheaf("diag", "notes", "x")
    assert r.code == 2 and rows() == []


# ── version ─────────────────────────────────────────────────────────────────

def test_version_prints_the_version_of_sheaf(sheaf):
    r = sheaf("version")
    assert (r.code, r.out, r.err) == (0, f"sheaf {sheafmd.__version__}\n", "")


def test_version_takes_no_arguments(sheaf):
    r = sheaf("version", "now")
    assert r.code == 2 and r.out == ""


def test_the_hub_seam_is_empty_until_the_hub_exists():
    assert cli.hub_version() is None


def test_version_prints_the_hubs_version_when_the_seam_gives_one(sheaf, monkeypatch):
    monkeypatch.setattr(cli, "hub_version", lambda: "9.9.9")
    assert sheaf("version").out == f"sheaf {sheafmd.__version__}\nhub 9.9.9\n"


# ── as a real process, and the brand ────────────────────────────────────────

def test_a_real_process_notes_and_reports(work):
    r = run_module("diag", "note", "from a process", cwd=work)
    assert r.returncode == 0 and r.stderr == ""
    out = run_module("diag", cwd=work).stdout
    assert "from a process" in out
    assert json.loads(run_module("diag", "--json", cwd=work).stdout)[0]["note"] == "from a process"


def test_a_real_process_prints_the_version(work):
    r = run_module("version", cwd=work)
    assert (r.returncode, r.stdout, r.stderr) == (0, f"sheaf {sheafmd.__version__}\n", "")


def test_diag_and_version_output_is_free_of_the_brand(work, sheaf, tmp_path):
    doc = write(work / "doc.md", "Text.\n")
    seen = []
    for argv in (["diag"], ["diag", "note", "a note", doc], ["diag"], ["diag", "--json"],
                 ["version"], ["diag", "--help"], ["diag", "note", "--help"], ["version", "--help"]):
        r = sheaf(*argv)
        seen.append(r.out + r.err)
    assert all(s.strip() for s in seen)
    assert brand_words_in("\n".join(seen), tmp_path) == []


# ── what the review found ───────────────────────────────────────────────────

def test_a_since_further_back_than_a_clock_goes_lists_everything(sheaf):
    old_row(10, "ten-days-ago")
    r = sheaf("diag", "--json", "--since", "1e30")
    assert r.code == 0 and [x["kind"] for x in json.loads(r.out)] == ["ten-days-ago"]


def test_diag_survives_log_lines_that_are_not_rows(sheaf):
    diagnostics.record("agent", "note", note="first")
    with open(diagnostics.log_path(), "a", encoding="utf-8") as f:
        f.write('123\n{}\n[1]\n{"kind": "no-source"}\n')
    r = sheaf("diag")
    assert r.code == 0 and "Traceback" not in r.err and "first" in r.out
    assert sheaf("diag", "--json").code == 0


def test_a_note_about_a_path_with_an_unknown_home_is_recorded_as_written(work, sheaf):
    r = sheaf("diag", "note", "x", "~nosuchuser-sheaf/y.md")
    assert r.code == 0 and "Traceback" not in r.err
    assert rows()[0]["doc"].endswith("~nosuchuser-sheaf/y.md")


def test_notes_and_failed_writes_record_a_document_the_same_way(work, sheaf, monkeypatch):
    doc = write(work / "doc.md", "Text.\n")
    monkeypatch.chdir(work)
    sheaf("diag", "note", "n", "doc.md")
    sheaf("reply", "doc.md", "c1", "x")
    assert [r["doc"] for r in rows()] == [str(doc)] * 2
