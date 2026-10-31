"""The one envelope a Tell travels in, on every path (SPEC 11.4, sheaf#117), and `sheaf deliver`,
which pushes it for a process that is not the hub: the box's supervisor, and the fork's relay.

The session is a record in the test's own config folder and its socket a peer thread of the test."""
import json
import os
import threading
import time
from pathlib import Path

import pytest

from agent_fakes import PID, FakeClaude, Peer, write_record
from sheafmd.agents import envelope

SENDER = "uds:/run/x/hub-27419.sock"
MSG_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
SESSION = "6f1c0e9a-2b3d-4c5e-8f70-1a2b3c4d5e6f"


# ── the envelope ─────────────────────────────────────────────────────────────

def test_the_envelope_is_the_json_line_of_the_spec_byte_for_byte():
    """The bytes the local hub has pushed since 11.4 was written, typed out by hand: moving the envelope
    out of the adapter must not change one of them."""
    got = envelope.line('Tell "me":\nline two', SENDER, msg_id=MSG_ID)
    assert got == (
        b'{"msgV":1,"msg_id":"0f8fad5b-d9cb-469f-a165-70867728950e","type":"user","message":'
        b'{"role":"user","content":"<cross-session-message from=\\"uds:/run/x/hub-27419.sock\\" '
        b'from-name=\\"sheaf\\" from-mode=\\"prompting\\">\\nTell \\"me\\":\\nline two\\n'
        b'</cross-session-message>"},"priority":"next","from":"uds:/run/x/hub-27419.sock"}\n')
