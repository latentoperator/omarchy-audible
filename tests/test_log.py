"""The secret-scrubbing logger must not let credentials reach a log line."""

from __future__ import annotations

import json

from omarchy_audible.log import scrub


def test_scrub_redacts_key_value_secrets():
    text = "authorization_code=ABC123&x=1 activation_bytes=deadbeef key=Zm9v iv=Q2hh"
    scrubbed = scrub(text)
    for secret in ("ABC123", "deadbeef", "Zm9v", "Q2hh"):
        assert secret not in scrubbed
    assert "authorization_code" in scrubbed


def test_scrub_redacts_bearer_headers():
    assert "ghp_supersecret" not in scrub("Authorization: Bearer ghp_supersecret")


def test_scrub_redacts_codes_in_urls():
    scrubbed = scrub("https://x/ap?openid.oa2.authorization_code=XYZ789&y=2")
    assert "XYZ789" not in scrubbed


def test_scrub_redacts_json_quoted_secrets():
    text = '{"iv": "Q2hh", "activation_bytes": "deadbeef", "key": "Zm9v"}'
    scrubbed = scrub(text)
    for secret in ("Q2hh", "deadbeef", "Zm9v"):
        assert secret not in scrubbed
    assert '"iv"' in scrubbed
    assert '"activation_bytes"' in scrubbed


def test_scrub_redacts_dict_repr_secrets():
    text = "{'iv': 'Q2hh', 'access_token': 'AT-123', 'refresh_token': 'RT-456'}"
    scrubbed = scrub(text)
    for secret in ("Q2hh", "AT-123", "RT-456"):
        assert secret not in scrubbed
    assert "'access_token'" in scrubbed


def test_scrub_leaves_plain_text_alone():
    assert scrub("syncing library page 2 of 3") == "syncing library page 2 of 3"


# ---- B11: the mpv option that carries a key ----


def test_scrub_redacts_the_lavf_option_shapes():
    lines = [
        # A loadfile option map, an mpv option, a JSON record and the legacy key.
        "loadfile /b/book.aaxc replace -1 {demuxer-lavf-o=audible_key=0011223344556677,audible_iv=aabbccdd00112233}",
        "audible_key=0011223344556677 audible_iv=aabbccdd00112233",
        '{"lavf_options": "audible_key=0011223344556677,audible_iv=aabbccdd00112233"}',
        "activation_bytes=0011223344556677",
    ]
    for line in lines:
        scrubbed = scrub(line)
        assert "0011223344556677" not in scrubbed, line
        assert "aabbccdd00112233" not in scrubbed, line


def test_scrub_keeps_the_option_name_without_a_value():
    # The clear command carries no value, so the option name stays readable.
    assert scrub("set_property demuxer-lavf-o") == "set_property demuxer-lavf-o"


# ---- F4: any name ending in a secret suffix ----


# An ``auth.json``-shaped dict. Every value is invented and obviously fake; it
# is what ``audible`` writes (device_private_key, adp_token, cookies, tokens),
# and the names that used to slip through the old allowlist are all here.
FAKE_AUTH = {
    "device_private_key": "FAKE-device-private-key",
    "adp_token": "FAKE-adp-token",
    "access_token": "FAKE-access-token",
    "refresh_token": "FAKE-refresh-token",
    "website_cookies": "FAKE-website-cookie",
    "store_authentication_cookie": "FAKE-store-cookie",
    "activation_bytes": "FAKE-activation-bytes",
    "customer_info": {"name": "Fake Listener"},  # not a secret
}


def test_scrub_masks_every_name_in_an_auth_json_shaped_dict():
    for text in (json.dumps(FAKE_AUTH), repr(FAKE_AUTH)):
        scrubbed = scrub(text)
        for name, value in FAKE_AUTH.items():
            if isinstance(value, str):
                assert value not in scrubbed, name
            assert name in scrubbed, name
        # The one non-secret field is left readable.
        assert "Fake Listener" in scrubbed


def test_scrub_masks_by_suffix_not_only_exact_names():
    text = (
        "device_private_key=AAAA adp_token=BBBB store_authentication_cookie=CCCC "
        "website_cookies=DDDD refresh_token=EEEE some_secret=FFFF verify_verifier=GGGG"
    )
    scrubbed = scrub(text)
    for value in ("AAAA", "BBBB", "CCCC", "DDDD", "EEEE", "FFFF", "GGGG"):
        assert value not in scrubbed, value


def test_scrub_leaves_the_fields_the_ui_reads_alone():
    # The status/doctor/local event fields must survive a round trip: none of
    # them ends in a secret suffix.
    text = (
        '{"type":"status","ready":true,"missing":[],"authenticated":false,'
        '"venv_ready":false,"marketplace":"us","account":"fake@example.com",'
        '"catalog_age_s":null,"config_dir":"/c","data_dir":"/d",'
        '"runtime_dir":"/r","books_dir":"/b"}'
    )
    assert scrub(text) == text
    assert scrub("syncing library page 2 of 3, 42 books") == (
        "syncing library page 2 of 3, 42 books"
    )
