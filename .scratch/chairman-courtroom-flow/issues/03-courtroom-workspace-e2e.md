# 03 — Courtroom 爭點 workspace 與端到端整合

Status: ready-for-agent

Blocked by: 01, 02

## 目標

提供主席可操作、可理解、可重整恢復的爭點清單與逐點審理體驗。

## 行為契約

- courtroom meeting 顯示「產生爭點草稿」loading/error/retry；AI 不可用時主席仍可手動新增爭點。
- draft editor 可新增、修改、刪除與上下排序；confirm 前清楚標示尚未開始審理。
- confirm 後顯示 issue progress（待審／攻防中／待裁定／已裁定）及 current focus。
- 每次只提供當前合法 primary action：開始此爭點、送交爭點裁定、進入下一爭點或作成最終判決。
- issue attack 完成後停下，主席 composer 可補充或追問；ruling 後也停下。
- issue ruling 顯示中文 outcome、理由、證據與未解問題；final verdict 與 issue rulings 明確分區。
- reload/switch meeting 從 backend projection 恢復，不跨 meeting 污染 draft/selection。
- legacy courtroom 顯示需要建立爭點，不改寫舊 transcript。
- 非 courtroom UI 不顯示 issue workspace，既有流程保持可用。

## Playwright 情境

1. 建立 courtroom → 手動 issue roster → reorder → confirm → reload 一致。
2. 第一 issue attack 只跑三步並停下；指定 Defense 追問後送 Judge ruling。
3. ruling 後不自動 next；手動開始第二 issue；final 在第二 ruling 前不可用。
4. 全部 ruling 後 final verdict 可執行且 reload 保留。
5. AI draft loading、成功與 failure manual fallback。
6. 統一 composer audience、title/goal edit、系統設定／流程操作、精確 primary CTA。
7. 舊 courtroom meeting gate 與歷史 events unchanged。

## 驗收

- targeted Chromium、frontend unit、backend tests與 build 全綠。
- direct browser smoke 走完整兩爭點 mock courtroom。
- commit 後送雙軸 review。
