# Workflow Bindings — AI Council 專案綁定檔

> 本檔只保存中央流程的專案變異點：來源、三角色模型、正式流程入口、canonical 紀錄與安全邊界。中央規範與角色 prompt 由 §0 固定 revision 載入，不在此重抄。

## 0. Workflow Source Bootstrap

| 欄位 | 值 |
|---|---|
| 來源模式 | local-path |
| 來源 locator | `/Users/chrischiu/SynologyDrive/Project/VibeCoding_Workflow` |
| 固定 revision | `de1aca49181af3ce8583f6d59b034ea8136d42c6` |
| 規範相對路徑 | `docs/agents/multi-agent-development.md` |
| Orchestrator prompt 相對路徑 | `docs/agent-prompts/orchestrator.md` |
| Executor prompt 相對路徑 | `docs/agent-prompts/executor.md` |
| Reviewer prompt 相對路徑 | `docs/agent-prompts/reviewer.md` |

`local-path` 的 locator 不構成未來 session 的跨 workspace 授權；每個 session 存取前仍須取得 Human Owner 對該精確路徑的明確授權。

## 1. 專案基本資訊

| 欄位 | 值 |
|---|---|
| 專案名稱 | AI Council |
| 專案根目錄 | `/Users/chrischiu/SynologyDrive/Project/AI_Council` |
| 主分支 | main |
| 專案政策入口 | `AGENTS.md`、`CLAUDE.md` |
| 專案必讀文件 | `docs/agents/multi-agent-development.md`（本專案自有內容；與 §0 中央規範為不同文件。三角色分工、gate 順序、acceptance 以 §0 載入的中央規範為準；專案特定工具與 §5 不可破壞規則以本檔為準）、`docs/agent-prompts/{orchestrator,executor,reviewer}.md`、`docs/HANDOFF.md`、`CONTEXT.md`、`spec.md` §15（依閱讀順序） |

## 2. 三角色執行者與模型（Human Owner 核准）

| 角色 | CLI／執行環境 | 模型 | Reasoning effort／能力設定 | 權限邊界 |
|---|---|---|---|---|
| Orchestrator | OpenCode session | session runtime 模型（觀察值 `opencode/big-pickle`） | 依 session 設定 | 唯讀調查、規劃、協調、整合、merge；不實作功能、不產生正式 Verdict |
| Executor | Orchestrator 派遣的 subagent | session runtime 模型 | 依 session 設定 | `.worktrees/{slice}` implementation workspace 可寫；不得 merge、不得宣告 acceptance |
| Reviewer | Orchestrator 派遣的獨立 subagent | session runtime 模型 | 依 session 設定 | 受審內容唯讀；僅可寫 `.scratch/review-runtime-*` 等授權 ephemeral runtime |

## 3. 正式流程入口（Human Owner 核准）

| 階段／檢查點 | 唯一控制入口 | 調用方式或專案指引位置 | Canonical 輸出／狀態 | 負責角色 |
|---|---|---|---|---|
| Idea — 需求探索 | `/grill-with-docs` | `.claude/skills/grill-with-docs/` | `spec.md` §15 backlog 登錄 | Orchestrator |
| Plan — 實作規劃 | `scripts/openspec-local` proposal/change | `openspec/changes/{change}/`（`.opencode/commands/opsx-propose.md`） | proposal、delta specs、design、tasks | Orchestrator |
| review(doc) | AI Council Gate A Reviewer procedure | `docs/agent-prompts/reviewer.md` §Gate A | Verdict 摘要 + reviewed plan identity（記入 `spec.md` §15） | Reviewer |
| Execute — 實作驅動 | `scripts/openspec-local apply` | `.opencode/commands/opsx-apply.md` | 固定 implementation identity（base...HEAD commit） | Executor |
| review(code) | AI Council Gate B Reviewer procedure | `docs/agent-prompts/reviewer.md` §Gate B | Verdict 摘要 + reviewed implementation identity（記入 `spec.md` §15） | Reviewer |
| 收尾 | 既有 closeout/archive procedure | `.opencode/commands/opsx-sync.md`、`opsx-archive.md`、closeout review | `accepted / done` 狀態、archive 位置、exact-HEAD merge | Orchestrator |

## 4. Canonical 紀錄

| 紀錄 | Provider 與穩定 locator | Identity／版本規則 | 誰可寫 | 誰會讀 |
|---|---|---|---|---|
| Backlog | `spec.md` §15 | backlog 編號（不可重用） | Orchestrator | 所有角色 |
| Plan artifacts | `openspec/changes/{change}/` | change 名 + artifacts commit SHA | Plan 控制入口產生者 | Executor、Reviewer |
| Review evidence／Verdict | `spec.md` §15 該條目 + review 的 fixed base...HEAD commit | Verdict 所在 commit；至少保存 Verdict、reviewed plan/implementation identity、findings、independent verification、未驗證範圍 | Reviewer | Orchestrator |
| Human acceptance | `spec.md` §15 該條目（git 版控） | 驗收 commit；至少保存 accepted/rejected、review(code) 通過的 exact implementation identity、實際版本/環境、逐項驗收結果、日期、Human Owner 原始確認的可查核引用 | Orchestrator | Human Owner、後續 session |

`docs/HANDOFF.md` 是可讀性同步摘要，不是 Human acceptance 的唯一 canonical record。

## 5. 專案安全與驗證

| 欄位 | 值 |
|---|---|
| Implementation workspace | `.worktrees/{slice}`（每 slice 一個 worktree） |
| Reviewer ephemeral runtime | `.scratch/review-runtime-*` |
| Workspace 外授權 | 無；local-path workflow source 每 session 需 Human Owner 另行授權 |
| 測試／驗證入口 | `scripts/test_all.sh`、backend `pytest`、frontend `npm run build`、`npm run test:unit`、`npm run test:e2e`（依 Execute/review 控制入口） |
| 不可破壞規則 | 歷史 events／meeting metadata／既有資料不得回填、重寫或 migration；不覆寫來源不明的既有變更；OpenSpec 一律透過 `scripts/openspec-local`，不得裸 `openspec`／`--force`；archive 必須在 Human Owner 驗收通過後 |
| 既有未提交變更處置 | 保留；不得 stage、commit、清理、回退或修改，除非 Human Owner 明確納入本次範圍 |

## 6. 交接

新 session 至少取得：

- 角色與本綁定檔位置；
- 目前 AIDLC 階段；
- canonical plan identity；
- current implementation identity（若有）；
- 未完成 findings／blockers；
- 已驗證與未驗證範圍；
- 下一步。
