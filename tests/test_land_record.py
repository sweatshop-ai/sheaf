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


def test_a_named_owner_in_the_record_wins_as_in_a_report(repos):
    repos.land_record(REPO, PATH, "bea", "c0ffee", {"named": "carl"})
    assert repos.owner_of(REPO, PATH) == "carl"


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
    repos.land_record(REPO, PATH, "bea", "aa", {"session": "s0", "named": "carl"})
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
