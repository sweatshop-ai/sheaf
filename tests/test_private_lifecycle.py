"""The whole life of a private sheaf (SPEC 9.11): made, edited, ticked, commented on, shown with a picture and given a
version, it leaves the list repo as it was (no file, no commit, nothing to push, no word of its text), and its own repo
holds all of it. The member's own steps are the positive control: each of them is answered and written."""
import subprocess

import pytest
from helpers import call
from test_private_root_file import untouched
from test_private_root_visible import NAME, World
from two_roots import A, TwoRoots, git, two_roots

from sheafmd import beneath
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import place, state
from sheafmd.source import md_hash

SECRET = "Secret words."
TEXT = f"""---
issue: acme/record#1
owner: a
sources: [library:doc-1]
---
# post

- [ ] Approve

{SECRET}

![pic](pic.png)
"""
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea7c2f3050000000049454e44ae426082")


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def everything_of(repo) -> str:
    """Every byte the repo can show: its files, and every commit of every ref with its patch."""
    files = "".join(p.read_text(encoding="utf-8", errors="replace") for p in repo.rglob("*")
                    if p.is_file() and ".git" not in p.relative_to(repo).parts)
    return files + git(repo, "log", "--all", "-p", "--format=%B")


def test_private_lifecycle_leaves_list_repo_untouched(two):
    w = World(two, ["login-a"])
    git(two.list_repo, "push", "-q", "origin", "HEAD:main")
    def refs():     # every ref but the rewrite guard's own, which the hub keeps at the list repo's head
        return tuple([l for l in git(r, "for-each-ref").splitlines() if "refs/sheaf/last-seen/" not in l]
                     for r in (two.list_repo, two.base / "list.git"))
    before = (untouched(two), git(two.list_repo, "rev-parse", "HEAD"), git(two.base / "list.git", "rev-parse", "main"), refs())

    made = call(w.door, "create", token=w.tokens["tok-a"], doc=w.address, text=TEXT)
    assert not made[0], made
    (two.private_repo / "acme/blog/pic.png").write_bytes(PNG)
    mine = lambda method, path, body=None: w.front.request(method, path, member=A, body=body)      # noqa: E731
    text = (two.private_repo / NAME).read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Secret"))

    saved = mine("POST", "/_/save", {"doc": w.address, "hash": md_hash(text), "edits": [{"i": i, "html": "<p>Secret edit.</p>"}]})
    assert saved.status == 200, saved.body[:200]
    text = (two.private_repo / NAME).read_text(encoding="utf-8")
    assert "Secret edit." in text
    w.hub.the_list.poll()
    ticked = mine("POST", "/_/tick", {"doc": w.address, "action": 0, "word": "Approve", "hash": md_hash(text)})
    assert ticked.status == 200, ticked.body[:200]
    text = (two.private_repo / NAME).read_text(encoding="utf-8")
    assert "- [x] Approve" in text
    said = mine("POST", "/_/comment", {"doc": w.address, "op": "add", "hash": md_hash(text), "block": i, "start": 0, "end": 3,
                                       "quote": "Sec", "body": "A private remark."})
    assert said.status == 200, said.body[:200]
    text = (two.private_repo / NAME).read_text(encoding="utf-8")
    assert "A private remark." in text
    shown = mine("GET", f"/_/mount?doc={w.address}")
    assert shown.status == 200 and "data:image/png;base64," in shown.json()["html"]
    assert mine("POST", "/_/pin", {"doc": w.address, "hash": md_hash(text)}).status == 200
    w.hub.tick()                                            # the sweep of each repo's versions
    assert w.hub.commits.settle()

    # the list repo shows nothing new: no file, no commit, nothing waiting to be pushed, no word of the sheaf's text
    assert (untouched(two), git(two.list_repo, "rev-parse", "HEAD"), git(two.base / "list.git", "rev-parse", "main"), refs()) == before
    assert not (two.list_repo / state.INSIDE).exists()
    for repo in (two.list_repo, two.base / "list.git"):
        assert not any(word in everything_of(repo) for word in (SECRET, "Secret edit.", "A private remark.", "pic.png"))

    # the private repo holds all of it, and has pushed it
    assert NAME in git(two.private_repo, "ls-files")
    kept = (two.private_repo / NAME).read_text(encoding="utf-8")
    assert "ret edit." in kept and "- [x] Approve" in kept and "A private remark." in kept
    assert state.doc_key(NAME) in git(two.private_repo, "ls-files")
    subjects = git(two.private_repo, "log", "--format=%s")
    assert "tick" in subjects and f"versions: {NAME}" in subjects
    assert git(two.private_repo, "log", "origin/main..", "--oneline") == ""
    assert git(two.private_repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert subprocess.run(["git", "-C", str(two.base / "private.git"), "cat-file", "-e", f"main:{NAME}"]).returncode == 0


def test_the_set_of_private_folders_only_grows_and_only_hides(two):
    """`opened_private` records the folder at a private root's path each time it looks. A stray folder read there stays
    private afterwards, and so does a private folder moved away: a wrong answer can only hide a file from the shared
    reader, never show one, so the set is not pruned (SPEC 9.9)."""
    w = World(two, ["login-a"])
    root = w.hub.the_list.root()
    away = two.base / "private-away"
    (two.private_repo / "acme/blog").mkdir(parents=True, exist_ok=True)
    (two.private_repo / NAME).write_text(TEXT, encoding="utf-8")
    two.private_repo.rename(away)                              # the private folder moved off its path
    two.private_repo.mkdir()                                   # a stray folder takes the path
    (two.private_repo / "note.md").write_text("# stray\n", encoding="utf-8")
    for top, rel in ((two.private_repo, "note.md"), (away, NAME)):
        with beneath.open_beneath(top, rel) as op:
            assert place.opened_private(w.hub, op) == "member-a-id"      # the stray, and the one moved away
    shared = two.list_repo / "acme/blog"
    shared.mkdir(parents=True, exist_ok=True)
    two.private_repo.rename(shared / "stray")                  # the stray folder now sits in the shared root
    with pytest.raises(OSError):
        w.hub.open_in(root, "acme/blog/stray/note.md")         # over-hidden from the shared reader, as a private file is
    (shared / "open.md").write_text("# open\n", encoding="utf-8")
    with w.hub.open_in(root, "acme/blog/open.md") as op:       # positive control: a shared file beside it reads as ever
        assert op.text() == "# open\n"
    with beneath.open_beneath(away, NAME) as op:
        assert place.opened_private(w.hub, op) == "member-a-id"          # and nothing private ever turns shared
