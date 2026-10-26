"""The fakes the agent tests stand on."""
from agent_fakes import FakeClaude


def test_a_call_that_has_not_written_its_pid_yet_is_not_listed_as_a_call(tmp_path):
    """The fake `claude` makes its call folder and then writes into it, pid last. A test that
    waits for the first call and reads its pid must never see the folder in between."""
    claude = FakeClaude(tmp_path / "claude")
    call = claude.log / "call0"
    call.mkdir()
    (call / "argv").write_bytes(b"-p\0")
    assert claude.calls() == []
    (call / "pid").write_text("123\n")
    assert [c["pid"] for c in claude.calls()] == [123]
