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

## Review 修正

- Standards／Spec review 發現 parallel future 已建立 completed group、但尚未 publish 前 meeting 轉 terminal 的邊界。新 deterministic test 用 barrier 在三個 future 全部產出後插入 cancel marker，無 sleep；publisher 現在每個 group／event append 前重驗 terminal，completed result 轉為 interrupted diagnostic，已完成的 parse／adapter failure diagnostic 保留原始分類，terminal 後 diagnostics 依 member index 排序。
- Pure workspace projection 現在使用 mode topology、保留重複角色的 queue 第一出現順序、current parallel round attempts 與 activity status：relay 只有 queue 第一位 thinking，其餘 waiting；parallel 未完成成員在 running snapshot／reload 為 thinking，早失敗成員不會讓其他成員變 waiting，全員完成後才輪到 synthesizer thinking；pending retry 優先於舊 failed event。
- 新 workspace Playwright 改為驗證可見 `workspace-operation-status`，並先斷言元件可見；舊 `operation-status` 僅保留 legacy compatibility flows。
- Review 提及 Conversation／Court Hearing shell 結構重複；本輪不做大量元件重構，避免在驗收前擴大 regression surface，後續僅在有第三個 presentation family 或 shell 已實質漂移時再抽取。
- Review-fix 驗證：backend parallel cancel／retry／anonymization／arrival targeted 12 passed；backend full 603 passed；frontend unit 61 passed；build 通過；targeted Chromium 8 passed；full Chromium 94 passed；最後 round-boundary 精確化後 parallel Chromium 1 passed。所有 runtime 位於 worktree `.scratch/`，服務已停止並清理確切目錄。
- Review round 2 以精確 TOCTOU 排程重現「terminal check 通過、cancel append、completed append」；原本 runner 的 read-before-append 仍不是原子發布，故改由 `MeetingRepository.append_event_if()` 在所有同 meeting append 共用的 per-meeting critical section 內，同時完成 locked snapshot predicate 與 event append。Cancel／close marker 也走同一 critical section；lock registry 以 waiter ref-count 回收，不會隨 meeting 數量永久成長。
- Runner 的 sequential／parallel completed model result 都改走 atomic publish。若 cancel 先取得線性化點，completed 不會寫入，改追加 `interrupted`／`result_discarded` diagnostic；parse／adapter／configuration／timeout failure 仍保留原分類。Repository deterministic tests 以 Event barriers（無 sleep）覆蓋 publisher 已進 predicate 後 cancel 競爭的 `completed → cancel`，以及 cancel 已進 append 後 publisher 競爭的 `cancel → interrupted`，禁止 `cancel → completed`。
- Review round 2 targeted：repository concurrency、parallel cancel、sequential terminal、courtroom snapshot 共 10 passed；backend full 605 passed。Frontend production 未再修改，因此沿用前一輪 frontend unit 61、build 與 Chromium 94 的綠燈證據。
