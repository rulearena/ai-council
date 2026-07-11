# Local Executor Canary PRD

## Goal

Evaluate whether the local LLM endpoints `qwen27` and `ornith` can act as coding Executors for this project under controlled conditions.

## Context

The project may use Codex and Claude as flexible Orchestrator / Executor / Reviewer roles. The user also has two local llama.cpp OpenAI-compatible endpoints:

- `qwen27`: `http://192.168.50.80:8487/v1`, model `bartowski/Qwen_Qwen3.6-27B-GGUF`
- `ornith`: `http://192.168.50.81:8488/v1`, model `deepreinforce-ai/Ornith-1.0-35B-GGUF`

Both endpoints require `chat_template_kwargs.enable_thinking=false` for normal `content` output and support JSON object output in simple tests.

## Success Criteria

- Each local executor runs the same small implementation ticket in an isolated worktree or sandbox.
- Neither executor commits, pushes, or modifies the main workspace directly.
- The Orchestrator can compare outputs using a consistent scorecard.
- The canary reveals whether either model is suitable for future executor work.

## Non-Goals

- Do not let local executors modify the main workspace directly.
- Do not evaluate full frontend implementation yet.
- Do not require production-grade coding-agent automation.
- Do not automatically adopt either executor's result without Orchestrator review.

## Candidate Canary Ticket

Use `issues/01-backend-meeting-repository.md` as the first canary.

This ticket is intentionally small and backend-focused. It tests whether an executor can read `spec.md`, follow TDD, implement JSONL persistence, and avoid scope creep.

## Minimal Harness

This repo includes a minimal local executor harness:

```text
scripts/local_executor.py
```

It:

- reads the sandbox ticket and context files
- calls an OpenAI-compatible local model endpoint
- optionally asks for a thinking-mode plan first with `--planning`
- asks for a unified diff only
- rejects patch paths that escape the sandbox
- applies the patch inside the sandbox
- runs the configured validation command
- retries with test failure feedback up to `--max-attempts`

Example qwen27 run:

```bash
python3 scripts/local_executor.py \
  --sandbox .scratch/local-executor-canary/sandboxes/qwen27 \
  --ticket .scratch/local-executor-canary/sandboxes/qwen27/.scratch/local-executor-canary/issues/01-backend-meeting-repository.md \
  --base-url http://192.168.50.80:8487/v1 \
  --model bartowski/Qwen_Qwen3.6-27B-GGUF \
  --test-command 'cd backend && pytest' \
  --max-attempts 2 \
  --planning
```

Example ornith run:

```bash
python3 scripts/local_executor.py \
  --sandbox .scratch/local-executor-canary/sandboxes/ornith \
  --ticket .scratch/local-executor-canary/sandboxes/ornith/.scratch/local-executor-canary/issues/01-backend-meeting-repository.md \
  --base-url http://192.168.50.81:8488/v1 \
  --model deepreinforce-ai/Ornith-1.0-35B-GGUF \
  --test-command 'cd backend && pytest' \
  --max-attempts 2 \
  --planning
```

## Backlog

- Test local executor with OpenHands.
- Test local executor with Aider if OpenHands is not viable.
- Consider a minimal custom local harness only if existing tools cannot run the canary safely.
- Add more canary tickets for `TranscriptProjector`, `ModelConfigRepository`, and `PromptRenderer` after the first result is reviewed.
