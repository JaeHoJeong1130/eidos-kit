"""Run the portable kit regressions without EidosWeb or a local Codex installation."""

from pathlib import Path
import os
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_vnext_*.py",
            "-v",
        ],
        cwd=root,
        env=environment,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
