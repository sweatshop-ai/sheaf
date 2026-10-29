"""Placement (SPEC 9.11 "Where a sheaf lives"): in proxy mode a sheaf of the list's root that is its owner's alone
lives at `<client>/<project>/private/<owner short>/<name>.md`, one open to the project at
`<client>/<project>/<name>.md`. The door's create lands at home, an update, a Share, its owner's withdrawal of it and
the list's poll move the file, and the logical name `<client>/<project>/<name>.md` still finds it for whoever may
see it. Through the handler in proxy mode, with the list on `work`: Thierry owns the sheaves, Hans is a member of
the project."""
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


def tick(team, work, rel, word, member):
    """The page's save that ticks the first action `word` of the sheaf, as `member`."""
    text = (work / rel).read_text(encoding="utf-8")
    n = [a[0] for a in the_list.read_sheaf(rel, text).actions].index(word)
    edit = the_list.tick_edit(text, n, word)
    return team.post("/_/save", {"doc": f"work/{rel}", "hash": md_hash(text), "edits": [edit]}, member=member)


def untick(team, work, rel, word, member, root="work"):
    """The page's save that unticks the box `- [x] <word>`, as the page sends it: the block's HTML with that box
    no longer checked."""
    text = (work / rel).read_text(encoding="utf-8")
    blocks = split_md_blocks(text)
    i = next(i for i, b in enumerate(blocks) if f"- [x] {word}" in b.content)
    soup = BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], blocks[i].content).stdout,
                         "html.parser")
    box = next(b for b in soup.select('input[type="checkbox"]') if word in b.parent.get_text())
    del box["checked"]
    return team.post("/_/save", {"doc": f"{root}/{rel}", "hash": md_hash(text),
                                 "edits": [{"i": i, "html": str(soup)}]}, member=member)


# ── the door's create lands at home ──────────────────────────────────────────

def test_a_door_create_of_an_owner_only_sheaf_lands_in_its_owners_private_folder(team, work, browser, tokens):
    is_error, got = call(browser, "create", token=tokens["thierry"], doc=f"work/{SHARED}", text=PRIVATE)
    assert not is_error, got
    assert got["doc"] == f"work/{HOME}" and got["url"].endswith(f"/work/{HOME}")
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
        t = threading.Thread(target=place.place, args=(team.hub, f"work/{other}"))
        t.start()
        t.join(1)
        threads.append(t)
        real(top, rel, text)
    monkeypatch.setattr(mcp, "create_file", create_while_moving)
    is_error, got = call(browser, "create", token=tokens["thierry"], doc=f"work/{SHARED}", text=PRIVATE)
    threads[0].join(10)
    assert not is_error, got
    assert (work / HOME).exists() and (work / "thinkingtoo/tiroir/other.md").exists()


# ── the logical name finds the sheaf ─────────────────────────────────────────

def test_the_logical_name_reads_and_updates_the_private_sheaf_for_its_owner(team, work, browser, tokens):
    put(team, work, HOME, PRIVATE)
    is_error, got = call(browser, "read", token=tokens["thierry"], doc=f"work/{SHARED}")
    assert not is_error and got["doc"] == f"work/{HOME}"
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{SHARED}",
                         text=PRIVATE + "\nMore.\n", expected_hash=md_hash(PRIVATE))
    assert not is_error and got["doc"] == f"work/{HOME}"
    assert (work / HOME).read_text(encoding="utf-8").endswith("More.\n")


def test_the_logical_name_is_absent_to_a_token_that_may_not_see_the_sheaf(team, work, browser, tokens):
    put(team, work, HOME, PRIVATE)
    _, got = call(browser, "read", token=tokens["hans"], doc=f"work/{SHARED}")
    _, missing = call(browser, "read", token=tokens["hans"], doc="work/thinkingtoo/tiroir/nothing.md")
    assert got == missing.replace("nothing.md", NAME)


# ── a door update moves the file ─────────────────────────────────────────────

def test_a_door_update_that_closes_a_sheaf_moves_it_into_private(team, work, browser, tokens):
    put(team, work, SHARED, OPEN)
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{SHARED}",
                         text=PRIVATE, expected_hash=md_hash(OPEN))
    assert not is_error, got
    assert got["doc"] == f"work/{HOME}" and got["url"].endswith(f"/work/{HOME}")
    assert not (work / SHARED).exists()
    assert front_matter((work / HOME).read_text(encoding="utf-8"))["visibility"] == "owner"


# ── Share moves out, its owner's withdrawal moves back ───────────────────────

def test_the_owners_share_moves_the_sheaf_out_of_private(team, work):
    put(team, work, HOME, PRIVATE)
    got = tick(team, work, HOME, "Share", THIERRY)
    assert got.status == 200, got.text
    assert got.json()["moved"] == f"work/{SHARED}"
    assert not (work / HOME).exists() and "- [x] Share" in (work / SHARED).read_text(encoding="utf-8")
    assert team.get(f"/work/{SHARED}", member=HANS).status == 200


def test_the_owner_unticking_share_closes_the_sheaf_and_moves_it_back(team, work):
    put(team, work, HOME, PRIVATE)
    tick(team, work, HOME, "Share", THIERRY)
    got = untick(team, work, SHARED, "Share", THIERRY)
    assert got.status == 200, got.text
    assert got.json()["moved"] == f"work/{HOME}"
    text = (work / HOME).read_text(encoding="utf-8")
    fm = front_matter(text)
    assert fm["visibility"] == "owner" and "shared" not in fm and "- [ ] Share" in text
    assert not (work / SHARED).exists()
    assert team.get(f"/work/{HOME}", member=HANS).status == 404


def test_a_member_who_is_not_the_owner_cannot_untick_share(team, work):
    put(team, work, HOME, PRIVATE)
    tick(team, work, HOME, "Share", THIERRY)
    before = (work / SHARED).read_text(encoding="utf-8")
    got = untick(team, work, SHARED, "Share", HANS)
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


def rewrite_untick(team, work, rel, member):
    """A save that unticks Share by rewriting its block through pandoc: the box unchecked and an item added, so the
    edit is no tick of 7.2."""
    text = (work / rel).read_text(encoding="utf-8")
    blocks = split_md_blocks(text)
    i = next(i for i, b in enumerate(blocks) if "- [x] Share" in b.content)
    soup = BeautifulSoup(_pandoc.run(["-f", "gfm", "-t", "html5"], blocks[i].content).stdout, "html.parser")
    del soup.select_one('input[type="checkbox"]')["checked"]
    item = soup.new_tag("li")
    item.string = "Also this."
    soup.select_one("ul").append(item)
    return team.post("/_/save", {"doc": f"work/{rel}", "hash": md_hash(text), "edits": [{"i": i, "html": str(soup)}]},
                     member=member)


def test_a_rewrite_that_unticks_share_is_refused_to_a_member_who_is_not_the_owner(team, work):
    put(team, work, HOME, PRIVATE)
    tick(team, work, HOME, "Share", THIERRY)
    before = (work / SHARED).read_text(encoding="utf-8")
    got = rewrite_untick(team, work, SHARED, HANS)
    assert got.status == 409 and got.json()["error"] == "Only the owner of this sheaf can withdraw its Share."
    assert (work / SHARED).read_text(encoding="utf-8") == before


def test_the_owners_rewrite_that_unticks_share_withdraws_it(team, work):
    put(team, work, HOME, PRIVATE)
    tick(team, work, HOME, "Share", THIERRY)
    got = rewrite_untick(team, work, SHARED, THIERRY)
    assert got.status == 200, got.text
    assert got.json()["moved"] == f"work/{HOME}"
    text = (work / HOME).read_text(encoding="utf-8")
    assert front_matter(text)["visibility"] == "owner" and "Also this." in text and not (work / SHARED).exists()


def test_the_lists_tick_of_share_moves_the_sheaf_and_says_where(team, work):
    put(team, work, HOME, PRIVATE)
    got = team.post("/_/tick", {"doc": f"work/{HOME}", "action": 0, "word": "Share"}, member=THIERRY)
    assert got.status == 200, got.text
    assert got.json()["moved"] == f"work/{SHARED}" and (work / SHARED).exists()


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


def test_a_home_already_taken_keeps_the_sheaf_where_it_is(team, work):
    put(team, work, SHARED, PRIVATE)
    put(team, work, HOME, OPEN)                 # an open one, itself to be moved out onto the first
    team.hub.the_list.poll()
    assert (work / SHARED).read_text(encoding="utf-8") == PRIVATE
    assert (work / HOME).read_text(encoding="utf-8") == OPEN
    assert {r["doc"] for r in hub_rows("place-refused")} == {f"work/{SHARED}", f"work/{HOME}"}


def test_a_name_held_by_another_private_sheaf_keeps_the_sheaf_where_it_is(team, work):
    """Its own home is free, but the name is not: a move there would give the name two files."""
    hans = f"thinkingtoo/tiroir/private/hans/{NAME}"
    put(team, work, SHARED, PRIVATE)
    put(team, work, hans, PRIVATE.replace("owner: thierry", "owner: hans"))
    team.hub.the_list.poll()
    assert (work / SHARED).read_text(encoding="utf-8") == PRIVATE and not (work / HOME).exists()
    assert [r["doc"] for r in hub_rows("place-refused")] == [f"work/{SHARED}"]


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


# ── what follows the file ────────────────────────────────────────────────────

def test_a_members_seen_state_follows_the_move(team, work):
    put(team, work, SHARED, PRIVATE)
    team.hub.member_seen.mark(THIERRY, f"work/{SHARED}", "c1", 2)
    team.hub.the_list.poll()
    assert team.hub.member_seen.get(THIERRY, f"work/{HOME}") == {"c1": 2}
    assert team.hub.member_seen.get(THIERRY, f"work/{SHARED}") == {}


def test_the_versions_follow_the_move(team, work):
    put(team, work, SHARED, PRIVATE)
    assert team.get(f"/work/{SHARED}", member=THIERRY).status == 200      # the page: its text is a version
    team.hub.the_list.poll()
    assert team.hub.versions.get(f"work/{HOME}", md_hash(PRIVATE)) == PRIVATE
    assert team.hub.versions.get(f"work/{SHARED}", md_hash(PRIVATE)) is None


def test_an_open_page_is_told_where_its_sheaf_went(team, work):
    put(team, work, HOME, PRIVATE)
    stream = team.get(f"/_/live?doc=work/{HOME}", member=THIERRY).stream
    stream.drain()
    tick(team, work, HOME, "Share", THIERRY)
    assert ("moved", {"doc": f"work/{HOME}", "to": f"work/{SHARED}"}) in stream.drain()


def test_a_private_sheaf_is_a_sheaf_of_the_list_for_work_on_this(team, work):
    assert work_mod.is_sheaf(team.hub, f"work/{HOME}")
    assert not work_mod.is_sheaf(team.hub, "work/thinkingtoo/tiroir/private/x.md")


# ── the page's address of a sheaf that moved ─────────────────────────────────

def test_the_logical_address_sends_the_owner_to_the_private_page_and_hans_to_a_404(team, work):
    put(team, work, HOME, PRIVATE)
    got = team.get(f"/work/{SHARED}", member=THIERRY)
    assert got.status == 302 and got.headers["Location"] == f"/work/{HOME}"
    hidden = team.get(f"/work/{SHARED}", member=HANS)
    missing = team.get("/work/thinkingtoo/tiroir/nothing.md", member=HANS)
    assert hidden.status == missing.status == 404 and hidden.body == missing.body


def test_a_private_address_whose_sheaf_was_shared_sends_to_the_shared_page(team, work):
    put(team, work, SHARED, OPEN)
    got = team.get(f"/work/{HOME}", member=HANS)
    assert got.status == 302 and got.headers["Location"] == f"/work/{SHARED}"


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


def test_a_move_is_one_commit_with_both_paths_and_the_versions_folder(hub, browser, tmp_path):
    box, repo = committing(hub, browser, tmp_path)
    assert box.get(f"/sheaves/{SHARED}", member=THIERRY).status == 200          # a version, inside the root
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the version")
    hub.the_list.poll()
    assert git(repo, "log", "-1", "--format=%s|%an").strip() == f"move: {SHARED} -> {HOME}|sheaf"
    files = set(git(repo, "show", "--no-renames", "--name-status", "--format=", "HEAD").splitlines())
    assert f"D\t{SHARED}" in files and f"A\t{HOME}" in files
    assert any(line.startswith("A\t" + str(INSIDE / doc_key(HOME))) for line in files)
    assert any(line.startswith("D\t" + str(INSIDE / doc_key(SHARED))) for line in files)
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / INSIDE / doc_key(HOME) / "address").read_text(encoding="utf-8") == HOME


def subjects(repo):
    return git(repo, "log", "--format=%s").splitlines()


def test_the_owners_untick_is_one_commit_that_moves_the_new_text(hub, browser, tmp_path):
    shared = OPEN.replace("- [ ] Share", "- [x] Share").replace("sources: [issue:thinkingtoo/tt-tiroir#9]\n",
                                                                  "visibility: project\n")
    box, repo = committing(hub, browser, tmp_path, first=shared)
    got = untick(box, repo, SHARED, "Share", THIERRY, root="sheaves")
    assert got.status == 200 and got.json()["moved"] == f"sheaves/{HOME}", got.text
    assert subjects(repo) == [f"move: {SHARED} -> {HOME}", "first"]
    assert front_matter(git(repo, "show", f"HEAD:{HOME}"))["visibility"] == "owner"
    assert git(repo, "status", "--porcelain") == ""


def test_a_door_update_that_closes_a_sheaf_is_one_commit_that_moves_the_new_text(hub, browser, tmp_path):
    committing(hub, browser, tmp_path, first=OPEN)
    repo = tmp_path / "sheaves"
    token = Tokens().add("james-thierry", write=True)
    is_error, got = call(browser, "update", token=token, doc=f"sheaves/{SHARED}", text=PRIVATE,
                         expected_hash=md_hash(OPEN))
    assert not is_error and got["doc"] == f"sheaves/{HOME}", got
    assert subjects(repo) == [f"move: {SHARED} -> {HOME}", "first"]
    assert git(repo, "show", f"HEAD:{HOME}") == (repo / HOME).read_text(encoding="utf-8")
    assert git(repo, "status", "--porcelain") == ""


def test_an_untick_whose_private_home_is_taken_writes_nothing(team, work):
    shared = OPEN.replace("- [ ] Share", "- [x] Share")
    put(team, work, SHARED, shared)
    put(team, work, HOME, "# Something else\n")
    got = untick(team, work, SHARED, "Share", THIERRY)
    assert got.status == 409 and "held by another file" in got.json()["error"], got.text
    assert (work / SHARED).read_text(encoding="utf-8") == shared


def test_a_door_update_whose_private_home_is_taken_writes_nothing(team, work, browser, tokens):
    put(team, work, SHARED, OPEN)
    put(team, work, HOME, "# Something else\n")
    is_error, got = call(browser, "update", token=tokens["thierry"], doc=f"work/{SHARED}", text=PRIVATE,
                         expected_hash=md_hash(OPEN))
    assert is_error and "held by another file" in got, got
    assert (work / SHARED).read_text(encoding="utf-8") == OPEN


def test_a_door_update_answers_where_the_sheaf_is_when_the_poll_moves_it_meanwhile(team, work, browser, tokens,
                                                                                    monkeypatch):
    """Codex P2: the poll's move comes between the update's write and its own placing; the answer must still name
    the file's home, never the address it left."""
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
    assert not is_error and got["doc"] == f"work/{HOME}", got
    assert (work / HOME).read_text(encoding="utf-8").endswith("More.\n")


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
    assert f"D\t{SHARED}" in files and not any(HOME in f for f in files)
    assert any(line.startswith("D\t" + str(INSIDE / doc_key(SHARED))) for line in files)
    assert git(repo, "ls-files", SHARED) == ""
