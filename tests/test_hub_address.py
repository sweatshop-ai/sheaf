"""The address of a document, `<root>/<path-in-root>` (SPEC 8.2): the one place it is split and
joined."""
import pytest

from sheafmd.hub.roots import Address


def test_an_address_is_split_at_its_first_slash():
    a = Address.parse("proj/docs/deep/a.md")
    assert (a.root, a.rel) == ("proj", "docs/deep/a.md")


def test_an_address_with_no_slash_is_all_root():
    assert (Address.parse("proj").root, Address.parse("proj").rel) == ("proj", "")
    assert (Address.parse("").root, Address.parse("").rel) == ("", "")


def test_an_address_is_written_root_slash_path():
    assert str(Address("proj", "docs/a.md")) == "proj/docs/a.md"
    assert str(Address.parse("proj/docs/a.md")) == "proj/docs/a.md"


def test_the_prefix_of_a_root_is_what_every_address_in_it_starts_with():
    assert Address.prefix("proj") == "proj/"
    assert str(Address("proj", "a.md")).startswith(Address.prefix("proj"))
    assert not str(Address("proj2", "a.md")).startswith(Address.prefix("proj"))


def test_an_address_with_no_path_is_written_with_the_slash_all_the_same():
    assert str(Address.parse("proj")) == "proj/"


def test_an_address_is_equal_by_its_parts_and_can_key_a_dict():
    assert Address.parse("p/a.md") == Address("p", "a.md")
    assert {Address("p", "a.md"): 1}[Address.parse("p/a.md")] == 1


@pytest.mark.parametrize("text", ["p/a.md", "p/docs/a.md", "p/.hidden/a.md", "p/a..b/c.md"])
def test_a_path_of_plain_segments_is_plain(text):
    assert Address.parse(text).plain


@pytest.mark.parametrize("text", ["p", "p/", "p//a.md", "p/./a.md", "p/../a.md", "p/a/", "p/a\0b.md", "p/docs/..",
                                  "p/.", "p/a//b.md", "p/a.md/"])
def test_no_path_an_empty_dot_dotdot_or_nul_segment_is_plain(text):
    assert not Address.parse(text).plain
