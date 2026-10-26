"""sheafmd.pdf — the rendered page, printed to PDF by headless Chrome.

    find_chrome()                the Chrome or Chromium executable, or None
    print_pdf(html, pdf[, exe])  print an HTML file; returns the line the CLI shows
    write_pdf(html, out)         print an HTML string to `out` (the library function)
    with_print_csp(html)         the copy Chrome prints: the CSP `<meta>` first in its `head`

Everything that goes wrong is a PdfError, with the words the reader needs.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT = 120

# The policy of every copy Chrome prints (6.5, 9.5, 9.9 "Local images"): every fetch directive
# it does not name falls back to 'none', so Chrome loads no file: address and no remote one into
# a PDF, whatever element or property names it. Images and fonts of a copy are data: already.
PRINT_CSP = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
             "style-src 'unsafe-inline'; img-src data:; font-src data:\">")
# What may stand before the first element of `head`: a doctype, the `html` and `head` tags.
_HEAD_OPENS = re.compile(r"\A\s*(?:<!doctype[^>]*>\s*)?(?:<html(?:\s[^>]*)?>\s*)?(?:<head(?:\s[^>]*)?>)?",
                         re.IGNORECASE)


class PdfError(Exception):
    pass


SNAP_BIN = "/snap/bin"


def _passwd_home() -> str:
    import pwd
    return pwd.getpwuid(os.getuid()).pw_dir


def _is_snap(exe: str) -> bool:
    return str(Path(exe).parent) == SNAP_BIN


def _snap_folder(exe: str) -> str:
    """~/snap/NAME/common, the snap's $SNAP_USER_COMMON: the same folder on both sides, and one a
    snap may always read and write. snapd puts it in the home of the passwd entry, not in $HOME,
    and makes it at the snap's first run; made here as snapd makes it when the snap never ran."""
    try:
        home = _passwd_home()
    except KeyError:
        raise PdfError(f"the user {os.getuid()} has no home in the passwd file, "
                       f"where the snap {exe} keeps its folder") from None
    name, snap = Path(exe).name, Path(home) / "snap"
    for d, mode in ((snap, 0o700), (snap / name, 0o755), (snap / name / "common", 0o755)):
        try:
            d.mkdir(mode=mode)
        except FileExistsError:
            pass
        except OSError as e:
            raise PdfError(f"cannot make {d} for the snap {exe}: {e.strerror or e}") from None
    return str(snap / name / "common")


def _scratch(exe: str | None) -> tempfile.TemporaryDirectory:
    """A temporary folder for one print: under TMPDIR, or for a snap in its own folder.

    A snap (SNAP_BIN/NAME, on Ubuntu the only Chromium) runs in its own mount namespace with a
    private /tmp, so a page written under the host's /tmp does not exist for it
    ("net::ERR_FILE_NOT_FOUND"), and the profile it makes there outlives our cleanup."""
    folder = _snap_folder(exe) if exe and _is_snap(exe) else None
    try:
        return tempfile.TemporaryDirectory(prefix="sheaf-", dir=folder)
    except OSError as e:
        raise PdfError(f"cannot make a temporary folder in {folder or tempfile.gettempdir()}: "
                       f"{e.strerror or e}") from None


def find_chrome():
    """Linux package names first, then the macOS app bundle, which is never on
    PATH. Without the bundle a Mac user got "not found" and no URL to click."""
    exe = (shutil.which("google-chrome-stable") or shutil.which("google-chrome")
           or shutil.which("chromium") or shutil.which("chromium-browser"))
    # Neither the macOS bundle nor the Windows install is ever on PATH.
    local = os.environ.get("LOCALAPPDATA", "")
    for cand in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 (local + r"\Google\Chrome\Application\chrome.exe") if local else ""):
        if not exe and cand and Path(cand).exists():
            exe = cand
    return exe


def _install_hint() -> str:
    """What installs Chrome here. sys.platform is read at call time. On Linux apt knows
    google-chrome-stable only once Google's apt source is set up, which its .deb does."""
    if sys.platform.startswith("darwin"):
        return "brew install --cask google-chrome"
    return ("google-chrome-stable comes from Google, for amd64 and arm64, not from Ubuntu or Debian; "
            "its .deb installs it and adds Google's apt source:\n"
            "    download https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb "
            "(_arm64.deb on ARM), then sudo apt install ./google-chrome-stable_current_*.deb")


def print_pdf(html_path: Path, pdf_path: Path, exe: str | None = None) -> str:
    """Print the rendered page to PDF with headless Chrome.

    Chrome rather than a markdown-to-PDF converter, and it is not a close call:
    the charts exist only as inline SVG that this script generates from a
    ```chart block, and the brand faces exist only as base64 inside the page.
    Anything that starts again from the markdown sees a JSON code block where a
    chart should be, and substitutes the fonts. So the PDF is made from the
    rendered HTML, which is the same artefact the reader sees on screen. `exe` is the browser,
    found when not given; for a snap, `html_path` and `pdf_path` must be where it can see them.

    --no-pdf-header-footer suppresses Chrome's own default header, which prints
    the file:// path of the source across the top of every page. On a client
    document that is an internal path leak.
    """
    exe = exe or find_chrome()
    if not exe:
        raise PdfError("Chrome or Chromium is needed to write a PDF and neither "
                       "is installed.\n    " + _install_hint())
    with _scratch(exe) as prof:
        try:
            r = subprocess.run(
                [exe, "--headless", "--disable-gpu", "--no-sandbox",
                 f"--user-data-dir={prof}",
                 "--no-pdf-header-footer",
                 "--print-to-pdf-no-header",
                 f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            raise PdfError(f"Chrome timed out after {TIMEOUT} seconds.") from None
        except OSError as e:
            raise PdfError(f"Chrome could not be started ({e.strerror or e}): {exe}") from None
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        output = r.stdout.decode("utf-8", "replace")[-400:]
        if _is_snap(exe):
            output = (output.rstrip("\n") + f"\n    {exe} is a snap, with a /tmp of its own; it was given "
                    f"the page in {html_path.parent}. Chrome from Google is not a snap:\n    " + _install_hint())
        raise PdfError("Chrome produced no PDF.\n    " + output)
    return f"  = {pdf_path}  ({pdf_path.stat().st_size // 1024} KB)"


def with_print_csp(html: str) -> str:
    """`html` with PRINT_CSP as the first element of its `head`. A meta policy covers only what
    comes after it, so it goes before everything else in `head`; where the page has no `head`
    tag the browser opens one for it, and the meta is still its first element."""
    at = _HEAD_OPENS.match(html).end()
    return html[:at] + PRINT_CSP + html[at:]


def write_pdf(html: str, out: Path) -> None:
    """Print an HTML string to the PDF file `out`. Raises PdfError.

    The copy Chrome is handed carries PRINT_CSP first in its `head`, in loopback mode as in
    proxy mode, so a `url(file:…)` in a `style` does not print a file of the machine (6.5).
    Chrome prints into a temporary folder first and the finished file replaces `out`
    in one step, so a PDF that was there before cannot pass for the new one when
    Chrome fails, and a half-written one is never left to be sent."""
    out = Path(out)
    exe = find_chrome()
    with _scratch(exe) as tmp:
        page, made = Path(tmp) / "page.html", Path(tmp) / "page.pdf"
        page.write_text(with_print_csp(html), encoding="utf-8")
        print_pdf(page, made, exe)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            fd, sibling = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".sheaf-tmp")
        except OSError as e:
            raise PdfError(f"cannot write {out}: {e.strerror or e}") from None
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(made.read_bytes())
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(sibling, 0o666 & ~umask)
            os.replace(sibling, out)
        except BaseException as e:
            try:
                os.unlink(sibling)
            except OSError:
                pass
            if isinstance(e, OSError):
                raise PdfError(f"cannot write {out}: {e.strerror or e}") from None
            raise
