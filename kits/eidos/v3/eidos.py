#!/usr/bin/env python3
"""Run the Eidos v3 project CLI directly from the source kit."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(
        str(
            Path(__file__).resolve().parent
            / "template"
            / ".agents"
            / "tools"
            / "eidos.py"
        ),
        run_name="__main__",
    )
