"""A page that lands from another tiroir (ticket 21) gets its record row written as a report writes it, and a landing
that fails takes the row away again: `Repos.land_record` and `Repos.drop_record` against a real `Repos`, no hub."""
import pytest
from test_repo_pages import REPO, FakeApp, origin, sh  # noqa: F401  (fixtures and helpers)

from sheafmd.hub.repos import Repos

PATH = "docs/plan.md"


@pytest.fixture
def repos(tmp_path, origin):  # noqa: F811
    r = Repos(tmp_path / "clones", FakeApp(), remote_url=lambda repo: str(origin))
    r.FETCH_EVERY = 0.0
    return r


def test_a_landed_record_is_read_by_owner_of_and_attribution(repos):
    prior = repos.land_record(REPO, PATH, "bea", "c0ffee", {"session": "s1", "host": "box", "link": "https://x.example/s1"})
    assert prior is None
    assert repos.owner_of(REPO, PATH) == "bea"
    assert repos.attribution(REPO, PATH) == {"session": "s1", "host": "box", "link": "https://x.example/s1",
                                             "label": "session s1"}


def test_a_peer_cannot_name_the_owner_through_the_record(repos):
    """`named` is what the page's own front matter says at a commit, read from git by a report: never what a peer sends."""
    repos.land_record(REPO, PATH, "bea", "c0ffee", {"named": "carl"})
    assert repos.owner_of(REPO, PATH) == "bea"
    assert "named" not in repos._read()[REPO][PATH]


def test_a_row_the_page_had_with_a_named_owner_does_not_outlive_the_landing(repos):
    repos._write({REPO: {PATH: {"owner": "bea", "commit": "aa", "named": "carl"}}})
    repos.land_record(REPO, PATH, "dan", "bb", {})
    assert repos.owner_of(REPO, PATH) == "dan"


def test_only_the_known_fields_of_a_record_are_kept(repos):
    repos.land_record(REPO, PATH, "bea", "c0ffee", {"session": "s1", "owner": "mallory", "commit": "bad", "other": 1, "host": ""})
    assert repos._read()[REPO][PATH] == {"owner": "bea", "commit": "c0ffee", "session": "s1"}


def test_a_drop_restores_a_missing_row_byte_for_byte(repos):
    repos.land_record(REPO, "docs/other.md", "bea", "aa", {})
    before = repos._records_file.read_bytes()
    prior = repos.land_record(REPO, PATH, "bea", "c0ffee", {"session": "s1"})
    repos.drop_record(REPO, PATH, prior)
    assert repos._records_file.read_bytes() == before
    assert repos.owner_of(REPO, PATH) is None


def test_a_drop_restores_an_earlier_row_byte_for_byte(repos):
    repos._write({REPO: {PATH: {"owner": "bea", "commit": "aa", "named": "carl", "session": "s0"}}})
    before = repos._records_file.read_bytes()
    prior = repos.land_record(REPO, PATH, "dan", "bb", {"session": "s1"})
    assert prior == {"owner": "bea", "commit": "aa", "named": "carl", "session": "s0"}
    assert repos.owner_of(REPO, PATH) == "dan"
    repos.drop_record(REPO, PATH, prior)
    assert repos._records_file.read_bytes() == before


def test_a_drop_of_the_only_row_leaves_no_empty_repo_entry(repos):
    assert not repos._records_file.exists()
    prior = repos.land_record(REPO, PATH, "bea", "aa", {})
    repos.drop_record(REPO, PATH, prior)
    assert repos._read() == {}


def test_the_named_owner_a_report_read_at_the_same_commit_survives_the_landing(repos):
    """The report that `check_root` waits for read `owner:` from the page's front matter at the tip: that is not the peer's."""
    repos._write({REPO: {PATH: {"owner": "bea", "commit": "c0ffee", "named": "carl"}}})
    repos.land_record(REPO, PATH, "dan", "c0ffee", {"session": "s1", "named": "mallory"})
    assert repos.owner_of(REPO, PATH) == "carl"
    assert repos._read()[REPO][PATH] == {"owner": "dan", "commit": "c0ffee", "named": "carl", "session": "s1"}


def test_a_named_owner_read_at_another_commit_is_not_carried_to_the_landed_one(repos):
    repos._write({REPO: {PATH: {"owner": "bea", "commit": "old", "named": "carl"}}})
    repos.land_record(REPO, PATH, "dan", "c0ffee", {})
    assert repos.owner_of(REPO, PATH) == "dan"


def test_a_landed_row_is_keyed_as_a_report_keys_it_so_the_reader_finds_it(repos):
    """A report writes under the lower-cased repo (`_clean_repo`); the landing of a root whose body spells it otherwise
    must write, read back and drop under that same key."""
    repos.land_record("Owner/Repo", PATH, "bea", "c0ffee", {})
    assert list(repos._read()) == ["owner/repo"]
    assert repos.owner_of("owner/repo", PATH) == "bea"
    repos.drop_record("Owner/Repo", PATH, None)
    assert repos._read() == {}
