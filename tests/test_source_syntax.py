"""Every source file parses on the oldest Python sheaf supports (3.11). A pull request runs 3.13 only, and
`ast.parse(feature_version=(3, 11))` still accepts what PEP 701 allowed in 3.12, so on a newer interpreter the
f-strings are read token by token for the two things 3.11 refuses inside a replacement field: a backslash, and
the enclosing string's own quote."""
import sys
import tokenize
from pathlib import Path

import pytest

SOURCES = sorted((Path(__file__).parent.parent / "src" / "sheafmd").rglob("*.py"))


def _quote(token: str) -> str:
    body = token.lstrip("rRbBuUfF")
    return body[:3] if body[:3] in ('"""', "'''") else body[:1]


def problems_for_311(text: str) -> list:
    """(line, what) for each place inside an f-string's replacement field that 3.11 cannot parse."""
    if sys.version_info < (3, 12):
        try:
            compile(text, "<source>", "exec")
        except SyntaxError as e:
            return [(e.lineno, e.msg)]
        return []
    out, stack = [], []                 # stack: [the f-string's quote, how deep in its braces]
    for t in tokenize.generate_tokens(iter(text.splitlines(keepends=True)).__next__):
        inside = bool(stack) and stack[-1][1] > 0
        if inside and t.type in (tokenize.STRING, tokenize.FSTRING_START) and _quote(t.string).startswith(stack[-1][0]):
            out.append((t.start[0], "the enclosing f-string's quote inside its replacement field"))
        if inside and t.type != tokenize.FSTRING_MIDDLE and "\\" in t.string:
            out.append((t.start[0], "a backslash inside an f-string's replacement field"))
        if t.type == tokenize.FSTRING_START:
            stack.append([_quote(t.string), 0])
        elif t.type == tokenize.FSTRING_END:
            stack.pop()
        elif stack and t.type == tokenize.OP and t.string == "{":
            stack[-1][1] += 1
        elif stack and t.type == tokenize.OP and t.string == "}":
            stack[-1][1] -= 1
    return out


@pytest.mark.parametrize("text, line", [
    ('x = f\'{" a=\\"b\\"" if k else ""}\'\n', 1),
    ("d = {}\nx = f\"{d[\"a\"]}\"\n", 2),
])
def test_what_311_refuses_inside_an_f_string_is_found(text, line):
    assert [n for n, _ in problems_for_311(text)] == [line]


@pytest.mark.parametrize("text", ['x = f"{a!r:>10} {b[\'k\']}\\n"\n', "x = f'''{'a'}'''\n", 'x = f"{{}}" + "\\\\"\n'])
def test_what_311_accepts_in_an_f_string_passes(text):
    assert problems_for_311(text) == []


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(p.parents[2])))
def test_every_source_file_parses_on_python_311(path):
    assert problems_for_311(path.read_text(encoding="utf-8")) == []
