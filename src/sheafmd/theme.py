"""
sheafmd.theme — a theme is a folder (SPEC 4.5, 6.4).

    theme.toml     name, and optionally wordmark, tagline, pdf_footer, [[font]] tables
    theme.css      replaces the plain theme's stylesheet; the base stylesheet comes first
    fonts/         optional

`plain` ships inside the package. Any other theme is a folder named by a path,
relative to the root when it comes from `.sheaf.toml`. Nothing in the code compares a
theme's name to a string: a theme is only what its folder says.

A font that is missing, outside the theme's folder, or does not convert is reported
loudly, never silently: a page that falls back to a system face looks almost right,
which is how an off-theme document reaches a client unnoticed.
"""
import base64
import hashlib
import io
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .config import ConfigError, _stderr, read_toml

BUILTIN = Path(__file__).resolve().parent / "themes"
THEME_KEYS = {"name": str, "wordmark": str, "tagline": str, "pdf_footer": str, "font": list}
FONT_KEYS = {"family": str, "file": str, "weight": str, "style": str}
FONT_SUFFIXES = {".ttf", ".otf", ".woff2"}


@dataclass(frozen=True)
class Font:
    family: str
    file: str
    weight: str = "400"
    style: str = "normal"


@dataclass(frozen=True)
class Theme:
    name: str
    css: str
    fonts: tuple[Font, ...] = ()
    wordmark: str = ""
    tagline: str = ""
    pdf_footer: str = ""
    folder: Path | None = field(default=None, compare=False)


def _builtin_names() -> list[str]:
    return sorted(p.name for p in BUILTIN.iterdir() if (p / "theme.toml").is_file())


def _folder(spec: str, root: Path | None) -> Path:
    """The folder a spec names: a built-in name, else a path (relative to the root)."""
    # A built-in is in the package: a spec that cannot be looked at is no built-in.
    if os.path.isfile(BUILTIN / spec / "theme.toml") and "/" not in spec and "\\" not in spec:
        return BUILTIN / spec
    try:
        p = Path(spec).expanduser()
    except RuntimeError:                  # "~nobody/x" with no such user: read it as written
        p = Path(spec)
    return p if p.is_absolute() else (Path(root) if root else Path.cwd()) / p


def load_theme(spec: str, root: Path | None = None, warn=None) -> Theme:
    """Read the theme `spec` names. Raises ConfigError naming both the spec as given
    and the path it was looked for at."""
    folder = _folder(spec, root)
    toml = folder / "theme.toml"
    try:
        is_folder, has_toml = paths.is_dir(folder), paths.is_file(toml)
    except OSError as e:                  # a folder on the way may not be entered: it may well be there
        raise ConfigError(
            f"theme {spec!r}: the folder {folder} cannot be entered: {e.strerror or e}") from None
    if not is_folder:
        raise ConfigError(f"theme {spec!r}: there is no folder at {folder} "
                          f"(built-in themes: {', '.join(_builtin_names())})")
    if not has_toml:
        raise ConfigError(f"theme {spec!r}: the folder {folder} has no theme.toml ({toml})")
    data = read_toml(toml, THEME_KEYS, warn)
    fonts = []
    for i, table in enumerate(data.get("font", []), 1):
        if not isinstance(table, dict):
            raise ConfigError(f"{toml}: font #{i} must be a [[font]] table")
        for k, v in table.items():
            if k not in FONT_KEYS:
                (warn or _stderr)(f"  ! unknown key '{k}' in [[font]] of {toml}")
            elif not isinstance(v, str):
                raise ConfigError(f"{toml}: font #{i}: '{k}' must be text, not {v!r}")
        if not table.get("family") or not table.get("file"):
            raise ConfigError(f"{toml}: font #{i} needs 'family' and 'file'")
        fonts.append(Font(family=table["family"], file=table["file"],
                          weight=table.get("weight", "400"), style=table.get("style", "normal")))
    css_file = folder / "theme.css"
    try:
        css = css_file.read_text(encoding="utf-8") if css_file.is_file() else ""
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"{css_file}: cannot be read ({e})")
    if "</style" in css.lower():
        # The stylesheet is pasted into a <style> element; this would end it.
        raise ConfigError(f"{css_file}: contains '</style', which would end the page's stylesheet")
    return Theme(name=data.get("name") or folder.name, css=css, fonts=tuple(fonts),
                 wordmark=data.get("wordmark", ""), tagline=data.get("tagline", ""),
                 pdf_footer=data.get("pdf_footer", ""), folder=folder)


def _woff2(src: Path) -> bytes:
    raw = src.read_bytes()
    if src.suffix.lower() == ".woff2":
        if raw[:4] != b"wOF2":
            raise ValueError("not a WOFF2 file")
        return raw
    cached = paths.cache_dir() / "fonts" / (hashlib.sha256(raw).hexdigest()[:24] + ".woff2")
    if cached.is_file() and cached.stat().st_size:
        return cached.read_bytes()
    from fontTools.ttLib import TTFont      # only a theme that ships fonts needs it
    font = TTFont(io.BytesIO(raw))
    font.flavor = "woff2"
    buf = io.BytesIO()
    font.save(buf)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(buf.getvalue())
    return buf.getvalue()


def font_css(theme: Theme, log: list[str]) -> str:
    """The @font-face rules of a theme, each font embedded as base64 WOFF2. A font that
    cannot be embedded puts the OFF THEME line in `log`; the page is still rendered."""
    rules = []
    for f in theme.fonts:
        off = f"  ! theme {theme.name}: font {f.file} "
        src = (theme.folder / f.file) if theme.folder else Path(f.file)
        try:
            if theme.folder and theme.folder.resolve() not in src.resolve().parents:
                log.append(off + "is outside the theme folder, this page is OFF THEME")
                continue
            if src.suffix.lower() not in FONT_SUFFIXES:
                log.append(off + "is not a .ttf, .otf or .woff2 file, this page is OFF THEME")
                continue
            if not paths.is_file(src):         # one behind a folder that may not be entered raises
                log.append(off + "missing, this page is OFF THEME")
                continue
            data = _woff2(src)
        except Exception as e:
            log.append(off + f"could not be converted ({e}), this page is OFF THEME")
            continue
        b64 = base64.b64encode(data).decode()
        family = "".join(ch for ch in f.family if ch not in "\\'<\n\r\f")
        rules.append(f"@font-face{{font-family:'{family}';font-style:{_css_word(f.style)};"
                     f"font-weight:{_css_word(f.weight)};font-display:swap;"
                     f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    if theme.fonts and len(rules) == len(theme.fonts):
        log.append(f"  + theme {theme.name}, {len(rules)} font(s) embedded "
                   f"({sum(len(r) for r in rules) // 1024} KB)")
    return "\n".join(rules)


def _css_word(v: str) -> str:
    """A value that goes into a CSS declaration unquoted: letters, digits, spaces."""
    return "".join(c for c in v if c.isalnum() or c in " .-")


def css_string(text: str) -> str:
    """`text` as the inside of a CSS "..." string: no way out of the string, the rule or
    the <style> element."""
    out = []
    for c in text:
        if c in '"\\':
            out.append("\\" + c)
        elif c in "\n\r\f":
            out.append("\\A ")
        elif c in "<>&":
            out.append(f"\\{ord(c):x} ")
        else:
            out.append(c)
    return "".join(out)
