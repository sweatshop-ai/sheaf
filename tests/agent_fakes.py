"""The fakes the agent tests share. Nothing here reaches a real session: the "session" is a
record in the test's own config folder, its socket is a peer thread of the test, and `claude` is
a shell script of the test's own that writes down how it was called."""
import json
import os
import socket
import threading
from pathlib import Path

from helpers import stop_listener, write_executable

PID = os.getpid()        # a live process: a session record of a dead one is not believed


def write_record(cfg, pid=PID, **fields):
    """A Claude Code session record, `<cfg>/sessions/<pid>.json`."""
    rec = {"pid": pid, "sessionId": "s-1", "cwd": "/work/here", "kind": "interactive",
           "peerProtocol": 1, "messagingSocketPath": "", "name": "Cosima", "status": "idle"}
    rec.update(fields)
    (Path(cfg) / "sessions").mkdir(parents=True, exist_ok=True)
    (Path(cfg) / "sessions" / f"{pid}.json").write_text(json.dumps(rec), encoding="utf-8")
    return rec


class Peer:
    """A session's socket. Every connection is read to its end; each is one message."""

    def __init__(self, path):
        self.path = str(path)
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        self.srv.listen(8)
        self.messages: list[bytes] = []
        self.accepted = 0                   # connections taken, read to their end or not
        self._cond = threading.Condition()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.accepted += 1
            data = b""
            with conn:
                while chunk := conn.recv(65536):
                    data += chunk
            with self._cond:
                self.messages.append(data)
                self._cond.notify_all()

    def wait_for(self, n=1, timeout=5.0) -> list[bytes]:
        with self._cond:
            self._cond.wait_for(lambda: len(self.messages) >= n, timeout)
            assert len(self.messages) >= n, f"{len(self.messages)} message(s) arrived, wanted {n}"
            return list(self.messages)

    def received(self) -> bytes:
        """The first message, waited for."""
        return self.wait_for(1)[0]

    @property
    def data(self) -> bytes:
        return b"".join(self.messages)

    def close(self):
        stop_listener(self.srv, self.thread)


class FakeClaude:
    """A `claude` that records how it was run (`argv`, `stdin`, `cwd`, how many times) and then does what
    it was told: print an answer, print to stderr, sleep, exit with a code."""

    def __init__(self, folder, *, answer="The answer.", err="", code=0, sleep=0):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.bin = self.dir / "claude"
        self.log = self.dir / "calls"
        self.log.mkdir(exist_ok=True)
        (self.dir / "answer").write_text(answer, encoding="utf-8")
        (self.dir / "err").write_text(err, encoding="utf-8")
        write_executable(self.bin,
            "#!/bin/sh\n"
            f'n=$(ls "{self.log}" | wc -l)\n'
            f'mkdir "{self.log}/call$n"\n'
            f'for a in "$@"; do printf "%s\\0" "$a"; done > "{self.log}/call$n/argv"\n'
            f'pwd > "{self.log}/call$n/cwd"\n'
            f'printf "%s" "${{CLAUDE_CODE_SESSION_ID-UNSET}}" > "{self.log}/call$n/session-var"\n'
            f'printf "%s" "${{CLAUDE_CONFIG_DIR-UNSET}}" > "{self.log}/call$n/config-var"\n'
            f'echo $$ > "{self.log}/call$n/pid"\n'
            # What came on stdin appears whole or not at all, so a reader never sees half of it.
            f'cat > "{self.log}/call$n/stdin.part"; mv "{self.log}/call$n/stdin.part" "{self.log}/call$n/stdin"\n'
            f'cat "{self.dir}/err" >&2\n'
            f'cat "{self.dir}/answer"\n'
            + (f"sleep {sleep}\n" if sleep else "")
            + f"exit {code}\n")

    def calls(self) -> list[dict]:
        """The calls that have started: the script writes its pid after argv, cwd and the
        session and config variables, so a call with a pid has those, and a test that waits for
        a call may read them."""
        out = []
        for d in sorted(self.log.iterdir(), key=lambda p: int(p.name[4:])):
            if not (d / "pid").exists() or not (d / "pid").read_text().strip():
                continue                                # not started yet, or the shell is still writing it
            out.append({"argv": [a.decode() for a in (d / "argv").read_bytes().split(b"\0")[:-1]]
                        if (d / "argv").exists() else [],
                        "stdin": (d / "stdin").read_text() if (d / "stdin").exists() else "",
                        "cwd": (d / "cwd").read_text().strip() if (d / "cwd").exists() else "",
                        "session_var": (d / "session-var").read_text() if (d / "session-var").exists() else None,
                        "config_var": (d / "config-var").read_text() if (d / "config-var").exists() else None,
                        "pid": int((d / "pid").read_text())})
        return out
