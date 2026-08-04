# 01 — Collapsed context sidebar clips the expand control

## Diagnosis

Chrome reproduction on the local `AI 眾議院` workspace showed:

- collapsed context panel width: 52px;
- header content width: 51px;
- context tab group remains visible and measures about 55px;
- expand toggle remains 32px wide but begins at x=1905.98 in a 1920px viewport, leaving only about 14px visible.

DOM and coordinate clicks can still toggle the state, so this is a layout/hit-target defect rather than a broken `contextCollapsed` state transition.

## Required regression signal

After collapsing, assert that the context tabs are hidden and the expand toggle's bounding box is fully contained by the context panel. Then click the toggle and assert the expanded state.

