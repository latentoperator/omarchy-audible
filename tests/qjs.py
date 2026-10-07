"""Run ``qml/lib/*.js`` inside PySide6's ``QJSEngine`` (the Quickshell engine).

The ``qml/lib`` files are pure ECMAScript (``.pragma library``, no Qt imports),
so the same V4 engine that runs them in the shell can load the file from disk
and call its functions. PySide6 is an optional test dependency: this module
skips itself with ``pytest.importorskip`` when it is missing, so the Python
suite still runs on a machine without it. Where it is installed these tests
run — they must not skip (P1a).

Values cross the boundary as JSON. Python arguments are encoded with
``json.dumps`` and rebuilt in JS with ``JSON.parse``; return values come back
through ``JSON.stringify``. Objects that keep state between calls (a splitter,
a queue) are instead kept alive on the engine's global object and passed around
as :class:`JsRef`, so in-place mutations stick.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtQml import QJSEngine  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "qml" / "lib"

_APP: QCoreApplication | None = None


def _application() -> QCoreApplication:
    """A ``QCoreApplication`` is required before any ``QJSEngine`` exists."""
    global _APP
    if _APP is None:
        _APP = QCoreApplication.instance() or QCoreApplication([])
    return _APP


class JsError(RuntimeError):
    """A JS evaluation returned an error (or a file failed to load)."""


def _strip_pragma(source: str) -> str:
    """Drop the ``.pragma library`` line; it is QML loader syntax, not JS."""
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith(".pragma")
    )


class JsRef:
    """A JS value kept on the engine's global object under a private name."""

    def __init__(self, module: JsModule, name: str) -> None:
        self._module = module
        self._name = name

    def read(self) -> Any:
        """The object's current value, as JSON-decoded Python data."""
        return self._module._json(self._name)

    def __repr__(self) -> str:
        return f"<JsRef {self._name}>"


class JsModule:
    """One loaded ``qml/lib/<name>.js``, isolated in its own engine."""

    def __init__(self, name: str) -> None:
        _application()
        self.name = name
        self._engine = QJSEngine()
        self._refs = 0
        self._load()

    def _load(self) -> None:
        path = LIB_DIR / f"{self.name}.js"
        if not path.is_file():
            raise FileNotFoundError(f"no such qml/lib file: {path}")
        before = self._globals()
        value = self._engine.evaluate(_strip_pragma(path.read_text(encoding="utf-8")))
        self._check(value, f"loading {self.name}.js")
        # Top-level function/var declarations become global properties; the diff
        # is the module's public surface, which keeps the API assertion honest.
        self.functions = sorted(self._globals() - before)

    def _globals(self) -> set[str]:
        value = self._engine.evaluate(
            "JSON.stringify(Object.getOwnPropertyNames(this))"
        )
        self._check(value, "listing globals")
        return set(json.loads(value.toString()))

    def _check(self, value: Any, what: str) -> None:
        if value.isError():
            raise JsError(f"{what}: {value.toString()}")

    def _json(self, expression: str) -> Any:
        wrapped = (
            "(function(){ var __r = (" + expression + "); "
            "return JSON.stringify(__r === undefined ? null : __r); })()"
        )
        value = self._engine.evaluate(wrapped)
        self._check(value, expression)
        text = value.toString()
        if text == "undefined":
            return None
        return json.loads(text)

    def _argument(self, value: Any) -> str:
        if isinstance(value, JsRef):
            return value._name
        return "JSON.parse(" + json.dumps(json.dumps(value)) + ")"

    def call(self, function: str, *args: Any) -> Any:
        """Call ``function`` and return its JSON-serialisable result."""
        call = f"{function}({', '.join(self._argument(arg) for arg in args)})"
        return self._json(call)

    def hold(self, function: str, *args: Any) -> JsRef:
        """Call ``function`` and keep the object it returns for later calls."""
        self._refs += 1
        name = f"__jsref_{self.name}_{self._refs}"
        value = self._engine.evaluate(
            f"{function}({', '.join(self._argument(arg) for arg in args)})"
        )
        self._check(value, function)
        self._engine.globalObject().setProperty(name, value)
        return JsRef(self, name)

    def read(self, ref: JsRef) -> Any:
        """The current value of a held object."""
        return ref.read()

    def evaluate(self, expression: str) -> Any:
        """Evaluate a JSON-serialisable expression in the module's engine."""
        return self._json(expression)


def load(name: str) -> JsModule:
    """Load ``qml/lib/<name>.js`` in a fresh engine."""
    return JsModule(name)
