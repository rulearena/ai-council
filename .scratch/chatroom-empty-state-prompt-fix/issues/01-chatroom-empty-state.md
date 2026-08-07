# 01 — Chatroom empty state uses deliberation wording

Status: implemented / awaiting Human Owner acceptance (2026-08-07)

## Scope

Make the empty feed copy mode-aware. Chatroom should explain that the user can type directly and mention `@角色` or `@all` to invite AI; other modes retain their existing copy.

## Acceptance

- Chatroom initial empty feed renders `還沒有訊息；可直接輸入文字，想請 AI 回應時請 @角色 或 @all。`.
- The chatroom copy has no fixed-deliberation CTA.
- Non-chatroom and selected-role empty states are unchanged.

## Implementation boundary

Only `ConversationWorkspace` presentation and its browser regression coverage are in scope. No backend, API, event schema, meeting data, or chat execution changes.
