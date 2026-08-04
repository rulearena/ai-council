# 01 — Chatroom quote preview uses a light background

Status: approved / queued behind #96/#98/#99 acceptance and closeout (2026-08-04).

## Diagnosis

On the `創業` chatroom, clicking the 「引用」 button for a saved response produced a visible `.chatroom-composer-quote` preview with computed background `rgb(245, 245, 245)`. The source rule uses `var(--bg-muted, #f5f5f5)`, but `--bg-muted` is not part of the application's `--color-*` theme token set.

## Required regression signal

After selecting a quote, assert through the user-visible composer seam that the quote preview is present, uses the dark theme surface, and keeps its text and dismiss control readable at desktop and responsive widths. Preserve the existing quote/send interaction contract.
