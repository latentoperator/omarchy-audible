"""Omarchy Audible backend package.

Runs inside the plugin-owned virtualenv and imports the pinned third-party
``audible`` dependency. The standard-library launcher in ``bin/`` bootstraps
that venv and re-execs this package.
"""
