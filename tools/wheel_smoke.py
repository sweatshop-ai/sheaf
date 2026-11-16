#!/usr/bin/env python3
"""Build the wheel and use it the way a new user does: `uv tool install`, `sheaf version`,
`sheaf FILE --share`, `sheaf init cursor`, a hub started and stopped from the installed tool.

It touches nothing of the person who runs it, except the macOS runtime folder (below). Everything goes into one temporary folder: the tool
environment (UV_TOOL_DIR, UV_TOOL_BIN_DIR), HOME and the XDG folders (the runtime one included on
Linux), SHEAF_HOME, and a hub port of its own. Only uv's download cache and managed Pythons are
shared, so nothing is fetched twice. On macOS the runtime folder is the exception: sheaf ignores
XDG_RUNTIME_DIR there and uses /tmp/sheaf-<uid>, so a hand run on a Mac shares that folder with the
person's own sheaf (ci.yml's macOS job, a manual dispatch, runs on a fresh runner, where that does no
harm). The run says so when it starts.
Nothing is published and no tag is made. Used by hand and by ci.yml:

    python3 tools/wheel_smoke.py [--keep]        # --keep leaves the folder, and says where

Exit 0 when every check holds."""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))
import _ci  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def agent_env_prefixes() -> tuple:
    """What an agent run by the person would add to the environment, none of which may reach the hub.
    Read from the source of hub/client.py, not imported: importing sheafmd needs the project's
    dependencies, and a hand run of this script needs only uv."""
    tree = ast.parse((ROOT / "src/sheafmd/hub/client.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_AGENT_ENV_PREFIXES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("_AGENT_ENV_PREFIXES is not in hub/client.py")


_AGENT_ENV_PREFIXES = agent_env_prefixes()
PACKAGED = [
    "sheafmd/page/page.js", "sheafmd/page/page.css", "sheafmd/page/index.js", "sheafmd/page/index.css",
    "sheafmd/themes/plain/theme.css", "sheafmd/themes/plain/theme.toml",
    "sheafmd/agent_files/claude-skill.md", "sheafmd/agent_files/agents-snippet.md",
]


def runtime_note(platform: str) -> str | None:
    """What the run cannot isolate, or None when it isolates everything."""
    if platform == "darwin":
        return (f"the runtime folder is shared: macOS ignores XDG_RUNTIME_DIR, so sheaf uses "
                f"/tmp/sheaf-{os.getuid()}, the one of your own sheaf")
    return None


def uv_dir(uv: str, *what: str) -> str:
    return subprocess.run([uv, *what, "dir"], capture_output=True, text=True, check=True).stdout.strip()


def clean_env(uv: str, work: Path, port: int) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(_AGENT_ENV_PREFIXES)}
    home = work / "home"
    home.mkdir()
    env.update({
        "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"), "XDG_CACHE_HOME": str(home / ".cache"),
        "UV_TOOL_DIR": str(work / "tools"), "UV_TOOL_BIN_DIR": str(work / "bin"),
        "SHEAF_HOME": str(work / "sheaf-home"), "SHEAF_PORT": str(port), "SHEAF_NAME": "Ada",
        "PATH": f"{work / 'bin'}{os.pathsep}{os.environ['PATH']}",
    })
    # Its own runtime folder: without the variable sheaf falls back to /tmp/sheaf-<uid>, the real one
    # (macOS ignores the variable and always uses that fallback: paths.runtime_dir).
    runtime = work / "run"
    runtime.mkdir()
    runtime.chmod(0o700)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env.setdefault("UV_CACHE_DIR", uv_dir(uv, "cache"))
    env.setdefault("UV_PYTHON_INSTALL_DIR", uv_dir(uv, "python"))
    return env


def check_wheel(wheel: Path):
    with zipfile.ZipFile(wheel) as z:
        names = set(z.namelist())
        missing = [n for n in PACKAGED if n not in names]
        _ci.check(not missing, "the wheel holds the page files, the theme and the agent files", str(missing))
        meta = next(n for n in names if n.endswith(".dist-info/METADATA"))
        text = z.read(meta).decode("utf-8")
        _ci.check("Name: sheafmd" in text and "Requires-Dist: pypandoc-binary==1.17" in text,
                  "the metadata names sheafmd and pins pandoc")
        entry = next(n for n in names if n.endswith(".dist-info/entry_points.txt"))
        _ci.check("sheaf = sheafmd.cli:main" in z.read(entry).decode("utf-8"), "the command `sheaf` is declared")
        return z.read("sheafmd/page/page.js").decode("utf-8")


def main(argv: list[str]) -> int:
    uv = shutil.which("uv")
    if not uv:
        _ci.fail("uv is not on PATH")
    work = Path(tempfile.mkdtemp(prefix="sheaf-wheel-smoke-"))
    port = _ci.free_port()
    try:
        env = clean_env(uv, work, port)
        run = lambda argv, **kw: _ci.sh(argv, env=env, **kw)  # noqa: E731
        _ci.say(f"folder: {work}")
        if note := runtime_note(sys.platform):
            _ci.say(f"note: {note}")

        _ci.say("1. build")
        dist = work / "dist"
        done = subprocess.run([uv, "build", "--wheel", "--out-dir", str(dist)], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=600)
        _ci.check(done.returncode == 0, "uv build --wheel", done.stderr[-800:])
        wheels = sorted(dist.glob("sheafmd-*.whl"))
        _ci.check(len(wheels) == 1, f"one wheel: {[w.name for w in wheels]}")
        wheel = wheels[0]
        version = wheel.name.split("-")[1]
        page_js = check_wheel(wheel)

        _ci.say("2. uv tool install")
        done = run([uv, "tool", "install", str(wheel)], timeout=600)
        _ci.check(done.returncode == 0, "uv tool install <wheel>")
        sheaf = work / "bin" / "sheaf"
        _ci.check(sheaf.is_file(), "the command is in UV_TOOL_BIN_DIR")
        done = run(["sheaf", "version"])
        _ci.check(done.stdout.strip() == f"sheaf {version}", f"sheaf version says {version}", done.stdout)

        _ci.say("3. sheaf FILE --share")
        doc = work / "doc.md"
        doc.write_text("# Smoke\n\nA paragraph with **bold** text.\n", encoding="utf-8")
        done = run(["sheaf", str(doc), "--share"])
        shared = work / "doc-share.html"
        _ci.check(done.returncode == 0 and shared.is_file(), "the share copy is written")
        html = shared.read_text(encoding="utf-8")
        _ci.check("<h1" in html and "Smoke" in html and "<style" in html and "<script" not in html,
                  "it is one page with the plain theme's style and no script")

        _ci.say("4. the page the hub serves")
        py = work / "tools" / "sheafmd" / "bin" / "python"
        done = _ci.quiet([str(py), "-I", "-c",
                          "import sys, sheafmd; sys.stdout.write(sheafmd.render(sys.argv[1], share=False))",
                          str(doc)], timeout=120, env=env)
        page = done.stdout
        _ci.check(done.returncode == 0 and page_js in page, "the installed package serves the page with its script")

        _ci.say("5. sheaf init cursor, under the folder's own HOME")
        done = run(["sheaf", "init", "cursor"])
        config = work / "home" / ".cursor" / "mcp.json"
        _ci.check(done.returncode == 0 and config.is_file(), "init cursor wrote ~/.cursor/mcp.json under the folder")
        server = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["sheaf"]
        _ci.check(server["command"] == str(sheaf) and server["args"] == ["mcp", "--agent", "cursor"],
                  "it registers the installed command, absolute", str(server))

        _ci.say("6. the hub, from the installed tool")
        try:
            _ci.check(run(["sheaf", "start"]).returncode == 0, "sheaf start")
            done = run(["sheaf", "status"])
            _ci.check(done.returncode == 0 and f"version  {version}" in done.stdout, "the hub runs the installed version")
        finally:
            run(["sheaf", "stop"])
        _ci.check(_ci.wait_until(lambda: run(["sheaf", "status"]).returncode != 0, seconds=15, every=0.5),
                  "sheaf stop: no hub is left")
    finally:
        if "--keep" in argv:
            _ci.say(f"kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    _ci.say("wheel smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
