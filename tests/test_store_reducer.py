"""P9 PR 8 — StateStore adoption, replay and file effects are pure vectors."""

from __future__ import annotations

import json
import pathlib
import re

import pytest

import qjs

REPO = pathlib.Path(__file__).resolve().parents[1]
PATH = "/fake/state.json"
AT1 = "2026-10-08T10:00:00Z"
AT2 = "2026-10-08T10:01:00Z"


@pytest.fixture(scope="module")
def store() -> qjs.JsModule:
    return qjs.load("Store")


def base(path: str = PATH) -> dict:
    return {
        "path": path,
        "doc": {
            "schema": 1,
            "books": {},
            "push_queue": [],
            "volume": None,
            "speed": None,
            "recovered": True,
        },
        "loaded": False,
        "dirty": False,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }


def vector(store, state: dict, **event) -> tuple[dict, list[dict]]:
    result = store.call("step", state, event)
    assert set(result) == {"state", "effects"}
    return result["state"], result["effects"]


def empty_doc() -> dict:
    return {
        "schema": 1,
        "books": {},
        "push_queue": [],
        "volume": None,
        "speed": None,
        "recovered": True,
    }


def state_with(**changes) -> dict:
    out = base()
    out.update(changes)
    return out


def test_pending_ops_replay_in_order_before_loaded_and_save(store):
    state = base()
    state, effects = vector(store, state, type="record", asin="A", ms=4000, at=AT1)
    assert state == state_with(
        pendingOps=[{"kind": "record", "asin": "A", "ms": 4000, "at": AT1}]
    )
    assert effects == []
    state, effects = vector(store, state, type="finished", asin="A")
    assert state == state_with(
        pendingOps=[
            {"kind": "record", "asin": "A", "ms": 4000, "at": AT1},
            {"kind": "finished", "asin": "A"},
        ]
    )
    assert effects == []
    state, effects = vector(
        store,
        state,
        type="adopt",
        text='{"schema":1,"books":{},"push_queue":[],"volume":null,"speed":null}',
        path=PATH,
    )
    doc = {
        "schema": 1,
        "books": {
            "A": {
                "ms": 4000,
                "updated_at": AT1,
                "last_played_at": AT1,
                "played_since_download": True,
                "finished": True,
            }
        },
        "push_queue": [],
        "volume": None,
        "speed": None,
        "recovered": False,
    }
    assert state == {
        "path": PATH,
        "doc": doc,
        "loaded": True,
        "dirty": True,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    # Adoption asks QML to decide whether to save after loaded reactions run.
    assert effects == [{"type": "save_now"}]
    state, effects = vector(store, state, type="save")
    assert state["dirty"] is False
    assert effects == [
        {
            "type": "write",
            "text": json.dumps(
                {
                    "schema": 1,
                    "books": doc["books"],
                    "push_queue": [],
                    "volume": None,
                    "speed": None,
                },
                separators=(",", ":"),
            ),
        }
    ]


def test_corrupt_file_waits_for_backup_then_replays_before_first_write(store):
    state = base()
    state, effects = vector(store, state, type="record", asin="A", ms=1000, at=AT1)
    assert state == state_with(
        pendingOps=[{"kind": "record", "asin": "A", "ms": 1000, "at": AT1}]
    )
    assert effects == []
    state, effects = vector(store, state, type="adopt", text="garbage", path=PATH)
    assert state == {
        "path": PATH,
        "doc": empty_doc(),
        "loaded": False,
        "dirty": False,
        "pendingOps": [{"kind": "record", "asin": "A", "ms": 1000, "at": AT1}],
        "lastError": "",
        "adoptWaiting": empty_doc(),
    }
    assert effects == [
        {"type": "backup", "path": PATH, "destination": PATH + ".corrupt"}
    ]
    state, effects = vector(store, state, type="backup_result", code=0)
    doc = {
        "schema": 1,
        "books": {
            "A": {
                "ms": 1000,
                "updated_at": AT1,
                "last_played_at": AT1,
                "played_since_download": True,
                "finished": False,
            }
        },
        "push_queue": [],
        "volume": None,
        "speed": None,
        "recovered": True,
    }
    assert state == {
        "path": PATH,
        "doc": doc,
        "loaded": True,
        "dirty": True,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    assert effects == [{"type": "save_now"}]
    state, effects = vector(store, state, type="save")
    assert state["dirty"] is False
    assert effects == [
        {
            "type": "write",
            "text": '{"schema":1,"books":{"A":{"ms":1000,"updated_at":"'
            + AT1
            + '","last_played_at":"'
            + AT1
            + '","played_since_download":true,"finished":false}},"push_queue":[],"volume":null,"speed":null}',
        }
    ]


def test_failed_backup_writes_nothing_retries_then_adopts(store):
    state, effects = vector(store, base(), type="record", asin="A", ms=2000, at=AT2)
    assert state == state_with(
        pendingOps=[{"kind": "record", "asin": "A", "ms": 2000, "at": AT2}]
    )
    assert effects == []
    state, effects = vector(store, state, type="adopt", text="{broken", path=PATH)
    assert state == {
        "path": PATH,
        "doc": empty_doc(),
        "loaded": False,
        "dirty": False,
        "pendingOps": [{"kind": "record", "asin": "A", "ms": 2000, "at": AT2}],
        "lastError": "",
        "adoptWaiting": empty_doc(),
    }
    assert effects == [
        {"type": "backup", "path": PATH, "destination": PATH + ".corrupt"}
    ]
    state, effects = vector(store, state, type="backup_result", code=1)
    assert state == {
        "path": PATH,
        "doc": empty_doc(),
        "loaded": False,
        "dirty": False,
        "pendingOps": [{"kind": "record", "asin": "A", "ms": 2000, "at": AT2}],
        "lastError": "could not back up the unreadable state.json",
        "adoptWaiting": empty_doc(),
    }
    assert effects == [{"type": "retry_backup"}]
    state, effects = vector(store, state, type="retry_backup")
    assert state == {
        "path": PATH,
        "doc": empty_doc(),
        "loaded": False,
        "dirty": False,
        "pendingOps": [{"kind": "record", "asin": "A", "ms": 2000, "at": AT2}],
        "lastError": "could not back up the unreadable state.json",
        "adoptWaiting": empty_doc(),
    }
    assert effects == [
        {"type": "backup", "path": PATH, "destination": PATH + ".corrupt"}
    ]
    state, effects = vector(store, state, type="backup_result", code=0)
    doc = {
        "schema": 1,
        "books": {
            "A": {
                "ms": 2000,
                "updated_at": AT2,
                "last_played_at": AT2,
                "played_since_download": True,
                "finished": False,
            }
        },
        "push_queue": [],
        "volume": None,
        "speed": None,
        "recovered": True,
    }
    assert state == {
        "path": PATH,
        "doc": doc,
        "loaded": True,
        "dirty": True,
        "pendingOps": [],
        "lastError": "could not back up the unreadable state.json",
        "adoptWaiting": None,
    }
    assert effects == [{"type": "save_now"}]
    state, effects = vector(store, state, type="save")
    assert state["dirty"] is False
    assert effects == [
        {
            "type": "write",
            "text": '{"schema":1,"books":{"A":{"ms":2000,"updated_at":"'
            + AT2
            + '","last_played_at":"'
            + AT2
            + '","played_since_download":true,"finished":false}},"push_queue":[],"volume":null,"speed":null}',
        }
    ]


def test_load_not_found_adopts_but_other_failure_waits_to_retry(store):
    state, effects = vector(store, base(), type="load_failed", notFound=True, path=PATH)
    assert state == {
        "path": PATH,
        "doc": empty_doc(),
        "loaded": True,
        "dirty": False,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    assert effects == []
    failed = state_with()
    failed["pendingOps"] = [{"kind": "finished", "asin": "A"}]
    state, effects = vector(
        store, failed, type="load_failed", notFound=False, path=PATH
    )
    assert state == {
        "path": PATH,
        "doc": empty_doc(),
        "loaded": False,
        "dirty": False,
        "pendingOps": [{"kind": "finished", "asin": "A"}],
        "lastError": "could not read state.json",
        "adoptWaiting": None,
    }
    assert effects == [{"type": "retry_read"}]


def test_unloaded_queue_and_settings_are_dropped_and_ops_can_be_noops(store):
    state, effects = vector(
        store, base(), type="set_queue", queue=[{"asin": "A", "ms": 1, "at": AT1}]
    )
    assert state == base()
    assert effects == []
    state, effects = vector(
        store, state, type="set_player_settings", volume=50, speed=1.5
    )
    assert state == base()
    assert effects == []
    loaded = {
        "path": PATH,
        "doc": {
            "schema": 1,
            "books": {},
            "push_queue": [],
            "volume": None,
            "speed": None,
            "recovered": False,
        },
        "loaded": True,
        "dirty": False,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    state, effects = vector(store, loaded, type="record", asin="", ms=1, at=AT1)
    assert state == loaded
    assert effects == []
    state, effects = vector(store, loaded, type="finished", asin="")
    assert state == loaded
    assert effects == []


def test_valid_direct_adopt_and_loaded_record_finished_transitions(store):
    encoded = '{"schema":1,"books":{},"push_queue":[],"volume":null,"speed":null}'
    state, effects = vector(store, base(), type="adopt", text=encoded, path=PATH)
    doc = {
        "schema": 1,
        "books": {},
        "push_queue": [],
        "volume": None,
        "speed": None,
        "recovered": False,
    }
    loaded = {
        "path": PATH,
        "doc": doc,
        "loaded": True,
        "dirty": False,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    assert state == loaded
    assert effects == []
    recorded, effects = vector(store, loaded, type="record", asin="A", ms=700, at=AT1)
    doc_recorded = {
        **doc,
        "books": {
            "A": {
                "ms": 700,
                "updated_at": AT1,
                "last_played_at": AT1,
                "played_since_download": True,
                "finished": False,
            }
        },
    }
    assert recorded == {
        "path": PATH,
        "doc": doc_recorded,
        "loaded": True,
        "dirty": True,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    assert effects == []
    saved, effects = vector(store, recorded, type="save")
    assert saved == {**recorded, "dirty": False}
    assert effects == [
        {
            "type": "write",
            "text": '{"schema":1,"books":{"A":{"ms":700,"updated_at":"'
            + AT1
            + '","last_played_at":"'
            + AT1
            + '","played_since_download":true,"finished":false}},"push_queue":[],"volume":null,"speed":null}',
        }
    ]
    finished, effects = vector(store, saved, type="finished", asin="A")
    finished_doc = {
        **doc_recorded,
        "books": {"A": {**doc_recorded["books"]["A"], "finished": True}},
    }
    assert finished == {
        "path": PATH,
        "doc": finished_doc,
        "loaded": True,
        "dirty": True,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    assert effects == []
    finished, effects = vector(store, finished, type="save")
    assert finished == {
        "path": PATH,
        "doc": finished_doc,
        "loaded": True,
        "dirty": False,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    assert effects == [
        {
            "type": "write",
            "text": '{"schema":1,"books":{"A":{"ms":700,"updated_at":"'
            + AT1
            + '","last_played_at":"'
            + AT1
            + '","played_since_download":true,"finished":true}},"push_queue":[],"volume":null,"speed":null}',
        }
    ]


def test_backup_without_waiting_is_ignored_and_bad_recovered_text_without_path_adopts(
    store,
):
    state, effects = vector(store, base(), type="backup_result", code=1)
    assert state == base()
    assert effects == []


def test_path_change_and_retry_without_a_waiting_document_are_noops(store):
    changed, effects = vector(
        store, base(), type="path_changed", path="/next/state.json"
    )
    assert changed == base("/next/state.json")
    assert effects == []
    waiting = {**base(""), "adoptWaiting": empty_doc()}
    unchanged, effects = vector(store, waiting, type="retry_backup")
    assert unchanged == waiting
    assert effects == []
    adopted, effects = vector(store, base(""), type="adopt", text="garbage", path="")
    assert adopted == {
        "path": "",
        "doc": empty_doc(),
        "loaded": True,
        "dirty": False,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    assert effects == []


def test_adopt_uses_event_path_for_valid_and_corrupt_text(store):
    path = "/adopted/state.json"
    valid = '{"schema":1,"books":{},"push_queue":[],"volume":null,"speed":null}'
    adopted, effects = vector(store, base(""), type="adopt", text=valid, path=path)
    assert adopted == {
        "path": path,
        "doc": empty_doc() | {"recovered": False},
        "loaded": True,
        "dirty": False,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    assert effects == []

    corrupt, effects = vector(store, base(""), type="adopt", text="broken", path=path)
    assert corrupt == {
        **base(path),
        "adoptWaiting": empty_doc(),
    }
    assert effects == [
        {"type": "backup", "path": path, "destination": path + ".corrupt"}
    ]


def test_unloaded_save_and_flush_never_write(store):
    unloaded = {**base(), "dirty": True}
    saved, effects = vector(store, unloaded, type="save")
    assert saved == unloaded
    assert effects == []
    flushed, effects = vector(store, saved, type="flush")
    assert flushed == unloaded
    assert effects == [{"type": "wait_file"}]


def test_backup_events_without_waiting_document_are_noops(store):
    loaded = {
        **base(),
        "doc": {**empty_doc(), "recovered": False},
        "loaded": True,
    }
    for code in (0, 1):
        unchanged, effects = vector(store, loaded, type="backup_result", code=code)
        assert unchanged == loaded
        assert effects == []
    unchanged, effects = vector(store, loaded, type="retry_backup")
    assert unchanged == loaded
    assert effects == []


def test_unknown_event_with_path_does_not_change_loaded_store(store):
    loaded = {
        **base(PATH),
        "doc": {**empty_doc(), "recovered": False},
        "loaded": True,
    }
    unchanged, effects = vector(store, loaded, type="nope")
    assert unchanged == loaded
    assert effects == []


def test_adoption_skips_garbage_pending_ops_and_replays_valid_ops_in_order(store):
    pending = [
        {"kind": "record", "asin": "A", "ms": 100, "at": AT1},
        None,
        "garbage",
        [],
        {"kind": "record", "asin": "A", "ms": 250, "at": AT2},
    ]
    adopted, effects = vector(
        store,
        {**base(), "pendingOps": pending},
        type="adopt",
        text='{"schema":1,"books":{},"push_queue":[],"volume":null,"speed":null}',
        path=PATH,
    )
    entry = {
        "ms": 250,
        "updated_at": AT2,
        "last_played_at": AT2,
        "played_since_download": True,
        "finished": False,
    }
    expected_doc = {
        **empty_doc(),
        "books": {"A": entry},
        "recovered": False,
    }
    assert adopted == {
        "path": PATH,
        "doc": expected_doc,
        "loaded": True,
        "dirty": True,
        "pendingOps": [],
        "lastError": "",
        "adoptWaiting": None,
    }
    assert effects == [{"type": "save_now"}]


def test_queue_settings_save_failure_success_and_path_gates(store):
    loaded_doc = {
        "schema": 1,
        "books": {},
        "push_queue": [],
        "volume": None,
        "speed": None,
        "recovered": False,
    }
    loaded = {
        "path": PATH,
        "doc": loaded_doc,
        "loaded": True,
        "dirty": False,
        "pendingOps": [],
        "lastError": "old",
        "adoptWaiting": None,
    }
    queued, effects = vector(
        store, loaded, type="set_queue", queue=[{"asin": "A", "ms": 3, "at": AT1}]
    )
    assert queued == {
        "path": PATH,
        "doc": {**loaded_doc, "push_queue": [{"asin": "A", "ms": 3, "at": AT1}]},
        "loaded": True,
        "dirty": False,
        "pendingOps": [],
        "lastError": "old",
        "adoptWaiting": None,
    }
    assert effects == [
        {
            "type": "write",
            "text": '{"schema":1,"books":{},"push_queue":[{"asin":"A","ms":3,"at":"'
            + AT1
            + '"}],"volume":null,"speed":null}',
        }
    ]
    failed, effects = vector(store, queued, type="save_failed")
    assert failed == {**queued, "dirty": True, "lastError": "could not save state.json"}
    assert effects == []
    saved, effects = vector(store, failed, type="saved")
    assert saved == {**failed, "lastError": ""}
    assert effects == []
    settings, effects = vector(
        store, loaded, type="set_player_settings", volume=55, speed=1.5
    )
    assert settings == {
        "path": PATH,
        "doc": {**loaded_doc, "volume": 55, "speed": 1.5},
        "loaded": True,
        "dirty": False,
        "pendingOps": [],
        "lastError": "old",
        "adoptWaiting": None,
    }
    assert effects == [
        {
            "type": "write",
            "text": '{"schema":1,"books":{},"push_queue":[],"volume":55,"speed":1.5}',
        }
    ]
    unchanged, effects = vector(
        store, loaded, type="set_player_settings", volume=None, speed=None
    )
    assert unchanged == loaded
    assert effects == []
    empty_path = {**queued, "path": "", "dirty": True}
    unchanged, effects = vector(store, empty_path, type="save")
    assert unchanged == empty_path
    assert effects == []
    unchanged, effects = vector(store, loaded, type="save")
    assert unchanged == loaded
    assert effects == []
    dirty = {**loaded, "dirty": True}
    flushed, effects = vector(store, dirty, type="flush")
    assert flushed == {**dirty, "dirty": False}
    assert effects == [
        {
            "type": "write",
            "text": '{"schema":1,"books":{},"push_queue":[],"volume":null,"speed":null}',
        },
        {"type": "wait_file"},
    ]


def test_malformed_inputs_never_throw(store):
    bad_states = [
        None,
        1,
        "bad",
        [],
        {},
        {"loaded": "yes", "pendingOps": "bad", "doc": None, "adoptWaiting": []},
    ]
    bad_events = [
        None,
        1,
        "bad",
        [],
        {},
        {"type": "adopt", "text": None, "path": 1},
        {"type": "backup_result", "code": "0"},
        {"type": "record", "asin": [], "ms": "x", "at": None},
        {"type": "set_queue", "queue": "bad"},
        {"type": "set_player_settings", "volume": [], "speed": {}},
        {"type": "load_failed", "notFound": "yes"},
        {"type": "unknown"},
    ]
    for state in bad_states:
        for event in bad_events:
            transition = store.call("step", state, event)
            assert set(transition) == {"state", "effects"}
            assert set(transition["state"]) == {
                "path",
                "doc",
                "loaded",
                "dirty",
                "pendingOps",
                "lastError",
                "adoptWaiting",
            }
            assert isinstance(transition["effects"], list)


def _function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    raise AssertionError(f"unterminated function {name}")


def test_qml_applies_every_effect_and_has_one_state_assignment_path():
    source = (REPO / "qml" / "StateStore.qml").read_text(encoding="utf-8")
    apply_body = _function_body(source, "apply")
    for effect in (
        "backup",
        "write",
        "save_now",
        "retry_read",
        "retry_backup",
        "wait_file",
    ):
        assert f'effect.type === "{effect}"' in apply_body
    assert "file.waitForJob()" in apply_body
    assert "reducerState = transition.state" in apply_body
    assert len(re.findall(r"\breducerState\s*=", source)) == 1
    for state_field in (
        "doc",
        "loaded",
        "dirty",
        "pendingOps",
        "lastError",
        "adoptWaiting",
    ):
        assert not re.search(rf"\broot\.{state_field}\s*=", source)
