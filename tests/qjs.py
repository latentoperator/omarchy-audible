"""Run ``qml/lib/*.js`` inside PySide6's ``QJSEngine`` (the Quickshell engine).

The ``qml/lib`` files are pure ECMAScript (``.pragma library``, no Qt imports),
so the same V4 engine that runs them in the shell can load the file from disk
and call its functions. PySide6 is a ``dev`` dependency and the JS tests must
not vanish silently when it is missing: importing this module **fails** without
it, so the suite goes red instead of skipping. Only an explicit
``OMARCHY_AUDIBLE_ALLOW_SKIP_QJS=1`` turns them back into skips, for a machine
that deliberately runs the Python backend alone.

Values cross the boundary as JSON. Python arguments are encoded with
``json.dumps`` and rebuilt in JS with ``JSON.parse``; return values come back
through ``JSON.stringify``. Objects that keep state between calls (a splitter,
a queue) are instead kept alive on the engine's global object and passed around
as :class:`JsRef`, so in-place mutations stick.

``Library.js`` imports ``Positions.js`` with the QML engine's
``.import "file.js" as Qualifier`` syntax (P7, F20). ``QJSEngine`` does not
resolve that itself, so this loader does: the imported file is evaluated in an
isolated function scope and bound to its qualifier, matching what the QML
loader hands the library at runtime.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

if os.environ.get("OMARCHY_AUDIBLE_ALLOW_SKIP_QJS") == "1":
    pytest.importorskip("PySide6")

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQml import QJSEngine
except ImportError as exc:  # pragma: no cover - exercised only without PySide6
    raise ImportError(
        "PySide6 is required for the qml/lib JS test suite; install it with "
        "`pip install -e '.[dev]'`, or set OMARCHY_AUDIBLE_ALLOW_SKIP_QJS=1 to "
        "skip these tests on purpose. They fail rather than skip so a missing "
        "engine can never pass the suite silently."
    ) from exc

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "qml" / "lib"

# The QML engine's JavaScript import: `.import "Positions.js" as Positions`.
_IMPORT = re.compile(
    r'^[ \t]*\.import[ \t]+"([^"]+)"[ \t]+as[ \t]+([A-Za-z_$][\w$]*)[ \t]*;?[ \t]*$',
    re.MULTILINE,
)
# A top-level declaration in a library: column 0 `function name`/`var name`.
_DECLARATION = re.compile(r"^(?:function|var)[ \t]+([A-Za-z_$][\w$]*)", re.MULTILINE)

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


def _resolve_imports(source: str, path: Path) -> tuple[str, list[tuple[str, str]]]:
    """Pull ``.import "file.js" as Qualifier`` lines out of a library.

    Returns the source without those lines and the ``(qualifier, source)`` pairs
    for the loader to bind. Only one level is supported; none of the libraries
    imports another library that itself imports one.
    """
    imports: list[tuple[str, str]] = []
    for match in _IMPORT.finditer(source):
        relative, qualifier = match.group(1), match.group(2)
        imported_path = (path.parent / relative).resolve()
        if not imported_path.is_file():
            raise JsError(f"{path.name} imports a missing file: {imported_path}")
        imported_source = _strip_pragma(imported_path.read_text(encoding="utf-8"))
        if _IMPORT.search(imported_source):
            raise JsError(
                f"{relative} imports another library; only one level is supported"
            )
        imports.append((qualifier, imported_source))
    return _IMPORT.sub("", source), imports


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
        source, imports = _resolve_imports(path.read_text(encoding="utf-8"), path)
        for qualifier, imported_source in imports:
            self._bind_import(qualifier, imported_source)
        # The imported aliases are part of the evaluation scope, not the
        # module's own surface, so they are bound before the diff is taken.
        before = self._globals()
        value = self._engine.evaluate(_strip_pragma(source))
        self._check(value, f"loading {self.name}.js")
        # Top-level function/var declarations become global properties; the diff
        # is the module's public surface, which keeps the API assertion honest.
        self.functions = sorted(self._globals() - before)

    def _bind_import(self, qualifier: str, source: str) -> None:
        """Bind an imported library as ``qualifier``, isolated from this one.

        The imported file's top-level declarations are scoped to the wrapper,
        so its private ``_p`` cannot collide with the importing library's, and
        only its qualifier becomes a global.
        """
        names = sorted(set(_DECLARATION.findall(source)))
        exports = ", ".join(f"{name}: {name}" for name in names)
        wrapped = (
            f"var {qualifier} = (function () {{\n{source}\n"
            f"return {{ {exports} }};\n}})();"
        )
        value = self._engine.evaluate(wrapped)
        self._check(value, f"importing {qualifier}")

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
