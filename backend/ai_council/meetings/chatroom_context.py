from __future__ import annotations

import os
from typing import Any

from ai_council.meetings.attachments import (
    ATTACHMENT_EVENT_KIND,
    ATTACHMENT_REMOVED_KIND,
)
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


def estimate_prompt_tokens(messages: list[dict[str, str]]) -> int:
    """Count the canonical message payload with the same deterministic metric."""
    return sum(estimate_tokens(str(message.get("content", ""))) for message in messages)


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
            e
            for e in events
            if e.get("meeting_id") == meeting_id
            and e.get("step_id") not in {ATTACHMENT_EVENT_KIND, ATTACHMENT_REMOVED_KIND}
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

    def build_request_context(
        self,
        events: list[dict[str, Any]],
        *,
        goal: str,
        instruction: str,
        quoted_event_id: str | None = None,
        reserved_tokens: int = 0,
    ) -> str:
        """Build the user/context block from one request-wide budget.

        The current instruction and quote are required blocks.  Only older
        transcript events are evicted, and the returned text is the exact
        context later used by every fanout member and retry.
        """
        meeting_id = events[0].get("meeting_id") if events else None
        filtered = [
            event for event in events
            if event.get("meeting_id") == meeting_id
            and event.get("step_id") not in {ATTACHMENT_EVENT_KIND, ATTACHMENT_REMOVED_KIND}
        ]
        quoted_event = next(
            (event for event in filtered if event.get("event_id") == quoted_event_id),
            None,
        ) if quoted_event_id else None
        quote_text = ""
        if quoted_event is not None:
            quote_text = f"引用訊息（{quoted_event.get('role', 'Human')}）：{quoted_event.get('content', '')}"
        # `reserved_tokens` is calculated from the same rendered system,
        # developer, and empty-user layers that the runner sends.  The quote
        # is the only required user block not present in that reservation.
        transcript_budget = max(0, self.token_budget - reserved_tokens - estimate_tokens(quote_text))
        selected: list[dict[str, Any]] = []
        used_tokens = 0
        for event in reversed(filtered):
            contribution = self.transcript_projector.project([event], title=goal)
            cost = estimate_tokens(contribution)
            if used_tokens + cost <= transcript_budget:
                selected.append(event)
                used_tokens += cost
        selected.reverse()
        transcript = self.transcript_projector.project(selected, title=goal) if selected else ""
        context = transcript
        if quote_text and quote_text not in context:
            context += ("\n" if context else "") + quote_text
        return context
