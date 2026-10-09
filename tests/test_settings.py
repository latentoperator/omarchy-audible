"""R1a settings validation and manifest contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import qjs

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_KEYS = {
    "skipSeconds",
    "defaultSort",
    "autoRemoveFinished",
    "showTitleInBar",
    "defaultSpeed",
    "syncOnOpenHours",
}
DEFAULTS = {
    "skipSeconds": 15,
    "defaultSort": "Recently listened",
    "autoRemoveFinished": "Off",
    "showTitleInBar": "Off",
    "defaultSpeed": 1.0,
    "syncOnOpenHours": 6,
}


@pytest.fixture(scope="module")
def settings() -> qjs.JsModule:
    return qjs.load("Settings")


def test_manifest_matches_library_defaults_and_scope(settings: qjs.JsModule) -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    schema = manifest["barWidget"]["schema"]
    by_key = {entry["key"]: entry for entry in schema}
    assert set(by_key) == EXPECTED_KEYS
    manifest_defaults = dict(DEFAULTS, defaultSpeed="1.0×")
    assert manifest["barWidget"]["defaults"] == manifest_defaults
    assert {
        key: item["defaultValue"] for key, item in by_key.items()
    } == manifest_defaults
    scope = (ROOT / "docs/SCOPE.md").read_text(encoding="utf-8")
    settings_table = scope.split("### 4.6 Settings", 1)[1].split("\n### ", 1)[0]
    scope_keys = set(re.findall(r"^\| `([^`]+)` \|", settings_table, re.MULTILINE)) - {
        "booksDir"
    }
    assert scope_keys == set(by_key)
    assert "`booksDir`" not in by_key
    assert settings.call("normalize", manifest["barWidget"]["defaults"]) == DEFAULTS


@pytest.mark.parametrize(
    "key,valid,invalid,wrong",
    [
        ("skipSeconds", "30", 4, {"bad": True}),
        ("defaultSort", "Title", "title", 3),
        ("autoRemoveFinished", "On", "yes", True),
        ("showTitleInBar", "On", "maybe", False),
        ("defaultSpeed", "1.5×", "fast", {"speed": 1.5}),
        ("syncOnOpenHours", "7", 49, []),
    ],
)
def test_each_setting_defaults_validates_range_and_type(
    settings, key, valid, invalid, wrong
) -> None:
    assert settings.call("normalize", {})[key] == DEFAULTS[key]
    assert (
        settings.call("normalize", {key: valid})[key]
        == {
            "defaultSpeed": 1.5,
            "defaultSort": "Title",
            "autoRemoveFinished": "On",
            "showTitleInBar": "On",
            "skipSeconds": 30,
            "syncOnOpenHours": 7,
        }[key]
    )
    assert settings.call("normalize", {key: invalid})[key] == DEFAULTS[key]
    assert settings.call("normalize", {key: wrong})[key] == DEFAULTS[key]
    assert settings.call("normalize", "garbage")[key] == DEFAULTS[key]


def test_speed_accepts_numeric_preset_and_garbage_object_falls_back(settings) -> None:
    assert settings.call("normalize", {"defaultSpeed": 1.25})["defaultSpeed"] == 1.25
    assert settings.call("normalize", {"defaultSpeed": {"x": 1}})["defaultSpeed"] == 1.0


@pytest.mark.parametrize(
    "saved,setting,last,expected",
    [
        (1.25, 1.0, 1.0, {"apply": False, "speed": 1.25}),
        (1.25, 1.5, 1.0, {"apply": True, "speed": 1.5}),
        (None, 1.5, None, {"apply": True, "speed": 1.5}),
        (1.25, 1.5, 1.5, {"apply": False, "speed": 1.25}),
    ],
)
def test_default_speed_choice(settings, saved, setting, last, expected) -> None:
    assert settings.call("speedChoice", saved, setting, last) == expected


def test_mini_skip_accepts_amount() -> None:
    mini = qjs.load("Mini")
    assert mini.call("skipSeconds", "back", 30) == -30
    assert mini.call("skipSeconds", "forward", 30) == 30


def test_old_skip_and_sync_constants_are_not_used_for_behaviour() -> None:
    sources = [ROOT / "BarWidget.qml", *(ROOT / "qml").rglob("*.qml")]
    joined = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    assert "Mini.SKIP_SECONDS" not in joined
    assert "Drawer.SYNC_HOURS" not in joined


def test_service_owns_and_applies_widget_settings() -> None:
    service = (ROOT / "Service.qml").read_text(encoding="utf-8")
    widget = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
    assert "onSettingsChanged: if (service) service.applySettings(settings)" in widget
    for setting in (
        "skipSeconds",
        "defaultSort",
        "autoRemoveFinished",
        "showTitleInBar",
        "defaultSpeed",
        "syncOnOpenHours",
    ):
        assert setting in service
    assert "LibraryUi.syncDue(age, syncOnOpenHours)" in service
    assert (
        "Settings.speedChoice(store.doc.speed, defaultSpeed, store.doc.default_speed_setting)"
        in service
    )
    assert "store.setDefaultSpeedSetting(defaultSpeed)" in service
    assert "default_speed_setting" in (ROOT / "qml/StateStore.qml").read_text(
        encoding="utf-8"
    )
