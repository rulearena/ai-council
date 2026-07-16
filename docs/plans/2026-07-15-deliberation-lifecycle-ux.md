# Backlog #88 實作計畫：審議生命週期與法院工作區

Status: implemented / awaiting acceptance

## Goal

在不改寫歷史 events、不中斷既有模型設定相容性的前提下，加入可追溯 restart、版本化案卷、民刑事案件 profile 與清楚的 meeting workspace IA。

## Delivery order

1. **Deliberation epochs/restart**：先建立 archive/current 的執行邊界，避免後續案卷與法院功能依賴單一無限 event stream。
2. **Versioned case materials**：將 evidence/note 變更與 restart safety gate 接到同一生命週期。
3. **Courtroom case profiles**：在穩定 epoch/material contracts 上加入民刑事語意、流程與 schemas。
4. **Settings/workspace UX**：最後整合 atomic settings、meeting navigation、records、materials 與法院 CTA，避免重做前端流程。

每一片由 Executor 在本隔離 worktree 以 red-green-refactor 實作，完成單一目的 commit 後交由未參與實作的 Reviewer 審查；審查缺陷由 Executor 修正並重審。

## Architecture seams

- `DeliberationEpochs`：raw journal → active/history view；restart command → append-only epoch transition。
- `CaseMaterials`：legacy/versioned materials → prompt/audit views；mutation → revision/pending-impact result。
- `CourtroomCaseProfile`：case type → roles/workflow/prompts/codecs/presentation。
- `MeetingSettings`：完整 draft → validated atomic meeting mutation。
- Frontend pure projections：settings draft、case profile、materials impact、records history selection。

Adapters（HTTP、runner、WebSocket、Vue）只能透過這些深 module 取得規則，不得各自重建 scope、case labels 或 lock logic。

## TDD sequence

每張票先提交可觀察 public behaviour 的 failing tests，再最小實作使其通過，最後只在綠燈下 refactor。禁止以 private helper、內部檔案 layout 或 over-mocked call graph 作主要斷言。

關鍵 failure-first 次序：

1. Legacy epoch/current projection → restart gates/scopes → runner/prompt isolation → transcript/WebSocket。
2. Legacy material projection → mutations/versioning → pending-impact backend gate → notes/prompts。
3. Case type gate/profile → Judge docket → phase workflow/manual judgment → civil/criminal codecs/renderers。
4. Atomic settings API → frontend draft → IA components → Playwright responsive end-to-end。

## Review and gates

- 每片：targeted backend/frontend tests、diff check、independent Standards + Spec review。
- 整批：backend full suite（基線 345）、frontend unit（基線 35）、production build、Chromium E2E（基線 77）。
- Direct browser：普通 restart、證據 identity/count、民事一爭點、sticky 法官判斷、reload/switch isolation、375px。
- 最終更新 `docs/HANDOFF.md` 與 `spec.md` backlog status，合併 main 後再於 main 重跑完整 gates。

## Operational constraints

- 暫存、logs 與 worktree 全部位於 repository 的 `.scratch/` / `.worktrees/`；禁止 `/tmp`。
- 不讀 workspace 外路徑、不呼叫外部 provider、不存取 credentials。
- main 的使用者 `config/models.yaml.example` 修改不屬本批，不得 stage、reset、stash 或覆寫。
- 若 runtime 無 model selector，Executor/Reviewer 使用 assigned runtime，最終報告揭露。
