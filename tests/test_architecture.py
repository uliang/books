"""Context boundaries are an executable invariant, not a convention.

ADR-0013: the import-linter contracts ride the pytest gate as well as
pre-commit, so a boundary violation fails the suite even off `main`.
This invokes the same command the gate runs, rather than import-linter's
internal API, so it can't drift on a dependency bump.
"""

from __future__ import annotations

import subprocess
import sys


def test_context_boundary_contracts_hold() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "importlinter.cli", "lint-imports"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "Context-boundary contracts broken (ADR-0013):\n"
        f"{result.stdout}\n{result.stderr}"
    )
