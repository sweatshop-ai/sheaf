"""Read-through, the parts that need no hub (SPEC 9.9): the "Clients" folder's addresses, how a client tiroir's rows are folded
under it, who a client tiroir answers for, and what the agency side says when a client does not answer."""
from types import SimpleNamespace

import pytest

from sheafmd.hub import readthrough as rt


def member(mid, email="", agency=True):
    return SimpleNamespace(id=mid, email=email, agency=agency, name=mid.title())


def clients(call=None):
    return rt.Clients({"acme": "https://acme.example.com", "beta": "https://beta.example.com"}, call or (lambda *a, **k: (200, {})))


# ── addresses ────────────────────────────────────────────────────────────────

def test_names_are_the_configured_clients_sorted():
    assert clients().names() == ["acme", "beta"]


@pytest.mark.parametrize("address,yes", [("Clients/acme/work/a.md", True), ("Clients/acme", True), ("Clients", True),
                                          ("clients/acme/a.md", False), ("Clientsx/acme/a.md", False), ("work/a.md", False)])
def test_is_clients_is_the_reserved_first_segment(address, yes):
    assert rt.is_clients(address) is yes


def test_split_gives_the_client_and_the_address_on_its_hub():
    assert clients().split("Clients/acme/work/a.md") == ("acme", "work/a.md")


@pytest.mark.parametrize("address", ["Clients", "Clients/", "Clients/acme", "Clients/unknown/work/a.md", "work/a.md", "Clients//a.md"])
def test_split_gives_none_for_what_names_no_page_of_a_configured_client(address):
    assert clients().split(address) is None


# ── folding rows ─────────────────────────────────────────────────────────────

ROW = {"doc": "work/a.md", "url": "/work/a.md", "title": "A", "root": "work", "folder": "work/notes", "share": "abc", "own": True,
       "archived": False, "kept": True, "mtime": 5.0, "when": "now", "open": 0, "write": "", "write_tip": "", "session": "",
       "session_tip": "", "session_link": None, "shared_by": ""}


def test_fold_puts_each_row_under_the_clients_folder():
    [row] = rt.fold_rows("acme", [ROW])
    assert row["doc"] == "Clients/acme/work/a.md"
    assert row["url"] == "/Clients/acme/work/a.md"
    assert row["folder"] == "Clients/acme/work/notes"
    assert row["root"] == "Clients/acme/work"


def test_a_folded_row_has_none_of_the_owners_actions():
    [row] = rt.fold_rows("acme", [ROW])
    assert row["own"] is False and row["share"] == "" and row["kept"] is False and row["archived"] is False
    assert row["session_link"] is None and row["session"] == "" and row["write"] == ""


def test_a_shared_row_is_told_under_its_owners_name_as_there():
    shared = {**ROW, "doc": "opaque", "root": "Shared with me", "folder": "Shared with me/Carol", "shared_from": "Carol"}
    [row] = rt.fold_rows("acme", [shared])
    assert row["folder"] == "Clients/acme/Shared with me/Carol"
    assert "shared_from" not in row


def test_a_client_name_with_a_space_or_slash_in_a_row_cannot_climb_out():
    [row] = rt.fold_rows("acme", [{**ROW, "doc": "../x.md", "folder": "a/../b"}])
    assert row["doc"].startswith("Clients/acme/") and ".." not in row["doc"].split("/")[2:3]


# ── who a client tiroir answers for ──────────────────────────────────────────

def hub(*members):
    return SimpleNamespace(proxy=SimpleNamespace(members={m.id: m for m in members}))


def test_the_member_is_found_by_e_mail_ignoring_case():
    h = hub(member("a", "Alice@Example.com"), member("b", "bob@example.com"))
    assert rt.member_for(h, "alice@example.COM").id == "a"


@pytest.mark.parametrize("asked", ["", None, "*", "nobody@example.com", 7, ["alice@example.com"]])
def test_no_member_for_an_empty_made_up_or_unknown_e_mail(asked):
    assert rt.member_for(hub(member("a", "alice@example.com")), asked) is None


def test_two_members_with_one_e_mail_are_nobody_never_the_first():
    assert rt.member_for(hub(member("a", "x@example.com"), member("b", "X@example.com")), "x@example.com") is None


def test_a_member_with_no_e_mail_is_never_found():
    assert rt.member_for(hub(member("a", "")), "") is None


def test_a_client_member_is_not_served():
    h = hub(member("c", "carol@example.com", agency=False))
    assert rt.served(h, "carol@example.com") is None


def test_an_agency_member_is_served():
    h = hub(member("a", "alice@example.com"))
    assert rt.served(h, "alice@example.com").id == "a"


# ── the agency side asks ─────────────────────────────────────────────────────

def test_a_member_with_no_e_mail_has_no_clients_folder_and_is_told_why():
    asked = []
    c = clients(lambda *a, **k: asked.append(a) or (200, {}))
    with pytest.raises(rt.NoEmail) as e:
        c.read("acme", member("a", ""), "sheaf")
    assert "e-mail" in str(e.value) and asked == []


def test_the_e_mail_sent_is_the_signed_in_members_never_a_field_of_the_request():
    seen = {}
    c = clients(lambda client, verb, body: seen.update(client=client, verb=verb, body=body) or (200, {"rows": []}))
    c.read("acme", member("a", "alice@example.com"), "sheaf", **{"as": "mallory@example.com", "role": "admin"})
    assert seen["verb"] == "read" and seen["client"] == "acme"
    assert seen["body"] == {"as": "alice@example.com", "op": "sheaf"}


def test_an_unreachable_client_is_said_and_nothing_older_is_served():
    def boom(*a, **k):
        raise OSError("down")
    c = clients(boom)
    with pytest.raises(rt.NotReachable):
        c.read("acme", member("a", "alice@example.com"), "sheaf")
    with pytest.raises(rt.NotReachable):
        c.read("acme", member("a", "alice@example.com"), "sheaf")


def test_a_client_that_refuses_is_a_client_that_does_not_answer():
    c = clients(lambda *a, **k: (404, {}))
    with pytest.raises(rt.NotReachable):
        c.read("acme", member("a", "alice@example.com"), "sheaf")
