# Context Sidebar Toggle Fix

Status: accepted / done (2026-08-04).

## Problem

On the desktop conversation workspace, collapsing the right meeting-context panel leaves the three context tabs inside the 52px collapsed header. The tab group and the 32px toggle compete for the narrow track, so the toggle is positioned at the viewport edge and is only partially visible. The state transition itself works when invoked through the DOM, but the user-facing control is clipped and unreliable.

## Scope

- Hide the context tabs while the panel is collapsed.
- Keep the expand toggle fully visible, centered, and clickable inside the collapsed track.
- Preserve the existing expanded/collapsed state semantics and mobile overlay behavior.
- Add a browser regression assertion for collapse → expand and control geometry at desktop and responsive widths.
- Do not change backend APIs, event schemas, meeting execution, or courtroom actions.

## Acceptance criteria

1. A desktop user can collapse the context panel and then expand it again using the visible toggle.
2. In the collapsed state, the context tabs are not rendered as competing visible controls.
3. The toggle's bounding box stays fully inside the context panel/viewport and retains at least its 32px hit target.
4. Repeated collapse/expand cycles remain stable.
5. Existing mobile context behavior and the rest of the workspace remain unchanged.

## Comments

- Human Owner 於 2026-08-04 明確驗收：「驗收通過可以做收尾了」。
- Acceptance 結果：Chrome smoke 確認桌面版收合後可由完整可見的 toggle 重新展開，重複收合／展開穩定；375px responsive context 行為保留。
- Gate B reviewed implementation identity：`12da4981df6e05088a132077cfe14af3d0d2758a`，獨立 Reviewer `PASS`；exact merge commit：`16002be9e61cd706da0d8932b40bfec8f0de3cc7`。
- Post-merge verification：frontend unit `162/162`、production build、focused Playwright regression 通過；full E2E 本次未執行。
- 本次無 OpenSpec delta；依 issue-tracker 規則，`.scratch/context-sidebar-toggle-fix/` 保留為歷史執行紀錄。
