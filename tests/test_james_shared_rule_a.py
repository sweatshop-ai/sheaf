"""Rule A (SPEC 9.11) on the door token of a second James that works shared projects (SPEC 9.12): a token listed in
`[list] james_tokens` but not the own one, bound to a member whose `roots` name the list root only and who has no
`private_root`, reaches nothing of a private root. It gets the 404 of a missing document on every door tool, cannot
create into the private root, and its listings leave the private file out. A file that is open to the project
(an `issue:` source) is refused just the same: Rule A holds whatever the file's front matter says. Each refusal has the owner's own token as its positive control, on the same tool."""
import pytest
from helpers import browser_on, call, comment, door, rpc
from two_roots import TwoRoots, git, two_roots

from sheafmd import mcp
from sheafmd.hub import place, proxy, the_list
from sheafmd.hub.state import Tokens
from sheafmd.source import md_hash

NAME = "acme/blog/post.md"
SID = "6f1c0e9a-2b3d-4c5e-8f70-1a2b3c4d5e6f"
OWNED_BY_ALICE = "---\nowner: alice\nsources: [library:doc-1]\n---\n# post\n\nSecret words.\n"
PROJECT_WIDE = OWNED_BY_ALICE.replace("sources: [library:doc-1]", "sources: [issue:acme/record#1]")    # open to the project
TEXTS = {"owner-only": OWNED_BY_ALICE, "project-wide": PROJECT_WIDE}
OPEN = "# post\n"
SHARED = "shared"       # the member a shared window acts for: a name, not an id a front user could carry
OWN = "own"             # the own James's door token, bound to alice


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


class World:
    """Alice has the private root and the own token; the shared token acts for `shared`, who has the list root only."""

    def __init__(self, two: TwoRoots, grants=True):
        self.two = two
        self.tokens = {n: Tokens().add(n, write=True) for n in (OWN, SHARED)}
        table = two.table(a={"name": "Alice", "short": "alice", "github": "login-alice", "tokens": [OWN]})
        table["members"] = {"alice-id": table["members"]["member-a-id"],
                            SHARED: {"name": "James shared", "short": SHARED, "roots": [str(two.list_repo)],
                                     "tokens": [SHARED]}}
        self.hub = two.hub(proxy.parse(table, "the test", two.list_table()))
        self.hub.the_list = the_list.TheList(self.hub, the_list.parse(
            {"root": str(two.list_repo), "repo": "acme/record", "project": 1, "token_file": str(two.base / "token"),
             "james_tokens": [OWN, SHARED], "own_james_token": OWN}, "the test"))
        self.hub.assignees = lambda address, fm: ["login-alice"]
        self.root = self.hub.the_list.root()
        for repo in (two.list_repo, two.private_repo):
            (repo / "acme/blog").mkdir(parents=True, exist_ok=True)
        if grants:      # without it the hub's grant check (SPEC 8.12) refuses the file too; Rule A alone decides when it is off
            (two.list_repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["alice", "shared"]\n'
                                                         'status = "live"\n', encoding="utf-8")
        self.door = browser_on(self.hub)
        self.address = f"{self.root.name}/{NAME}"

    def put(self, text, repo=None):
        (repo or self.two.private_repo).joinpath(NAME).write_text(text, encoding="utf-8")

    def call(self, tool, who, **args):
        return call(self.door, tool, token=self.tokens[who], **args)

    def commits(self, repo):
        return int(git(repo, "rev-list", "--count", "HEAD"))


@pytest.fixture(params=["granted", "ungranted"])
def world(two, request) -> World:
    """With a `projects.toml` that grants the shared member the project, and without one: the first is the deployed
    shape, the second is the one in which no grant check refuses the file and Rule A alone does."""
    return World(two, grants=request.param == "granted")


def test_the_shared_token_is_a_james_token_of_a_member_with_no_private_root(world):
    """The set-up is the one the design names, so the tests below say something about it."""
    cfg = world.hub.the_list.cfg
    assert cfg.james_tokens == (OWN, SHARED) and cfg.own_token == OWN
    shared = world.hub.proxy.member_of_token(SHARED)
    assert shared is not None and shared.id == SHARED and not shared.private_root
    assert world.hub.proxy.member_of_token(OWN).private_root


@pytest.mark.parametrize("tool", ["read", "threads", "update", "reply", "resolve"])
@pytest.mark.parametrize("by", ["list name", "root address", "absolute path"])
@pytest.mark.parametrize("kind", TEXTS)
def test_james_shared_token_404_on_private_sheaf(world, tmp_path, tool, by, kind):
    w, text = world, TEXTS[kind]
    w.put(text)
    root_name = w.hub.roots.lookup(w.two.private_repo / NAME).name
    doc, twin = {"list name": (w.address, w.address.replace("post.md", "none.md")),
                 "root address": (f"{root_name}/{NAME}", f"{root_name}/acme/blog/none.md"),
                 "absolute path": (str(w.two.private_repo / NAME), str(tmp_path / "nowhere" / NAME))}[by]
    args = {"read": {}, "threads": {}, "reply": {"id": "c1", "text": "Done."}, "resolve": {"id": "c1"},
            "update": {"text": text.replace("Secret", "Changed"), "expected_hash": md_hash(text)}}[tool]
    heads = (w.commits(w.two.list_repo), w.commits(w.two.private_repo))
    is_error, got = w.call(tool, SHARED, doc=doc, **args)
    _, missing = w.call(tool, SHARED, doc=twin, **args)
    assert is_error and got.replace(doc, "D") == missing.replace(twin, "D"), (tool, got)
    assert w.hub.commits.settle()
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == text                  # nothing was written
    assert (w.commits(w.two.list_repo), w.commits(w.two.private_repo)) == heads             # and nothing committed
    is_error, got = w.call(tool, OWN, doc=w.address, **args)                                # positive control: the owner
    assert not (is_error and "no document" in got.lower()), (tool, got)
    if tool == "read":
        assert not is_error and "Secret words." in str(got)


@pytest.mark.parametrize("tool", ["read", "threads", "update", "reply", "resolve"])
def test_a_session_header_on_the_shared_token_opens_no_private_sheaf(world, tool):
    w = world
    w.put(PROJECT_WIDE)
    comment(w.two.private_repo / NAME, quote="Secret words.")      # a real c1, so reply and resolve fail on the document and not on the id
    text = (w.two.private_repo / NAME).read_text(encoding="utf-8")
    args = {"read": {}, "threads": {}, "reply": {"id": "c1", "text": "Done."}, "resolve": {"id": "c1"},
            "update": {"text": text.replace("# post", "# changed", 1), "expected_hash": md_hash(text)}}[tool]    # leaves the commented words alone

    def with_header(name, arguments, who=SHARED):
        res = door(w.door, rpc("tools/call", {"name": name, "arguments": arguments}), token=w.tokens[who],
                   headers={"X-James-Session": SID})
        assert res.status == 200, res.text
        return res.json()["result"]["isError"], res.text

    heads = (w.commits(w.two.list_repo), w.commits(w.two.private_repo))
    for doc, twin in ((w.address, w.address.replace("post.md", "none.md")),
                      (str(w.two.private_repo / NAME), str(w.two.private_repo / "acme/blog/none.md"))):
        is_error, got = with_header(tool, {"doc": doc, **args})
        _, missing = with_header(tool, {"doc": twin, **args})
        assert is_error and "Secret words." not in got, (doc, got)
        assert got.replace(doc, "D") == missing.replace(twin, "D"), (doc, got)               # the answer of a missing document
    assert w.hub.commits.settle()
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == text
    assert (w.commits(w.two.list_repo), w.commits(w.two.private_repo)) == heads
    control = with_header(tool, {"doc": w.address, **args}, who=OWN)                         # positive control: the owner opens it with the same header
    assert not control[0], control[1]


def test_a_session_header_on_the_shared_token_creates_nothing_in_the_private_root(world):
    """Rule F with the header: a free name, so it is the home of the text and not a taken name that refuses."""
    w = world
    fresh = w.address.replace("post.md", "fresh.md")
    heads = (w.commits(w.two.list_repo), w.commits(w.two.private_repo))
    res = door(w.door, rpc("tools/call", {"name": "create", "arguments": {"doc": fresh, "text": OWNED_BY_ALICE}}),
               token=w.tokens[SHARED], headers={"X-James-Session": SID})
    assert res.json()["result"]["isError"] and "cannot be made" in res.text and place.PRIVATE_ROOT in res.text, res.text
    assert w.hub.commits.settle()
    assert not list(w.two.private_repo.rglob("fresh.md")) and not list(w.two.list_repo.rglob("fresh.md"))
    assert (w.commits(w.two.list_repo), w.commits(w.two.private_repo)) == heads
    assert not w.call("create", OWN, doc=fresh, text=OWNED_BY_ALICE)[0]                    # positive control: the owner makes it
    assert (w.two.private_repo / "acme/blog/fresh.md").is_file()


def test_james_shared_token_cannot_create_in_private_root(world):
    w = world
    heads = (w.commits(w.two.list_repo), w.commits(w.two.private_repo))
    is_error, got = w.call("create", SHARED, doc=w.address, text=OWNED_BY_ALICE)
    assert is_error and "cannot be made" in got and place.PRIVATE_ROOT in got, got
    by_path = w.call("create", SHARED, doc=str(w.two.private_repo / NAME), text=OWNED_BY_ALICE)
    assert by_path[0] and "Secret words." not in by_path[1]
    assert w.hub.commits.settle()
    assert not (w.two.private_repo / NAME).exists() and not list(w.two.list_repo.rglob("post.md"))
    assert (w.commits(w.two.list_repo), w.commits(w.two.private_repo)) == heads             # no commit anywhere
    assert not w.call("create", OWN, doc=w.address, text=OWNED_BY_ALICE)[0]                 # positive control
    assert (w.two.private_repo / NAME).is_file()


def test_james_shared_token_cannot_move_a_shared_sheaf_into_private_root(world):
    w = world
    assert not w.call("create", SHARED, doc=w.address, text=OPEN)[0]                        # an open sheaf of the list
    path = w.two.list_repo / NAME
    before = path.read_text(encoding="utf-8")
    heads = (w.commits(w.two.list_repo), w.commits(w.two.private_repo))
    is_error, got = w.call("update", SHARED, doc=w.address, text=OWNED_BY_ALICE, expected_hash=md_hash(before))
    assert is_error and "cannot be moved between roots" in got, got
    assert w.hub.commits.settle()
    assert path.read_text(encoding="utf-8") == before and not (w.two.private_repo / NAME).exists()
    assert (w.commits(w.two.list_repo), w.commits(w.two.private_repo)) == heads


@pytest.mark.parametrize("kind", TEXTS)
def test_james_shared_token_lists_no_private_file(world, kind):
    w = world
    w.put(TEXTS[kind])
    private_root = w.hub.roots.lookup(w.two.private_repo / NAME).name
    for args in ({"open_only": False}, {"root": w.root.name, "open_only": False}):
        is_error, got = w.call("documents", SHARED, **args)
        assert not is_error and NAME not in str(got), (args, got)
    # the private root is no root of this hub to it: the answer for a root that does not exist
    named = w.call("documents", SHARED, root=private_root, open_only=False)
    none = w.call("documents", SHARED, root="nosuchroot", open_only=False)
    assert named[0] and named[1].replace(private_root, "R") == none[1].replace("nosuchroot", "R"), (named, none)
    is_error, got = w.call("documents", OWN, open_only=False)                               # positive control
    assert not is_error and NAME in str(got), got
    (w.two.list_repo / "acme/blog/open.md").write_text(OPEN, encoding="utf-8")              # a shared file is listed
    is_error, got = w.call("documents", SHARED, open_only=False)
    assert not is_error and "acme/blog/open.md" in str(got) and NAME not in str(got)


@pytest.mark.parametrize("kind", TEXTS)
def test_the_listing_filter_alone_keeps_a_private_file_from_the_shared_member(world, monkeypatch, kind):
    """Rule D on its own: with the door's per-file judgment (Rule A among it) answering yes to everything, the shared
    member's listing still leaves out a private root's file, because that root is not listed to it."""
    w = world
    w.put(TEXTS[kind])
    monkeypatch.setattr(mcp.Door, "_sees", lambda self, *a, **kw: True)
    for args in ({"open_only": False}, {"root": w.root.name, "open_only": False}):
        is_error, got = w.call("documents", SHARED, **args)
        assert not is_error and NAME not in str(got), (args, got)
    is_error, got = w.call("documents", OWN, open_only=False)                               # positive control: the owner's root is listed
    assert not is_error and NAME in str(got), got


@pytest.fixture
def private_file(world):
    """A private file seen from the hub: its address under the list's name (a private root has no address of its own, so
    this is the one the hub's Rule A functions are asked about), its front matter, and the two members."""
    w = world
    w.put(PROJECT_WIDE)                                         # open to the project: only Rule A keeps it from the shared member
    fm = w.hub.judged(w.address)[0]
    return w, fm, w.hub.proxy.member_of_token(OWN), w.hub.proxy.member_of_token(SHARED)


def test_members_owning_alone_leaves_the_shared_member_out(private_file):
    """The site in `members_owning`: asked of the shared member and the owner together, only the owner owns it. The shared
    member owns the list root, so no other rule of this call takes it out."""
    w, _, alice, shared = private_file
    assert w.hub.owns(shared, w.hub.roots.get(w.address.split("/")[0]))
    assert [m.id for m in w.hub.members_owning([alice, shared], w.address)] == ["alice-id"]
    assert not w.hub.member_owns(shared, w.address)
    assert w.hub.member_owns(alice, w.address)                  # positive control: the owner owns it by the list's name


def test_visible_alone_hides_the_private_file_from_the_shared_member(private_file):
    """The site in `visible`, called on its own: the file is open to the project, so only Rule A and, in the granted
    variant, the grant check answer no (the next test shows which of them does)."""
    w, _, alice, shared = private_file
    assert not w.hub.visible(shared, w.address)
    assert not w.hub.visible(shared, w.address, never_read=False)
    assert w.hub.visible(alice, w.address)                      # positive control: the owner sees it


def test_may_open_alone_refuses_the_private_file_to_the_shared_member(private_file):
    """The site in `may_open`, called on its own with the file's own front matter, as the door and the handlers do."""
    w, fm, alice, shared = private_file
    assert not w.hub.may_open(shared, w.address, fm)
    assert w.hub.may_open(alice, w.address, fm)                 # positive control: the owner opens it


def test_rule_a_is_what_refuses_in_the_two_tests_above(private_file, monkeypatch):
    """The isolation control: with Rule A's lookup answering "nobody's", the shared member is refused by nothing else
    when no `projects.toml` grants the project (the ungranted variant, in which the two tests above isolate their site),
    and by the grant check alone when one does. So if another rule ever starts refusing the ungranted case, this fails."""
    w, fm, alice, shared = private_file
    has_grants = (w.two.list_repo / "projects.toml").exists()   # there, the grant check refuses a file whose real path lies outside the list root
    monkeypatch.setattr(place, "private_member", lambda *a, **kw: None)
    assert w.hub.granted(shared, w.address) is not has_grants
    assert w.hub.visible(shared, w.address) is not has_grants
    assert w.hub.may_open(shared, w.address, fm) is not has_grants
    assert [m.id for m in w.hub.members_owning([alice, shared], w.address)] == ["alice-id", "shared"]
