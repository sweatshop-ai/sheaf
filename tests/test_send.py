"""`sheaf FILE.md` on a connected laptop sends a loose page to the member's tiroir (SPEC 13): `create` the first time,
`update` with the last hash after, `FILE.tiroir.md` and a non-zero exit when the tiroir's text moved on, `sheaf pull`
to fetch it. Run against the hub in memory standing in for the tiroir, in a temp home with a fake keyring: no test reads
or writes the real keyring, `~/.claude.json` or config (premortem R7), and no token is in a fixture, a log or an output
line."""
import http.client
import http.server
import json
import os
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from helpers import FRONT, door
from helpers import call as door_call
from test_hub_commits import box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents  # noqa: F401  (fixture)

from sheafmd import cli, connect, paths, send
from sheafmd.cli import main
from sheafmd.hub import loose
from sheafmd.source import md_hash

ORIGINAL_POST, ORIGINAL_GET = send.post, send.get
SECOND = "https://second.example.com"
TEXT = "# Notes\n\nA first page.\n"
SESSION = "6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11"


class FakeKeyring:
    def __init__(self):
        self.items = {}

    def get(self, service, user):
        return self.items.get((service, user))

    def set(self, service, user, secret):
        self.items[(service, user)] = secret


@pytest.fixture(autouse=True)
def no_real_keyring(monkeypatch):
    def refuse():
        raise AssertionError("a test asked for the real keyring (R7): inject a FakeKeyring")
    monkeypatch.setattr(connect, "system_store", refuse)


@pytest.fixture
def keyring(monkeypatch):
    k = FakeKeyring()
    monkeypatch.setattr(connect, "system_store", lambda: k)
    return k


@pytest.fixture
def tiroir(agents, keyring, monkeypatch):  # noqa: F811
    """The hub as the tiroir, reached by `send`'s two network calls: its door and `whoami`. Bea's laptop holds her
    token for FRONT, and FRONT is the laptop's default tiroir. `tiroir.seen` is every request the CLI made."""
    token = agents.tokens["bea-claude"]
    keyring.set("sheaf", FRONT, token)
    config = paths.config_file()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f'tiroir = "{FRONT}"\n', encoding="utf-8")
    agents.seen = []
    agents.token = token

    def post(url, bearer, message, headers):
        agents.seen.append((url, headers, message))
        assert url == FRONT + "/mcp"
        res = door(agents.door, message, token=bearer, headers=dict(headers), as_name=None)
        return res.status, (res.json() if res.status == 200 else None), {}

    def get(url, bearer):
        agents.seen.append((url, {}, None))
        assert url == FRONT + "/_/whoami"
        res = agents.door.request("GET", "/_/whoami", cookie=False, headers={"Authorization": f"Bearer {bearer}"})
        return res.status, (res.json() if res.status == 200 else None), {}

    agents.calls = (post, get)
    monkeypatch.setattr(send, "post", post)
    monkeypatch.setattr(send, "get", get)
    return agents


@pytest.fixture
def scratch(tmp_path):
    """A folder outside git with a page in it: a loose page."""
    d = tmp_path / "scratch"
    d.mkdir()
    (d / "notes.md").write_text(TEXT, encoding="utf-8")
    return d / "notes.md"


@pytest.fixture
def local(monkeypatch):
    """The laptop hub's render, which `sheaf FILE.md` makes when nothing goes to a tiroir: noted, never started."""
    rendered = []
    monkeypatch.setattr(cli, "_open", lambda args: rendered.append(args.file) or 0)
    return rendered


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def on_the_tiroir(tiroir, address):
    return tiroir.hub.file(address).read_text(encoding="utf-8")


def changed_there(tiroir, address, text):
    """The member (or another session) changes the page on the tiroir: a door update with the hash it holds."""
    old = on_the_tiroir(tiroir, address)
    bad, got = door_call(tiroir.door, "update", token=tiroir.token, doc=address, text=text, expected_hash=md_hash(old))
    assert not bad, got


def state():
    return json.loads((paths.state_dir() / "sends.json").read_text(encoding="utf-8"))


# ── the first send and the next ──────────────────────────────────────────────

def test_the_first_send_creates_the_page_and_prints_the_address_the_tiroir_and_the_folder_in_that_order(tiroir, scratch, capsys):
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    lines = out.splitlines()
    address = f"loose-bea/{loose.month()}/notes.md"
    assert lines[0].startswith(f"{FRONT}/") and lines[0].endswith("notes.md"), lines
    assert lines[1] == "on chat.example.com as Bea · no agent", lines
    assert lines[2] == f"loose-bea/{loose.month()}", lines
    assert len(lines) == 3, lines
    assert on_the_tiroir(tiroir, address) == TEXT


def test_the_second_send_updates_the_same_page_with_the_hash_the_first_gave(tiroir, scratch, capsys):
    run(capsys, scratch)
    scratch.write_text(TEXT + "\nA second paragraph.\n", encoding="utf-8")
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    address = f"loose-bea/{loose.month()}/notes.md"
    assert on_the_tiroir(tiroir, address) == TEXT + "\nA second paragraph.\n"
    tools = [m["params"]["name"] for _, _, m in tiroir.seen if m and m["method"] == "tools/call"]
    assert tools == ["create", "update"]
    assert out.splitlines()[0].endswith("notes.md") and len(out.splitlines()) == 3


def test_a_send_of_a_page_that_has_not_changed_still_prints_the_three_lines(tiroir, scratch, capsys):
    run(capsys, scratch)
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    assert len(out.splitlines()) == 3


def test_folder_and_keep_go_to_the_create(tiroir, scratch, capsys):
    code, out, err = run(capsys, scratch, "--folder", "clients/acme", "--keep")
    assert code == 0, err
    assert out.splitlines()[2] == "loose-bea/clients/acme"
    root = tiroir.hub.roots.get("loose-bea")
    assert loose.kept(root.path, "clients/acme/notes.md")


def test_the_tiroir_of_a_root_beats_the_laptops_default(tiroir, scratch, local, capsys):
    """The root's `.sheaf.toml` names a tiroir this laptop holds no credential for: the page renders here."""
    (scratch.parent / ".sheaf.toml").write_text(f'tiroir = "{SECOND}"\n', encoding="utf-8")
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    assert local == [str(scratch)] and tiroir.seen == []


def test_the_tiroir_of_a_root_is_where_the_page_goes_when_the_laptop_holds_its_credential(tiroir, scratch, keyring, capsys):
    paths.config_file().write_text(f'tiroir = "{SECOND}"\n', encoding="utf-8")
    (scratch.parent / ".sheaf.toml").write_text(f'tiroir = "{FRONT}"\n', encoding="utf-8")
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    assert out.splitlines()[1].startswith("on chat.example.com")


# ── the tiroir's text moved on ───────────────────────────────────────────────

def test_a_page_changed_on_the_tiroir_meanwhile_leaves_the_tiroirs_text_beside_the_file_and_fails(tiroir, scratch, capsys):
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    theirs = TEXT + "\nAdded on the tiroir.\n"
    changed_there(tiroir, address, theirs)
    mine = TEXT + "\nAdded on the laptop.\n"
    scratch.write_text(mine, encoding="utf-8")
    code, out, err = run(capsys, scratch)
    assert code == 1 and out == ""
    beside = scratch.with_name("notes.tiroir.md")
    assert beside.read_text(encoding="utf-8") == theirs
    assert scratch.read_text(encoding="utf-8") == mine
    assert on_the_tiroir(tiroir, address) == theirs
    assert "notes.tiroir.md" in err and "merge" in err and "run" in err and "again" in err


def test_the_run_after_the_merge_succeeds(tiroir, scratch, capsys):
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    changed_there(tiroir, address, TEXT + "\nAdded on the tiroir.\n")
    scratch.write_text(TEXT + "\nAdded on the laptop.\n", encoding="utf-8")
    assert run(capsys, scratch)[0] == 1
    merged = TEXT + "\nAdded on the tiroir.\n\nAdded on the laptop.\n"
    scratch.write_text(merged, encoding="utf-8")
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    assert on_the_tiroir(tiroir, address) == merged
    assert len(out.splitlines()) == 3


def test_a_refused_update_that_is_not_a_stale_hash_says_what_the_door_said_and_writes_no_beside_file(tiroir, scratch, capsys):
    """A text the door refuses for its size: the tiroir's hash is still the latest, so there is no text to leave beside."""
    run(capsys, scratch)
    scratch.write_text(TEXT + "x" * (1024 * 1024), encoding="utf-8")
    code, out, err = run(capsys, scratch)
    assert code == 1 and out == ""
    assert not scratch.with_name("notes.tiroir.md").exists()
    assert err.strip()


def test_a_second_refusal_before_the_merge_keeps_the_tiroirs_latest_text(tiroir, scratch, capsys):
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    changed_there(tiroir, address, TEXT + "\nOne.\n")
    scratch.write_text(TEXT + "\nMine.\n", encoding="utf-8")
    run(capsys, scratch)
    changed_there(tiroir, address, TEXT + "\nOne.\n\nTwo.\n")
    assert run(capsys, scratch)[0] == 1
    assert scratch.with_name("notes.tiroir.md").read_text(encoding="utf-8") == TEXT + "\nOne.\n"          # never overwritten
    assert scratch.with_name("notes.tiroir-2.md").read_text(encoding="utf-8") == TEXT + "\nOne.\n\nTwo.\n"


# ── the state file, held by more than one sheaf at once ──────────────────────

def test_two_keeps_of_a_row_at_once_both_stay(tmp_path):
    one, two = tmp_path / "one.md", tmp_path / "two.md"
    row = lambda name: {"tiroir": FRONT, "doc": name, "hash": "h", "local": "l"}  # noqa: E731
    write_state, other = send.write_state, []

    def slow_write(data):
        if not other:                                       # the first keep is between its read and its write
            other.append(threading.Thread(target=send.keep_row, args=(two, row("two.md"))))
            other[0].start()
            other[0].join(0.5)                              # the second keep gets its turn, if the state file lets it
        write_state(data)
    send.write_state = slow_write
    try:
        send.keep_row(one, row("one.md"))
    finally:
        send.write_state = write_state
    other[0].join(10)
    assert sorted(v["doc"] for v in send.read_state().values()) == ["one.md", "two.md"]


# ── sheaf pull ───────────────────────────────────────────────────────────────

def test_pull_writes_the_tiroirs_latest_text_into_the_file(tiroir, scratch, capsys):
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    theirs = TEXT + "\nAdded on the tiroir.\n"
    changed_there(tiroir, address, theirs)
    code, out, err = run(capsys, "pull", scratch)
    assert code == 0, err
    assert scratch.read_text(encoding="utf-8") == theirs
    scratch.write_text(theirs + "\nAnd then here.\n", encoding="utf-8")       # the pull recorded the hash it read
    assert run(capsys, scratch)[0] == 0


def test_pull_never_overwrites_an_edit_made_here_and_leaves_the_tiroirs_text_beside_it(tiroir, scratch, capsys):
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    theirs = TEXT + "\nAdded on the tiroir.\n"
    changed_there(tiroir, address, theirs)
    mine = TEXT + "\nAdded here.\n"
    scratch.write_text(mine, encoding="utf-8")
    code, out, err = run(capsys, "pull", scratch)
    assert code == 1
    assert scratch.read_text(encoding="utf-8") == mine
    assert scratch.with_name("notes.tiroir.md").read_text(encoding="utf-8") == theirs
    assert "merge" in err and "nothing was sent" not in err


def test_pull_never_overwrites_an_edit_made_while_it_asks_the_door(tiroir, scratch, capsys, monkeypatch):
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    theirs = TEXT + "\nAdded on the tiroir.\n"
    changed_there(tiroir, address, theirs)
    mine = TEXT + "\nTyped while the pull waited.\n"
    asked = send.post

    def post(url, bearer, message, headers):
        got = asked(url, bearer, message, headers)
        if message.get("params", {}).get("name") == "read":
            scratch.write_text(mine, encoding="utf-8")                  # the edit lands after the pull read the file, before it writes
        return got
    monkeypatch.setattr(send, "post", post)
    code, out, err = run(capsys, "pull", scratch)
    assert code == 1
    assert scratch.read_text(encoding="utf-8") == mine
    assert scratch.with_name("notes.tiroir.md").read_text(encoding="utf-8") == theirs


def test_pull_never_overwrites_an_edit_saved_while_it_writes_the_file(tiroir, scratch, capsys, monkeypatch):
    """185 BH: the edit lands after the pull compared the file, while the new text is written and synced."""
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    theirs = TEXT + "\nAdded on the tiroir.\n"
    changed_there(tiroir, address, theirs)
    mine = TEXT + "\nSaved while the pull wrote.\n"
    writes = send.write_text_atomic

    def write(path, text, *a, **k):
        if Path(path) == scratch and text == theirs:
            scratch.write_text(mine, encoding="utf-8")
        return writes(path, text, *a, **k)
    monkeypatch.setattr(send, "write_text_atomic", write)
    code, out, err = run(capsys, "pull", scratch)
    assert code == 1
    assert scratch.read_text(encoding="utf-8") == mine
    assert scratch.with_name("notes.tiroir.md").read_text(encoding="utf-8") == theirs
    assert not list(scratch.parent.glob(".notes.md.*sheaf-tmp"))


def test_pull_of_a_page_never_sent_from_here_says_so(tiroir, scratch, capsys):
    code, out, err = run(capsys, "pull", scratch)
    assert code == 1 and "sheaf" in err and "never" in err
    assert tiroir.seen == []


# ── --local, no credential, repo pages ───────────────────────────────────────

def test_local_renders_on_the_laptop_hub_and_asks_the_tiroir_nothing(tiroir, scratch, local, capsys):
    code, out, err = run(capsys, scratch, "--local")
    assert code == 0, err
    assert local == [str(scratch)] and tiroir.seen == []


def test_no_credential_renders_on_the_laptop_hub(tiroir, scratch, local, keyring, capsys):
    keyring.items.clear()
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    assert local == [str(scratch)] and tiroir.seen == []


def test_no_default_tiroir_renders_on_the_laptop_hub(tiroir, scratch, local, capsys):
    paths.config_file().unlink()
    assert run(capsys, scratch)[0] == 0
    assert local == [str(scratch)] and tiroir.seen == []


def test_a_laptop_with_no_keyring_renders_on_the_laptop_hub(tiroir, scratch, local, monkeypatch, capsys):
    def none():
        raise connect.ConnectError("no login keyring on this computer")
    monkeypatch.setattr(connect, "system_store", none)
    assert run(capsys, scratch)[0] == 0
    assert local == [str(scratch)] and tiroir.seen == []


def test_a_page_in_a_git_repo_is_not_uploaded(tiroir, tmp_path, local, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    page = repo / "plan.md"
    page.write_text(TEXT, encoding="utf-8")
    assert run(capsys, page)[0] == 0
    assert local == [str(page)] and tiroir.seen == []


def test_folder_and_keep_with_local_are_a_usage_error(tiroir, scratch, local, capsys):
    code, out, err = run(capsys, scratch, "--local", "--keep")
    assert code == 2 and local == [] and tiroir.seen == []


# ── a tiroir that refuses ────────────────────────────────────────────────────

def test_a_revoked_token_fails_loudly_and_renders_nothing_on_the_laptop(tiroir, scratch, local, keyring, capsys):
    keyring.set("sheaf", FRONT, "sheaf_mcp_" + "A" * 43)
    code, out, err = run(capsys, scratch)
    assert code == 1 and local == [] and out == ""
    assert "refused" in err and "sheaf connect" in err


# ── where the state lives, and what is never written ─────────────────────────

def test_the_state_is_in_the_clis_state_folder_and_nothing_is_written_beside_the_file(tiroir, scratch, capsys):
    before = sorted(p.name for p in scratch.parent.iterdir())
    run(capsys, scratch)
    assert sorted(p.name for p in scratch.parent.iterdir()) == before
    row = state()[str(scratch.resolve())]
    assert row["tiroir"] == FRONT
    assert row["doc"] == f"loose-bea/{loose.month()}/notes.md"
    assert row["hash"] == md_hash(TEXT)
    assert oct((paths.state_dir() / "sends.json").stat().st_mode & 0o777) == "0o600"


def test_the_token_is_in_no_file_of_the_state_folder_no_output_and_no_diagnostics_row(tiroir, scratch, capsys):
    code, out, err = run(capsys, scratch)
    scratch.write_text(TEXT + "\nMore.\n", encoding="utf-8")
    code2, out2, err2 = run(capsys, scratch)
    for text in (out, err, out2, err2):
        assert tiroir.token not in text
    for f in [*paths.state_dir().rglob("*"), *Path.home().rglob("*")]:
        if f.is_file():
            assert tiroir.token.encode() not in f.read_bytes(), f


# ── what every send declares ─────────────────────────────────────────────────

def test_every_send_declares_the_session_the_machine_and_the_remote_control_link(tiroir, scratch, monkeypatch, capsys):
    cfg = Path(os.environ["HOME"]) / "claude"
    (cfg / "sessions").mkdir(parents=True)
    (cfg / "sessions" / "1.json").write_text(json.dumps(
        {"pid": 1, "sessionId": SESSION, "remoteControlUrl": "https://claude.ai/code/session_01ABC"}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    monkeypatch.setattr(send, "machine", lambda: "laptop-bea")
    run(capsys, scratch)
    scratch.write_text(TEXT + "\nMore.\n", encoding="utf-8")
    assert run(capsys, scratch)[0] == 0
    writes = [h for _, h, m in tiroir.seen if m and m["method"] == "tools/call"]
    assert len(writes) == 2
    for h in writes:
        assert h["X-Sheaf-Session"] == SESSION and h["X-Sheaf-Host"] == "laptop-bea"
        assert h["X-Sheaf-Link"] == "https://claude.ai/code/session_01ABC"
    address = f"loose-bea/{loose.month()}/notes.md"
    got = tiroir.get(f"/_/writes?doc={address}")
    assert SESSION in json.dumps(got.json()) and "laptop-bea" in json.dumps(got.json())


def test_a_session_with_no_remote_control_declares_no_link_and_one_that_is_no_web_address_is_not_sent(tiroir, scratch, monkeypatch, capsys):
    cfg = Path(os.environ["HOME"]) / "claude"
    (cfg / "sessions").mkdir(parents=True)
    (cfg / "sessions" / "1.json").write_text(json.dumps(
        {"pid": 1, "sessionId": SESSION, "remoteControlUrl": "javascript:alert(1)"}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    run(capsys, scratch)
    (_, h, _), = [s for s in tiroir.seen if s[2] and s[2]["method"] == "tools/call"]
    assert "X-Sheaf-Link" not in h and h["X-Sheaf-Session"] == SESSION


def test_the_output_names_the_agent_that_ran_the_command(tiroir, scratch, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    code, out, err = run(capsys, scratch)
    assert out.splitlines()[1] == "on chat.example.com as Bea · Claude Code"


# ── two loose files with one name ────────────────────────────────────────────
def test_a_second_loose_file_with_the_same_name_is_refused_and_the_first_page_keeps_its_text(tiroir, scratch, tmp_path, capsys):
    run(capsys, scratch)
    other = tmp_path / "elsewhere" / scratch.name
    other.parent.mkdir()
    other.write_text("# Other\n\nA different page.\n", encoding="utf-8")
    code, out, err = run(capsys, other)
    assert code == 1 and out == ""
    assert "exists already" in err and scratch.name in err and "Rename" in err
    assert on_the_tiroir(tiroir, f"loose-bea/{loose.month()}/{scratch.name}") == TEXT


# ── a tiroir that cannot be reached, or refuses the token (SPEC 13) ──────────

class StandIn:
    """A tiroir on a local socket, reached by the CLI's own network code (only the address it dials is changed). `mode`
    is what it does to every request: `hang` (accepts, never answers), `500`, `403` or `401`; a closed port is a server that has been closed."""

    def __init__(self, mode):
        self.mode, self.requests, self.release = mode, [], threading.Event()
        stand = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                stand.requests.append(self.path)
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if stand.mode == "hang":
                    stand.release.wait(30)
                    return
                self.send_response(int(stand.mode))
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stand_in(tiroir, real_network, monkeypatch):
    """`stand(mode)` points the CLI's dial at a `StandIn`; the bearer and the address stay the tiroir's own."""
    made = []

    def stand(mode):
        s = StandIn(mode)
        made.append(s)

        class Dial(urllib.request.HTTPSHandler):
            def https_open(self, req):
                return self.do_open(lambda host, timeout=None, **kw: http.client.HTTPConnection("127.0.0.1", s.port, timeout=timeout), req)

        monkeypatch.setattr(connect, "_NO_REDIRECT", urllib.request.build_opener(connect._Refuse3xx, Dial))
        return s

    yield stand
    for s in made:
        s.close()


def children() -> list[str]:
    """The live child processes of this process: from /proc where there is one, else from ps (macOS)."""
    me = os.getpid()
    found = []
    if not Path("/proc").is_dir():
        ps = subprocess.Popen(["ps", "-A", "-o", "pid=,ppid=,stat="], stdout=subprocess.PIPE, text=True)
        out = ps.communicate()[0]
        for line in out.splitlines():
            pid, ppid, state = line.split()[:3]
            if int(ppid) == me and int(pid) != ps.pid and not state.startswith("Z"):      # ps is our child too
                found.append(pid)
        return found
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                stat = (p / "stat").read_text().rsplit(")", 1)[1].split()
            except (OSError, IndexError):
                continue
            if int(stat[1]) == me and stat[0] != "Z":
                found.append(p.name)
    return found


@pytest.fixture
def real_network(monkeypatch):
    """The CLI's own `post` and `get`, which the `tiroir` fixture replaced, and a short connect timeout."""
    monkeypatch.setattr(send, "post", ORIGINAL_POST)
    monkeypatch.setattr(send, "get", ORIGINAL_GET)
    monkeypatch.setattr(send, "CONNECT_TIMEOUT", 0.4)

    def refuse(*a, **kw):
        raise AssertionError("a test dialled the network without a stand-in: call stand(mode)")
    monkeypatch.setattr(connect._NO_REDIRECT, "open", refuse)


LOUD = "not on {host}: run sheaf {file} again when it is back"


@pytest.mark.parametrize("mode", ["hang", "500", "503"])
def test_a_tiroir_that_hangs_or_fails_leaves_the_page_on_the_laptop_hub_with_the_loud_line(mode, stand_in, scratch, local, capsys):
    stand_in(mode)
    before = children()
    code, out, err = run(capsys, scratch)
    assert code == 0 and local == [str(scratch)], (code, err)
    assert LOUD.format(host="chat.example.com", file=scratch) in err
    assert children() == before


def test_a_closed_port_falls_back_the_same_way(stand_in, scratch, local, capsys):
    stand_in("500").close()
    code, out, err = run(capsys, scratch)
    assert code == 0 and local == [str(scratch)]
    assert "not on chat.example.com" in err


def test_a_tiroir_that_hangs_is_given_up_on_within_the_connect_timeout(stand_in, scratch, local, capsys):
    stand_in("hang")
    began = time.monotonic()
    run(capsys, scratch)
    assert time.monotonic() - began < 3


def test_the_fallback_queues_nothing_and_writes_nothing_beside_the_file(stand_in, scratch, local, capsys):
    stand_in("500")
    before = sorted(p.name for p in scratch.parent.iterdir())
    run(capsys, scratch)
    assert sorted(p.name for p in scratch.parent.iterdir()) == before
    assert not (paths.state_dir() / "sends.json").exists()


@pytest.mark.parametrize("status", ["401", "403"])
def test_a_refused_token_fails_loudly_with_no_fallback(status, stand_in, scratch, local, capsys):
    stand_in(status)
    code, out, err = run(capsys, scratch)
    assert code == 1 and local == [] and out == ""
    assert "refused" in err and "sheaf connect" in err and "not on" not in err


def test_running_again_after_recovery_creates_the_page_that_never_arrived(tiroir, stand_in, scratch, local, capsys):
    stand_in("500")
    run(capsys, scratch)
    # the tiroir is back: the CLI's network is the in-memory tiroir again
    send.post, send.get = tiroir.calls
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    tools = [m["params"]["name"] for _, _, m in tiroir.seen if m and m["method"] == "tools/call"]
    assert tools == ["create"]


def test_running_again_after_recovery_updates_with_the_last_hash_when_the_page_had_arrived(tiroir, stand_in, scratch, local, monkeypatch, capsys):
    kept = send.post, send.get = tiroir.calls  # the tiroir answers the first run
    run(capsys, scratch)
    scratch.write_text(TEXT + "\nMore.\n", encoding="utf-8")
    stand_in("500")
    send.post, send.get = ORIGINAL_POST, ORIGINAL_GET  # the tiroir is gone: the CLI's own network, into the stand-in
    run(capsys, scratch)
    send.post, send.get = kept
    tiroir.seen.clear()
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    tools = [m["params"]["name"] for _, _, m in tiroir.seen if m and m["method"] == "tools/call"]
    assert tools == ["update"]
    assert local == [str(scratch)]  # the run that failed rendered here; this one did not
    assert on_the_tiroir(tiroir, f"loose-bea/{loose.month()}/notes.md") == TEXT + "\nMore.\n"


def test_a_page_changed_on_the_tiroir_while_it_was_away_is_refused_as_before(tiroir, stand_in, scratch, local, capsys):
    kept = send.post, send.get = tiroir.calls  # the tiroir answers the first run
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    scratch.write_text(TEXT + "\nMine.\n", encoding="utf-8")
    stand_in("500")
    send.post, send.get = ORIGINAL_POST, ORIGINAL_GET
    run(capsys, scratch)
    assert local == [str(scratch)] and on_the_tiroir(tiroir, address) == TEXT  # it stayed here, nothing reached the tiroir
    send.post, send.get = kept
    changed_there(tiroir, address, TEXT + "\nTheirs.\n")
    code, out, err = run(capsys, scratch)
    assert code == 1 and "changed on the shared Sheaf" in err
    assert on_the_tiroir(tiroir, address) == TEXT + "\nTheirs.\n"


def test_a_failure_after_the_write_was_sent_is_no_fallback_and_says_it_may_have_arrived(tiroir, scratch, local, capsys, monkeypatch):
    first = tiroir.calls[0]

    def dies_on_the_write(url, bearer, message, headers):
        if message.get("method") == "tools/call" and message["params"]["name"] == "create":
            raise send.Unreachable("cannot reach chat.example.com: reset")
        return first(url, bearer, message, headers)

    monkeypatch.setattr(send, "post", dies_on_the_write)
    code, out, err = run(capsys, scratch)
    assert code == 1 and local == [] and "may have reached" in err and "not on" not in err


def test_a_certificate_the_laptop_cannot_trust_is_no_outage_and_falls_back_nowhere(tiroir, real_network, scratch, local, capsys, monkeypatch):
    import ssl
    import urllib.error

    def untrusted(req, timeout=None):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))

    monkeypatch.setattr(connect._NO_REDIRECT, "open", untrusted)
    code, out, err = run(capsys, scratch)
    assert code == 1 and local == [] and "cannot trust" in err and "not on" not in err


@pytest.mark.parametrize("name, answer", [("create", {"hash": "h"}), ("create", ["x"]), ("update", {"doc": "r/a.md"}),
                                          ("read", {"hash": 3}), ("read", {"hash": "h"}),
                                          ("read", {"hash": "h", "text": None})])
def test_a_door_result_without_the_text_fields_the_caller_reads_is_a_send_error(name, answer):
    door = send.Door("https://t.example.com", "tok", {})
    door.started = True
    door._post = lambda message: (200, {"result": {"content": [{"text": json.dumps(answer)}]}}, {})
    with pytest.raises(send.SendError, match="no `"):
        door.tool(name, {})


@pytest.mark.parametrize("error", [
    lambda: urllib.error.URLError(ssl.SSLEOFError("EOF occurred in violation of protocol")),
    lambda: ConnectionResetError("reset by peer"),
    lambda: ssl.SSLError("SSLV3_ALERT_HANDSHAKE_FAILURE"),
])
def test_a_reset_or_a_failed_handshake_is_an_outage_not_an_untrusted_certificate(error, monkeypatch):
    def broken(req, timeout=None):
        raise error()

    monkeypatch.setattr(connect._NO_REDIRECT, "open", broken)
    with pytest.raises(send.Unreachable):
        send.get("https://chat.example.com/x", "t")


def test_a_certificate_that_fails_its_check_is_untrusted_whether_the_error_comes_wrapped_or_bare(monkeypatch):
    for error in (urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed")),
                  ssl.SSLCertVerificationError("certificate verify failed")):
        def broken(req, timeout=None, error=error):
            raise error

        monkeypatch.setattr(connect._NO_REDIRECT, "open", broken)
        with pytest.raises(send.SendError, match="cannot trust") as e:
            send.get("https://chat.example.com/x", "t")
        assert not isinstance(e.value, send.Unreachable)


# ── a conflict copy is never written over ────────────────────────────────────

def test_a_second_conflict_leaves_the_first_conflict_copy_as_it_is_and_writes_the_next_free_name(tiroir, scratch, capsys):
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    changed_there(tiroir, address, TEXT + "\nFirst.\n")
    scratch.write_text(TEXT + "\nMine.\n", encoding="utf-8")
    assert run(capsys, scratch)[0] == 1
    first = scratch.with_name("notes.tiroir.md")
    first.write_text("my merge, half done\n", encoding="utf-8")        # the person has begun editing the copy
    changed_there(tiroir, address, TEXT + "\nFirst.\n\nSecond.\n")
    code, out, err = run(capsys, scratch)
    assert code == 1
    assert first.read_text(encoding="utf-8") == "my merge, half done\n"
    second = scratch.with_name("notes.tiroir-2.md")
    assert second.read_text(encoding="utf-8") == TEXT + "\nFirst.\n\nSecond.\n"
    assert "notes.tiroir-2.md" in err


def test_a_conflict_whose_text_is_the_copy_already_there_reuses_that_copy(tiroir, scratch, capsys):
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    changed_there(tiroir, address, TEXT + "\nTheirs.\n")
    scratch.write_text(TEXT + "\nMine.\n", encoding="utf-8")
    scratch.with_name("notes.tiroir.md").write_text(TEXT + "\nTheirs.\n", encoding="utf-8")   # already there, same text
    code, out, err = run(capsys, scratch)
    assert code == 1 and "notes.tiroir.md" in err
    assert not scratch.with_name("notes.tiroir-2.md").exists()


def test_pull_leaves_an_existing_conflict_copy_as_it_is_too(tiroir, scratch, capsys):
    run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    scratch.write_text(TEXT + "\nMine.\n", encoding="utf-8")
    changed_there(tiroir, address, TEXT + "\nTheirs.\n")
    scratch.with_name("notes.tiroir.md").write_text("an unrelated file\n", encoding="utf-8")
    code, out, err = run(capsys, "pull", scratch)
    assert code == 1
    assert scratch.with_name("notes.tiroir.md").read_text(encoding="utf-8") == "an unrelated file\n"
    assert scratch.with_name("notes.tiroir-2.md").read_text(encoding="utf-8") == TEXT + "\nTheirs.\n"


# ── a page whose place in git cannot be told is not sent ─────────────────────

@pytest.mark.parametrize("stderr, said", [
    ("fatal: detected dubious ownership in repository at '/srv/x'\n", "dubious ownership"),
    ("fatal: unsafe repository ('/srv/x' is owned by someone else)\n", "unsafe repository"),
])
def test_a_git_that_refuses_the_folder_stops_the_send_and_names_why(tiroir, scratch, local, capsys, monkeypatch, stderr, said):
    monkeypatch.setattr(send, "_git_probe", lambda folder: subprocess.CompletedProcess([], 128, "", stderr))
    code, out, err = run(capsys, scratch)
    assert code == 1 and out == "" and local == [] and tiroir.seen == []
    assert said in err and "Nothing was sent" in err


def test_a_git_that_does_not_run_stops_the_send(tiroir, scratch, local, capsys, monkeypatch):
    def none(folder):
        raise OSError("no git here")
    monkeypatch.setattr(send, "_git_probe", none)
    code, out, err = run(capsys, scratch)
    assert code == 1 and local == [] and tiroir.seen == []
    assert "no git here" in err and "Nothing was sent" in err


def test_a_folder_git_says_is_no_repository_is_a_loose_page_and_is_sent(tiroir, scratch, capsys):
    code, out, err = run(capsys, scratch)
    assert code == 0, err
    assert [m for _, _, m in tiroir.seen if m and m["method"] == "tools/call"]


# ── a write that may have arrived ────────────────────────────────────────────

def test_a_failure_after_the_write_does_not_say_nothing_was_sent(tiroir, scratch, local, capsys, monkeypatch):
    first = tiroir.calls[0]

    def dies_on_the_write(url, bearer, message, headers):
        if message.get("method") == "tools/call" and message["params"]["name"] == "create":
            raise send.Unreachable("cannot reach chat.example.com: reset. Nothing was sent.")   # as `_request` words it
        return first(url, bearer, message, headers)

    monkeypatch.setattr(send, "post", dies_on_the_write)
    code, out, err = run(capsys, scratch)
    assert code == 1 and "Nothing was sent" not in err
    assert "not known" in err and "may have reached" in err


def test_a_retried_create_of_a_page_that_did_arrive_takes_it_up_instead_of_the_name_collision(tiroir, scratch, local, capsys, monkeypatch):
    first = tiroir.calls[0]

    def dies_after_the_write(url, bearer, message, headers):
        got = first(url, bearer, message, headers)
        if message.get("method") == "tools/call" and message["params"]["name"] == "create":
            raise send.Unreachable("cannot reach chat.example.com: reset")
        return got

    monkeypatch.setattr(send, "post", dies_after_the_write)
    assert run(capsys, scratch)[0] == 1
    monkeypatch.setattr(send, "post", first)
    code, out, err = run(capsys, scratch)
    address = f"loose-bea/{loose.month()}/notes.md"
    assert code == 0, err
    assert on_the_tiroir(tiroir, address) == TEXT
    assert state()[str(scratch.resolve())]["doc"] == address
    scratch.write_text(TEXT + "\nNext.\n", encoding="utf-8")
    assert run(capsys, scratch)[0] == 0                                  # the next run updates it
    assert on_the_tiroir(tiroir, address) == TEXT + "\nNext.\n"


def test_a_retried_create_of_another_page_with_that_name_is_still_refused(tiroir, scratch, tmp_path, capsys):
    run(capsys, scratch)
    other = tmp_path / "elsewhere" / scratch.name
    other.parent.mkdir()
    other.write_text("# Other\n\nA different page.\n", encoding="utf-8")
    code, out, err = run(capsys, other)
    assert code == 1 and "exists already" in err
    assert str(other.resolve()) not in state()
