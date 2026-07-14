# 模型選擇可靠性實作計畫

**Goal:** 合併完成 spec backlog 83、84：meeting role model assignment 可持久化並成為所有執行入口的唯一來源；模型管理提供 Provider 導引與 exact model discovery/manual 流程。

**Architecture:** 後端建立深 module `MeetingModelAssignments`，把 metadata、legacy events、models.yaml 的解析與更新藏在小 interface 後面；HTTP 更新與所有 runner 入口共用同一 seam。Provider 保持為前端產品 domain module，映射到既有 adapter schema，不要求 models.yaml migration。已保存 config 沿用 GET discovery；未保存 config 以不落檔 preview endpoint discovery。

## 固定契約

- 新 meeting participant metadata 保存 relay/parallel 完整 roster 的 model id。
- `PUT /meetings/{meeting_id}/participant-models` 是唯一明確 assignment 更新 interface，body 為完整 role→model map。
- Effective assignment 的 deterministic 次序為：有效 metadata；metadata 無值時最新 event；models.yaml 第一筆；unavailable。
- Metadata 指向已刪除 model 時走 default，不回掃更舊 event。
- Projection 提供 effective `model_config_id`、source 與 warning；fallback/recovery 不寫回 metadata/events。
- Run request models 不具權威；start/respond/sequence/retry 只解析 meeting assignment。
- Provider 與 adapter 分離；舊 models.yaml、既有 CRUD payload、existing discovery endpoint 相容。
- 型號為 exact model ID/version；unsupported discovery 一律保留手動輸入。
- 前端與 API 只處理 credential 環境變數名稱，不處理 API key 明文。

## 已確認 TDD seams

1. **Meeting HTTP seam**：create/get/list/update 與四種 run route 的公開 request/response。
2. **Runner event seam**：從公開 meeting projection 觀察實際 event `model_config_id`，不 mock 內部 assignment module。
3. **Discovery HTTP seam**：mock 真外部 HTTP boundary，驗證 preview/existing discovery 的狀態與 secret safety。
4. **Provider domain seam**：pure projection/payload/label interface，expected values 來自本計畫 literal contract。
5. **Playwright seam**：真瀏覽器操作 New Case、Settings、Model Manager、reload/switch，不存取 Vue 私有 state。

## Tasks

1. Executor 01 逐一 red→green 完成 assignment backend、atomic metadata update 與 run-source convergence；targeted backend commit。
2. Executor 02 逐一 red→green 完成 New Case assignment、meeting hydration、Settings persistence/fallback；targeted build/e2e commit。
3. Executor 03 逐一 red→green 完成 Provider domain、preview/existing discovery foundation；targeted backend/frontend commit。
4. Executor 04 逐一 red→green 完成 Provider-guided Model Manager 與全 UI label；targeted build/e2e commit。
5. Orchestrator 執行完整 gates；獨立 Reviewer 依 `81a65af` 後的核准批次做 Standards/Spec 雙軸 review。
6. Blocking/Major 回原 Executor 修復並複驗；通過後更新 spec/HANDOFF/tickets，merge main、清理 worktree/branch。

## 驗收線

- Backend 不低於 262 passed，所有新增 tests 綠。
- Frontend build 綠；Chromium 不低於 39 passed，所有新增情境綠。
- 真瀏覽器 smoke 覆蓋建立 assignment、reload、Provider discovery/manual fallback。
- `git diff --check` 綠；雙軸 review pass；不修改或回填既有 meeting/events。
