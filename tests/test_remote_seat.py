"""`sheaf open` on a machine reached over ssh with no display (SPEC 9.6, 13): the browser is on
the person's own machine, where 127.0.0.1 is that machine, so the command prints the tunnel to
run there instead of starting a browser here."""
import getpass
import http.client
import re
import socket

import pytest

from helpers import PLAN
from sheafmd import paths, seat

SSH = "192.0.2.10 51234 198.51.100.20 22"


@pytest.fixture
def browser(monkeypatch):
    opened = []
    monkeypatch.setattr("sheafmd.cli.webbrowser.open", lambda url, *a, **k: opened.append(url) or True)
    return opened


@pytest.fixture
def doc(work):
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    return f


@pytest.fixture
def over_ssh(monkeypatch):
    for var in seat.BROWSER_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SSH_CONNECTION", SSH)


# ── which seat ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("env", [
    {"SSH_CONNECTION": SSH},
    {"SSH_CLIENT": "192.0.2.10 51234 22"},
    {"SSH_TTY": "/dev/pts/0"},
    {"SSH_CONNECTION": SSH, "DISPLAY": ""},              # set but empty is not set
])
def test_ssh_with_no_display_is_a_remote_seat(env):
    assert seat.remote(env) is not None


@pytest.mark.parametrize("env", [
    {},                                                  # a local console, or macOS with no DISPLAY
    {"DISPLAY": ":0"},
    {"SSH_CONNECTION": SSH, "DISPLAY": "localhost:10.0"},  # ssh -X: a browser started here shows there
    {"SSH_CONNECTION": SSH, "WAYLAND_DISPLAY": "wayland-0"},
    {"SSH_CONNECTION": SSH, "BROWSER": "/srv/.vscode-server/bin/x/helpers/browser.sh"},
])
def test_a_display_a_named_browser_or_no_ssh_keeps_the_browser(env):
    assert seat.remote(env) is None


def test_the_tunnel_names_the_login_the_address_the_person_used_and_the_hub_port():
    s = seat.remote({"SSH_CONNECTION": SSH})
    assert s.tunnel(27419) == f"ssh -N -L 27419:127.0.0.1:27419 {getpass.getuser()}@198.51.100.20"


def test_an_ssh_port_that_is_not_22_is_named():
    s = seat.remote({"SSH_CONNECTION": "192.0.2.11 40000 203.0.113.9 2222"})
    assert s.tunnel(27500) == f"ssh -N -L 27500:127.0.0.1:27500 -p 2222 {getpass.getuser()}@203.0.113.9"


def test_without_the_server_address_the_host_name_stands_in():
    s = seat.remote({"SSH_TTY": "/dev/pts/3"})
    assert s.tunnel(27419) == f"ssh -N -L 27419:127.0.0.1:27419 {getpass.getuser()}@{socket.gethostname()}"


def test_with_only_ssh_client_its_server_port_is_kept():
    s = seat.remote({"SSH_CLIENT": "192.0.2.10 51234 2222"})
    assert s.tunnel(27419) == f"ssh -N -L 27419:127.0.0.1:27419 -p 2222 {getpass.getuser()}@{socket.gethostname()}"


def test_a_server_address_that_is_no_address_is_not_printed():
    s = seat.remote({"SSH_CONNECTION": "a b $(reboot) 22"})
    assert "$(" not in s.tunnel(27419) and s.tunnel(27419).endswith(f"@{socket.gethostname()}")


# ── sheaf open ───────────────────────────────────────────────────────────────

def test_open_over_ssh_prints_the_tunnel_and_starts_no_browser(sheaf, browser, doc, port, over_ssh):
    r = sheaf("open", doc)
    assert r.code == 0, r.err
    url = f"http://127.0.0.1:{port}/work/plan.md"
    out = r.out.splitlines()
    assert out[-1] == f"  ~ {url}"                                    # the URL is the last line (13)
    said = "\n".join(out[:-1]) + r.err
    assert "this machine is reached over ssh" in said
    assert f"ssh -N -L {port}:127.0.0.1:{port} {getpass.getuser()}@198.51.100.20" in said
    assert "sheaf signin-url" in said
    assert browser == []
    key = paths.key_file().read_text().strip()
    assert key not in r.out + r.err and "nonce=" not in r.out + r.err


def test_no_127_url_is_printed_without_the_tunnel(sheaf, browser, doc, port, over_ssh):
    r = sheaf("open", doc)
    text = r.out + r.err
    for m in re.finditer(r"http://127\.0\.0\.1:\d+", text):
        before = text[:m.start()]
        assert f"-L {port}:127.0.0.1:{port}" in before, text


def test_a_page_url_over_ssh_prints_the_tunnel_too(sheaf, browser, doc, port, over_ssh):
    sheaf("open", doc)
    r = sheaf("open", f"http://127.0.0.1:{port}/work/plan.md")
    assert r.code == 0, r.err
    assert f"-L {port}:127.0.0.1:{port}" in r.out + r.err and browser == []


def test_ssh_with_a_display_opens_the_browser_as_before(sheaf, browser, doc, port, monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", SSH)
    monkeypatch.setenv("DISPLAY", "localhost:10.0")
    r = sheaf("open", doc)
    assert r.code == 0 and len(browser) == 1 and "reached over ssh" not in r.out + r.err


def test_no_browser_over_ssh_still_says_how_to_reach_it(sheaf, browser, doc, port, over_ssh):
    r = sheaf("open", doc, "--no-browser")
    assert r.code == 0 and f"-L {port}:127.0.0.1:{port}" in r.out + r.err and browser == []


def test_a_page_already_open_in_a_tab_gets_no_tunnel_warning(sheaf, browser, doc, port, monkeypatch):
    sheaf("open", doc)                                           # signed in from here, as through a tunnel
    resp, _ = _get(port, browser[0].split(str(port), 1)[1])
    jar = resp.getheader("Set-Cookie").split(";")[0]
    tab = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    tab.request("GET", "/_/live?doc=work/plan.md", headers={"Cookie": jar})
    stream = tab.getresponse()
    stream.fp.readline()
    for var in seat.BROWSER_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SSH_CONNECTION", SSH)
    r = sheaf("open", doc)
    tab.close()
    assert r.out.splitlines()[-2:] == ["  (already open in 1 tab)", f"  ~ http://127.0.0.1:{port}/work/plan.md"]
    assert "reached over ssh" not in r.out + r.err and len(browser) == 1


def _get(port, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path)
    r = c.getresponse()
    r.read()
    return r, c
