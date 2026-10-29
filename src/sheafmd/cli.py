"""
sheafmd.cli — the `sheaf` command (SPEC 13).

    sheaf FILE.md [render options]              open the page of a document (the hub)
    sheaf FILE.md --share [--out PATH] [--pdf [PATH]] [--open]

--share writes the share copy of a document next to it: one self-contained HTML file with
every comment removed and no script. The commands that read or change the comments of
a file (comments, comment, reply, resolve, reopen), `diag` and `version` need no hub
either; `open`, `start`, `stop` and `status` talk to it. Exit codes: 0 done, 1 failed,
2 usage error.

The first argument is a file when it ends in `.md` or names an existing path;
otherwise it is a subcommand looked up in COMMANDS. Each subcommand is a function
`(argv) -> exit code`, registered in COMMANDS and given its usage line in COMMAND_HELP at
the foot of the commands section.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, agent_setup, comments, config, diagnostics, lifecycle, mcp, paths, pdf, seat, theme
from .agents.detect import detect
from .agents.registry import detect_target
from .atomic import write_text_atomic
from .hub import client as hubclient
from .hub import roots as hubroots
from .hub import server as hubserver
from .hub.auth import clean_display
from .hub.roots import url_path
from .hub.state import TokenError, Tokens
from .render import RenderError, UnclosedComment, render_file
from .source import StaleError, Source, now, update_file

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

# name -> function(argv) -> exit code, and name -> (usage line, what it does) for --help.
COMMANDS: dict = {}
COMMAND_HELP: dict = {}

TOP_HELP = """\
sheaf: a working page for a markdown document, shared between a person and their agent.

usage:
  sheaf FILE.md [render options]
                 open the page of a document in your browser (starts the hub if none runs)
  sheaf FILE.md --share [--out PATH] [--pdf [PATH]] [--open] [render options]

  --share        write the share copy, <stem>-share.html next to the .md: one
                 self-contained file, every comment removed, no script. Needs no hub.
  --out PATH     write it there instead
  --pdf [PATH]   also print it to PDF with Chrome or Chromium, <stem>-share.pdf
  --open         open the written file in the browser

render options:
  --title TEXT, --toc always|auto|never, --max-image-width N, --by NAME, --for NAME,
  --theme NAME|PATH, --credit

Exit codes: 0 done, 1 failed, 2 usage error.
"""


def top_help() -> str:
    """TOP_HELP, then every registered command with its one line."""
    out = [TOP_HELP.rstrip("\n")]
    if COMMAND_HELP:
        out += ["", "commands:"]
        for usage, what in COMMAND_HELP.values():
            out += [f"  sheaf {usage}", f"      {what}"]
    return "\n".join(out)


def _out(line: str = ""):
    print(line)


def _err(line: str = ""):
    print(line, file=sys.stderr)


def print_log(log: list[str]):
    """The render log as it always was: "+" added and "-" removed on stdout, and every
    "!" warning on stderr, where a pipe does not swallow it."""
    for line in log:
        (_err if line.lstrip().startswith("!") else _out)(line)


def _positive(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number above zero")
    return n


def add_render_options(p: argparse.ArgumentParser):
    g = p.add_argument_group("render options")
    g.add_argument("--title", help="the page title (default: the first heading, else the file name)")
    g.add_argument("--toc", choices=["always", "auto", "never"], default="auto",
                   help="the table of contents; auto shows it from 6 headings")
    g.add_argument("--max-image-width", type=_positive, default=1400, metavar="N",
                   help="embedded images wider than N pixels are downscaled (default 1400)")
    g.add_argument("--by", help="who prepared the document (default: your name from config)")
    g.add_argument("--for", dest="for_", metavar="NAME",
                   help="who it is prepared for (default: `for` in .sheaf.toml; an empty NAME leaves it out)")
    g.add_argument("--theme", metavar="NAME|PATH",
                   help="a built-in theme name or a theme folder (default: .sheaf.toml, else plain)")
    g.add_argument("--credit", action="store_true", default=None,
                   help="end the page with a 'Made with sheaf' line")


def file_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sheaf", usage="sheaf FILE.md --share [--out PATH] [--pdf [PATH]] [--open]",
        description="Write the share copy of a markdown document: one self-contained HTML "
                    "file, every comment removed, no script.")
    p.add_argument("file", metavar="FILE.md")
    p.add_argument("--share", action="store_true", help="write the share copy")
    p.add_argument("--out", metavar="PATH", help="write the share copy there "
                   "(default: <stem>-share.html next to the .md)")
    p.add_argument("--pdf", nargs="?", const=True, default=None, metavar="PATH",
                   help="also print it to PDF with Chrome or Chromium (default: <stem>-share.pdf, "
                        "or the --out name with .pdf)")
    p.add_argument("--open", dest="open_it", action="store_true",
                   help="open the written file in the browser (nothing opens otherwise)")
    p.add_argument("--no-browser", action="store_true", help="never open a browser window")
    p.add_argument("--browser", action="store_true",
                   help="the default: --open may open a browser (config.toml and SHEAF_NO_BROWSER "
                        "still switch it off)")
    p.add_argument("--agent", metavar="NAME|none",
                   help="accepted for the options sheaf FILE takes; a share copy has no session to attach to")
    p.add_argument("--session", metavar="ID", help="accepted like --agent; it has no effect here")
    add_render_options(p)
    return p


def _theme_spec(spec: str | None) -> str | None:
    """A --theme that names a folder on disk is taken relative to where the command
    runs, not to the root; a built-in name stays a name. A path that cannot be looked
    at (a folder on the way may not be entered) goes on as the absolute path it is
    here, so that load_theme says why there and never tries it in the root."""
    if not spec:
        return spec
    if os.path.isfile(theme.BUILTIN / spec / "theme.toml"):      # a built-in is in the package
        return spec
    try:
        p = Path(spec).expanduser()
    except RuntimeError:                  # "~nobody/x" with no such user: leave it for load_theme
        return spec
    try:
        there = paths.exists(p)
    except OSError:
        return os.path.abspath(p)
    return str(p.resolve()) if there else spec


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve() or (b.exists() and a.samefile(b))
    except OSError:
        return False


def _share_rule(md: Path):
    """In proxy mode a share copy holds the image rule that the hub's own copies hold (9.9 "Local
    images"): None in loopback mode, where every local image is embedded (6.2)."""
    from .hub import proxy, roots
    return roots.image_rule(md) if proxy.configured() else None


def cmd_share(args) -> int:
    md = Path(args.file)
    if not md.is_file():
        _err(f"sheaf: {md}: no such file")
        return EXIT_FAILED
    out = Path(args.out) if args.out else md.with_name(md.stem + "-share.html")
    if _same_file(out, md):
        _err(f"sheaf: {out} is the document itself; --out must name a new file")
        return EXIT_USAGE
    pdf_out = None
    if args.pdf:
        pdf_out = (Path(args.pdf) if args.pdf is not True else
                   out.with_suffix(".pdf") if args.out else md.with_name(md.stem + "-share.pdf"))
        if _same_file(pdf_out, md) or _same_file(pdf_out, out):
            _err(f"sheaf: {pdf_out} would overwrite the document or its share copy")
            return EXIT_USAGE

    log: list[str] = []
    try:
        page = render_file(
            md, share=True, theme=_theme_spec(args.theme), title=args.title, toc=args.toc,
            max_image_width=args.max_image_width, by=args.by, for_=args.for_, credit=args.credit,
            log=log, warn=_err, image_ok=_share_rule(md))
    except (config.ConfigError, RenderError) as e:
        print_log(log)
        _err(f"sheaf: {md}: {e}" if isinstance(e, UnclosedComment) else f"sheaf: {e}")
        return EXIT_FAILED
    except UnicodeDecodeError:
        print_log(log)
        _err(f"sheaf: {md}: is not UTF-8 text")
        return EXIT_FAILED
    except subprocess.CalledProcessError as e:
        print_log(log)
        _err(f"sheaf: {md}: pandoc could not read it: {(e.stderr or '').strip()[:300]}")
        return EXIT_FAILED
    except OSError as e:
        print_log(log)
        _err(f"sheaf: {e.filename or md}: {e.strerror or e}")
        return EXIT_FAILED
    print_log(log)
    try:
        write_text_atomic(out, page)
    except OSError as e:
        _err(f"sheaf: cannot write {out}: {e.strerror or e}")
        return EXIT_FAILED
    _out(f"  = {out}  ({out.stat().st_size // 1024} KB)")

    if pdf_out:
        try:
            pdf.write_pdf(page, pdf_out)
        except pdf.PdfError as e:
            _err(f"sheaf: PDF not written: {e}")
            _err(f"  the share copy is written: {out}")
            return EXIT_FAILED
        _out(f"  = {pdf_out}  ({pdf_out.stat().st_size // 1024} KB)")

    if args.open_it:
        if args.no_browser or not config.browser_enabled(_err):
            _out("  (not opened: the browser is off, by --no-browser, SHEAF_NO_BROWSER or config.toml)")
        elif not webbrowser.open(out.resolve().as_uri()):
            _err(f"  ! no browser could be opened; the file is {out}")
    return EXIT_OK


def cmd_file(argv: list[str]) -> int:
    """`sheaf FILE.md ...`: the share copy with --share, else the same as `sheaf open`."""
    p = file_parser()
    args = p.parse_args(argv)
    if args.share:
        return cmd_share(args)
    if args.out or args.pdf or args.open_it:
        p.error("--out, --pdf and --open go with --share")
    return _open(args)


# ── the hub: open, start, stop, status, hub ─────────────────────────────────

def open_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sheaf open", usage="sheaf open FILE.md|URL [--browser | --no-browser] [render options]",
        description="Open the page of a markdown document in your browser, starting the hub if "
                    "none runs. Given the URL of a page, signs this browser in to the hub again.")
    p.add_argument("file", metavar="FILE.md|URL")
    p.add_argument("--no-browser", action="store_true", help="print the URL and open nothing")
    p.add_argument("--browser", action="store_true",
                   help="the default (config.toml and SHEAF_NO_BROWSER still switch it off)")
    p.add_argument("--agent", metavar="NAME|none",
                   help="none forgets the agent session this page was attached to")
    p.add_argument("--session", metavar="ID",
                   help="attach the page to this session of the agent instead of the one that runs the command")
    add_render_options(p)
    return p


def _target(args) -> dict | None:
    """What this render tells the hub about the agent (SPEC 8.3, 11.5): the target detected in
    the environment, forced by `--agent`, with `--session` overriding the id; `{"agent":
    "none"}` forgets the one on record; None when no agent is here, which keeps it."""
    if args.agent == "none":
        return {"agent": "none"}
    t = detect_target(os.environ, args.agent, args.session)
    return t.as_dict() if t else None


def cmd_open(argv: list[str]) -> int:
    return _open(open_parser().parse_args(argv))


def _hub_failure(e: Exception) -> int:
    if isinstance(e, hubclient.Impostor):
        _err(f"  ! {e}")
    else:
        _err(f"sheaf: {e}")
    return EXIT_FAILED


def _open(args) -> int:
    """`sheaf open`: register the document with the hub (starting it if needed), record the
    settings, print the clean URL, and sign the browser in. The URL printed never holds the
    key, and neither does the one the browser is given: that holds a one-time nonce (SPEC 9.3)."""
    target = args.file
    url_arg = target.startswith(("http://", "https://"))
    md = None
    if url_arg:
        u = urlsplit(target)
        if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost") or not u.path.startswith("/"):
            _err(f"sheaf open: {target}: only the URL of a page on your own hub (127.0.0.1) can be opened")
            return EXIT_USAGE
        next_path = u.path + (f"?{u.query}" if u.query else "")
    else:
        md = Path(target)
        if not md.is_file():
            _err(f"sheaf: {md}: no such file")
            return EXIT_FAILED
        if md.suffix != ".md":
            _err(f"sheaf: {md}: only .md files are opened")
            return EXIT_FAILED
    try:
        c, _ = hubclient.ensure_hub("render", _out, _err)
        tabs = 0
        if md is not None:
            body = {"path": str(md.resolve()),
                    "settings": {"title": args.title, "toc": args.toc,
                                 "max_image_width": args.max_image_width, "by": args.by,
                                 "for": args.for_, "theme": _theme_spec(args.theme), "credit": args.credit},
                    "target": _target(args)}
            status, res = c.call("POST", "/_/render", body)
            if status != 200 or not res.get("ok"):
                _err(f"sheaf: {md}: {res.get('error') or f'the hub answered {status}'}")
                return EXIT_FAILED
            print_log(res.get("log", []))
            for w in res.get("warnings", []):
                _err(w)
            next_path, tabs = hubroots.url_path(res["doc"]), res.get("tabs", 0)
            shown = res["url"]
        else:
            shown = f"http://127.0.0.1:{c.port}{next_path}"
    except (hubclient.Impostor, hubclient.HubDidNotStart) as e:
        return _hub_failure(e)
    if tabs:
        _out(f"  (already open in {tabs} tab{'s' if tabs != 1 else ''})")
    # A browser here would not reach the hub, and none is there; an open tab already does.
    remote_seat = None if tabs else seat.remote(os.environ)
    if remote_seat is not None:
        _out("  ! this machine is reached over ssh: the URL below opens only through a tunnel. "
             "On your own machine run:")
        _out(f"      {remote_seat.tunnel(c.port)}")
        _out("    and open the URL there. The first time in that browser, run sheaf signin-url "
             "here and open what it prints")
    _out(f"  ~ {shown}")                    # the URL is the last line (SPEC 13)
    if remote_seat is None and not tabs and not args.no_browser and config.browser_enabled(_err):
        try:
            link = c.one_time_sign_in_url(next_path)
        except hubclient.SignInRefused as e:
            _err(f"  ! the browser was not opened: the hub gave no sign-in link ({e}). "
                 "Run sheaf signin-url and open what it prints yourself")
            return EXIT_OK
        except hubclient.Impostor as e:                  # replaced since the render, or silent: no key went to it
            return _hub_failure(e)
        if not webbrowser.open(link):
            _err("  ! no browser could be opened; open the URL above in a browser")
    return EXIT_OK


def cmd_start(argv: list[str]) -> int:
    _parser("start", "start", "Start the hub if it is not running.").parse_args(argv)
    through = lifecycle.via_service("start")        # with the service installed, it starts the hub
    if through is not None:
        return through
    try:
        c, started = hubclient.ensure_hub("cli", _out, _err)
    except (hubclient.Impostor, hubclient.HubDidNotStart) as e:
        return _hub_failure(e)
    info = hubserver.read_pid_file() or {}
    _out(f"  hub {'started' if started else 'running'} on 127.0.0.1:{c.port} (pid {info.get('pid', '?')})")
    return EXIT_OK


def _ended(pid: int) -> bool:
    """Whether the process `pid` has ended (see `hubclient.ended`)."""
    return hubclient.ended(pid)


def cmd_stop(argv: list[str]) -> int:
    _parser("stop", "stop", "Stop the hub. Documents are plain files; nothing is lost.").parse_args(argv)
    try:
        c = hubclient.client()
        recovered = False
        try:
            got = c.challenge()
        except hubclient.HubSilent as silent:
            # Stopped here, or asked of the service manager: either way what is left is the port.
            # (It raises a HubSilent that says why when it may not, and HubDidNotStart when nothing ended.)
            lifecycle.recover_silent_hub(c, silent, "stop")
            pid, recovered = None, True
        else:
            if got is None:
                _out("  no hub is running")
                return EXIT_OK
            info = hubserver.read_pid_file() or {}
            pid = info.get("pid") if info.get("boot") == got.get("boot") else None
            status, res = c.call("POST", "/_/stop", {"reason": "stop"})
            if status != 200 or not res.get("ok"):
                _err(f"sheaf: the hub refused to stop: {res.get('error') or status}")
                return EXIT_FAILED
        deadline = time.time() + hubclient.STOP_WAIT
        while time.time() < deadline:
            try:
                closed = c.challenge() is None
            except hubclient.Impostor:
                # After a stop the hub asked for, whatever answers is another process and the hub is
                # gone. After a recovery nothing was asked of the hub, so something that holds the
                # port and says nothing is still the port held: not closed.
                closed = not recovered
            if closed and (pid is None or _ended(pid)):
                break
            time.sleep(0.05)
        else:
            _err(f"sheaf: 127.0.0.1:{c.port} is still held after {hubclient.STOP_WAIT:g} s; see `sheaf diag`"
                 if recovered else f"sheaf: the hub is still running after {hubclient.STOP_WAIT:g} s")
            return EXIT_FAILED
    except (hubclient.Impostor, hubclient.HubDidNotStart) as e:
        return _hub_failure(e)
    _out("  hub stopped")
    return EXIT_OK


def cmd_status(argv: list[str]) -> int:
    _parser("status", "status", "Say whether the hub runs. Exit 0 when it does, 1 when it does not."
            ).parse_args(argv)
    try:
        got = hubclient.client().challenge()
    except hubclient.Impostor as e:
        return _hub_failure(e)
    if got is None:
        _out("  no hub is running")
        return EXIT_FAILED
    info = hubserver.read_pid_file() or {}
    if info.get("boot") != got.get("boot"):
        info = {}
    port = config.port()
    _out(f"  hub running on 127.0.0.1:{port}")
    _out(f"    version  {got.get('version')}")
    if info:
        _out(f"    pid      {info.get('pid')}")
        _out(f"    started  {info.get('started')}")
    _out(f"    service  {'yes' if got.get('service') else 'no'}")
    return EXIT_OK


def cmd_list(argv: list[str]) -> int:
    _parser("list", "list", "List the documents rendered since the hub started, and for each whether "
            "a tab has it open, had it open, or never did.").parse_args(argv)
    try:
        c = hubclient.client()
        if c.challenge() is None:
            _out("  no hub is running")
            return EXIT_OK
        status, res = c.call("GET", "/_/index.json?rendered=1")
    except hubclient.Impostor as e:
        return _hub_failure(e)
    if status != 200 or not res.get("ok"):
        _err(f"sheaf: the hub refused: {res.get('error') or status}")
        return EXIT_FAILED
    docs = [(r, d) for r in res["roots"] for d in r["docs"]]
    if not docs:
        _out("  nothing has been rendered since the hub started")
    for root, d in docs:
        _out(f"  {d['url']}")
        tabs, opened = d["tabs"], d["opened"]
        state = (f"{tabs} tab{'s' if tabs != 1 else ''} open" if tabs
                 else "opened, now closed" if opened else "never opened")
        _out(f"    {Path(root['path']) / hubroots.Address.parse(d['doc']).rel} · {state}")
    return EXIT_OK


def _forget_on_hub(c, name: str) -> tuple[bool, str | None]:
    """Ask the hub to forget the root `name`: (whether it took the request, the folder of the root
    it forgot, or None when it holds none by that name). Says why when it refused."""
    status, res = c.call("POST", "/_/forget", {"name": name})
    if status == 404:
        return True, None
    if status != 200 or not res.get("ok"):
        _err(f"sheaf: the hub refused: {res.get('error') or status}")
        return False, None
    return True, res.get("path")


def _forget_root(name: str) -> int:
    """Through the hub when one runs: it holds the roots in memory and would write its own copy
    back over ours. With none, the files it reads when it starts (`_forget_with_no_hub`)."""
    try:
        c = hubclient.client()
        if c.challenge() is None:
            return _forget_with_no_hub(c, name)
        took, path = _forget_on_hub(c, name)
    except hubclient.Impostor as e:
        return _hub_failure(e)
    return _hub_forgot(name, took, path)


def _hub_forgot(name: str, took: bool, path: str | None) -> int:
    """How a forget ends: `took`, whether it was done (a hub's refusal was said already), and `path`,
    the folder of the root forgotten, or None when no root has that name."""
    if not took:
        return EXIT_FAILED
    if path is None:
        _err(f"sheaf: no root is named {name} (sheaf roots lists them)")
        return EXIT_FAILED
    _forgot(name, path)
    return EXIT_OK


def _forget_with_no_hub(c, name: str) -> int:
    """Forget the root in the files, then ask the hub once more: one that started after the first
    look read the files before they were written (it binds its port before it reads them, so it
    listens by now) and is told too. The files are then forgotten twice, which is harmless. The
    files are said to be forgotten as soon as they are, so what fails at the second look (a hub
    that is starting and stays silent through the start's wait, one that hangs up or refuses,
    something else on the port) is said after that line, never in its place."""
    root = hubroots.forget_offline(name)
    if root is not None:
        _forgot(name, str(root.path))
    try:
        late = _second_look(c)
    except hubclient.HubSilent:
        if root is not None:
            _err(f"  ! a hub that is starting on 127.0.0.1:{c.port} did not answer within "
                 f"{hubclient.START_WAIT:g} s, so it was not told and may still hold {name}: "
                 f"run sheaf roots forget {name} again once it answers")
            return EXIT_FAILED
        late = None                                # the files held no such root, so neither can that hub
    if late is None:
        return EXIT_OK if root is not None else _hub_forgot(name, True, None)
    took, held = _forget_on_hub(c, name)
    if root is not None:
        return EXIT_OK if took else EXIT_FAILED
    return _hub_forgot(name, took, held)


def _second_look(c):
    """The hub that answers once an offline forget has written the files, or None when nothing
    listens. One that listens and does not serve yet is waited for, through the start's wait;
    HubSilent when it is still silent then."""
    try:
        return c.challenge()
    except hubclient.HubSilent:            # listening, and not serving yet
        return hubclient.wait_for_start(c, hubclient.START_WAIT)


def _forgot(name: str, path: str):
    _out(f"  forgot {name} ({path}); its documents are untouched")


def cmd_roots(argv: list[str]) -> int:
    if argv and argv[0] == "forget":
        p = _parser("roots forget", "roots forget NAME",
                    "Forget a root: it leaves the index, and its documents' render settings and "
                    "read state with it. The documents themselves are not touched.")
        p.add_argument("name", metavar="NAME", type=_one_line)
        return _forget_root(p.parse_args(argv[1:]).name)
    _parser("roots", "roots\n       sheaf roots forget NAME",
            "List the roots the hub serves, with their folders. A root is a folder with "
            "documents in it that were opened, never one the hub found by looking.").parse_args(argv)
    found = sorted(hubroots.Roots().all(), key=lambda r: r.name)
    if not found:
        _out("  no roots yet; a folder becomes one when a document in it is opened")
    width = max((len(r.name) for r in found), default=0)
    for r in found:
        closed = r.closed()
        note = (f"  (folder cannot be entered: {closed})" if closed
                else "  (folder missing)" if r.missing() else "")
        _out(f"  {r.name.ljust(width)}  {r.path}{note}")
    return EXIT_OK


def cmd_hub(argv: list[str]) -> int:
    p = _parser("hub", "hub [--started-by WHO]",
                "Run the hub in the foreground: what the service and the detached start run.")
    p.add_argument("--started-by", default="cli", choices=["render", "mcp", "cli", "upgrade", "service"])
    return hubserver.run(p.parse_args(argv).started_by)


# ── comments, diag, version: commands that work on a file alone ─────────────

def _parser(name: str, usage: str, what: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"sheaf {name}", usage=f"sheaf {usage}", description=what)


def _one_line(text: str) -> str:
    """An id or a root name as one line of single-spaced words: a newline in the head of a
    comment would cut it in two."""
    out = " ".join(text.split())
    if not out:
        raise argparse.ArgumentTypeError("is empty")
    return out


def _display_name(text: str) -> str:
    """A name a comment is signed with, by the one rule for a display name (SPEC 12)."""
    out = clean_display(text)
    if not out:
        raise argparse.ArgumentTypeError("is empty")
    return out


def _add_as(p: argparse.ArgumentParser):
    p.add_argument("--as", dest="as_name", metavar="NAME", type=_display_name,
                   help="sign as NAME (default: the agent detected in the environment, else you)")


def _not_blank(text: str) -> str:
    if not text.strip():
        raise argparse.ArgumentTypeError("is empty")
    return text


def _days(text: str) -> float:
    try:
        n = float(text)
    except ValueError:
        n = 0.0
    if not (math.isfinite(n) and n > 0):
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of days above zero")
    return n


def _abs(path) -> Path:
    """The document as an absolute path, links left alone: what a diagnostics row records,
    wherever the command ran from."""
    try:
        p = Path(path).expanduser()
    except RuntimeError:                  # "~nobody/x" with no such user: take it as written
        p = Path(path)
    return Path(os.path.abspath(p))


def _author(as_name: str | None) -> tuple[str, bool]:
    """Who signs, and whether that name came from a detected agent (which is what D20
    keys on): `--as`, else the display name of the agent detected in the environment
    (SPEC 11.5), else the user's name (SPEC 4.3)."""
    if as_name is not None:
        return as_name, False
    agent = detect()
    if agent:
        return agent.display, True
    return clean_display(config.user_name()) or "author", False


def _reason(e: Exception) -> str:
    if isinstance(e, UnicodeDecodeError):
        return "is not UTF-8 text"
    if isinstance(e, FileNotFoundError):
        return "no such file"
    if isinstance(e, OSError):
        return e.strerror or str(e)
    return str(e)


def _read_doc(md: Path) -> str | None:
    """The text of a document for a command that only reads, or None after saying why."""
    try:
        return Source(md).read()[0]
    except (OSError, UnicodeDecodeError) as e:
        _err(f"sheaf: {md}: {_reason(e)}")
        return None


def _change_doc(md: Path, kind: str, change) -> bool:
    """Apply change(text) -> text to a document under its lock. On a failure say why,
    write a diagnostics row of `kind` (SPEC 15) and return False. A missing file is a
    typing mistake, not a failed write: said, not recorded."""
    try:
        update_file(md, change)
        return True
    except FileNotFoundError as e:
        _err(f"sheaf: {md}: {_reason(e)}")
    except (comments.AnchorError, StaleError, paths.PathError, OSError, UnicodeDecodeError) as e:
        diagnostics.record("cli", kind, _abs(md), error=f"{type(e).__name__}: {e}")
        _err(f"sheaf: {md}: {_reason(e)}")
    return False


def _reply_line(c, r) -> str:
    role = c.effective_role(r)
    return f"@{c.display(r)} {r.at}{' ' + role if role else ''}: " + r.text.replace("\n", "\n      ")


def cmd_comments(argv: list[str]) -> int:
    p = _parser("comments", "comments FILE [--all] [--json]",
                "List the open comments of a document: id, author, line, status, the passage "
                "and the thread; the malformed ones after.")
    p.add_argument("file", metavar="FILE")
    p.add_argument("--all", action="store_true", help="list the resolved ones too")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = p.parse_args(argv)
    md = Path(args.file)
    text = _read_doc(md)
    if text is None:
        return EXIT_FAILED
    got = comments.parse(text)
    shown = [c for c in got.comments if args.all or c.status == "open"]
    if args.json:
        _out(json.dumps({"comments": [c.as_dict() for c in shown],
                         "malformed": [{"line": m.line, "reason": m.reason} for m in got.malformed]},
                        indent=2, ensure_ascii=False))
        return EXIT_OK
    for c in shown:
        tags = [c.status] + (["orphan: its text was deleted"] if c.orphan else [])
        _out(f"{c.id}  {c.by}  {c.at}  line {c.line}  [{', '.join(tags)}]")
        _out(f'    on: "{c.quote}"')
        for line in c.body.split("\n"):
            _out(f"    {line}")
        for r in c.replies:
            _out(f"    {_reply_line(c, r)}")
        _out()
    for m in got.malformed:
        _out(f"malformed  line {m.line}: {m.reason}")
    if not shown and not got.malformed:
        _out("  no comments" if args.all else "  no open comments")
    return EXIT_OK


def cmd_comment(argv: list[str]) -> int:
    p = _parser("comment", "comment FILE PASSAGE TEXT [--as NAME]",
                "Add a comment on PASSAGE, which must occur exactly once in the rendered text.")
    p.add_argument("file", metavar="FILE")
    p.add_argument("passage", metavar="PASSAGE", type=_not_blank)
    p.add_argument("text", metavar="TEXT", type=_not_blank)
    _add_as(p)
    args = p.parse_args(argv)
    md = Path(args.file)
    who, _ = _author(args.as_name)
    made = []

    def add(t):
        block, start, end = comments.find_quote(t, args.passage)
        new, cid = comments.add_comment(t, block, start, end, args.passage, args.text, who, now())
        made.append(cid)
        return new
    if not _change_doc(md, "comment-failed", add):
        return EXIT_FAILED
    _out(f"  + {made[-1]} added to {md.name}")
    return EXIT_OK


def cmd_reply(argv: list[str]) -> int:
    p = _parser("reply", "reply FILE ID TEXT [--resolve] [--role answer|action] [--as NAME]",
                "Reply in the thread of comment ID. An agent's reply with no --role is "
                "written as an answer; a person's reply carries no role.")
    p.add_argument("file", metavar="FILE")
    p.add_argument("id", metavar="ID", type=_one_line)
    p.add_argument("text", metavar="TEXT", type=_not_blank)
    p.add_argument("--resolve", action="store_true", help="also mark the comment resolved")
    p.add_argument("--role", choices=comments.ROLES,
                   help="answer: you only answered; action: you did what the comment asked")
    _add_as(p)
    args = p.parse_args(argv)
    md = Path(args.file)
    who, from_agent = _author(args.as_name)
    role = args.role or ("answer" if from_agent else None)          # D20
    fields = {"id": args.id, "body": args.text, "resolve": args.resolve}
    if not _change_doc(md, "reply-failed",
                       lambda t: comments.apply_op(t, "reply", fields, who, now(), role)):
        return EXIT_FAILED
    _out(f"  + replied to {args.id}" + (" and resolved it" if args.resolve else ""))
    return EXIT_OK


def _status_command(name: str, status: str, past: str):
    def cmd(argv: list[str]) -> int:
        p = _parser(name, f"{name} FILE ID", f"Mark comment ID {past}.")
        p.add_argument("file", metavar="FILE")
        p.add_argument("id", metavar="ID", type=_one_line)
        args = p.parse_args(argv)
        md = Path(args.file)
        already = []

        def change(t):
            c = comments.parse(t).by_id(args.id)
            if c is not None and c.status == status:
                already.append(True)
                return t                                  # not one byte of it is rewritten
            return comments.apply_op(t, "status", {"id": args.id, "status": status})
        if not _change_doc(md, f"{name}-failed", change):
            return EXIT_FAILED
        _out(f"  {args.id} was already {status}" if already else f"  + {args.id} {past}")
        return EXIT_OK
    cmd.__name__ = f"cmd_{name}"
    return cmd


cmd_resolve = _status_command("resolve", "resolved", "resolved")
cmd_reopen = _status_command("reopen", "open", "reopened")


def cmd_diag(argv: list[str]) -> int:
    usage = "diag [--since DAYS] [--json]\n       sheaf diag note TEXT [FILE]"
    if argv and argv[0] == "note":
        p = _parser("diag note", "diag note TEXT [FILE]",
                    "Record in the diagnostics log what only a session can see.")
        p.add_argument("text", metavar="TEXT", type=_not_blank)
        p.add_argument("file", metavar="FILE", nargs="?", help="the document the note is about")
        args = p.parse_args(argv[1:])
        if not diagnostics.record("agent", "note", _abs(args.file) if args.file else None,
                                  note=args.text):
            _err(f"sheaf: the note could not be written to {diagnostics.log_path()}")
            return EXIT_FAILED
        if len(args.text) > diagnostics.MAX_FIELD:
            _err(f"  ! the note is longer than {diagnostics.MAX_FIELD} characters; "
                 "the first ones are kept")
        _out(f"  + noted in {diagnostics.log_path()}")
        return EXIT_OK
    p = _parser("diag", usage, "Summarise the diagnostics log: counts by source and kind and the "
                               "latest 40 rows. It never leaves this machine.")
    p.add_argument("--since", type=_days, metavar="DAYS", help="only the last DAYS days")
    p.add_argument("--json", action="store_true", help="print the rows as JSON")
    args = p.parse_args(argv)
    _out(diagnostics.report(args.since, args.json))
    return EXIT_OK


def cmd_projects(argv: list[str]) -> int:
    from .hub import projects, the_list
    p = _parser("projects groups", "projects groups [--root PATH]",
                "Print as JSON the groups the Library gives from projects.toml (8.12): for each member short its "
                "project groups, the same for each assistant, and each project with its group, glob, status, members "
                "and assistants. The hub's own reading, so the two never judge membership differently. Needs no hub.")
    p.add_argument("what", choices=["groups"])
    p.add_argument("--root", metavar="PATH", help="the folder that holds projects.toml (default: the [list] root)")
    args = p.parse_args(argv)
    root = args.root
    if root is None:
        try:
            cfg = the_list.load()
        except the_list.ListError as e:
            _err(f"sheaf: {e}")
            return EXIT_FAILED
        if cfg is None:
            _err(f"sheaf: {paths.config_file()} has no [list]: name the folder with --root")
            return EXIT_USAGE
        root = cfg.root
    f = Path(root) / projects.FILE
    try:
        entries = projects.read(Path(root))
    except projects.Invalid as e:
        _err(f"sheaf: {f}: {e}")
        return EXIT_FAILED
    if entries is None:
        # Nothing printed: an empty answer would read as "no project has a member" and take every group away.
        _err(f"sheaf: {f} is not there")
        return EXIT_FAILED
    _out(json.dumps({"root": str(Path(root).resolve()), **projects.groups(entries)}, indent=2))
    return EXIT_OK


def cmd_mcp(argv: list[str]) -> int:
    p = _parser("mcp", "mcp [--agent NAME]",
                "The stdio MCP door: an agent runs this to reach the hub. It reads one JSON-RPC "
                "message per line on stdin, passes each to the hub (starting it if none runs) "
                "and writes each answer as one line on stdout.")
    p.add_argument("--agent", metavar="NAME",
                   help="the agent that runs this, which signs its replies (default: the agent "
                        "found in the environment)")
    args = p.parse_args(argv)
    link = hubclient.DoorLink(mcp.display_for(args.agent), say=_err)
    try:
        link.connect()
    except hubclient.HubUnavailable as e:
        _err(f"sheaf mcp: {e}")                    # and each request is told why, until a hub is there
    return mcp.Stdio(link.post, sys.stdin.buffer, sys.stdout.buffer, sys.stderr).run()


def _member_named(display: str) -> str | None:
    """The name of the member of proxy mode (9.9) that `display` would pass for, or None. A
    `[proxy]` table that cannot be read is the hub's start to refuse, and names nobody here."""
    from .hub import proxy
    try:
        cfg = proxy.load()
    except proxy.ProxyError:
        return None
    return next((m.name for m in (cfg.members.values() if cfg else ()) if proxy.same_name(m.name, display)), None)


def cmd_token(argv: list[str]) -> int:
    p = _parser("token", "token add NAME [--as DISPLAY] [--write] | list | revoke NAME",
                "MCP tokens: a named, revocable secret that lets one agent use the hub's HTTP MCP "
                "door. Only a hash is kept; the token itself is shown once, by `add`.")
    sub = p.add_subparsers(dest="action", required=True, metavar="add|list|revoke")
    add = sub.add_parser("add", usage="sheaf token add NAME [--as DISPLAY] [--write]",
                         help="make a token and print it once")
    add.add_argument("name", metavar="NAME", help="what the token is called, to list or revoke it")
    add.add_argument("--as", dest="display", metavar="DISPLAY",
                     help="the name its replies are signed with (default: NAME)")
    add.add_argument("--write", action="store_true",
                     help="it may also read pages, make them and change their text (default: it "
                          "reads and answers comments only)")
    sub.add_parser("list", usage="sheaf token list", help="names, display names, created, last used")
    revoke = sub.add_parser("revoke", usage="sheaf token revoke NAME", help="end a token")
    revoke.add_argument("name", metavar="NAME")
    args = p.parse_args(argv)
    tokens = Tokens()
    tokens_file = Tokens.path()                    # the hub reads its own SHEAF_HOME; a hand run may not
    if args.action == "add":
        if (taken := _member_named(args.name if args.display is None else args.display)) is not None:
            _err(f"sheaf: {taken!r} is the name of a member of proxy mode (config.toml [proxy]); "
                 "a token's replies must not pass for that member's")
            return EXIT_FAILED
        try:
            token = tokens.add(args.name, args.display, write=args.write)
        except TokenError as e:
            _err(f"sheaf: {e}")
            return EXIT_FAILED
        _out(f"  + token {args.name}, its replies are signed {token.display!r}"
             + (", it may read, make and change pages" if args.write else ""))
        _out(f"    {token}")
        _out(f"  Written to {tokens_file}")
        _out(f"  Shown once. Send it as `Authorization: Bearer <token>` to "
             f"http://127.0.0.1:{config.port()}/_/mcp")
    elif args.action == "list":
        rows = tokens.list()
        if not rows:
            _out(f"  no tokens in {tokens_file}")
        wide = [max((len(w) for w in col), default=0) for col in ([r.name_text for r in rows], [r.display_text for r in rows])]
        for r in rows:
            _out(f"  {r.name_text:<{wide[0]}}  {r.display_text:<{wide[1]}}  created {r.created_text}"
                 f"  last used {r.last_used_text}"
                 + ("  may write" if r.write else "")
                 + ("  refused by verify: its name or display is not one `token add` writes" if r.invalid else ""))
        if rows:
            _out(f"  read from {tokens_file}")
    else:
        if not tokens.revoke(args.name):
            _err(f"sheaf: no token named {args.name} in {tokens_file}")
            return EXIT_FAILED
        _out(f"  - token {args.name} revoked, in {tokens_file}")
    return EXIT_OK


def cmd_code(argv: list[str]) -> int:
    p = _parser("code", "code issue --member ID --doc ADDRESS --out FILE",
                "Sign-in codes for the laptop client of the fork (SPEC 9.13). `issue` asks the hub for one, for a member on one "
                "sheaf, and writes it to a new file of mode 0600 as the header line `curl -H @FILE` sends. It "
                "prints only the code's id and expiry: the code is never in a terminal or on a command line.")
    sub = p.add_subparsers(dest="action", required=True, metavar="issue")
    issue = sub.add_parser("issue", usage="sheaf code issue --member ID --doc ADDRESS --out FILE",
                           help="make a code for a member on one sheaf, into a new 0600 file")
    issue.add_argument("--member", required=True, metavar="ID", help="the front's id of the member")
    issue.add_argument("--doc", required=True, metavar="ADDRESS", help="the sheaf's address on the hub")
    issue.add_argument("--out", required=True, metavar="FILE", help="a new file: one that is there is refused")
    args = p.parse_args(argv)
    out = Path(args.out)
    # The file first, so one that is there, or a link, is refused before a code is made.
    try:
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        _err(f"sheaf: {out} is there already: name a new file")
        return EXIT_FAILED
    except OSError as e:
        _err(f"sheaf: cannot make {out}: {e.strerror or e}")
        return EXIT_FAILED
    written = False
    try:
        os.fchmod(fd, 0o600)
        try:
            status, res = hubclient.client().call("POST", "/_/code", {"doc": args.doc, "member": args.member})
        except (hubclient.Impostor, paths.PathError, OSError) as e:
            return _hub_failure(e)
        if status != 200 or not isinstance(res.get("code"), str):
            _err(f"sheaf: the hub answered {status}: {res.get('error') or 'no code'}")
            return EXIT_FAILED
        view = memoryview(f"Authorization: Bearer {res['code']}\n".encode("ascii"))
        while view:
            view = view[os.write(fd, view):]
        written = True
    finally:
        os.close(fd)
        if not written:
            out.unlink(missing_ok=True)
    _out(f"  code {res.get('id')} for {args.member} on {args.doc}, good until {res.get('expires')}")
    _out(f"  Written to {out} (0600). Send it with `curl -H @{out}`, never on a command line.")
    return EXIT_OK


def hub_version() -> str | None:
    """The version of the hub that is running, or None when none is. The hub is asked, with
    the challenge of SPEC 9.4; an impostor, or a key that cannot be read, is no hub."""
    try:
        got = hubclient.client().challenge()
    except (hubclient.Impostor, paths.PathError, OSError):
        return None
    return got.get("version") if got else None


def cmd_version(argv: list[str]) -> int:
    _parser("version", "version", "Print the version of sheaf, and of the hub when one runs."
            ).parse_args(argv)
    _out(f"sheaf {__version__}")
    hub = hub_version()
    if hub:
        _out(f"hub {hub}")
    return EXIT_OK


COMMANDS.update({"open": cmd_open, "start": cmd_start, "stop": cmd_stop, "status": cmd_status,
                 "hub": cmd_hub, "comments": cmd_comments, "comment": cmd_comment,
                 "reply": cmd_reply, "resolve": cmd_resolve, "reopen": cmd_reopen,
                 "diag": cmd_diag, "version": cmd_version, "list": cmd_list, "roots": cmd_roots,
                 "token": cmd_token, "code": cmd_code, "mcp": cmd_mcp, "projects": cmd_projects})
COMMAND_HELP.update({
    "open": ("open FILE.md|URL [--no-browser] [render options]",
             "open the page of a document; starts the hub if none runs"),
    "start": ("start", "start the hub"),
    "stop": ("stop", "stop the hub"),
    "status": ("status", "say whether the hub runs (exit 1 when it does not)"),
    "list": ("list", "the documents rendered since the hub started, and whether a tab has them open"),
    "roots": ("roots [forget NAME]", "list the folders the hub serves; forget one"),
    "hub": ("hub [--started-by WHO]", "run the hub in the foreground"),
    "comments": ("comments FILE [--all] [--json]",
                 "list the open comments of a document (--all: the resolved ones too)"),
    "comment": ("comment FILE PASSAGE TEXT [--as NAME]",
                "comment on a passage that occurs exactly once"),
    "reply": ("reply FILE ID TEXT [--resolve] [--role answer|action] [--as NAME]",
              "reply in a thread; an agent's reply with no --role is an answer"),
    "resolve": ("resolve FILE ID", "mark a comment resolved"),
    "reopen": ("reopen FILE ID", "mark a comment open again"),
    "diag": ("diag [--since DAYS] [--json]", "summarise the diagnostics log"),
    "diag note": ("diag note TEXT [FILE]", "record what only a session can see"),
    "mcp": ("mcp [--agent NAME]", "run the stdio MCP door for an agent (comments, replies, pages)"),
    "token add": ("token add NAME [--as DISPLAY] [--write]",
                  "make an MCP token for an agent that reaches the hub over HTTP; shown once"),
    "token list": ("token list", "MCP tokens: name, display name, created, last used"),
    "token revoke": ("token revoke NAME", "end an MCP token"),
    "code issue": ("code issue --member ID --doc ADDRESS --out FILE",
                   "a sign-in code for the fork's laptop client, written to a new 0600 file; never printed"),
    "projects groups": ("projects groups [--root PATH]",
                        "print the Library's project groups from projects.toml as JSON (exit 1 without a good file)"),
    "version": ("version", "print the version"),
})


COMMANDS.update(lifecycle.COMMANDS)
COMMAND_HELP.update(lifecycle.COMMAND_HELP)
COMMANDS.update(agent_setup.COMMANDS)
COMMAND_HELP.update(agent_setup.COMMAND_HELP)


# SPEC 14.2: on native Windows only what needs no hub and no service manager runs.
WINDOWS_SAYING = "sheaf supports Linux and macOS. On Windows, use WSL2 (untested)."
WINDOWS_COMMANDS = ("comments", "comment", "reply", "resolve", "reopen", "version")


def _platform() -> str:
    return sys.platform


def windows_stops(first: str, is_file: bool, argv: list[str]) -> bool:
    """Whether this command line stops here, on Windows: every command but the ones that work on a
    file alone, and a document only with --share. The platform is read at call time."""
    if not _platform().startswith("win"):
        return False
    return "--share" not in argv if is_file else first not in WINDOWS_COMMANDS


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        _err(top_help())
        return EXIT_USAGE
    first = argv[0]
    if first in ("-h", "--help", "help"):
        _out(top_help())
        return EXIT_OK
    try:
        is_file = first.endswith(".md") or Path(first).exists()
        if (is_file or first in COMMANDS) and windows_stops(first, is_file, argv):
            _err(WINDOWS_SAYING)
            return EXIT_FAILED
        if is_file:
            return cmd_file(argv)
        if first in COMMANDS:
            return COMMANDS[first](argv[1:])
    except SystemExit as e:                     # argparse: usage errors exit 2, --help 0
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    except (config.ConfigError, paths.PathError) as e:   # a file the command needed and cannot use
        _err(f"sheaf: {e}")
        return EXIT_FAILED
    except BrokenPipeError:
        return EXIT_FAILED
    known = ", ".join(COMMANDS)
    _err(f"sheaf: {first!r} is neither a .md file nor a command (commands: {known}). "
         "Try: sheaf --help")
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
