"""A request authorises the entry it resolved, by that entry's root, never an address it resolves afterwards: a root
name given to another folder between the check and the resolve must not hand a member the replacement's document."""
import pytest
from helpers import Front
from test_hub_visibility import BOB, OPEN, members

DOC = "acme/tiroir/2026-10-28-contract.md"
MINE = OPEN
THEIRS = OPEN.replace("A quote from the contract.", "The replacement root's own text.")


@pytest.fixture
def team(hub, browser, work, plan):
    hub.proxy = members(work)
    (work / DOC).parent.mkdir(parents=True)
    (work / DOC).write_text(MINE, encoding="utf-8")
    return Front(hub, browser.handler)


def reassign_in_the_gap(hub, work, tmp_path, when):
    """The root name `work` is let go and given to another folder holding a document of the same address, once, at the
    moment `Hub.entry` (the resolve) is called, so after the handler's first check and before anything is served."""
    other = tmp_path / "other"
    (other / DOC).parent.mkdir(parents=True)
    (other / "plan.md").write_text("# plan\n", encoding="utf-8")
    (other / DOC).write_text(THEIRS, encoding="utf-8")
    real, done = hub.entry, []

    def entry(address):
        if when == "before" and not done:
            done.append(1)
            hub.roots.forget("work")
            hub.roots._add(other, False, name="work")
        got = real(address)
        if when == "after" and not done:
            done.append(1)
            hub.roots.forget("work")
            hub.roots._add(other, False, name="work")
        return got
    hub.entry = entry
    return done


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("path", ["/work/" + DOC, "/_/doc?doc=work/" + DOC])
def test_a_root_name_given_to_another_folder_between_the_check_and_the_resolve_serves_nothing(team, work, tmp_path, when, path):
    done = reassign_in_the_gap(team.hub, work, tmp_path, when)
    got = team.get(path, member=BOB)
    assert done, "the gap was not reached"
    assert "replacement root" not in got.text
    if when == "before":
        assert got.status == 404


