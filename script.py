# /// script
# requires-python = ">=3.10"
# dependencies = ["PySide6-Essentials>=6.12,<7"]
# ///
"""Alternative Python launcher for AgentSleuth."""

from agentsleuth.ui.qt_app import main

if __name__ == "__main__":
    raise SystemExit(main(__file__))
