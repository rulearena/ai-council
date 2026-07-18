# 03 — A3-1 Conversation workspace

Type: task
Status: implemented
Blocked by: 02

## 目標

以 production components 實作 A3-1：極窄角色列、中央時間序 feed、右側可收合脈絡、底部相鄰 composer。

## 行為

- Relay／parallel 使用完全相同 layout。
- 長文預設三行，可用 accessible control 展開／收合。
- 點角色篩選並提供跳至最近發言；狀態與思考中提示清楚。
- `+` 開啟既有案卷與證據 drawer。
- 移除重複且無新指示的「開始新回合／請全體回應」入口；只顯示 backend 允許且語意真實的動作。
- 角色形象保留於可收合狀態視圖，不佔據主閱讀區。

## 完成條件

- Unit、targeted Playwright、build 綠；375px 與 desktop 可操作。

## 實作與驗證

- Red：targeted Chromium 先因找不到 `conversation-workspace` 失敗；新增長文／角色篩選／375px／parallel 測試後，再分別抓到角色點擊誤開 Drawer 與 fixed-roster parallel 被投影成 `0/0` 的問題。
- Green：relay／parallel 共用 A3-1 role rail、時間序 feed、右側可收合脈絡與相鄰 composer；長文三行收合、角色篩選／跳至最近發言、parallel 完成數與彙整狀態、375px mobile context 均由 production UI 呈現。結構化輸出的摘要、論點、風險、建議與裁決欄位會轉為完整中文可讀內容，不退化成只有摘要或曝露 raw JSON。
- `+` 僅 emit 至既有 Case Materials drawer；原角色場景保留於次要 `<details>`，不再佔主閱讀區。
- `npm run test:unit`：57 passed；`npm run build`：通過；targeted Chromium：4 passed（含既有模型標籤相容檢查）。
