"""A page test waits with a function, never a string. Playwright runs a string predicate through `eval`, and Chromium lets an
`eval` run only during the protocol call that carries it: the later polls of a wait that was not true at once are the page's
own, and the page's CSP (no `unsafe-eval`, SPEC 10) refuses them (`EvalError ... 'unsafe-eval' is not an allowed source`).
A wait that is true at its first poll passes, so the test failed only when the page was a little late (CI, three runs of
`test_a_recording_is_dropped_when_the_service_is_lost_during_it`)."""
import ast
import re
from pathlib import Path

PAGE_TESTS = Path(__file__).resolve().parent / "page"
A_FUNCTION = re.compile(r"^\s*(async\s*)?(\(.*?\)\s*=>|[\w$]+\s*=>|function\b)")


def string_predicates():
    found = []
    for path in sorted(PAGE_TESTS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "wait_for_function"):
                continue
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                text = first.value
            elif isinstance(first, ast.JoinedStr):
                text = "".join(v.value for v in first.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            else:
                continue
            if not A_FUNCTION.match(text):
                found.append(f"{path.name}:{node.lineno}: {text[:60]}")
    return found


def test_no_page_test_waits_with_a_string_predicate():
    assert string_predicates() == [], "a wait_for_function over a string needs `unsafe-eval`: write `() => <expression>`"


def test_a_parenthesised_expression_is_not_a_function_and_an_arrow_function_is():
    for text in ("(document.title)", "(1 + 2) === 3", "(a, b)"):
        assert not A_FUNCTION.match(text), text
    for text in ("() => 1", "(a, b) => a", "async (a) => a", "x => x", "function () {}", "  async function f() {}"):
        assert A_FUNCTION.match(text), text
