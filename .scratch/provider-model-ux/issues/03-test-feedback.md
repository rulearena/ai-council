# Model test loading and stale-response safety

Type: task
Status: open
Blocked by: 02

## 目標

所有 Model Manager 測試按鈕提供立即、慢速、成功、失敗回饋，並避免重複送出與過期回應污染。

## TDD

- Playwright 以 delayed route 驗證 spinner/文字、disabled、slow hint、success/error。
- 驗證同模型重啟測試、切換編輯目標、刪除/關閉表單後 late response 不改目前 UI。
- 如 race 邏輯抽成 pure coordinator，補 frontend unit tests。

## 驗收

- 可存取的 status text/`aria-live`；不只靠動畫表達狀態。
- Targeted e2e、unit 與 build 綠；單一目的 commit。
