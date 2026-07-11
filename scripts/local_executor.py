from __future__ import annotations

import argparse
import json
import subprocess
import textwrap
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class PatchSafetyError(RuntimeError):
    pass


class ExecutorClient(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        json_mode: bool = False,
    ) -> str:
        ...


@dataclass(frozen=True)
class ExecutorConfig:
    sandbox: Path
    ticket: Path
    test_command: str
    max_attempts: int = 2
    planning: bool = False
    protocol: str = "diff"


@dataclass(frozen=True)
class ExecutorResult:
    success: bool
    attempts: int
    test_exit_code: int | None
    test_output: str
    error: str = ""


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        temperature: float = 0,
        max_tokens: int = 4096,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def complete(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        json_mode: bool = False,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"].get("content") or ""


class LocalExecutorHarness:
    def __init__(self, *, config: ExecutorConfig, client: ExecutorClient) -> None:
        self.config = config
        self.client = client

    def run(self) -> ExecutorResult:
        sandbox = self.config.sandbox.resolve()
        ticket = self._safe_existing_path(self.config.ticket, sandbox)
        previous_failure = ""

        last_exit_code: int | None = None
        last_output = ""
        last_error = ""
        plan = self._create_plan(ticket) if self.config.planning else ""
        for attempt in range(1, self.config.max_attempts + 1):
            prompt = self._build_patch_prompt(ticket, previous_failure, plan)
            model_output = self.client.complete(
                prompt,
                enable_thinking=False,
                json_mode=self.config.protocol == "json-files",
            )
            self._write_attempt_file(attempt, "raw.txt", model_output)
            try:
                if self.config.protocol == "json-files":
                    self._write_attempt_file(attempt, "files.json", model_output)
                    apply_json_files(model_output, sandbox)
                else:
                    patch_text = extract_unified_diff(model_output)
                    self._write_attempt_file(attempt, "patch.diff", patch_text)
                    validate_patch_paths(patch_text, sandbox)
                    apply_patch_text(patch_text, sandbox)
            except PatchSafetyError:
                raise
            except (RuntimeError, json.JSONDecodeError, KeyError, TypeError) as error:
                last_error = str(error)
                previous_failure = textwrap.dedent(
                    f"""
                    Previous file application failed.

                    Error:
                    {last_error}

                    Return a valid response in the requested protocol only. Do not include prose.
                    """
                ).strip()
                continue
            test_result = subprocess.run(
                self.config.test_command,
                cwd=sandbox,
                shell=True,
                text=True,
                capture_output=True,
                timeout=120,
            )
            last_exit_code = test_result.returncode
            last_output = (test_result.stdout or "") + (test_result.stderr or "")
            if test_result.returncode == 0:
                return ExecutorResult(
                    success=True,
                    attempts=attempt,
                    test_exit_code=test_result.returncode,
                    test_output=last_output,
                    error="",
                )
            previous_failure = textwrap.dedent(
                f"""
                Previous test command failed.

                Command:
                {self.config.test_command}

                Exit code:
                {test_result.returncode}

                Output:
                {last_output}
                """
            ).strip()

        return ExecutorResult(
            success=False,
            attempts=self.config.max_attempts,
            test_exit_code=last_exit_code,
            test_output=last_output,
            error=last_error,
        )

    def _create_plan(self, ticket: Path) -> str:
        prompt = self._build_plan_prompt(ticket)
        plan = self.client.complete(prompt, enable_thinking=True)
        self._write_attempt_file(0, "plan.txt", plan)
        return plan

    def _build_plan_prompt(self, ticket: Path) -> str:
        spec = read_optional(self.config.sandbox / "spec.md")
        runner = read_optional(self.config.sandbox / "RUNNER.md")
        ticket_text = ticket.read_text(encoding="utf-8")
        return textwrap.dedent(
            f"""
            You are planning a scoped coding task before implementation.

            Return a concise implementation plan only. Do not return a patch.
            Include:
            - files to create or edit
            - tests to write
            - likely import/package setup needed
            - scope boundaries

            ## Runner Notes
            {runner}

            ## Project Spec
            {spec}

            ## Ticket
            {ticket_text}
            """
        ).strip()

    def _build_patch_prompt(self, ticket: Path, previous_failure: str, plan: str) -> str:
        spec = read_optional(self.config.sandbox / "spec.md")
        runner = read_optional(self.config.sandbox / "RUNNER.md")
        ticket_text = ticket.read_text(encoding="utf-8")
        failure_section = f"\n\n## Retry Feedback\n\n{previous_failure}" if previous_failure else ""
        plan_section = f"\n\n## Executor Plan\n\n{plan}" if plan else ""
        return textwrap.dedent(
            f"""
            You are a coding executor working inside one sandbox.

            Rules:
            - Work only inside the sandbox.
            - Do not commit or push.
            - Keep the change scoped to the ticket.
            - Include every new file needed for tests to run.
            {self._protocol_instruction()}

            ## Runner Notes
            {runner}

            ## Project Spec
            {spec}

            ## Ticket
            {ticket_text}
            {plan_section}
            {failure_section}
            """
        ).strip()

    def _protocol_instruction(self) -> str:
        if self.config.protocol == "json-files":
            return (
                '- Return only JSON with shape: {"files":[{"path":"relative/path","content":"full file content"}]}.\n'
                "- Do not include markdown fences, prose, shell commands, or completion reports.\n"
                "- Each file content must be the complete final content for that file."
            )
        return (
            "- Return only one complete unified diff.\n"
            "- Do not include prose, markdown fences, shell commands, or completion reports."
        )

    @staticmethod
    def _safe_existing_path(path: Path, sandbox: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(sandbox):
            raise PatchSafetyError(f"Path escapes sandbox: {path}")
        if not resolved.exists():
            raise FileNotFoundError(path)
        return resolved

    def _write_attempt_file(self, attempt: int, suffix: str, content: str) -> None:
        log_dir = self.config.sandbox / ".local-executor"
        log_dir.mkdir(exist_ok=True)
        (log_dir / f"attempt-{attempt}.{suffix}").write_text(content, encoding="utf-8")


def read_optional(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def extract_unified_diff(model_output: str) -> str:
    text = model_output.strip()
    if "```" not in text:
        return text
    parts = text.split("```")
    for part in parts:
        candidate = part.strip()
        if candidate.startswith("diff"):
            candidate = candidate[4:].lstrip()
        if candidate.startswith("--- ") or candidate.startswith("diff --git"):
            return candidate
    return text


def validate_patch_paths(patch_text: str, sandbox: Path) -> None:
    for raw_line in patch_text.splitlines():
        if not (raw_line.startswith("--- ") or raw_line.startswith("+++ ")):
            continue
        path_text = raw_line[4:].strip().split("\t", 1)[0]
        if path_text == "/dev/null":
            continue
        if path_text.startswith("a/") or path_text.startswith("b/"):
            path_text = path_text[2:]
        path = Path(path_text)
        if path.is_absolute() or ".." in path.parts:
            raise PatchSafetyError(f"Unsafe patch path: {path_text}")
        resolved = (sandbox / path).resolve()
        if not resolved.is_relative_to(sandbox):
            raise PatchSafetyError(f"Patch path escapes sandbox: {path_text}")


def apply_patch_text(patch_text: str, sandbox: Path) -> None:
    strip_arg = "-p1" if patch_uses_git_prefixes(patch_text) else "-p0"
    dry_run = subprocess.run(
        ["patch", strip_arg, "--forward", "--batch", "--dry-run"],
        input=patch_text,
        cwd=sandbox,
        text=True,
        capture_output=True,
        timeout=120,
    )
    if dry_run.returncode != 0:
        raise RuntimeError(
            "patch dry-run failed\n"
            f"stdout:\n{dry_run.stdout}\n"
            f"stderr:\n{dry_run.stderr}"
        )
    process = subprocess.run(
        ["patch", strip_arg, "--forward", "--batch"],
        input=patch_text,
        cwd=sandbox,
        text=True,
        capture_output=True,
        timeout=120,
    )
    if process.returncode != 0:
        raise RuntimeError(
            "patch failed\n"
            f"stdout:\n{process.stdout}\n"
            f"stderr:\n{process.stderr}"
        )


def patch_uses_git_prefixes(patch_text: str) -> bool:
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            return True
        if line.startswith("--- a/") or line.startswith("+++ b/"):
            return True
    return False


def apply_json_files(model_output: str, sandbox: Path) -> None:
    payload = json.loads(model_output)
    files = payload["files"]
    if not isinstance(files, list):
        raise TypeError("files must be a list")
    for file_entry in files:
        path_text = file_entry["path"]
        content = file_entry["content"]
        if not isinstance(path_text, str) or not isinstance(content, str):
            raise TypeError("file path and content must be strings")
        path = Path(path_text)
        if path.is_absolute() or ".." in path.parts:
            raise PatchSafetyError(f"Unsafe file path: {path_text}")
        target = (sandbox / path).resolve()
        if not target.is_relative_to(sandbox):
            raise PatchSafetyError(f"File path escapes sandbox: {path_text}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local LLM executor canary.")
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--ticket", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--planning", action="store_true")
    parser.add_argument("--protocol", choices=["diff", "json-files"], default="diff")
    args = parser.parse_args()

    harness = LocalExecutorHarness(
        config=ExecutorConfig(
            sandbox=args.sandbox,
            ticket=args.ticket,
            test_command=args.test_command,
            max_attempts=args.max_attempts,
            planning=args.planning,
            protocol=args.protocol,
        ),
        client=OpenAICompatibleClient(base_url=args.base_url, model=args.model),
    )
    result = harness.run()
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
