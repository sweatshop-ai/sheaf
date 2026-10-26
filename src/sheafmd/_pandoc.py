"""The one place the bundled pandoc is started (SPEC 3.2).

A document can make pandoc run without end and grow without bound (pandoc 3.9: a footnote
that cites itself, `[^1]: a [^1]`), so every call has a heap cap and a time limit. A run that
hits either one comes back as a failed run, like a document pandoc cannot read."""
import subprocess

import pypandoc

HEAP = "-M1g"      # a 470 KB document needs about 180 MB
TIMEOUT = 120      # seconds


def run(args: list[str], text: str) -> subprocess.CompletedProcess:
    cmd = [pypandoc.get_pandoc_path(), *args, "+RTS", HEAP, "-RTS"]
    try:
        return subprocess.run(cmd, input=text, capture_output=True, text=True,
                              encoding="utf-8", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"pandoc did not finish in {TIMEOUT} seconds")
