"""B7 — protocol contract: one schema per event type, every command validated.

The contract is the NDJSON protocol in ARCHITECTURE 4.2. There is one JSON
Schema per event type in ``tests/schemas/``; this module runs **every** command
in the backend registry in fake mode and validates every line it writes.

``make test`` therefore fails if a command emits an event whose ``type`` has no
schema, whose payload does not match its schema, or that breaks the terminal
rule (exactly one final ``done`` or ``error``, and a nonzero exit on failure).
The test module is extended as commands land, per docs/PLAN.md B7.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from omarchy_audible.commands import KNOWN_COMMANDS

TERMINAL_TYPES = frozenset({"done", "error"})

# Every event type the protocol in ARCHITECTURE 4.2 may emit. A schema file must
# exist for each, and no schema may exist for anything else.
DOCUMENTED_EVENT_TYPES = frozenset(
    {
        "doctor",
        "done",
        "error",
        "local",
        "login_url",
        "positions",
        "progress",
        "status",
    }
)

# One fake-mode invocation per command in the registry. B7 must cover every
# command that exists; ``test_contract_covers_every_registered_command`` fails
# when the registry grows and this table does not.
COMMAND_CASES: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("status", (), None),
    ("doctor", (), None),
    ("setup", (), None),
    ("sync", (), None),
    ("get", ("B00FAKE01",), None),
    ("cancel", ("B00FAKE01",), None),
    ("remove", ("B00FAKE01",), None),
    ("local", (), None),
    ("login-start", ("--marketplace", "us"), None),
    ("login-finish", ("--session", "fake-session"), ""),
    ("login-import-cli", (), None),
    ("logout", (), None),
    ("position-get", ("B00FAKE01", "B00FAKE02"), None),
    ("position-push", ("B00FAKE01", "1000"), None),
)

CASE_IDS = [name for name, _, _ in COMMAND_CASES]


def _load_schemas(schemas_dir: Path) -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(schemas_dir.glob("*.json"))
    }


def test_contract_covers_every_registered_command():
    """A command added to the registry must get a contract case in this file."""
    assert {name for name, _, _ in COMMAND_CASES} == set(KNOWN_COMMANDS)


def test_schema_files_cover_the_documented_protocol(schemas_dir):
    jsonschema = pytest.importorskip("jsonschema")
    schemas = _load_schemas(schemas_dir)
    assert set(schemas) == DOCUMENTED_EVENT_TYPES
    for event_type, schema in schemas.items():
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["properties"]["type"]["const"] == event_type


@pytest.mark.parametrize("command,args,stdin", COMMAND_CASES, ids=CASE_IDS)
def test_command_writes_only_valid_events(command, args, stdin, run_cli, events, validate_event):
    result = run_cli(command, *args, fake=True, stdin=stdin)

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"{command}: no events on stdout; stderr={result.stderr!r}"
    for line in lines:
        assert line.startswith("{"), f"{command}: stdout is not NDJSON: {line!r}"

    parsed = events(result)
    for event in parsed:
        validate_event(event)
        assert event["type"] in DOCUMENTED_EVENT_TYPES, f"{command}: undocumented event"

    terminals = [event for event in parsed if event["type"] in TERMINAL_TYPES]
    assert len(terminals) == 1, f"{command}: expected exactly one terminal event"
    assert parsed[-1]["type"] in TERMINAL_TYPES, f"{command}: last event is not terminal"

    if result.returncode == 0:
        assert parsed[-1]["type"] == "done"
    else:
        assert parsed[-1]["type"] == "error"


def test_validator_rejects_an_unknown_event_type(validate_event):
    with pytest.raises(AssertionError):
        validate_event({"type": "mystery_event"})


def test_validator_rejects_a_malformed_event(validate_event):
    jsonschema = pytest.importorskip("jsonschema")
    # `status` without its required payload keys.
    with pytest.raises(jsonschema.ValidationError):
        validate_event({"type": "status", "ready": True})


def test_validator_rejects_an_unknown_done_payload_field(validate_event):
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        validate_event({"type": "done", "garbage": 1})


def test_progress_schema_accepts_the_documented_shapes(validate_event):
    jsonschema = pytest.importorskip("jsonschema")
    validate_event({"type": "progress", "stage": "library", "n": 40, "of": 91})
    validate_event({"type": "progress", "stage": "download", "bytes": 123, "total": 456})
    validate_event({"type": "progress", "stage": "convert", "bytes": 0, "total": 456})
    # A documented stage without its counters is malformed.
    with pytest.raises(jsonschema.ValidationError):
        validate_event({"type": "progress", "stage": "library", "n": 40})
    with pytest.raises(jsonschema.ValidationError):
        validate_event({"type": "progress", "stage": "download"})


def test_positions_schema_requires_an_entry_per_asin(validate_event):
    jsonschema = pytest.importorskip("jsonschema")
    validate_event(
        {
            "type": "positions",
            "items": {"B00FAKE01": {"ms": 1000, "updated_at": None}},
        }
    )
    with pytest.raises(jsonschema.ValidationError):
        validate_event({"type": "positions", "items": {"B00FAKE01": {"ms": 1000}}})
