# Backlog #88 Acceptance 修補計畫：法院設定與主席動作 IA

Status: implemented / awaiting acceptance

## Goal

不變更 courtroom state machine、events 或資料格式，只修正案件類型入口、主席 composer 語意、workflow 狀態與正式下一步 CTA。

## Delivery

1. 以 pure projection unit tests 固定 courtroom composer、workflow status 與短 CTA。
2. 讓 legacy case type 經 meeting settings atomic interface 儲存，docket 只保留導引 banner。
3. 以 Playwright 覆蓋 legacy migration、等待裁定、下一爭點與 final gate。
4. 完整 gates、真瀏覽器 smoke、Standards/Spec 雙軸獨立 review。

## Seams

- `chairmanActions.ts`：meeting workflow projection → composer options / primary action presentation。
- `meetingWorkspace.ts` + `MeetingSettingsDrawer.vue`：meeting projection → editable/locked atomic draft。
- `CourtroomDocketPanel.vue`：backend workflow projection → status、focus、single primary CTA。
- `App.vue`：docket 的「前往會議設定」intent → drawer navigation。

## Gates

- Baseline: backend 589、frontend unit 45、build green、Chromium 90。
- 新增測試全部通過且不得降低基線。
- Direct Chromium 不使用 test runner，runtime/log/cache 全部置於 workspace `.scratch/`。
- 使用 assigned runtime（工具無 Luna/Terra selector）並於交付揭露。
