"""Rule A (SPEC 9.11) on the door token of a second James that works shared projects (SPEC 9.12): a token listed in
`[list] james_tokens` but not the own one, bound to a member whose `roots` name the list root only and who has no
`private_root`, reaches nothing of a private root. It gets the 404 of a missing document on every door tool, cannot
create into the private root, and its listings leave the private file out. A file that is open to the project
(an `issue:` source) is refused just the same: Rule A holds whatever the file's front matter says. Each refusal has the owner's own token as its positive control, on the same tool."""
import pytest
from helpers import browser_on, call, door, rpc
from two_roots import TwoRoots, git, two_roots

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

    def __init__(self, two: TwoRoots):
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


@pytest.fixture
def world(two) -> World:
    return World(two)


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
    if by == "list name":                                                                   # positive control: the owner's token
        is_error, got = w.call(tool, OWN, doc=doc, **args)
        assert not (is_error and "no document" in got.lower()), (tool, got)
        if tool == "read":
            assert not is_error and "Secret words." in str(got)


def test_a_session_header_on_the_shared_token_opens_no_private_sheaf(world):
    w = world
    w.put(OWNED_BY_ALICE)
    for doc in (w.address, str(w.two.private_repo / NAME)):
        res = door(w.door, rpc("tools/call", {"name": "read", "arguments": {"doc": doc}}), token=w.tokens[SHARED],
                   headers={"X-James-Session": SID})
        assert res.status == 200 and res.json()["result"]["isError"], (doc, res.text)
        assert "Secret words." not in res.text


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


def test_james_shared_token_lists_no_private_file(world):
    w = world
    w.put(OWNED_BY_ALICE)
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
