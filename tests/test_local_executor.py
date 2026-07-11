from __future__ import annotations

from pathlib import Path

import pytest

from scripts.local_executor import (
    ExecutorConfig,
    LocalExecutorHarness,
    PatchSafetyError,
)


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.prompt = ""
        self.thinking_values: list[bool] = []

    def complete(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        json_mode: bool = False,
    ) -> str:
        self.prompt = prompt
        self.thinking_values.append(enable_thinking)
        return self.content


def test_harness_applies_model_patch_inside_sandbox_and_runs_command(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / ".scratch/local-executor-canary/issues").mkdir(parents=True)
    (sandbox / ".scratch/local-executor-canary/issues/01-ticket.md").write_text(
        "# Ticket\n\nCreate hello.txt.\n",
        encoding="utf-8",
    )
    patch = """\
```diff
--- /dev/null
+++ hello.txt
@@ -0,0 +1 @@
+hello from executor
```
"""
    harness = LocalExecutorHarness(
        config=ExecutorConfig(
            sandbox=sandbox,
            ticket=sandbox / ".scratch/local-executor-canary/issues/01-ticket.md",
            test_command="test -f hello.txt",
            max_attempts=1,
        ),
        client=FakeClient(patch),
    )

    result = harness.run()

    assert result.success is True
    assert (sandbox / "hello.txt").read_text(encoding="utf-8").strip() == "hello from executor"
    assert result.attempts == 1
    assert result.test_exit_code == 0
    assert "Create hello.txt" in harness.client.prompt
    assert harness.client.thinking_values == [False]


def test_harness_rejects_patch_that_escapes_sandbox(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ticket = sandbox / "ticket.md"
    ticket.write_text("# Ticket\n", encoding="utf-8")
    patch = """\
--- /dev/null
+++ ../outside.txt
@@ -0,0 +1 @@
+bad
"""
    harness = LocalExecutorHarness(
        config=ExecutorConfig(
            sandbox=sandbox,
            ticket=ticket,
            test_command="true",
            max_attempts=1,
        ),
        client=FakeClient(patch),
    )

    with pytest.raises(PatchSafetyError):
        harness.run()

    assert not (tmp_path / "outside.txt").exists()


def test_harness_retries_once_with_test_failure_feedback(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ticket = sandbox / "ticket.md"
    ticket.write_text("# Ticket\nCreate pass.txt.\n", encoding="utf-8")

    class RetryClient:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(
            self,
            prompt: str,
            *,
            enable_thinking: bool = False,
            json_mode: bool = False,
        ) -> str:
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                return """\
--- /dev/null
+++ fail.txt
@@ -0,0 +1 @@
+nope
"""
            return """\
--- /dev/null
+++ pass.txt
@@ -0,0 +1 @@
+ok
"""

    harness = LocalExecutorHarness(
        config=ExecutorConfig(
            sandbox=sandbox,
            ticket=ticket,
            test_command="test -f pass.txt",
            max_attempts=2,
        ),
        client=RetryClient(),
    )

    result = harness.run()

    assert result.success is True
    assert result.attempts == 2
    assert "Previous test command failed" in harness.client.prompts[1]


def test_harness_applies_git_style_patch_without_creating_a_directory(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ticket = sandbox / "ticket.md"
    ticket.write_text("# Ticket\nCreate backend file.\n", encoding="utf-8")
    patch = """\
diff --git a/backend/example.txt b/backend/example.txt
new file mode 100644
--- /dev/null
+++ b/backend/example.txt
@@ -0,0 +1 @@
+ok
"""
    harness = LocalExecutorHarness(
        config=ExecutorConfig(
            sandbox=sandbox,
            ticket=ticket,
            test_command="test -f backend/example.txt",
            max_attempts=1,
        ),
        client=FakeClient(patch),
    )

    result = harness.run()

    assert result.success is True
    assert (sandbox / "backend/example.txt").read_text(encoding="utf-8").strip() == "ok"
    assert not (sandbox / "a").exists()


def test_harness_can_request_thinking_plan_before_patch(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ticket = sandbox / "ticket.md"
    ticket.write_text("# Ticket\nCreate planned.txt.\n", encoding="utf-8")

    class PlanningClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def complete(
            self,
            prompt: str,
            *,
            enable_thinking: bool = False,
            json_mode: bool = False,
        ) -> str:
            self.calls.append((prompt, enable_thinking))
            if enable_thinking:
                return "Plan: create planned.txt and validate it exists."
            return """\
--- /dev/null
+++ planned.txt
@@ -0,0 +1 @@
+planned
"""

    client = PlanningClient()
    harness = LocalExecutorHarness(
        config=ExecutorConfig(
            sandbox=sandbox,
            ticket=ticket,
            test_command="test -f planned.txt",
            max_attempts=1,
            planning=True,
        ),
        client=client,
    )

    result = harness.run()

    assert result.success is True
    assert client.calls[0][1] is True
    assert client.calls[1][1] is False
    assert "Executor Plan" in client.calls[1][0]


def test_harness_can_apply_json_file_protocol(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ticket = sandbox / "ticket.md"
    ticket.write_text("# Ticket\nCreate JSON protocol file.\n", encoding="utf-8")
    client = FakeClient(
        '{"files":[{"path":"backend/example.py","content":"VALUE = 1\\n"}]}'
    )
    harness = LocalExecutorHarness(
        config=ExecutorConfig(
            sandbox=sandbox,
            ticket=ticket,
            test_command="test -f backend/example.py",
            max_attempts=1,
            protocol="json-files",
        ),
        client=client,
    )

    result = harness.run()

    assert result.success is True
    assert (sandbox / "backend/example.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_harness_rejects_json_file_protocol_outside_sandbox(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ticket = sandbox / "ticket.md"
    ticket.write_text("# Ticket\n", encoding="utf-8")
    client = FakeClient(
        '{"files":[{"path":"../outside.py","content":"bad\\n"}]}'
    )
    harness = LocalExecutorHarness(
        config=ExecutorConfig(
            sandbox=sandbox,
            ticket=ticket,
            test_command="true",
            max_attempts=1,
            protocol="json-files",
        ),
        client=client,
    )

    with pytest.raises(PatchSafetyError):
        harness.run()
