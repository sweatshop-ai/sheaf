"""Themes (SPEC 4.5, 6.4): a folder with theme.toml and theme.css, fonts embedded as WOFF2."""
import base64
import hashlib
import io
import re
from pathlib import Path

import fontTools.ttLib
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from sheafmd import paths, theme
from sheafmd.config import ConfigError
from sheafmd.theme import Font, Theme, css_string, font_css, load_theme

# One @font-face rule exactly as font_css writes it: nothing in the family, style or
# weight can be anything but plain text inside its own declaration.
RULE = re.compile(
    r"@font-face\{font-family:'(?P<family>[^'\\\n\r\f]*)';"
    r"font-style:(?P<style>[A-Za-z0-9 .\-]*);font-weight:(?P<weight>[A-Za-z0-9 .\-]*);"
    r"font-display:swap;src:url\(data:font/woff2;base64,(?P<b64>[A-Za-z0-9+/=]+)\) "
    r"format\('woff2'\)\}")


# ── helpers ────────────────────────────────────────────────────────────────

def build_ttf(path: Path, family: str = "Fam", advance: int = 600) -> bytes:
    """A real, tiny TrueType font: two glyphs. `family` and `advance` make two
    builds differ in their bytes."""
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({0x41: "A"})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((0, 700))
    pen.lineTo((advance - 100, 700))
    pen.lineTo((advance - 100, 0))
    pen.closePath()
    glyph = pen.glyph()
    fb.setupGlyf({".notdef": glyph, "A": glyph})
    fb.setupHorizontalMetrics({".notdef": (advance, 0), "A": (advance, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(path))
    return path.read_bytes()


def build_woff2(path: Path, family: str = "Fam", advance: int = 600) -> bytes:
    ttf = path.with_name(path.name + ".src.ttf")
    build_ttf(ttf, family, advance)
    font = fontTools.ttLib.TTFont(str(ttf))
    font.flavor = "woff2"
    path.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(path))
    ttf.unlink()
    return path.read_bytes()


def make_theme_folder(folder: Path, toml: str = 'name = "brand"\n', css: str | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "theme.toml").write_text(toml, encoding="utf-8")
    if css is not None:
        (folder / "theme.css").write_text(css, encoding="utf-8")
    return folder


def theme_of(folder: Path, *fonts: Font, name: str = "brand") -> Theme:
    return Theme(name=name, css="", fonts=tuple(fonts), folder=folder)


def rules_of(css: str) -> list[re.Match]:
    return list(RULE.finditer(css))


def embedded_bytes(rule: re.Match) -> bytes:
    return base64.b64decode(rule["b64"])


def cached_fonts() -> list[Path]:
    d = paths.cache_dir() / "fonts"
    return sorted(d.glob("*")) if d.exists() else []


# ── the built-in theme ─────────────────────────────────────────────────────

def test_plain_is_built_in_with_a_stylesheet_and_nothing_else():
    t = load_theme("plain")
    assert t.name == "plain"
    assert t.css.strip() and t.css == (theme.BUILTIN / "plain" / "theme.css").read_text(encoding="utf-8")
    assert t.fonts == ()
    assert t.wordmark == "" and t.pdf_footer == "" and t.tagline == ""
    assert t.folder == theme.BUILTIN / "plain"


def test_plain_does_not_depend_on_the_root_or_the_current_folder(tmp_path, monkeypatch):
    decoy = make_theme_folder(tmp_path / "somewhere" / "plain", 'name = "decoy"\n', "x{}")
    monkeypatch.chdir(decoy.parent)
    for root in (None, tmp_path / "somewhere", tmp_path):
        t = load_theme("plain", root)
        assert t.name == "plain" and t.folder == theme.BUILTIN / "plain" and t.css != "x{}"


def test_a_folder_named_plain_in_the_root_does_not_shadow_the_built_in(tmp_path):
    root = tmp_path / "proj"
    make_theme_folder(root / "plain", 'name = "shadow"\nwordmark = "SHADOW"\n', "x{}")
    t = load_theme("plain", root)
    assert (t.name, t.wordmark, t.folder) == ("plain", "", theme.BUILTIN / "plain")
    assert t.css == (theme.BUILTIN / "plain" / "theme.css").read_text(encoding="utf-8")


def test_the_same_folder_is_reached_by_naming_it_as_a_path(tmp_path):
    root = tmp_path / "proj"
    make_theme_folder(root / "plain", 'name = "shadow"\n', "x{}")
    assert load_theme("./plain", root).name == "shadow"
    assert load_theme(str(root / "plain"), None).css == "x{}"


# ── a theme folder ─────────────────────────────────────────────────────────

THEME_TOML = '''\
name = "brand"
wordmark = "EXAMPLE CO"
tagline = "Plain words for good pages"
pdf_footer = "EXAMPLE CO / Ada"

[[font]]
family = "Fam"
file = "fonts/Fam.ttf"
weight = "400 700"
style = "italic"
'''
THEME_CSS = "body{color:#123456}\n"


def test_a_theme_folder_loads_every_field(tmp_path):
    folder = make_theme_folder(tmp_path / "proj" / "brand", THEME_TOML, THEME_CSS)
    t = load_theme(str(folder))
    assert t.name == "brand"
    assert t.css == THEME_CSS
    assert t.wordmark == "EXAMPLE CO"
    assert t.tagline == "Plain words for good pages"
    assert t.pdf_footer == "EXAMPLE CO / Ada"
    assert t.fonts == (Font(family="Fam", file="fonts/Fam.ttf", weight="400 700", style="italic"),)
    assert t.folder == folder


def test_a_font_without_weight_or_style_is_400_normal(tmp_path):
    folder = make_theme_folder(tmp_path / "brand", '[[font]]\nfamily = "Fam"\nfile = "a.woff2"\n')
    assert load_theme(str(folder)).fonts == (Font("Fam", "a.woff2", "400", "normal"),)


def test_several_fonts_keep_their_order(tmp_path):
    folder = make_theme_folder(tmp_path / "brand", (
        '[[font]]\nfamily = "One"\nfile = "1.woff2"\n[[font]]\nfamily = "Two"\nfile = "2.woff2"\n'))
    assert [f.family for f in load_theme(str(folder)).fonts] == ["One", "Two"]


def test_a_theme_without_a_name_is_named_after_its_folder_and_without_css_has_none(tmp_path):
    folder = make_theme_folder(tmp_path / "grace-theme", "")
    t = load_theme(str(folder))
    assert t.name == "grace-theme" and t.css == ""
    folder = make_theme_folder(tmp_path / "other", 'name = ""\n')
    assert load_theme(str(folder)).name == "other"


def test_a_relative_spec_resolves_against_the_root_not_the_current_folder(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    make_theme_folder(root / ".sheaf" / "theme-brand", 'name = "from-root"\n')
    cwd = tmp_path / "elsewhere"
    make_theme_folder(cwd / ".sheaf" / "theme-brand", 'name = "from-cwd"\n')
    monkeypatch.chdir(cwd)
    t = load_theme(".sheaf/theme-brand", root)
    assert t.name == "from-root" and t.folder == root / ".sheaf" / "theme-brand"


def test_a_bare_word_that_is_not_built_in_is_a_folder_in_the_root(tmp_path):
    root = tmp_path / "proj"
    make_theme_folder(root / "brand", 'name = "b"\n')
    assert load_theme("brand", root).folder == root / "brand"


def test_an_absolute_spec_ignores_the_root(tmp_path):
    folder = make_theme_folder(tmp_path / "abs" / "brand", 'name = "absolute"\n')
    other_root = tmp_path / "proj"
    other_root.mkdir()
    assert load_theme(str(folder), other_root).name == "absolute"
    assert load_theme(str(folder), None).name == "absolute"


def test_without_a_root_a_relative_spec_resolves_against_the_current_folder(tmp_path, monkeypatch):
    make_theme_folder(tmp_path / "proj" / ".sheaf" / "brand", 'name = "from-cwd"\n')
    monkeypatch.chdir(tmp_path / "proj")
    t = load_theme(".sheaf/brand")
    assert t.name == "from-cwd" and t.folder == Path.cwd() / ".sheaf" / "brand"


def test_a_spec_starting_with_a_tilde_is_the_home_folder(tmp_path):
    make_theme_folder(Path.home() / "mytheme", 'name = "home-theme"\n')
    assert Path.home() == tmp_path / "home"          # the conftest home, never the real one
    assert load_theme("~/mytheme").name == "home-theme"


def test_a_spec_with_an_unknown_tilde_user_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_theme("~no-such-user-here/theme", tmp_path)


# ── errors ─────────────────────────────────────────────────────────────────

def test_a_spec_naming_no_folder_names_the_spec_and_the_path_it_looked_at(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(ConfigError) as e:
        load_theme("brand-missing", root)
    msg = str(e.value)
    assert repr("brand-missing") in msg                  # the spec as given
    assert str(root / "brand-missing") in msg            # where it was looked for
    assert "plain" in msg                                # and what does exist


def test_a_missing_relative_spec_without_a_root_names_the_current_folder_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as e:
        load_theme(".sheaf/brand-missing")
    assert repr(".sheaf/brand-missing") in str(e.value)
    assert str(Path.cwd() / ".sheaf" / "brand-missing") in str(e.value)


def test_a_missing_absolute_spec_names_it_as_given_and_as_looked_at(tmp_path):
    spec = str(tmp_path / "nowhere" / "brand")
    with pytest.raises(ConfigError) as e:
        load_theme(spec, tmp_path / "proj")
    assert repr(spec) in str(e.value) and f"at {spec}" in str(e.value)


def test_a_file_where_the_folder_should_be_is_a_missing_folder(tmp_path):
    (tmp_path / "brand").write_text("not a folder")
    with pytest.raises(ConfigError) as e:
        load_theme("brand", tmp_path)
    assert "no folder" in str(e.value) and str(tmp_path / "brand") in str(e.value)


def test_a_folder_without_theme_toml_names_the_folder_and_the_toml_path(tmp_path):
    folder = tmp_path / "proj" / "brand"
    folder.mkdir(parents=True)
    (folder / "theme.css").write_text("body{}")
    with pytest.raises(ConfigError) as e:
        load_theme("brand", tmp_path / "proj")
    msg = str(e.value)
    assert repr("brand") in msg and str(folder) in msg and str(folder / "theme.toml") in msg


def test_a_toml_error_in_theme_toml_names_the_file_and_the_line(tmp_path):
    folder = make_theme_folder(tmp_path / "brand", 'name = "brand"\nwordmark = "X"\ntagline = = "Y"\n')
    with pytest.raises(ConfigError) as e:
        load_theme(str(folder))
    assert str(folder / "theme.toml") in str(e.value)
    assert re.search(r"\bline 3\b", str(e.value)), str(e.value)


@pytest.mark.parametrize("font", [
    'file = "fonts/a.woff2"',
    'family = "Fam"',
    'family = ""\nfile = "fonts/a.woff2"',
    'family = "Fam"\nfile = ""',
    'weight = "400"',
])
def test_a_font_without_family_or_file_is_refused_naming_theme_toml(tmp_path, font):
    folder = make_theme_folder(tmp_path / "brand", f'name = "brand"\n\n[[font]]\n{font}\n')
    with pytest.raises(ConfigError) as e:
        load_theme(str(folder))
    assert str(folder / "theme.toml") in str(e.value) and "'family' and 'file'" in str(e.value)


def test_the_second_font_is_the_one_named_when_it_is_the_incomplete_one(tmp_path):
    folder = make_theme_folder(tmp_path / "brand", (
        '[[font]]\nfamily = "One"\nfile = "1.woff2"\n[[font]]\nfamily = "Two"\n'))
    with pytest.raises(ConfigError) as e:
        load_theme(str(folder))
    assert "font #2" in str(e.value) and str(folder / "theme.toml") in str(e.value)


def test_a_font_value_that_is_not_text_is_refused(tmp_path):
    folder = make_theme_folder(tmp_path / "brand", '[[font]]\nfamily = 5\nfile = "a.woff2"\n')
    with pytest.raises(ConfigError) as e:
        load_theme(str(folder))
    assert str(folder / "theme.toml") in str(e.value) and "'family'" in str(e.value)


@pytest.mark.parametrize("toml", ['font = "x"\n', "[font]\nfamily = \"Fam\"\nfile = \"a.woff2\"\n",
                                  "font = [1]\n"])
def test_font_that_is_not_a_list_of_tables_is_refused_naming_theme_toml(tmp_path, toml):
    folder = make_theme_folder(tmp_path / "brand", toml)
    with pytest.raises(ConfigError) as e:
        load_theme(str(folder))
    assert str(folder / "theme.toml") in str(e.value)


@pytest.mark.parametrize("key", ["name", "wordmark", "tagline", "pdf_footer"])
def test_a_theme_key_of_the_wrong_type_names_the_file_and_the_key(tmp_path, key):
    folder = make_theme_folder(tmp_path / "brand", f"{key} = 5\n")
    with pytest.raises(ConfigError) as e:
        load_theme(str(folder))
    assert str(folder / "theme.toml") in str(e.value) and f"'{key}'" in str(e.value)


def test_an_unknown_key_in_theme_toml_warns_naming_the_file_and_the_key(tmp_path):
    folder = make_theme_folder(tmp_path / "brand", 'name = "brand"\nmotto = "x"\n')
    warned = []
    t = load_theme(str(folder), warn=warned.append)
    assert t.name == "brand"
    assert len(warned) == 1 and str(folder / "theme.toml") in warned[0] and "motto" in warned[0]


def test_an_unknown_key_in_a_font_table_warns_naming_the_file_and_the_key(tmp_path):
    folder = make_theme_folder(tmp_path / "brand", (
        '[[font]]\nfamily = "Fam"\nfile = "a.woff2"\nstretch = "wide"\n'))
    warned = []
    t = load_theme(str(folder), warn=warned.append)
    assert len(t.fonts) == 1
    assert len(warned) == 1 and str(folder / "theme.toml") in warned[0] and "stretch" in warned[0]


def test_the_warning_goes_to_stderr_without_a_warn(tmp_path, capsys):
    folder = make_theme_folder(tmp_path / "brand", 'motto = "x"\n')
    load_theme(str(folder))
    out, err = capsys.readouterr()
    assert out == "" and str(folder / "theme.toml") in err and "motto" in err


@pytest.mark.parametrize("css", [
    "body{}\n</style><script>alert(1)</script>",
    "body{}</STYLE>",
    "/* a */ </Style >",
])
def test_a_stylesheet_that_would_end_the_style_element_is_refused(tmp_path, css):
    folder = make_theme_folder(tmp_path / "brand", css=css)
    with pytest.raises(ConfigError) as e:
        load_theme(str(folder))
    assert str(folder / "theme.css") in str(e.value) and "</style" in str(e.value)


def test_a_stylesheet_with_other_angle_brackets_is_fine(tmp_path):
    css = 'a>b{content:"<b>"}\n/* <!-- --> */'
    folder = make_theme_folder(tmp_path / "brand", css=css)
    assert load_theme(str(folder)).css == css


def test_a_stylesheet_that_is_not_utf8_is_refused_naming_it(tmp_path):
    folder = make_theme_folder(tmp_path / "brand")
    (folder / "theme.css").write_bytes(b"body{content:'\xff\xfe'}")
    with pytest.raises(ConfigError) as e:
        load_theme(str(folder))
    assert str(folder / "theme.css") in str(e.value)


# ── fonts ──────────────────────────────────────────────────────────────────

def test_a_ttf_is_converted_to_woff2_and_embedded(tmp_path):
    folder = tmp_path / "brand"
    build_ttf(folder / "fonts" / "Fam.ttf", family="Fam")
    t = theme_of(folder, Font("Fam", "fonts/Fam.ttf", "400 700", "normal"))
    log = []
    css = font_css(t, log)
    (rule,) = rules_of(css)
    assert css == rule.group(0)
    assert css.startswith("@font-face{font-family:'Fam';font-style:normal;font-weight:400 700;")
    assert "src:url(data:font/woff2;base64," in css
    data = embedded_bytes(rule)
    assert data[:4] == b"wOF2"
    # and it is the font that was given, readable as WOFF2
    back = fontTools.ttLib.TTFont(io.BytesIO(data))
    assert back.flavor == "woff2"
    assert back.getGlyphOrder() == [".notdef", "A"]
    assert back["name"].getDebugName(1) == "Fam"
    assert log == [f"  + theme brand, 1 font(s) embedded ({len(css) // 1024} KB)"]


def test_the_converted_font_is_cached_under_the_cache_folder(tmp_path):
    folder = tmp_path / "brand"
    raw = build_ttf(folder / "fonts" / "Fam.ttf")
    css = font_css(theme_of(folder, Font("Fam", "fonts/Fam.ttf")), [])
    (cached,) = cached_fonts()
    assert cached.parent == paths.cache_dir() / "fonts"
    assert cached.name == hashlib.sha256(raw).hexdigest()[:24] + ".woff2"
    assert cached.read_bytes() == embedded_bytes(rules_of(css)[0])
    assert cached.read_bytes()[:4] == b"wOF2"


def test_a_second_call_uses_the_cache_and_does_not_need_fonttools(tmp_path, monkeypatch):
    folder = tmp_path / "brand"
    build_ttf(folder / "fonts" / "Fam.ttf", family="Fam")
    build_ttf(folder / "fonts" / "Uncached.ttf", family="Uncached", advance=700)
    t = theme_of(folder, Font("Fam", "fonts/Fam.ttf"))
    first = font_css(t, [])

    def refuse(*a, **k):
        raise AssertionError("fontTools was asked to convert")

    monkeypatch.setattr(fontTools.ttLib, "TTFont", refuse)
    log = []
    assert font_css(t, log) == first
    assert log == [f"  + theme brand, 1 font(s) embedded ({len(first) // 1024} KB)"]
    # the patch bites: a font that is not cached is a conversion, and it fails loudly
    log = []
    css = font_css(theme_of(folder, Font("Uncached", "fonts/Uncached.ttf")), log)
    assert css == "" and len(log) == 1 and "could not be converted" in log[0]


def test_a_changed_font_file_is_not_served_from_the_old_cache(tmp_path):
    folder = tmp_path / "brand"
    t = theme_of(folder, Font("Fam", "fonts/Fam.ttf"))
    build_ttf(folder / "fonts" / "Fam.ttf", advance=600)
    first = font_css(t, [])
    build_ttf(folder / "fonts" / "Fam.ttf", advance=800)
    second = font_css(t, [])
    assert first != second
    assert len(cached_fonts()) == 2
    back = fontTools.ttLib.TTFont(io.BytesIO(embedded_bytes(rules_of(second)[0])))
    assert back["hmtx"]["A"][0] == 800


def test_an_empty_cache_file_is_converted_again(tmp_path):
    folder = tmp_path / "brand"
    raw = build_ttf(folder / "fonts" / "Fam.ttf")
    cached = paths.cache_dir() / "fonts" / (hashlib.sha256(raw).hexdigest()[:24] + ".woff2")
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"")
    css = font_css(theme_of(folder, Font("Fam", "fonts/Fam.ttf")), [])
    assert embedded_bytes(rules_of(css)[0])[:4] == b"wOF2"
    assert cached.read_bytes()[:4] == b"wOF2"


def test_a_woff2_is_embedded_as_it_is(tmp_path):
    folder = tmp_path / "brand"
    raw = build_woff2(folder / "fonts" / "Fam.woff2")
    assert raw[:4] == b"wOF2"
    log = []
    css = font_css(theme_of(folder, Font("Fam", "fonts/Fam.woff2", "400", "normal")), log)
    (rule,) = rules_of(css)
    assert embedded_bytes(rule) == raw
    assert cached_fonts() == []                           # nothing was converted
    assert log == [f"  + theme brand, 1 font(s) embedded ({len(css) // 1024} KB)"]


@pytest.mark.parametrize("name,build", [("Fam.TTF", build_ttf), ("Fam.WOFF2", build_woff2)])
def test_the_suffix_is_matched_without_regard_to_case(tmp_path, name, build):
    folder = tmp_path / "brand"
    build(folder / "fonts" / name)
    log = []
    css = font_css(theme_of(folder, Font("Fam", f"fonts/{name}")), log)
    assert len(rules_of(css)) == 1 and embedded_bytes(rules_of(css)[0])[:4] == b"wOF2"
    assert log[0].startswith("  + theme brand, 1 font(s) embedded")


def test_several_fonts_embed_one_rule_each_and_the_log_counts_them(tmp_path):
    folder = tmp_path / "brand"
    build_ttf(folder / "fonts" / "A.ttf", family="A")
    build_woff2(folder / "fonts" / "B.woff2", family="B")
    log = []
    css = font_css(theme_of(folder, Font("A", "fonts/A.ttf"), Font("B", "fonts/B.woff2", "700", "italic")), log)
    rules = rules_of(css)
    assert [(r["family"], r["weight"], r["style"]) for r in rules] == [("A", "400", "normal"),
                                                                        ("B", "700", "italic")]
    assert css.count("\n") == 1
    assert log == [f"  + theme brand, 2 font(s) embedded ({len(css) // 1024} KB)"]


def test_a_theme_without_fonts_gives_no_css_and_no_log(tmp_path):
    log = []
    assert font_css(theme_of(tmp_path), log) == ""
    assert log == []
    assert font_css(load_theme("plain"), log) == "" and log == []


def test_fonts_declared_in_theme_toml_reach_the_page_css(tmp_path):
    folder = make_theme_folder(tmp_path / "proj" / "brand", THEME_TOML, THEME_CSS)
    build_ttf(folder / "fonts" / "Fam.ttf")
    log = []
    css = font_css(load_theme("brand", tmp_path / "proj"), log)
    (rule,) = rules_of(css)
    assert (rule["family"], rule["style"], rule["weight"]) == ("Fam", "italic", "400 700")
    assert embedded_bytes(rule)[:4] == b"wOF2" and log[0].startswith("  + theme brand, 1 font(s)")


def test_a_missing_font_is_logged_and_gives_no_rule_while_the_others_still_embed(tmp_path):
    folder = tmp_path / "brand"
    raw = build_woff2(folder / "fonts" / "Good.woff2", family="Good")
    log = []
    css = font_css(theme_of(folder, Font("Gone", "fonts/x.ttf"), Font("Good", "fonts/Good.woff2")), log)
    assert log == ["  ! theme brand: font fonts/x.ttf missing, this page is OFF THEME"]
    (rule,) = rules_of(css)
    assert rule["family"] == "Good" and embedded_bytes(rule) == raw
    assert "Gone" not in css


def test_a_font_behind_a_folder_that_may_not_be_entered_is_logged_with_the_reason_not_as_missing(
        tmp_path, closed):
    folder = tmp_path / "brand"
    build_woff2(folder / "fonts" / "Shut.woff2", family="Shut")
    closed(folder / "fonts")
    log = []
    assert font_css(theme_of(folder, Font("Shut", "fonts/Shut.woff2")), log) == ""
    assert len(log) == 1 and "missing" not in log[0]
    assert log[0].startswith("  ! theme brand: font fonts/Shut.woff2 could not be converted (")
    assert "Permission denied" in log[0] and log[0].endswith(", this page is OFF THEME")


def test_a_missing_woff2_is_logged_the_same_way(tmp_path):
    folder = tmp_path / "brand"
    folder.mkdir()
    log = []
    css = font_css(theme_of(folder, Font("Gone", "fonts/x.woff2")), log)
    assert css == ""
    assert log == ["  ! theme brand: font fonts/x.woff2 missing, this page is OFF THEME"]


@pytest.mark.parametrize("content", [b"this is not a font", b""])
def test_a_ttf_that_is_not_a_font_is_logged_as_not_converted(tmp_path, content):
    folder = tmp_path / "brand"
    (folder / "fonts").mkdir(parents=True)
    (folder / "fonts" / "bad.ttf").write_bytes(content)
    log = []
    css = font_css(theme_of(folder, Font("Bad", "fonts/bad.ttf")), log)
    assert css == ""
    assert len(log) == 1
    assert log[0].startswith("  ! theme brand: font fonts/bad.ttf could not be converted (")
    assert log[0].endswith(", this page is OFF THEME") and "could not be converted" in log[0]
    assert cached_fonts() == []


@pytest.mark.parametrize("make", [
    lambda p: p.write_bytes(b"not a woff2 file at all"),
    lambda p: p.write_bytes(b""),
    lambda p: build_ttf(p),                          # a TrueType font under a .woff2 name
])
def test_a_woff2_that_does_not_start_with_the_woff2_signature_is_logged_as_not_converted(tmp_path, make):
    folder = tmp_path / "brand"
    (folder / "fonts").mkdir(parents=True)
    make(folder / "fonts" / "bad.woff2")
    log = []
    css = font_css(theme_of(folder, Font("Bad", "fonts/bad.woff2")), log)
    assert css == ""
    assert len(log) == 1 and "fonts/bad.woff2 could not be converted" in log[0]
    assert "not a WOFF2 file" in log[0] and log[0].endswith("this page is OFF THEME")


@pytest.mark.parametrize("secret_name", ["secret.ttf", "secret.woff2"])
def test_a_font_outside_the_theme_folder_is_refused_and_its_bytes_do_not_leak(tmp_path, secret_name):
    folder = tmp_path / "proj" / "theme"
    folder.mkdir(parents=True)
    build = build_woff2 if secret_name.endswith("woff2") else build_ttf
    secret = build(tmp_path / "proj" / secret_name, family="Secret")
    assert (tmp_path / "proj" / secret_name).is_file()
    log = []
    css = font_css(theme_of(folder, Font("Secret", f"../{secret_name}")), log)
    assert log == [f"  ! theme brand: font ../{secret_name} is outside the theme folder, "
                   f"this page is OFF THEME"]
    assert css == ""
    output = css + "\n".join(log)
    assert base64.b64encode(secret)[:60].decode() not in output
    assert "base64," not in output


def test_an_absolute_font_path_outside_the_theme_folder_is_refused(tmp_path):
    folder = tmp_path / "theme"
    folder.mkdir()
    secret = tmp_path / "secret.woff2"
    build_woff2(secret)
    log = []
    css = font_css(theme_of(folder, Font("Secret", str(secret))), log)
    assert css == "" and len(log) == 1 and "is outside the theme folder" in log[0]


def test_a_folder_that_only_shares_the_start_of_the_name_is_outside(tmp_path):
    folder = tmp_path / "theme"
    folder.mkdir()
    build_woff2(tmp_path / "theme-evil" / "x.woff2")
    log = []
    css = font_css(theme_of(folder, Font("X", "../theme-evil/x.woff2")), log)
    assert css == "" and "is outside the theme folder" in log[0]


def test_a_symlink_inside_the_theme_folder_pointing_outside_is_refused(tmp_path):
    folder = tmp_path / "theme"
    (folder / "fonts").mkdir(parents=True)
    secret = tmp_path / "outside" / "secret.woff2"
    build_woff2(secret)
    (folder / "fonts" / "link.woff2").symlink_to(secret)
    log = []
    css = font_css(theme_of(folder, Font("Secret", "fonts/link.woff2")), log)
    assert css == ""
    assert log == ["  ! theme brand: font fonts/link.woff2 is outside the theme folder, "
                   "this page is OFF THEME"]


def test_a_symlinked_folder_inside_the_theme_folder_pointing_outside_is_refused(tmp_path):
    folder = tmp_path / "theme"
    folder.mkdir()
    build_woff2(tmp_path / "outside" / "secret.woff2")
    (folder / "fonts").symlink_to(tmp_path / "outside", target_is_directory=True)
    log = []
    css = font_css(theme_of(folder, Font("Secret", "fonts/secret.woff2")), log)
    assert css == "" and len(log) == 1 and "is outside the theme folder" in log[0]


def test_a_symlink_that_stays_inside_the_theme_folder_is_fine(tmp_path):
    folder = tmp_path / "theme"
    raw = build_woff2(folder / "real" / "Fam.woff2")
    (folder / "fonts").mkdir()
    (folder / "fonts" / "alias.woff2").symlink_to(folder / "real" / "Fam.woff2")
    css = font_css(theme_of(folder, Font("Fam", "fonts/alias.woff2")), [])
    assert embedded_bytes(rules_of(css)[0]) == raw


@pytest.mark.parametrize("name", ["x.txt", "x.woff", "x"])
def test_a_file_that_is_not_a_font_suffix_is_refused(tmp_path, name):
    folder = tmp_path / "brand"
    (folder / "fonts").mkdir(parents=True)
    (folder / "fonts" / name).write_text("some text")
    log = []
    css = font_css(theme_of(folder, Font("X", f"fonts/{name}")), log)
    assert css == ""
    assert log == [f"  ! theme brand: font fonts/{name} is not a .ttf, .otf or .woff2 file, "
                   f"this page is OFF THEME"]


def test_a_missing_font_of_a_theme_loaded_from_a_folder_is_reported_with_the_theme_name(tmp_path):
    folder = make_theme_folder(tmp_path / "brand", THEME_TOML, THEME_CSS)   # no fonts/Fam.ttf on disk
    log = []
    css = font_css(load_theme(str(folder)), log)
    assert css == ""
    assert log == ["  ! theme brand: font fonts/Fam.ttf missing, this page is OFF THEME"]


def _evil_rule(tmp_path, family: str, weight: str = "400", style: str = "normal") -> str:
    folder = tmp_path / "brand"
    build_woff2(folder / "fonts" / "a.woff2")
    log = []
    css = font_css(theme_of(folder, Font(family, "fonts/a.woff2", weight, style)), log)
    assert len(log) == 1 and log[0].startswith("  + theme brand, 1 font(s) embedded")
    return css


def test_a_family_with_a_quote_cannot_close_the_string_or_the_rule(tmp_path):
    css = _evil_rule(tmp_path, "Evil'; } body{x:y")
    # The quote is gone; what is left is plain text inside the one pair of quotes.
    assert css.startswith("@font-face{font-family:'Evil; } body{x:y';font-style:normal;"
                          "font-weight:400;font-display:swap;src:url(data:font/woff2;base64,")
    assert css.count("'") == 4                           # the family's two and format('woff2')
    (rule,) = rules_of(css)
    assert rule["family"] == "Evil; } body{x:y"
    assert rule.group(0) == css                         # the whole output is that one rule


@pytest.mark.parametrize("family,kept", [
    ("Back\\slash", "Backslash"),
    ("Ends with\\", "Ends with"),                        # so no \' can swallow the closing quote
    ("Two'Quotes'", "TwoQuotes"),
    ("</style><script>x</script>", "/style>script>x/script>"),
    ("Fine Name 2", "Fine Name 2"),
])
def test_a_family_name_loses_quotes_backslashes_and_angle_openers(tmp_path, family, kept):
    css = _evil_rule(tmp_path, family)
    (rule,) = rules_of(css)
    assert rule["family"] == kept
    assert "<" not in css and "\\" not in css and "</style" not in css.lower()


def test_a_weight_or_style_cannot_carry_a_declaration_either(tmp_path):
    css = _evil_rule(tmp_path, "Fam", weight="400; } body{x:y", style="italic}/*")
    (rule,) = rules_of(css)                              # the shape holds: nothing broke out
    assert rule.group(0) == css
    assert ";" not in rule["weight"] and "}" not in rule["weight"] and "{" not in rule["weight"]
    assert ";" not in rule["style"] and "}" not in rule["style"] and "/" not in rule["style"]


@pytest.mark.parametrize("family", ["A\nB", "A\rB", "A\fB"])
def test_a_family_with_a_line_break_cannot_break_the_string(tmp_path, family):
    css = _evil_rule(tmp_path, family)
    assert rules_of(css) and rules_of(css)[0].group(0) == css


# ── css_string ─────────────────────────────────────────────────────────────

HEX = "0123456789abcdefABCDEF"


def read_css_string(src: str, quote: str = '"') -> tuple[str, int]:
    """Read a CSS string whose opening quote is already consumed. Returns (decoded,
    index just past the closing quote). A raw line break before the closing quote is a
    bad string (CSS Syntax), and so is no closing quote at all."""
    out, i = [], 0
    while i < len(src):
        c = src[i]
        if c == quote:
            return "".join(out), i + 1
        if c in "\n\r\f":
            raise ValueError(f"raw line break at {i}")
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        j = i
        while j < len(src) and j - i < 6 and src[j] in HEX:
            j += 1
        if j > i:                                        # backslash + hex digits + one optional space
            out.append(chr(int(src[i:j], 16)))
            i = j
            if i < len(src) and src[i] in " \t\n\r\f":
                i += 1
        elif i < len(src):                               # backslash + any other char = that char
            out.append(src[i])
            i += 1
    raise ValueError("the string never closes")


def wrapped(text: str) -> str:
    """`content:"<css_string(text)>"` and what the rule after it would be."""
    return f'content:"{css_string(text)}"'


def test_the_css_decoder_itself_follows_the_css_rules():
    assert read_css_string(r'a\"b\\c\3c d\41 e"') == ('a"b\\c<dAe', len(r'a\"b\\c\3c d\41 e"'))
    assert read_css_string('x" y')[1] == 2                # stops at the first unescaped quote
    with pytest.raises(ValueError):
        read_css_string('a\nb"')
    with pytest.raises(ValueError):
        read_css_string('never closed')


ALL_BAD = 'He said "hi" \\ back\nline <b>&amp;</b> > a\nbad <abc \\41 x \\\\ "quoted" end'


def test_every_dangerous_character_is_neutralised_and_the_string_decodes_back():
    out = css_string(ALL_BAD)
    for raw in ("<", ">", "&", "\n", "\r", "\f"):
        assert raw not in out, repr(raw)
    assert "</style" not in out.lower()
    rule = wrapped(ALL_BAD)
    inner = rule[len('content:"'):]                     # what follows the opening quote
    decoded, end = read_css_string(inner)
    assert decoded == ALL_BAD
    assert inner[end:] == ""                              # the string ended at the last character


@pytest.mark.parametrize("ch", ['"', "\\", "<", ">", "&", "\n"])
def test_each_character_alone_round_trips_and_cannot_end_the_string(ch):
    text = f"a{ch}b{ch}"
    inner = f'{css_string(text)}"; color:red'            # whatever follows must stay outside
    decoded, end = read_css_string(inner)
    assert decoded == text
    assert inner[end:] == "; color:red"


@pytest.mark.parametrize("ch", ["<", ">", "&", "\n", "\r", "\f"])
def test_no_raw_line_break_or_angle_bracket_or_ampersand_is_left(ch):
    assert ch not in css_string(f"x{ch}y")


@pytest.mark.parametrize("ch", ["\r", "\f"])
def test_a_carriage_return_or_form_feed_becomes_a_line_feed(ch):
    decoded, _ = read_css_string(css_string(f"a{ch}b") + '"')
    assert decoded == "a\nb"


def test_a_hex_escape_does_not_swallow_the_character_after_it():
    # "\n" then "bad": a bare \A followed by b, a, d would read as one hex number.
    for text in ("\nbad", "<abc", "&1", "\n\n", ">>"):
        decoded, _ = read_css_string(css_string(text) + '"')
        assert decoded == text, repr(text)


def test_a_style_end_tag_cannot_come_out_of_a_string():
    out = css_string("</style><script>alert(1)</script>")
    assert "<" not in out and "</style" not in out.lower()
    assert read_css_string(out + '"')[0] == "</style><script>alert(1)</script>"


def test_ordinary_text_is_left_alone():
    assert css_string("") == ""
    assert css_string("EXAMPLE CO / Ada, page 1: ünï 日本 'single' ok") == \
        "EXAMPLE CO / Ada, page 1: ünï 日本 'single' ok"


def test_css_string_is_what_a_footer_needs_inside_a_content_declaration():
    footer = 'Ada "the" <Example> & Co\\Ltd'
    rule = '@media print{@page{@bottom-left{content:"%s"}}}' % css_string(footer)
    start = rule.index('content:"') + len('content:"')
    decoded, end = read_css_string(rule[start:])
    assert decoded == footer
    assert rule[start + end:] == "}}}"
    assert "<" not in rule and ">" not in rule and "&" not in rule
