"""The PDF is printed from the rendered page by headless Chrome, and a missing or
failing Chrome is a PdfError that says what to do, never a traceback from deeper in."""
import stat
import subprocess
import tempfile
import types

import pytest

from sheafmd import pdf

NO_CHROME = "Chrome or Chromium is needed to write a PDF and neither is installed."
HTML = "<!doctype html><title>t</title><h1>Hello</h1>"


def fake_chrome(tmp_path, body, name="fake-chrome"):
    """A stand-in executable: `body` is the shell script after the shebang."""
    exe = tmp_path / name
    exe.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


def test_pdf_error_is_its_own_exception():
    assert issubclass(pdf.PdfError, Exception)
    assert not issubclass(pdf.PdfError, RuntimeError)


# ── finding Chrome ──────────────────────────────────────────────────────────

def test_find_chrome_returns_none_when_nothing_is_on_path_and_no_bundle_exists(monkeypatch):
    monkeypatch.setattr(pdf.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", "")
    # the macOS bundle and the Windows installs are looked up with Path(...).exists()
    monkeypatch.setattr(pdf, "Path", lambda p: types.SimpleNamespace(exists=lambda: False))
    assert pdf.find_chrome() is None


def test_find_chrome_prefers_a_package_name_on_path(monkeypatch):
    found = {"google-chrome": "/usr/bin/google-chrome", "chromium": "/usr/bin/chromium"}
    monkeypatch.setattr(pdf.shutil, "which", lambda name: found.get(name))
    assert pdf.find_chrome() == "/usr/bin/google-chrome"


def test_find_chrome_falls_back_to_the_macos_bundle(monkeypatch):
    bundle = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    monkeypatch.setattr(pdf.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", "")
    monkeypatch.setattr(pdf, "Path", lambda p: types.SimpleNamespace(exists=lambda: p == bundle))
    assert pdf.find_chrome() == bundle


# ── no Chrome ───────────────────────────────────────────────────────────────

# Where google-chrome-stable comes from: neither Ubuntu nor Debian has it, so apt knows
# it only once Google's apt source is set up, which the .deb from dl.google.com does as it installs
# (its postinst writes google-chrome.sources). Google builds it for arm64 too.
LINUX_HINT = ("google-chrome-stable comes from Google, for amd64 and arm64, not from Ubuntu or Debian; "
              "its .deb installs it and adds Google's apt source:\n"
              "    download https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb "
              "(_arm64.deb on ARM), then sudo apt install ./google-chrome-stable_current_*.deb")


@pytest.mark.parametrize("platform, hint", [
    ("linux", LINUX_HINT),
    ("darwin", "brew install --cask google-chrome"),
])
def test_write_pdf_without_chrome_says_what_to_install_on_this_platform(
        tmp_path, monkeypatch, platform, hint):
    monkeypatch.setattr(pdf, "find_chrome", lambda: None)
    monkeypatch.setattr(pdf.sys, "platform", platform)
    out = tmp_path / "out.pdf"
    with pytest.raises(pdf.PdfError) as e:
        pdf.write_pdf(HTML, out)
    assert str(e.value) == NO_CHROME + "\n    " + hint
    assert not out.exists()


def test_print_pdf_without_chrome_raises_the_same_error(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "find_chrome", lambda: None)
    monkeypatch.setattr(pdf.sys, "platform", "linux")
    page = tmp_path / "page.html"
    page.write_text(HTML, encoding="utf-8")
    with pytest.raises(pdf.PdfError, match="neither is installed"):
        pdf.print_pdf(page, tmp_path / "out.pdf")


# ── a Chrome that does not do its job ───────────────────────────────────────

def test_chrome_that_writes_nothing_is_a_pdf_error_with_its_output(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "find_chrome", lambda: fake_chrome(tmp_path, "echo sandbox says no\nexit 0\n"))
    with pytest.raises(pdf.PdfError, match="Chrome produced no PDF") as e:
        pdf.write_pdf(HTML, tmp_path / "out.pdf")
    assert "sandbox says no" in str(e.value)
    assert not (tmp_path / "out.pdf").exists()


def test_chrome_that_writes_an_empty_file_is_a_pdf_error(tmp_path, monkeypatch):
    body = 'for a in "$@"; do case "$a" in --print-to-pdf=*) : > "${a#--print-to-pdf=}";; esac; done\n'
    monkeypatch.setattr(pdf, "find_chrome", lambda: fake_chrome(tmp_path, body))
    with pytest.raises(pdf.PdfError, match="Chrome produced no PDF"):
        pdf.write_pdf(HTML, tmp_path / "out.pdf")


def test_chrome_that_takes_too_long_is_a_pdf_error(tmp_path, monkeypatch):
    seen = {}

    def slow(cmd, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(pdf, "find_chrome", lambda: "/usr/bin/chrome")
    monkeypatch.setattr(pdf.subprocess, "run", slow)
    with pytest.raises(pdf.PdfError, match="Chrome timed out after 120 seconds"):
        pdf.write_pdf(HTML, tmp_path / "out.pdf")
    assert seen["timeout"] == 120


def test_chrome_is_called_with_the_flags_that_keep_the_page_clean(tmp_path, monkeypatch):
    log = tmp_path / "argv.txt"
    body = (f'printf "%s\\n" "$@" > "{log}"\n'
            'for a in "$@"; do case "$a" in --print-to-pdf=*) head -c 3000 /dev/zero > "${a#--print-to-pdf=}";; esac; done\n')
    monkeypatch.setattr(pdf, "find_chrome", lambda: fake_chrome(tmp_path, body))
    page = tmp_path / "page.html"
    page.write_text(HTML, encoding="utf-8")
    out = tmp_path / "out.pdf"
    line = pdf.print_pdf(page, out)
    assert line == f"  = {out}  (2 KB)"
    args = log.read_text(encoding="utf-8").split("\n")
    for flag in ("--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                 "--print-to-pdf-no-header", f"--print-to-pdf={out}", page.as_uri()):
        assert flag in args, flag
    assert any(a.startswith("--user-data-dir=") for a in args)


# ── the real thing ──────────────────────────────────────────────────────────

@pytest.mark.skipif(pdf.find_chrome() is None, reason="Chrome or Chromium not installed")
def test_write_pdf_with_chrome_writes_a_pdf(tmp_path, tmp_path_factory, monkeypatch):
    # Chrome keeps a unix socket under TMPDIR and fails on a path of about 108 bytes
    # ("Socket path too long"); the suite's own temp dir inside tmp_path is too deep.
    short = str(tmp_path_factory.mktemp("c"))
    monkeypatch.setenv("TMPDIR", short)
    monkeypatch.setattr(tempfile, "tempdir", short)
    out = tmp_path / "out.pdf"
    assert pdf.write_pdf(HTML, out) is None
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 0


# ── a failed print never leaves or keeps a PDF that is not the new one ───────

def test_an_old_pdf_does_not_pass_for_the_new_one_when_chrome_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "find_chrome", lambda: fake_chrome(tmp_path, "exit 0\n"))
    out = tmp_path / "out.pdf"
    out.write_bytes(b"%PDF-1.4 the old one")
    with pytest.raises(pdf.PdfError, match="Chrome produced no PDF"):
        pdf.write_pdf(HTML, out)
    assert out.read_bytes() == b"%PDF-1.4 the old one"


def test_the_finished_pdf_replaces_the_old_one_whole_and_no_temp_file_stays(tmp_path, monkeypatch):
    body = 'for a in "$@"; do case "$a" in --print-to-pdf=*) printf "%%PDF-new" > "${a#--print-to-pdf=}";; esac; done\n'
    monkeypatch.setattr(pdf, "find_chrome", lambda: fake_chrome(tmp_path, body))
    out = tmp_path / "sub" / "out.pdf"                    # a folder that does not exist yet
    pdf.write_pdf(HTML, out)
    assert out.read_bytes() == b"%PDF-new"
    out.write_bytes(b"old")
    pdf.write_pdf(HTML, out)
    assert out.read_bytes() == b"%PDF-new"
    assert sorted(p.name for p in out.parent.iterdir()) == ["out.pdf"]
    assert out.stat().st_mode & 0o044                      # readable by others, like any file the umask allows


def test_a_chrome_that_cannot_be_started_is_a_pdf_error(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "find_chrome", lambda: str(tmp_path / "no-such-chrome"))
    with pytest.raises(pdf.PdfError, match="could not be started"):
        pdf.write_pdf(HTML, tmp_path / "out.pdf")


# ── a PDF that cannot be written there is a PdfError, not an OSError ─────────

PRINTS = 'for a in "$@"; do case "$a" in --print-to-pdf=*) printf "%%PDF-new" > "${a#--print-to-pdf=}";; esac; done\n'


def test_an_out_that_is_an_existing_folder_is_a_pdf_error_and_leaves_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "find_chrome", lambda: fake_chrome(tmp_path, PRINTS))
    out = tmp_path / "taken"
    out.mkdir()
    with pytest.raises(pdf.PdfError, match="cannot write .*taken: Is a directory"):
        pdf.write_pdf(HTML, out)
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".sheaf-tmp")] == []    # no temp file
    assert list(out.iterdir()) == []


def test_an_out_in_a_folder_that_cannot_be_made_is_a_pdf_error(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "find_chrome", lambda: fake_chrome(tmp_path, PRINTS))
    (tmp_path / "afile").write_text("not a folder", encoding="utf-8")
    with pytest.raises(pdf.PdfError, match="cannot write .*out.pdf"):
        pdf.write_pdf(HTML, tmp_path / "afile" / "out.pdf")


# ── a Chromium snap ─────────────────────────────────────────────────────────

def fake_snap(tmp_path, monkeypatch, body=None):
    """A stand-in for the Chromium snap, at SNAP_BIN/chromium, in a home of the test. Like the snap it
    has its own /tmp: a path under the host's TMPDIR does not exist for it, and a folder or file it
    makes there lands in its private /tmp instead, which the host never sees (on Ubuntu,
    /tmp/snap-private-tmp/snap.chromium). Everything else it shares with the host. Returns the
    folders a test looks at: the host's TMPDIR, the snap's private /tmp and the home."""
    host_tmp, private, home, snap_bin = (tmp_path / "host-tmp", tmp_path / "private-tmp",
                                         tmp_path / "home", tmp_path / "snap" / "bin")
    for d in (host_tmp, private, home, snap_bin):
        d.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(host_tmp))
    monkeypatch.setattr(pdf, "SNAP_BIN", str(snap_bin))
    monkeypatch.setattr(pdf, "_passwd_home", lambda: str(home))
    exe = fake_chrome(snap_bin, (
        f'host_tmp="{host_tmp}"; private="{private}"\n'
        'seen() { case "$1" in "$host_tmp"/*) echo "$private$1";; *) echo "$1";; esac; }\n'
        + (body or
           'for a in "$@"; do case "$a" in\n'
           '  --user-data-dir=*) d=$(seen "${a#--user-data-dir=}"); mkdir -p "$d"; echo "{}" > "$d/Local State";;\n'
           '  --print-to-pdf=*) out=$(seen "${a#--print-to-pdf=}");;\n'
           '  file://*) page="${a#file://}";;\n'
           'esac; done\n'
           'case "$page" in "$host_tmp"/*) echo "Page load failed: net::ERR_FILE_NOT_FOUND"; exit 0;; esac\n'
           'mkdir -p "$(dirname "$out")"; printf "%%PDF-1.4 from the snap" > "$out"\n')), name="chromium")
    monkeypatch.setattr(pdf, "find_chrome", lambda: exe)
    return host_tmp, private, home


def test_a_chromium_snap_prints_a_pdf_with_the_default_tmpdir(tmp_path, monkeypatch):
    fake_snap(tmp_path, monkeypatch)
    out = tmp_path / "out.pdf"
    pdf.write_pdf(HTML, out)
    assert out.read_bytes() == b"%PDF-1.4 from the snap"


def test_a_chromium_snap_leaves_no_profile_folder_in_its_private_tmp_or_in_its_own_folder(tmp_path, monkeypatch):
    host_tmp, private, home = fake_snap(tmp_path, monkeypatch)
    common = home / "snap" / "chromium" / "common"
    common.mkdir(parents=True)
    (common / "chromium").mkdir()                          # the snap's own, from an earlier run
    pdf.write_pdf(HTML, tmp_path / "out.pdf")
    assert list(private.rglob("*")) == []
    assert [p.name for p in common.iterdir()] == ["chromium"]
    assert list(host_tmp.iterdir()) == []


def test_a_chromium_snap_that_prints_nothing_is_named_with_what_to_do(tmp_path, monkeypatch):
    fake_snap(tmp_path, monkeypatch, body='echo "Page load failed: net::ERR_FILE_NOT_FOUND"\n')
    monkeypatch.setattr(pdf.sys, "platform", "linux")
    with pytest.raises(pdf.PdfError) as e:
        pdf.write_pdf(HTML, tmp_path / "out.pdf")
    lines = str(e.value).split("\n")
    assert lines[:2] == ["Chrome produced no PDF.", "    Page load failed: net::ERR_FILE_NOT_FOUND"]
    named = f"    {tmp_path}/snap/bin/chromium is a snap"
    assert any(line.startswith(named) for line in lines[2:]), lines
    assert "    " + pdf._install_hint() in str(e.value)


def test_a_chromium_snap_whose_folder_cannot_be_made_is_a_pdf_error(tmp_path, monkeypatch):
    _, _, home = fake_snap(tmp_path, monkeypatch)
    (home / "snap").write_text("not a folder", encoding="utf-8")
    with pytest.raises(pdf.PdfError, match=f"cannot make {home}/snap/chromium for the snap"):
        pdf.write_pdf(HTML, tmp_path / "out.pdf")
    assert not (tmp_path / "out.pdf").exists()


def test_a_chromium_snap_that_never_ran_gets_its_folder_made_as_snapd_makes_it(tmp_path, monkeypatch):
    _, _, home = fake_snap(tmp_path, monkeypatch)
    pdf.write_pdf(HTML, tmp_path / "out.pdf")
    assert stat.S_IMODE((home / "snap").stat().st_mode) == 0o700
    assert list((home / "snap" / "chromium" / "common").iterdir()) == []


def test_a_chromium_snap_whose_common_folder_is_a_file_is_a_pdf_error(tmp_path, monkeypatch):
    _, _, home = fake_snap(tmp_path, monkeypatch)
    (home / "snap" / "chromium").mkdir(parents=True)
    (home / "snap" / "chromium" / "common").write_text("not a folder", encoding="utf-8")
    with pytest.raises(pdf.PdfError, match=f"cannot make a temporary folder in {home}/snap/chromium/common"):
        pdf.write_pdf(HTML, tmp_path / "out.pdf")


def test_a_chromium_snap_for_a_user_with_no_passwd_entry_is_a_pdf_error(tmp_path, monkeypatch):
    fake_snap(tmp_path, monkeypatch)

    def no_entry():
        raise KeyError("getpwuid(): uid not found: 4242")

    monkeypatch.setattr(pdf, "_passwd_home", no_entry)
    with pytest.raises(pdf.PdfError, match="has no home in the passwd file"):
        pdf.write_pdf(HTML, tmp_path / "out.pdf")
