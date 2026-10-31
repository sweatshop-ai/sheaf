"""Placement (SPEC 9.11 "Where a sheaf lives"): in proxy mode the hub keys a sheaf of the list's root by its logical
name `<client>/<project>/<name>.md`, and finds its file only when it reads or writes it: at that path when the sheaf
is open to the project, at `<client>/<project>/private/<owner short>/<name>.md` when it is its owner's alone. The
door's create lands at home; an update, a Share, its owner's withdrawal of it and the list's poll move the file, and
nothing else moves: the address, the versions, the read state and the render settings stay with the name. The
private path is no address. Through the handler in proxy mode, with the list on `work`: Thierry owns the sheaves,
Hans is a member of the project."""
import dataclasses
import os
import pwd
import subprocess
import threading
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from helpers import FRONT, Front, call, hub_rows

from sheafmd import _pandoc
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import place, projects, proxy, the_list, work as work_mod
from sheafmd.hub.state import INSIDE, Tokens, doc_key
from sheafmd.hub.visibility import front_matter
from sheafmd.source import md_hash

THIERRY = "503b2f77-83de-452c-817a-a357faf85929"
HANS = "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"
NAME = "2026-10-28-contract.md"
SHARED = f"thinkingtoo/tiroir/{NAME}"
HOME = f"thinkingtoo/tiroir/private/thierry/{NAME}"
MISSING = "thinkingtoo/tiroir/nothing.md"

PRIVATE = """---
issue: thinkingtoo/tt-tiroir#9
assistant: James
owner: thierry
sources: [library:doc-123]
---
# What the contract says

- [ ] Share

A quote from the contract.
"""
OPEN = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:thinkingtoo/tt-tiroir#9]")


def members(work):
    team = {THIERRY: {"name": "Thierry", "short": "thierry", "github": "tiroir", "roots": [str(work)],
                      "tokens": ["james-thierry"]},
            HANS: {"name": "Hans", "short": "hans", "github": "hanshermans", "roots": [str(work)],
                   "tokens": ["james-hans"]}}
    return proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                        "proxy_user": pwd.getpwuid(os.getuid()).pw_name, "members": team}, "the test")


def the_list_on(hub, root, tmp_path):
    hub.the_list = the_list.TheList(hub, the_list.parse({
        "root": str(root), "repo": "thinkingtoo/tt-tiroir", "project": 1,
        "token_file": str(tmp_path / "no-token")}, "the test"))


@pytest.fixture
def team(hub, browser, work, plan, tmp_path):
    hub.proxy = members(work)
    (work / "projects.toml").write_text('[projects."thinkingtoo/tiroir"]\nmembers = ["thierry", "hans"]\n'
                                        'status = "live"\n', encoding="utf-8")
    (work / "thinkingtoo" / "tiroir").mkdir(parents=True)
    the_list_on(hub, work, tmp_path)
    return Front(hub, browser.handler)


@pytest.fixture
def tokens():
    return {"thierry": Tokens().add("james-thierry", write=True), "hans": Tokens().add("james-hans", write=True)}


def put(team, work, rel, text):
    f = work / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    team.hub.roots.for_document(f)
    return f"work/{rel}"


def text_of(work, name=SHARED):
    """The text of the one file that holds the sheaf's name, at the project's path or in a private folder."""
    client, project, file = name.split("/")
    held = [p for p in [work / name, *(work / client / project / "private").glob(f"*/{file}")] if p.exists()]
    assert len(held) == 1, held
    return held[0].read_text(encoding="utf-8")


def tick(team, work, word, member, name=SHARED):
    """The page's save that ticks the first action `word` of the sheaf named `name`, as `member`."""
    text = text_of(work, name)
    n = [a[0] for a in the_list.read_sheaf(name, text).actions].index(word)
    edit = the_list.tick_edit(text, n, word)
    return team.post("/_/save", {"doc": f"work/{name}", "hash": md_hash(text), "edits": [edit]}, member=member)


def untick(team, work, word, member, name=SHARED, root="work", via=None):
    """The page's save that unticks the box `- [x] <word>`, as the page sends it: the block's HTML with that box
    no longer checked. `via`: a browser on the loopback port, the hub's own person, instead of `member`."""
    text = text_of(work, name)
    blocks = split_md_blocks(text)
    i = next(i for i, b in enumerate(blocks) if f"- [x] {word}" in b.content)
    soup = BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], blocks[i].content).stdout,
                         "html.parser")
    box = next(b for b in soup.select('input[type="checkbox"]') if word in b.parent.get_text())
    del box["checked"]
    body = {"doc": f"{root}/{name}", "hash": md_hash(text), "edits": [{"i": i, "html": str(soup)}]}
    return via.post("/_/save", body) if via is not None else team.post("/_/save", body, member=member)


def absent(browser, token, rel):
    """What the door answers `token` for a `read` of `rel`, with the name of a document that does not exist in its
    place, so two answers compare."""
    _, got = call(browser, "read", token=token, doc=f"work/{rel}")
    return got.replace(rel, "<doc>") if isinstance(got, str) else got


# ── the door's create lands at home ──────────────────────────────────────────

def test_a_door_create_of_an_owner_only_sheaf_lands_in_its_owners_private_folder(team, work, browser, tokens):
    is_error, got = call(browser, "create", token=tokens["thierry"], doc=f"work/{SHARED}", text=PRIVATE)
    assert not is_error, got
    assert got["doc"] == f"work/{SHARED}" and got["url"].endswith(f"/work/{SHARED}")       # its name, not its file
    assert front_matter((work / HOME).read_text(encoding="utf-8"))["visibility"] == "owner"
    assert not (work / SHARED).exists()


def test_a_door_create_of_an_open_sheaf_lands_at_the_project(team, work, browser, tokens):
    is_error, got = call(browser, "create", token=tokens["thierry"], doc=f"work/{SHARED}", text=OPEN)
    assert not is_error, got
    assert got["doc"] == f"work/{SHARED}" and (work / SHARED).exists()
    assert not (work / "thinkingtoo/tiroir/private").exists()


def test_a_door_create_of_an_owner_only_sheaf_whose_owner_has_no_short_is_refused(team, work, browser, tokens):
    """A short that cannot name a folder (`..`, which the config's rule lets through) is no short for it."""
    team.hub.proxy.members[THIERRY] = dataclasses.replace(team.hub.proxy.members[THIERRY], short="..")
    (work / "projects.toml").write_text('[projects."thinkingtoo/tiroir"]\nmembers = ["..", "hans"]\n'
                                        'status = "live"\n', encoding="utf-8")       # the project names that short
    is_error, got = call(browser, "create", token=tokens["thierry"], doc=f"work/{SHARED}",
                         text=PRIVATE.replace("owner: thierry", "owner: .."))
    assert is_error and "no owner of it has a short" in got, got
    assert not (work / SHARED).exists() and not (work / "thinkingtoo/tiroir/private").exists()


def test_a_name_held_by_a_private_sheaf_is_taken_for_every_token(team, work, browser, tokens):
    put(team, work, HOME, PRIVATE)
    for token in tokens.values():
        is_error, got = call(browser, "create", token=token, doc=f"work/{SHARED}", text=OPEN)
        assert is_error and got == f"work/{SHARED} exists already; `create` makes a new page, and `update` changes one."


@pytest.mark.parametrize("rel", [f"thinkingtoo/tiroir/private/thierry/{NAME}", f"thinkingtoo/tiroir/private/{NAME}",
                                 f"thinkingtoo/private/{NAME}"])
def test_a_create_that_names_a_private_folder_is_refused(team, work, browser, tokens, rel):
    (work / rel).parent.mkdir(parents=True, exist_ok=True)
    is_error, got = call(browser, "create", token=tokens["thierry"], doc=f"work/{rel}", text=OPEN)
    assert is_error and "the hub places owner-only sheaves itself" in got
    assert not (work / rel).exists()


def test_two_creates_of_one_name_with_different_homes_make_one_file(team, work, browser, tokens, monkeypatch):
    """The second create comes while the first makes its file: it waits on the name's lock, then finds the name
    taken. Without the lock it would see no file at either home and make the other."""
    from sheafmd import mcp
    real, answers = mcp.create_file, []

    def second():
        answers.append(call(browser, "create", token=tokens["thierry"], doc=f"work/{SHARED}", text=OPEN))

    def first_writes(top, rel, text):
        monkeypatch.setattr(mcp, "create_file", real)
        t = threading.Thread(target=second)
        t.start()
        t.join(1)
        real(top, rel, text)
        threads.append(t)
    threads = []
    monkeypatch.setattr(mcp, "create_file", first_writes)
    answers.append(call(browser, "create", token=tokens["thierry"], doc=f"work/{SHARED}", text=PRIVATE))
    threads[0].join(10)
    assert sorted(is_error for is_error, _ in answers) == [False, True], answers
    assert (work / HOME).exists() and not (work / SHARED).exists()


def test_a_move_out_of_private_leaves_the_folder_a_create_just_made(team, work, browser, tokens, monkeypatch):
    """The move of another sheaf out of `private/thierry` comes while a create of a new one there has made the
    folder and not yet its file: the move's tidying must not take the folder from under it."""
    from sheafmd import mcp
    from sheafmd.hub import place
    other = "thinkingtoo/tiroir/private/thierry/other.md"
    put(team, work, other, OPEN)
    (work / other).rename(work / "other.md")                    # out of the way while the create makes the folder
    real, threads = mcp.create_file, []

    def create_while_moving(top, rel, text):
        monkeypatch.setattr(mcp, "create_file", real)
        os.rename(work / "other.md", work / other)              # an open sheaf in the folder, the poll's to move
        t = threading.Thread(target=place.place, args=(team.hub, "work/thinkingtoo/tiroir/other.md"))
        t.start()
        t.join(1)
        threads.append(t)
        real(top, rel, text)
    monkeypatch.setattr(mcp, "create_file", create_while_moving)
    is_error, got = call(browser, "create", token=tokens["thierry"], doc=f"work/{SHARED}", text=PRIVATE)
    threads[0].join(10)
    assert not is_error, got
    assert (work / HOME).exists() and (work / "thinkingtoo/tiroir/other.md").exists()


# ── the logical name is the address; the private path is none ────────────────

def test_the_logical_name_reads_and_updates_the_private_sheaf_for_its_owner(team, work, browser, tokens):
    put(team, work, HOME, PRIVATE)
    is_error, got = call(browser, "read", token=tokens["thierry"], doc=f"work/{SHARED}")
    assert not is_error and got["doc"] == f"work/{SHARED}" and got["text"] == PRIVATE, got
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{SHARED}",
                         text=PRIVATE + "\nMore.\n", expected_hash=md_hash(PRIVATE))
    assert not is_error and got["doc"] == f"work/{SHARED}", got
    assert (work / HOME).read_text(encoding="utf-8").endswith("More.\n") and not (work / SHARED).exists()


def test_the_logical_name_is_absent_to_a_token_that_may_not_see_the_sheaf(team, work, browser, tokens):
    put(team, work, HOME, PRIVATE)
    assert absent(browser, tokens["hans"], SHARED) == absent(browser, tokens["hans"], MISSING)


def test_the_logical_name_is_the_page_of_the_private_sheaf_for_its_owner_and_a_404_to_hans(team, work):
    put(team, work, HOME, PRIVATE)
    assert team.get(f"/work/{SHARED}", member=THIERRY).status == 200
    hidden = team.get(f"/work/{SHARED}", member=HANS)
    missing = team.get(f"/work/{MISSING}", member=HANS)
    assert hidden.status == missing.status == 404 and hidden.body == missing.body


def test_a_private_path_is_no_address(team, work, browser, tokens):
    """No second entry for one file: the page, the door and its stream answer the private path as a document that
    does not exist, to its owner too."""
    put(team, work, HOME, PRIVATE)
    page, missing = team.get(f"/work/{HOME}", member=THIERRY), team.get(f"/work/{MISSING}", member=THIERRY)
    assert page.status == missing.status == 404 and page.body == missing.body
    assert team.get(f"/_/live?doc=work/{HOME}", member=THIERRY).status == 404
    assert absent(browser, tokens["thierry"], HOME) == absent(browser, tokens["thierry"], MISSING)
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{HOME}", text=PRIVATE + "x\n",
                         expected_hash=md_hash(PRIVATE))
    assert is_error and (work / HOME).read_text(encoding="utf-8") == PRIVATE


def test_the_index_names_a_private_sheaf_by_its_logical_name(team, work):
    put(team, work, HOME, PRIVATE)
    docs = [d["doc"] for r in team.get("/_/index.json", member=THIERRY).json()["roots"] for d in r["docs"]]
    assert f"work/{SHARED}" in docs and f"work/{HOME}" not in docs


def door_documents(browser, token=None):
    """The addresses the door's `documents` lists to `token` (the key without one), open threads or not."""
    is_error, got = call(browser, "documents", token=token, open_only=False)
    assert not is_error, got
    return [d["doc"] for d in got if "doc" in d]


def test_the_doors_documents_lists_an_owner_only_sheaf_by_its_name_to_its_owner_and_the_key(team, work, browser,
                                                                                               tokens):
    put(team, work, HOME, PRIVATE)
    for token in (tokens["thierry"], None):
        docs = door_documents(browser, token)
        assert f"work/{SHARED}" in docs and f"work/{HOME}" not in docs, docs
    docs = door_documents(browser, tokens["hans"])
    assert f"work/{SHARED}" not in docs and f"work/{HOME}" not in docs, docs

@pytest.mark.parametrize("rel", ["thinkingtoo/tiroir/private/readme.md",
                                 "thinkingtoo/tiroir/private/thierry/sub/note.md",
                                 "thinkingtoo/tiroir/private/thierry/sub/deeper/note.md"])
def test_every_path_under_a_projects_private_folder_is_no_address(team, work, browser, tokens, rel):
    """Not only a private home: a file anywhere under `private/` is no document, to the page, the index and the
    door, for the key and its owner too."""
    put(team, work, rel, OPEN)
    page, missing = team.get(f"/work/{rel}", member=THIERRY), team.get(f"/work/{MISSING}", member=THIERRY)
    assert page.status == missing.status == 404 and page.body == missing.body
    docs = [d["doc"] for r in team.get("/_/index.json", member=THIERRY).json()["roots"] for d in r["docs"]]
    assert f"work/{rel}" not in docs, docs
    for token in (tokens["thierry"], None):
        assert f"work/{rel}" not in door_documents(browser, token)
    assert absent(browser, tokens["thierry"], rel) == absent(browser, tokens["thierry"], MISSING)
    assert absent(browser, None, rel) == absent(browser, None, MISSING)

def test_a_private_sheaf_is_a_sheaf_of_the_list_for_work_on_this_by_its_name_only(team, work):
    assert work_mod.is_sheaf(team.hub, f"work/{SHARED}")
    assert not work_mod.is_sheaf(team.hub, f"work/{HOME}")


# ── a door update moves the file ─────────────────────────────────────────────

def test_a_door_update_that_closes_a_sheaf_moves_its_file_into_private(team, work, browser, tokens):
    put(team, work, SHARED, OPEN)
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{SHARED}",
                         text=PRIVATE, expected_hash=md_hash(OPEN))
    assert not is_error, got
    assert got["doc"] == f"work/{SHARED}" and got["url"].endswith(f"/work/{SHARED}")
    assert not (work / SHARED).exists()
    assert front_matter((work / HOME).read_text(encoding="utf-8"))["visibility"] == "owner"


# ── Share moves the file out, its owner's withdrawal moves it back ───────────

def test_the_owners_share_moves_the_file_out_of_private(team, work):
    put(team, work, HOME, PRIVATE)
    got = tick(team, work, "Share", THIERRY)
    assert got.status == 200, got.text
    assert "moved" not in got.json()                                   # the address stays
    assert not (work / HOME).exists() and "- [x] Share" in (work / SHARED).read_text(encoding="utf-8")
    assert team.get(f"/work/{SHARED}", member=HANS).status == 200


def test_a_move_renders_the_page_again_from_the_new_folder(team, work):
    """Codex P1: the page rendered from private/<owner>/ embeds a relative image of that folder; after Share moves
    the file, the same text resolves the image against the shared folder, so the private image is no longer sent."""
    from PIL import Image
    put(team, work, HOME, PRIVATE.replace("A quote from the contract.", "![seal](seal.png)"))
    Image.new("RGB", (8, 8), (200, 10, 10)).save(work / "thinkingtoo/tiroir/private/thierry/seal.png", "PNG")
    assert "data:image/png;base64," in team.get(f"/work/{SHARED}", member=THIERRY).text
    assert tick(team, work, "Share", THIERRY).status == 200
    page = team.get(f"/work/{SHARED}", member=HANS)
    assert page.status == 200
    assert "data:image/png;base64," not in page.text and "missing image: seal.png" in page.text


def test_the_owner_unticking_share_closes_the_sheaf_and_moves_its_file_back(team, work):
    put(team, work, HOME, PRIVATE)
    tick(team, work, "Share", THIERRY)
    got = untick(team, work, "Share", THIERRY)
    assert got.status == 200, got.text
    assert "moved" not in got.json()
    text = (work / HOME).read_text(encoding="utf-8")
    fm = front_matter(text)
    assert fm["visibility"] == "owner" and "shared" not in fm and "- [ ] Share" in text
    assert not (work / SHARED).exists()
    assert team.get(f"/work/{SHARED}", member=HANS).status == 404


def test_the_hubs_own_person_unticking_share_on_the_loopback_port_closes_the_sheaf_again(team, work, browser):
    """Codex P2: the loopback person is no member, and reads every file; the untick still withdraws the Share."""
    put(team, work, HOME, PRIVATE)
    tick(team, work, "Share", THIERRY)
    got = untick(team, work, "Share", None, via=browser)
    assert got.status == 200, got.text
    text = (work / HOME).read_text(encoding="utf-8")
    fm = front_matter(text)
    assert fm["visibility"] == "owner" and "shared" not in fm and "- [ ] Share" in text
    assert not (work / SHARED).exists()


def test_a_member_who_is_not_the_owner_cannot_untick_share(team, work):
    put(team, work, HOME, PRIVATE)
    tick(team, work, "Share", THIERRY)
    before = (work / SHARED).read_text(encoding="utf-8")
    got = untick(team, work, "Share", HANS)
    assert got.status == 409 and got.json()["error"] == "Only the owner of this sheaf can withdraw its Share."
    assert (work / SHARED).read_text(encoding="utf-8") == before


def test_a_merged_save_that_unticks_share_follows_the_same_rule(team, work):
    """7.3: a save made against an older text is merged onto the file's, and its untick is still the owner's alone."""
    put(team, work, SHARED, OPEN.replace("- [ ] Share", "- [x] Share"))
    assert team.get(f"/work/{SHARED}", member=HANS).status == 200            # the page: its text is a version
    older = (work / SHARED).read_text(encoding="utf-8")
    blocks = split_md_blocks(older)
    i = next(i for i, b in enumerate(blocks) if "- [x] Share" in b.content)
    soup = BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5"], blocks[i].content).stdout, "html.parser")
    del soup.select_one('input[type="checkbox"]')["checked"]
    now = older.replace("A quote from the contract.", "A quote, changed elsewhere.")
    (work / SHARED).write_text(now, encoding="utf-8")
    got = team.post("/_/save", {"doc": f"work/{SHARED}", "hash": md_hash(older),
                                "edits": [{"i": i, "html": str(soup)}]}, member=HANS)
    assert got.status == 409 and got.json()["error"] == "Only the owner of this sheaf can withdraw its Share."
    assert (work / SHARED).read_text(encoding="utf-8") == now


def rewrite_untick(team, work, member, word="Share"):
    """A save that unticks `word` by rewriting its block through pandoc: the box unchecked and an item added, so the
    edit is no tick of 7.2."""
    text = text_of(work)
    blocks = split_md_blocks(text)
    i = next(i for i, b in enumerate(blocks) if f"- [x] {word}" in b.content)
    soup = BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5"], blocks[i].content).stdout, "html.parser")
    del next(b for b in soup.select('input[type="checkbox"]') if word in b.parent.get_text())["checked"]
    item = soup.new_tag("li")
    item.string = "Also this."
    soup.select_one("ul").append(item)
    return team.post("/_/save", {"doc": f"work/{SHARED}", "hash": md_hash(text),
                                 "edits": [{"i": i, "html": str(soup)}]}, member=member)


def test_a_rewrite_that_unticks_share_is_refused_to_a_member_who_is_not_the_owner(team, work):
    put(team, work, HOME, PRIVATE)
    tick(team, work, "Share", THIERRY)
    before = (work / SHARED).read_text(encoding="utf-8")
    got = rewrite_untick(team, work, HANS)
    assert got.status == 409 and got.json()["error"] == "Only the owner of this sheaf can withdraw its Share."
    assert (work / SHARED).read_text(encoding="utf-8") == before


def test_the_owners_rewrite_that_unticks_share_withdraws_it(team, work):
    put(team, work, HOME, PRIVATE)
    tick(team, work, "Share", THIERRY)
    got = rewrite_untick(team, work, THIERRY)
    assert got.status == 200, got.text
    text = (work / HOME).read_text(encoding="utf-8")
    assert front_matter(text)["visibility"] == "owner" and "Also this." in text and not (work / SHARED).exists()


# ── a one-off stays pressed (#108) ────────────────────────────────────────────

PRESSED = OPEN.replace("- [ ] Share", "- [x] Approve\n- [ ] Share")
REFUSED = "Approve is pressed once: its tick cannot be taken back."


def the_block(text, word):
    """(the number of the block of `text` that holds `- [x] <word>`, its HTML as the page draws it)."""
    blocks = split_md_blocks(text)
    i = next(i for i, b in enumerate(blocks) if f"- [x] {word}" in b.content)
    return i, BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5"], blocks[i].content).stdout, "html.parser")


@pytest.mark.parametrize("member", [THIERRY, HANS], ids=["owner", "member"])
def test_a_save_that_unticks_a_one_off_is_refused_and_writes_nothing(team, work, member):
    put(team, work, SHARED, PRESSED)
    got = untick(team, work, "Approve", member)
    assert got.status == 409 and got.json()["error"] == REFUSED
    assert (work / SHARED).read_text(encoding="utf-8") == PRESSED


def test_the_hubs_own_person_cannot_untick_a_one_off_either(team, work, browser):
    put(team, work, SHARED, PRESSED)
    got = untick(team, work, "Approve", None, via=browser)
    assert got.status == 409 and got.json()["error"] == REFUSED
    assert (work / SHARED).read_text(encoding="utf-8") == PRESSED


def test_a_rewrite_that_unticks_a_one_off_is_refused(team, work):
    put(team, work, SHARED, PRESSED)
    got = rewrite_untick(team, work, THIERRY, "Approve")
    assert got.status == 409 and got.json()["error"] == REFUSED
    assert (work / SHARED).read_text(encoding="utf-8") == PRESSED


def test_a_merged_save_that_unticks_a_one_off_is_refused(team, work):
    put(team, work, SHARED, PRESSED)
    assert team.get(f"/work/{SHARED}", member=HANS).status == 200            # the page: its text is a version
    i, soup = the_block(PRESSED, "Approve")
    del next(b for b in soup.select('input[type="checkbox"]') if "Approve" in b.parent.get_text())["checked"]
    now = PRESSED.replace("A quote from the contract.", "A quote, changed elsewhere.")
    (work / SHARED).write_text(now, encoding="utf-8")
    got = team.post("/_/save", {"doc": f"work/{SHARED}", "hash": md_hash(PRESSED),
                                "edits": [{"i": i, "html": str(soup)}]}, member=HANS)
    assert got.status == 409 and got.json()["error"] == REFUSED
    assert (work / SHARED).read_text(encoding="utf-8") == now


def test_a_save_that_takes_a_ticked_one_off_out_writes(team, work):
    """Only an untick is refused: a box taken out, with no other box of its word left, leaves no action to press
    again, as for Share (9.11)."""
    put(team, work, SHARED, PRESSED)
    i, soup = the_block(PRESSED, "Approve")
    next(li for li in soup.select("li") if "Approve" in li.get_text()).decompose()
    got = team.post("/_/save", {"doc": f"work/{SHARED}", "hash": md_hash(PRESSED),
                                "edits": [{"i": i, "html": str(soup)}]}, member=THIERRY)
    assert got.status == 200, got.text
    assert "Approve" not in (work / SHARED).read_text(encoding="utf-8")


def test_the_lists_tick_of_share_moves_the_file(team, work):
    put(team, work, HOME, PRIVATE)
    read = md_hash((work / HOME).read_text(encoding="utf-8"))          # the text the list read
    got = team.post("/_/tick", {"doc": f"work/{SHARED}", "action": 0, "word": "Share", "hash": read}, member=THIERRY)
    assert got.status == 200, got.text
    assert "moved" not in got.json() and (work / SHARED).exists() and not (work / HOME).exists()


def test_the_untick_is_refused_outside_the_list_too(team, work, tmp_path):
    """#40 holds for every root: the list only decides where the file goes."""
    other = tmp_path / "other"
    both = [str(work), str(other)]
    team.hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                                  "proxy_user": pwd.getpwuid(os.getuid()).pw_name, "members": {
                                      THIERRY: {"name": "Thierry", "short": "thierry", "roots": both},
                                      HANS: {"name": "Hans", "short": "hans", "roots": both}}}, "the test")
    rel = "a/b/x.md"
    f = other / rel
    f.parent.mkdir(parents=True)
    (other / "top.md").write_text("# Top\n", encoding="utf-8")
    team.hub.roots.for_document(other / "top.md")
    f.write_text(OPEN.replace("- [ ] Share", "- [x] Share"), encoding="utf-8")
    text = f.read_text(encoding="utf-8")
    blocks = split_md_blocks(text)
    i = next(i for i, b in enumerate(blocks) if "- [x] Share" in b.content)
    soup = BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5"], blocks[i].content).stdout, "html.parser")
    del soup.select_one('input[type="checkbox"]')["checked"]
    got = team.post("/_/save", {"doc": f"other/{rel}", "hash": md_hash(text), "edits": [{"i": i, "html": str(soup)}]},
                    member=HANS)
    assert got.status == 409 and f.read_text(encoding="utf-8") == text


# ── the poll places what is not at home ──────────────────────────────────────

def test_the_poll_moves_an_owner_only_sheaf_into_private_and_an_open_one_out(team, work):
    put(team, work, SHARED, PRIVATE)
    put(team, work, "thinkingtoo/tiroir/private/thierry/open.md", OPEN)
    team.hub.the_list.poll()
    assert (work / HOME).exists() and not (work / SHARED).exists()
    assert (work / "thinkingtoo/tiroir/open.md").exists()
    assert not (work / "thinkingtoo/tiroir/private/thierry/open.md").exists()


QUARANTINE = f"thinkingtoo/tiroir/private/~unplaced/{NAME}"
NOBODY = PRIVATE.replace("owner: thierry", "owner: nobody")


def test_an_owner_only_sheaf_with_no_owner_that_has_a_short_goes_to_quarantine_and_says_why(team, work):
    """Not at the project's path, where the Library's project glob would file it for the whole project (#61)."""
    put(team, work, SHARED, NOBODY)
    team.hub.the_list.poll()
    assert not (work / SHARED).exists() and (work / QUARANTINE).read_text(encoding="utf-8") == NOBODY
    rows = hub_rows("place-refused")
    assert [r["doc"] for r in rows] == [f"work/{SHARED}"] and "owner" in rows[0]["why"]
    assert rows[0]["quarantined"] is True, rows


def test_a_quarantined_sheaf_keeps_its_name_and_its_path_is_no_address(team, work, browser, tokens):
    put(team, work, SHARED, NOBODY)
    team.hub.the_list.poll()
    root = team.hub.roots.get("work")
    assert place.physical(team.hub, root, SHARED) == QUARANTINE
    assert absent(browser, tokens["hans"], QUARANTINE) == absent(browser, tokens["hans"], MISSING)
    assert team.get(f"/work/{QUARANTINE}", member=HANS).status == 404


def test_a_quarantined_sheaf_goes_home_once_it_has_one_and_the_quarantine_folder_goes(team, work):
    put(team, work, SHARED, NOBODY)
    team.hub.the_list.poll()
    (work / QUARANTINE).write_text(PRIVATE, encoding="utf-8")         # an owner with a short now
    team.hub.the_list.poll()
    assert (work / HOME).read_text(encoding="utf-8") == PRIVATE and not (work / QUARANTINE).exists()
    assert not (work / "thinkingtoo/tiroir/private/~unplaced").exists()


def test_a_quarantined_sheaf_opened_to_the_project_goes_to_the_projects_path(team, work):
    put(team, work, SHARED, NOBODY)
    team.hub.the_list.poll()
    (work / QUARANTINE).write_text(OPEN, encoding="utf-8")
    team.hub.the_list.poll()
    assert (work / SHARED).read_text(encoding="utf-8") == OPEN and not (work / QUARANTINE).exists()


def test_a_sheaf_open_to_the_project_is_never_quarantined(team, work):
    put(team, work, SHARED, OPEN.replace("owner: thierry", "owner: nobody"))
    team.hub.the_list.poll()
    assert (work / SHARED).exists() and not (work / QUARANTINE).exists() and not hub_rows("place-refused")


def test_an_owner_only_sheaf_that_loses_every_owner_with_a_short_leaves_its_old_owners_folder(team, work):
    """At `private/thierry/` the owner's Library glob `*/*/private/thierry/**` files it for `user:thierry`, who no
    longer owns it (#66): it goes to quarantine at the next poll, as one at the project's path does (#61)."""
    put(team, work, SHARED, PRIVATE)
    team.hub.the_list.poll()
    assert (work / HOME).exists()
    (work / HOME).write_text(NOBODY, encoding="utf-8")
    team.hub.the_list.poll()
    assert (work / QUARANTINE).read_text(encoding="utf-8") == NOBODY
    assert not (work / HOME).exists() and not (work / "thinkingtoo/tiroir/private/thierry").exists()
    rows = hub_rows("place-refused")
    assert [r["doc"] for r in rows] == [f"work/{SHARED}"] and rows[0]["quarantined"] is True, rows


def test_a_sheaf_in_the_folder_of_an_owner_it_still_has_stays_when_its_new_home_cannot_be_made(team, work,
                                                                                               monkeypatch):
    """Its folder's owner's Library glob files it for one of its owners, so it is not quarantined (#66): it waits
    there for its home, as before."""
    hans = PRIVATE.replace("owner: thierry", "owner: hans")
    put(team, work, SHARED, hans)
    team.hub.the_list.poll()
    at_hans = f"thinkingtoo/tiroir/private/hans/{NAME}"
    assert (work / at_hans).exists()
    # Owned by both now, and its front matter names neither: its home is the first in the config's order, thierry's.
    monkeypatch.setattr(team.hub, "assignees", lambda address, fm: ["hanshermans", "tiroir"])
    (work / at_hans).write_text(NOBODY, encoding="utf-8")
    (work / "thinkingtoo/tiroir/private/thierry").write_text("", encoding="utf-8")       # no folder can be made
    team.hub.the_list.poll()
    assert (work / at_hans).read_text(encoding="utf-8") == NOBODY and not (work / QUARANTINE).exists()
    assert [r.get("quarantined") for r in hub_rows("place-refused")] == [None]


def test_a_sheaf_already_in_quarantine_that_still_has_no_home_stays_there(team, work):
    put(team, work, SHARED, NOBODY)
    team.hub.the_list.poll()
    team.hub.the_list.poll()
    assert (work / QUARANTINE).read_text(encoding="utf-8") == NOBODY
    assert [r["quarantined"] for r in hub_rows("place-refused")] == [True]


def test_the_quarantine_folder_is_no_members_short():
    """No `short` can name it, so no owner's Library glob `*/*/private/<short>/**` reads it, and it is no hidden
    folder, which the listing would leave out (8.6)."""
    folder = QUARANTINE.split("/")[3]
    assert not proxy._SHORT_RE.fullmatch(folder) and not folder.startswith(".")


def test_a_stuck_sheaf_is_one_place_refused_row_per_hub_run(team, work):
    put(team, work, SHARED, PRIVATE.replace("owner: thierry", "owner: nobody"))
    team.hub.the_list.poll()
    team.hub.the_list.poll()
    assert [r["doc"] for r in hub_rows("place-refused")] == [f"work/{SHARED}"]


def test_two_files_that_hold_one_name_are_refused_and_left_as_they_are(team, work, browser, tokens):
    """Made by hand: one at the project's path, one in a private folder. The name answers as a document that does
    not exist, to the page and to the door, a create of it is refused, a diagnostics row says why, and the hub
    repairs nothing: no move, no write."""
    hans = f"thinkingtoo/tiroir/private/hans/{NAME}"
    put(team, work, SHARED, PRIVATE)
    put(team, work, hans, PRIVATE.replace("owner: thierry", "owner: hans"))
    page, missing = team.get(f"/work/{SHARED}", member=THIERRY), team.get(f"/work/{MISSING}", member=THIERRY)
    assert page.status == missing.status == 404 and page.body == missing.body
    assert absent(browser, tokens["thierry"], SHARED) == absent(browser, tokens["thierry"], MISSING)
    is_error, got = call(browser, "create", token=tokens["thierry"], doc=f"work/{SHARED}", text=OPEN)
    assert is_error and "exists already" in got, got
    team.hub.the_list.poll()
    assert (work / SHARED).read_text(encoding="utf-8") == PRIVATE and not (work / HOME).exists()
    assert (work / hans).read_text(encoding="utf-8") == PRIVATE.replace("owner: thierry", "owner: hans")
    rows = hub_rows("place-refused")
    assert [r["doc"] for r in rows] == [f"work/{SHARED}"] and "held by 2 files" in rows[0]["why"], rows


def test_the_owner_is_the_front_matters_owner_when_it_is_one_of_the_owners(team, work):
    put(team, work, SHARED, PRIVATE.replace("owner: thierry", "owner: hans"))
    team.hub.the_list.poll()
    assert (work / f"thinkingtoo/tiroir/private/hans/{NAME}").exists()


def test_nothing_moves_outside_the_lists_root_or_below_project_depth(team, work):
    put(team, work, "thinkingtoo/tiroir/notes/deep.md", PRIVATE)
    team.hub.the_list.poll()
    assert (work / "thinkingtoo/tiroir/notes/deep.md").exists()


def test_nothing_moves_in_loopback_mode(team, work, browser):
    team.hub.proxy = None
    put(team, work, SHARED, PRIVATE)
    team.hub.the_list.poll()
    assert (work / SHARED).exists()


# ── what the hub keeps of a sheaf stays with its name ────────────────────────

def test_the_read_state_and_render_settings_stay_with_the_name_when_the_file_moves(team, work):
    put(team, work, SHARED, PRIVATE)
    team.hub.member_seen.mark(THIERRY, f"work/{SHARED}", "c1", 2)
    team.hub.seen.mark(f"work/{SHARED}", "c1", 3)
    team.hub.docs.put(f"work/{SHARED}", {"title": "The contract"})
    team.hub.the_list.poll()
    assert (work / HOME).exists()
    assert team.hub.member_seen.get(THIERRY, f"work/{SHARED}") == {"c1": 2}
    assert team.hub.seen.get(f"work/{SHARED}") == {"c1": 3}
    assert team.hub.docs.get(f"work/{SHARED}")["title"] == "The contract"


def test_a_save_against_the_page_before_the_move_still_merges_into_the_moved_file(team, work):
    put(team, work, SHARED, PRIVATE)
    assert team.get(f"/work/{SHARED}", member=THIERRY).status == 200      # the page: its text is a version
    team.hub.the_list.poll()
    assert (work / HOME).exists() and not (work / SHARED).exists()
    assert team.hub.versions.get(f"work/{SHARED}", md_hash(PRIVATE)) == PRIVATE
    i = next(i for i, b in enumerate(split_md_blocks(PRIVATE)) if "A quote" in b.content)
    got = team.post("/_/save", {"doc": f"work/{SHARED}", "hash": md_hash(PRIVATE),
                                "edits": [{"i": i, "html": "<p>A quote, edited.</p>"}]}, member=THIERRY)
    assert got.status == 200 and "moved" not in got.json(), got.text
    assert "A quote, edited." in (work / HOME).read_text(encoding="utf-8") and not (work / SHARED).exists()


def test_an_open_stream_stays_open_across_a_move_and_hears_the_next_change(team, work, browser, tokens):
    put(team, work, SHARED, PRIVATE)
    stream = team.get(f"/_/live?doc=work/{SHARED}", member=THIERRY).stream
    stream.drain()
    team.hub.the_list.poll()
    assert (work / HOME).exists()
    assert [name for name, _ in stream.drain() if name in ("moved", "gone")] == []
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{SHARED}",
                         text=PRIVATE + "\nMore.\n", expected_hash=md_hash(PRIVATE))
    assert not is_error, got
    assert "changed" in [name for name, _ in stream.drain()]


def test_a_comment_written_as_the_poll_moves_the_file_lands_in_the_one_file(team, work, monkeypatch):
    """A document's write holds the name's lock from finding its file to the file written: the poll's move that
    comes between waits, so the write never makes a second file where the first one was."""
    from sheafmd import comments as rdc
    from sheafmd.hub import live
    put(team, work, SHARED, PRIVATE)                           # written before the rule: the poll would move it
    assert team.get(f"/work/{SHARED}", member=THIERRY).status == 200
    real, threads = live.rds.update_file, []

    def poll_then_write(path, change, **kw):
        monkeypatch.setattr(live.rds, "update_file", real)
        t = threading.Thread(target=team.hub.the_list.poll)
        t.start()
        t.join(1)
        threads.append(t)
        return real(path, change, **kw)
    monkeypatch.setattr(live.rds, "update_file", poll_then_write)
    blk, start, end = rdc.find_quote(PRIVATE, "A quote")
    got = team.post("/_/comment", {"doc": f"work/{SHARED}", "op": "add", "hash": md_hash(PRIVATE), "block": blk,
                                   "start": start, "end": end, "quote": "A quote", "body": "Which clause?"},
                    member=THIERRY)
    threads[0].join(10)
    assert got.status == 200, got.text
    assert not (work / SHARED).exists() and "Which clause?" in (work / HOME).read_text(encoding="utf-8")


# ── a project named private ──────────────────────────────────────────────────

def test_a_project_named_private_is_refused(tmp_path):
    (tmp_path / projects.FILE).write_text('[projects."acme/private"]\nmembers = ["a"]\nstatus = "live"\n',
                                          encoding="utf-8")
    with pytest.raises(projects.Invalid, match="private"):
        projects.read(tmp_path)


# ── one commit per move ──────────────────────────────────────────────────────

def git(at, *args):
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True, text=True).stdout


def committing(hub, browser, tmp_path, first=PRIVATE, at=SHARED, ignore=""):
    """A root that commits, with `versions = "root"`, the list on it and `first` committed at `at`; `ignore` is its
    `.gitignore`."""
    repo = tmp_path / "sheaves"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "the box")
    git(repo, "config", "user.email", "box@example.com")
    (repo / ".sheaf.toml").write_text('versions = "root"\ncommit = true\n', encoding="utf-8")
    (repo / "projects.toml").write_text('[projects."thinkingtoo/tiroir"]\nmembers = ["thierry"]\nstatus = "live"\n',
                                        encoding="utf-8")
    (repo / at).parent.mkdir(parents=True)
    (repo / at).write_text(first, encoding="utf-8")
    if ignore:
        (repo / ".gitignore").write_text(ignore, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    hub.proxy = members(repo)
    hub.roots.for_document(repo / at)
    the_list_on(hub, repo, tmp_path)
    return Front(hub, browser.handler), repo


def test_a_move_is_one_commit_of_both_paths_and_the_versions_stay_under_the_name(hub, browser, tmp_path):
    box, repo = committing(hub, browser, tmp_path)
    assert box.get(f"/sheaves/{SHARED}", member=THIERRY).status == 200          # a version, inside the root
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the version")
    hub.the_list.poll()
    assert git(repo, "log", "-1", "--format=%s|%an").strip() == f"move: {SHARED} -> {HOME}|sheaf"
    files = set(git(repo, "show", "--no-renames", "--name-status", "--format=", "HEAD").splitlines())
    assert files == {f"D\t{SHARED}", f"A\t{HOME}"}, files
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / INSIDE / doc_key(SHARED) / "address").read_text(encoding="utf-8") == SHARED
    assert not (repo / INSIDE / doc_key(HOME)).exists()


def test_a_move_to_quarantine_is_one_commit_of_both_paths(hub, browser, tmp_path):
    _, repo = committing(hub, browser, tmp_path, first=NOBODY)
    hub.the_list.poll()
    assert git(repo, "log", "-1", "--format=%s|%an").strip() == f"move: {SHARED} -> {QUARANTINE}|sheaf"
    files = set(git(repo, "show", "--no-renames", "--name-status", "--format=", "HEAD").splitlines())
    assert files == {f"D\t{SHARED}", f"A\t{QUARANTINE}"}, files


def test_a_root_that_ignores_its_private_folders_keeps_an_unplaceable_sheaf_where_it_is(hub, browser, tmp_path):
    """Its quarantine is under `private/` too: a sheaf moved there would leave the list (8.6)."""
    _, repo = committing(hub, browser, tmp_path, first=NOBODY, ignore="*/*/private/\n")
    hub.the_list.poll()
    assert (repo / SHARED).exists() and not (repo / QUARANTINE).exists()
    assert [r.get("quarantined") for r in hub_rows("place-refused")] == [False]


def test_a_write_to_a_sheaf_that_could_not_go_home_takes_it_to_quarantine_in_one_commit(hub, browser, tmp_path):
    """Not at the home of the text on disk (its owner's private folder is ignored), the door's update is written as
    before (9.11), and its move goes to quarantine, with the new text, in the write's one `move:` commit."""
    _, repo = committing(hub, browser, tmp_path, ignore="*/*/private/thierry/\n")
    token = Tokens().add("james-thierry", write=True)
    is_error, got = call(browser, "update", token=token, doc=f"sheaves/{SHARED}", text=PRIVATE + "More.\n",
                         expected_hash=md_hash(PRIVATE))
    assert not is_error, got
    assert not (repo / SHARED).exists() and (repo / QUARANTINE).read_text(encoding="utf-8").endswith("More.\n")
    assert git(repo, "log", "-1", "--format=%s").strip() == f"move: {SHARED} -> {QUARANTINE}"
    assert git(repo, "status", "--porcelain") == ""


def subjects(repo):
    return git(repo, "log", "--format=%s").splitlines()


def test_the_owners_untick_is_one_commit_that_moves_the_new_text(hub, browser, tmp_path):
    shared = OPEN.replace("- [ ] Share", "- [x] Share").replace("sources: [issue:thinkingtoo/tt-tiroir#9]\n",
                                                                  "visibility: project\n")
    box, repo = committing(hub, browser, tmp_path, first=shared)
    got = untick(box, repo, "Share", THIERRY, root="sheaves")
    assert got.status == 200 and "moved" not in got.json(), got.text
    assert subjects(repo) == [f"move: {SHARED} -> {HOME}", "first"]
    assert front_matter(git(repo, "show", f"HEAD:{HOME}"))["visibility"] == "owner"
    assert git(repo, "status", "--porcelain") == ""


def test_a_door_update_that_closes_a_sheaf_is_one_commit_that_moves_the_new_text(hub, browser, tmp_path):
    committing(hub, browser, tmp_path, first=OPEN)
    repo = tmp_path / "sheaves"
    token = Tokens().add("james-thierry", write=True)
    is_error, got = call(browser, "update", token=token, doc=f"sheaves/{SHARED}", text=PRIVATE,
                         expected_hash=md_hash(OPEN))
    assert not is_error and got["doc"] == f"sheaves/{SHARED}", got
    assert subjects(repo) == [f"move: {SHARED} -> {HOME}", "first"]
    assert git(repo, "show", f"HEAD:{HOME}") == (repo / HOME).read_text(encoding="utf-8")
    assert git(repo, "status", "--porcelain") == ""


def test_an_edit_of_a_private_sheaf_commits_its_file(hub, browser, tmp_path):
    box, repo = committing(hub, browser, tmp_path, at=HOME)
    i = next(i for i, b in enumerate(split_md_blocks(PRIVATE)) if "A quote" in b.content)
    got = box.post("/_/save", {"doc": f"sheaves/{SHARED}", "hash": md_hash(PRIVATE),
                               "edits": [{"i": i, "html": "<p>A quote, edited.</p>"}]}, member=THIERRY)
    assert got.status == 200, got.text
    assert subjects(repo)[0] == f"edit: {HOME}"
    assert git(repo, "status", "--porcelain") == ""


def test_an_untick_while_another_file_holds_the_name_writes_nothing(team, work):
    """The private home is taken by another file: two files hold the name, which then names no document."""
    shared = OPEN.replace("- [ ] Share", "- [x] Share")
    put(team, work, SHARED, shared)
    put(team, work, HOME, "# Something else\n")
    text = (work / SHARED).read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if "- [x] Share" in b.content)
    got = team.post("/_/save", {"doc": f"work/{SHARED}", "hash": md_hash(text),
                                "edits": [{"i": i, "html": "<ul><li><input type=\"checkbox\"> Share</li></ul>"}]},
                    member=THIERRY)
    assert got.status == 404, got.text
    assert (work / SHARED).read_text(encoding="utf-8") == shared and (work / HOME).read_text() == "# Something else\n"


def test_a_door_update_while_another_file_holds_the_name_writes_nothing(team, work, browser, tokens):
    put(team, work, SHARED, OPEN)
    put(team, work, HOME, "# Something else\n")
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{SHARED}", text=PRIVATE,
                         expected_hash=md_hash(OPEN))
    assert is_error, got
    assert (work / SHARED).read_text(encoding="utf-8") == OPEN


def test_a_door_update_and_a_poll_at_once_leave_one_file_with_the_update(team, work, browser, tokens, monkeypatch):
    """Codex P2: the poll comes while the update writes; it waits on the name's lock, and the answer names the
    sheaf by its name."""
    from sheafmd import mcp
    put(team, work, SHARED, PRIVATE)                           # written before the rule: the poll would move it
    real, threads = mcp.update_file, []

    def write_then_poll(path, change, **kw):
        got = real(path, change, **kw)
        t = threading.Thread(target=team.hub.the_list.poll)
        t.start()
        t.join(1)
        threads.append(t)
        return got
    monkeypatch.setattr(mcp, "update_file", write_then_poll)
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{SHARED}",
                         text=PRIVATE + "\nMore.\n", expected_hash=md_hash(PRIVATE))
    threads[0].join(10)
    assert not is_error and got["doc"] == f"work/{SHARED}", got
    assert (work / HOME).read_text(encoding="utf-8").endswith("More.\n") and not (work / SHARED).exists()


def test_a_door_reply_with_no_page_open_and_a_poll_at_once_lands_in_the_moved_file(team, work, browser, tokens,
                                                                                    monkeypatch):
    """A door comment write on a sheaf the hub holds no page for goes straight into the file: under the name's
    lock, its file found again under it, so a poll that comes between finding the file and writing it waits."""
    from sheafmd import mcp
    commented = PRIVATE.replace("A quote from the contract.\n", 'A quote from the contract.<!-- sheaf-comment id=c1 '
                                'by="Hans" at=2026-10-14T09:00 status=open quote="A quote"\nSource?\n-->\n')
    put(team, work, SHARED, commented)                         # written before the rule: the poll would move it
    assert f"work/{SHARED}" not in team.hub.entries
    real, threads = mcp.update_file, []

    def poll_then_write(path, change, **kw):
        t = threading.Thread(target=team.hub.the_list.poll)
        t.start()
        t.join(1)
        threads.append(t)
        return real(path, change, **kw)
    monkeypatch.setattr(mcp, "update_file", poll_then_write)
    is_error, got = call(browser, "reply", token=tokens["thierry"], doc=f"work/{SHARED}", id="c1",
                         text="The second page.")
    threads[0].join(10)
    assert not is_error, got
    assert "The second page." in (work / HOME).read_text(encoding="utf-8") and not (work / SHARED).exists()

def test_a_root_that_ignores_its_private_folders_is_told_and_nothing_moves_into_them(hub, browser, tmp_path, capsys):
    """A root the hub places must not ignore `private/` (8.11, 9.11): the poll would lose the sheaf it moved."""
    box, repo = committing(hub, browser, tmp_path, ignore="*/*/private/\n")
    hub.the_list.poll()
    hub.the_list.poll()
    assert (repo / SHARED).exists() and not (repo / HOME).exists()
    rows = hub_rows("private-ignored")
    assert len(rows) == 1 and rows[0]["root"] == "sheaves", rows
    assert "private" in capsys.readouterr().err
    assert [r["why"] for r in hub_rows("place-refused")] == ["the repo ignores the private folder"]
    token = Tokens().add("james-thierry", write=True)
    is_error, got = call(browser, "update", token=token, doc=f"sheaves/{SHARED}", text=PRIVATE + "More.\n",
                         expected_hash=md_hash(PRIVATE))
    assert not is_error, got                                    # it could not go home before: written as before
    assert (repo / SHARED).exists() and not (repo / HOME).exists()


def test_a_door_update_that_changes_nothing_still_commits_the_move_it_makes(hub, browser, tmp_path):
    closed = PRIVATE.replace("sources: [library:doc-123]\n", "sources: [library:doc-123]\nvisibility: owner\n")
    committing(hub, browser, tmp_path, first=closed)                # written before the rule, at the project's path
    repo = tmp_path / "sheaves"
    is_error, got = call(browser, "update", token=Tokens().add("james-thierry", write=True), doc=f"sheaves/{SHARED}",
                         text=closed, expected_hash=md_hash(closed))
    assert not is_error and got["doc"] == f"sheaves/{SHARED}" and not got["changed"], got
    assert subjects(repo) == [f"move: {SHARED} -> {HOME}", "first"]
    assert git(repo, "status", "--porcelain") == ""


def poll_before_the_lock(team, monkeypatch):
    """The list's poll comes between the request finding its document and taking the name's lock."""
    from sheafmd.hub import place
    real = place.held

    def held(hub, address):
        monkeypatch.setattr(place, "held", real)        # once: every read and write takes the lock (9.11)
        team.hub.the_list.poll()
        return real(hub, address)
    monkeypatch.setattr(place, "held", held)


def test_a_save_the_poll_overtook_lands_in_the_moved_file(team, work, monkeypatch):
    put(team, work, SHARED, PRIVATE)                           # written before the rule: the poll moves it
    assert team.get(f"/work/{SHARED}", member=THIERRY).status == 200
    i = next(i for i, b in enumerate(split_md_blocks(PRIVATE)) if "A quote" in b.content)
    poll_before_the_lock(team, monkeypatch)
    got = team.post("/_/save", {"doc": f"work/{SHARED}", "hash": md_hash(PRIVATE),
                                "edits": [{"i": i, "html": "<p>A quote, edited.</p>"}]}, member=THIERRY)
    assert got.status == 200 and "moved" not in got.json(), got.text
    assert "A quote, edited." in (work / HOME).read_text(encoding="utf-8") and not (work / SHARED).exists()


def test_a_tick_the_poll_overtook_lands_in_the_moved_file(team, work, monkeypatch):
    put(team, work, SHARED, PRIVATE)
    read = md_hash((work / SHARED).read_text(encoding="utf-8"))        # the text the list read
    poll_before_the_lock(team, monkeypatch)
    got = team.post("/_/tick", {"doc": f"work/{SHARED}", "action": 0, "word": "Share", "hash": read}, member=THIERRY)
    assert got.status == 200, got.text
    assert "- [x] Share" in (work / SHARED).read_text(encoding="utf-8") and not (work / HOME).exists()


# ── reads hold the name's lock; a move is move, write, render, commit under it ──

def test_a_reader_during_a_share_save_never_gets_the_page_rendered_from_the_private_folder(team, work, monkeypatch):
    """Codex P1: the Share save writes `visibility: project` while the file is still in private/<owner>/; a reader
    that came between that write and the move passed the new visibility check and got the page rendered against
    the private folder. The reader waits on the name's lock, and the move comes before the write."""
    from PIL import Image
    put(team, work, HOME, PRIVATE.replace("A quote from the contract.", "![seal](seal.png)"))
    Image.new("RGB", (8, 8), (200, 10, 10)).save(work / "thinkingtoo/tiroir/private/thierry/seal.png", "PNG")
    assert "data:image/png;base64," in team.get(f"/work/{SHARED}", member=THIERRY).text
    e = team.hub.entries[f"work/{SHARED}"]
    pages, threads = [], []

    def read_between():
        monkeypatch.undo()
        t = threading.Thread(target=lambda: pages.append(team.get(f"/work/{SHARED}", member=HANS)))
        t.start()
        t.join(1)
        threads.append(t)
    monkeypatch.setattr(e.live, "_after_write", read_between)
    assert tick(team, work, "Share", THIERRY).status == 200
    threads[0].join(10)
    assert pages[0].status == 200
    assert "data:image/png;base64," not in pages[0].text and "missing image: seal.png" in pages[0].text


def test_a_door_read_during_a_move_finds_the_file(team, work, browser, tokens, monkeypatch):
    """Codex P1: a read resolved the path a move then unlinked, and read nothing. The move waits for the read."""
    put(team, work, SHARED, PRIVATE)                           # written before the rule: the poll moves it
    real, threads = team.hub.roots.document, []

    def resolve_then_poll(address):
        got = real(address)
        monkeypatch.setattr(team.hub.roots, "document", real)
        t = threading.Thread(target=team.hub.the_list.poll)
        t.start()
        t.join(1)
        threads.append(t)
        return got
    monkeypatch.setattr(team.hub.roots, "document", resolve_then_poll)
    is_error, got = call(browser, "read", token=tokens["thierry"], doc=f"work/{SHARED}")
    threads[0].join(10)
    assert not is_error, got
    assert got["text"].startswith("---") and (work / HOME).exists() and not (work / SHARED).exists()


def test_two_writers_of_one_name_each_commit_their_own_write(hub, browser, tmp_path, monkeypatch):
    """Codex P1: the commit ran after the name's lock was let go, so a second writer could write and commit first,
    its commit taking the first one's text under its own author. The commit is made under the lock."""
    box, repo = committing(hub, browser, tmp_path, at=HOME)
    blocks = split_md_blocks(PRIVATE)
    i = next(i for i, b in enumerate(blocks) if "A quote" in b.content)
    h = next(i for i, b in enumerate(blocks) if "What the contract says" in b.content)
    real, threads, answers = hub.commits.saved, [], []

    def second(*a, **kw):
        monkeypatch.setattr(hub.commits, "saved", real)
        t = threading.Thread(target=lambda: answers.append(browser.post(
            "/_/save", {"doc": f"sheaves/{SHARED}", "hash": md_hash(PRIVATE),
                        "edits": [{"i": h, "html": "<h1>What the contract says, edited</h1>"}]})))
        t.start()
        t.join(1)
        threads.append(t)
        return real(*a, **kw)
    monkeypatch.setattr(hub.commits, "saved", second)
    got = box.post("/_/save", {"doc": f"sheaves/{SHARED}", "hash": md_hash(PRIVATE),
                               "edits": [{"i": i, "html": "<p>A quote, edited.</p>"}]}, member=THIERRY)
    threads[0].join(10)
    assert got.status == 200 and answers[0].status == 200, (got.text, answers[0].text)
    log = git(repo, "log", "--format=%an|%s").splitlines()
    assert log == [f"{hub.person}|edit: {HOME}", f"Thierry|edit: {HOME}", "the box|first"], log
    first = git(repo, "show", f"HEAD~1:{HOME}")
    assert "A quote, edited." in first and "says, edited" not in first
    assert "says, edited" in git(repo, "show", f"HEAD:{HOME}")


def test_a_door_create_of_an_owner_only_sheaf_in_a_root_that_ignores_private_is_refused(hub, browser, tmp_path):
    """An owner-only create picks the private home; in a root whose repo ignores it the file would be made
    untracked. Refused as the move is, and nothing is written."""
    box, repo = committing(hub, browser, tmp_path, at="thinkingtoo/tiroir/other.md", first=OPEN,
                           ignore="*/*/private/\n")
    token = Tokens().add("james-thierry", write=True)
    is_error, got = call(browser, "create", token=token, doc=f"sheaves/{SHARED}", text=PRIVATE)
    assert is_error and "the repo ignores the private folder" in got, got
    assert not (repo / SHARED).exists() and not (repo / HOME).exists()
    assert not (repo / "thinkingtoo/tiroir/private").exists()


# ── round 7: a link holds no name; ahead is the one judge; a write and its commit are one step ──

LINK = "thinkingtoo/tiroir/link.md"
SHARED_TEXT = OPEN.replace("- [ ] Share", "- [x] Share").replace("sources: [issue:thinkingtoo/tt-tiroir#9]\n",
                                                                   "visibility: project\n")


def test_a_poll_placing_a_link_while_its_target_is_withdrawn_does_not_deadlock(team, work, monkeypatch):
    """Opus P1 (round 7): a link and its target took two name locks and one file lock (the file lock resolves
    links), so the owner's withdrawal (file lock, then the folders lock in `ahead`) and the poll's `place` of the
    link (folders lock, then the file lock) waited on each other for good. A link holds no name (9.11): the poll
    takes no lock of its file."""
    from sheafmd.hub import place
    put(team, work, SHARED, SHARED_TEXT)
    os.symlink(NAME, work / LINK)
    real, threads = place.ahead, []

    def poll_first(hub, address, *a, **kw):
        t = threading.Thread(target=place.place, args=(team.hub, f"work/{LINK}"), daemon=True)
        t.start()
        t.join(1)
        threads.append(t)
        return real(hub, address, *a, **kw)
    monkeypatch.setattr(place, "ahead", poll_first)
    answers = []
    t = threading.Thread(target=lambda: answers.append(untick(team, work, "Share", THIERRY)), daemon=True)
    t.start()
    t.join(20)
    assert not t.is_alive() and not threads[0].is_alive(), "the withdrawal and the poll wait on each other"
    assert answers[0].status == 200, answers[0].text
    assert front_matter((work / HOME).read_text(encoding="utf-8"))["visibility"] == "owner"


def test_a_withdrawal_through_a_link_name_writes_nothing_at_the_shared_path(team, work):
    """Opus P1 (round 7): the owner's untick on the page of a link to a shared sheaf wrote `visibility: owner`
    through the link into the shared path, where the shared glob reads it. A link holds no name: its page is
    the 404 of a document that does not exist, and nothing is written."""
    put(team, work, SHARED, SHARED_TEXT)
    os.symlink(NAME, work / LINK)
    got = untick(team, work, "Share", THIERRY, name=LINK)
    assert got.status == 404, got.text
    assert (work / SHARED).read_text(encoding="utf-8") == SHARED_TEXT
    assert team.get(f"/work/{LINK}", member=THIERRY).status == 404


@pytest.mark.parametrize("alias, to", [
    ("thinkingtoo/alias.md", f"tiroir/{NAME}"),
    ("thinkingtoo/tiroir/notes/alias.md", f"../{NAME}"),
    (f"thinkingtoo/tiroir/notes/{NAME}", ".."),
])
def test_no_path_reaches_a_sheaf_through_a_link_at_any_depth(team, work, alias, to):
    """Opus P1 (round 8): a link above or below project depth, or a linked folder on the way, was no name, so the
    hub served it as a plain document: the owner's untick there wrote `visibility: owner` through it at the shared
    path, unlocked, and the commit staged that path. In a root the hub places no address reaches a file through a
    link, at any depth (9.11): the page answers 404 and nothing is written."""
    put(team, work, SHARED, SHARED_TEXT)
    link = alias if to != ".." else alias.rsplit("/", 1)[0]
    (work / link).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(to, work / link)
    assert team.get(f"/work/{alias}", member=THIERRY).status == 404
    blocks = split_md_blocks(SHARED_TEXT)
    i = next(i for i, b in enumerate(blocks) if "- [x] Share" in b.content)
    soup = BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], blocks[i].content).stdout,
                         "html.parser")
    del next(b for b in soup.select('input[type="checkbox"]') if "Share" in b.parent.get_text())["checked"]
    got = team.post("/_/save", {"doc": f"work/{alias}", "hash": md_hash(SHARED_TEXT),
                                "edits": [{"i": i, "html": str(soup)}]}, member=THIERRY)
    assert got.status == 404, got.text
    assert (work / SHARED).read_text(encoding="utf-8") == SHARED_TEXT


def test_a_document_below_project_depth_in_real_folders_is_still_served(team, work):
    """The rule above refuses links, not depth: a file in real folders under a project is a document as before."""
    put(team, work, "thinkingtoo/tiroir/notes/plain.md", "# Plain\n\nWords.\n")
    assert team.get("/work/thinkingtoo/tiroir/notes/plain.md", member=THIERRY).status == 200


@pytest.mark.parametrize("alias, to", [("thinkingtoo/alias.md", f"tiroir/{NAME}"),
                                       ("thinkingtoo/tiroir/notes/alias.md", f"../{NAME}")])
def test_a_link_off_a_sheafs_path_is_in_no_index_and_no_list_and_the_poll_says_so(team, work, alias, to):
    """Opus P2 (round 9): the page answered such a link 404, but the index listed it and the list read it as a
    sheaf, through the link and under no name's lock. Nothing is listed or read through a link (9.11), and the
    poll says so of it once, as of a link at a sheaf's path."""
    put(team, work, SHARED, SHARED_TEXT)
    (work / alias).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(to, work / alias)
    team.hub.the_list.poll()
    docs = [d["doc"] for r in team.get("/_/index.json", member=THIERRY).json()["roots"] for d in r["docs"]]
    assert f"work/{alias}" not in docs, docs
    assert alias not in [r.sheaf.rel for r in team.hub.the_list._snap.rows]
    assert [(r["root"], r["path"]) for r in hub_rows("link-ignored")] == [("work", alias)]


def test_a_holder_that_turns_into_a_link_while_the_poll_moves_it_deadlocks_nothing(team, work, monkeypatch):
    """Opus P2 (round 9): `place` took the project's folders lock and then the file's, and a writer that moves
    (`ahead`) holds the file's lock and then takes the folders': one file whose path became a link to another's
    between the poll's look and its file lock crossed the two, and the project hung. One order everywhere
    (9.11): a name's, then the file's, then the folders'."""
    from sheafmd.hub import place
    from sheafmd.source import file_lock
    other = "thinkingtoo/tiroir/other.md"
    put(team, work, SHARED, OPEN)
    put(team, work, other, PRIVATE)
    hub, top = team.hub, Path(os.path.realpath(work))
    real_one, swapped, holding = place._one, threading.Event(), threading.Event()

    def one(t, name):
        got = real_one(t, name)
        if name == other and threading.current_thread().name == "poll" and not swapped.is_set():
            os.unlink(work / other)
            os.symlink(NAME, work / other)          # by hand, or a pull, between the poll's look and its file lock
            swapped.set()
        return got
    monkeypatch.setattr(place, "_one", one)

    def writer():
        with place.held(hub, f"work/{SHARED}"), file_lock(top / SHARED):
            holding.set()
            swapped.wait(5)
            place.ahead(hub, f"work/{SHARED}", OPEN, PRIVATE)
    w = threading.Thread(target=writer, name="writer", daemon=True)
    w.start()
    assert holding.wait(5)
    poll = threading.Thread(target=lambda: place.place(hub, f"work/{other}"), name="poll", daemon=True)
    poll.start()
    w.join(10)
    poll.join(10)
    assert not w.is_alive() and not poll.is_alive(), "the writer waits on the folders, the poll on the file"


@pytest.mark.parametrize("linked", ["private", "private/thierry"])
def test_a_file_under_a_linked_private_folder_holds_no_name(team, work, tmp_path, linked):
    """A name is held only by a regular file reached through real folders (9.11): one under a linked `private`
    or `private/<short>` is no sheaf, to the page and to the list, and the poll moves nothing out of it."""
    elsewhere = tmp_path / "elsewhere"
    target = elsewhere / "thierry" if linked == "private" else elsewhere
    target.mkdir(parents=True)
    (target / NAME).write_text(PRIVATE, encoding="utf-8")
    (work / "thinkingtoo/tiroir" / linked).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(elsewhere, work / "thinkingtoo/tiroir" / linked)
    team.hub.the_list.poll()
    assert team.get(f"/work/{SHARED}", member=THIERRY).status == 404
    assert not (work / SHARED).exists() and (target / NAME).read_text(encoding="utf-8") == PRIVATE
    assert SHARED not in [r.sheaf.rel for r in team.hub.the_list._snap.rows]


def test_a_link_the_poll_meets_is_one_link_ignored_row_per_hub_run(team, work, capsys):
    """A link holds no name, and the hub says so once, from the poll: a `link-ignored` row (15) with the root and
    the path, and a line on stderr, never again for that path in that hub run, and never on a lookup."""
    put(team, work, SHARED, SHARED_TEXT)
    os.symlink(NAME, work / LINK)
    team.hub.the_list.poll()
    team.hub.the_list.poll()
    team.get(f"/work/{LINK}", member=THIERRY)
    rows = hub_rows("link-ignored")
    assert [(r["root"], r["path"]) for r in rows] == [("work", LINK)], rows
    assert capsys.readouterr().err.count(LINK) == 1


def test_an_untick_whose_move_fails_in_the_folder_is_refused_and_writes_nothing(team, work, tmp_path):
    """Opus P1 (round 7): `refusal` judged the move allowed (nothing at the home through a linked `private/<short>`,
    and `git check-ignore` does not answer beyond a link), the move then failed making the folder, and the
    withdrawal wrote `visibility: owner` at the shared path. `ahead` is the one judge: a move it cannot make
    refuses the write."""
    put(team, work, SHARED, SHARED_TEXT)
    (tmp_path / "elsewhere").mkdir()
    (work / "thinkingtoo/tiroir/private").mkdir()
    os.symlink(tmp_path / "elsewhere", work / "thinkingtoo/tiroir/private/thierry")
    got = untick(team, work, "Share", THIERRY)
    assert got.status == 409 and "This sheaf cannot go to its home" in got.text, got.text
    assert (work / SHARED).read_text(encoding="utf-8") == SHARED_TEXT


def test_a_door_update_whose_link_into_place_fails_is_refused_and_writes_nothing(team, work, browser, tokens,
                                                                                  monkeypatch):
    """Any error of the link into place (EXDEV, EPERM, ENOSPC) refuses the write, at the door as on the page."""
    import errno
    from sheafmd.hub import place
    put(team, work, SHARED, OPEN)

    def no_link(*a, **kw):
        raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))
    monkeypatch.setattr(place.os, "link", no_link)
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{SHARED}", text=PRIVATE,
                         expected_hash=md_hash(OPEN))
    assert is_error and "was not written" in got and "so it could not go to its home" in got, got
    assert (work / SHARED).read_text(encoding="utf-8") == OPEN and not (work / HOME).exists()


def test_a_comment_committed_while_the_owner_withdraws_the_share_is_its_own_commit(hub, browser, tmp_path,
                                                                                    monkeypatch):
    """Opus P1 (round 7): the page's comment was written under the name's lock and committed after it, so the
    owner's withdrawal came between: its `move:` commit took the comment, and the comment's commit found nothing.
    A write and its commit are one step under the name's lock."""
    box, repo = committing(hub, browser, tmp_path, first=SHARED_TEXT)
    page = browser.get(f"/sheaves/{SHARED}")
    assert page.status == 200
    real, threads, answers = hub.committed, [], []

    def withdraw_first(address, *a, **kw):
        if kw.get("what", a[1] if len(a) > 1 else None) == "comment" and not threads:
            t = threading.Thread(target=lambda: answers.append(untick(box, repo, "Share", THIERRY, root="sheaves")),
                                 daemon=True)
            t.start()
            t.join(2)
            threads.append(t)
        return real(address, *a, **kw)
    monkeypatch.setattr(hub, "committed", withdraw_first)
    from sheafmd import comments as rdc
    blk, start, end = rdc.find_quote(SHARED_TEXT, "A quote")
    got = browser.post("/_/comment", {"doc": f"sheaves/{SHARED}", "op": "add", "hash": md_hash(SHARED_TEXT),
                                      "block": blk, "start": start, "end": end, "quote": "A quote", "body": "Mine."})
    assert threads, got.text
    threads[0].join(20)
    assert got.status == 200 and answers[0].status == 200, (got.text, answers[0].text)
    log = git(repo, "log", "--format=%an|%s").splitlines()
    assert log == [f"Thierry|move: {SHARED} -> {HOME}", f"{hub.person}|comment: {SHARED}", "the box|first"], log
    assert "Mine." in git(repo, "show", f"HEAD~1:{SHARED}")
    assert git(repo, "status", "--porcelain") == ""


def test_a_move_made_before_a_render_that_fails_is_still_committed(hub, browser, tmp_path, monkeypatch):
    """Opus P2 (round 7): the withdrawal moved and wrote the file, its render raised, and the commit was skipped:
    HEAD kept the shared path for good. The move is committed whatever the render does."""
    from sheafmd.render import RenderError
    box, repo = committing(hub, browser, tmp_path, first=SHARED_TEXT)
    assert box.get(f"/sheaves/{SHARED}", member=THIERRY).status == 200
    e = hub.entries[f"sheaves/{SHARED}"]

    def fails():
        raise RenderError("pandoc took too long")
    monkeypatch.setattr(e.live, "_rerender", fails)
    untick(box, repo, "Share", THIERRY, root="sheaves")
    assert subjects(repo)[0] == f"move: {SHARED} -> {HOME}", subjects(repo)
    assert git(repo, "status", "--porcelain") == ""


def test_a_commit_outside_the_names_lock_is_a_programming_error(team, work):
    """Nothing commits a sheaf's file without holding its name (9.11): the hub refuses such a commit loudly."""
    put(team, work, SHARED, OPEN)
    with pytest.raises(RuntimeError, match="lock"):
        team.hub.committed(f"work/{SHARED}", what="edit")


def test_the_lock_of_a_name_nobody_holds_is_let_go(team, work):
    """Opus P2 (round 7): a lock was kept for every well-formed name ever asked for, so a member asking for
    unlimited URLs grew the hub's memory without end. A name's lock lives while a thread holds it or waits on it."""
    from sheafmd.hub import place
    before = len(place._LOCKS)
    for n in range(200):
        assert team.get(f"/work/thinkingtoo/tiroir/none-{n}.md", member=THIERRY).status == 404
    with place.held(team.hub, f"work/{SHARED}"):
        assert place.owns(team.hub, f"work/{SHARED}") and len(place._LOCKS) == before + 1
    assert len(place._LOCKS) == before and not place.owns(team.hub, f"work/{SHARED}")
