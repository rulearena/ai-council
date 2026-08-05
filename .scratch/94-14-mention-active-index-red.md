# #94⑭ red evidence

- Base: `702d60f8862ef1781472f13964970f1f9477dd31`
- Test: `frontend/tests/e2e/chatroom.spec.ts` — `13.10a mention active descendant stays valid when participants shrink`
- Command: `npx playwright test tests/e2e/chatroom.spec.ts -g 'participants shrink' --project=chromium`
- Result: failed at the public DOM contract assertion
- Failure: after the participant list shrank to two options, `aria-activedescendant` remained `mention-menu-v-0-option-4`; the current option elements did not contain that id (`Expected: true`, `Received: false`).
- Reproduction seam: real composer input → hover the fifth mention option → reopen the same meeting through the history UI with a reduced participants response.

This is a product assertion failure, not a tautological test: it compares the textarea's public ARIA reference with the currently rendered option DOM.
