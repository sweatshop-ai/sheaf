"""The Write log where a rectoverso is named otherwise than by its path: a file of a private root, a file of
`<project>/private/<short>/`, and the box's James at the door. The two-root fixture of the private-root tests."""
import pytest
from helpers import door, rpc
from test_james_shared_rule_a import NAME, OPEN, OWN, SHARED, SID, World, two  # noqa: F401  (two: a fixture)

from sheafmd.source import md_hash


@pytest.fixture
def world(two):  # noqa: F811
    return World(two)


def pulled(world, path, author="Ada", ok=True):
    """What a pull of the file at `path` tells the hub: it is about to change it, and then it is done."""
    files = [(path, author)]
    world.hub.pulling(path.parent, files)
    world.hub.pulled(path.parent, files, ok)


def test_a_file_of_a_private_root_is_named_by_the_address_its_page_opens_under(world):
    world.put(OPEN)
    path = world.two.private_repo / NAME
    assert world.hub._page_of(path) == world.address != str(path)
    world.hub.entry(world.address)                  # the page is open
    world.hub.pulling(path.parent, [(path, "Ada")])
    assert world.hub.writes.is_pull(world.address, "any")      # a change the page sees while the pull is under way is its
    world.hub.pulled(path.parent, [(path, "Ada")], True)
    assert [(l.writer, l.place, l.via) for l in world.hub.writes.lines(world.address)] == [("git · Ada", "tiroir", "pull")]


def test_a_file_under_private_short_is_named_by_its_project_name(world):
    path = world.two.list_repo / "acme/blog/private/alice" / NAME.rsplit("/", 1)[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(OPEN, encoding="utf-8")
    assert world.hub._page_of(path) == world.address
    pulled(world, path)
    assert [l.via for l in world.hub.writes.lines(world.address)] == ["pull"]


def test_a_refused_pull_leaves_no_line_and_no_window_behind(world):
    world.put(OPEN)
    path = world.two.private_repo / NAME
    world.hub.entry(world.address)
    pulled(world, path, ok=False)
    assert world.hub.writes.lines(world.address) == []
    assert not world.hub.writes.is_pull(world.address, md_hash(OPEN))


def test_the_box_s_james_at_the_door_writes_from_tiroir_with_his_session(world):
    world.put(OPEN, repo=world.two.list_repo)
    text = world.two.list_repo.joinpath(NAME).read_text(encoding="utf-8")
    res = door(world.door, rpc("tools/call", {"name": "update", "arguments": {
        "doc": world.address, "expected_hash": md_hash(text), "text": text + "\nEdited.\n"}}),
               token=world.tokens[SHARED], headers={"X-James-Session": SID})
    assert res.status == 200 and not res.json()["result"]["isError"], res.text
    line = world.hub.writes.last(world.address)
    assert (line.place, line.session, line.via) == ("tiroir", SID, "update")
    assert world.hub.writes.last_session(world.address) == line


def test_a_pull_logs_the_pages_the_hub_opens_and_no_versions_file_nor_readme(world):
    top = world.two.list_repo
    others = [top / ".sheaf/versions/acme/blog" / NAME.rsplit("/", 1)[1].replace(".md", "") / "ab12.md",
              top / "README.md"]
    for path in others:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Not a page\n", encoding="utf-8")
        assert world.hub._page_of(path) is None
        pulled(world, path)
    assert world.hub.writes._lines == {} and world.hub.writes._left == {}


def test_a_pull_remembers_the_text_it_left_only_for_a_page_that_is_open(world):
    world.put(OPEN)
    path = world.two.private_repo / NAME
    pulled(world, path)                             # the page is not open: its line, nothing to wait for
    assert [l.via for l in world.hub.writes.lines(world.address)] == ["pull"]
    assert world.hub.writes._left == {}


def test_a_write_between_the_pull_and_its_telling_keeps_its_disk_line(world):
    world.put(OPEN)
    path = world.two.private_repo / NAME
    world.hub.entry(world.address)
    files = [(path, "Ada")]
    hashes = {path: md_hash(OPEN)}                  # what the pull left, read under its locks
    world.hub.pulling(path.parent, files)
    path.write_text(OPEN + "\nAn editor, in the gap.\n", encoding="utf-8")
    world.hub.pulled(path.parent, files, True, hashes)
    assert not world.hub.writes.is_pull(world.address, md_hash(path.read_text(encoding="utf-8")))
