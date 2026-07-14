# 02 — 中文 presentation module 與會議識別

Status: ready-for-agent

Blocked by: 01

## Goal

主要 UI 不再暴露可由 mode catalog 解釋的英文 role/step ID，並讓 title 成為使用者辨識 meeting 的主資訊。

## Interface

- 建立一個集中式 frontend presentation module：輸入 mode/participant/event，輸出 role display name、step display label、interaction label、decision label。呼叫端不得各自維護 switch/map。
- role 優先使用 participant `display_name`，其次 mode role `name`，最後才 raw ID。
- 固定輸出區塊中文化：角色回應、裁決、判定事項、論點、風險、建議處置、附帶條件、待釐清事項。
- decision 值只做 UI mapping；事件中的 enum 不變。
- TopBar 顯示 title，複製 `{title}\n會議 ID：{meeting_id}`；raw ID 不常駐。
- Meetings、New Case、Settings、Role drawer、Action bar、主要空狀態與 transcript 固定標籤使用繁體中文。模型 ID、exact model ID、Provider 名稱及 Records 診斷 raw 欄位不翻譯。
- RoleDrawer/history 不顯示 raw step_id，改用 presentation label；Records Drawer 可保留並標示「內部步驟代碼」。

## TDD seams

- Frontend pure module unit seam：courtroom role/step、directed/sequence、parallel participant 與 decision literals。
- Playwright seam：法院 meeting 的席位、抽屜、輸出標題、頂欄及複製內容皆符合中文契約且不顯示 raw courtroom IDs。
- Backend transcript HTTP seam：下載標題使用 title，固定欄位中文化；歷史 event ID 不變。

## Forbidden

- 不改 mode/role/step/schema ID。
- 不建立超出本批的 locale 切換或翻譯管理後台。
