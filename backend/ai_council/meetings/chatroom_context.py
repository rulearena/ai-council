from __future__ import annotations

import os
from typing import Any

from ai_council.meetings.transcript import TranscriptProjector


def estimate_tokens(text: str) -> int:
    cjk_count = 0
    other_count = 0
    for ch in text:
        if ord(ch) >= 0x2E80:
            cjk_count += 1
        else:
            other_count += 1
    return cjk_count // 2 + other_count // 4


class ChatroomContextBuilder:
    def __init__(
        self,
        transcript_projector: TranscriptProjector,
        token_budget: int | None = None,
    ) -> None:
        self.transcript_projector = transcript_projector
        if token_budget is not None:
            self.token_budget = token_budget
        else:
            self.token_budget = int(
                os.environ.get("AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET", "4096")
            )

    def build(
        self,
        events: list[dict[str, Any]],
        goal: str,
        quoted_event_id: str | None = None,
    ) -> str:
        meeting_id = events[0].get("meeting_id") if events else None
        filtered = [
            e for e in events if e.get("meeting_id") == meeting_id
        ]

        quoted_event = None
        if quoted_event_id:
            quoted_event = next(
                (e for e in filtered if e.get("event_id") == quoted_event_id),
                None,
            )

        selected: list[dict[str, Any]] = []
        used_tokens = 0
        for event in reversed(filtered):
            contribution = self.transcript_projector.project(
                [event], title=goal
            )
            cost = estimate_tokens(contribution)
            if used_tokens + cost <= self.token_budget:
                selected.append(event)
                used_tokens += cost

        selected.reverse()

        parts: list[str] = []
        if selected:
            parts.append(
                self.transcript_projector.project(selected, title=goal)
            )

        if quoted_event and quoted_event.get("event_id") not in {
            e.get("event_id") for e in selected
        }:
            role = str(quoted_event.get("role", "Human"))
            content = str(quoted_event.get("content", ""))
            parts.append(f"引用訊息（{role}）：{content}")

        return "\n".join(parts)
