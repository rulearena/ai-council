---
description: Implement tasks from an OpenSpec change (Experimental)
---

Implement tasks from an OpenSpec change.

**AI Council hard gate:** STOP unless the caller identifies the exact change, every artifact named by `applyRequires` is complete, and the exact current artifacts commit has a Codex Gate A `ready` conclusion. Implementation must occur in the approved isolated worktree. OpenSpec artifact completeness alone never authorizes apply.

**Repository containment gate:** Treat every path returned by the CLI as untrusted. Require repo-local action context; any `workspace-planning` or linked-repository context is a hard stop. Before every read or write, canonicalize the existing path, or the nearest existing parent of a not-yet-created path, and verify it is inside the exact current worktree. Apply the same check to every `allowedEditRoots` entry. Stop on an absolute/path-traversal/symlink escape or any containment ambiguity.

**Input**: Optionally specify a change name (e.g., `/opsx-apply add-auth`). If omitted, check if it can be inferred from conversation context. If vague or ambiguous you MUST prompt for available changes.

**Steps**

1. **Select the change**

   If a name is provided, use it. Otherwise:
   - Infer from conversation context if the user mentioned a change
   - Auto-select if only one active change exists
   - If ambiguous, run `scripts/openspec-local list --json` to get available changes and use the **AskUserQuestion tool** to let the user select

   Always announce: "Using change: <name>" and how to override (e.g., `/opsx-apply <other>`).

2. **Check status to understand the schema**
   ```bash
   scripts/openspec-local status --change "<name>" --json
   ```
   Parse the JSON to understand:
   - `schemaName`: The workflow being used (e.g., "spec-driven")
   - `planningHome`, `changeRoot`, and `actionContext`: planning scope and edit constraints
   - Which artifact contains the tasks (typically "tasks" for spec-driven, check status for others)

3. **Get apply instructions**

   ```bash
   scripts/openspec-local instructions apply --change "<name>" --json
   ```

   This returns:
   - `contextFiles`: artifact ID -> array of concrete file paths (varies by schema)
   - Progress (total, complete, remaining)
   - Task list with status
   - Dynamic instruction based on current state

   **Handle states:**
   - If `state: "blocked"` or any `applyRequires` artifact is not complete: show the missing artifacts and STOP; do not implement
   - If `state: "all_done"`: report completion and STOP for Gate B; do not suggest archive
   - Otherwise: proceed to implementation

   **Workspace guard:** Enforce the repository containment gate above before using `planningHome`, `changeRoot`, `artifactPaths`, `contextFiles`, or `allowedEditRoots`. Any non-repo-local context is unsupported and must STOP before reading or editing files.

4. **Read context files**

   Read every file path listed under `contextFiles` from the apply instructions output.
   The files depend on the schema being used:
   - **spec-driven**: proposal, specs, design, tasks
   - Other schemas: follow the contextFiles from CLI output

5. **Show current progress**

   Display:
   - Schema being used
   - Progress: "N/M tasks complete"
   - Remaining tasks overview
   - Dynamic instruction from CLI

6. **Implement tasks (loop until done or blocked)**

   For each pending task:
   - Show which task is being worked on
   - Make the code changes required
   - Keep changes minimal and focused
   - Mark task complete in the tasks file: `- [ ]` → `- [x]`
   - Continue to next task

   **Stop and invalidate Gate A if:**
   - Implementation reveals that proposal, delta specs, design, or task semantics must change. Do not edit application code further. An explicitly assigned Implementer may update the artifacts in a separate commit, then must obtain a fresh Gate A for that exact artifact commit before apply resumes.

   **Pause if:**
   - Task is unclear → ask for clarification
   - Implementation reveals a design issue → follow the Gate A invalidation rule above
   - Error or blocker encountered → report and wait for guidance
   - User interrupts

7. **On completion or pause, show status**

   Display:
   - Tasks completed this session
   - Overall progress: "N/M tasks complete"
   - If all done: stop for full gates and Gate B. The later order is exact reviewed-HEAD merge → Human Owner acceptance → dedicated closeout worktree → accepted/done + main-spec sync + archive → closeout commit → independent closeout review → exact closeout merge.
   - If paused: explain why and wait for guidance

**Output During Implementation**

```
## Implementing: <change-name> (schema: <schema-name>)

Working on task 3/7: <task description>
[...implementation happening...]
✓ Task complete

Working on task 4/7: <task description>
[...implementation happening...]
✓ Task complete
```

**Output On Completion**

```
## Implementation Complete

**Change:** <change-name>
**Schema:** <schema-name>
**Progress:** 7/7 tasks complete ✓

### Completed This Session
- [x] Task 1
- [x] Task 2
...

All tasks complete! Run full gates, complete docs, commit the exact review chain, and stop for Codex Gate B review. Do not archive before Human Owner acceptance.
```

**Output On Pause (Issue Encountered)**

```
## Implementation Paused

**Change:** <change-name>
**Schema:** <schema-name>
**Progress:** 4/7 tasks complete

### Issue Encountered
<description of the issue>

**Options:**
1. <option 1>
2. <option 2>
3. Other approach

What would you like to do?
```

**Guardrails**
- Keep going through tasks until done or blocked
- Always read context files before starting (from the apply instructions output)
- If task is ambiguous, pause and ask before implementing
- Any semantic artifact update immediately invalidates Gate A: stop implementation, commit the artifact change, and obtain a fresh Gate A before resuming
- Keep code changes minimal and scoped to each task
- Update task checkbox immediately after completing each task
- Pause on errors, blockers, or unclear requirements - don't guess
- Use contextFiles from CLI output, don't assume specific file names

**Phase boundary:** This command may run only after all required artifacts and the exact artifact commit pass Gate A. Artifact authoring and implementation must never be interleaved under one Gate A approval.
