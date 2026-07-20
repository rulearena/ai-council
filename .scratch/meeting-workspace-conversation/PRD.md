# Backlog #90：會議工作區與時間序對話介面重整

Status: accepted / done

## 問題

目前場景圖佔據主要閱讀面積，發言與主席操作位於下方，難以快速理解時間序、目前進度與下一步。Relay／parallel 的執行差異也被呈現成不同操作心智模型；法院正式程序則與一般會議混在同一套卡片與 composer 中。

`spec.md` §15 Backlog #90 是本批 canonical contract。

## 使用者成果

- 一般接力與平行會議共用 A3-1 Conversation workspace，發言依真正完成／保存順序排列。
- 角色狀態列、時間序對話與脈絡面板在同一個免反覆捲動的工作區。
- 長文預設收合；點角色可篩選並跳至最近發言。
- 主席輸入與對話相鄰，所有動作說明實際會否呼叫 AI、對象與流程效果。
- Parallel 成員完成即顯示；全員完成後才彙整，reload 保持同一順序。
- 法院以爭點與階段分組，正式 CTA 只來自 backend workflow projection。
- 375px 到桌面寬度皆可操作；原角色形象保留為次要狀態視圖。
- 法院案件名稱只在全域頂欄顯示；桌面版中央庭審紀錄獨立滾動，左右角色與正式流程不隨長文離開視窗。

## 固定產品契約

1. 只有兩個 presentation family：Conversation 與 Court Hearing；relay／parallel 共用 Conversation。
2. Parallel fanout 每位成員讀取相同的 round-start transcript，完成事件以實際 arrival order 立即 append；synthesis 等全員成功後才開始。
3. Conversation composer 不發明 backend 未支援的能力。法院 composer 不推進正式流程。
4. `+` 開啟既有 Case Materials／Evidence drawer；不新增 per-message attachment schema。
5. 歷史 events append-only，不回填、不排序、不改寫。
6. Free-form chat mode 與 parallel 指定角色回應是後續產品批次，不在本批。

## TDD seams

1. Backend `MeetingRunner.start_parallel()` 與 public live meeting snapshot：controlled completion order、frozen transcript、partial visibility、synthesis gate、failure/retry/cancel。
2. Frontend pure workspace projection：events → chronological messages／role state／capabilities／Court Hearing groups。
3. HTTP + Playwright：relay conversation、parallel arrival/reload、courtroom grouped workflow、responsive layout。

## Gates

- 每個 vertical slice 先有原因明確的紅燈，再做最小綠燈。
- Backend full 不低於 600 passed；frontend unit 不低於 50 passed；build 綠；Chromium 不低於 90/90 且新增測試全綠。
- 必要的 direct browser smoke。
- Standards／Spec 雙軸獨立 review 通過。
