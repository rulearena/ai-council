# 01 — 審議輪次與重開

Status: implemented / awaiting acceptance

Blocked by: none

Canonical contract: `spec.md` §15 #88；`.scratch/deliberation-lifecycle-ux/PRD.md`

## Outcome

所有 meeting 都能在保留案卷與完整稽核歷史的前提下重開審議；live runner、retry、projection、WebSocket 與預設逐字稿只看目前輪次。

## Public contracts

- 建立單一 deliberation domain seam，能由 raw append-only events 投影 active epoch、所有 epochs 與 carry-forward 結果。
- 提供 meeting restart HTTP interface：scope 為 `current_issue`、`all_deliberation` 或 `rebuild_issues`，reason 必填；非 courtroom 只允許適用 scope。
- 提供依 epoch 讀取與下載議事紀錄的 HTTP interface，預設 current，明示時可取指定輪或完整歷史。
- restart 透過 versioned system marker 記錄新 epoch、前一輪、原因、scope、issue context 與必要 snapshot；legacy marker 前 events read-time 視為第一輪。
- 新輪事件 ID 不得與舊輪碰撞；internal role/step identity 保持穩定。

## Behaviour

- running/open-in-flight 必須先取消或完成；terminal 必須先 reopen；idle/open 才可 restart。
- `current_issue` 封存目標爭點的攻防與判斷、保留其他已完成爭點；`all_deliberation` 保留已確認 docket；`rebuild_issues` 封存整輪並回到可編輯 goal/case type 的前置狀態。
- archived chairman/AI messages 不進新 prompt；只有後續票據定義的 case notes 可跨輪。
- retry 不得命中 archived failure；parallel synthesis 不得讀 archived members。
- restart 後 WebSocket 必須 full-replace live snapshot，不能只 append marker。
- 不修改或回填既有 events，不永久刪除歷史。

## TDD seams

- Domain public interface：legacy implicit epoch、三種 scope、blank reason、carry-forward、unique identity。
- Meeting HTTP interface：scope/lifecycle conflict、epoch transcript/history。
- Runner observable events/prompts：archived exclusion、retry isolation、parallel isolation。
- WebSocket observable snapshot：restart full replacement。
- Fault-injection：metadata/event 雙檔寫入排序不得形成可執行的半套 restart。

## Acceptance

- 普通 mode 可 restart 全部審議並保留 meeting/案卷。
- courtroom 三種 restart 的 live projection 與歷史皆正確。
- 預設 records 只呈現 current epoch；可瀏覽與下載舊輪。
- 既有 meeting 不需 migration/backfill 即可讀取。
- 相關 backend、frontend unit 與 Chromium tests 通過。

## Forbidden

- 不把 raw repository 改成隱式只回 active events。
- 不 hard-delete、重寫或複製歷史 events/evidence。
- 不建立第二套 meeting lock。
