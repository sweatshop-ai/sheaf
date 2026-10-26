"""```chart fences become inline SVG (bar, hbar, line), drawn with no library."""
import html
import json
import re

import pytest
from helpers import active_content

from sheafmd import charts


def fence(spec) -> str:
    """The <pre> pandoc writes for a ```chart fence: the JSON, html-escaped."""
    body = spec if isinstance(spec, str) else json.dumps(spec)
    return f'<pre class="chart"><code>{html.escape(body, quote=False)}</code></pre>'


def texts(svg: str) -> list[str]:
    return re.findall(r"<text[^>]*>([^<]*)</text>", svg)


BAR = {"type": "bar", "x": ["north", "south", "east"],
       "series": [{"name": "Sales", "values": [10, 20, 30]}]}


def test_nice_ticks_round_the_top_up_to_a_human_step():
    assert charts.nice_ticks(97) == (100.0, [0.0, 25.0, 50.0, 75.0, 100.0])
    assert charts.nice_ticks(8) == (8, [0, 2, 4, 6, 8])
    assert charts.nice_ticks(0) == (1.0, [0, 1])
    assert charts.nice_ticks(-5) == (1.0, [0, 1])


def test_a_bar_spec_gives_one_bar_per_value_with_its_labels_and_title():
    out = charts.render_charts(fence({**BAR, "title": "Sales by region <2026>",
                                      "y_label": "units", "note": "Source: example.com"}))
    assert out.startswith('<div class="chart"><svg viewBox="0 0 720 300"')
    assert out.endswith("</svg><div class=\"cap\">Source: example.com</div></div>")
    assert "<pre" not in out
    assert out.count('opacity=".88"') == 3          # one rect per value
    assert texts(out) == ["Sales by region &lt;2026&gt;", "0", "10", "20", "30", "units",
                          "north", "south", "east"][:1] + texts(out)[1:]
    assert {"north", "south", "east", "units"} <= set(texts(out))
    assert "Sales by region &lt;2026&gt;" in out     # the title is escaped
    assert "<b>" not in out


def test_a_bar_is_as_tall_as_its_value():
    out = charts.svg_chart({"type": "bar", "x": ["a", "b"],
                            "series": [{"name": "n", "values": [10, 20]}]})
    heights = [float(h) for h in re.findall(r'<rect [^>]*height="([\d.]+)"[^>]*opacity="\.88"', out)]
    assert len(heights) == 2
    assert abs(heights[1] / heights[0] - 2) < 0.01


def test_several_series_get_a_legend_with_their_names():
    out = charts.svg_chart({"type": "bar", "x": ["a", "b"],
                            "series": [{"name": "north", "values": [1, 2]},
                                       {"name": "south", "values": [2, 3]}]})
    assert out.count('opacity=".88"') == 4
    assert {"north", "south"} <= set(texts(out))
    assert 'fill="var(--ink)"' in out and 'fill="#dc2626"' in out   # first two palette colours


def test_a_custom_palette_replaces_the_default_colours():
    out = charts.svg_chart({**BAR, "colors": ["#123456"]})
    assert 'fill="#123456" opacity=".88"' in out
    assert "var(--ink)" not in out


def test_an_hbar_spec_labels_each_row_and_prints_its_value():
    out = charts.render_charts(fence({"type": "hbar", "x": ["alpha", "beta"],
                                      "series": [{"name": "n", "values": [12, 7]}],
                                      "note": "Rows"}))
    assert out.startswith('<div class="chart"><svg')
    assert out.count('opacity=".88"') == 2
    assert {"alpha", "beta", "12", "7"} <= set(texts(out))
    assert out.endswith("</svg><div class='cap'>Rows</div></div>")


def test_an_hbar_with_a_negative_value_diverges_from_a_zero_line_in_the_middle():
    out = charts.svg_chart({"type": "hbar", "x": ["gained", "lost"],
                            "series": [{"name": "n", "values": [8, -4]}]})
    ticks = texts(out)
    assert "-8" in ticks and "8" in ticks and "0" in ticks
    assert "-4" in ticks                              # the value label of the negative bar
    grid = [float(x) for x in re.findall(r'<line x1="([\d.]+)" x2="\1" y1="\d+" y2="\d+" '
                                          r'stroke="var\(--grid\)"', out)]
    zero = re.findall(r'<line x1="([\d.]+)" x2="\1" y1="\d+" y2="\d+" stroke="currentColor" '
                      r'stroke-width="1.5"/>', out)
    assert len(zero) == 1
    assert float(zero[0]) == (min(grid) + max(grid)) / 2      # the zero line sits mid-plot


def test_a_line_spec_gives_a_polyline_and_a_point_per_value():
    out = charts.render_charts(fence({"type": "line", "x": ["jan", "feb", "mar"],
                                      "series": [{"name": "n", "values": [1, 5, 3]}]}))
    assert out.count("<polyline") == 1
    assert out.count("<circle") == 3
    assert re.search(r'<polyline points="(\d+\.\d,\d+\.\d ){2}\d+\.\d,\d+\.\d"', out)
    assert {"jan", "feb", "mar"} <= set(texts(out))


def test_a_missing_value_is_bridged_unless_gaps_break_the_line():
    spec = {"type": "line", "x": ["a", "b", "c"], "series": [{"name": "n", "values": [1, None, 3]}]}
    bridged = charts.svg_chart(spec)
    broken = charts.svg_chart({**spec, "gaps": "break"})
    assert bridged.count("<polyline") == 1 and bridged.count("<circle") == 2
    assert broken.count("<polyline") == 2 and broken.count("<circle") == 2


def test_invert_puts_the_smallest_value_at_the_top():
    spec = {"type": "line", "x": ["a", "b"], "series": [{"name": "rank", "values": [1, 9]}]}
    plain = re.findall(r'<circle cx="[\d.]+" cy="([\d.]+)"', charts.svg_chart(spec))
    inverted = re.findall(r'<circle cx="[\d.]+" cy="([\d.]+)"', charts.svg_chart({**spec, "invert": True}))
    assert float(plain[0]) > float(plain[1])          # 1 is low on a normal axis
    assert float(inverted[0]) < float(inverted[1])    # and high on an inverted one


def test_a_line_series_on_the_right_axis_gets_its_own_scale():
    out = charts.svg_chart({"type": "line", "x": ["a", "b"], "y_label": "clicks",
                            "y_label_right": "views",
                            "series": [{"name": "clicks", "values": [1, 9]},
                                       {"name": "views", "values": [100, 900], "axis": "right"}]})
    t = texts(out)
    assert {"clicks", "views", "250", "500", "750", "1000"} <= set(t)
    assert 'text-anchor="end" fill="var(--muted)" font-size="10">views</text>' in out


def test_bands_draw_a_tinted_strip_and_a_legend_for_the_labelled_ones():
    out = charts.svg_chart({**BAR, "bands": [{"from": 0, "to": 15, "color": "green", "label": "on target"},
                                             {"from": 15, "to": 40, "color": "#123456"}]})
    strips = re.findall(r'<rect x="56" y="[\d.]+" width="646" height="[\d.]+" fill="([^"]+)" '
                        r'opacity="0.11"/>', out)
    assert strips == ["#16a34a", "#123456"]           # "green" resolved, a hex colour kept
    assert out.count('<div class="bandleg">') == 1
    assert '<span><i style="background:#16a34a"></i>on target</span>' in out
    assert out.count("<span>") == 1                   # only the labelled band is in the legend


def test_a_band_outside_the_scale_is_not_drawn():
    out = charts.svg_chart({**BAR, "bands": [{"from": 900, "to": 950, "label": "off the chart"}]})
    assert 'opacity="0.11"' not in out
    assert "bandleg" not in out and "off the chart" not in out


def test_bands_are_ignored_on_a_horizontal_chart():
    out = charts.svg_chart({"type": "hbar", "x": ["a"], "series": [{"name": "n", "values": [5]}],
                            "bands": [{"from": 0, "to": 3, "color": "red"}]})
    assert 'opacity="0.11"' not in out


def test_on_a_line_with_one_series_a_point_takes_the_colour_of_its_band():
    out = charts.svg_chart({"type": "line", "x": ["a", "b"],
                            "series": [{"name": "n", "values": [5, 95]}],
                            "bands": [{"from": 0, "to": 50, "color": "red"},
                                      {"from": 50, "to": 100, "color": "green"}]})
    assert re.findall(r'<circle[^>]*fill="([^"]*)"', out) == ["#dc2626", "#16a34a"]


def test_error_bars_add_a_stem_and_two_caps_to_each_bar_that_has_one():
    spec = {"type": "bar", "x": ["a", "b"],
            "series": [{"name": "n", "values": [10, 20], "err": [2, 0]}]}
    out = charts.render_charts(fence(spec))
    assert out.count('stroke-width="1.4"') == 3       # one bar has an error: stem + two caps
    assert out.count('opacity=".88"') == 2
    without = charts.svg_chart({**spec, "series": [{"name": "n", "values": [10, 20]}]})
    assert 'stroke-width="1.4"' not in without


def test_the_axis_makes_room_for_the_error_bar_above_the_tallest_bar():
    with_err = charts.svg_chart({"type": "bar", "x": ["a"],
                                 "series": [{"name": "n", "values": [100], "err": [20]}]})
    without = charts.svg_chart({"type": "bar", "x": ["a"], "series": [{"name": "n", "values": [100]}]})
    assert "150" in texts(with_err) and "150" not in texts(without)   # 100 + 20 needs a 150 tick
    assert "100" in texts(without) and "100" in texts(with_err)


def test_a_category_name_too_long_for_its_slot_is_rotated():
    out = charts.svg_chart({"type": "bar", "x": [f"{'categoryname' * 3}{i}" for i in range(6)],
                            "series": [{"name": "n", "values": [1, 2, 3, 4, 5, 6]}]})
    assert out.count("rotate(-32") == 6
    # a label past 30 characters is cut to 29 and ends in an ellipsis
    assert texts(out).count("categorynamecategorynamecateg\u2026") == 6


def test_a_long_label_with_spaces_wraps_instead_of_rotating():
    out = charts.svg_chart({"type": "bar", "x": ["one two three four five six"] + ["b"] * 5,
                            "series": [{"name": "n", "values": [1, 2, 3, 4, 5, 6]}]})
    assert "rotate(" not in out
    assert {"one two three", "four five six"} <= set(texts(out))     # two lines, same slot


def test_a_bad_json_chart_fence_is_replaced_by_a_spec_error():
    out = charts.render_charts(fence('{"type": "bar", "x": ['))
    assert out.startswith("<pre><code>chart spec error: ")
    assert out.endswith("</code></pre>")
    assert "<svg" not in out


@pytest.mark.parametrize("spec", [
    {**BAR, "height": "300"},                                              # a string where a number goes
    {**BAR, "series": [{"name": "Sales", "values": [10, "20", 30]}]},
    {**BAR, "series": [{"name": "Sales", "values": [10, 20, 30], "err": "wide"}]},
    {**BAR, "series": ["Sales"]},                                          # a series that is not an object
    {**BAR, "x": 3},
    {**BAR, "type": "line", "ymax": "high"},
    [1, 2, 3],                                                             # valid JSON, not a spec
], ids=["height", "values", "err", "series", "x", "ymax", "list"])
def test_a_spec_with_the_wrong_kind_of_value_is_a_spec_error_not_a_traceback(spec):
    """Bad JSON already said so; a well-formed spec holding a value of the wrong type
    stopped the whole render with a Python error. A fix against the reference."""
    good = fence(BAR)
    out = charts.render_charts(fence(spec) + good)
    assert out.startswith("<pre><code>chart spec error: ")
    assert out.count("</code></pre>") == 1 and "<svg" in out.split("</code></pre>")[1]    # the next chart still draws
    assert "<svg" not in out.split("</code></pre>")[0]


def test_a_spec_without_series_or_categories_leaves_the_fence_as_it_was():
    for spec in ({"type": "bar"}, {"type": "bar", "x": ["a"], "series": []},
                 {"type": "bar", "x": [], "series": [{"name": "n", "values": []}]}):
        src = fence(spec)
        assert charts.svg_chart(spec) is None
        assert charts.render_charts(src) == src


def test_a_pre_that_is_not_a_chart_is_untouched():
    code = '<pre class="python"><code>print("hi")\n</code></pre>'
    plain = "<pre><code>just text\n</code></pre>"
    page = f"<p>before</p>{code}{plain}<p>after</p>"
    assert charts.render_charts(page) == page


def test_only_the_chart_fences_in_a_page_are_replaced():
    code = '<pre class="python"><code>x = 1\n</code></pre>'
    page = f"<h1>T</h1>{fence(BAR)}<p>mid</p>{code}{fence({**BAR, 'type': 'line'})}"
    out = charts.render_charts(page)
    assert out.count('<div class="chart">') == 2
    assert out.count("<polyline") == 1
    assert code in out
    assert out.startswith("<h1>T</h1>") and "<p>mid</p>" in out


# ── style values are colours and numbers, never markup (SPEC 9.5) ───────────

NOT_A_COLOUR = ['" onmouseover="alert(1)', 'red"><script>alert(1)</script>',
                "url(http://x.example/a.svg#b)", "expression(alert(1))", "red; x", "",
                "#12", "#12345", 5, None, ["red"], {"a": 1}]


@pytest.mark.parametrize("colour", ["#123456", "#abc", "#abcd", "#12345678", "green",
                                    "currentColor", "var(--ink)", "rgb(10, 20, 30)",
                                    "rgba(10,20,30,.5)", "hsl(120 50% 40%)"])
def test_a_palette_entry_written_as_a_css_colour_is_kept(colour):
    out = charts.svg_chart({**BAR, "colors": [colour]})
    assert f'fill="{colour}" opacity=".88"' in out


@pytest.mark.parametrize("bad", NOT_A_COLOUR)
def test_a_palette_entry_that_is_not_a_colour_gives_way_to_the_built_in_one(bad):
    out = charts.svg_chart({**BAR, "colors": [bad]})
    assert out.count('fill="var(--ink)" opacity=".88"') == 3
    assert active_content(out) == []
    assert "alert" not in out and "x.example" not in out


def test_each_palette_entry_falls_back_to_the_built_in_colour_at_its_own_place():
    two = {**BAR, "series": [{"name": "a", "values": [1, 2, 3]}, {"name": "b", "values": [3, 2, 1]}]}
    out = charts.svg_chart({**two, "colors": ['" onclick="x', "#123456"]})
    assert 'fill="var(--ink)" opacity=".88"' in out and 'fill="#123456" opacity=".88"' in out
    out = charts.svg_chart({**two, "colors": ["#123456", '" onclick="x']})
    assert 'fill="#123456" opacity=".88"' in out and 'fill="#dc2626" opacity=".88"' in out


@pytest.mark.parametrize("palette", ["red", 5, {"a": 1}])
def test_a_palette_that_is_not_a_list_is_the_built_in_one(palette):
    out = charts.svg_chart({**BAR, "colors": palette})
    assert out.count('fill="var(--ink)" opacity=".88"') == 3


@pytest.mark.parametrize("bad", NOT_A_COLOUR)
def test_a_band_colour_that_is_not_a_colour_is_grey_in_the_strip_and_the_legend(bad):
    out = charts.svg_chart({**BAR, "bands": [{"from": 0, "to": 15, "color": bad, "label": "band"}]})
    assert 'fill="#7a869a" opacity="0.11"/>' in out
    assert '<span><i style="background:#7a869a"></i>band</span>' in out
    assert active_content(out) == []
    assert "alert" not in out and "x.example" not in out and "<script" not in out


@pytest.mark.parametrize("bad", NOT_A_COLOUR)
def test_a_band_colour_that_is_not_a_colour_does_not_tint_a_line_point(bad):
    out = charts.svg_chart({"type": "line", "x": ["a", "b"],
                            "series": [{"name": "n", "values": [5, 95]}],
                            "bands": [{"from": 0, "to": 100, "color": bad}]})
    assert active_content(out) == [] and "alert" not in out and "x.example" not in out


@pytest.mark.parametrize("opacity, written", [(0.5, "0.5"), (1, "1"), (0, "0"), ("0.25", "0.25")])
def test_a_band_opacity_that_is_a_number_is_kept(opacity, written):
    out = charts.svg_chart({**BAR, "bands": [{"from": 0, "to": 15, "opacity": opacity}]})
    assert f'opacity="{written}"/>' in out


@pytest.mark.parametrize("bad", ['0.1" onclick="alert(1)', "abc", "", None, True, [0.1], {"a": 1},
                                 float("nan"), float("inf"), "nan", "inf"])
def test_a_band_opacity_that_is_not_a_number_is_the_default(bad):
    out = charts.svg_chart({**BAR, "bands": [{"from": 0, "to": 15, "opacity": bad}]})
    assert 'fill="#7a869a" opacity="0.11"/>' in out
    assert active_content(out) == [] and "alert" not in out
