"""`[list]`'s `member_dirs`: the James that works for a member has folders of his own, and every other member, an
unknown one and a Tell with no member reach the `[list]` folders. The map holds the exceptions and the default is
the shared James, so a missing or wrong entry never lands a Tell, a Stop or a transcript at another member's James.
Through the handler in proxy mode on the fixtures of test_hub_work: Thierry has a James of his own, Hans has none."""
import json
from pathlib import Path

import pytest
from helpers import hub_rows
from test_hub_work import (ADDRESS, BEA, CWD, DOC, FOLDER, HANS, LIVE, SHEAF, THIERRY, box, comment,  # noqa: F401
                           download, drops, meta, put, replies, stop_james, team)

from sheafmd.hub import the_list
from sheafmd.hub.the_list import Dirs

OWN_LIVE = "5a5a5a5a-1b2c-4d3e-8f40-a1b2c3d4e5f6"
OWN_WORK = "/home/james/own-work"
OWN_CWD = f"{OWN_WORK}/thinkingtoo/tiroir"
OWN_FOLDER = "-home-james-own-work-thinkingtoo-tiroir"
OWN_TRANSCRIPT = (b'{"type":"user","cwd":"%s","sessionId":"%s","message":"own"}\n'
                  % (OWN_CWD.encode(), OWN_LIVE.encode()))
OWN_SHEAF = SHEAF.replace("sessions:\n", f"sessions:\n  - {{id: {OWN_LIVE}, host: tiroir-tt, member: james, "
                                         "date: 2026-10-29T05:12:03Z}\n")


def cfg_of(team, **changes):
    cfg = team.hub.the_list.cfg
    team.hub.the_list = the_list.TheList(team.hub, the_list.ListConfig(**{**cfg.__dict__, **changes}))
    return team.hub.the_list.cfg


@pytest.fixture
def mapped(team, box, work, tmp_path):
    """Thierry's James has folders of his own; the `[list]` folders of `box` are the shared James's."""
    own = {"tell": tmp_path / "own-tell", "stop": tmp_path / "own-stop", "sessions": tmp_path / "own-sessions"}
    for folder in own.values():
        folder.mkdir()
    (own["sessions"] / OWN_FOLDER).mkdir()
    (own["sessions"] / OWN_FOLDER / f"{OWN_LIVE}.jsonl").write_bytes(OWN_TRANSCRIPT)
    shared_stop = tmp_path / "shared-stop"
    shared_stop.mkdir()
    cfg_of(team, stop_dir=shared_stop, member_dirs={THIERRY: Dirs(own["tell"], own["stop"], own["sessions"],
                                                                 Path(OWN_WORK))})
    put(team, work, DOC, OWN_SHEAF + "\n- [ ] Stop James\n")
    return {**box, "own": own, "shared_stop": shared_stop}


def files(folder):
    return sorted(f for f in folder.iterdir() if not f.name.startswith("."))


# ── a Tell ───────────────────────────────────────────────────────────────────

def test_a_tell_by_the_member_the_map_names_goes_to_his_dir_only(team, work, mapped):
    assert comment(team, work, "tell", as_=THIERRY).status == 200
    assert len(files(mapped["own"]["tell"])) == 1 and files(mapped["tell"]) == []


def test_member_not_in_map_goes_to_shared_dir(team, work, mapped):
    assert comment(team, work, "tell", as_=HANS).status == 200
    assert len(drops(mapped)) == 1 and files(mapped["own"]["tell"]) == []
    assert json.loads(drops(mapped)[0].read_bytes())["member"] == "hans"


def test_a_member_with_no_short_name_and_one_of_another_root_go_to_shared_dir(team, work, mapped):
    cfg = team.hub.the_list.cfg
    assert cfg.dirs_for(team.hub.proxy.members[BEA]).tell_dir == mapped["tell"]
    assert cfg.dirs_for(team.hub.proxy.members[HANS]).tell_dir == mapped["tell"]


def test_missing_member_goes_to_shared_dir(team, mapped):
    cfg = team.hub.the_list.cfg
    assert cfg.dirs_for(None) == cfg.default_dirs
    assert cfg.dirs_for(None).tell_dir == mapped["tell"]
    # something that is not a member at all, a name that is only like an id of the map
    assert cfg.dirs_for(object()).tell_dir == mapped["tell"]
    assert cfg.dirs_for(type("M", (), {"id": THIERRY.upper()})()).tell_dir == mapped["tell"]


def test_no_map_means_all_shared(team, box, work):
    assert team.hub.the_list.cfg.member_dirs == {}
    for who in (THIERRY, HANS):
        assert comment(team, work, "tell", as_=who).status == 200
    assert len(drops(box)) == 2


def test_a_key_the_member_leaves_out_is_the_list_s(team, mapped):
    cfg = cfg_of(team, member_dirs={THIERRY: Dirs(tell_dir=mapped["own"]["tell"])})
    mine = cfg.dirs_for(team.hub.proxy.members[THIERRY])
    assert mine.tell_dir == mapped["own"]["tell"]
    assert (mine.stop_dir, mine.sessions_dir, mine.work_dir) == (cfg.stop_dir, cfg.sessions_dir, cfg.work_dir)


def test_without_a_default_tell_dir_a_member_not_in_the_map_can_not_tell(team, work, mapped):
    cfg_of(team, tell_dir=None)
    got = comment(team, work, "tell", as_=HANS)
    assert got.status == 400 and "only on the machine that runs the hub" in got.json()["error"]
    assert files(mapped["own"]["tell"]) == []
    assert comment(team, work, "tell", as_=THIERRY).status == 200
    assert len(files(mapped["own"]["tell"])) == 1


def test_the_page_offers_a_tell_by_the_dirs_of_the_member_it_is_for(team, work, mapped):
    cfg_of(team, tell_dir=None)
    assert meta(team, member=HANS)["can"] == []
    assert meta(team, member=THIERRY)["can"] == ["box-ask", "box-tell"]


def test_a_drop_s_status_is_read_in_the_dir_it_was_written_in(team, work, mapped):
    cid = comment(team, work, "tell", as_=THIERRY).json()["id"]
    name = files(mapped["own"]["tell"])[0].name
    (mapped["own"]["tell"] / f"{name}.status").write_text('{"state": "picked-up"}', encoding="utf-8")
    (mapped["tell"] / f"{name}.status").write_text('{"state": "failed", "error": "the shared one"}', encoding="utf-8")
    team.hub._read_drop_statuses()
    assert [r["state"] for r in hub_rows("drop-status") if r["thread"] == cid] == ["picked-up"]


# ── a Stop ───────────────────────────────────────────────────────────────────

def test_a_stop_by_a_member_not_in_the_map_goes_to_shared_dir_and_clears_only_its_tells(team, work, mapped):
    own = comment(team, work, "tell", as_=THIERRY, body="Mine.").json()["id"]
    shared = comment(team, work, "tell", as_=HANS, body="Theirs.").json()["id"]
    assert stop_james(team, work, member=HANS).status == 200
    assert [f.read_text(encoding="utf-8") for f in files(mapped["shared_stop"])] == ["thinkingtoo/tiroir\n"]
    assert files(mapped["own"]["stop"]) == []
    assert len(files(mapped["own"]["tell"])) == 1 and files(mapped["tell"]) == []
    assert [r["thread"] for r in hub_rows("tell-stopped")] == [shared]
    assert not [r for r in replies(team, own) if "Stopped before delivery" in r["text"]]


def test_a_stop_by_the_member_the_map_names_goes_to_his_dir_only(team, work, mapped):
    comment(team, work, "tell", as_=HANS)
    assert stop_james(team, work, member=THIERRY).status == 200
    assert [f.read_text(encoding="utf-8") for f in files(mapped["own"]["stop"])] == ["thinkingtoo/tiroir\n"]
    assert files(mapped["shared_stop"]) == []
    assert len(drops(mapped)) == 1                          # the shared James's Tell stays


# ── a transcript ─────────────────────────────────────────────────────────────

def test_a_member_not_in_the_map_is_served_the_list_s_copy_only(team, mapped):
    assert download(team, id=LIVE, member=HANS).status == 200
    got = download(team, id=OWN_LIVE, member=HANS)
    assert got.status == 404 and got.body != OWN_TRANSCRIPT


def test_the_member_the_map_names_is_served_his_copy_and_then_the_list_s(team, mapped):
    assert download(team, id=OWN_LIVE, member=THIERRY).body == OWN_TRANSCRIPT
    assert download(team, id=LIVE, member=THIERRY).status == 200


def test_the_live_session_is_served_from_the_copy_of_the_member_asking(team, mapped):
    got = download(team, member=THIERRY)
    assert got.status == 200 and got.headers["X-Sheaf-Session"] == OWN_LIVE
    # Hans reads the newest session of the shared copy, never the own one that the front matter lists first
    assert download(team, member=HANS).status == 404


def test_a_member_with_no_copy_of_his_own_has_none_without_a_list_copy(team, mapped):
    cfg = cfg_of(team, sessions_dir=None)
    assert cfg.copies(team.hub.proxy.members[HANS]) == ()
    assert download(team, id=OWN_LIVE, member=HANS).status == 404


def test_a_session_is_recorded_only_from_the_copy_of_the_james_that_wrote_it(team, mapped):
    from sheafmd.hub import work as work_mod
    cfg = team.hub.the_list.cfg
    thierry, hans = team.hub.proxy.members[THIERRY], team.hub.proxy.members[HANS]
    assert work_mod.james_has(cfg, "thinkingtoo/tiroir", OWN_LIVE, thierry) is True
    assert work_mod.james_has(cfg, "thinkingtoo/tiroir", OWN_LIVE, hans) in (None, False)
    assert work_mod.james_has(cfg, "thinkingtoo/tiroir", OWN_LIVE) in (None, False)


# ── the config ───────────────────────────────────────────────────────────────

def parse(work, tmp_path, **extra):
    t = {"root": str(work), "repo": "thinkingtoo/tt-tiroir", "project": 1, "token_file": str(tmp_path / "token"),
         "tell_dir": "/run/shared/tell", **extra}
    return the_list.parse(t, "the test")


def test_member_dirs_read(work, tmp_path):
    cfg = parse(work, tmp_path, member_dirs={THIERRY: {"tell_dir": "/run/own/tell/", "sessions_dir": "/var/own",
                                                       "work_dir": "/home/own/work"}})
    assert cfg.member_dirs == {THIERRY: Dirs(Path("/run/own/tell"), None, Path("/var/own"), Path("/home/own/work"))}
    assert cfg.tell_dir == Path("/run/shared/tell")


@pytest.mark.parametrize("table, word", [
    ({"x": "text"}, "must be a table"),
    ({"x": {"tell_dir": "relative"}}, "absolute path"),
    ({"x": {"tell_dirs": "/a"}}, "unknown key"),
    ({"x": {"tell_dir": 5}}, "absolute path"),
    ({"x": {"sessions_dir": "/var/own"}}, "go together"),
    ({"x": {"work_dir": "/home/own/work"}}, "go together"),
    ({"x": {"stop_dir": "@ROOT@/stop"}}, "inside the list's root"),
    ({"x": {"tell_dir": "@ROOT@"}}, "inside the list's root"),
])
def test_member_dirs_refuses(work, tmp_path, table, word):
    table = json.loads(json.dumps(table).replace("@ROOT@", str(work)))
    with pytest.raises(the_list.ListError, match=word):
        parse(work, tmp_path, member_dirs=table)


def test_member_dirs_must_be_a_table(work, tmp_path):
    with pytest.raises(the_list.ListError, match="a table"):
        parse(work, tmp_path, member_dirs="x")


# ── the hub's start ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["stop_dir", "tell_dir", "sessions_dir"])
def test_a_members_own_folder_inside_a_members_root_stops_the_start(proxy_folder, key):
    from test_hub_list import NELL, configure_list
    from test_proxy_start import refused_start
    table = f'[list.member_dirs."{NELL}"]\n{key} = "/srv/nell/box"\n'
    if key == "sessions_dir":
        table += 'work_dir = "/home/own/work"\n'
    configure_list(f"{proxy_folder}/hub.sock", "/srv/nell",
                   'root = "/srv/list"\nrepo = "a/b"\nproject = 1\ntoken_file = "/run/t"\n')
    from sheafmd import paths
    p = paths.config_file()
    p.write_text(p.read_text(encoding="utf-8") + "\n" + table, encoding="utf-8")
    code, err, rows = refused_start()
    assert code == 1
    assert [r["kind"] for r in rows] == ["list-config"], rows
    assert f"'{key}' of [list.member_dirs" in rows[0]["reason"] and "inside a root of Nell" in rows[0]["reason"]


def test_a_member_dirs_id_that_is_no_member_stops_the_start(proxy_folder):
    from test_hub_list import configure_list
    from test_proxy_start import refused_start
    configure_list(f"{proxy_folder}/hub.sock", "/srv/nell",
                   'root = "/srv/list"\nrepo = "a/b"\nproject = 1\ntoken_file = "/run/t"\n')
    from sheafmd import paths
    p = paths.config_file()
    p.write_text(p.read_text(encoding="utf-8") + '\n[list.member_dirs."nobody"]\ntell_dir = "/run/own/tell"\n',
                 encoding="utf-8")
    code, err, rows = refused_start()
    assert code == 1 and "who is no member of [proxy]" in rows[0]["reason"]
