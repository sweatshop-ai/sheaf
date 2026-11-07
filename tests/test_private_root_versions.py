"""The versions store follows the file (SPEC 7.4, 9.11): a private sheaf's versions are kept in the private repo under the
key its commit uses, chosen again at each call, so the list repo never holds one."""
import pytest
from test_private_root_file import NAME, OPEN, PRIVATE_TEXT, address, hub_of, untouched
from two_roots import TwoRoots, git, two_roots

from sheafmd.blocks import split_md_blocks
from sheafmd.hub import place, state
from sheafmd.source import md_hash

SECOND = "\n\nSecond paragraph.\n"


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def edit(hub, name, words):
    a = address(hub, name)
    with place.held(hub, a):
        e = hub.entry(a)
        text = e.path.read_text(encoding="utf-8")
        i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith(("Secret", "Shared")))
        e.live.save(md_hash(text), [{"i": i, "html": f"<p>{words}</p>"}])


def test_private_version_merges_after_restart(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT + SECOND, encoding="utf-8")
    a = address(hub)
    text = hub.entry(a).path.read_text(encoding="utf-8")       # the page is rendered from this text
    edit(hub, NAME, "Changed by another tab.")
    again = two.hub()                                          # a restart
    again.the_list.root()
    with place.held(again, a):
        e = again.entry(a)
        blocks = split_md_blocks(text)
        i = next(i for i, b in enumerate(blocks) if b.content.startswith("Second"))
        report = e.live.save(md_hash(text), [{"i": i, "html": "<p>Second, edited.</p>"}])
    assert report["merged"]
    now = (two.private_repo / NAME).read_text(encoding="utf-8")
    assert "Changed by another tab." in now and "Second, edited." in now
    # the folder is the one a commit of the file names: the path in the root, not the list root's address
    assert (two.private_repo / state.INSIDE / state.doc_key(NAME)).is_dir()
    assert not (two.private_repo / state.INSIDE / state.doc_key(a)).exists()


def test_versions_store_follows_file_root(two):
    hub = hub_of(two)
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    a = address(hub)
    live = hub.entry(a).live                                   # opened as a list sheaf, the handle kept
    (two.list_repo / NAME).unlink()
    git(two.list_repo, "add", "-A")
    git(two.list_repo, "commit", "-q", "-m", "gone")
    git(two.list_repo, "push", "-q", "origin", "HEAD:main")
    seen = untouched(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")   # a private sheaf at the same name
    live._remember("# post\n\nPrivate edit, through the old handle.\n")
    edit(hub, NAME, "Private edit.")
    hub.tick()                                                 # the sweep of each repo's versions
    assert hub.commits.settle()
    assert untouched(two) == seen
    assert (two.private_repo / state.INSIDE / state.doc_key(NAME)).is_dir()
    assert "Private edit" not in "".join(p.read_text(encoding="utf-8") for p in (two.list_repo / state.INSIDE).rglob("*.md"))


def test_stale_handle_with_both_roots_holding_the_name_stores_nothing(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    live = hub.entry(a).live
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")  # a second holder: the store is undecided
    seen = untouched(two)
    live._remember("# post\n\nA later text.\n")
    assert untouched(two) == seen
    assert not (two.list_repo / state.INSIDE).exists()


def test_sweep_private_versions_in_private_repo(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    hub.entry(address(hub))                                    # a page opened: a version, no write behind it
    seen = untouched(two)
    hub.tick()
    assert hub.commits.settle()
    assert untouched(two) == seen
    subjects = git(two.private_repo, "log", "--format=%s")
    assert f"versions: {NAME}" in subjects
    assert f"versions: {address(hub)}" not in subjects
    assert state.doc_key(NAME) in git(two.private_repo, "ls-files")


def test_private_file_gone_stores_nothing_in_the_list_repo(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    live = hub.entry(address(hub)).live
    (two.private_repo / NAME).unlink()                         # no holder left: not a reason to use the list root's store
    live._remember(PRIVATE_TEXT)
    hub.tick()
    assert hub.commits.settle()
    assert not (two.list_repo / state.INSIDE).exists()
    assert "versions:" not in git(two.list_repo, "log", "--format=%s")


def test_private_repo_away_pins_nothing_in_the_list_repo(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    live = hub.entry(address(hub)).live
    two.private_repo.rename(two.base / "private-away")
    assert live.pin(md_hash(PRIVATE_TEXT))                     # the page keeps the version in memory
    assert not (two.list_repo / state.INSIDE).exists()


def test_private_root_config_unreadable_stores_nothing_in_the_state_folder(two, monkeypatch):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    live = hub.entry(address(hub)).live
    (two.private_repo / ".sheaf.toml").write_text("versions = [", encoding="utf-8")
    live._remember("# post\n\nA later private text.\n")
    assert not (state.paths.state_dir() / "versions").exists() or not any(
        "A later private text" in p.read_text(encoding="utf-8") for p in (state.paths.state_dir() / "versions").rglob("*.md"))
