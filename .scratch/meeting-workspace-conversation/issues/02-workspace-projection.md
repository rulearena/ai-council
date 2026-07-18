# 02 — Meeting workspace projection interface

Type: task
Status: ready
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
