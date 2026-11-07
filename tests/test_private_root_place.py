"""Where the file of a sheaf lives when a member has a private root (SPEC 9.11): `home_in` names the root as well as
the path, a name is looked for in the list's root and in each private root, and the placer answers a root and a path
(the door's create into a private root is in test_private_root_create.py)."""
import pytest
from helpers import hub_rows
from two_roots import A, TwoRoots, two_roots

from sheafmd.hub import place, roots as roots_mod

NAME = "acme/blog/post.md"
OPEN = "# post\n"
OWNED_BY_A = "---\nowner: a\nsources: [library:doc-1]\n---\n# post\n"      # a private source makes it its owner's alone
OWNED_BY_B = OWNED_BY_A.replace("owner: a", "owner: b")


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def hub_of(two: TwoRoots, **over):
    hub = two.hub(two.config(**over))
    hub.the_list.root()
    return hub


def list_root(hub):
    return hub.the_list.root()


def private_root(hub):
    return next(r for r in hub.roots.all() if r.id in hub.private_roots)


def test_home_in_owner_only_sheaf_of_a_member_with_a_private_root_is_in_that_root(two):
    hub = hub_of(two)
    assert place.home_in(hub, list_root(hub), NAME, OWNED_BY_A) == (private_root(hub), NAME)


def test_home_in_keeps_today_s_home_for_everything_else(two):
    hub = hub_of(two)
    root = list_root(hub)
    assert place.home_in(hub, root, NAME, OPEN) == (root, NAME)                                  # open to the project
    assert place.home_in(hub, root, NAME, OWNED_BY_B) == (root, "acme/blog/private/b/post.md")    # owner has none
    assert place.home_in(hub, root, NAME, OWNED_BY_A.replace("owner: a", "owner: nobody")) is None


def test_home_in_two_owners_keep_the_shared_home(two, monkeypatch):
    hub = hub_of(two, a={"github": "aye"}, b={"github": "bee"})
    root = list_root(hub)
    monkeypatch.setattr(hub, "assignees", lambda address, fm=None: ["aye", "bee"])
    assert place.home_in(hub, root, NAME, OWNED_BY_A) == (root, "acme/blog/private/a/post.md")
    monkeypatch.setattr(hub, "assignees", lambda address, fm=None: ["aye"])
    assert place.home_in(hub, root, NAME, OWNED_BY_A) == (private_root(hub), NAME)           # positive control


def test_home_in_a_hub_without_a_private_root_answers_the_list_root_only(two):
    table = two.table()
    del table["members"][A]["private_root"]
    from sheafmd.hub import proxy
    hub = two.hub(proxy.parse(table, "the test", two.list_table()))
    root = list_root(hub)
    assert hub.private_roots == {}
    assert place.home_in(hub, root, NAME, OWNED_BY_A) == (root, "acme/blog/private/a/post.md")


def test_holders_look_in_the_list_root_and_each_private_root(two):
    hub = hub_of(two)
    root, private = list_root(hub), private_root(hub)
    (two.list_repo / "acme/blog").mkdir(parents=True)
    (two.private_repo / "acme/blog").mkdir(parents=True)
    assert place.holders(hub, root, NAME) == [] and not place.taken(hub, root, NAME)
    (two.private_repo / NAME).write_text(OWNED_BY_A, encoding="utf-8")
    assert place.holders(hub, root, NAME) == [(private, NAME)] and place.taken(hub, root, NAME)
    assert place.where_is(hub, f"{root.name}/{NAME}") == (private, NAME)
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    assert place.holders(hub, root, NAME) == [(root, NAME), (private, NAME)]
    assert place.where_is(hub, f"{root.name}/{NAME}") is None                                   # held twice: no one file


def test_where_is_the_list_roots_file_and_none_for_a_name_held_by_nothing(two):
    hub = hub_of(two)
    root = list_root(hub)
    (two.list_repo / "acme/blog").mkdir(parents=True)
    assert place.where_is(hub, f"{root.name}/{NAME}") is None
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    assert place.where_is(hub, f"{root.name}/{NAME}") == (root, NAME)


def test_a_name_held_in_both_roots_is_refused_and_a_row_says_so(two):
    hub = hub_of(two)
    root = list_root(hub)
    for repo in (two.list_repo, two.private_repo):
        (repo / "acme/blog").mkdir(parents=True)
        (repo / NAME).write_text(OPEN, encoding="utf-8")
    with pytest.raises(roots_mod.NotFound):
        place.physical(hub, root, NAME)
    assert [r["doc"] for r in hub_rows("place-refused")] == [f"{root.name}/{NAME}"]


def test_placer_returns_root_and_rel(two):
    hub = hub_of(two)
    root, private = list_root(hub), private_root(hub)
    (two.list_repo / "acme/blog").mkdir(parents=True)
    (two.private_repo / "acme/blog").mkdir(parents=True)
    (two.list_repo / "acme/blog/open.md").write_text(OPEN, encoding="utf-8")
    (two.private_repo / NAME).write_text(OWNED_BY_A, encoding="utf-8")
    assert hub.roots.placer(root, "acme/blog/open.md") == (root, "acme/blog/open.md")
    assert hub.roots.placer(root, NAME) == (private, NAME)
    assert hub.roots.resolve(f"{root.name}/{NAME}") == (two.private_repo / NAME).resolve()


def test_resolve_refuses_a_link_that_leaves_the_private_root(two, tmp_path):
    hub = hub_of(two)
    root = list_root(hub)
    (two.private_repo / "acme/blog").mkdir(parents=True)
    outside = tmp_path / "elsewhere.md"
    outside.write_text(OPEN, encoding="utf-8")
    (two.private_repo / NAME).symlink_to(outside)                       # a link out of the private root
    (two.private_repo / "acme/blog/real.md").write_text(OPEN, encoding="utf-8")
    assert hub.roots.resolve(f"{root.name}/acme/blog/real.md")          # a regular file in it is found
    with pytest.raises(roots_mod.NotFound):
        hub.roots.resolve(f"{root.name}/{NAME}")                        # a link holds no name; nothing is served


def test_resolve_refuses_the_git_dir_and_state_of_the_returned_root(two, monkeypatch):
    hub = hub_of(two)
    root, private = list_root(hub), private_root(hub)
    (two.private_repo / ".sheaf").mkdir()
    (two.private_repo / ".sheaf/x.md").write_text(OPEN, encoding="utf-8")
    monkeypatch.setattr(hub.roots, "placer", lambda r, rel: (private, ".sheaf/x.md"))      # a placer's answer is judged
    with pytest.raises(roots_mod.NotFound):                                                 # against its own root
        hub.roots.resolve(f"{root.name}/acme/blog/x.md")
