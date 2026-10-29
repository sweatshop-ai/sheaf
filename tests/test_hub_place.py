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

import pytest
from bs4 import BeautifulSoup
from helpers import FRONT, Front, call, hub_rows

from sheafmd import _pandoc
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import projects, proxy, the_list, work as work_mod
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


def untick(team, work, word, member, name=SHARED, root="work"):
    """The page's save that unticks the box `- [x] <word>`, as the page sends it: the block's HTML with that box
    no longer checked."""
    text = text_of(work, name)
    blocks = split_md_blocks(text)
    i = next(i for i, b in enumerate(blocks) if f"- [x] {word}" in b.content)
    soup = BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], blocks[i].content).stdout,
                         "html.parser")
    box = next(b for b in soup.select('input[type="checkbox"]') if word in b.parent.get_text())
    del box["checked"]
    return team.post("/_/save", {"doc": f"{root}/{name}", "hash": md_hash(text),
                                 "edits": [{"i": i, "html": str(soup)}]}, member=member)


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


def rewrite_untick(team, work, member):
    """A save that unticks Share by rewriting its block through pandoc: the box unchecked and an item added, so the
    edit is no tick of 7.2."""
    text = text_of(work)
    blocks = split_md_blocks(text)
    i = next(i for i, b in enumerate(blocks) if "- [x] Share" in b.content)
    soup = BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5"], blocks[i].content).stdout, "html.parser")
    del soup.select_one('input[type="checkbox"]')["checked"]
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


def test_the_lists_tick_of_share_moves_the_file(team, work):
    put(team, work, HOME, PRIVATE)
    got = team.post("/_/tick", {"doc": f"work/{SHARED}", "action": 0, "word": "Share"}, member=THIERRY)
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


def test_an_owner_only_sheaf_with_no_owner_that_has_a_short_stays_and_says_why(team, work):
    put(team, work, SHARED, PRIVATE.replace("owner: thierry", "owner: nobody"))
    team.hub.the_list.poll()
    assert (work / SHARED).exists()
    rows = hub_rows("place-refused")
    assert [r["doc"] for r in rows] == [f"work/{SHARED}"] and "owner" in rows[0]["why"]


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

    def poll_then_write(path, change):
        monkeypatch.setattr(live.rds, "update_file", real)
        t = threading.Thread(target=team.hub.the_list.poll)
        t.start()
        t.join(1)
        threads.append(t)
        return real(path, change)
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

    def write_then_poll(path, change):
        got = real(path, change)
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

    def poll_then_write(path, change):
        t = threading.Thread(target=team.hub.the_list.poll)
        t.start()
        t.join(1)
        threads.append(t)
        return real(path, change)
    monkeypatch.setattr(mcp, "update_file", poll_then_write)
    is_error, got = call(browser, "reply", token=tokens["thierry"], doc=f"work/{SHARED}", id="c1",
                         text="The second page.")
    threads[0].join(10)
    assert not is_error, got
    assert "The second page." in (work / HOME).read_text(encoding="utf-8") and not (work / SHARED).exists()

def test_a_move_into_an_ignored_private_folder_still_commits_the_old_path_gone(hub, browser, tmp_path):
    """Codex P1: a deployment that keeps private folders out of git must not keep the shared copy in it."""
    box, repo = committing(hub, browser, tmp_path, ignore="*/*/private/\n")
    assert box.get(f"/sheaves/{SHARED}", member=THIERRY).status == 200          # a version, inside the root
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the version")
    hub.the_list.poll()
    assert (repo / HOME).exists()
    assert git(repo, "log", "-1", "--format=%s").strip() == f"move: {SHARED} -> {HOME}"
    files = set(git(repo, "show", "--no-renames", "--name-status", "--format=", "HEAD").splitlines())
    assert files == {f"D\t{SHARED}"}, files
    assert git(repo, "ls-files", SHARED) == ""


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
    poll_before_the_lock(team, monkeypatch)
    got = team.post("/_/tick", {"doc": f"work/{SHARED}", "action": 0, "word": "Share"}, member=THIERRY)
    assert got.status == 200, got.text
    assert "- [x] Share" in (work / SHARED).read_text(encoding="utf-8") and not (work / HOME).exists()
