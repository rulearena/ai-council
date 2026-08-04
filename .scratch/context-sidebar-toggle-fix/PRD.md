# Context Sidebar Toggle Fix

Status: Human Owner approved, scoped implementation in progress (2026-08-04).

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

