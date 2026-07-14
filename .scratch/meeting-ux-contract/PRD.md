# 會議語意與中文化 UX

Status: implemented / awaiting acceptance

Canonical backlog: `spec.md` §15 #86

## Problem

目前 `topic` 同時承擔人類識別名稱與 AI 任務目標；內部 role/step ID 與英文輸出欄位直接出現在主要 UI；頂欄以長 meeting ID 取代名稱；「請角色回應」沒有問題內容，實際上只是重跑角色最後一個 phase template。這些行為讓使用者難以理解會議如何運作，也可能讓 AI 把短標題誤認為最終任務。

## Approved outcome

- 新 meeting 必填 `title` 與 `goal`；title 只服務人類識別，goal 才是 AI 任務。
- 舊 metadata 只有 `topic` 時必須由使用者補 goal 後才能再執行；不以 topic 當 goal、不靜默回填。
- 主要使用者流程以繁體中文顯示 mode catalog 的 role name、step label 與輸出欄位；raw ID 僅留在診斷／進階資訊。
- 頂欄顯示 title；複製內容為 title + meeting ID。
- 定向角色回應必填 instruction，保存目標角色與可追溯關係，使用專用通用 prompt 回答使用者問題。

## Non-goals

- 不建立完整多語 i18n framework。
- 不翻譯模型、Provider、adapter、schema 或歷史事件中的 raw ID。
- 不改寫歷史 events、模型輸出或案卷。
- 不改 relay/parallel round、retry、sequence 的既有執行順序。
- 不加入對特定發言片段的 quote/thread picker；本批只做 meeting-level 明確定向追問。

## Acceptance gates

- Backend full suite 不低於 291 passed；新增測試全綠。
- Frontend unit 不低於 12 passed；新增測試全綠。
- Frontend build 通過。
- Chromium e2e 全綠，並以真瀏覽器 smoke 驗證建立、舊 meeting 遷移、中文呈現、複製與定向追問。
- Standards 與 Spec 兩軸獨立 review 皆無 Blocking/Major。
