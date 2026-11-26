"""The flat splitter knows pandoc fenced divs: one tile for a whole div, blank lines and nested divs inside it."""
import pytest

from sheafmd.blocks import split_md_blocks


def kinds(text):
    return [(t.kind, t.content) for t in split_md_blocks(text)]


def tiles_exactly(text):
    assert "".join(t.text for t in split_md_blocks(text)) == text


DIV = '::: {#c1 .callout}\nOne.\n\nTwo.\n:::\n'


def test_a_div_holding_blank_lines_is_one_tile():
    got = kinds(DIV + "\nAfter.\n")
    assert got == [("div", DIV), ("para", "After.\n")]
    tiles_exactly(DIV + "\nAfter.\n")


def test_nested_divs_close_at_their_own_fence():
    text = ":::: {.columns}\n::: {.column}\nA\n\nB\n:::\n::: {.column}\nC\n:::\n::::\n\nTail.\n"
    got = kinds(text)
    assert [k for k, _ in got] == ["div", "para"]
    tiles_exactly(text)


def test_a_colon_fence_inside_a_code_fence_does_not_close_the_div():
    text = "::: {.callout}\n```\n:::\n```\n\nafter code\n:::\n\nTail.\n"
    assert [k for k, _ in kinds(text)] == ["div", "para"]


def test_a_div_may_interrupt_a_paragraph():
    text = "Text.\n::: {.callout}\nInside.\n:::\n"
    assert [k for k, _ in kinds(text)] == ["para", "div"]
    tiles_exactly(text)


def test_an_unterminated_div_runs_to_the_end_of_the_file():
    text = "::: {.callout}\nInside.\n\nMore.\n"
    assert [k for k, _ in kinds(text)] == ["div"]
    tiles_exactly(text)


@pytest.mark.parametrize("text", ["::: {.a}\r\nx\r\n\r\ny\r\n:::\r\n", "\n\n::: {.a}\nx\n:::\n\n\n", "::: warning\nx\n:::"])
def test_other_shapes_tile_exactly(text):
    assert "div" in [t.kind for t in split_md_blocks(text)]
    tiles_exactly(text)


def test_a_bare_colon_line_is_not_an_opener():
    assert [k for k, _ in kinds(":::\ntext\n")] != ["div"]


def test_an_indented_colon_fence_is_not_a_top_level_div():
    assert "div" not in [k for k, _ in kinds("    ::: {.a}\n    x\n    :::\n")]
