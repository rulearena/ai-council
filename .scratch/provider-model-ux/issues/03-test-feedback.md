# Model test loading and stale-response safety

Type: task
Status: resolved
Blocked by: 02, 04

## 目標

所有 Model Manager 測試按鈕提供立即、慢速、成功、失敗回饋，並避免重複送出與過期回應污染。

## TDD

- Playwright 以 delayed route 驗證 spinner/文字、disabled、slow hint、success/error。
- 驗證同模型重啟測試、切換編輯目標、刪除/關閉表單後 late response 不改目前 UI。
- 如 race 邏輯抽成 pure coordinator，補 frontend unit tests。

## 驗收

- 可存取的 status text/`aria-live`；不只靠動畫表達狀態。
- Targeted e2e、unit 與 build 綠；單一目的 commit。

## Answer

Model Manager 的 row-level 測試現在會立即顯示 spinner 與「正在測試連線…」，同列進行中同時以 disabled 與 handler guard 防止重複；1 秒後切換為「Provider 回應較慢，仍在等待…」。成功、HTTP failure 與 provider unavailable 都會透過 `role="status"`、`aria-live="polite"` 的文字回饋呈現，並同步更新該列狀態點。

每個 model ID 使用獨立 generation；Settings 關閉造成 panel unmount，進入編輯與確認刪除也會 invalidate generation 並清除 timer。Playwright 已覆蓋關閉後新測試、進入編輯，以及刪除後用相同 ID 重建時，舊回應都不能更新目前 UI。

完成結果會在 generation 仍為 current 時重新讀取 `GET /models`，因此 row feedback 因切換分頁或關閉 modal 而 unmount 後，成功／失敗 health 仍由後端 projection 正確顯示；refresh 完成後會再次檢查 generation，過期請求仍不得提交目前 feedback。

驗證：test feedback/stale/projection 6 個 Playwright 流程全綠；Model Manager 相關 7 tests 全綠；frontend unit 10 passed；frontend build 綠；`git diff --check` 綠。

後端持久 health projection 的 concurrent result ordering 已由 Ticket 05 補齊；本票 refresh 後取得的是只接受最新 token 的結果。
