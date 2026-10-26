"""What the two service checks share. CI only: see `guard`."""
import json
import os
import socket
import subprocess
import sys
import time


def guard(system: str):
    """Refuse unless this is a GitHub Actions runner of `system` ('Linux' or 'macOS'). The checks
    install a real user service; a laptop has its own hub and units, so a stray GITHUB_ACTIONS
    alone is not enough: the runner sets RUNNER_OS too."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != system:
        script = os.path.basename(sys.argv[0])
        sys.stderr.write(f"{script}: refuses to run. It installs a real user service, so it is for "
                         f"a GitHub Actions {system} runner only (GITHUB_ACTIONS=true and "
                         f"RUNNER_OS={system}).\n")
        sys.exit(2)


def say(text: str = ""):
    print(text, flush=True)


def notice(text: str):
    say(f"::notice::{text}")


def fail(text: str):
    say(f"::error::{text}")
    sys.exit(1)


def check(ok, what: str, detail: str = ""):
    if ok:
        say(f"  ok    {what}")
    else:
        fail(f"{what}" + (f": {detail}" if detail else ""))


def sh(argv: list[str], *, timeout: int = 60, env: dict | None = None) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env,
                          stdin=subprocess.DEVNULL)
    say(f"  $ {' '.join(argv)}  -> {done.returncode}")
    for stream in (done.stdout, done.stderr):
        for line in stream.strip().splitlines()[:12]:
            say(f"    {line}")
    return done


def quiet(argv: list[str], *, timeout: int = 30, env: dict | None = None) -> subprocess.CompletedProcess:
    """The same as `sh`, without printing: for what is polled."""
    return subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout,
                          env=env)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(look, *, seconds: float, every: float = 0.5):
    """The first truthy value `look()` returns within `seconds`, else None."""
    end = time.monotonic() + seconds
    while True:
        got = look()
        if got:
            return got
        if time.monotonic() >= end:
            return None
        time.sleep(every)


def parse_show(text: str) -> dict:
    """`systemctl show` prints Key=Value lines."""
    out = {}
    for line in text.splitlines():
        key, eq, value = line.partition("=")
        if eq and key:
            out[key] = value
    return out


def has_row(diag_json: str, kind: str, **fields) -> bool:
    return any(r.get("kind") == kind and all(r.get(k) == v for k, v in fields.items())
               for r in json.loads(diag_json))


def hub_answers() -> bool:
    return quiet(["sheaf", "status"]).returncode == 0


def diag() -> str:
    return quiet(["sheaf", "diag", "--json"]).stdout or "[]"


def upgrade_command() -> subprocess.CompletedProcess:
    """What a NEWER sheaf does when it meets the running hub: `ensure_hub`, the rule of SPEC 8.4.
    The version is patched before the package is used, as tests/test_hub_upgrade.py does, so no
    second install is needed. (`sheaf start` would not do: with the service installed it only asks
    the service to start.) The hub that comes back is the installed code, which is not newer, so
    ensure_hub ends by saying it did not meet the new version; that is printed, not a failure."""
    code = ("import sheafmd; sheafmd.__version__ = '99.0.0'\n"
            "from sheafmd.hub import client\n"
            "try:\n"
            "    client.ensure_hub('cli', print, print)\n"
            "except Exception as e:\n"
            "    print(f'ensure_hub: {type(e).__name__}: {e}')\n")
    return sh([sys.executable, "-c", code], timeout=60)
