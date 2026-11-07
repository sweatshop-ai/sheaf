"""Rule E (SPEC 9.11): the private root has no address of its own. A sheaf of it is named `<list root>/<client>/
<project>/<name>.md` and by nothing else: not by the root's own name on any route, not by the root's real path at the
door, not by `sheaf open`. Each refusal has the owner's call as its positive control, on the same route."""
import pytest
from helpers import call
from test_private_root_visible import NAME, PRIVATE, World
from two_roots import A, B, two_roots

from sheafmd.hub import roots as roots_mod
from sheafmd.render import RenderError


@pytest.fixture
def world(tmp_path):
    return World(two_roots(tmp_path), ["login-a"])


def private_root(w):
    return next(r for r in w.hub.roots.all() if r.id in w.hub.private_roots)


def test_private_root_has_no_address(world):
    w = world
    w.put(PRIVATE)
    p = private_root(w).name
    direct = f"{p}/{NAME}"
    assert direct != w.address and w.hub.roots.get(p) is None
    for member in (A, B):
        for path in (f"/{direct}", f"/_/doc?doc={direct}", f"/_/mount?doc={direct}", f"/{p}", f"/{p}/",
                     f"/_/list?list={p}"):
            assert w.front.get(path, member=member).status == 404, (member, path)
    with pytest.raises(roots_mod.NotFound):
        w.hub.roots.resolve(direct)
    with pytest.raises(roots_mod.NotFound):
        w.hub.roots.locate(direct)
    # the key's index and the door's listing name no such root, and show no path of it
    for member in (None, A):
        got = (w.door.get("/_/index.json", key=True) if member is None else w.front.get("/_/index.json", member=member))
        assert got.status == 200 and p not in [r["name"] for r in got.json()["roots"]]
        assert str(w.two.private_repo) not in got.text
    is_error, said = call(w.door, "read", doc=direct)
    _, none = call(w.door, "read", doc="nowhere/acme/blog/post.md")
    assert is_error and said.replace(direct, "X") == none.replace("nowhere/acme/blog/post.md", "X")
    url = f"http://127.0.0.1:{w.hub.port}/{direct}"                         # nor does its page's URL name the sheaf
    assert call(w.door, "read", token=w.tokens["tok-a"], doc=url)[0]
    assert not call(w.door, "read", token=w.tokens["tok-a"], doc=url.replace(direct, w.address))[0]
    is_error, said = call(w.door, "documents", root=p)
    assert is_error and said == call(w.door, "documents", root="nowhere")[1].replace("nowhere", p)
    assert str(w.two.private_repo) not in str(call(w.door, "documents", open_only=False))
    # positive control: its member opens the same sheaf by its list name, on the same routes
    assert w.front.get(f"/{w.address}", member=A).status == 200
    assert w.front.get(f"/_/doc?doc={w.address}", member=A).status == 200
    assert "Secret words." in w.front.get(f"/_/mount?doc={w.address}", member=A).json()["html"]


def test_absolute_path_makes_no_second_address(world):
    w = world
    w.put(PRIVATE)
    path = str(w.two.private_repo / NAME)
    tok_a, tok_b, loose = (w.tokens[n] for n in ("tok-a", "tok-b", "loose"))
    for tool, args in (("read", {}), ("threads", {}),
                       ("update", {"text": PRIVATE + "x", "expected_hash": call(w.door, "read", doc=w.address)[1]["hash"]})):
        for who in (tok_b, loose):                  # another member, and a token bound to nobody: a path in no root
            assert call(w.door, tool, token=who, doc=path, **args)[0], (tool, who)
        is_error, got = call(w.door, tool, token=tok_a, doc=path, **args)       # positive control: its member, same call
        assert not is_error and (tool == "threads" or got["doc"] == w.address), (tool, got)
        assert str(w.two.private_repo) not in str(got)
    is_error, got = call(w.door, "read", doc=path)                       # the key: the list name, never the root's
    assert not is_error and got["doc"] == w.address and str(w.two.private_repo) not in str(got)
    # a create by that path, even of a name nobody holds, makes no file in either repo and takes no name
    new = str(w.two.private_repo / "acme/blog/new.md")
    for who in (tok_b, loose, tok_a, None):
        is_error, said = call(w.door, "create", token=who, doc=new, text="---\nowner: a\nsources: [library:d]\n---\n# n\n")
        assert is_error, (who, said)
        assert ("a private root" in said) is (who in (tok_a, None)), (who, said)     # its member: the private create's refusal
    assert not (w.two.private_repo / "acme/blog/new.md").exists() and not (w.two.list_repo / "acme/blog/new.md").exists()
    assert not [a for a in w.hub.entries if a.startswith(private_root(w).name + "/")]
    assert (w.two.private_repo / NAME).read_text(encoding="utf-8").endswith("Secret words.\nx")     # the member's own update
    assert not (w.two.list_repo / NAME).exists()


def test_render_open_private_path(world):
    w = world
    w.put(PRIVATE)
    with pytest.raises(RenderError):
        w.hub.render(w.two.private_repo / NAME, {}, None)
    with pytest.raises(roots_mod.NotFound):
        w.hub.roots.address(w.two.private_repo / NAME)
    assert w.hub.roots.address(w.two.private_repo / NAME, alias=lambda root, rel: f"x/{rel}") == f"x/{NAME}"
    assert not [a for a in w.hub.entries if a.startswith(private_root(w).name + "/")]
    assert w.hub.roots.address(w.two.list_repo / "acme/blog/other.md") == "list/acme/blog/other.md"     # positive control


def test_nested_root_check_still_sees_private_root(world):
    w = world
    w.put(PRIVATE)
    mine = private_root(w)
    assert w.hub.roots.lookup(w.two.private_repo / NAME) == mine           # the nested-root check and the image rule
    assert w.hub.roots.for_document(w.two.private_repo / NAME) == mine
    assert mine in w.hub.roots.all() and mine not in w.hub.roots.listed()
    assert w.hub.roots.get(mine.name) is None


def test_a_second_spelling_of_the_private_folder_is_hidden_too(world):
    w = world
    mine = private_root(w)
    sub = w.two.private_repo / "acme"
    other = roots_mod.Root("alias", w.two.private_repo / "acme" / "..", True, "id-alias")     # same folder, spelled again
    assert sub.is_dir() or sub.mkdir()
    assert not w.hub.roots.hidden(other)             # not until it is registered: judged then, never at a request
    w.hub.roots.registered(other)
    assert w.hub.roots.hidden(mine) and w.hub.roots.hidden(other)
    assert not w.hub.roots.hidden(w.hub.the_list.root())             # positive control
    w.put(PRIVATE)
    (w.two.private_repo / "readme.md").write_text("# r\n", encoding="utf-8")
    is_error, said = call(w.door, "read", doc=str(w.two.private_repo / "readme.md"))   # the key, no list name for it
    assert is_error and "failed" not in said


def test_a_dotdot_or_link_path_into_the_private_root_is_a_path_in_no_root(world):
    w = world
    w.put(PRIVATE)
    link = w.two.base / "elsewhere"
    link.symlink_to(w.two.private_repo)
    spelled = f"{w.two.base}/nowhere/../private/acme/blog/new.md"
    for doc in (spelled, str(link / "acme/blog/new.md")):
        nothing = str(w.two.base / "nowhere/../none/acme/blog/new.md")
        for who in (w.tokens["loose"], w.tokens["tok-b"]):
            got = call(w.door, "create", token=who, doc=doc, text="# n\n")[1]
            _, base = call(w.door, "create", token=who, doc=nothing, text="# n\n")
            assert got.replace(doc, "X") == base.replace(nothing, "X"), (doc, who, got)
