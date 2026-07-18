# 02 — Meeting workspace projection interface

Type: task
Status: done
Blocked by: 01

## 目標

建立單一 pure frontend interface，把 backend meeting/events 投影為 Conversation 或 Court Hearing view model；Vue components 不重建 workflow state machine。

## TDD 案例

- events 按保存順序成為 messages，parallel 不按 participant index 重排。
- Human、角色、synthesizer、failed／thinking state 有穩定投影。
- 角色 filter 與 latest-message target deterministic；切換 meeting 不殘留 filter。
- 長文是否預設收合由純函式決定。
- courtroom 僅使用 backend docket／available_actions 分組與 capability；一般 mode 不洩漏法院狀態。

## 完成條件

- public pure seam tests 先紅後綠；型別檢查與 unit suite 綠。

## 完成證據

- `projectMeetingWorkspace()` 以 discriminated `conversation | court-hearing` view model 保留 event 寫入順序，投影角色狀態、parallel k/N／彙整狀態與 backend 法院 capabilities。
- 角色 filter 以 meeting id 隔離，latest target 只對當前 meeting 生效；長文收合政策為可單測 pure function。
- 法院 events 依 backend issue 與 phase 分組，`available_actions` 原樣透傳，未新增 frontend state machine。
- Red：新 public exports 缺失、Court Hearing `phases` 缺失、新 parallel round 誤用上輪 synthesis 均曾產生原因明確的 failing tests。
- Green：`npm run test:unit` → 56 passed；`npm run build` → `vue-tsc --noEmit` 與 Vite build 通過。
