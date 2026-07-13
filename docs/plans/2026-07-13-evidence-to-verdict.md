# 證據到可追溯裁決批次實作計畫

> 狀態：implemented / awaiting acceptance（2026-07-13）。Main 驗收：backend 241 passed、frontend build 綠、Chromium e2e 31 passed。

**核准範圍：** `spec.md` backlog 80、63、64、65。執行順序為證據引用錨點 → 版本化角色輸出契約 → 豐富裁決。

**目標：** 讓案卷中的每份文件可以被 AI 角色以穩定錨點引用，並讓 adjudicator 類角色產生可呈現、可追溯且不破壞舊事件的結構化裁決。

## 架構與相容性契約

- `events.jsonl` 仍是唯一真相來源；不得重寫既有事件或以 `transcript.md` 回填狀態。
- 既有 step id、round/base step id、interaction metadata 全部不變。
- 現行共用 output schema 保留為 `role-output/v1`，內容與 hash 不變。
- 新事件可增加 versioned output schema identity；舊事件缺少 identity 時必須投影為 `role-output/v1`。
- mode role 可宣告 output schema；未宣告時必須使用 `role-output/v1`。
- rich verdict 僅先套用 `kind: adjudicator` 的角色；member 與 synthesizer 行為不變。
- 舊版與新版 parsed output 都必須可經 meeting API、transcript 與前端角色抽屜呈現。
- Case Files 舊資料若沒有新增欄位，必須依檔案順序穩定衍生相同引用錨點。

## 已確認 TDD seams

- **Meeting API seam：** `POST /meetings`、`GET /meetings/{id}` 與執行後事件投影。
- **Runner/event seam：** completed/failed event 的 prompt、schema metadata 與 parsed output。
- **Compatibility seam：** repository 中缺少新欄位的既有 metadata/case files/events 仍可讀。
- **Transcript seam：** `GET /meetings/{id}/transcript.md` 可讀地投影兩種 schema。
- **Frontend seam：** Playwright 從建立案卷、執行 adjudicator 到角色抽屜檢視裁決。

測試只驗證上述公開行為，不 mock repository、runner、parser 等內部協作者；模型呼叫只在 adapter 系統邊界使用既有 mock adapter。

## Slice A1 — Backlog 80：證據編號引用

- 新案卷依建立順序取得穩定、使用者可見的證物編號與引用錨點。
- role-scoped `case_files` prompt block 顯示錨點，並明確要求引用案卷主張時帶錨點。
- API manifest/full projection 讓前端可顯示錨點；舊案卷按順序補衍生值，不改寫檔案。
- targeted backend tests、frontend build、案卷 e2e/真瀏覽器 smoke 通過。

## Slice A2 — Backlog 63/64：版本化角色輸出契約

- 建立 schema registry/codec 邊界，至少包含不變的 `role-output/v1`。
- mode role 可選 schema ID；catalog validation 拒絕未知 schema。
- runner 按 step role 選 schema，prompt、parser、event metadata 使用同一 schema definition。
- retry、directed response、sequence、relay 與 parallel 都不可繞過 schema selection。
- 舊 mode、舊事件與現有 frontend 行為完整相容。

## Slice A3 — Backlog 65：Rich structured verdicts

- 增加 `structured-verdict/v1`，保留 `summary`、`risks`、`recommendation` 等共通可讀欄位，另包含裁決結果、認定事項及其 evidence refs、附帶條件與未決問題。
- 所有 mode 的 adjudicator role 宣告使用 rich verdict；其他 role 維持 `role-output/v1`。
- parser 嚴格驗證欄位與引用字串形狀；解析失敗沿用既有一次自動 retry 語意。
- transcript 與 Role Drawer 對新版 schema 顯示專屬區塊，舊事件顯示不退化。
- backend full pytest、frontend build、完整 e2e 與真瀏覽器 smoke 通過。

## 批次完成線

- 每個 slice 使用獨立 `.worktrees/<slice>` 與 branch，TDD red → green，小步 commit。
- 每個 slice 由獨立 Reviewer 做 spec 與 quality 兩關審查；Blocking/Major 修完才 merge。
- 最終不得低於 main 基線：backend 190 passed、frontend build 綠、e2e 31 passed；新增測試全部通過。
- 完成後在 `spec.md` §15 標記 80、63、64、65，更新 HANDOFF，清理所有 batch worktree/branch，狀態為 `implemented / awaiting acceptance`。
