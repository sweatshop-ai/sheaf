"""The agency tiroir's `[proxy.clients]` table (SPEC 9.9, read-through): the client tiroirs whose pages the "Clients" folder
reads through, one name and origin each. Pure config, no hub."""
import os
import pwd

import pytest

from sheafmd.hub import proxy


def table(**extra):
    return {"origin": "https://agency.example.com", "socket": "/run/sheaf-proxy/hub.sock",
            "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
            "members": {"m1": {"name": "Alice", "roots": ["/srv/alice"], "email": "alice@example.com", "agency": True}}, **extra}


def test_no_clients_table_is_no_clients():
    assert proxy.parse(table(), "the test").clients == {}


def test_a_clients_table_names_each_client_tiroir_by_its_origin():
    cfg = proxy.parse(table(clients={"acme": "https://acme.example.com", "beta": "https://beta.example.com:8443"}), "the test")
    assert cfg.clients == {"acme": "https://acme.example.com", "beta": "https://beta.example.com:8443"}


@pytest.mark.parametrize("name", ["", "has/slash", "Clients", "with space", ".dot", "a" * 41])
def test_a_client_name_is_a_plain_folder_name(name):
    with pytest.raises(proxy.ProxyError, match="clients"):
        proxy.parse(table(clients={name: "https://acme.example.com"}), "the test")


@pytest.mark.parametrize("origin", ["http://acme.example.com", "https://acme.example.com/path", "acme.example.com", 7])
def test_a_client_origin_is_an_https_origin(origin):
    with pytest.raises(proxy.ProxyError, match="origin"):
        proxy.parse(table(clients={"acme": origin}), "the test")


def test_a_client_origin_is_not_this_tiroirs_own():
    with pytest.raises(proxy.ProxyError, match="this tiroir"):
        proxy.parse(table(clients={"self": "https://agency.example.com"}), "the test")


def test_clients_is_a_table_not_a_list():
    with pytest.raises(proxy.ProxyError, match="clients"):
        proxy.parse(table(clients=["https://acme.example.com"]), "the test")


def test_a_client_names_never_collide_ignoring_case():
    with pytest.raises(proxy.ProxyError, match="twice"):
        proxy.parse(table(clients={"acme": "https://a.example.com", "ACME": "https://b.example.com"}), "the test")
