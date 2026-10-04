"""The secret-scrubbing logger must not let credentials reach a log line."""

from __future__ import annotations

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


def test_scrub_leaves_plain_text_alone():
    assert scrub("syncing library page 2 of 3") == "syncing library page 2 of 3"
