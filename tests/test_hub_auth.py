"""The hub's authentication, one module (SPEC 9.2 to 9.4, 21): the Host and Origin checks,
the key, the cookie, the health proof, the sign-in redirect target and the CSP."""
import base64
import hashlib
import hmac
import os
import re
import stat

import pytest

from sheafmd import paths
from sheafmd.hub import auth


# ── the key file (SPEC 4.2) ──────────────────────────────────────────────────

def test_ensure_key_makes_one_private_line_of_32_random_bytes():
    key = paths.ensure_key()
    f = paths.key_file()
    assert f.read_text(encoding="ascii") == key + "\n"
    assert len(auth.key_bytes(key)) == 32
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700


def test_ensure_key_keeps_the_key_it_finds():
    assert paths.ensure_key() == paths.ensure_key()


def test_two_homes_have_two_keys(tmp_path, monkeypatch):
    first = paths.ensure_key()
    monkeypatch.setenv("SHEAF_HOME", str(tmp_path / "other"))
    assert paths.ensure_key() != first


def test_a_key_file_that_is_not_a_key_is_refused_not_replaced():
    f = paths.key_file()
    paths.private_dir(f.parent)
    f.write_text("not a key\n")
    with pytest.raises(paths.PathError, match="hub.key"):
        paths.ensure_key()
    assert f.read_text() == "not a key\n"


def test_a_key_file_other_users_can_read_is_tightened():
    key = paths.ensure_key()
    os.chmod(paths.key_file(), 0o644)
    assert paths.ensure_key() == key
    assert stat.S_IMODE(paths.key_file().stat().st_mode) == 0o600


# ── Host (SPEC 9.2) ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1:27419", "localhost:27419", "127.0.0.1:1",
                                  "127.0.0.1:65535", "localhost:8080", "LOCALHOST:27419"])
def test_the_loopback_names_with_any_port_pass_the_host_check(host):
    assert auth.host_ok(host)


@pytest.mark.parametrize("host", [
    None, "", "evil.example", "evil.example:27419", "127.0.0.1", "localhost", "127.0.0.1:",
    "127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1:abc", "127.0.0.1:27419.evil.example",
    "127.0.0.1.evil.example:27419", "evil.example:27419@127.0.0.1:27419", "[::1]:27419",
    "0.0.0.0:27419", "127.0.0.2:27419", "127.0.0.1:27419, evil.example", " 127.0.0.1:27419",
    "127.0.0.1:27419\n", "localhost.:27419", "xlocalhost:27419", "127.0.0.1:٢٧٤١٩"])
def test_every_other_host_fails_it(host):
    assert not auth.host_ok(host)


# ── Origin (SPEC 9.2) ────────────────────────────────────────────────────────

def test_a_cookie_post_needs_an_origin_equal_to_its_host():
    assert auth.origin_ok("http://127.0.0.1:27419", "127.0.0.1:27419")
    assert auth.origin_ok("http://localhost:3000", "localhost:3000")


@pytest.mark.parametrize("origin,host", [
    (None, "127.0.0.1:27419"), ("", "127.0.0.1:27419"), ("null", "127.0.0.1:27419"),
    ("http://127.0.0.1:3000", "127.0.0.1:27419"), ("http://localhost:27419", "127.0.0.1:27419"),
    ("https://127.0.0.1:27419", "127.0.0.1:27419"), ("http://evil.example", "127.0.0.1:27419"),
    ("http://127.0.0.1:27419/", "127.0.0.1:27419"), ("http://127.0.0.1:27419.evil.example",
                                                      "127.0.0.1:27419")])
def test_any_other_origin_fails_it(origin, host):
    assert not auth.origin_ok(origin, host)


# ── the key, the cookie, the proof (SPEC 9.3, 9.4) ───────────────────────────

@pytest.fixture
def a():
    return auth.Auth(paths.ensure_key(), 27419)


def test_the_key_header_is_compared_in_constant_time_form(a):
    assert a.key_ok(a.key)
    for bad in (None, "", a.key[:-1], a.key + "x", "x" * len(a.key), a.key.upper()):
        assert not a.key_ok(bad)


def test_the_cookie_is_named_for_the_configured_port_and_derived_from_the_key(a):
    assert a.cookie_name == "sheaf_27419"
    want = hmac.new(auth.key_bytes(a.key), b"cookie", hashlib.sha256).hexdigest()
    assert a.cookie_value() == want
    assert auth.Auth(a.key, 28000).cookie_name == "sheaf_28000"


def test_the_cookie_header_is_read_whatever_else_it_holds(a):
    good = f"{a.cookie_name}={a.cookie_value()}"
    assert a.cookie_ok(good)
    assert a.cookie_ok(f"a=b; {good}; c=d")
    assert a.cookie_ok(f'{a.cookie_name}="{a.cookie_value()}"')
    for bad in (None, "", f"{a.cookie_name}=", f"{a.cookie_name}={a.cookie_value()[:-1]}",
                f"sheaf_1={a.cookie_value()}", f"x{a.cookie_name}={a.cookie_value()}",
                f"{a.cookie_name}={a.cookie_value().upper()}", "garbage", ";;;"):
        assert not a.cookie_ok(bad), bad


def test_a_cookie_made_for_another_key_fails(a):
    other = auth.Auth(base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="), 27419)
    assert not a.cookie_ok(f"{other.cookie_name}={other.cookie_value()}")


def test_the_set_cookie_line_has_the_attributes_of_the_spec(a):
    line = a.set_cookie()
    assert line == (f"sheaf_27419={a.cookie_value()}; HttpOnly; SameSite=Strict; Path=/; "
                    "Max-Age=34560000")


def test_the_health_proof_is_the_hmac_of_the_nonce(a):
    nonce = "ab" * 16
    want = hmac.new(auth.key_bytes(a.key), b"health:" + nonce.encode(), hashlib.sha256).hexdigest()
    assert a.proof(nonce) == want
    assert a.proof(nonce) != a.proof("cd" * 16)


@pytest.mark.parametrize("nonce", ["ab" * 16, "0" * 32, "f" * 64])
def test_a_nonce_is_hex_of_a_sane_length(nonce):
    assert auth.nonce_ok(nonce)


@pytest.mark.parametrize("nonce", ["", "xyz", "ab" * 3, "ab" * 100, "AB" * 16, "ab cd" * 8, None])
def test_anything_else_is_not_a_nonce(nonce):
    assert not auth.nonce_ok(nonce)


# ── where sign-in may send the browser (SPEC 9.3) ────────────────────────────

@pytest.mark.parametrize("nxt", ["/", "/root/a.md", "/root/a%20b.md", "/root/a.md?x=1#h",
                                 "/root/dir/ünï.md"])
def test_sign_in_redirects_only_to_a_path_on_the_hub(nxt):
    assert auth.safe_next(nxt)


@pytest.mark.parametrize("nxt", ["", "//evil.example", "/\\evil.example", "http://evil.example",
                                 "https://evil.example/x", "evil.example", "/a\\b", "//",
                                 "/\\", "javascript:alert(1)", "/x\r\nSet-Cookie: a=b",
                                 "/x\ny", "/x\x00", "/x\x7f", "\\\\evil.example"])
def test_every_other_target_is_refused(nxt):
    assert not auth.safe_next(nxt)


def test_the_location_header_is_plain_ascii():
    loc = auth.location("/root/dir/ünï.md")
    assert loc == "/root/dir/%C3%BCn%C3%AF.md"
    loc.encode("ascii")
    assert auth.location("/root/a%20b.md?x=1#h") == "/root/a%20b.md?x=1#h"


# ── the policy (SPEC 9.5) ────────────────────────────────────────────────────

def test_the_csp_is_the_one_of_the_spec_with_the_nonce_in_it():
    nonce = auth.new_nonce()
    assert auth.csp(nonce) == (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; "
        "img-src data:; font-src data:; connect-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'")


def test_every_nonce_is_new_and_fits_the_csp_grammar():
    seen = {auth.new_nonce() for _ in range(50)}
    assert len(seen) == 50
    assert all(re.fullmatch(r"[A-Za-z0-9+/_-]{16,}", n) for n in seen)
