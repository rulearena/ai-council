# 05 — 法院設定與主席動作資訊架構驗收修補

Status: implemented / awaiting acceptance

Blocked by: none

Canonical contract: `spec.md` §15 #88 acceptance 修補

## Outcome

舊法院 meeting 的案件類型只在會議設定補齊；主席 composer 與正式法院流程完全分離，等待狀態與下一步能直接理解。

## Public contracts

- `MeetingSettingsDrawer` 是 meeting-scoped case type 的唯一編輯入口；legacy `requires_case_type` 允許一次補齊，即使舊 docket 已 confirmed，仍走現有原子 settings transition。
- `CourtroomDocketPanel` 只消費 backend `courtroom.available_actions`，顯示 workflow 狀態與單一正式 primary action，不自行建立 state machine。
- `chairmanActionOptions` 在 courtroom 只投影 note 與當下 backend 允許的 directed roles；非 courtroom 的「請全體回應」行為不變。

## TDD seams

1. Frontend unit：legacy confirmed courtroom 的 settings draft 可選 case type；一般 confirmed courtroom 仍鎖定。
2. Frontend unit：courtroom options 不含 `all`，指定角色文案說明不會裁定或推進；其他 relay mode 保留 `all`。
3. Frontend unit：courtroom workflow status 與短 primary labels 由 backend available actions/issue status 決定。
4. Playwright：legacy case-type gate 導向 drawer、atomic save 後 gate 消失；等待裁定只由「送交法官判斷」推進；composer 無「請全體回應」；下一爭點與 final CTA 文案正確。
5. Direct browser：使用既有 legacy courtroom fixture 驗證桌面與 375px 的焦點卡、settings drawer、composer 與 sticky CTA。

## Forbidden

- 不新增或改寫歷史 events。
- 不修改 backend courtroom state machine 或正式攻防順序。
- 不讓 directed response 自動推進正式流程。
- 不改非 courtroom mode 的「請全體回應」契約。
- 不讀寫 workspace 外暫存、設定或服務。

## Acceptance

- 爭點區不再出現案件類型下拉；一鍵開啟會議設定完成補齊。
- 法院 composer 不再顯示「請全體回應」，各指定角色選項清楚說明不推進流程。
- 等待法官時狀態不是「已完成」，主 CTA 短、清楚且必須由主席明示點擊。
- Targeted unit/e2e、完整 frontend unit/build、backend regression 與 direct browser smoke 全綠；若完整 Chromium 被既有 flake 阻擋，必須在相同環境由 main 重現並記入 canonical backlog。

## Completion

- Commits: `892bcb8`, `0a9aa0b`, `543350c`.
- Frontend unit 48/48、build、targeted Chromium 6/6 + legacy terminal 1/1、direct non-test-runner Chromium 通過。
- Backend 589/589 通過；Standards 與 Spec 最終複審均 pass。
- 完整 Chromium 兩次各 89/90，失敗為不同法院 transition 的既有 async refresh race；main 固定點在相同壓力下 10 次重現 4 次，已記錄為 canonical backlog #89。
