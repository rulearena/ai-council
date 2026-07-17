from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_ROOT = BACKEND_ROOT.parent
RUNTIME_ROOT = CHECKOUT_ROOT / ".scratch" / "pytest-runtime"
PROBE = Path(__file__).with_name("pytest_workspace_probe.py")


def _run_probe(
    *args: str,
    backend_root: Path = BACKEND_ROOT,
    probe: Path = PROBE,
) -> subprocess.CompletedProcess[str]:
    system_temp = RUNTIME_ROOT / "system"
    system_temp.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TMPDIR"] = str(system_temp)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(probe), "-q", "-s", *args],
        cwd=backend_root,
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


def test_cli_rejects_basetemp_outside_nested_checkout_before_creation(
    tmp_path: Path,
) -> None:
    fake_checkout = tmp_path / "fake-checkout"
    fake_backend = fake_checkout / "backend"
    fake_backend.mkdir(parents=True)
    fake_conftest = fake_backend / "conftest.py"
    fake_probe = fake_backend / "pytest_workspace_probe.py"
    shutil.copyfile(BACKEND_ROOT / "conftest.py", fake_conftest)
    shutil.copyfile(PROBE, fake_probe)
    outside_candidate = tmp_path / "outside-fake-checkout"
    assert not outside_candidate.exists()

    result = _run_probe(
        "--collect-only",
        f"--basetemp={outside_candidate}",
        backend_root=fake_backend,
        probe=fake_probe,
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "--basetemp must stay inside the current checkout" in output
    assert str(fake_checkout) in output
    assert not outside_candidate.exists()
