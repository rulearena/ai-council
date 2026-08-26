# Workflow Bindings — AI Council `modular-v1`

> This file stores project values and central locators only. Runtime mechanics come from the
> fixed central revision and are not copied into this repository.

## 0. Workflow source and runtime locators

| Field | Value |
|---|---|
| Runtime contract | `modular-v1` |
| Source mode | `embedded` |
| Source locator | Central AIDLC Workflow repo — canonical source of truth; portable governance copy embedded in this repository (read from the repo root, no Mac-local clone required). |
| Fixed revision | `ecf37e4876ecff39a08f4f0cf30ba26fe69356f1` |
| Full-reference index | `docs/agents/multi-agent-development.md` |
| Runtime router | `docs/agents/runtime-module-router.md` |
| Runtime kernel | `docs/agents/runtime-kernel.md` |
| Orchestrator prompt | `docs/agent-prompts/orchestrator.md` |
| Executor prompt | `docs/agent-prompts/executor.md` |
| Reviewer prompt | `docs/agent-prompts/reviewer.md` |
| Role launch/rebind module | `docs/agents/modules/role-launch-and-rebind.md` |
| Review convergence module | `docs/agents/modules/review-convergence.md` |
| Session recovery module | `docs/agents/modules/session-recovery.md` |
| External publication module | `docs/agents/modules/external-publication.md` |
| External delivery module | `docs/agents/modules/external-delivery.md` |
| Assignment packet schema | `docs/templates/role-assignment-packet.md` |
| Acceptance record schema | `docs/templates/acceptance-record.md` |

The source locator is not standing cross-workspace permission. Packet recipients load only Q,
kernel, matching role prompt, current packet, packet-scoped project documents, and triggered
modules. The authorized issuer additionally reads the router only while creating or refreshing
a packet.

### Portable retrieval (Mac / srv-vm / CI)

The governance contract in this repository is self-contained and portable: Mac, the srv-vm
sandbox, and CI all read the project rules from this repository root with **no Mac-local clone and
no absolute host path**. `Source mode` is `embedded`; the pinned `Fixed revision` above records the
central AIDLC Workflow revision the governance was authored against (version info).

- **In-repo (always resolvable):** `AGENTS.md`, `CLAUDE.md`, this file, `docs/agents/project-development.md`,
  `docs/HANDOFF.md`, `spec.md` §15, and `docs/adr/`.
- **Central AIDLC-provided at the pinned revision (runtime mechanics):** the runtime kernel,
  runtime router, role prompts, role/acceptance modules, and packet/acceptance schemas. When these
  are unavailable in an environment, ordinary roles stay read-only and ask the Human Owner (see
  `AGENTS.md` bootstrap fallback) rather than resolving a host-local path.

## 1. Project identity and scoped documents

| Field | Value |
|---|---|
| Project name | `AI Council` |
| Project root | `<repo-root>` — the `ai-council` repository checkout (canonical identity `github-rulearena:rulearena/ai-council.git` plus exact git commit); resolves to the current portable checkout, never a Mac-local path. |
| Main branch | `main` |
| Project policy entries | `AGENTS.md`, `CLAUDE.md` |
| Canonical project identity | `github-rulearena:rulearena/ai-council.git` plus exact git commit |

| Project document locator / identity rule | Consumer roles | Trigger | Purpose |
|---|---|---|---|
| `AGENTS.md` at packet-fixed project commit | all | session-start | Repository safety and bootstrap policy |
| `CLAUDE.md` at packet-fixed project commit | all | session-start | Compatible policy entry |
| `CONTEXT.md` at packet-fixed project commit | Orchestrator, Executor, Reviewer | idea, plan, review-doc, execute, review-code | Domain vocabulary when packet-scoped |
| `docs/agents/project-development.md` at packet-fixed project commit | Orchestrator, Executor, Reviewer | plan, review-doc, execute, review-code, closeout | AI Council-specific tools, tests, worktrees, data safety, and archive rules |
| `docs/HANDOFF.md` at packet-fixed project commit | Orchestrator | session-start | Current handoff state |
| `spec.md` §15 at packet-fixed project commit | Orchestrator, Executor, Reviewer | plan, review-doc, execute, review-code, closeout | Product backlog SoR and scoped acceptance clauses |
| `docs/adr/` entries fixed by packet | Orchestrator, Executor, Reviewer | plan, review-doc, execute, review-code | Applicable architecture decisions |

## 2. Three role bindings (Human Owner approved)

| Role | Environment | Strategy | Model selector | Reasoning/capability selector | Permission boundary |
|---|---|---|---|---|---|
| Orchestrator | OpenCode human-facing session | `human-selected-session` | `session-selected` | `session-selected` | Read-only investigation, planning, coordination, integration; no implementation or Verdict |
| Executor | OpenCode subagent | `fixed` | `opencode/big-pickle` | `not-applicable` | Packet-authorized `.worktrees/{slice}` implementation workspace write; no merge or acceptance |
| Reviewer | Independent OpenCode subagent | `fixed` | `opencode/big-pickle` | `not-applicable` | Reviewed content read-only; only packet-authorized `.scratch/review-runtime-*` writes |

| Shared field | Value |
|---|---|
| Binding snapshot identity rule | SHA-256 of exact Q bytes plus Q locator and packet-fixed project commit; resolved identity is stored in packet evidence, not written back into Q |

## 3. Stage controllers

| Stage | Unique control entry | Project guide locator | Canonical output / identity | Role |
|---|---|---|---|---|
| Idea | Human-facing OpenCode Orchestrator self-issued packet | `spec.md` §15 and project-approved exploration | Requirements and unresolved decisions fixed in packet/work item | Orchestrator |
| Plan | `scripts/openspec-local` proposal/change | `docs/agents/project-development.md` | `openspec/changes/{change}/` at artifacts commit | Orchestrator |
| `review(doc)` | Controller `review-doc` / review convergence chain | `controller.py` at `086d140bc4682e57e3a2a173c726231e592c5494` (Central AIDLC-provided at pinned revision, portable — no Mac-local absolute path) | Immutable candidate, Verdict, and reviewed plan identity | Reviewer |
| Execute | Packet-fixed `.opencode/agents/executor.md` plus `scripts/openspec-local apply` | `docs/agents/project-development.md` | Base...HEAD implementation identity | Executor |
| `review(code)` | Controller `review-code` / review convergence chain | `controller.py` at `086d140bc4682e57e3a2a173c726231e592c5494` (Central AIDLC-provided at pinned revision, portable — no Mac-local absolute path) | Immutable candidate, Verdict, and reviewed implementation identity | Reviewer |
| closeout | Controller `closeout` plus configured delivery controller | `controller.py` at `086d140bc4682e57e3a2a173c726231e592c5494` (Central AIDLC-provided at pinned revision, portable — no Mac-local absolute path) | Human decision, integration readback, final state | Orchestrator |

| Transition | Value |
|---|---|
| Gate A `pass` → Execute | `direct-after-review-doc-pass` |

| Gate A field | Value |
|---|---|
| Gate A project capability | `git-only` |
| Assignment subject-branch selection rule | Authorized issuer fixes exactly one git branch in every immutable packet; external Gate A branch is forbidden |
| Gate A evidence controller locator/identity | `controller.py` at `086d140bc4682e57e3a2a173c726231e592c5494` (Central AIDLC-provided at pinned revision, portable — no Mac-local absolute path); packet and receipts are content-addressed JSON |
| External Plan locator/semantic identity rule | `not-applicable` |
| Assignment anchor path/raw identity rule | `not-applicable` |
| Handoff identity rule | `not-applicable` |
| Provider-readback identity rule | `not-applicable` |

## 4. Canonical records and review evidence chain

| Record | Provider and stable locator | Identity rule | Semantic author | Writer | Consumers |
|---|---|---|---|---|---|
| Backlog | `spec.md` §15 | Non-reused backlog number plus commit | Project convention | Orchestrator | all roles |
| Plan artifacts | `openspec/changes/{change}/` | Change name plus artifacts commit | Orchestrator | Plan entry | Executor, Reviewer |
| Review evidence/Verdict | Controller-owned `.scratch/{work}/` review chain | Content digest plus exact reviewed identity | Reviewer | Controller recorder | Orchestrator |
| Human acceptance package and decision | Controller-owned `.scratch/{work}/acceptance-*.json` | Package and decision have separate content identities | package: Orchestrator; decision: Human Owner | Controller recorder | Human Owner, later sessions |

| Review convergence evidence | Value |
|---|---|
| Candidate report locator/identity rule | Controller-owned immutable review-chain locator plus SHA-256 content identity |
| Initial R0 Verdict locator/identity rule | Separate immutable Verdict identity bound to exact reviewed identity |
| Orchestrator disposition ledger locator/identity rule | Controller-owned immutable ledger bound to candidate and R0 Verdict |
| Focused R0 adjudication report locator/identity rule | One independent Reviewer report bound to the same reviewed identity and disputed Candidate IDs |
| Superseding/effective Verdict locator/identity rule | Separate identity referencing original report, initial Verdict, ledger, and adjudication |
| Correction Set locator/identity rule | Controller-owned immutable Correction Set bound to effective Verdict |
| Correction Set fixer mapping | `review(doc) → plan semantic author；review(code) → implementation author／Executor` |
| Remediation group and R0/R1/R2 state rule | Unique group identity and round state from the fixed review-convergence module |
| Evidence surface separation rule | Review evidence remains outside the plan/implementation subject identity and cannot mutate it |

## 5. Conditional external publication

| Field | Value |
|---|---|
| Publication mode | `none` |
| Scope configuration locator/identity | `not-applicable` |
| External Plan lifecycle scope locator/identity | `not-applicable` |

### 5A. Conditional external delivery

| Field | Value |
|---|---|
| Delivery mode | `configured` |
| Delivery scope locator/identity | `.github/workflows/aidlc-pilot-ci.yml` at `e8c6e02ba832a7aafa757de993e598cc5254a052`, SHA-256 `7479adf0fc376167eb5e485566f344cf93fde1e997d0bd8388c29ad82bbc7342` |
| Closeout delivery controller locator/identity | `controller.py` at `086d140bc4682e57e3a2a173c726231e592c5494` (Central AIDLC-provided at pinned revision, portable — no Mac-local absolute path); `prepare-delivery` then Human-accepted `closeout` |

Delivery is limited to repository `rulearena/ai-council`, base `main`, owner `rulearena`,
non-force `aidlc/` branches, one exact PR, required checks `backend-tests`, `frontend-unit`,
`frontend-build`, and PR integration after Human acceptance. No direct main mutation, deployment,
release, tag, publication, branch deletion, automatic approval, SIEM access, or force push.

## 6. Project safety and verification

| Field | Value |
|---|---|
| Implementation workspace | `.worktrees/{slice}` inside the project repository |
| Reviewer ephemeral runtime | `.scratch/review-runtime-*` inside the authorized checkout |
| Outside-workspace authority | none; the local central source and Controller each require exact Human authorization per session |
| Verification entry | `scripts/test_all.sh`, backend pytest, frontend `npm run test:unit`, `npm run build`, and packet-scoped e2e/browser checks |
| Non-destructive rules | `docs/agents/project-development.md`; no historical data rewrite, source-unknown overwrite, bare OpenSpec, warning override, deployment, release, publication, or SIEM mutation |
| Existing changes | Preserve; never stage, commit, modify, clean, or revert unless Human explicitly includes them |

## 7. Assignment packet and conditional checkpoints

| Field | Value |
|---|---|
| Packet provider/stable locator | `controller.py` at `086d140bc4682e57e3a2a173c726231e592c5494` (Central AIDLC-provided at pinned revision, portable — no Mac-local absolute path), command `bootstrap-to-packet` |
| Packet identity rule | SHA-256 of canonical packet serialization; every refresh produces a new immutable identity |
| Schema | `docs/templates/role-assignment-packet.md` at §0 fixed revision |
| Initial read-only Idea sentinel | `unassigned-readonly-idea` |
| Initial packet bootstrap mode | `human-facing-orchestrator-self-issue` |
| Initial packet issuer | §2 Human-facing OpenCode Orchestrator session |
| Launcher procedure locator/identity | `not-applicable` |

Initial self-issue uses only Q, router, kernel, Orchestrator prompt, and packet schema. It stops at
`preflight-required`; role-launch evidence must be recorded before an ordinary packet or project
write. Every later packet refresh is performed by the same authorized issuer reading the router.
