# 02 — 主席 composer、會議資訊與流程操作

Status: ready-for-agent

Blocked by: 01（需使用後端 projected action/state）

## 目標

把主席所有主要輸入收斂到一個可預期的 interface，並讓 meeting identity/objective 與流程操作可被發現。

## 行為契約

- composer 下拉至少包含：記錄補充、請全體回應、每個 mode/backend 支援定向回應之 active role 的指定回答；parallel 不顯示不支援的角色選項。
- label、placeholder、submit text 與 success feedback 必須明示是否呼叫 AI 及 audience。
- 記錄補充只 append Human message；指定角色沿用 linked directed instruction；請全體回應保存 Human message後執行公開顯示的下一動作，courtroom 必須遵守 issue phase。
- Role Drawer 仍可看歷史/輸出，但不再作為唯一可發現的指定追問入口。
- title 旁提供 edit affordance；idle meeting 可保存 title/goal。running 時禁用；已有 AI events 且 goal 改變時需確認。
- 一般 mode 的 goal change append Human audit event，內容至少能辨識 old/new goal；不改寫既有 events，title-only change 不污染 AI prompt。courtroom docket confirm 後 goal 唯讀，backend 與 UI 都拒絕修改。
- 上方文字為「系統設定」；下方改為「流程操作」且不使用設定齒輪語意。
- primary CTA 由 projected state 顯示精確動作：開始審議／繼續本回合與下一角色／開始新回合；不得因單一 Human event 就變「繼續討論」，不得在 completed round 暗中跑 sequence preset。

## TDD tracer bullets

1. Pure frontend action projection 對 mode/phase/target 產生正確 option、placeholder、button label。
2. Chairman note 不觸發 model；targeted action 只觸發選定 role；全體 action 顯示並執行相同 next action。
3. Edit title/goal reload 後保留；running 禁止；一般 mode goal change confirm + audit event；confirmed courtroom goal 拒絕；title-only 無 audit。
4. 無 AI events但有 Human note 時仍顯示「開始審議」。
5. Completed non-courtroom round顯示「開始新回合」，sequence 只存在流程操作且執行前可見順序。

## 相關檔案

- `frontend/src/components/ActionBar.vue`
- `frontend/src/components/TopBar.vue`
- `frontend/src/components/RoleDrawer.vue`
- `frontend/src/components/SettingsModal.vue`
- `frontend/src/composables/useCouncil.ts`
- 新增小型 chairman/workflow presentation module
- `frontend/src/api.ts`
- `backend/ai_council/api.py`
- frontend unit / backend API tests

## 驗收

- targeted backend/frontend unit tests與 build 全綠並 commit。
