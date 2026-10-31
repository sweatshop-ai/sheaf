"""
sheafmd.agents.envelope — the one envelope a Tell travels in, on every path (SPEC 11.4, sheaf#117).

The local hub, `sheaf deliver` (the box's supervisor) and the fork's relay all push these bytes on a
Claude Code session's socket, so a session sees a Tell the same way whoever delivers it: a peer message
from sheaf, never a typed user turn and never a frame from no one.
"""
import json
import re
import socket
import uuid

PUSH_TIMEOUT = 5
_TAG_RE = re.compile(r"<(?=\s*/?\s*cross-session-message)", re.I)


def line(text: str, sender: str, msg_id: str | None = None) -> bytes:
    """The JSON line, newline-terminated, that carries `text` from `sender` (a `uds:` address). The text is
    a person's comment: an envelope tag of its own would close this message and open one from any sender it
    likes, so its `<` is written as `&lt;`. `msg_id` is a new uuid4 unless one is given."""
    text = _TAG_RE.sub("&lt;", text)
    content = (f'<cross-session-message from="{sender}" from-name="sheaf" '
               f'from-mode="prompting">\n{text}\n</cross-session-message>')
    return (json.dumps({"msgV": 1, "msg_id": msg_id or str(uuid.uuid4()), "type": "user",
                        "message": {"role": "user", "content": content},
                        "priority": "next", "from": sender},
                       separators=(",", ":")) + "\n").encode("utf-8")


def push(sock_path: str, data: bytes, timeout: float = PUSH_TIMEOUT) -> None:
    """Connect to the session's socket, write `data` and close; no reply is read. Raises OSError."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect(sock_path)
        s.sendall(data)
    finally:
        s.close()
