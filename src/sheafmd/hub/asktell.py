"""
sheafmd.hub.asktell — Ask, Tell and Cancel (SPEC 11.2, 11.3), and what the page is told about the
agent (10.5, 10.6).

An Ask forks the session through the adapter's command and writes the stdout as a reply with the
role `answer`; the real session never hears of it. A Tell hands the message to the adapter's
`deliver` and then the thread waits (LiveDocument) for a reply with the role `action`. The
processes belong to the job runner (jobs.py).

A job is aimed only at the target the document's render recorded in `docs.json`: nothing in a
request names a session, a socket or a command.
"""
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

from .. import comments as rdc
from .. import config, diagnostics
from ..agents import prompts
from ..agents.base import Adapter, DeliveryCancelled, DeliveryError, Target
from . import roots as roots_mod
from .auth import clean_display
from .live import BY_ID

ASK_TIMEOUT = 10 * 60
STOP_WAITS = 15.0      # seconds a stop message waits for the delivery it cancels to end

NO_AGENT = "Render this page from an agent session to Ask and Tell it."
NOT_YET = ("{product} can answer threads through the MCP door. Ask and Tell need an adapter "
           "sheaf does not have yet.")
ENDED = "The {product} session that rendered this page has ended. Render it again from a session."
NO_SOCKET = ("Tell needs the session's message socket, which was not found. Render the page "
             "again from the session.")
UPGRADING = "The hub is restarting for an upgrade. Try again in a moment."
CANCELLING = "The Tell of this comment is still being cancelled. Try again when that is done."
WAIT_ENDED = ("This Tell ended before it went out: it was cancelled, answered or failed. "
              "Tell again if you still want it.")
NO_JUMP = ("Jump is not set up: add a [jump] table with a command to config.toml, then try again.")
NOT_MINE = ("No session to jump to: it is not run by this account, or its record cannot say which "
            "process it is.")
JUMP_BUSY = "A jump is already running."
JUMP_TIMEOUT = 5.0
_PLACEHOLDER = re.compile(r"\{(session|pid|name|agent)\}")
NO_ASK = ("Ask needs the {product} session id and its command, which were not found. Render the "
          "page again from the session.")
GONE = "The document is no longer on the hub: its folder was forgotten, or its file is gone."


class JobRefused(Exception):
    """`leaves_wait`: the wait that this request began is not its to end: the Cancel in the way ends the
    thread's wait when it is over (and a wait that has ended already is nobody's)."""

    def __init__(self, status: int, message: str, leaves_wait: bool = False):
        super().__init__(message)
        self.status, self.message, self.leaves_wait = status, message, leaves_wait


@dataclass
class View:
    """What the hub knows of a document's agent now."""
    target: Target | None
    adapter: Adapter | None
    caps: frozenset
    lines: dict               # the line under a disabled button, or None when it works
    jump: bool = False        # a [jump] command is set up and the adapter can name the session to it

    def agent(self) -> dict | None:
        """The part of the target a page may hold: never the session id, the socket or the
        command."""
        t, ad = self.target, self.adapter
        if t is None:
            return None
        name = clean_display(ad.name(t)) or clean_display(t.name)
        out = {"agent": t.agent, "display": ad.display, "product": ad.product, "name": name,
               "label": name or t.session[:8]}
        if self.jump:
            out["jump"] = True
        return out

    def can(self) -> list:
        return sorted(self.caps & {"ask", "deliver"})


def who(t: Target, ad: Adapter) -> str:
    """What the page calls the session: its own name (cleaned by the rule of a display name),
    else the stored one, else the adapter's display name (SPEC 10.5)."""
    return clean_display(ad.name(t)) or clean_display(t.name) or ad.display


def _one_line(text: str, limit: int = 200) -> str:
    """`text` on one line, printable characters only, at most `limit` of them."""
    text = "".join(c for c in text if c.isspace() or c.isprintable())
    return " ".join(text.split())[:limit].strip()


def _span(seconds: float) -> str:
    return f"{int(seconds // 60)} minutes" if seconds >= 60 and seconds % 60 == 0 \
        else f"{seconds:g} seconds"


class AskTell:
    def __init__(self, hub):
        self.hub = hub
        self.ask_timeout = ASK_TIMEOUT
        self._jumping = threading.Lock()

    # ── what the page is told ────────────────────────────────────────────────
    def view(self, address: str) -> View:
        t = self.hub.target(address)
        if t is None:
            return View(None, None, frozenset(), {"ask": NO_AGENT, "tell": NO_AGENT})
        ad = self.hub.adapter(t.agent)
        caps = ad.capabilities(t)
        lines = {"ask": None if "ask" in caps else self._line("ask", t, ad),
                 "tell": None if "deliver" in caps else self._line("tell", t, ad)}
        return View(t, ad, caps, lines, jump=ad.implemented and self._jump_set())

    @staticmethod
    def _jump_set() -> bool:
        try:
            return config.jump_command(warn=lambda line: None) is not None
        except config.ConfigError:
            return False                    # the click says why (jump below)

    @staticmethod
    def _line(which: str, t: Target, ad: Adapter) -> str:
        """Why a button does not work (SPEC 10.6)."""
        if not ad.implemented:
            return NOT_YET.format(product=ad.product)
        if which == "ask":
            return NO_ASK.format(product=ad.product)
        state = ad.state(t)
        if state is not None and state.status == "gone":
            return ENDED.format(product=ad.product)
        return NO_SOCKET

    # ── the jump to the session's terminal (SPEC 8.5, 10.5) ──────────────────
    def jump(self, address: str) -> None:
        """Run the `[jump]` command of config.toml for the session this document's last render
        attached. The request names a document and nothing else: the values come from the hub's own
        record of that session, go into the argument list one element at a time, and no shell reads
        them. Raises JobRefused with the one line that says why not."""
        v = self.view(address)
        if v.target is None:
            raise JobRefused(409, NO_AGENT)
        try:
            command = config.jump_command()        # warns of an unknown key, once per click
        except config.ConfigError as e:
            raise JobRefused(409, str(e)) from None
        if command is None:
            raise JobRefused(409, NO_JUMP)
        t, ad = v.target, v.adapter
        if not ad.implemented:
            raise JobRefused(409, NOT_YET.format(product=ad.product))
        state = ad.state(t)
        if state is not None and state.status == "gone":
            raise JobRefused(409, ENDED.format(product=ad.product))
        values = ad.jump_values(t)
        if values is None:
            raise JobRefused(409, NOT_MINE)
        # The adapter gives an id and a pid that are safe as they are; only a name needs cleaning.
        values["name"] = clean_display(values["name"]) or ad.display
        values["agent"] = clean_display(values["agent"])
        argv = [_PLACEHOLDER.sub(lambda m: values[m.group(1)], a) for a in command]
        env = {**os.environ, **{f"SHEAF_JUMP_{k.upper()}": x for k, x in values.items()}}
        if not self._jumping.acquire(blocking=False):
            raise JobRefused(409, JUMP_BUSY)
        try:
            self._run_jump(argv, env)
        finally:
            self._jumping.release()

    @staticmethod
    def _run_jump(argv: list, env: dict) -> None:
        """Run the command to its end. Its stderr goes to a file, not a pipe: a helper it leaves
        running would hold a pipe open and make a command that worked look as if it never ended."""
        try:
            err = tempfile.TemporaryFile()
        except OSError as e:
            raise JobRefused(409, f"The jump command could not be started: {e.strerror or e}") from None
        with err:
            try:
                p = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=err, start_new_session=True)
            except FileNotFoundError:
                raise JobRefused(409, "The jump command was not found.") from None
            except OSError as e:
                raise JobRefused(409, f"The jump command could not be started: {e.strerror or e}") from None
            try:
                p.wait(timeout=JUMP_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
                p.wait()
                raise JobRefused(409, f"The jump command did not finish within {JUMP_TIMEOUT:g} seconds.") from None
            if p.returncode != 0:
                err.seek(0)
                lines = err.read(4000).decode("utf-8", "replace").splitlines()
                first = next((ln.strip() for ln in lines if ln.strip()), "")
                why = f": {_one_line(first)}" if first else ""
                raise JobRefused(409, f"The jump command failed (exit {p.returncode}){why}")

    def product(self, address: str) -> str:
        t = self.hub.target(address)
        return self.hub.adapter(t.agent).product if t else "agent"

    def _require(self, view: View, which: str):
        line = view.lines[which]
        if line is not None:
            raise JobRefused(409, line)

    def refusal(self, address: str, which: str) -> str | None:
        """The line that says why `which` ("ask" or "tell") cannot start now, or None."""
        return self.view(address).lines[which]

    def _pair(self, address: str):
        v = self.view(address)
        return v.target, v.adapter

    def telling_line(self, address: str, cid: str) -> str | None:
        """The line that says why a Tell of this thread cannot start now (one is being delivered, or the
        cancel of the last one is not over), or None. The comment route asks it before it writes, so a
        refused Tell leaves the wait that is there."""
        if self.hub.runner.running("tell", address, cid):
            return self._already_telling(*self._pair(address))
        if self._cancelling(address, cid):
            return CANCELLING
        return None

    # ── helpers ──────────────────────────────────────────────────────────────
    @contextmanager
    def _admitting(self):
        """A job starts, or a Tell's wait begins, only inside this: under the hub's admission
        lock, which an upgrade stop also takes, so neither slips between the other's check and
        its act (SPEC 8.4). Refused once an upgrade stop has been taken."""
        with self.hub.admit:
            if self.hub.upgrading:
                raise JobRefused(409, UPGRADING)
            yield

    def _cancelling(self, address: str, cid: str) -> bool:
        """Whether the cancel of this thread's Tell is not over: it has taken its step under the
        admission lock, and its stop message has not been sent or ruled out (see `cancel`)."""
        return self.hub.runner.held("stop", address, cid)

    def _not_cancelling(self, address: str, cid: str):
        """Inside `_admitting`: no Tell of a thread starts while the cancel of its Tell is not over. The
        cancel would end the new Tell's wait and send a stop message for a delivery it never cancelled,
        or its stop message would reach the session after the new Tell (SPEC 11.3). Only a Tell is
        refused: an Ask touches no wait."""
        if self._cancelling(address, cid):
            raise JobRefused(409, CANCELLING, leaves_wait=True)

    def _start(self, e, kind: str, cid: str, work, on_error):
        """Inside `_admitting`: start the job on `e`, if `e` is still the document's entry. `forget_root`
        takes the entry out and then cancels the jobs of the root; so the job is registered first, held
        back from `work`, and the entry looked at after: either the forget's cancel finds the job, or the
        look finds the entry gone, and `work` never runs. No lock of the hub is taken here: the admission
        lock must not wait for a render, and `render` and `forget_root` hold the hub's lock through one."""
        armed, refused = threading.Event(), threading.Event()

        def held_back(job):
            armed.wait()
            if not refused.is_set():
                work(job)
        job = None
        try:
            job = self.hub.runner.start(kind, e.address, cid, held_back, on_error=on_error)
            if job is not None and not self._is_current(e):
                raise JobRefused(404, GONE)
            return job
        except BaseException:
            if job is not None:
                refused.set()
                job.cancel()
            raise
        finally:
            armed.set()                  # on every path: the job's thread waits for it

    def _is_current(self, e) -> bool:
        """Whether `e` is still the entry the hub holds for its address."""
        return self.hub.entries.get(e.address) is e

    def _emit(self, e, name: str, data: dict):
        e.bus.publish(name, data)

    def _entry(self, address: str):
        """The document a job runs on, looked up again when it starts. Its root forgotten since the
        request found it, with no folder that takes the name, or its file gone: refused as a document
        that is not there, so the comment route still answers for the comment it wrote (SPEC 7.3)."""
        try:
            return self.hub.entry(address)
        except roots_mod.NotFound:
            raise JobRefused(404, GONE) from None

    @staticmethod
    def _version(e, held):
        """A thread is named by id in a text: the one a page holds, or the one the comment route has just
        written the comment in (`held`, its hash). In a version the document does not know the id may
        name another thread (SPEC 7.3). Checked on the entry the job then runs on, so a forget in
        between cannot hand it the thread of another folder's file."""
        if not e.live.knows(held):
            raise JobRefused(409, f"{BY_ID}. Reload the page")

    def _thread(self, e, cid: str):
        try:
            c = rdc.parse(e.path.read_text(encoding="utf-8")).by_id(cid)
        except OSError:
            raise JobRefused(404, "no such document") from None
        if c is None:
            raise JobRefused(404, f"no comment {cid} in this document")
        return c

    def _links(self, address: str) -> bool:
        root = self.hub.roots.get(roots_mod.Address.parse(address).root)
        if root is None:
            return True
        try:
            return config.load_root_config(root.path, warn=lambda m: None).links
        except config.ConfigError:
            return True

    def _cwd(self, e) -> str:
        """The root of the document: where an Ask runs (SPEC 11.2)."""
        root = self.hub.roots.get(roots_mod.Address.parse(e.address).root)
        for d in (root.path if root else None, e.path.parent):
            if d is not None and d.is_dir():
                return str(d)
        return str(e.path.parent)

    # ── Ask ──────────────────────────────────────────────────────────────────
    def start_ask(self, address: str, cid: str, held=None):
        """Start answering thread `cid`, named in the version `held`: the page's, or the text the comment
        route has just written the comment in; None when no page is behind it. Raises JobRefused with the
        status and the sentence."""
        e = self._entry(address)
        self._version(e, held)
        v = self.view(address)
        self._require(v, "ask")
        self._thread(e, cid)
        t, ad = v.target, v.adapter

        def work(job):
            self._ask(e, ad, t, cid, job)

        def failed(ex):
            self._emit(e, "ask-failed", {"id": cid, "error": f"the hub failed to ask "
                                         f"({type(ex).__name__}); the details are in `sheaf diag`"})
        with self._admitting():
            started = self._start(e, "ask", cid, work, failed)
        if started is None:
            raise JobRefused(409, f"{who(t, ad)} is already answering this comment")

    def _ask(self, e, ad: Adapter, t: Target, cid: str, job):
        def fail(message: str):
            self._emit(e, "ask-failed", {"id": cid, "error": message})

        self._emit(e, "ask-started", {"id": cid})
        try:
            c = rdc.parse(e.path.read_text(encoding="utf-8")).by_id(cid)
        except OSError:
            return fail("the document is gone")
        if c is None:
            return fail(f"no comment {cid} in this document")
        prompt = prompts.ask(str(e.path), c, self._links(e.address))
        try:
            r = job.run(ad.ask_command(t), timeout=self.ask_timeout, env=ad.child_env(t),
                        cwd=self._cwd(e), input=prompt)
        except FileNotFoundError:
            return fail(f"the {ad.product} command was not found")
        except subprocess.TimeoutExpired:
            return fail(f"{who(t, ad)} did not answer within {_span(self.ask_timeout)}")
        if job.cancelled:
            self._emit(e, "ask-cancelled", {"id": cid})
            return
        tail = " ".join((r.stderr or "").strip().splitlines()[-3:])
        if r.returncode < 0:
            return fail(f"{ad.product} was stopped by signal {-r.returncode}")
        answer = (r.stdout or "").strip()
        if r.returncode != 0:
            return fail(f"{ad.product} exited with {r.returncode}: {tail or 'no output'}")
        if not answer:
            return fail(f"{who(t, ad)} gave no answer" + (f": {tail}" if tail else ""))
        try:
            e.live.reply_as(cid, answer, ad.display, "answer", "ask-done",
                            expect=rdc.thread_identity(c))
        except rdc.ThreadChanged:
            fail(f"the comment changed while {who(t, ad)} was answering")
        except rdc.AnchorError:
            fail(f"the comment was deleted while {who(t, ad)} was answering")

    # ── Tell ─────────────────────────────────────────────────────────────────
    def start_tell(self, address: str, cid: str, waiting: bool = False, held=None):
        """Deliver thread `cid` to the session. `waiting`: the thread already waits for the
        reply (a comment written with Tell starts the wait when it is written). `held`: as for an
        Ask. Raises JobRefused."""
        e = self._entry(address)
        self._version(e, held)
        v = self.view(address)
        self._require(v, "tell")
        # Before the wait is touched: a second Tell must leave the first one's as it is.
        if self.hub.runner.running("tell", address, cid):
            raise JobRefused(409, self._already_telling(v.target, v.adapter))
        with self._admitting():
            self._not_cancelling(address, cid)
            if not waiting and not e.live.await_reply(cid):
                raise JobRefused(404, f"no comment {cid} in this document")
        try:
            c = self._thread(e, cid)
        except JobRefused:
            e.live.stop_waiting(cid)
            raise
        t, ad = v.target, v.adapter
        text = prompts.tell(address, str(e.path), self.hub.person, c, self._links(address))

        def work(job):
            if job.cancelled:                      # the Cancel came before the first byte
                return
            try:
                ad.deliver(t, text, job.run)
            except DeliveryCancelled:
                return
            except DeliveryError as ex:
                if not job.cancelled:
                    self._tell_failed(e, cid, str(ex))
                return
            if not job.cancelled:
                self._emit(e, "tell-sent", {"id": cid})

        def failed(ex):
            self._tell_failed(e, cid, f"the hub failed to deliver the message "
                              f"({type(ex).__name__}); the details are in `sheaf diag`")
        try:
            with self._admitting():
                self._not_cancelling(address, cid)
                if not e.live.is_waiting(cid):       # it ended (cancel, answer, failure): no job to end
                    raise JobRefused(409, WAIT_ENDED, leaves_wait=True)
                started = self._start(e, "tell", cid, work, failed)
        except JobRefused as r:              # an upgrade stop, or a cancel, after the wait began
            if not r.leaves_wait:            # else the cancel must find the wait, to stop the session
                e.live.stop_waiting(cid)
            raise
        except BaseException:                # the start failed: no job will end the wait
            e.live.stop_waiting(cid)
            raise
        if started is None:                  # a Tell of this thread began between the check and here
            raise JobRefused(409, self._already_telling(t, ad))

    @staticmethod
    def _already_telling(t: Target, ad: Adapter) -> str:
        return f"{who(t, ad)} is already being told about this comment"

    def _tell_failed(self, e, cid: str, message: str):
        e.live.stop_waiting(cid)
        self._emit(e, "tell-failed", {"id": cid, "error": message})

    # ── Cancel ───────────────────────────────────────────────────────────────
    def cancel(self, address: str, cid: str, what: str):
        # The entry as it is held, not looked up in the file: a cancel of a job on a file that has
        # gone must still stop it. No entry means a forget took the document; a job that started on
        # its entry after the forget counted the jobs is still stopped, with no page left to tell.
        e = self.hub.entries.get(address)
        if e is None:
            self.hub.runner.cancel(what, address, cid)
            return
        if what == "ask":
            # A running Ask says so itself when its child ends. Nothing running means the answer
            # has just landed or it never started: clear the page all the same.
            if not self.hub.runner.cancel("ask", address, cid):
                self._emit(e, "ask-cancelled", {"id": cid})
            return
        # Under the admission lock only what an upgrade stop must not come between: the end of the
        # delivery's job and the hold that says the stop message is on its way (8.4). The wait ends
        # after, outside the lock, because it needs the document's lock, which a render holds for
        # as long as pandoc or mmdc take, and an upgrade stop (the announced SIGTERM of `sheaf restart`
        # too) and every Ask and Tell start wait on the admission lock. The hold stays until the cancel
        # is over: no Tell of the thread starts meanwhile (`_not_cancelling`).
        with self.hub.admit:
            deliveries = self.hub.runner.worker_threads("tell", address, cid)
            running = self.hub.runner.cancel("tell", address, cid)
            held = self.hub.runner.hold("stop", address, cid)
        try:
            waiting = e.live.stop_waiting(cid)
            if running or waiting:
                # A delivery killed half-way may still have reached the session, so the stop message
                # goes out either way, and only once that delivery has ended: a delivery cannot be
                # taken back, and the stop must not arrive before the Tell it cancels.
                self._emit(e, "tell-cancelled", {"id": cid, "sent": True})
                if self._send_stop(e, cid, deliveries, held):
                    return                                  # the stop message's job ends the cancel
        except BaseException:
            self.hub.runner.release(held)                   # failed: the wait stays, to cancel again
            raise
        self._cancel_over(e, cid, held)

    def _cancel_over(self, e, cid: str, held):
        """The cancel is over, and Tells are accepted again. No Tell of the thread started meanwhile, so
        a wait that is there was begun by a reply sent with Tell (its write begins the wait under the
        document's lock, which the runner knows nothing of) and was refused: it ends with the cancel, and
        the tabs, which hold it as "working" from that reply's answer, are told."""
        try:
            if e.live.stop_waiting(cid):
                self._emit(e, "tell-cancelled", {"id": cid})
        finally:
            self.hub.runner.release(held)

    def _send_stop(self, e, cid: str, deliveries: list[threading.Thread], held) -> bool:
        """Start the stop message as a job. True when its job has the cancel from here on and ends it."""
        v = self.view(e.address)               # reads files and asks the adapter: not under the lock
        if v.target is None or "stop" not in v.caps:
            diagnostics.record("hub", "tell-stop-skipped", e.address, id=cid,
                               reason="the session cannot be reached")
            return False
        t, ad = v.target, v.adapter
        text = prompts.cancel(e.address, self.hub.person, cid)

        def work(job):
            try:
                end = time.monotonic() + STOP_WAITS
                for delivery in deliveries:
                    delivery.join(max(0.0, end - time.monotonic()))
                try:
                    ad.stop(t, text, job.run)
                except DeliveryCancelled:
                    pass
                except DeliveryError as ex:
                    diagnostics.record("hub", "tell-stop-failed", e.address, id=cid, error=str(ex))
            finally:
                self._cancel_over(e, cid, held)
        self.hub.runner.start("stop", e.address, cid, work)
        return True

    # ── the watcher's step (SPEC 8.9) ────────────────────────────────────────
    def observe(self, e):
        """What the told session is doing, for the threads waiting on it."""
        if not (e.live.waiting() or e.live.session_question()):
            return
        t = self.hub.target(e.address)
        e.live.observe(self.hub.adapter(t.agent).state(t) if t else None)
