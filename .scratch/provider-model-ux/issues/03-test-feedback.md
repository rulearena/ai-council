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

驗證：新增 5 個 Playwright 流程全綠；Model Manager 相關 7 tests 全綠；frontend unit 10 passed；frontend build 綠；`git diff --check` 綠。

已知後續：後端 health store 的 generation 目前只在 config clear 時遞增；兩個真正併發的 test request 仍可能由較舊請求最後寫入 store。這不會污染本票的當前 row UI，但應由獨立 backend stale-result ticket 修正持久 health projection。
