"""Load real plugin QML against a stub ``qs.Commons`` and report palette colours.

Run as a script (``python color_harness.py <stub dir>``) by
``test_theme_tokens.py``: it needs a ``QGuiApplication`` with a Qt Quick
runtime, which cannot share a process with the suites that create a
``QCoreApplication``. It prints one JSON object of the colours it observed.

The stub ``qs.Commons`` is written by the test. It provides a ``Color``
singleton, so a file that reads ``Commons.Color.*`` gets the stub's values
while a file that reads a bare ``Color.*`` gets Qt 6.12's own ``QtQuick``
``Color`` singleton instead: nothing, and the colour binding is dropped.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine

REPO = Path(__file__).resolve().parents[1]

# Real plugin files, each binding a palette colour: SoftText reads the popup
# text colour through its channels, StateBadge picks one of four palette
# colours from a JavaScript decision.
FILES = {
    "soft_text": REPO / "qml" / "components" / "SoftText.qml",
    "state_badge": REPO / "qml" / "components" / "StateBadge.qml",
}
PROPERTIES = {
    "soft_text": ("color",),
    "state_badge": ("toneColor", "color"),
}


def rgba(value) -> list[float] | None:
    """The colour as ``[r, g, b, a]`` floats, or ``None`` when it is unset."""
    if value is None:
        return None
    return [round(part, 3) for part in value.getRgbF()]


def main(stub_dir: str) -> int:
    warnings: list[str] = []
    qInstallMessageHandler(lambda mode, context, message: warnings.append(message))
    _app = QGuiApplication([])  # the engine needs a QGuiApplication
    engine = QQmlEngine()
    engine.addImportPath(stub_dir)

    observed: dict[str, object] = {}
    for name, path in FILES.items():
        entry: dict[str, object] = {key: None for key in PROPERTIES[name]}
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
        item = component.create()
        if item is None:
            entry["errors"] = [error.toString() for error in component.errors()]
        else:
            entry.update(
                {
                    property_name: rgba(item.property(property_name))
                    for property_name in PROPERTIES[name]
                }
            )
        observed[name] = entry
    observed["warnings"] = warnings
    print(json.dumps(observed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
