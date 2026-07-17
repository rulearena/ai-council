from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


CHECKOUT_ROOT = Path(__file__).resolve().parent.parent
PYTEST_RUNTIME_ROOT = CHECKOUT_ROOT / ".scratch" / "pytest-runtime"
PYTEST_SYSTEM_TEMP = PYTEST_RUNTIME_ROOT / "system"
PYTEST_DEFAULT_BASETEMP = PYTEST_RUNTIME_ROOT / "cases"


def _resolved_basetemp(value: str | os.PathLike[str]) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve(strict=False)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Constrain pytest-owned temporary files to the active checkout."""
    runtime_root = PYTEST_RUNTIME_ROOT.resolve(strict=False)
    system_temp = PYTEST_SYSTEM_TEMP.resolve(strict=False)
    if (
        runtime_root == CHECKOUT_ROOT
        or not runtime_root.is_relative_to(CHECKOUT_ROOT)
        or system_temp == CHECKOUT_ROOT
        or not system_temp.is_relative_to(CHECKOUT_ROOT)
    ):
        raise pytest.UsageError(
            "pytest runtime paths must stay inside the current checkout "
            f"({CHECKOUT_ROOT}); received: {runtime_root}"
        )

    explicit_basetemp = config.option.basetemp
    basetemp = (
        PYTEST_DEFAULT_BASETEMP.resolve(strict=False)
        if explicit_basetemp is None
        else _resolved_basetemp(explicit_basetemp)
    )
    if basetemp == CHECKOUT_ROOT or not basetemp.is_relative_to(CHECKOUT_ROOT):
        raise pytest.UsageError(
            "--basetemp must stay inside the current checkout "
            f"({CHECKOUT_ROOT}); received: {basetemp}"
        )

    # tempfile caches its answer, so update both the environment inherited by
    # child processes and the current pytest process before fixtures run.
    system_temp.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(system_temp)
    tempfile.tempdir = str(system_temp)
    config.option.basetemp = str(basetemp)
