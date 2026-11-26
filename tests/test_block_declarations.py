"""The fixed list of typed Block declarations (block editor v1, ADR 0001, 0004 and 0008): one list that feeds
the reader's checks, both sanitiser layers and the generated CSS."""
import re

from sheafmd.blocks import declarations as dec


def test_the_callout_is_declared_with_typed_attributes_and_defaults():
    callout = dec.DECLARED["callout"]
    assert callout.tag == "div"
    by_name = {a.name: a for a in callout.attrs}
    assert set(by_name) == {"tone", "align", "pad"}
    assert by_name["tone"].default == "info" and "warning" in by_name["tone"].values
    assert by_name["pad"].values == ("none", "s", "m", "l") and by_name["pad"].default == "m"
    assert by_name["align"].values == ("left", "center", "right")
    for a in callout.attrs:
        assert a.default in a.values


def test_check_attrs_accepts_declared_values_and_names_the_first_fault():
    assert dec.check_attrs("callout", {}) is None
    assert dec.check_attrs("callout", {"tone": "warning", "pad": "l"}) is None
    assert "onclick" in dec.check_attrs("callout", {"onclick": "x"})
    assert "style" in dec.check_attrs("callout", {"style": "color:red"})
    why = dec.check_attrs("callout", {"tone": "purple"})
    assert "tone" in why and "purple" in why
    assert "pad" in dec.check_attrs("callout", {"pad": "xl"})


def test_a_callout_holds_plain_blocks_and_never_another_rich_block():
    for kid in ("paragraph", "heading", "list", "quote", "table", "code", "rule"):
        assert dec.check_children("callout", [kid]) is None
    assert dec.check_children("callout", ["box", "image"]) is None      # the layout divs of ADR 0001
    for kid in ("callout", "columns", "column", "app"):
        assert kid in dec.check_children("callout", ["paragraph", kid])


def test_quote_and_list_items_refuse_a_rich_block():
    assert "callout" in dec.check_plain_container("quote", ["paragraph", "callout"])
    assert dec.check_plain_container("list", ["paragraph"]) is None


def test_the_generated_css_has_one_rule_per_allowed_step_and_no_style_values_from_the_document():
    css = dec.css()
    for v in ("none", "s", "m", "l"):
        assert f'div.callout[data-pad="{v}"]' in css
    for v in ("info", "success", "warning", "danger"):
        assert f'div.callout[data-tone="{v}"]' in css
    # every Theme property used is also given a default
    used = set(re.findall(r"var\((--sheaf-[\w-]+)", css))
    given = set(re.findall(r"(--sheaf-[\w-]+)\s*:", css))
    assert used <= given, used - given


def test_the_allow_list_is_what_both_sanitisers_are_generated_from():
    allow = dec.allow_list()
    assert allow["callout"] == {"tag": "div", "attrs": {"data-tone": ["info", "success", "warning", "danger"],
                                                       "data-align": ["left", "center", "right"],
                                                       "data-pad": ["none", "s", "m", "l"]}}


def test_the_generated_block_in_mount_js_is_in_step_with_the_declarations():
    import pathlib
    import sheafmd
    js = (pathlib.Path(sheafmd.__file__).parent / "page" / "mount.js").read_text(encoding="utf-8")
    assert dec.mount_js() in js        # regenerate with: python -m sheafmd.blocks.declarations --write
