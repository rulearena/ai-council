# 06 — 法院中央獨立滾動驗收修補

Type: acceptance fix
Status: ready
Blocked by: 04

## 問題

全域頂欄已顯示案件名稱，但 Court Hearing 中央欄又顯示「法院庭審／案件名稱」，浪費閱讀高度。長篇庭審紀錄目前也可能撐高整頁，使左側角色狀態與右側正式流程隨頁面一起被捲走。

## 行為契約

- 移除中央欄重複的 presentation label 與案件名稱；案件名稱仍只由 TopBar 顯示。
- 桌面版工作區使用 viewport 剩餘高度，中央庭審紀錄是自己的 scroll container。
- 捲動中央紀錄時，左側角色列與右側正式流程位置不變且仍可見；左右欄若自身內容過長，各自滾動。
- 角色篩選清除按鈕不可因移除 header 而消失；只有篩選生效時才顯示在中央紀錄的緊湊工具列。
- 375px 行動版既有角色列、正式 CTA、主席 composer 仍可操作，不製造被固定高度困住的內容。
- 不改 backend、events、法院 state machine 或正式 CTA 語意。

## TDD 紅燈

Playwright 建立法院 meeting 並塞入足以溢出的庭審補充，驗證：

1. `court-hearing-record` 中沒有案件名稱或「法院庭審」重複標頭。
2. `court-hearing-scroll` 的 `scrollHeight > clientHeight`，設定 `scrollTop` 後確實改變。
3. 中央滾動前後，角色列與正式流程的 viewport 座標不變，且 `window.scrollY` 不增加。

## 完成條件

- 紅燈先在現有 main 明確重現，再由最小 CSS／template 修正轉綠。
- Court Hearing targeted Playwright、frontend unit、build、完整 Chromium 與 backend full 全綠。
- 真瀏覽器在桌面 viewport 驗證長文滾動與固定左右欄。
- Standards／Spec 兩軸獨立 review 通過。
