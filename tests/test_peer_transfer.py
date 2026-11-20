"""The receiving end of a move to this tiroir (ticket 20): `POST /_/tiroir/transfer` lands a bundle in the owner's loose
root, in the same folder, matched by e-mail, and answers what landed. In memory through the handler (`front`)."""
import json
import os
from dataclasses import replace

import pytest
from helpers import BEA, CAL
from test_peer_channel import PEER, TAILNET, channel, peer_token  # noqa: F401  (fixtures and helpers)

from sheafmd.hub import channel as chan
from sheafmd.hub import loose
from sheafmd.source import md_hash

TEXT = """---
owner: bea
---
# Notes

First paragraph.

<!-- comment c1: Cal, open
Why pears?
-->
"""


@pytest.fixture
def members(front):
    front.hub.proxy.members[BEA] = replace(front.hub.proxy.members[BEA], email="Bea@Example.com", short="bea")
    front.hub.proxy.members[CAL] = replace(front.hub.proxy.members[CAL], short="cal")
    return front


def bundle(**over):
    return {"id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "owner_email": "bea@example.com", "folder": "projects/blog",
            "name": "notes.md", "text": TEXT, "versions": [{"text": "# Notes\n\nOlder.\n"}, {"text": TEXT}],
            "writes": [{"time": "2026-11-10T09:00:00", "writer": "Claude Code (Bea)", "place": "laptop", "via": "door",
                        "session": "s-1", "host": "", "link": "", "chat": ""}],
            "keep": False, "from": {"origin": PEER, "by": "Bea", "at": "2026-11-16T10:00:00"}, **over}


def transfer(front, token, **over):
    return channel(front, "transfer", bundle(**over), token)


def landed(front, res):
    assert res.status == 200, res.text
    out = res.json()
    return out, front.hub.file(out["address"])


def test_a_transfer_lands_the_page_in_the_owners_loose_root_in_the_same_folder(members):
    res = transfer(members, peer_token())
    out, path = landed(members, res)
    assert out["address"] == "loose-bea/projects/blog/notes.md" and out["origin"] == members.hub.proxy.origin
    assert out["hash"] == md_hash(path.read_text(encoding="utf-8"))
    assert members.hub.loose.known(members.hub.proxy.members[BEA]) is not None


def test_the_comments_travel_with_the_text_and_the_owner_is_the_one_there(members):
    _, path = landed(members, transfer(members, peer_token()))
    text = path.read_text(encoding="utf-8")
    assert "comment c1: Cal, open" in text and "Why pears?" in text


def test_the_bundle_carries_versions_write_log_lines_and_the_keep_mark(members):
    out, _ = landed(members, transfer(members, peer_token(), keep=True))
    a = out["address"]
    assert members.hub.versions.get(a, md_hash("# Notes\n\nOlder.\n")) == "# Notes\n\nOlder.\n"
    lines = members.hub.writes.lines(a)
    assert any(l.session == "s-1" and l.writer == "Claude Code (Bea)" and l.time == "2026-11-10T09:00:00" for l in lines)
    assert lines[-1].via == "transfer" and lines[-1].place == "tiroir"
    root = members.hub.roots.get(a.split("/")[0])
    assert loose.kept(root.path, "projects/blog/notes.md")


def test_the_share_does_not_go_the_landed_page_is_private_to_the_owner(members):
    shared = TEXT.replace("owner: bea\n", "owner: bea\nvisibility: project\nshared: Cal 2026-11-01\n").replace("# Notes\n", "# Notes\n\n- [x] Share with Cal\n")
    out, path = landed(members, transfer(members, peer_token(), text=shared))
    text = path.read_text(encoding="utf-8")
    assert "shared:" not in text and "[x] Share" not in text and "[ ] Share with Cal" in text
    cfg = members.hub.proxy
    assert members.hub.member_owns(cfg.members[BEA], out["address"]) and not members.hub.member_owns(cfg.members[CAL], out["address"])


def test_the_versions_carry_no_share_either(members):
    shared = "---\nowner: bea\nvisibility: project\nshared: Cal 2026-11-01\n---\n# Notes\n\n- [x] Share with Cal\n"
    out, _ = landed(members, transfer(members, peer_token(), versions=[{"text": shared}]))
    kept = [members.hub.versions.get(out["address"], md_hash(t)) for t in (shared,)]
    assert kept == [None]
    from sheafmd.hub import visibility
    clean = visibility.set_keys(visibility.without_ticked_share(shared), {"shared": None})
    assert members.hub.versions.get(out["address"], md_hash(clean)) == clean


def test_the_owner_is_matched_by_email_ignoring_case_never_by_name(members):
    token = peer_token()
    assert transfer(members, token, owner_email="BEA@example.COM").status == 200
    res = transfer(members, token, id="2" * 36, owner_email="Bea", name="b.md")
    assert res.status == 409 and res.json()["why"] == "no_owner"
    res = transfer(members, token, id="3" * 36, owner_email="stranger@example.com", name="c.md")
    assert res.status == 409 and res.json()["why"] == "no_owner"


def test_two_members_with_the_same_email_land_nothing(members):
    members.hub.proxy.members[CAL] = replace(members.hub.proxy.members[CAL], email="bea@example.com")
    res = transfer(members, peer_token())
    assert res.status == 409 and res.json()["why"] == "ambiguous_owner"
    assert not list(os.scandir(loose._base())) if loose._base().exists() else True


def test_a_member_with_no_email_cannot_be_the_owner_and_the_line_says_why(members):
    members.hub.proxy.members[BEA] = replace(members.hub.proxy.members[BEA], email="")
    res = transfer(members, peer_token(), owner_email="")
    assert res.status == 409 and res.json()["why"] == "no_email" and "e-mail" in res.json()["say"]
    made_up = f"{BEA}@{members.hub.proxy.origin.split('//')[1]}"
    res = transfer(members, peer_token(), owner_email=made_up, id="4" * 36)
    assert res.status == 409 and res.json()["why"] == "no_email"
    res = transfer(members, peer_token(), owner_email="bea@example.com", id="5" * 36)
    assert res.status == 409 and res.json()["why"] == "no_owner"          # her block has no e-mail: nobody is found by it


def test_a_name_that_is_there_is_refused_and_nothing_is_overwritten_or_suffixed(members):
    token = peer_token()
    out, path = landed(members, transfer(members, token))
    before = path.read_text(encoding="utf-8")
    res = transfer(members, token, id="9" * 36, text=TEXT + "\nOther.\n")
    assert res.status == 409 and res.json()["why"] == "name_taken"
    assert path.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["notes.md"]


def test_a_repeated_id_answers_the_first_answer_and_lands_nothing_more(members):
    token = peer_token()
    first = transfer(members, token).json()
    again = transfer(members, token, text=TEXT + "\nChanged after.\n")
    assert again.status == 200 and again.json() == first
    path = members.hub.file(first["address"])
    assert "Changed after" not in path.read_text(encoding="utf-8")


def test_a_bundle_over_the_limit_is_refused_before_it_is_read(members):
    token = peer_token()
    big = json.dumps(bundle(text="x" * (chan.MAX_TRANSFER + 1))).encode()
    res = members.request("POST", "/_/tiroir/transfer", member=None, raw=big,
                          headers={**TAILNET, "Authorization": f"Bearer {token}"})
    assert res.status == 413
    assert members.hub.loose.known(members.hub.proxy.members[BEA]) is None


@pytest.mark.parametrize("bad", [{"name": "../x.md"}, {"name": "x.txt"}, {"folder": "../up"}, {"folder": "/abs"},
                                  {"versions": "no"}, {"writes": [1]}, {"id": ""}, {"text": 5}, {"keep": "yes"}],
                         ids=lambda b: next(iter(b)) + "=" + str(next(iter(b.values()))))
def test_a_bundle_that_is_not_one_lands_nothing(members, bad):
    res = transfer(members, peer_token(), **bad)
    assert res.status in (400, 409)
    root = members.hub.loose.known(members.hub.proxy.members[BEA])
    assert root is None or not [p for p in root.rglob("*.md")]


def test_a_failed_landing_leaves_nothing_behind(members, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk")
    token = peer_token()
    with monkeypatch.context() as m:
        m.setattr(members.hub.versions, "put", boom)
        res = transfer(members, token)
    assert res.status == 500
    root = members.hub.loose.known(members.hub.proxy.members[BEA])
    assert not [p for p in root.rglob("*.md")]
    assert members.hub.writes.lines("loose-bea/projects/blog/notes.md") == []
    assert transfer(members, token).status == 200      # the id of a failed landing is free again


# ── the sending side's refusal (the move itself is hooked up once ticket 17 is in) ──

def test_a_member_with_no_email_or_the_made_up_one_has_none_to_send_and_the_line_says_why(members):
    from sheafmd.hub import outgoing, proxy
    cfg = members.hub.proxy
    assert outgoing.owner_email(cfg, cfg.members[BEA]) == ("Bea@Example.com", "")
    none, why = outgoing.owner_email(cfg, cfg.members[CAL])
    assert none is None and "e-mail" in why
    made_up = replace(cfg.members[CAL], email=proxy.default_email(CAL, cfg.origin))
    assert outgoing.owner_email(cfg, made_up)[0] is None


def test_an_archived_page_lands_archived_and_a_page_that_was_not_lands_in_the_default_view(members):
    from sheafmd.hub import archive
    token = peer_token()
    out, path = landed(members, transfer(members, token, archived=True))
    root = members.hub.roots.get(out["address"].split("/")[0])
    rel = out["address"].split("/", 1)[1]
    assert archive.is_archived(loose.times(root.path, loose.ARCHIVED), rel, path.stat().st_mtime)
    out, path = landed(members, transfer(members, token, id="8" * 36, name="other.md", archived=False))
    assert not archive.is_archived(loose.times(root.path, loose.ARCHIVED), "projects/blog/other.md", path.stat().st_mtime)


def test_an_archived_that_is_not_true_or_false_is_not_a_bundle(members):
    res = transfer(members, peer_token(), archived="yes")
    assert res.status == 400


def test_a_landing_that_outlasts_the_deadline_lands_nothing_and_answers_too_slow(members, monkeypatch):
    import time
    sender_waits = chan.SECONDS
    monkeypatch.setattr(chan, "SECONDS", 0.05)
    real = members.hub.versions.put

    def slow(*a, **k):
        time.sleep(0.15)
        return real(*a, **k)
    monkeypatch.setattr(members.hub.versions, "put", slow)
    token = peer_token()
    res = transfer(members, token)
    assert res.status == 409 and res.json()["why"] == "too_slow" and res.json()["say"]
    root = members.hub.loose.known(members.hub.proxy.members[BEA])
    assert root is None or not [p for p in root.rglob("notes.md")]
    monkeypatch.setattr(members.hub.versions, "put", real)
    # the real landing must not race the 0.05 s deadline set above: on a loaded runner it took longer and answered too_slow
    monkeypatch.setattr(chan, "SECONDS", sender_waits)
    assert transfer(members, token).status == 200            # nothing was remembered of the failed one: the same id lands


# ── a page moving back, and the landing that fails ───────────────────────────

ELSEWHERE = "https://elsewhere.example.com"
GONE = "loose-bea/projects/blog/gone.md"


def forwarded(members, origin=ELSEWHERE):
    """A page of Bea's has left for `origin`: a Forward at `GONE`, and her loose root exists (an earlier page landed in it)."""
    landed(members, transfer(members, peer_token(origin=origin)))
    members.hub.forwards.add_remote(GONE, origin, "loose-bea2/projects/blog/gone.md", "Bea", "h1")


def back(members, token, **over):
    return transfer(members, token, id="7c9e6679-7425-40de-944b-e07fc1f90ae8", name="gone.md",
                    **{"from": {"origin": ELSEWHERE, "by": "Bea", "at": "2026-11-16T10:00:00"}, **over})


def test_a_page_moving_back_lifts_the_forward_when_the_peer_token_names_the_tiroir_it_left_for(members):
    forwarded(members)
    res = back(members, peer_token(origin=ELSEWHERE))
    assert res.status == 200, res.text
    assert members.hub.forwards.remote(GONE) is None


def test_a_bundle_that_claims_the_origin_the_page_left_for_lifts_no_forward_when_the_token_is_another_tiroirs(members):
    forwarded(members)
    res = back(members, peer_token())            # the token is PEER's; only the body says ELSEWHERE
    assert res.status == 409
    assert members.hub.forwards.remote(GONE) is not None


def test_a_landing_that_fails_with_any_exception_puts_the_lifted_forward_back(members, monkeypatch):
    from sheafmd import mcp
    forwarded(members)

    def broken(self, args, caller):
        raise OSError("disk full")
    monkeypatch.setattr(mcp.Door, "_create", broken)
    try:
        back(members, peer_token(origin=ELSEWHERE))
    except OSError:
        pass
    assert members.hub.forwards.remote(GONE) is not None


def test_a_page_moving_back_lifts_every_forward_the_move_made_for_it_and_points_its_earlier_addresses_at_it(members):
    forwarded(members)
    older = "loose-bea/older/gone.md"
    members.hub.forwards.add(older, GONE, "Bea")                     # the page was at `older` first, and moved to GONE here
    members.hub.forwards.add_remote(GONE, ELSEWHERE, "loose-bea2/projects/blog/gone.md", "Bea", "h1")    # then left: `older` leads there too
    assert members.hub.forwards.remote(older) is not None
    res = back(members, peer_token(origin=ELSEWHERE))
    assert res.status == 200, res.text
    assert members.hub.forwards.remote(GONE) is None and members.hub.forwards.remote(older) is None
    assert members.hub.forwards.follow(older) == GONE          # its old links lead to where the page is again


def test_a_landing_that_waited_for_the_lock_past_the_senders_deadline_lands_nothing(members, monkeypatch):
    import threading
    import time

    from sheafmd.hub import state
    monkeypatch.setattr(chan, "SECONDS", 0.2)
    held, release = threading.Event(), threading.Event()

    def other_landing():
        with state.file_locked("transfers.lock"):
            held.set()
            release.wait(5)
    threading.Thread(target=other_landing, daemon=True).start()
    assert held.wait(5)
    threading.Timer(0.5, release.set).start()
    res = transfer(members, peer_token())
    assert res.status == 409 and res.json()["why"] == "too_slow"
    time.sleep(0.05)
    root = members.hub.loose.known(members.hub.proxy.members[BEA])
    assert root is None or not [p for p in root.rglob("notes.md")]


def test_a_landing_that_fails_takes_back_only_the_write_log_lines_it_made_not_the_ones_kept_at_the_address(members, monkeypatch):
    from sheafmd.hub.writelog import WriteLog
    forwarded(members)
    members.hub.writes.add(GONE, "Bea", "laptop", "door")           # what `moved_remote` kept of the page that left
    kept = members.hub.writes.lines(GONE)
    assert kept

    def broken(self, *a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(WriteLog, "carry", broken)
    try:
        back(members, peer_token(origin=ELSEWHERE))
    except OSError:
        pass
    assert members.hub.writes.lines(GONE) == kept


def test_a_page_that_moves_back_carries_no_write_log_line_the_address_already_keeps(members):
    from sheafmd.hub.writelog import WriteLog
    forwarded(members)
    members.hub.writes.add(GONE, "Bea", "laptop", "door", session="s-1")       # kept at the address when the page left
    sent = [{k: v for k, v in vars(line).items() if k != "address"} for line in members.hub.writes.lines(GONE)]
    res = back(members, peer_token(origin=ELSEWHERE), writes=sent)             # the other tiroir sends the same lines back
    assert res.status == 200, res.text
    own = [(line.time, line.writer, line.place, line.via, line.session, line.host, line.link, line.chat)
           for line in members.hub.writes.lines(GONE) if line.via != "transfer"]
    assert len(own) == len(set(own)) == len(sent)
    assert isinstance(members.hub.writes, WriteLog)


def test_two_identical_lines_in_one_bundle_are_both_kept(members):
    forwarded(members)
    line = {"time": "2026-11-10T09:00:00", "writer": "Claude Code (Bea)", "place": "laptop", "via": "door",
            "session": "s-1", "host": "", "link": "", "chat": ""}
    res = back(members, peer_token(origin=ELSEWHERE), writes=[line, dict(line)])      # two writes in the same second
    assert res.status == 200, res.text
    assert len([w for w in members.hub.writes.lines(GONE) if w.via == "door"]) == 2


def _fails_after_carry(monkeypatch):
    from sheafmd.hub.writelog import WriteLog
    real = WriteLog.carry

    def carried_then_broken(self, *a, **k):
        real(self, *a, **k)
        raise OSError("disk full")
    monkeypatch.setattr(WriteLog, "carry", carried_then_broken)


def test_a_failed_landing_is_taken_back_in_the_write_log_file_too_so_a_restart_does_not_bring_its_lines_back(members, monkeypatch):
    from sheafmd.hub.writelog import WriteLog
    forwarded(members)
    members.hub.writes.add(GONE, "Bea", "laptop", "door")           # kept at the address when the page left
    kept = members.hub.writes.lines(GONE)
    _fails_after_carry(monkeypatch)
    assert back(members, peer_token(origin=ELSEWHERE)).status != 200
    assert members.hub.writes.lines(GONE) == kept
    assert WriteLog().lines(GONE) == kept                           # a restarted hub, built from the file


def test_a_failed_landing_at_a_new_address_leaves_no_line_of_it_after_a_restart(members, monkeypatch):
    from sheafmd.hub.writelog import WriteLog
    _fails_after_carry(monkeypatch)
    assert transfer(members, peer_token()).status != 200
    address = "loose-bea/projects/blog/notes.md"
    assert members.hub.writes.lines(address) == []
    assert WriteLog().lines(address) == []



def test_a_landing_that_fails_keeps_the_line_someone_else_wrote_at_its_address_meanwhile(members, monkeypatch):
    import threading
    import time
    monkeypatch.setattr(chan, "SECONDS", 0.05)
    address = "loose-bea/projects/blog/notes.md"
    real = members.hub.versions.put

    def slow(*a, **k):
        # the landing holds no writer lock: another writer's line reaches the log from its own thread while the landing runs
        other = threading.Thread(target=members.hub.writes.add, args=(address, "Cal", "page", "save"))
        other.start()
        other.join()
        time.sleep(0.15)
        return real(*a, **k)
    monkeypatch.setattr(members.hub.versions, "put", slow)
    res = transfer(members, peer_token())
    assert res.status == 409 and res.json()["why"] == "too_slow"
    assert [(l.writer, l.via) for l in members.hub.writes.lines(address)] == [("Cal", "save")]    # the landing's own lines go, Cal's stays


def test_a_failed_unkeep_does_not_skip_the_unarchive_of_a_failed_landing(members, monkeypatch):
    from sheafmd.hub import incoming

    def boom(*a, **k):
        raise OSError("disk")
    seen = []
    monkeypatch.setattr(incoming, "_unkeep", boom)
    monkeypatch.setattr(incoming, "_unarchive", lambda *a: seen.append(a))
    monkeypatch.setattr(members.hub.versions, "put", boom)
    assert transfer(members, peer_token()).status == 500
    assert seen
