# 05 — Responsive integration, review and delivery

Type: task
Status: implemented / awaiting review
Blocked by: 03, 04

## 目標

完成 responsive polish、完整 regression gates、獨立雙軸 review、main merge 與清理。

## 驗證

- Relay：發言時間序、role filter、long collapse、materials drawer、reload。
- Parallel：partial arrival、thinking state、arrival order reload、synthesis last。
- Courtroom：docket／arguments／ruling／next／final 不 reload。
- 375px：角色列、feed、context 與 composer 無不可達操作。
- Backend full、frontend unit、build、full Chromium、direct browser smoke。

## 禁止事項

- 不合併 prototype branch；正式功能依 production architecture 重建。
- 不提交或覆寫 `config/models.yaml.example` 的 Human Owner 變更。

## 實作與驗證

- 完整 Chromium 先建立 regression evidence：83 passed／11 failed。11 個紅燈中，「點角色席位開另一個 Drawer」與「沒有新指示仍顯示開始新回合」是 #90 明確取代的舊契約，測試改為角色篩選／跳至最新發言與透過 composer 提供新指示。
- 新 workspace 補齊失敗重試可達性：右側會議脈絡顯示失敗角色與「重試失敗步驟」；席位繼續專注在篩選發言。
- 全域 API 錯誤移至 workspace shell，因此無 meeting／modal 開啟時仍可見，且不會產生重複 `app-error` test id。
- Relay e2e 覆蓋時間序、長文收合、role filter、案卷 Drawer 與 reload；parallel e2e 固定彙整最後、完成序列 reload 不變；courtroom 的 docket／arguments／ruling／next／final 由既有兩爭點流程與新 grouped workspace 共同覆蓋。375px workspace／drawer 測試全綠。
- Backend full：602 passed；frontend unit：57 passed；production build：通過；full Chromium：94 passed。
- Playwright backend／frontend 皆使用 worktree 內 `.scratch/e2e-runtime-ticket05-*`、獨立 8327/3327 與 8328/3328 ports；完成後停止服務並清理這兩個確切 runtime 目錄。
- 本 runtime 沒有可呼叫的 in-app browser session，因此無法另做交互式 direct-browser smoke；實際 Chromium 瀏覽器驗證由 94 個 Playwright flows 完成。
- 環境未提供模型 selector；Executor 使用 assigned runtime，無法指定 `gpt-5.6-luna`。
