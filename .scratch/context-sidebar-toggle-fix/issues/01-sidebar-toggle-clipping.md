# 01 — Collapsed context sidebar clips the expand control

Status: accepted / done (2026-08-04).

## Diagnosis

Chrome reproduction on the local `AI 眾議院` workspace showed:

- collapsed context panel width: 52px;
- header content width: 51px;
- context tab group remains visible and measures about 55px;
- expand toggle remains 32px wide but begins at x=1905.98 in a 1920px viewport, leaving only about 14px visible.

DOM and coordinate clicks can still toggle the state, so this is a layout/hit-target defect rather than a broken `contextCollapsed` state transition.

## Required regression signal

After collapsing, assert that the context tabs are hidden and the expand toggle's bounding box is fully contained by the context panel. Then click the toggle and assert the expanded state.

## Comments

- Human Owner 於 2026-08-04 明確驗收：「驗收通過可以做收尾了」。
- Chrome smoke 通過：桌面收合後 toggle 可重新展開，重複循環穩定；375px responsive 行為保留。
- Gate B reviewed implementation identity：`12da4981df6e05088a132077cfe14af3d0d2758a`，獨立 Reviewer `PASS`；exact merge commit：`16002be9e61cd706da0d8932b40bfec8f0de3cc7`。
- Post-merge frontend unit `162/162`、production build、focused Playwright regression 通過；full E2E 未執行。
- 無 OpenSpec delta；`.scratch/context-sidebar-toggle-fix/` 依政策保留為歷史執行紀錄。
