"""What the hub keeps in the state folder (SPEC 4.2): small JSON files, and the texts it
handed pages (SPEC 7.4)."""
import json
import os
import stat
import subprocess
import sys
import time

import pytest

from sheafmd import paths
from sheafmd.hub import state
from sheafmd.source import md_hash


# ── JSON files ───────────────────────────────────────────────────────────────

def test_a_json_file_is_written_whole_and_private():
    f = paths.state_dir() / "docs.json"
    state.write_json(f, {"a": 1})
    assert json.loads(f.read_text()) == {"a": 1}
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert not list(f.parent.glob(".*tmp*"))


def test_a_missing_file_reads_as_the_default():
    assert state.read_json(paths.state_dir() / "nothing.json", {"d": 1}) == {"d": 1}


def test_a_file_that_is_not_json_is_set_aside_and_reads_as_the_default():
    f = paths.state_dir() / "seen.json"
    paths.private_dir(f.parent)
    f.write_text("{not json")
    assert state.read_json(f, {}) == {}
    assert not f.exists()
    assert (f.parent / "seen.json.corrupt").read_text() == "{not json"


def test_a_file_of_the_wrong_shape_is_set_aside_too():
    f = paths.state_dir() / "roots.json"
    paths.private_dir(f.parent)
    f.write_text("[1, 2]")
    assert state.read_json(f, {}, kind=dict) == {}
    assert (f.parent / "roots.json.corrupt").exists()


# ── the versions handed to pages ─────────────────────────────────────────────

ADDR = "notes/plan.md"


def test_doc_key_is_the_first_16_hex_of_the_sha256_of_the_address():
    import hashlib
    assert state.doc_key(ADDR) == hashlib.sha256(ADDR.encode()).hexdigest()[:16]


def test_a_text_is_kept_under_its_hash_and_found_again():
    v = state.Versions()
    h = v.put(ADDR, "# A\n\nText.\n")
    assert h == md_hash("# A\n\nText.\n")
    f = paths.state_dir() / "versions" / state.doc_key(ADDR) / f"{h}.md"
    assert f.read_text() == "# A\n\nText.\n"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert state.Versions().get(ADDR, h) == "# A\n\nText.\n"     # another process, after a restart


def test_an_unknown_hash_is_none():
    v = state.Versions()
    assert v.get(ADDR, "0" * 16) is None
    assert v.get("other/doc.md", md_hash("x")) is None


@pytest.mark.parametrize("bad", ["", "../../hub.key", "..", "a" * 15, "A" * 16, "g" * 16,
                                 "0" * 16 + "/../x", "0" * 17, None, 12, "0" * 15 + "\x00"])
def test_a_hash_that_is_not_16_hex_never_reaches_the_disk(bad):
    v = state.Versions()
    assert v.get(ADDR, bad) is None


def test_a_file_whose_content_is_not_its_name_is_not_believed():
    v = state.Versions()
    h = v.put(ADDR, "real\n")
    f = paths.state_dir() / "versions" / state.doc_key(ADDR) / f"{h}.md"
    f.write_text("tampered\n")
    assert v.get(ADDR, h) is None


def test_the_newest_60_of_a_document_are_kept():
    v = state.Versions()
    for i in range(70):
        v.put(ADDR, f"text {i}\n")
        d = paths.state_dir() / "versions" / state.doc_key(ADDR)
        os.utime(d / f"{md_hash(f'text {i}' + chr(10))}.md", (1000 + i, 1000 + i))
    files = sorted((paths.state_dir() / "versions" / state.doc_key(ADDR)).glob("*.md"))
    assert len(files) == 60
    assert v.get(ADDR, md_hash("text 69\n")) is not None
    assert v.get(ADDR, md_hash("text 10\n")) is not None
    assert v.get(ADDR, md_hash("text 9\n")) is None


def test_files_older_than_7_days_go_when_the_hub_starts():
    v = state.Versions()
    old, new = v.put(ADDR, "old\n"), v.put(ADDR, "new\n")
    d = paths.state_dir() / "versions" / state.doc_key(ADDR)
    eight_days = time.time() - 8 * 86400
    os.utime(d / f"{old}.md", (eight_days, eight_days))
    state.Versions().prune()
    assert v.get(ADDR, old) is None and v.get(ADDR, new) == "new\n"


def test_an_empty_document_folder_goes_with_its_last_file():
    v = state.Versions()
    h = v.put(ADDR, "old\n")
    d = paths.state_dir() / "versions" / state.doc_key(ADDR)
    old = time.time() - 9 * 86400
    os.utime(d / f"{h}.md", (old, old))
    v.prune()
    assert not d.exists()


def test_forgetting_by_prefix_takes_a_root_and_no_other():
    v = state.Versions()
    a, b, other = (v.put("notes/a.md", "# A\n"), v.put("notes/sub/b.md", "# B\n"),
                   v.put("notes-2/a.md", "# Other\n"))
    v.forget_prefix("notes/")
    assert v.get("notes/a.md", a) is None and v.get("notes/sub/b.md", b) is None
    assert v.get("notes-2/a.md", other) == "# Other\n"


def test_a_versions_folder_with_no_address_file_is_left_alone_by_forget_prefix():
    v = state.Versions()
    h = v.put(ADDR, "text\n")
    (paths.state_dir() / "versions" / state.doc_key(ADDR) / "address").unlink()
    v.forget_prefix(ADDR.partition("/")[0] + "/")
    assert v.get(ADDR, h) == "text\n"


def test_putting_the_same_text_again_keeps_one_file():
    v = state.Versions()
    v.put(ADDR, "same\n")
    v.put(ADDR, "same\n")
    assert len(list((paths.state_dir() / "versions" / state.doc_key(ADDR)).glob("*.md"))) == 1


# ── the versions pages keep (pins/) ──────────────────────────────────────────

def pins_dir():
    return paths.state_dir() / "versions" / state.doc_key(ADDR) / "pins"


def test_a_pinned_text_is_found_again_after_the_newest_60_have_moved_on():
    v = state.Versions()
    h = v.pin(ADDR, "pinned\n")
    assert h == md_hash("pinned\n")
    for i in range(state.VERSIONS_KEPT + 10):
        v.put(ADDR, f"text {i}\n")
    f = pins_dir() / f"{h}.md"
    assert f.read_text() == "pinned\n" and stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(pins_dir().stat().st_mode) == 0o700
    assert state.Versions().get(ADDR, h) == "pinned\n"           # another process, after a restart
    assert len(list(pins_dir().parent.glob("*.md"))) == state.VERSIONS_KEPT


def test_the_newest_16_pins_of_a_document_are_kept():
    v = state.Versions()
    for i in range(state.PINS_KEPT + 4):
        h = v.pin(ADDR, f"pin {i}\n")
        os.utime(pins_dir() / f"{h}.md", (1000 + i, 1000 + i))
    assert len(list(pins_dir().glob("*.md"))) == state.PINS_KEPT
    assert v.get(ADDR, md_hash("pin 3\n")) is None and v.get(ADDR, md_hash("pin 4\n")) == "pin 4\n"


def test_a_text_pinned_again_counts_from_then():
    v = state.Versions()
    first = v.pin(ADDR, "first\n")
    os.utime(pins_dir() / f"{first}.md", (1000, 1000))
    for i in range(state.PINS_KEPT - 1):
        h = v.pin(ADDR, f"pin {i}\n")
        os.utime(pins_dir() / f"{h}.md", (2000 + i, 2000 + i))
    v.pin(ADDR, "first\n")                                      # now the newest
    v.pin(ADDR, "one more\n")
    assert v.get(ADDR, first) == "first\n" and v.get(ADDR, md_hash("pin 0\n")) is None


def test_entries_that_are_not_versions_take_no_slot_among_the_16_pins_nor_the_60_versions():
    # A stray `notes.md` or a folder called `y.md` is not a version (`get` believes only a file named by the hash
    # of its text): it takes no slot and is deleted for none.
    v = state.Versions()
    valid = v.pin(ADDR, "valid\n")
    os.utime(pins_dir() / f"{valid}.md", (1000, 1000))
    for i in range(state.PINS_KEPT):
        foreign = pins_dir() / f"foreign-{i}.md"
        foreign.write_text("not a version\n")
        os.utime(foreign, (5000 + i, 5000 + i))
    (pins_dir() / "folder.md").mkdir()
    v.pin(ADDR, "another\n")
    assert v.get(ADDR, valid) == "valid\n"
    assert len(list(pins_dir().glob("foreign-*.md"))) == state.PINS_KEPT and (pins_dir() / "folder.md").is_dir()
    folder = pins_dir().parent
    first = v.put(ADDR, "first\n")
    os.utime(folder / f"{first}.md", (1000, 1000))
    for i in range(state.VERSIONS_KEPT):
        foreign = folder / f"foreign-{i}.md"
        foreign.write_text("not a version\n")
        os.utime(foreign, (5000 + i, 5000 + i))
    v.put(ADDR, "second\n")
    assert v.get(ADDR, first) == "first\n"


def test_a_folder_named_like_a_pin_is_not_taken_for_it():
    # `exists()` was true for it, so the text was neither written nor counted as written now: the pin was lost
    # without a word. The write now meets the folder and fails, which the hub keeps in memory only (live.pin).
    v = state.Versions()
    h = md_hash("pinned\n")
    (pins_dir() / f"{h}.md").mkdir(parents=True)
    with pytest.raises(OSError):
        v.pin(ADDR, "pinned\n")


def test_pins_older_than_7_days_go_when_the_hub_starts_and_their_folder_with_the_last():
    v = state.Versions()
    old, new = v.pin(ADDR, "old\n"), v.pin(ADDR, "new\n")
    eight_days = time.time() - 8 * 86400
    os.utime(pins_dir() / f"{old}.md", (eight_days, eight_days))
    state.Versions().prune()
    assert v.get(ADDR, old) is None and v.get(ADDR, new) == "new\n"
    os.utime(pins_dir() / f"{new}.md", (eight_days, eight_days))
    state.Versions().prune()
    assert not pins_dir().parent.exists()


def test_a_document_folder_that_holds_a_pin_stays_when_its_versions_go():
    v = state.Versions()
    old, kept = v.put(ADDR, "old\n"), v.pin(ADDR, "kept\n")
    nine_days = time.time() - 9 * 86400
    os.utime(pins_dir().parent / f"{old}.md", (nine_days, nine_days))
    v.prune()
    assert v.get(ADDR, old) is None and v.get(ADDR, kept) == "kept\n"


def test_forgetting_a_document_or_its_root_takes_its_pins():
    v = state.Versions()
    h = v.pin(ADDR, "pinned\n")
    v.forget(ADDR)
    assert v.get(ADDR, h) is None
    h = v.pin(ADDR, "pinned\n")
    v.forget_prefix(ADDR.partition("/")[0] + "/")
    assert v.get(ADDR, h) is None and not pins_dir().parent.exists()


def test_a_pin_whose_content_is_not_its_name_is_not_believed():
    v = state.Versions()
    h = v.pin(ADDR, "real\n")
    (pins_dir() / f"{h}.md").write_text("tampered\n")
    assert v.get(ADDR, h) is None


# ── docs.json: each rendered document's settings and target (SPEC 8.3) ───────

def test_a_documents_entry_is_kept_across_restarts():
    d = state.Docs()
    assert d.get(ADDR) == {}
    d.put(ADDR, {"path": "/x/plan.md", "toc": "never", "title": None})
    assert state.Docs().get(ADDR) == {"path": "/x/plan.md", "toc": "never", "title": None}
    assert json.loads((paths.state_dir() / "docs.json").read_text())[ADDR]["toc"] == "never"


def test_an_entry_handed_out_is_a_copy():
    d = state.Docs()
    d.put(ADDR, {"toc": "auto"})
    d.get(ADDR)["toc"] = "never"
    assert d.get(ADDR)["toc"] == "auto"


def test_forgetting_a_document_removes_its_entry():
    d = state.Docs()
    d.put(ADDR, {"toc": "auto"})
    d.put("other/b.md", {"toc": "auto"})
    d.forget_prefix("notes/")
    assert d.get(ADDR) == {} and d.get("other/b.md") == {"toc": "auto"}


# ── seen.json: how many messages of each thread the reader has seen (SPEC 8.7) ──

def test_seen_counts_only_go_up_and_survive_restarts():
    s = state.Seen()
    assert s.get(ADDR) == {}
    s.mark(ADDR, "c3", 2)
    s.mark(ADDR, "c3", 1)                          # an older tab: never lowers it
    s.mark(ADDR, "c4", 5)
    assert state.Seen().get(ADDR) == {"c3": 2, "c4": 5}
    assert state.Seen().get("other/b.md") == {}
    assert json.loads((paths.state_dir() / "seen.json").read_text()) == {ADDR: {"c3": 2, "c4": 5}}


# ── a second process changes the same file (SPEC 4.2): the offline `forget`, `sheaf roots` ──

def _other_process(code: str):
    """Run `code` in a second Python process on the same state folder (the test's env holds it)."""
    r = subprocess.run([sys.executable, "-c", "from sheafmd.hub import state\n" + code],
                       capture_output=True, text=True, env=os.environ.copy(), timeout=60)
    assert r.returncode == 0, r.stderr


def test_docs_opened_before_another_process_changed_the_file_keep_that_change():
    hub = state.Docs()
    hub.put("a/one.md", {"toc": "auto"})
    _other_process("d = state.Docs(); d.put('b/two.md', {'toc': 'off'}); d.forget_prefix('a/')")
    hub.put("c/three.md", {"toc": "on"})
    assert json.loads((paths.state_dir() / "docs.json").read_text()) == {
        "b/two.md": {"toc": "off"}, "c/three.md": {"toc": "on"}}


def test_seen_opened_before_another_process_changed_the_file_keeps_that_change():
    hub = state.Seen()
    hub.mark("a/one.md", "c1", 1)
    _other_process("s = state.Seen(); s.mark('b/two.md', 'c2', 4); s.forget_prefix('a/')")
    hub.mark("c/three.md", "c3", 2)
    assert json.loads((paths.state_dir() / "seen.json").read_text()) == {
        "b/two.md": {"c2": 4}, "c/three.md": {"c3": 2}}


def test_member_seen_opened_before_another_process_changed_the_file_keeps_that_change():
    hub = state.MemberSeen()
    hub.mark("m1", "a/one.md", "c1", 1)
    _other_process("s = state.MemberSeen(); s.mark('m2', 'b/two.md', 'c2', 4); s.forget_prefix('a/')")
    hub.mark("m1", "c/three.md", "c3", 2)
    assert json.loads((paths.state_dir() / "seen-members.json").read_text()) == {
        "m1": {"c/three.md": {"c3": 2}}, "m2": {"b/two.md": {"c2": 4}}}


def test_a_count_another_process_raised_is_not_lowered_by_this_one():
    hub = state.Seen()
    _other_process("state.Seen().mark('a/one.md', 'c1', 5)")
    hub.mark("a/one.md", "c1", 3)
    assert state.Seen().get("a/one.md") == {"c1": 5}


def test_processes_changing_docs_together_keep_every_entry():
    code = "d = state.Docs()\nfor j in range(15): d.put(f'r/{i}-{j}.md', {'toc': 'auto'})"
    procs = [subprocess.Popen([sys.executable, "-c", "from sheafmd.hub import state\n" + code.replace("{i}", str(i))],
                              stderr=subprocess.PIPE, text=True, env=os.environ.copy())
             for i in range(6)]
    for p in procs:
        _, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    assert len(json.loads((paths.state_dir() / "docs.json").read_text())) == 90


def test_each_store_takes_the_lock_the_spec_names():
    state.Docs().put("a/one.md", {})
    state.Seen().mark("a/one.md", "c1", 1)
    state.MemberSeen().mark("m1", "a/one.md", "c1", 1)
    assert {p.name for p in paths.locks_dir().glob("*.lock")} >= {"docs.lock", "seen.lock", "seen-members.lock"}
