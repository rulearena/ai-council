# 03 — A3-1 Conversation workspace

Type: task
Status: ready
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
