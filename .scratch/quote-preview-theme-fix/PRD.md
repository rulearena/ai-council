# Quote Preview Theme Fix

Status: Human Owner approved, queued behind #96/#98/#99 acceptance and closeout (2026-08-04).

## Problem

Clicking 「引用」 in the chatroom renders the composer quote preview with a light background that is harsh against the application's dark theme.

Chrome reproduction measured `.chatroom-composer-quote` at `rgb(245, 245, 245)`. `ChatroomComposer.vue` uses the undefined `--bg-muted` token with a `#f5f5f5` fallback, while the application theme defines `--color-*` tokens.

## Scope

- Replace the quote preview's light fallback with the existing dark surface, border, and text tokens.
- Preserve quote content, dismiss-quote behavior, send behavior, and responsive layout.
- Add a browser regression for the visible quote preview theme and readability.
- Do not change backend APIs, event schemas, chat execution semantics, or other meeting modes.

## Acceptance criteria

1. Clicking 「引用」 in a chatroom shows a dark quote preview consistent with the rest of the composer.
2. Quote text and the 「取消引用」 control remain readable and usable.
3. Desktop and responsive layouts do not reintroduce a light fallback or overflow.
4. Existing quote and send semantics remain unchanged.
