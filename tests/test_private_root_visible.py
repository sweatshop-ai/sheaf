"""A file of a private root is visible only to that root's member, on every route (SPEC 9.11): whatever the issue's
assignees, `projects.toml` or the front matter say, another member and a token bound to nobody get the 404 of a missing
document, and a file that names a member as its owner in the list's repo is nobody's. Each refusal has the owner's own
call as its positive control, on the same route."""
import os
from pathlib import Path
import time

import pytest
from helpers import Front, browser_on, call, comment, hub_rows
from two_roots import A, B, TwoRoots, git, two_roots

from sheafmd.blocks import split_md_blocks
from sheafmd.hub import the_list
from sheafmd.hub.index import SWEEP_SECONDS
from sheafmd.hub.state import Tokens
from sheafmd.source import md_hash

NAME = "acme/blog/post.md"
SID = "6f1c0e9a-2b3d-4c5e-8f70-1a2b3c4d5e6f"
CWD = "/home/box/work/acme/blog"
TRANSCRIPT = b'{"type":"user","cwd":"%s","sessionId":"%s","message":"hello"}\n' % (CWD.encode(), SID.encode())
PRIVATE = f"""---
issue: acme/record#1
owner: a
sources: [library:doc-1]
sessions:
  - {{id: {SID}, host: the-box, member: a, date: 2026-11-01T05:12:03Z}}
---
# post

Secret words.
"""
PROJECT_WIDE = PRIVATE.replace("sources: [library:doc-1]", "sources: [issue:acme/record#1]")    # open to the project


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


class World:
    def __init__(self, two: TwoRoots, assignees):
        self.two = two
        self.tokens = {n: Tokens().add(n, write=True) for n in ("tok-a", "tok-b", "loose")}
        cfg = two.config(a={"github": "login-a", "tokens": ["tok-a"]}, b={"github": "login-b", "tokens": ["tok-b"]})
        self.hub = two.hub(cfg)
        sessions = two.base / "sessions"
        (sessions / "-home-box-work-acme-blog").mkdir(parents=True)
        (sessions / "-home-box-work-acme-blog" / f"{SID}.jsonl").write_bytes(TRANSCRIPT)
        self.hub.the_list = the_list.TheList(self.hub, the_list.parse(
            {"root": str(two.list_repo), "repo": "acme/record", "project": 1, "token_file": str(two.base / "token"),
             "sessions_dir": str(sessions), "box": "the-box", "work_dir": "/home/box/work"}, "the test"))
        self.hub.assignees = lambda address, fm: assignees
        self.root = self.hub.the_list.root()
        for repo in (two.list_repo, two.private_repo):
            (repo / "acme/blog").mkdir(parents=True, exist_ok=True)
        (two.list_repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a", "b"]\nstatus = "live"\n',
                                                     encoding="utf-8")
        self.door = browser_on(self.hub)
        self.front = Front(self.hub, self.door.handler)
        self.address = f"{self.root.name}/{NAME}"

    def put(self, text, repo=None):
        (repo or self.two.private_repo).joinpath(NAME).write_text(text, encoding="utf-8")


@pytest.fixture
def world(two):
    return World(two, ["login-a", "login-b"])      # the issue is also assigned to member B: the assignees would own the sheaf


def listed(w: World, member) -> list:
    """The documents the index shows `member` under the sheaf's name, wherever the hub lists its file."""
    got = w.front.get("/_/index.json", member=member)
    assert got.status == 200
    return [d["doc"] for r in got.json()["roots"] for d in r["docs"] if d["doc"].endswith(NAME)]


def routes(w: World, text: str):
    """(name, method, path, body) of each route of the members' socket that names the sheaf (Ask, Tell, Jump and Cancel
    are routes of the loopback port only, and a member is told there is no such route)."""
    a, h = w.address, md_hash(text)
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Secret"))
    return [
        ("page", "GET", f"/{a}", None),
        ("doc", "GET", f"/_/doc?doc={a}", None),
        ("mount", "GET", f"/_/mount?doc={a}", None),
        ("stream", "GET", f"/_/live?doc={a}", None),
        ("save", "POST", "/_/save", {"doc": a, "hash": h, "edits": [{"i": i, "html": "<p>Changed.</p>"}]}),
        ("comment", "POST", "/_/comment", {"doc": a, "op": "add", "hash": h, "block": i, "start": 0, "end": 3,
                                           "quote": "Sec", "body": "hi"}),
        ("code", "POST", "/_/code", {"doc": a}),
        ("export", "POST", "/_/export", {"doc": a, "kind": "html"}),
        ("pin", "POST", "/_/pin", {"doc": a, "hash": h}),
        ("tick", "POST", "/_/tick", {"doc": a, "hash": h, "n": 0}),
        ("seen", "POST", "/_/seen", {"doc": a, "id": "c1"}),
        ("sessions", "POST", "/_/sessions", {"doc": a, "id": SID, "machine": "m"}),
        ("transcript", "GET", f"/_/session?doc={a}&id={SID}", None),
    ]


def test_assignee_does_not_open_private_sheaf(world):
    w = world
    w.put(PRIVATE)
    table = routes(w, PRIVATE)
    for name, method, path, body in table:
        gone = w.front.request(method, path, member=B, body=body)
        assert gone.status == 404, (name, gone.status, gone.body[:200])
        other = path.replace("post.md", "none.md")
        missing = w.front.request(method, other, member=B, body=body and {**body, "doc": body["doc"].replace("post.md", "none.md")})
        assert (gone.status, gone.body) == (missing.status, missing.body) or name == "page", name
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PRIVATE        # nothing was written
    assert "Secret words." in w.front.get(f"/_/mount?doc={w.address}", member=A).json()["html"]
    for name, method, path, body in table:                                           # the owner's call, the same route
        own = w.front.request(method, path, member=A, body=body)
        assert not (own.status == 404 and b"no such document" in own.body), (name, own.status, own.body[:200])


def test_assignee_has_no_row_and_no_event(world, monkeypatch):
    w = world
    w.put(PRIVATE)
    assert not listed(w, B)          # the owner's row, under the list's name, is the next change's (rule D)
    now = [time.time()]
    w.hub.clock = lambda: now[0]
    monkeypatch.setattr(w.hub.index, "_start_sweep", lambda run: run())          # a sweep inside the tick
    mine, theirs = (w.front.get("/_/live", member=m).stream for m in (A, B))
    for m in (A, B):
        w.front.get("/_/index.json", member=m)
    now[0] += SWEEP_SECONDS
    w.hub.tick()
    mine.drain(), theirs.drain()
    (w.two.private_repo / NAME).unlink()                  # a change both streams would be told of if both could see it
    now[0] += SWEEP_SECONDS
    w.hub.tick()
    mine.drain()                                          # the owner's status, under the list's name, is the next change's
    assert [d for n, d in theirs.drain() if n == "status"] == []


def test_unbound_token_by_the_private_roots_own_address(world):
    w = world
    w.put(PROJECT_WIDE)
    direct = f"{w.hub.roots.lookup(w.two.private_repo / NAME).name}/{NAME}"
    assert direct != w.address
    for doc in (direct, str(w.two.private_repo / NAME)):
        for tool, args in (("read", {}), ("threads", {}),
                           ("update", {"text": PROJECT_WIDE + "x", "expected_hash": md_hash(PROJECT_WIDE)})):
            assert call(w.door, tool, token=w.tokens["loose"], doc=doc, **args)[0], (doc, tool)
    is_error, got = call(w.door, "documents", token=w.tokens["loose"], open_only=False)
    assert not is_error and NAME not in str(got)
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PROJECT_WIDE
    assert call(w.door, "read", token=w.tokens["tok-a"], doc=direct)[0]                   # the root has no address, not even the owner's
    assert not call(w.door, "read", token=w.tokens["tok-a"], doc=w.address)[0]            # the owner reads it by its list name


def test_a_nobodys_sheaf_gone_is_told_to_its_named_owner_no_more_than_before(world):
    w = world
    w.put(PRIVATE, w.two.list_repo)
    w.hub.assignees = lambda address, fm: None
    a = w.hub.proxy.members[A]
    assert not w.hub.visible(a, w.address)
    w.hub.member_owns(a, w.address)                       # a call with no front matter must not forget it was nobody's
    (w.two.list_repo / NAME).unlink()
    assert not w.hub.visible(a, w.address, never_read=False)


@pytest.mark.parametrize("tool", ["read", "update", "threads"])
def test_door_gives_an_assignee_and_a_loose_token_nothing_of_private_sheaf(world, tool):
    w = world
    w.put(PRIVATE)
    args = {"read": {}, "update": {"text": PRIVATE.replace("Secret", "Changed"), "expected_hash": md_hash(PRIVATE)},
            "threads": {}}[tool]
    for token in ("tok-b", "loose"):
        is_error, got = call(w.door, tool, token=w.tokens[token], doc=w.address, **args)
        _, missing = call(w.door, tool, token=w.tokens[token], doc=f"{w.root.name}/acme/blog/none.md", **args)
        assert is_error and got == missing.replace("none.md", "post.md"), (tool, token, got)
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PRIVATE
    if tool == "read":
        is_error, got = call(w.door, tool, token=w.tokens["tok-a"], doc=w.address)          # positive control
        assert not is_error and "Secret words." in str(got)


def test_door_listings_leave_out_private_sheaf(world):
    w = world
    w.put(PRIVATE)
    for token in ("tok-a", "tok-b", "loose"):         # the owner's rows, under the list's name, are the next change's (rule D)
        is_error, got = call(w.door, "documents", token=w.tokens[token], open_only=False)
        assert not is_error and NAME not in str(got), (token, got)


def test_unbound_token_private_root(world):
    w = world
    w.put(PROJECT_WIDE)                                  # a file that says it is open to the project, in a private root
    assert w.front.get(f"/{w.address}", member=B).status == 404
    for tool, args in (("read", {}), ("update", {"text": PROJECT_WIDE + "x", "expected_hash": md_hash(PROJECT_WIDE)})):
        is_error, got = call(w.door, tool, token=w.tokens["loose"], doc=w.address, **args)
        assert is_error, (tool, got)
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PROJECT_WIDE
    is_error, got = call(w.door, "read", token=w.tokens["tok-a"], doc=w.address)             # positive control
    assert not is_error
    w.put(PROJECT_WIDE, w.two.list_repo)                 # the same text as a file of the list's repo is open to all
    (w.two.private_repo / NAME).unlink()
    assert not call(w.door, "read", token=w.tokens["loose"], doc=w.address)[0]
    assert w.front.get(f"/{w.address}", member=B).status == 200


def test_owner_file_in_shared_repo_invisible(world):
    w = world
    w.put(PRIVATE, w.two.list_repo)                      # pushed into the shared repo by someone else, naming A as owner
    w.hub.assignees = lambda address, fm: None
    for member in (A, B):
        assert w.front.get(f"/{w.address}", member=member).status == 404, member
    for token in ("tok-a", "tok-b", "loose"):
        assert call(w.door, "read", token=w.tokens[token], doc=w.address)[0], token
    assert not listed(w, A) and not listed(w, B)
    w.hub.the_list.poll()
    assert [r["doc"] for r in hub_rows("place-refused")] == [w.address]            # and a row says why
    (w.two.list_repo / "acme/blog/open.md").write_text(PROJECT_WIDE, encoding="utf-8")       # control: an open one is seen
    assert w.front.get(f"/{w.root.name}/acme/blog/open.md", member=B).status == 200


def test_private_sheaf_gone_is_told_to_nobody_else(world):
    w = world
    w.put(PRIVATE)
    assert w.front.get(f"/{w.address}", member=B).status == 404           # the hub judged it, as an index would
    (w.two.private_repo / NAME).unlink()
    members = w.hub.proxy.members
    assert not w.hub.visible(members[B], w.address)                      # not the last good read, which was project-wide
    assert not w.hub.visible(members[B], w.address, never_read=False)


def test_transcript_private_sheaf(world):
    w = world
    w.put(PRIVATE)
    got = w.front.get(f"/_/session?doc={w.address}&id={SID}", member=A)                      # positive control
    assert got.status == 200 and got.body == TRANSCRIPT
    for who in (B,):
        assert w.front.get(f"/_/session?doc={w.address}&id={SID}", member=who).status == 404
        assert w.front.get(f"/_/session?doc={w.address}", member=who).status == 404


def moved_to_private(w: World, text: str):
    """The sheaf open on a page bound to the list's repo, then its file gone from there and held by the private repo."""
    w.put(PROJECT_WIDE, w.two.list_repo)
    w.hub.entry(w.address)
    (w.two.list_repo / NAME).unlink()
    w.put(text)


@pytest.mark.parametrize("tool", ["update", "reply"])
def test_door_write_through_an_entry_bound_to_the_list_repo(world, tool):
    w = world
    moved_to_private(w, PRIVATE)
    comment(w.two.private_repo / NAME, quote="Secret words.")
    text = (w.two.private_repo / NAME).read_text(encoding="utf-8")
    args = {"update": {"text": text + "\nChanged words.\n", "expected_hash": md_hash(text)},
            "reply": {"id": "c1", "text": "Done."}}[tool]
    is_error, got = call(w.door, tool, token=w.tokens["tok-a"], doc=w.address, **args)
    assert not is_error, got
    assert ("Changed words." if tool == "update" else "Done.") in (w.two.private_repo / NAME).read_text(encoding="utf-8")
    assert w.hub.commits.settle()
    assert NAME in git(w.two.base / "private.git", "log", "--name-only", "--format=").split()
    assert not (w.two.list_repo / NAME).exists() and not hub_rows("commit-refused")


def test_a_root_around_the_private_root_is_not_registered(world):
    """Rule 1 (SPEC 9.11): no registered root encloses, equals or lies inside a private root: a render of a folder above
    both repos registers nothing."""
    from sheafmd.hub.roots import Nested
    w = world
    (w.two.base / "note.md").write_text("# note\n", encoding="utf-8")
    before = {r.name for r in w.hub.roots.all()}
    with pytest.raises(Nested):
        w.hub.roots.for_document(w.two.base / "note.md")
    assert {r.name for r in w.hub.roots.all()} == before


def test_the_hub_does_not_start_with_a_root_around_a_private_root(two):
    from sheafmd.hub.proxy import ProxyError
    cfg = two.config(a={"github": "login-a", "tokens": ["tok-a"]}, b={"github": "login-b", "tokens": ["tok-b"]})
    (two.base / "note.md").write_text("# note\n", encoding="utf-8")
    from sheafmd.hub.roots import Roots
    Roots()._add(two.base, False)                       # the registry holds a root above both repos, as an older hub left it
    with pytest.raises(ProxyError, match="encloses or lies inside the private root"):
        two.hub(cfg)


def test_the_hub_does_not_start_without_the_private_root_folder(two):
    import shutil

    from sheafmd.hub.proxy import ProxyError
    cfg = two.config(a={"github": "login-a", "tokens": ["tok-a"]}, b={"github": "login-b", "tokens": ["tok-b"]})
    shutil.rmtree(two.private_repo)
    with pytest.raises(ProxyError, match="is not a folder"):
        two.hub(cfg)


def test_a_deletion_is_told_to_nobody_else_whoever_read_the_file_first(world, monkeypatch):
    w = world
    w.put(PRIVATE)
    w.hub.entry(w.address)                                # the file read by the hub alone, never through a member's check
    w.hub.judged(w.address)
    (w.two.private_repo / NAME).unlink()
    b = w.hub.proxy.members[B]
    assert not w.hub.visible(b, w.address, never_read=False)


def _create_docs(w: World) -> dict:
    """The ways a door `create` can name a new page inside the private root: its own registered name, a root around it."""
    own = w.hub.roots.lookup(w.two.private_repo / NAME).name
    return {"own": f"{own}/acme/blog/new.md", "own-taken": f"{own}/{NAME}",
            "own-nofolder": f"{own}/nowhere/at/all/new.md"}


@pytest.mark.parametrize("who", ["loose", "tok-b"])
def test_door_create_in_a_private_root_is_a_path_in_no_root_and_probes_nothing(world, who):
    w = world
    w.put(PROJECT_WIDE)
    docs = _create_docs(w)
    answers = {}
    for key, doc in docs.items():
        is_error, got = call(w.door, "create", token=w.tokens[who], doc=doc, text="# new\n")
        assert is_error, (key, got)
        answers[key] = str(got).replace(doc, "<doc>")
    assert len(set(answers.values())) == 1, answers          # taken, free and no folder are told apart by nothing
    assert not (w.two.private_repo / "acme/blog/new.md").exists()
    assert not (w.two.private_repo / "nowhere").exists()
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PROJECT_WIDE


def test_door_create_in_a_private_root_by_a_loose_token_writes_no_commit(world):
    w = world
    w.put(PROJECT_WIDE)
    before = git(w.two.private_repo, "rev-list", "--count", "HEAD")
    call(w.door, "create", token=w.tokens["loose"], doc=_create_docs(w)["own"], text="# new\n")
    assert w.hub.commits.settle()
    assert git(w.two.private_repo, "rev-list", "--count", "HEAD") == before
    assert not (w.two.private_repo / "acme/blog/new.md").exists()


def test_a_forgotten_private_root_is_still_private(world):
    w = world
    w.put(PROJECT_WIDE)
    own = w.hub.roots.lookup(w.two.private_repo / NAME).name
    w.hub.forget_root(own)
    assert own not in {r.name for r in w.hub.roots.all()} and w.hub._private_paths
    for tool, args in (("read", {}), ("threads", {}),
                       ("update", {"text": PROJECT_WIDE + "x", "expected_hash": md_hash(PROJECT_WIDE)})):
        assert call(w.door, tool, token=w.tokens["loose"], doc=w.address, **args)[0], tool
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PROJECT_WIDE


@pytest.mark.parametrize("forget", [False, True])
@pytest.mark.parametrize("tool", ["reply", "resolve", "threads"])
def test_door_comment_verbs_by_a_loose_token_reach_nothing_of_a_private_root(world, tool, forget):
    w = world
    w.put(PROJECT_WIDE)
    comment(w.two.private_repo / NAME, quote="Secret words.")
    own = w.hub.roots.lookup(w.two.private_repo / NAME).name
    docs = [f"{own}/{NAME}", w.address]
    if forget:
        w.hub.forget_root(own)
        docs = docs[1:]
    args = {"reply": {"id": "c1", "text": "Done."}, "resolve": {"id": "c1"}, "threads": {}}[tool]
    before = (w.two.private_repo / NAME).read_text(encoding="utf-8")
    for doc in docs:
        assert call(w.door, tool, token=w.tokens["loose"], doc=doc, **args)[0], doc
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == before


# ── the invariant, as a table (place.py, Rule A): what a caller gets is decided by the real path alone ──────────

def _refuse_registration(monkeypatch, repo):
    import dataclasses

    from sheafmd.hub.roots import Roots
    real = Roots.for_document

    def for_document(self, md):
        root = real(self, md)
        return dataclasses.replace(root, git=False) if str(root.path) == str(repo.resolve()) else root
    monkeypatch.setattr(Roots, "for_document", for_document)


def _state_world(two, monkeypatch, state):
    if state == "refused":
        _refuse_registration(monkeypatch, two.private_repo)
    w = World(two, ["login-a", "login-b"])
    w.put(PROJECT_WIDE)
    comment(two.private_repo / NAME, quote="Secret words.")
    own = w.hub.roots.lookup(two.private_repo / NAME).name
    if state == "refused":
        assert not w.hub.private_roots and w.hub._private_paths
    if state == "forgotten":
        w.hub.forget_root(own)
    docs = {"registered": [f"{own}/{NAME}", w.address],
            "refused": [f"{own}/{NAME}"],
            "forgotten": [w.address],
            "list": [w.address]}[state]
    return w, docs


def _args(tool, doc):
    return {"read": {}, "threads": {}, "reply": {"id": "c1", "text": "Done."}, "resolve": {"id": "c1"},
            "update": {"text": PROJECT_WIDE + "x", "expected_hash": md_hash(PROJECT_WIDE)},
            "create": {"text": "# new\n"}}[tool]


@pytest.mark.parametrize("state", ["registered", "refused", "forgotten", "list"])
@pytest.mark.parametrize("kind", ["tok-b", "loose"])
@pytest.mark.parametrize("tool", ["read", "threads", "reply", "resolve", "update", "create", "documents"])
def test_invariant_table_a_caller_that_is_not_the_member_gets_nothing_inside_the_set(two, monkeypatch, state, kind, tool):
    w, docs = _state_world(two, monkeypatch, state)
    before = (two.private_repo / NAME).read_text(encoding="utf-8")
    if state == "forgotten" and tool == "create":
        docs = []           # a forgotten root holds no name: a list name is free to make, as any free name (9.11)
    for doc in docs:
        if tool == "documents":
            root = doc.split("/")[0]
            is_error, got = call(w.door, tool, token=w.tokens[kind], open_only=False, root=root)
            assert NAME not in str(got), (doc, got)
            continue
        # a new page in the list's root is the caller's to make; the name already taken is not made again
        target = doc.replace(NAME, "acme/blog/new.md") if tool == "create" and doc != w.address else doc
        is_error, got = call(w.door, tool, token=w.tokens[kind], doc=target, **_args(tool, doc))
        assert is_error, (doc, got)
    assert w.hub.commits.settle()
    assert (two.private_repo / NAME).read_text(encoding="utf-8") == before
    assert not (two.private_repo / "acme/blog/new.md").exists()


@pytest.mark.parametrize("state", ["registered", "list"])
@pytest.mark.parametrize("kind", ["tok-a", None])
@pytest.mark.parametrize("tool", ["read", "threads"])
def test_invariant_table_the_member_and_the_key_are_the_controls(two, monkeypatch, state, kind, tool):
    w, docs = _state_world(two, monkeypatch, state)
    token = w.tokens[kind] if kind else None
    for doc in docs:
        if doc != w.address:                    # the private root has no address of its own, not even for its member
            assert call(w.door, tool, token=token, doc=doc, **_args(tool, doc))[0], (kind, doc)
            continue
        is_error, got = call(w.door, tool, token=token, doc=doc, **_args(tool, doc))
        assert not is_error, (kind, doc, got)


@pytest.mark.parametrize("who", ["loose", "tok-b"])
def test_a_list_address_create_tells_a_privately_held_name_from_none_no_more_than_a_shared_one(world, who):
    w = world
    w.put(PROJECT_WIDE)
    (w.two.list_repo / "acme/blog/shared.md").write_text("# shared\n", encoding="utf-8")
    held = call(w.door, "create", token=w.tokens[who], doc=w.address, text="# new\n")
    shared = call(w.door, "create", token=w.tokens[who], doc=f"{w.root.name}/acme/blog/shared.md", text="# new\n")
    assert held[0] and shared[0]
    # byte for byte: private-held, shared-held, and (after deletion) free
    assert held[1].replace(w.address, "<d>") == shared[1].replace(f"{w.root.name}/acme/blog/shared.md", "<d>")
    (w.two.private_repo / NAME).unlink()
    assert not call(w.door, "create", token=w.tokens[who], doc=w.address, text="# new\n")[0]   # free again once gone


# ── in_private by file identity: a spelling in another case is the same folder where the filesystem folds case ───

class _Hub:
    def __init__(self, paths, ids):
        self._private_paths, self._private_ids = paths, ids


def _fake_stat(table):
    """A stat for a filesystem that folds case: a path's identity is that of its lowercased spelling."""
    import types

    def stat(path):
        if path.lower() not in table:
            raise FileNotFoundError(path)
        dev, ino = table[path.lower()]
        return types.SimpleNamespace(st_dev=dev, st_ino=ino, st_mode=0)
    return stat


def test_in_private_by_identity_finds_a_case_variant_spelling_of_the_private_root():
    from sheafmd.hub import place
    hub = _Hub({"/outer/private/acme": "a"}, {(1, 42): "a"})
    stat = _fake_stat({"/": (1, 1), "/outer": (1, 2), "/outer/private": (1, 3), "/outer/private/acme": (1, 42),
                       "/outer/private/acme/blog": (1, 43)})
    assert place.in_private(hub, "/outer/Private/acme/blog/new.md", stat) == "a"      # the file is not there yet
    assert place.in_private(hub, "/outer/PRIVATE/ACME", stat) == "a"                  # the top itself
    assert place.in_private(hub, "/outer/private/acme/blog/post.md", stat) == "a"     # the path test, unchanged
    assert place.in_private(hub, "/outer/Shared/acme/blog/new.md", stat) is None      # a neighbour is not inside
    assert place.in_private(hub, "/outer/Private/other/x.md", stat) is None
    assert place.in_private(_Hub({}, {}), "/outer/Private/acme/x.md", stat) is None


def test_in_private_by_identity_is_off_without_a_stat_answer():
    from sheafmd.hub import place
    hub = _Hub({"/outer/private/acme": "a"}, {(1, 42): "a"})
    assert place.in_private(hub, "/elsewhere/x.md", _fake_stat({})) is None


def test_the_hub_records_the_identity_of_each_configured_private_root(world):
    w = world
    assert list(w.hub._private_ids.values()) == list(w.hub._private_paths.values()) == ["member-a-id"]


# ── rule 2: one open, judged on what was opened (sheafmd.beneath) ───────────────────────────────────────────────

@pytest.fixture(params=["openat2", "walk"])
def mode(request, monkeypatch):
    from sheafmd import beneath
    monkeypatch.setattr(beneath, "FALLBACK", request.param == "walk")
    return request.param


def _shared_root(w: World):
    """A root that is no private root's, with a link `x` inside it that the test swaps: (its name, the folder, the link)."""
    top = w.two.base / "shared"
    for sub in ("one", "two"):
        (top / sub / "acme/blog").mkdir(parents=True)
        (top / sub / NAME).write_text(f"# {sub}\n\nShared words {sub}.\n", encoding="utf-8")
    (top / "x").symlink_to("one")
    (top / "note.md").write_text("# note\n", encoding="utf-8")
    root = w.hub.roots.for_document(top / "note.md")          # a folder of its own: a root that holds `one`, `two` and `x`
    assert root.path == top.resolve()
    return root, top, top / "x"


def _swap(link, target):
    tmp = link.with_name(link.name + ".tmp")
    tmp.symlink_to(target)
    os.replace(tmp, link)


def test_a_link_swapped_between_the_check_and_the_open_to_a_private_root_gives_no_private_byte(world, mode, monkeypatch):
    """The reviewer's race, made deterministic: the link is swapped for one to the private repo after the first look at
    the address and before the file is opened. The open is beneath the root, so a link out of it is refused."""
    from sheafmd import beneath
    w = world
    w.put(PRIVATE)
    root, top, link = _shared_root(w)
    doc = f"{root.name}/x/{NAME}"
    assert not call(w.door, "read", token=w.tokens["loose"], doc=doc)[0]
    real = beneath.open_beneath
    calls = []

    def swapping(t, rel):
        if not calls:
            calls.append(1)
            _swap(link, w.two.private_repo)
        return real(t, rel)
    monkeypatch.setattr(beneath, "open_beneath", swapping)
    is_error, got = call(w.door, "read", token=w.tokens["loose"], doc=doc)
    assert calls and "Secret words" not in str(got)
    assert is_error


def test_a_link_swapped_to_another_place_inside_the_root_is_followed_as_before(world, mode, monkeypatch):
    from sheafmd import beneath
    w = world
    root, top, link = _shared_root(w)
    doc = f"{root.name}/x/{NAME}"
    real = beneath.open_beneath
    monkeypatch.setattr(beneath, "open_beneath", lambda t, rel: (_swap(link, "two"), real(t, rel))[1])
    is_error, got = call(w.door, "read", token=w.tokens["loose"], doc=doc)
    assert not is_error and "Shared words two." in str(got)


def test_a_link_to_a_private_root_in_the_path_of_a_door_read_update_and_comment_is_refused(world, mode):
    w = world
    w.put(PRIVATE)
    comment(w.two.private_repo / NAME, quote="Secret words.")
    root, top, link = _shared_root(w)
    link.unlink()
    link.symlink_to(w.two.private_repo)             # a folder link, then a file link, to the private repo
    (top / "f.md").symlink_to(w.two.private_repo / NAME)
    before = (w.two.private_repo / NAME).read_text(encoding="utf-8")
    for doc in (f"{root.name}/x/{NAME}", f"{root.name}/f.md"):
        for tool, args in (("read", {}), ("threads", {}), ("reply", {"id": "c1", "text": "Done."}),
                           ("update", {"text": PRIVATE + "x", "expected_hash": md_hash(PRIVATE)})):
            is_error, got = call(w.door, tool, token=w.tokens["loose"], doc=doc, **args)
            assert is_error and "Secret" not in str(got), (doc, tool)
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == before


def test_the_walk_and_the_kernel_open_say_the_same_for_links(tmp_path, mode):
    from sheafmd import beneath
    top, out = tmp_path / "top", tmp_path / "out"
    (top / "a/b").mkdir(parents=True)
    out.mkdir()
    (top / "a/b/f.md").write_text("hi", encoding="utf-8")
    (out / "s.md").write_text("secret", encoding="utf-8")
    (top / "a/lnk").symlink_to("b")
    (top / "rel.md").symlink_to("a/b/f.md")
    (top / "abs.md").symlink_to(top / "a/b/f.md")
    (top / "out.md").symlink_to(out / "s.md")
    (top / "up.md").symlink_to("../out/s.md")
    (top / "a/dots.md").symlink_to("../../out/s.md")
    (top / "loop.md").symlink_to("loop.md")
    for rel in ("a/b/f.md", "a/lnk/f.md", "rel.md", "abs.md", "a/../a/b/f.md"):
        with beneath.open_beneath(top, rel) as op:
            assert op.text() == "hi", rel
    for rel in ("out.md", "up.md", "a/dots.md", "loop.md", "../out/s.md", "a", "nope.md"):
        with pytest.raises(OSError):
            beneath.open_beneath(top, rel)


def test_a_write_through_a_link_replaces_the_target_and_only_while_it_is_the_opened_file(tmp_path, mode):
    from sheafmd import beneath
    top = tmp_path / "top"
    top.mkdir()
    (top / "f.md").write_text("one", encoding="utf-8")
    (top / "l.md").symlink_to("f.md")
    with beneath.open_beneath(top, "l.md") as op:
        op.write("two")
    assert (top / "l.md").is_symlink() and (top / "f.md").read_text(encoding="utf-8") == "two"
    with beneath.open_beneath(top, "l.md") as op:
        (top / "g.md").write_text("other", encoding="utf-8")
        os.replace(top / "g.md", top / "f.md")              # someone else replaced the file since it was opened
        with pytest.raises(OSError):
            op.write("three")
    assert (top / "f.md").read_text(encoding="utf-8") == "other" and not list(top.glob(".*tmp"))


def test_privacy_is_judged_on_the_descriptors_of_the_open(world, mode):
    from sheafmd import beneath
    from sheafmd.hub import place
    w = world
    w.put(PRIVATE)
    with beneath.open_beneath(w.two.private_repo, NAME) as op:
        assert place.opened_private(w.hub, op) == "member-a-id"
    root, top, _ = _shared_root(w)
    with beneath.open_beneath(root.path, f"x/{NAME}") as op:
        assert place.opened_private(w.hub, op) is None


def test_a_link_swapped_at_random_between_a_shared_folder_and_a_private_one_never_gives_a_private_byte(world, mode):
    """The real race, many reads: SHEAF_RACE_READS (default 150) door reads while a thread swaps the link `x`."""
    import threading
    w = world
    w.put(PRIVATE)
    root, top, link = _shared_root(w)
    doc, stop, got_shared, leaked = f"{root.name}/x/{NAME}", threading.Event(), 0, 0

    def swapper():
        n = 0
        while not stop.is_set():
            _swap(link, w.two.private_repo if n % 2 else "one")
            n += 1
    t = threading.Thread(target=swapper)
    t.start()
    try:
        for _ in range(int(os.environ.get("SHEAF_RACE_READS", "150"))):
            is_error, got = call(w.door, "read", token=w.tokens["loose"], doc=doc)
            leaked += "Secret words" in str(got)
            got_shared += (not is_error) and "Shared words one" in str(got)
    finally:
        stop.set()
        t.join()
    assert leaked == 0 and got_shared > 0


def test_no_walk_goes_through_a_sheaf_or_git_folder_by_its_path_or_by_a_link(tmp_path, mode):
    from sheafmd import beneath
    top = tmp_path / "top"
    for own in (".git", ".sheaf"):
        (top / own).mkdir(parents=True)
        (top / own / "f.md").write_text("own", encoding="utf-8")
    (top / "ok.md").write_text("ok", encoding="utf-8")
    (top / "viagit.md").symlink_to(".git/f.md")                 # a link whose target names it
    (top / "viasheaf.md").symlink_to(".sheaf/f.md")
    (top / "folder").symlink_to(".git")                          # a link to the folder, then a name below it
    (top / "okay.md").symlink_to("ok.md")
    for rel in (".git/f.md", ".sheaf/f.md", "viagit.md", "viasheaf.md", "folder/f.md", "a/.git/f.md"):
        with pytest.raises(FileNotFoundError):
            beneath.open_beneath(top, rel)
    with beneath.open_beneath(top, "okay.md") as op:
        assert op.text() == "ok"


def test_an_absolute_link_is_followed_from_the_root_wherever_the_walk_is_and_refused_outside_it(tmp_path, mode):
    from sheafmd import beneath
    top, out = tmp_path / "top", tmp_path / "out"
    (top / "a/b").mkdir(parents=True)
    out.mkdir()
    (top / "f.md").write_text("hi", encoding="utf-8")
    (out / "s.md").write_text("secret", encoding="utf-8")
    (top / "a/b/in.md").symlink_to(top / "f.md")                # from a folder deep in the walk, to a place above it
    (top / "a/b/out.md").symlink_to(out / "s.md")
    (top / "a/b/root.md").symlink_to(top)                       # the root itself is no file
    with beneath.open_beneath(top, "a/b/in.md") as op:
        assert op.text() == "hi"
    for rel in ("a/b/out.md", "a/b/root.md"):
        with pytest.raises(OSError):
            beneath.open_beneath(top, rel)


def test_a_document_the_hub_holds_never_opens_a_file_that_the_descriptors_say_is_a_private_roots(world, mode):
    w = world
    w.put(PRIVATE)
    root, top, _ = _shared_root(w)
    address = f"{root.name}/one/{NAME}"
    e = w.hub.entry(address)
    assert "Shared words one" in e.read()
    st = os.stat(top / "one" / NAME)
    w.hub._private_ids[(st.st_dev, st.st_ino)] = "member-a-id"     # as if the folder it lies in were a private root's (a mount)
    before = (top / "one" / NAME).read_text(encoding="utf-8")
    with pytest.raises(OSError):
        e.read()
    with pytest.raises(OSError):
        e.stat()
    with pytest.raises(OSError):
        e.live.comment("add", {"block": 0, "start": 0, "end": 3, "quote": "abc", "body": "leak"}, None)
    with pytest.raises(OSError):
        e.live.rewrite(lambda t: t + "\nmore\n")
    assert (top / "one" / NAME).read_text(encoding="utf-8") == before


def test_a_file_with_two_names_is_not_opened_in_either_mode(tmp_path, mode):
    from sheafmd import beneath
    top = tmp_path / "top"
    top.mkdir()
    (top / "one.md").write_text("hi", encoding="utf-8")
    with beneath.open_beneath(top, "one.md") as op:
        assert op.text() == "hi"
    os.link(top / "one.md", top / "two.md")
    for rel in ("one.md", "two.md"):
        with pytest.raises(beneath.Linked):
            beneath.open_beneath(top, rel)
    os.unlink(top / "two.md")
    with beneath.open_beneath(top, "one.md") as op:
        assert op.text() == "hi"


def test_a_private_file_hard_linked_into_a_shared_root_is_read_by_no_door(world, mode):
    w = world
    w.put("# Plain\n\nSecret words, visible to the project.\n")      # nothing in its text keeps it from a token
    root, top, _ = _shared_root(w)
    try:
        os.link(w.two.private_repo / NAME, top / "twin.md")
    except OSError:
        pytest.skip("this folder cannot hard-link across to the private repo")
    for tool, args in (("read", {}), ("threads", {}), ("reply", {"id": "c1", "text": "Done."})):
        is_error, got = call(w.door, tool, token=w.tokens["loose"], doc=f"{root.name}/twin.md", **args)
        assert is_error and "Secret" not in str(got), tool


def test_a_local_image_is_read_beneath_its_root_and_never_from_a_private_one(world, mode):
    w = world
    root, top, link = _shared_root(w)
    (top / "one" / "pic.png").write_bytes(b"PNG shared")
    read = w.hub._image_read(root)
    assert read(top.resolve() / "one" / "pic.png") == b"PNG shared"
    (w.two.private_repo / "secret.png").write_bytes(b"PNG secret")
    (top / "out.png").symlink_to(w.two.private_repo / "secret.png")
    for path in (top.resolve() / "out.png", w.two.private_repo / "secret.png", top.resolve() / ".." / "x.png"):
        with pytest.raises(OSError):
            read(path)
    st = os.stat(top)                               # as if the root were a private root's (a mount)
    w.hub._private_ids[(st.st_dev, st.st_ino)] = "member-a-id"
    with pytest.raises(PermissionError):
        read(top.resolve() / "one" / "pic.png")


def test_the_share_copy_is_rendered_from_the_text_the_descriptor_gave(world, mode, monkeypatch):
    from sheafmd.hub import core
    w = world
    root, top, _ = _shared_root(w)
    e = w.hub.entry(f"{root.name}/one/{NAME}")
    seen = {}
    monkeypatch.setattr(core, "render_file", lambda path, **kw: seen.update(kw) or "<html></html>")
    w.hub.share_copy(e)
    assert seen["src"] == e.read()


def test_the_blame_of_a_list_row_is_not_asked_of_a_private_file(world, monkeypatch):
    from types import SimpleNamespace

    from sheafmd.hub import the_list
    blamed = []
    monkeypatch.setattr(the_list, "pressers", lambda *a: blamed.append(a) or {"x": 1})
    s = SimpleNamespace(pressed=[(0, 0, 3, 0)], hash=the_list.md_hash("text"), rel="a.md")
    me = SimpleNamespace(root=lambda: SimpleNamespace(git=True), hub=SimpleNamespace(blamed={}),
                         _file=lambda root, rel: Path("/x/a.md"))
    for private, want in ((None, {"x": 1}), ("member-a-id", {})):
        me._read = lambda root, rel, p=private: ("text", (), p)
        assert the_list.TheList._pressers(me, me.root(), s) == want


def test_a_write_that_moves_the_file_writes_only_the_file_it_opened(world, mode, monkeypatch):
    """A door update that makes a sheaf owner-only moves its file to its home first. A link swapped in for the moved
    file before the write must not carry the text into another member's private root: the file at its home is opened
    again beneath the root and written only if it is the one opened first."""
    from sheafmd import beneath
    w = world
    secret = w.two.private_repo / "acme/other/post.md"
    secret.parent.mkdir(parents=True)
    secret.write_text("# A's other private note\n", encoding="utf-8")
    shared = PROJECT_WIDE.replace("owner: a", "owner: b")
    (w.two.list_repo / NAME).write_text(shared, encoding="utf-8")
    owner_only = shared.replace("sources: [issue:acme/record#1]", "sources: [library:doc-1]")
    real, calls = beneath.open_beneath, []

    def swapping(top, rel, *a, **k):
        calls.append(rel)
        if "private/" in rel and not any("private/" in c for c in calls[:-1]):   # the first open of the file at its home
            home = Path(top) / rel
            os.unlink(home)
            os.symlink(secret, home)            # a folder writer of the list root swaps it for a link
        return real(top, rel, *a, **k)
    monkeypatch.setattr(beneath, "open_beneath", swapping)
    is_error, got = call(w.door, "update", token=w.tokens["tok-b"], doc=w.address, text=owner_only,
                         expected_hash=md_hash(shared))
    assert any("private/" in c for c in calls), calls
    assert is_error, got
    assert secret.read_text(encoding="utf-8") == "# A's other private note\n"


def test_a_private_root_made_new_at_its_path_is_private_still_to_a_listing_and_a_read(world, mode):
    """A private root's folder replaced at its path while the hub runs (a fresh clone, a restore) has a new identity: it is
    private all the same, so a token bound to nobody is shown neither its name nor its thread counts, and reads nothing."""
    import shutil
    w = world
    w.put(PRIVATE)
    w.put(PROJECT_WIDE)                                  # the private root also holds a sheaf that says visibility: project
    comment(w.two.private_repo / NAME, quote="Secret words.")
    pname = w.hub.roots.lookup(w.two.private_repo / NAME).name
    p = w.two.private_repo
    shutil.move(str(p), str(p) + ".old")
    shutil.copytree(str(p) + ".old", str(p), symlinks=True)
    is_error, got = call(w.door, "documents", token=w.tokens["loose"], open_only=False, root=pname)
    assert "post.md" not in str(got) and "Secret words" not in str(got), got
    for tool in ("read", "threads"):
        is_error, got = call(w.door, tool, token=w.tokens["loose"], doc=f"{pname}/{NAME}")
        assert "Secret words" not in str(got), (tool, got)


def test_the_kernel_open_judges_the_folders_between_the_root_and_the_file_too(tmp_path, mode):
    from sheafmd import beneath
    top = tmp_path / "top"
    (top / "a/b").mkdir(parents=True)
    (top / "a/b/f.md").write_text("hi", encoding="utf-8")
    here = os.stat(top / "a/b")
    with beneath.open_beneath(top, "a/b/f.md") as op:
        assert (here.st_dev, here.st_ino) in op.idents(), mode
        up = os.stat(top / "a")
        assert (up.st_dev, up.st_ino) in op.idents(), mode


# ── rule 2 on the root's own folder: a create is made, and judged, on the folder as opened ───────────────────────

def _created_root(w: World):
    """A registered root that is no private root's, with `acme/blog` and a file in it: (root, its folder)."""
    top = w.two.base / "shared"
    (top / "acme/blog").mkdir(parents=True)
    (top / "note.md").write_text("# note\n", encoding="utf-8")
    root = w.hub.roots.for_document(top / "note.md")
    assert root.path == top.resolve()
    return root, top


def _planted(w: World, name: str) -> bool:
    return (w.two.private_repo / "acme/blog" / name).exists()


def test_the_folder_of_a_root_swapped_for_the_private_root_before_a_create_opens_it_is_refused_whatever_the_name(world, mode, monkeypatch):
    """The folder of a shared root is exchanged for a link to the private repo between the checks by path and the open
    (G1): nothing is made there, and the answer for a name the private root holds is the answer for a free one."""
    from sheafmd import mcp
    w = world
    w.put(PRIVATE)
    root, top = _created_root(w)
    real, swapped, answers = mcp.check_create, [], {}

    def swapping(t, rel, judge=None):
        if not swapped:
            swapped.append(1)
            os.rename(top, top.with_name("shared.real"))
            top.symlink_to(w.two.private_repo)
        return real(t, rel, judge)
    monkeypatch.setattr(mcp, "check_create", swapping)
    for name in ("post.md", "free.md"):
        swapped.clear()
        if top.is_symlink():
            top.unlink()
            os.rename(top.with_name("shared.real"), top)
        answers[name] = call(w.door, "create", token=w.tokens["loose"], doc=f"{root.name}/acme/blog/{name}", text="# x\n")
        assert not _planted(w, "free.md")
    said = {n: (e, text.replace(n, "NAME")) for n, (e, text) in answers.items()}
    assert said["post.md"][0] and said["post.md"] == said["free.md"] and "not inside a root" in said["free.md"][1]
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PRIVATE


def test_a_root_folder_opened_as_a_private_one_is_refused_by_every_folder_open_that_writes(world, mode, tmp_path):
    """`create_file`, `check_create`, `make_folders` and the tidying all open the root's folder through the judge, and a
    root that is itself a private root has none."""
    from sheafmd import beneath, source
    from sheafmd.hub import place
    w = world
    root, top = _created_root(w)
    judge = place.judge_for(w.hub, root)
    assert judge is not None and place.judge_for(w.hub, w.hub.roots.get(w.root.name)) is not None
    link = w.two.base / "linked"
    link.symlink_to(w.two.private_repo)
    for act in (lambda: source.create_file(link, "acme/blog/n.md", "x", judge),
                lambda: source.check_create(link, "acme/blog/n.md", judge),
                lambda: place.make_folders(link, "acme/blog/new/n.md", judge)):
        with pytest.raises(beneath.Private):
            act()
    (w.two.private_repo / "acme/blog/private/a").mkdir(parents=True)
    place._tidy(link, "acme/blog/private/a/n.md", judge)            # tidies nothing: refused, and says nothing
    assert (w.two.private_repo / "acme/blog/private/a").is_dir()
    place._tidy(link, "acme/blog/private/a/n.md")                    # control: without the judge it removes it
    assert not (w.two.private_repo / "acme/blog/private/a").exists()
    assert not (w.two.private_repo / "acme/blog/n.md").exists() and not (w.two.private_repo / "acme/blog/new").exists()
    source.create_file(top, "acme/blog/n.md", "x", judge)          # the same calls on the root itself go through
    assert (top / "acme/blog/n.md").read_text(encoding="utf-8") == "x"


def test_a_root_folder_exchanged_for_a_link_to_the_private_root_again_and_again_never_gets_a_file(world, mode):
    """The real race: a thread exchanges (RENAME_EXCHANGE) the folder of a shared root and a link to the private repo
    while SHEAF_RACE_CREATES (default 300) door creates run. Not one file in the private root."""
    import ctypes
    import threading
    w = world
    w.put(PRIVATE)
    root, top = _created_root(w)
    alt = top.with_name("shared.link")
    alt.symlink_to(w.two.private_repo)
    libc, stop, hits, made = ctypes.CDLL(None, use_errno=True), threading.Event(), 0, 0
    n_tries = int(os.environ.get("SHEAF_RACE_CREATES", "300"))

    def flip():
        while not stop.is_set():
            libc.renameat2(-100, str(top).encode(), -100, str(alt).encode(), 2)        # RENAME_EXCHANGE
    t = threading.Thread(target=flip)
    t.start()
    try:
        for i in range(n_tries):
            is_error, _ = call(w.door, "create", token=w.tokens["loose"], doc=f"{root.name}/acme/blog/race{i}.md", text="# x\n")
            hits += _planted(w, f"race{i}.md")
            made += not is_error
    finally:
        stop.set()
        t.join()
    assert hits == 0 and made > 0


# ── projects.toml and the locks are opened beneath their folder too (rule 2) ─────────────────────────────────────

SHARED_SHEAF = """---
issue: acme/record#2
sources: [issue:acme/record#2]
---
# shared

Shared words.
"""


def _b_status(w: World) -> int:
    return w.front.get(f"/_/doc?doc={w.root.name}/acme/blog/shared.md", member=B).status


def test_a_projects_toml_that_is_a_link_to_a_private_root_gives_no_oracle_and_no_grants(two, mode):
    w = World(two, [])
    (w.two.list_repo / "acme/blog/shared.md").write_text(SHARED_SHEAF, encoding="utf-8")
    toml = w.two.list_repo / "projects.toml"
    toml.unlink()
    toml.symlink_to(w.two.private_repo / NAME)          # out of the shared root, to a file of A's private root
    absent = _b_status(w)
    w.put(PRIVATE)
    present = _b_status(w)
    assert absent == present                            # B learns nothing of whether A's file is there
    (w.two.private_repo / NAME).write_text('[projects."acme/blog"]\nmembers = ["b"]\nstatus = "live"\n', encoding="utf-8")
    assert _b_status(w) == absent                       # and a private file shaped as a projects.toml grants nothing


def test_a_projects_toml_is_read_beneath_its_root_in_both_modes(tmp_path, mode):
    from sheafmd.hub import projects
    root, out = tmp_path / "root", tmp_path / "out"
    root.mkdir(), out.mkdir()
    good = '[projects."acme/blog"]\nmembers = ["a"]\nstatus = "live"\n'
    assert projects.read(root) is None                                      # missing: as before
    (root / "real.toml").write_text(good, encoding="utf-8")
    (root / "projects.toml").symlink_to("real.toml")
    assert set(projects.read(root)) == {"acme/blog"}                        # a link inside the root is followed
    (root / "projects.toml").unlink()
    (out / "x.toml").write_text(good, encoding="utf-8")
    (root / "projects.toml").symlink_to(out / "x.toml")
    with pytest.raises(projects.Invalid):                                   # a link that leaves the root: refused, not absent
        projects.read(root)
    (root / "projects.toml").unlink()
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(good, encoding="utf-8")
    (root / "projects.toml").symlink_to(".git/config")
    with pytest.raises(projects.Invalid):                                   # a link into the hub's own folders: refused
        projects.read(root)
    (root / "projects.toml").unlink()
    os.link(root / "real.toml", root / "projects.toml")
    with pytest.raises(projects.Invalid):                                   # a file with two names: refused
        projects.read(root)


def test_a_projects_toml_the_descriptors_say_is_private_is_refused(tmp_path, mode):
    from types import SimpleNamespace
    from sheafmd.hub import projects
    st = tmp_path.stat()
    hub = SimpleNamespace(_private_ids={(st.st_dev, st.st_ino): "a"}, _private_paths={})
    (tmp_path / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a"]\nstatus = "live"\n', encoding="utf-8")
    assert set(projects.read(tmp_path)) == {"acme/blog"}
    with pytest.raises(projects.Invalid):
        projects.read(tmp_path, hub)


def test_a_legacy_lock_that_is_a_link_creates_nothing_where_it_points(tmp_path, monkeypatch):
    import tempfile
    from sheafmd import source
    fake = tmp_path / "faketmp"
    locks = fake / "render-doc" / "locks"
    locks.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(fake))
    doc = tmp_path / "d.md"
    doc.write_text("# d\n", encoding="utf-8")
    victim = tmp_path / "elsewhere" / "planted"
    victim.parent.mkdir()
    (locks / f"{source.lock_key(doc)}.lock").symlink_to(victim)
    source.update_file(doc, lambda t: t + "x\n")                    # the update itself still goes through
    assert doc.read_text(encoding="utf-8") == "# d\nx\n"
    assert not victim.exists()


def _legacy_world(tmp_path, monkeypatch):
    import tempfile
    from sheafmd import source
    fake = tmp_path / "faketmp"
    (fake / "render-doc").mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(fake))
    doc = tmp_path / "d.md"
    doc.write_text("# d\n", encoding="utf-8")
    return fake, doc, source


def test_a_legacy_lock_folder_that_is_a_link_creates_nothing_where_it_points(tmp_path, monkeypatch):
    fake, doc, source = _legacy_world(tmp_path, monkeypatch)
    target = tmp_path / "private" / "acme"
    target.mkdir(parents=True)
    os.chmod(target, 0o755)                                         # a folder of ours: only the link itself is refused
    os.chmod(fake / "render-doc", 0o755)
    (fake / "render-doc" / "locks").symlink_to(target)              # the folder is the link, not the lock
    source.update_file(doc, lambda t: t + "x\n")
    assert doc.read_text(encoding="utf-8") == "# d\nx\n" and list(target.iterdir()) == []


def test_a_legacy_lock_folder_others_can_write_is_not_used(tmp_path, monkeypatch):
    fake, doc, source = _legacy_world(tmp_path, monkeypatch)
    locks = fake / "render-doc" / "locks"
    locks.mkdir()
    os.chmod(locks, 0o777)                                          # another user could swap what is in it
    source.update_file(doc, lambda t: t + "x\n")
    assert list(locks.iterdir()) == []


def test_a_legacy_lock_folder_that_is_ours_is_still_taken(tmp_path, monkeypatch):
    fake, doc, source = _legacy_world(tmp_path, monkeypatch)
    locks = fake / "render-doc" / "locks"
    locks.mkdir()
    for d in (locks, locks.parent):
        os.chmod(d, 0o755)
    source.update_file(doc, lambda t: t + "x\n")
    assert [p.name for p in locks.iterdir()] == [source.lock_key(doc) + ".lock"]


def test_a_private_roots_own_projects_toml_is_read_for_its_member(tmp_path, mode):
    from types import SimpleNamespace
    from sheafmd.hub import projects
    st = tmp_path.stat()
    hub = SimpleNamespace(_private_ids={(st.st_dev, st.st_ino): "a"}, _private_paths={str(tmp_path): "a"})
    (tmp_path / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a"]\nstatus = "live"\n', encoding="utf-8")
    assert set(projects.read(tmp_path, hub)) == {"acme/blog"}
