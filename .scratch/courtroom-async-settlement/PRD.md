# Backlog #89：法院非同步完成狀態收斂

Status: approved

## 問題

法院 arguments、ruling 或 final job 已寫入 completed events 後，前端偶爾取得沒有下一步的 courtroom projection，長時間顯示「請先完成目前爭點的必要步驟」，reload 後才恢復。

`spec.md` §15 Backlog #89 是本批 canonical contract。

## 使用者成果

- AI 完成後不需 reload，即顯示正確下一個法院 CTA。
- arguments 完成後顯示「送交法官判斷」。
- ruling 完成後顯示「進入下一爭點」或「作成最終判決」。
- final 完成後顯示最終判決，且不再顯示不可用的流程按鈕。
- running 中間 projection 不得被前端當成 settled。

## 範圍限制

- 不改 courtroom workflow、角色順序、prompt、event schema 或歷史 events。
- 不以固定 sleep 掩蓋競態；必須有 deterministic release-order regression test。
- 不修改既有 meeting 資料。
- 不順手處理其他 UI 或非 courtroom polling。

## TDD seams

1. Backend `GET /meetings/{id}` 與 WebSocket activity projection 在受控 job release 時序下的公開行為。
2. Frontend `refreshMeetingUntilSettled()` 對 running／stale／settled meeting responses 的公開 store 行為。
3. Playwright courtroom arguments、ruling、final 使用者流程，不 reload 即看見下一個 CTA。

## Gates

- deterministic regression test 紅燈後綠燈。
- 相關 backend、frontend unit 與 targeted Chromium 綠。
- backend full 589+、frontend unit 48+、build 綠。
- 完整 Chromium 不得新增相對 main baseline 的失敗。
- 真瀏覽器驗證 courtroom CTA 收斂。
- Standards／Spec 雙軸獨立 review 通過。
