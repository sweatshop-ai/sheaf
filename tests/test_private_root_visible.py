"""A file of a private root is visible only to that root's member, on every route (SPEC 9.11): whatever the issue's
assignees, `projects.toml` or the front matter say, another member and a token bound to nobody get the 404 of a missing
document, and a file that names a member as its owner in the list's repo is nobody's. Each refusal has the owner's own
call as its positive control, on the same route."""
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
    assert listed(w, A) and not listed(w, B)
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
    assert [d["doc"][-len(NAME):] for n, d in mine.drain() if n == "status"] == [NAME]       # the owner's stream hears it
    assert [d for n, d in theirs.drain() if n == "status"] == []


def test_unbound_token_by_the_private_roots_own_address(world):
    w = world
    w.put(PROJECT_WIDE)
    direct = f"{w.hub.roots.get(w.hub.roots.lookup(w.two.private_repo / NAME).name).name}/{NAME}"
    assert direct != w.address
    for doc in (direct, str(w.two.private_repo / NAME)):
        for tool, args in (("read", {}), ("threads", {}),
                           ("update", {"text": PROJECT_WIDE + "x", "expected_hash": md_hash(PROJECT_WIDE)})):
            assert call(w.door, tool, token=w.tokens["loose"], doc=doc, **args)[0], (doc, tool)
    is_error, got = call(w.door, "documents", token=w.tokens["loose"], open_only=False)
    assert not is_error and NAME not in str(got)
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PROJECT_WIDE
    assert not call(w.door, "read", token=w.tokens["tok-a"], doc=direct)[0]               # the owner reads it there


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
    for token, seen in (("tok-a", True), ("tok-b", False), ("loose", False)):
        is_error, got = call(w.door, "documents", token=w.tokens[token], open_only=False)
        assert not is_error and (NAME in str(got)) is seen, (token, got)


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


def test_unbound_token_by_a_root_around_the_private_root(world):
    w = world
    w.put(PROJECT_WIDE)
    (w.two.base / "note.md").write_text("# note\n", encoding="utf-8")
    outer = w.hub.roots.for_document(w.two.base / "note.md")          # a folder above both repos, as a render registers it
    assert outer.id not in w.hub.private_roots
    doc = f"{outer.name}/private/{NAME}"
    for tool, args in (("read", {}), ("threads", {}),
                       ("update", {"text": PROJECT_WIDE + "x", "expected_hash": md_hash(PROJECT_WIDE)})):
        assert call(w.door, tool, token=w.tokens["loose"], doc=doc, **args)[0], tool
    is_error, got = call(w.door, "documents", token=w.tokens["loose"], open_only=False, root=outer.name)
    assert NAME not in str(got)
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PROJECT_WIDE
    assert not call(w.door, "read", token=w.tokens["tok-a"], doc=w.address)[0]         # the owner reads it by the list's name


def test_a_deletion_is_told_to_nobody_else_whoever_read_the_file_first(world, monkeypatch):
    w = world
    w.put(PRIVATE)
    w.hub.entry(w.address)                                # the file read by the hub alone, never through a member's check
    w.hub.judged(w.address)
    (w.two.private_repo / NAME).unlink()
    b = w.hub.proxy.members[B]
    assert not w.hub.visible(b, w.address, never_read=False)


def _enclosing(w: World):
    (w.two.base / "note.md").write_text("# note\n", encoding="utf-8")
    return w.hub.roots.for_document(w.two.base / "note.md")


def _create_docs(w: World) -> dict:
    """The ways a door `create` can name a new page inside the private root: its own registered name, a root around it."""
    own = w.hub.roots.get(w.hub.roots.lookup(w.two.private_repo / NAME).name).name
    return {"own": f"{own}/acme/blog/new.md", "own-taken": f"{own}/{NAME}",
            "own-nofolder": f"{own}/nowhere/at/all/new.md", "outer": f"{_enclosing(w).name}/private/acme/blog/new.md",
            "outer-taken": f"{_enclosing(w).name}/private/{NAME}",
            "outer-nofolder": f"{_enclosing(w).name}/private/nowhere/at/all/new.md"}


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
    call(w.door, "create", token=w.tokens["loose"], doc=_create_docs(w)["outer"], text="# new\n")
    assert w.hub.commits.settle()
    assert git(w.two.private_repo, "rev-list", "--count", "HEAD") == before
    assert not (w.two.private_repo / "acme/blog/new.md").exists()


def test_a_private_root_forgotten_while_a_root_around_it_stays_is_still_private(world):
    w = world
    w.put(PROJECT_WIDE)
    outer = _enclosing(w)
    doc = f"{outer.name}/private/{NAME}"
    assert call(w.door, "read", token=w.tokens["loose"], doc=doc)[0]
    own = w.hub.roots.lookup(w.two.private_repo / NAME).name
    w.hub.forget_root(own)
    assert own not in {r.name for r in w.hub.roots.all()} and w.hub._private_paths
    for tool, args in (("read", {}), ("threads", {}),
                       ("update", {"text": PROJECT_WIDE + "x", "expected_hash": md_hash(PROJECT_WIDE)})):
        assert call(w.door, tool, token=w.tokens["loose"], doc=doc, **args)[0], tool
    is_error, got = call(w.door, "documents", token=w.tokens["loose"], open_only=False, root=outer.name)
    assert NAME not in str(got)
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == PROJECT_WIDE


@pytest.mark.parametrize("forget", [False, True])
@pytest.mark.parametrize("tool", ["reply", "resolve", "threads"])
def test_door_comment_verbs_by_a_loose_token_reach_nothing_of_a_private_root(world, tool, forget):
    w = world
    w.put(PROJECT_WIDE)
    comment(w.two.private_repo / NAME, quote="Secret words.")
    own = w.hub.roots.lookup(w.two.private_repo / NAME).name
    docs = [f"{own}/{NAME}", f"{_enclosing(w).name}/private/{NAME}"]
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
    outer = _enclosing(w).name
    if state == "refused":
        assert not w.hub.private_roots and w.hub._private_paths
    if state == "forgotten":
        w.hub.forget_root(own)
    docs = {"registered": [f"{own}/{NAME}", w.address, f"{outer}/private/{NAME}"],
            "refused": [f"{own}/{NAME}", f"{outer}/private/{NAME}"],
            "forgotten": [f"{outer}/private/{NAME}"],
            "enclosing": [f"{outer}/private/{NAME}"],
            "list": [w.address]}[state]
    return w, docs


def _args(tool, doc):
    return {"read": {}, "threads": {}, "reply": {"id": "c1", "text": "Done."}, "resolve": {"id": "c1"},
            "update": {"text": PROJECT_WIDE + "x", "expected_hash": md_hash(PROJECT_WIDE)},
            "create": {"text": "# new\n"}}[tool]


@pytest.mark.parametrize("state", ["registered", "refused", "forgotten", "enclosing", "list"])
@pytest.mark.parametrize("kind", ["tok-b", "loose"])
@pytest.mark.parametrize("tool", ["read", "threads", "reply", "resolve", "update", "create", "documents"])
def test_invariant_table_a_caller_that_is_not_the_member_gets_nothing_inside_the_set(two, monkeypatch, state, kind, tool):
    w, docs = _state_world(two, monkeypatch, state)
    before = (two.private_repo / NAME).read_text(encoding="utf-8")
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
        if doc == f"{_enclosing(w).name}/private/{NAME}":
            continue                                   # a root around the private one is not the member's (9.11)
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
