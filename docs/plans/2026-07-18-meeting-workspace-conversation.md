# Backlog #90 會議工作區與時間序對話介面實作計畫

## Fixed point

`d9a4b52`（Backlog #89 accepted / done）

## Slice 1：Parallel arrival-order contract

- 先以 controlled futures／threading events 建立穩定紅燈。
- 在 fanout 啟動前凍結 active transcript；worker 只做 model attempt，不寫 repository。
- main runner 以 completion order 收割 future，逐組立即 append。
- 全員完成後才 synthesis；維持 failure、retry、cancel、anonymization 與 event identity。

## Slice 2：Pure workspace projection

- 定義 `Conversation | CourtHearing` presentation discriminated union。
- 把 event chronological messages、role states、filter target、collapse policy、right-context capabilities 放入 pure module。
- Backend courtroom projection 與 mode catalog 仍是 workflow／role Source of Truth。

## Slice 3：A3-1 Conversation production UI

- 建立 meeting workspace shell：role rail／feed／context／composer。
- Relay 與 parallel 同 layout；parallel 只以 thinking／k-of-N／synthesis 狀態呈現執行差異。
- `+` 導向既有 materials drawer；移除重複回合 action。
- 保留角色形象為 secondary collapsible status view。

## Slice 4：Court Hearing adapter

- 以相同 shell 呈現法院專用 issue groups。
- 右側 formal CTA 僅依 `courtroom.available_actions`；composer 不推進程序。
- 保持 #87–#89 lifecycle、settings、evidence impact 與 settlement contracts。

## Slice 5：Integration and delivery

- Targeted unit／HTTP／Playwright，接著完整 backend、frontend unit、build、Chromium。
- Direct browser smoke 驗證 relay、parallel、courtroom 與 375px。
- 從 fixed point 由 Standards 與 Spec 兩位獨立 Reviewer 平行審查。
- Blocking／Major 回 Executor 修復並複驗；merge main 後更新 spec/HANDOFF，再清理 feature 與 prototype worktree／branch。

## 明確排除

- Free-form chat mode。
- Parallel 指定單一角色回應。
- Per-message attachment schema。
- 歷史 event migration／rewrite。
