"""The receiving end of a root's move, first stage (ticket 21): which pages this tiroir can take. The clone through the
same report as a laptop's, each page's owner by e-mail, the page's blob against this tiroir's own clone. A fake hub: no
server, no network."""
import contextlib
import subprocess
from types import SimpleNamespace

import pytest

from sheafmd.hub import incoming, proxy
from sheafmd.hub import repos as repos_mod

HERE = "https://here.example"


def member(id, email, short="", private_root=""):
    return proxy.Member(id=id, name=id, roots=(), email=email, short=short, private_root=private_root)


class FakeRepos:
    def __init__(self, clone, dest):
        self.answer, self.dest, self.calls, self.queue = {"clone": clone, "commit_known": True}, dest, [], []
        self.rest, self.rest_refused, self.settled_for = [], {}, []

    busy, settle_ok = False, True

    def report(self, member, repo, path, commit, privates=(), declared=None, row=True):
        self.calls.append((member, repo, path, commit, list(privates)))
        if isinstance(self.answer, Exception):
            raise self.answer
        self.busy = row             # the report's row is settled on the repo's own thread: `settle` waits for it (a clone-only report writes none)
        if row:
            self.queue.append((member, repo, path, commit))      # the row a report settles; `row=False` makes the clone only
        return {"repo": repo, "path": path, **self.answer}

    def clone_dir(self, repo):
        return self.dest

    moved, unmoved, slept = None, [], []

    def moved_to(self, repo):
        return self.moved

    def page_text(self, repo, path, commit):
        repos_mod._clean_path(path)         # as the real one: a markdown page's path, never `.sheaf.toml`
        return self._show(commit, path)

    def root_toml(self, repo, commit):
        return self._show(commit, ".sheaf.toml")

    def _show(self, commit, path):
        r = subprocess.run(["git", "-C", str(self.dest), "show", f"{commit}:{path}"], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None

    def report_rest(self, repo, commit, owned, privates=()):
        self.rest.append((repo, commit, [(m, p) for m, p in owned]))
        for member, path in owned:
            if path not in self.rest_refused:
                self.queue.append((member, repo, path, commit))
                self.busy = True
        return dict(self.rest_refused)

    def settle(self, seconds=120.0, repo=None):
        self.settled_for.append(repo)
        if self.settle_ok and self.busy:
            self.busy = False
            self._settled()
        return self.settle_ok

    def _settled(self):
        pass

    sleep_fails = 0

    def sleep_moved(self, repo, to):
        if self.sleep_fails:
            self.sleep_fails -= 1
            return False
        if self.busy:
            return False            # a report is being settled: the caller asks again
        self.slept.append((repo, to))
        self.moved = to
        return True

    def install_url(self, repo):
        return self.answer.get("install", "")

    def refusal(self, member, repo, privates=()):
        a = self.answer
        if isinstance(a, Exception):
            return None
        return a["clone"] if a["clone"] in (repos_mod.NO_APP, repos_mod.PRIVATE_ROOT, repos_mod.NOT_CLONED) else None

    def unmove(self, repo):
        self.unmoved.append(repo)
        self.moved = None
        return True


def git(at, *args):
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clone(tmp_path):
    """A clone on `dev` whose `origin/dev` holds a.md."""
    bare = tmp_path / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(bare)], check=True)
    c = tmp_path / "c"
    subprocess.run(["git", "clone", "-q", str(bare), str(c)], check=True, capture_output=True)
    git(c, "checkout", "-q", "-b", "dev")
    (c / "a.md").write_text("# A\n")
    (c / ".sheaf.toml").write_text(f'tiroir = "{HERE}"\n')
    git(c, "add", "a.md", ".sheaf.toml")
    git(c, "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-qm", "a")
    git(c, "push", "-q", "-u", "origin", "dev")
    return c


def hub(clone, state=repos_mod.OK, members=None):
    members = members if members is not None else [member("alice", "alice@example.com", short="al"), member("bob", "bob@example.com")]
    return SimpleNamespace(proxy=SimpleNamespace(origin=HERE, members={m.id: m for m in members}), repos=FakeRepos(state, clone))


def body(clone, *pages, **over):
    return {"id": "m1", "repo": "o/r", "branch": "dev", "tip": git(clone, "rev-parse", "dev"),
            "from": {"origin": "https://there.example", "by": "alice"},
            "pages": [{"path": p, "owner_email": e, "blob": git(clone, "hash-object", "a.md") if b is None else b}
                      for p, e, b in pages], **over}


def test_a_page_whose_owner_and_blob_match_is_ready(clone):
    status, answer = incoming.check_root(hub(clone), body(clone, ("a.md", "ALICE@example.com", None)))
    assert (status, answer) == (200, {"pages": {"a.md": {"ready": True}}})


def test_the_report_is_the_laptops_own_with_the_owner_the_tip_and_the_private_roots(clone):
    h = hub(clone, members=[member("alice", "alice@example.com", short="al"), member("bob", "bob@example.com", private_root="/x")])
    incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)))
    (who, repo, path, commit, privates), = h.repos.calls
    assert (who, repo, path, commit) == ("al", "o/r", "a.md", git(clone, "rev-parse", "dev"))
    assert privates == [("bob", "/x")]


def test_a_report_is_made_for_each_owned_page_so_each_keeps_the_owner_its_front_matter_names(clone):
    h = hub(clone)
    incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None), ("b.md", "bob@example.com", None),
                                ("c.md", "nobody@example.com", None)))
    assert [(who, path) for who, _, path, *_ in h.repos.calls] == [("al", "a.md")]      # the first one only clones; every page is queued whole after the toml check
    assert h.repos.rest == [("o/r", git(clone, "rev-parse", "dev"), [("al", "a.md"), ("bob", "b.md")])]


def test_every_owned_page_has_its_row_settled_before_any_page_lands(clone):
    (clone / "b.md").write_text("# A\n")      # the same text as a.md: the body's blob fits both
    git(clone, "add", "b.md")
    git(clone, "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-qm", "b")
    git(clone, "push", "-q", "origin", "dev")
    h = land_hub(clone)
    b = body(clone, ("a.md", "alice@example.com", None), ("b.md", "bob@example.com", None))
    incoming.check_root(h, b)
    assert h.repos.events == ["settled"] and set(h.repos.rows) == {("o/r", "a.md"), ("o/r", "b.md")}
    incoming.land_root(h, b)
    assert h.repos.events == ["settled", "settled", "land_record", "land_record"]
    assert set(h.repos.rows) == {("o/r", "a.md"), ("o/r", "b.md")}


def test_a_clone_being_made_answers_cloning(clone):
    assert incoming.check_root(hub(clone, repos_mod.CLONING), body(clone, ("a.md", "alice@example.com", None))) == (202, {"state": "cloning"})


def test_a_clone_that_does_not_know_the_tip_yet_answers_cloning(clone):
    h = hub(clone)
    h.repos.answer["commit_known"] = False
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (202, {"state": "cloning"})


def test_no_app_for_the_repo_is_refused_whole_with_the_install_link(clone):
    h = hub(clone, repos_mod.NO_APP)
    h.repos.answer["install"] = "https://install.example/o/r"
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == \
        (409, {"why": "no_app", "install": "https://install.example/o/r"})


@pytest.mark.parametrize("state,why", [(repos_mod.PRIVATE_ROOT, "private_root"), (repos_mod.NOT_CLONED, "not_cloned")])
def test_a_private_root_or_a_repo_not_cloned_is_refused_whole(clone, state, why):
    assert incoming.check_root(hub(clone, state), body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": why})


def test_a_refused_report_is_refused_whole(clone):
    h = hub(clone)
    h.repos.answer = repos_mod.Refused("the clone failed")
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "refused"})


def test_each_page_is_judged_alone_none_ambiguous_and_made_up_refused(clone):
    members = [member("alice", "alice@example.com"), member("c1", "twin@example.com"), member("c2", "TWIN@example.com"), member("dan", "")]
    made_up = proxy.default_email("dan", HERE)
    pages = [("a.md", "alice@example.com", None), ("b.md", "nobody@example.com", None), ("c.md", "twin@example.com", None),
             ("d.md", made_up, None), ("e.md", "", None)]
    status, answer = incoming.check_root(hub(clone, members=members), body(clone, *pages))
    assert status == 200
    assert answer["pages"] == {"a.md": {"ready": True}, "b.md": {"ok": False, "why": "no_owner"},
                               "c.md": {"ok": False, "why": "ambiguous_owner"}, "d.md": {"ok": False, "why": "no_email"},
                               "e.md": {"ok": False, "why": "no_email"}}


def test_a_page_this_tiroirs_clone_does_not_hold_with_that_blob_is_text_differs(clone):
    status, answer = incoming.check_root(hub(clone), body(clone, ("a.md", "alice@example.com", "0" * 40), ("gone.md", "alice@example.com", None)))
    assert answer["pages"] == {"a.md": {"ok": False, "why": "text_differs"}, "gone.md": {"ok": False, "why": "text_differs"}}


def test_no_page_with_an_owner_makes_no_report_and_no_clone(clone):
    h = hub(clone)
    status, answer = incoming.check_root(h, body(clone, ("a.md", "nobody@example.com", None)))
    assert h.repos.calls == [] and answer["pages"]["a.md"]["why"] == "no_owner"


def test_a_hub_with_no_clones_refuses_the_root(clone):
    h = hub(clone)
    h.repos = None
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "no_clones"})


@pytest.mark.parametrize("bad", [{"id": ""}, {"repo": 3}, {"branch": None}, {"tip": ""}, {"pages": "x"}, {"pages": [{"path": "../x.md", "owner_email": "a", "blob": "b"}]},
                                 {"pages": [{"path": "a.md", "blob": "b"}]},
                                 {"pages": [{"path": "a.md", "owner_email": "a@example.com", "blob": "b"}] * 2}])
def test_a_body_that_is_not_a_root_is_refused_with_the_reason(clone, bad):
    with pytest.raises(ValueError):
        incoming.check_root(hub(clone), body(clone, ("a.md", "alice@example.com", None), **bad))


@pytest.mark.parametrize("page", [{"path": [], "owner_email": "a@example.com", "blob": "b"},
                                  {"path": {}, "owner_email": "a@example.com", "blob": "b"}, "a.md"])
def test_a_page_path_of_another_json_type_is_refused_as_no_path(clone, page):
    """A path no set can hold (a list) raised TypeError before the shapes were checked (189 B)."""
    with pytest.raises(ValueError, match="a page of the root's move has no path"):
        incoming.check_root(hub(clone), body(clone, pages=[page]))


def test_a_repo_that_moved_away_is_refused_whole_and_never_answers_cloning(clone):
    assert incoming.check_root(hub(clone, repos_mod.MOVED), body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "moved"})


def test_a_hub_with_no_origin_of_its_own_refuses_the_root_whole(clone):
    h = hub(clone)
    del h.proxy
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "no_origin"})


# ── the way back (ticket 21 part 2) ──────────────────────────────────────────

THERE = "https://there.example"


def moved_hub(clone, state=repos_mod.OK, to=THERE):
    h = hub(clone, state)
    h.repos.moved, h.repos.unmoved, h.repos.slept = to, [], []
    return h


def test_a_root_that_moved_to_the_verified_peer_is_unmoved_before_the_report(clone):
    h = moved_hub(clone)
    status, answer = incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE)
    assert (status, answer) == (200, {"pages": {"a.md": {"ready": True}}})
    assert h.repos.unmoved == ["o/r"]


def test_the_peers_origin_is_compared_as_the_hub_spells_it(clone):
    h = moved_hub(clone)
    incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer="HTTPS://There.example/")
    assert h.repos.unmoved == ["o/r"]


@pytest.mark.parametrize("peer", ["https://third.example", None, ""])
def test_a_peer_the_root_did_not_move_to_unmoves_nothing_whatever_the_body_says(clone, peer):
    h = moved_hub(clone, repos_mod.MOVED)
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=peer) == (409, {"why": "moved"})
    assert h.repos.unmoved == []                  # the body's from.origin is THERE: it is never trusted


def test_a_root_that_did_not_move_is_not_unmoved(clone):
    h = hub(clone)
    h.repos.unmoved = []
    incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE)
    assert h.repos.unmoved == []


@pytest.mark.parametrize("state", [repos_mod.NO_APP, repos_mod.PRIVATE_ROOT, repos_mod.NOT_CLONED])
def test_a_refusal_of_the_whole_root_leaves_it_moved(clone, state):
    h = moved_hub(clone, state)
    status, _ = incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE)
    assert status == 409 and h.repos.unmoved == [] and h.repos.moved == THERE


def test_a_report_the_repos_refuse_after_the_unmove_is_answered_refused_and_the_root_is_back(clone):
    h = moved_hub(clone)
    h.repos.answer = repos_mod.Refused("clone failed")
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE) == (409, {"why": "refused"})
    assert h.repos.unmoved == ["o/r"]           # a clone that failed before is settled by this report, as for any root: it is tried again


def test_no_page_with_a_known_owner_unmoves_nothing(clone):
    h = moved_hub(clone)
    incoming.check_root(h, body(clone, ("a.md", "nobody@example.com", None)), peer=THERE)
    assert h.repos.unmoved == []


def test_the_way_back_refusal_for_no_app_names_the_install_link_only_when_there_is_one(clone):
    h = moved_hub(clone, repos_mod.NO_APP)
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE) == (409, {"why": "no_app"})
    h.repos.answer["install"] = "https://install.example/o/r"
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE) == \
        (409, {"why": "no_app", "install": "https://install.example/o/r"})


# ── the toml at the tip names this tiroir (ticket 21 part 2) ─────────────────

def set_toml(clone, text):
    (clone / ".sheaf.toml").write_text(text)
    git(clone, "add", ".sheaf.toml")
    git(clone, "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-qm", "toml")
    git(clone, "push", "-q", "origin", "dev")


@pytest.mark.parametrize("text", ['tiroir = "https://other.example"\n', "", 'theme = "x"\n', "not = [valid"])
def test_a_root_whose_toml_at_the_tip_does_not_name_this_tiroir_is_refused_whole(clone, text):
    set_toml(clone, text)
    h = hub(clone)
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "not_named"})


def test_a_root_refused_not_named_leaves_no_row_of_any_page(clone):
    set_toml(clone, 'tiroir = "https://other.example"\n')
    h = hub(clone)
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "not_named"})
    assert h.repos.queue == [] and h.repos.rest == []


def test_the_first_owned_page_is_reported_with_the_rest_once_the_toml_names_this_tiroir(clone):
    h = hub(clone)
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)))[0] == 200
    assert [path for _, _, path, _ in h.repos.queue] == ["a.md"]


def test_the_toml_naming_this_tiroir_in_another_spelling_is_accepted(clone):
    set_toml(clone, 'tiroir = "HTTPS://Here.example/"\n')
    status, _ = incoming.check_root(hub(clone), body(clone, ("a.md", "alice@example.com", None)))
    assert status == 200


def test_a_root_unmoved_by_this_call_goes_back_to_sleep_when_its_toml_does_not_name_this_tiroir(clone):
    set_toml(clone, 'tiroir = "https://other.example"\n')
    h = moved_hub(clone)
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE) == (409, {"why": "not_named"})
    assert h.repos.unmoved == ["o/r"] and h.repos.slept == [("o/r", THERE)] and h.repos.moved == THERE


def test_a_root_with_no_clone_of_the_tip_yet_is_not_judged_by_its_toml(clone):
    h = hub(clone)
    h.repos.answer["commit_known"] = False
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (202, {"state": "cloning"})


# ── landing (ticket 21 part 2b) ──────────────────────────────────────────────

class Versions:
    """A hub's versions that record what they are given, and fail when told to."""

    def __init__(self, fail=False, before=()):
        self.puts, self.fail, self.before, self.taken_back = [], fail, list(before), []

    def stamps(self, address):
        return {}

    def put(self, address, text):
        if self.fail:
            raise OSError("disk full")
        self.puts.append((address, text))

    def texts(self, address):
        return list(self.before)

    def take_back(self, address, before, made, stamps=None):
        self.taken_back.append((address, list(before), list(made)))


class Writes:
    def __init__(self, before=()):
        self.carried, self.restored, self.before, self.made, self.took_back = [], [], list(before), [], []

    def lines(self, address):
        return list(self.before)

    @contextlib.contextmanager
    def own_lines(self):
        self.made = ["carried line"]
        yield self.made

    def carry(self, address, lines, came_from, by):
        self.carried.append((address, lines, came_from, by))

    def undo(self, address, own):
        self.took_back.append((address, own))

    def restore(self, address, kept):
        self.restored.append((address, list(kept)))


class LandRepos(FakeRepos):
    def __init__(self, *a):
        super().__init__(*a)
        self.rows, self.priors, self.events = {}, {}, []

    def _settled(self):
        """What the repo's thread writes when it settles the report: the row of the page it was made for, as `_settle` writes one,
        the first owner kept and no field of a landed record."""
        for member, repo, path, commit in self.queue:
            row = self.rows.get((repo, path))
            self.rows[(repo, path)] = (row[0] if row else member, commit, {})
        self.queue.clear()
        self.events.append("settled")

    def land_record(self, repo, path, owner, commit, record):
        self.events.append("land_record")
        self.priors[(repo, path)] = self.rows.get((repo, path))
        self.rows[(repo, path)] = (owner, commit, record)
        return self.priors[(repo, path)]

    def drop_record(self, repo, path, prior):
        if prior is None:
            self.rows.pop((repo, path), None)
        else:
            self.rows[(repo, path)] = prior


def land_hub(clone, state=repos_mod.OK, fail=False):
    h = hub(clone, state)
    h.repos = LandRepos(state, clone)
    h.versions, h.writes = Versions(fail), Writes()
    return h


def test_a_ready_page_writes_its_record_versions_and_write_log_under_the_roots_address(clone):
    h = land_hub(clone)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0].update(record={"session": "s1", "host": "box"}, versions=[{"text": "# old\n"}],
                         writes=[{"time": "t", "writer": "w"}])
    blob = b["pages"][0]["blob"]
    assert incoming.land_root(h, b) == (200, {"pages": {"a.md": {"ok": True, "hash": blob}}})
    assert h.repos.rows == {("o/r", "a.md"): ("al", b["tip"], {"session": "s1", "host": "box"})}
    assert h.versions.puts == [("o--r/a.md", "# old\n")]
    assert h.writes.carried == [("o--r/a.md", [{"time": "t", "writer": "w"}], "https://there.example", "alice")]


def test_a_landed_version_brings_back_no_audience(clone):
    h = land_hub(clone)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "---\nshared: bob\n---\n# old\n"}]
    incoming.land_root(h, b)
    (_, text), = h.versions.puts
    assert "shared" not in text


def test_a_page_with_no_extras_lands_its_record_alone(clone):
    h = land_hub(clone)
    incoming.land_root(h, body(clone, ("a.md", "bob@example.com", None)))
    assert h.repos.rows == {("o/r", "a.md"): ("bob", git(clone, "rev-parse", "dev"), {})}
    assert h.versions.puts == [] and h.writes.carried[0][3] == "alice"


def test_a_repeat_with_the_same_id_and_path_lands_once_and_is_told_the_same_answer(clone):
    h = land_hub(clone)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# old\n"}]
    first = incoming.land_root(h, b)
    second = incoming.land_root(h, b)
    assert first == second
    assert len(h.versions.puts) == 1 and len(h.writes.carried) == 1


def test_a_second_id_for_the_same_path_lands_again(clone):
    h = land_hub(clone)
    incoming.land_root(h, body(clone, ("a.md", "alice@example.com", None)))
    incoming.land_root(h, body(clone, ("a.md", "alice@example.com", None), id="m2"))
    assert len(h.writes.carried) == 2


def test_a_failing_store_leaves_nothing_and_answers_failed_for_that_page(clone):
    h = land_hub(clone, fail=True)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# old\n"}]
    assert incoming.land_root(h, b) == (200, {"pages": {"a.md": {"ok": False, "why": "failed"}}})
    assert h.repos.rows == {("o/r", "a.md"): ("al", b["tip"], {})}      # the row the report made, and no more
    assert h.versions.taken_back == [("o--r/a.md", [], ["# old\n"])] and len(h.writes.took_back) == 1 and h.writes.took_back[0][0] == "o--r/a.md" and h.writes.restored == []


def test_a_failed_landing_restores_the_row_the_page_had_and_is_not_remembered(clone):
    h = land_hub(clone, fail=True)
    h.repos.rows[("o/r", "a.md")] = ("bob", "old", {})
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# old\n"}]
    incoming.land_root(h, b)
    assert h.repos.rows == {("o/r", "a.md"): ("bob", b["tip"], {})}      # as the report left it: the first owner is kept, never alice's
    h.versions.fail = False
    assert incoming.land_root(h, b)[1]["pages"]["a.md"]["ok"] is True     # a retry of the same id lands


def test_one_page_failing_does_not_stop_the_next(clone):
    h = land_hub(clone)
    real = h.versions.put
    h.versions.put = lambda address, text: (_ for _ in ()).throw(OSError("x")) if address.endswith("a.md") else real(address, text)
    (clone / "b.md").write_text("# B\n")
    git(clone, "add", "b.md")
    git(clone, "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-qm", "b")
    git(clone, "push", "-q", "origin", "dev")
    b = body(clone, ("a.md", "alice@example.com", None), ("b.md", "alice@example.com", git(clone, "hash-object", "b.md")))
    b["pages"][0]["versions"] = [{"text": "x"}]
    status, answer = incoming.land_root(h, b)
    assert answer["pages"]["a.md"] == {"ok": False, "why": "failed"} and answer["pages"]["b.md"]["ok"] is True
    assert h.repos.rows[("o/r", "b.md")][2] == {} and h.repos.rows[("o/r", "a.md")] == ("al", b["tip"], {})     # a.md: the report's row alone


def test_a_page_the_check_refused_writes_nothing(clone):
    h = land_hub(clone)
    b = body(clone, ("a.md", "nobody@example.com", None), ("gone.md", "alice@example.com", "0" * 40))
    status, answer = incoming.land_root(h, b)
    assert status == 200 and answer["pages"]["a.md"]["why"] == "no_owner" and answer["pages"]["gone.md"]["why"] == "text_differs"
    assert ("o/r", "a.md") not in h.repos.rows and h.versions.puts == [] and h.writes.carried == []     # nothing landed for either page


def test_a_root_the_check_refuses_whole_is_answered_as_is_and_writes_nothing(clone):
    h = land_hub(clone, repos_mod.NO_APP)
    assert incoming.land_root(h, body(clone, ("a.md", "alice@example.com", None))) == (409, {"why": "no_app"})
    assert h.repos.rows == {} and h.writes.carried == []
    h = land_hub(clone, repos_mod.CLONING)
    assert incoming.land_root(h, body(clone, ("a.md", "alice@example.com", None))) == (202, {"state": "cloning"})


def test_a_move_naming_a_repo_outside_the_receivers_installation_clones_nothing(clone):
    h = land_hub(clone, repos_mod.NO_APP)
    h.repos.answer["install"] = "https://install.example/o/r"
    status, answer = incoming.land_root(h, body(clone, ("a.md", "alice@example.com", None)))
    assert (status, answer["why"]) == (409, "no_app")
    assert h.repos.rows == {} and h.repos.unmoved == []


def test_the_peer_is_passed_on_to_the_check(clone):
    h = land_hub(clone)
    h.repos.moved = THERE
    incoming.land_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE)
    assert h.repos.unmoved == ["o/r"]


@pytest.mark.parametrize("extra", [{"record": "x"}, {"record": ["a"]}, {"versions": "x"}, {"versions": [{"nope": 1}]}, {"versions": [3]},
                                   {"versions": [{"text": "x"}] * (incoming.MAX_VERSIONS + 1)}, {"writes": [3]}, {"writes": "x"},
                                   {"writes": [{}] * (incoming.MAX_WRITES + 1)}])
def test_a_page_with_a_malformed_extra_is_a_value_error_before_anything_is_written(clone, extra):
    h = land_hub(clone)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0].update(extra)
    with pytest.raises(ValueError):
        incoming.land_root(h, b)
    assert h.repos.calls == [] and h.repos.rows == {}


# ── the fix round of the first review (ticket 21 part 2b) ────────────────────

def test_a_page_that_comes_back_keeps_its_prior_versions_and_pins_when_its_landing_fails(clone):
    """What the member kept at the address before the page left stays when the landing fails: only what it made goes."""
    from sheafmd.hub import state as hub_state
    h = land_hub(clone)
    h.versions = real = hub_state.Versions()
    address = "o--r/a.md"
    for text in ("# one\n", "# two\n"):
        real.put(address, text)
    pinned = real.pin(address, "# pinned\n")
    before = real.texts(address)
    h.writes.carry = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# two\n"}, {"text": "# from there\n"}]
    assert incoming.land_root(h, b) == (200, {"pages": {"a.md": {"ok": False, "why": "failed"}}})
    assert sorted(real.texts(address)) == sorted(before)
    assert real.get(address, pinned) == "# pinned\n"


def test_a_page_that_comes_back_keeps_its_prior_versions_when_the_incoming_ones_push_them_out(clone):
    from sheafmd.hub import state as hub_state
    h = land_hub(clone)
    h.versions = real = hub_state.Versions()
    address = "o--r/a.md"
    prior = [f"# prior {n}\n" for n in range(hub_state.VERSIONS_KEPT)]
    for text in prior:
        real.put(address, text)
    h.writes.carry = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": f"# incoming {n}\n"} for n in range(10)]
    incoming.land_root(h, b)
    assert sorted(real.texts(address)) == sorted(prior)


def test_the_report_is_settled_before_any_page_lands_so_it_cannot_overwrite_a_landed_row(clone):
    h = land_hub(clone)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["record"] = {"session": "s1"}
    incoming.land_root(h, b)
    assert h.repos.events == ["settled", "land_record"]
    h.repos.settle()                       # a late settle changes nothing
    assert h.repos.rows == {("o/r", "a.md"): ("al", b["tip"], {"session": "s1"})}


def test_a_failed_first_page_leaves_the_row_the_report_made_whenever_the_thread_runs(clone):
    h = land_hub(clone, fail=True)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# old\n"}]
    incoming.land_root(h, b)
    first = dict(h.repos.rows)
    h.repos.settle()
    assert h.repos.rows == first == {("o/r", "a.md"): ("al", b["tip"], {})}


def test_a_report_that_does_not_settle_in_time_answers_cloning_and_lands_nothing(clone):
    h = land_hub(clone)
    h.repos.settle_ok = False
    assert incoming.land_root(h, body(clone, ("a.md", "alice@example.com", None))) == (202, {"state": "cloning"})
    assert h.writes.carried == [] and "land_record" not in h.repos.events


def test_a_root_unmoved_by_the_call_goes_back_to_sleep_though_its_report_is_still_being_settled(clone):
    set_toml(clone, 'tiroir = "https://other.example"\n')
    h = moved_hub(clone)
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE) == (409, {"why": "not_named"})
    assert h.repos.slept == [("o/r", THERE)] and h.repos.moved == THERE and not h.repos.busy


def test_a_version_written_at_the_address_during_the_landing_survives_its_failure(clone):
    """The landing does not hold the page's writer lock: what someone else puts there meanwhile is not the landing's to take back."""
    from sheafmd.hub import state as hub_state
    h = land_hub(clone)
    h.versions = real = hub_state.Versions()
    address = "o--r/a.md"
    real.put(address, "# prior\n")

    def meanwhile(*a, **k):
        real.put(address, "# written meanwhile\n")
        raise OSError("disk full")

    h.writes.carry = meanwhile
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# from there\n"}]
    incoming.land_root(h, b)
    assert sorted(real.texts(address)) == sorted(["# prior\n", "# written meanwhile\n"])


# ── the fix round of the fifth review (ticket 21 part 2b) ────────────────────

def test_the_root_toml_is_read_through_the_root_file_and_not_a_markdown_page_path(clone):
    """`FakeRepos.page_text` refuses a path that is not a page's, as `Repos.page_text` does: the toml cannot go through it."""
    h = hub(clone)
    with pytest.raises(repos_mod.Refused):
        h.repos.page_text("o/r", ".sheaf.toml", git(clone, "rev-parse", "dev"))
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None))) == (200, {"pages": {"a.md": {"ready": True}}})


def test_a_repo_named_in_mixed_case_is_cleaned_once_for_everything_the_check_asks(clone):
    h = moved_hub(clone)
    status, _ = incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None), repo="O/R"), peer=THERE)
    assert status == 200 and h.repos.unmoved == ["o/r"]
    assert {repo for _, repo, *_ in h.repos.calls} == {"o/r"} and {repo for repo, *_ in h.repos.rest} <= {"o/r"}


def test_a_repo_that_is_no_repo_name_is_refused_whole(clone):
    assert incoming.check_root(hub(clone), body(clone, ("a.md", "alice@example.com", None), repo="not a repo")) == (409, {"why": "refused"})


def test_the_owned_pages_are_reported_together_and_none_is_dropped(clone):
    h = hub(clone)
    pages = [("a.md", "alice@example.com", None)] + [(f"p{n}.md", "bob@example.com", "0" * 40) for n in range(200)]
    incoming.check_root(h, body(clone, *pages))
    (repo, commit, owned), = h.repos.rest
    assert len(owned) == 201 and {m for m, _ in owned} == {"al", "bob"}


def test_a_page_whose_owner_may_not_have_the_clone_is_refused_and_the_others_go_on(clone):
    h = hub(clone)
    h.repos.rest_refused = {"b.md": repos_mod.PRIVATE_ROOT}
    status, answer = incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None), ("b.md", "bob@example.com", None)))
    assert answer["pages"] == {"a.md": {"ready": True}, "b.md": {"ok": False, "why": "private_root"}}


def test_the_check_waits_for_this_repos_thread_only(clone):
    h = land_hub(clone)
    incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)))
    assert h.repos.settled_for and set(h.repos.settled_for) == {"o/r"}


def test_a_root_that_cannot_go_back_to_sleep_at_once_is_put_to_sleep_when_asked_again(clone):
    set_toml(clone, 'tiroir = "https://other.example"\n')
    h = moved_hub(clone)
    h.repos.sleep_fails = 1
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE) == (409, {"why": "not_named"})
    assert h.repos.slept == [("o/r", THERE)]


def test_a_root_that_will_not_sleep_is_still_refused_not_named(clone):
    set_toml(clone, 'tiroir = "https://other.example"\n')
    h = moved_hub(clone)
    h.repos.sleep_fails = 99
    assert incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE) == (409, {"why": "not_named"})
    assert h.repos.slept == []



@pytest.mark.parametrize("answer", [{"clone": repos_mod.OK, "commit_known": False}, {"clone": repos_mod.CLONING}])
def test_a_root_unmoved_by_the_call_sleeps_again_when_the_check_leaves_early(clone, answer):
    h = moved_hub(clone)
    h.repos.answer.update(answer)
    status, _ = incoming.check_root(h, body(clone, ("a.md", "alice@example.com", None)), peer=THERE)
    assert status != 200 and h.repos.unmoved == ["o/r"] and h.repos.slept == [("o/r", THERE)]
class InsideVersions(Versions):
    pass


def hub_with_root(clone, store, strict=False):
    h = land_hub(clone)
    root = SimpleNamespace(id="r1", path=clone, name="o--r")
    h.roots = SimpleNamespace(get=lambda name: root if name == "o--r" else None)
    h.private_roots = {"r1": "x"} if strict else {}
    h._versions_of = lambda r, named="", strict=False: store
    return h


def test_the_versions_of_a_page_land_in_the_store_the_roots_page_reads(clone):
    store = InsideVersions()
    h = hub_with_root(clone, store)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# one\n"}]
    incoming.land_root(h, b)
    assert [a for a, _ in store.puts] == ["o--r/a.md"] and h.versions.puts == []


def test_a_private_roots_versions_land_nowhere_and_the_page_still_lands(clone):
    h = hub_with_root(clone, None, strict=True)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# one\n"}]
    assert incoming.land_root(h, b)[1]["pages"]["a.md"]["ok"] is True
    assert h.versions.puts == []


def test_a_failed_landing_takes_the_versions_back_from_the_store_it_wrote_to(clone):
    store = InsideVersions()
    h = hub_with_root(clone, store)
    h.writes.carry = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# one\n"}]
    incoming.land_root(h, b)
    assert len(store.taken_back) == 1 and h.versions.taken_back == []


def test_a_failed_landing_takes_back_the_write_log_lines_it_carried_and_no_others(clone):
    h = land_hub(clone, fail=True)
    b = body(clone, ("a.md", "alice@example.com", None))
    b["pages"][0]["versions"] = [{"text": "# old\n"}]
    incoming.land_root(h, b)
    assert h.writes.took_back == [("o--r/a.md", h.writes.made)] and h.writes.restored == []
