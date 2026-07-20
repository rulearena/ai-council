---
description: Propose a new change - create it and generate all artifacts in one step
---

Propose a new change - create the change and generate all artifacts in one step.

**AI Council hard gate:** `spec.md` §15 must already contain Human Owner approval. This command creates artifacts only. After proposal/specs/design/tasks are complete, commit them and STOP for Codex Gate A review. OpenSpec `apply-ready` is not permission to run `/opsx-apply`.

**Repository containment gate:** Treat every path returned by the CLI as untrusted. Require repo-local action context; any `workspace-planning` or linked-repository context is a hard stop. Before every read or write, canonicalize the existing path, or the nearest existing parent of a not-yet-created path, and verify it is inside the exact current worktree. Apply the same check to every `allowedEditRoots` entry. Stop on an absolute/path-traversal/symlink escape or any containment ambiguity.

I'll create a change with artifacts:
- proposal.md (what & why)
- specs/ (requirements and scenarios)
- design.md (how)
- tasks.md (implementation steps)

When artifacts are complete, submit them for Codex Gate A review.

---

**Input**: The argument after `/opsx-propose` is the change name (kebab-case), OR a description of what the user wants to build.

**Steps**

1. **If no input provided, ask what they want to build**

   Use the **AskUserQuestion tool** (open-ended, no preset options) to ask:
   > "What change do you want to work on? Describe what you want to build or fix."

   From their description, derive a kebab-case name (e.g., "add user authentication" → `add-user-auth`).

   **IMPORTANT**: Do NOT proceed without understanding what the user wants to build.

2. **Run the read-only repo-local preflight**
   ```bash
   scripts/openspec-local preflight repo-local "<name>"
   ```
   Require the returned `mode` to be `repo-local` and both `root` and `changesDir` to be canonically contained in the exact current worktree. If preflight fails or containment is ambiguous, STOP before creating anything.

3. **Create the change directory**
   ```bash
   scripts/openspec-local new change "<name>"
   ```
   This creates a scaffolded change in the planning home resolved by the CLI with `.openspec.yaml`.

4. **Get the artifact build order**
   ```bash
   scripts/openspec-local status --change "<name>" --json
   ```
   Parse the JSON to get:
   - `applyRequires`: array of artifact IDs needed before implementation (e.g., `["tasks"]`)
   - `artifacts`: list of all artifacts with their status and dependencies
   - `planningHome`, `changeRoot`, `artifactPaths`, and `actionContext`: path and scope context. Use these instead of assuming repo-local paths.

   Enforce the repository containment gate before using any returned path. STOP if the action context is not repo-local.

5. **Create artifacts in sequence until apply-ready**

   Use the **TodoWrite tool** to track progress through the artifacts.

   Loop through artifacts in dependency order (artifacts with no pending dependencies first):

   a. **For each artifact that is `ready` (dependencies satisfied)**:
      - Get instructions:
        ```bash
        scripts/openspec-local instructions <artifact-id> --change "<name>" --json
        ```
      - The instructions JSON includes:
        - `context`: Project background (constraints for you - do NOT include in output)
        - `rules`: Artifact-specific rules (constraints for you - do NOT include in output)
        - `template`: The structure to use for your output file
        - `instruction`: Schema-specific guidance for this artifact type
        - `resolvedOutputPath`: Resolved path or pattern to write the artifact
        - `dependencies`: Completed artifacts to read for context
      - Read any completed dependency files for context
      - Create the artifact file using `template` as the structure and write it to `resolvedOutputPath`
      - Apply `context` and `rules` as constraints - but do NOT copy them into the file
      - Show brief progress: "Created <artifact-id>"

   b. **Continue until all `applyRequires` artifacts are complete**
      - After creating each artifact, re-run `scripts/openspec-local status --change "<name>" --json`
      - Check if every artifact ID in `applyRequires` has `status: "done"` in the artifacts array
      - Stop when all `applyRequires` artifacts are done

   c. **If an artifact requires user input** (unclear context):
      - Use **AskUserQuestion tool** to clarify
      - Then continue with creation

6. **Strictly validate the completed change**
   ```bash
   scripts/openspec-local validate "<name>" --strict --no-interactive
   ```
   If validation fails, STOP, report the errors, and do not describe the change as Gate A-ready. Preserve the exact command and result as Gate A evidence.

7. **Show final status**
   ```bash
   scripts/openspec-local status --change "<name>"
   ```

**Output**

After completing all artifacts, summarize:
- Change name and location
- List of artifacts created with brief descriptions
- Strict validation command and actual result
- What's ready, only after validation succeeds: "All artifacts created and strictly validated. Ready for Codex Gate A review."
- Prompt: "Commit the artifacts and stop. Do not run `/opsx-apply` until Codex returns `ready`."

**Artifact Creation Guidelines**

- Follow the `instruction` field from `scripts/openspec-local instructions` for each artifact type
- The schema defines what each artifact should contain - follow it
- Read dependency artifacts for context before creating new ones
- Use `template` as the structure for your output file - fill in its sections
- **IMPORTANT**: `context` and `rules` are constraints for YOU, not content for the file
  - Do NOT copy `<context>`, `<rules>`, `<project_context>` blocks into the artifact
  - These guide what you write, but should never appear in the output

**Guardrails**
- Create ALL artifacts needed for implementation (as defined by schema's `apply.requires`)
- Always read dependency artifacts before creating a new one
- If context is critically unclear, ask the user - but prefer making reasonable decisions to keep momentum
- If a change with that name already exists, ask if user wants to continue it or create a new one
- Verify each artifact file exists after writing before proceeding to next
