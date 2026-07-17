from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_ROOT = BACKEND_ROOT.parent
RUNTIME_ROOT = CHECKOUT_ROOT / ".scratch" / "pytest-runtime"
PROBE = Path(__file__).with_name("pytest_workspace_probe.py")
AUTHORIZED_EXTERNAL_PROBE = Path(
    "/private/var/folders/6_/g4v6317d6j5djb3gdllp9_nm0000gn/T/pytest-of-chrischiu/"
)


def _run_probe(*args: str) -> subprocess.CompletedProcess[str]:
    system_temp = RUNTIME_ROOT / "system"
    system_temp.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TMPDIR"] = str(system_temp)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(PROBE), "-q", "-s", *args],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _probe_report(result: subprocess.CompletedProcess[str]) -> dict[str, str | None]:
    prefix = "PYTEST_WORKSPACE_PROBE="
    line = next(line for line in result.stdout.splitlines() if line.startswith(prefix))
    return json.loads(line.removeprefix(prefix))


def test_cli_defaults_all_pytest_temp_to_checkout_runtime() -> None:
    result = _run_probe()

    assert result.returncode == 0, result.stdout + result.stderr
    report = _probe_report(result)
    expected_cases = RUNTIME_ROOT / "cases"
    expected_system = RUNTIME_ROOT / "system"
    assert Path(report["tmp_path"]).is_relative_to(expected_cases)
    assert report["tmpdir"] == str(expected_system)
    assert report["tempfile"] == str(expected_system)


def test_cli_preserves_explicit_checkout_local_basetemp(tmp_path: Path) -> None:
    explicit_cases = tmp_path / "explicit-cases"
    result = _run_probe(f"--basetemp={explicit_cases}")

    assert result.returncode == 0, result.stdout + result.stderr
    report = _probe_report(result)
    assert Path(report["tmp_path"]).is_relative_to(explicit_cases)


def test_cli_rejects_external_basetemp_before_creation() -> None:
    assert not AUTHORIZED_EXTERNAL_PROBE.exists()

    result = _run_probe("--collect-only", f"--basetemp={AUTHORIZED_EXTERNAL_PROBE}")

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "--basetemp must stay inside the current checkout" in output
    assert str(CHECKOUT_ROOT) in output
    assert not AUTHORIZED_EXTERNAL_PROBE.exists()
