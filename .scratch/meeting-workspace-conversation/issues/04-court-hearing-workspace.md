# 04 — Court Hearing presentation

Type: task
Status: resolved
Blocked by: 02

## 目標

法院共用 workspace shell，但中央按爭點／攻防階段呈現，正式流程 CTA 固定在右側並完全採用 backend `available_actions`。

## 行為

- 不把法院攻防偽裝成自由聊天。
- Composer 僅允許記錄補充與 backend 支援的指定角色補充；不裁定、不推進。
- current issue、已完成 rulings、final verdict 與 blocked reason 容易辨識。
- 等待主席時顯示精確下一步，不恢復已淘汰的重複 action selector。

## 完成條件

- Civil／criminal、reload、next issue、final gate 的 targeted Playwright 綠。

## Comments

- 2026-07-18 TDD red：新增法院工作區 Playwright 後，`court-hearing-workspace` 不存在，測試在第一個 shell 契約明確失敗。
- 2026-07-18 green：法院改用 A3-1 shell；中央依 backend `issue_id`／`issue_phase` 分組，右側正式 CTA 沿用 `primaryAction`，底部 composer 沿用既有能力投影且不提供 `@all`。
- 保留既有 docket draft CRUD／排序／確認、legacy gate、phase/final retry、ruling、next、final、restart 與 testids；案卷 `+`、角色篩選／最近發言、長文收合、次要場景與 375px 皆覆蓋。
- 驗證：frontend unit 57 passed；build 通過；新增 Court Hearing Playwright、11 個 courtroom targeted flows 與既有 375px sticky-action flow 通過。
- 執行環境沒有模型 selector；Executor 使用 assigned runtime，未能指定 `gpt-5.6-luna`。
