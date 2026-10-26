"""References that must resolve in every tree (SPEC 23 builds the new repo from this tree).

A comment or a docstring that names a Python file names one that exists, and a relative link in the
top-level documents names a file or a folder of the repo. The files of the render-doc this one
replaces (`render-doc.py`, `render_doc_*.py`) are cited as history and are left out, and SPEC.md is
not read for the first check: its tables cite them too."""
import ast
import io
import os
import re
import tokenize
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
PRUNE = {"__pycache__", ".pytest_cache", "node_modules", "corpus"}
TEXT_SUFFIXES = {".py", ".js", ".css", ".md", ".yml", ".toml", ".sh"}
PY_FILE = re.compile(r"(?<![\w.-])((?:[\w.-]+/)*[A-Za-z_][\w-]*\.py)\b")
OLD_TOOL = re.compile(r"render[-_]doc(?:_\w+)?\.py")
LINK = re.compile(r"\]\(<?((?:[^()\s>]|\([^()\s>]*\))+)>?(?:\s+\"[^\"]*\")?\)|^\[[^\]]+\]:\s*<?(\S+?)>?\s*$", re.M)
FENCE = re.compile(r"\s*(`{3,}|~{3,})")


def text_files(*roots):
    for top in roots:
        top = ROOT / top
        if top.is_file():
            yield top
            continue
        for folder, dirs, names in os.walk(top):
            dirs[:] = sorted(d for d in dirs if d not in PRUNE)
            for name in sorted(names):
                if Path(name).suffix in TEXT_SUFFIXES:
                    yield Path(folder) / name


def prose_lines(path):
    """(line number, text) of what a person wrote about the code: the comments and the docstrings
    of a Python file (a string that is data, like a fixture, is not), every line of any other file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix != ".py":
        yield from enumerate(text.split("\n"), 1)
        return
    try:
        tree = ast.parse(text)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, tokenize.TokenError):
        yield from enumerate(text.split("\n"), 1)
        return
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                for i, line in enumerate(doc.split("\n")):
                    yield node.body[0].lineno + i, line
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            yield tok.start[0], tok.string


def missing_python_files(text, have):
    """The `.py` files `text` names that are not among `have` (file names), the old tool's aside."""
    names = (m.group(1) for m in PY_FILE.finditer(text))
    return [n for n in names if n.rsplit("/", 1)[-1] not in have and not OLD_TOOL.fullmatch(n.rsplit("/", 1)[-1])]


def prose_of_markdown(text):
    """The text of a markdown file outside its fenced code (any length of fence, indented or not) and
    outside inline code: the examples there are not links."""
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)
        elif fence is not None and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                and not line.strip().strip(fence[0]):
            fence = None
        elif fence is None:
            out.append(re.sub(r"`[^`\n]*`", "", line))
    return "\n".join(out)


def dangling_links(text, base):
    """The relative link targets of a markdown text that name nothing inside `base`: a file or a
    folder of it (a fragment and a query are cut, a percent-escape is read), not an absolute path."""
    base = base.resolve()
    out = []
    for inline, reference in LINK.findall(prose_of_markdown(text)):
        target = inline or reference
        if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
            continue
        path = unquote(re.split(r"[#?]", target, maxsplit=1)[0])
        dest = (base / path).resolve()
        if path.startswith("/") or base not in (dest, *dest.parents) or not dest.exists():
            out.append(target)
    return out


def test_the_detector_finds_a_python_file_that_is_not_there_and_leaves_the_rest():
    have = {"cli.py", "test_references.py"}
    text = ("see " + "test_" + "nowhere.py, hub/" + "nowhere.py and cli.py, hub/cli.py, "
            "test_references.py; render_doc_source.py and render-doc.py are the old tool's")
    assert missing_python_files(text, have) == ["test_nowhere.py", "hub/nowhere.py"]


def test_the_detector_reads_the_comments_and_the_docstrings_of_a_python_file_and_not_its_data(tmp_path):
    f = tmp_path / "x.py"
    f.write_text('"""A module that cites a_doc.py."""\n\n# and a_comment.py\nNAME = "a_string.py"\n', encoding="utf-8")
    assert sorted(t for _, t in prose_lines(f) if ".py" in t) == ["# and a_comment.py", "A module that cites a_doc.py."]


def test_the_detector_finds_a_link_to_what_is_not_there_and_leaves_the_rest(tmp_path):
    for name in ("README.md", "my file.md", "a_(b).md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    text = ("[gone](nowhere.md) [here](README.md#sheaf) [site](https://example.com/x.md) [part](#top)\n"
            "[escaped](my%20file.md) [query](README.md?x=1) [parens](a_(b).md) [folder](docs/)\n"
            "[outside](../README.md) [absolute](/etc/hostname) [angle](<my file.md>)\n"
            "[ref]: nowhere-either.md\n"
            "`[example](nowhere.md)`\n"
            "````\n[example](nowhere.md)\n```\n[still in the long fence](nowhere.md)\n````\n"
            "   ```\n   [indented](nowhere.md)\n   ```\n"
            "[after](nowhere-after.md)\n")
    assert dangling_links(text, tmp_path) == ["nowhere.md", "../README.md", "/etc/hostname",
                                              "nowhere-either.md", "nowhere-after.md"]


def test_every_python_file_named_in_a_comment_or_a_docstring_exists():
    have = {p.name for top in ("src", "tests", "tools") for p in (ROOT / top).rglob("*.py")}
    bad = []
    for path in text_files("src", "tests", "tools", "README.md", "GLOSSARY.md"):
        for n, line in prose_lines(path):
            bad += [f"{path.relative_to(ROOT)}:{n}: {name}" for name in missing_python_files(line, have)]
    assert not bad, "\n".join(bad)


def test_every_relative_link_of_the_top_level_documents_names_a_file_of_the_repo():
    bad = []
    for doc in ("README.md", "SPEC.md", "GLOSSARY.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        bad += [f"{doc}: {target}" for target in dangling_links(text, ROOT)]
    assert not bad, "\n".join(bad)
