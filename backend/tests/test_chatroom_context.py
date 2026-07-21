from __future__ import annotations

import os

import pytest

from ai_council.meetings.chatroom_context import ChatroomContextBuilder, estimate_tokens
from ai_council.meetings.transcript import TranscriptProjector


def _make_event(
    event_id: str,
    content: str,
    *,
    meeting_id: str = "meeting-1",
    step_id: str = "human-message",
    role: str = "Human",
    status: str = "completed",
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "meeting_id": meeting_id,
        "step_id": step_id,
        "role": role,
        "attempt": 1,
        "status": status,
        "content": content,
    }


class TestEstimateTokens:
    def test_ascii_chars_counted_at_one_per_four(self) -> None:
        assert estimate_tokens("abcd") == 1

    def test_ascii_eight_chars_two_tokens(self) -> None:
        assert estimate_tokens("abcdefgh") == 2

    def test_cjk_chars_counted_at_one_per_two(self) -> None:
        assert estimate_tokens("你好") == 1

    def test_cjk_four_chars_two_tokens(self) -> None:
        assert estimate_tokens("你好世界") == 2

    def test_mixed_ascii_and_cjk(self) -> None:
        text = "ab你好cd"  # 4 ascii = 1 token, 2 cjk = 1 token → 2
        assert estimate_tokens(text) == 2

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0


class TestContextIncludesCurrentAndQuoted:
    def test_context_always_includes_quoted_event_in_history(self, tmp_path):
        projector = TranscriptProjector()
        builder = ChatroomContextBuilder(
            transcript_projector=projector, token_budget=500
        )
        events = [
            _make_event("e1", "Old message from the past"),
            _make_event("e2", "Another old message"),
            _make_event("eq", "The quoted message content"),
        ]

        result = builder.build(
            events=events,
            goal="Test goal",
            quoted_event_id="eq",
        )

        assert "Old message from the past" in result
        assert "Another old message" in result
        assert "The quoted message content" in result

    def test_quoted_event_always_present_even_when_outside_budget(self):
        projector = TranscriptProjector()
        builder = ChatroomContextBuilder(
            transcript_projector=projector, token_budget=5
        )
        # Budget is tiny (5 tokens). Events are long enough to exceed budget.
        events = [
            _make_event("e1", "A" * 100),
            _make_event("e2", "B" * 100),
            _make_event("eq", "Quoted important content"),
        ]

        result = builder.build(
            events=events,
            goal="Goal",
            quoted_event_id="eq",
        )

        assert "Quoted important content" in result

    def test_quoted_event_append_label_when_budget_dropped(self):
        projector = TranscriptProjector()
        builder = ChatroomContextBuilder(
            transcript_projector=projector, token_budget=5
        )
        events = [
            _make_event("e1", "A" * 100),
            _make_event("e2", "B" * 100),
            _make_event("eq", "Important quoted text"),
        ]

        result = builder.build(
            events=events,
            goal="Goal",
            quoted_event_id="eq",
        )

        assert "引用訊息（Human）：Important quoted text" in result


class TestContextRespectsTokenBudget:
    def test_budget_limited_events(self):
        projector = TranscriptProjector()
        # Each event "content" is 8 chars = 2 tokens via estimate_tokens,
        # but projector renders full markdown with headings etc.
        # Use a budget that allows ~10 events but not 50.
        builder = ChatroomContextBuilder(
            transcript_projector=projector, token_budget=200
        )
        events = [_make_event(f"e{i}", f"Message number {i}") for i in range(50)]

        result = builder.build(events=events, goal="Test")

        # Most recent events should be included
        assert "Message number 49" in result
        assert "Message number 48" in result
        # Oldest events should be dropped
        assert "Message number 0" not in result
        assert "Message number 1" not in result

    def test_budget_none_uses_env_default(self, monkeypatch):
        monkeypatch.setenv("AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET", "100")
        projector = TranscriptProjector()
        builder = ChatroomContextBuilder(transcript_projector=projector)
        assert builder.token_budget == 100


class TestContextDeterministic:
    def test_same_inputs_same_output(self):
        projector = TranscriptProjector()
        builder = ChatroomContextBuilder(
            transcript_projector=projector, token_budget=500
        )
        events = [
            _make_event("e1", "First message"),
            _make_event("e2", "Second message"),
            _make_event("e3", "Third message"),
        ]

        result1 = builder.build(events=events, goal="Deterministic test")
        result2 = builder.build(events=events, goal="Deterministic test")

        assert result1 == result2

    def test_deterministic_with_quoted_event(self):
        projector = TranscriptProjector()
        builder = ChatroomContextBuilder(
            transcript_projector=projector, token_budget=500
        )
        events = [
            _make_event("e1", "First message"),
            _make_event("e2", "Second message"),
        ]

        result1 = builder.build(
            events=events, goal="Test", quoted_event_id="e1"
        )
        result2 = builder.build(
            events=events, goal="Test", quoted_event_id="e1"
        )

        assert result1 == result2


class TestContextNoCrossMeetingLeak:
    def test_other_meeting_events_excluded(self):
        projector = TranscriptProjector()
        builder = ChatroomContextBuilder(
            transcript_projector=projector, token_budget=5000
        )
        events = [
            _make_event("e1", "This meeting message"),
            _make_event(
                "e2",
                "Other meeting message",
                meeting_id="other-meeting",
            ),
            _make_event("e3", "Back to this meeting"),
        ]

        result = builder.build(events=events, goal="Test")

        assert "This meeting message" in result
        assert "Back to this meeting" in result
        assert "Other meeting message" not in result
