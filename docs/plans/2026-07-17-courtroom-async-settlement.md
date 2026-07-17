# Backlog #89 法院非同步完成狀態收斂實作計畫

## Fixed point

`4142231`（Backlog #88 accepted / done）

## Slice 1：建立 deterministic feedback loop

- 在公開 API/store seam 控制「completed event 已存在，但 job 尚未 release」的順序。
- 確認 main 會穩定失敗，且失敗訊息對應 UI 卡在無下一步。
- 產出三至五項可證偽假設，只測一個變因。

## Slice 2：最小修復

- 依紅燈證據修正唯一責任邊界。
- 保持 backend courtroom projection 為 Source of Truth；frontend 不自建法院狀態機。
- 以 request generation／settlement contract 防止 stale result commit（若證據指向 frontend）。
- 以明確 job lifecycle signal 修正過早 settled（若證據指向 backend）。

## Slice 3：流程驗證

- arguments → ruling → next issue → ruling → final 全程不 reload。
- targeted backend、frontend unit、Chromium。
- 完整 backend、frontend unit、build、完整 Chromium與真瀏覽器 smoke。

## Slice 4：雙軸 review 與整合

- Standards reviewer 與 Spec reviewer 從 `4142231...HEAD` 獨立審查。
- Blocking／Major 回原 Executor TDD 修復再複驗。
- 更新 `spec.md` #89 與 `docs/HANDOFF.md` 為 `implemented / awaiting acceptance`。
- merge main，重跑 gates，清理 worktree／branch／repo-local runtime artifacts。
