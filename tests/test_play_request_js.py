"""B11 desktop — ``qml/lib/PlayRequest.js``: only the newest play-info reply loads."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def pr() -> qjs.JsModule:
    return qjs.load("PlayRequest")


def job(asin, purpose, command="play-info"):
    return {"command": command, "args": [asin], "purpose": purpose}


def test_create(pr):
    assert pr.call("create", "B0X", 12.5, 3) == {
        "asin": "B0X",
        "startSec": 12.5,
        "id": 3,
        "purpose": "play:3",
    }
    assert pr.call("create", "B0X", None, 4)["startSec"] == 0
    assert pr.call("create", "B0X", -1, 5)["startSec"] == -1


def test_matches_its_own_reply(pr):
    request = pr.call("create", "B0X", 0, 7)
    assert pr.call("matches", request, job("B0X", "play:7")) is True


def test_same_book_asked_twice_only_the_newest_matches(pr):
    # A -> A: the first reply (success or failure) must not stand in for the second.
    newer = pr.call("create", "B0X", 30, 2)
    assert pr.call("matches", newer, job("B0X", "play:1")) is False
    assert pr.call("matches", newer, job("B0X", "play:2")) is True


def test_other_book_or_command_never_matches(pr):
    request = pr.call("create", "B0B", 0, 9)
    assert pr.call("matches", request, job("B0A", "play:9")) is False
    assert (
        pr.call("matches", request, job("B0B", "play:9", command="position-get"))
        is False
    )
    assert pr.call("matches", request, job("B0B", "resume")) is False


@pytest.mark.parametrize(
    "request_,job_",
    [
        (None, {"command": "play-info", "args": ["B0X"], "purpose": "play:1"}),
        ({"asin": "B0X", "purpose": "play:1"}, None),
        (
            {"asin": "B0X", "purpose": "play:1"},
            {"command": "play-info", "args": "B0X", "purpose": "play:1"},
        ),
        ([], {}),
    ],
)
def test_matches_bad_input(pr, request_, job_):
    assert pr.call("matches", request_, job_) is False


def test_busy_asin(pr):
    assert pr.call("busyAsin", pr.call("create", "B0X", 0, 1)) == "B0X"
    assert pr.call("busyAsin", None) == ""
    assert pr.call("busyAsin", {}) == ""
