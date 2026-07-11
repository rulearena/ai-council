from __future__ import annotations

from pathlib import Path

import pytest

from ai_council.prompting.parser import OutputParseError, RoleOutputParser
from ai_council.prompting.renderer import PromptRenderer


@pytest.mark.parametrize(
    ("template_name", "role"),
    [
        ("blue_propose", "Blue"),
        ("red", "Red"),
        ("blue_revise", "Blue"),
        ("judge", "Judge"),
    ],
)
def test_role_prompts_require_responses_to_follow_the_topic_language(
    template_name: str,
    role: str,
) -> None:
    prompt_dir = Path(__file__).parents[2] / "prompts"

    rendered = PromptRenderer(prompt_dir).render(
        template_name=template_name,
        role=role,
        topic="如何自動化開發？",
        prior_transcript="尚未發言",
        required_json_schema='{"summary":"string"}',
    )

    assert "Respond in the same language as the meeting topic." in rendered
    assert "All JSON string values must use that language." in rendered


def test_prompt_renderer_loads_template_and_injects_context(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "blue_propose.md").write_text(
        "Role={{ role }}\nTopic={{ topic }}\nTranscript={{ prior_transcript }}\nSchema={{ required_json_schema }}",
        encoding="utf-8",
    )

    rendered = PromptRenderer(prompt_dir).render(
        template_name="blue_propose",
        role="Blue",
        topic="是否先做後端？",
        prior_transcript="Red 尚未發言",
        required_json_schema='{"summary":"string"}',
    )

    assert rendered == (
        'Role=Blue\nTopic=是否先做後端？\nTranscript=Red 尚未發言\nSchema={"summary":"string"}'
    )


def test_role_output_parser_parses_json_code_fence() -> None:
    raw_output = """
模型回覆如下：

```json
{
  "summary": "結論",
  "arguments": [{"title": "理由", "detail": "細節"}],
  "risks": [],
  "recommendation": "採用"
}
```
"""

    parsed = RoleOutputParser().parse(raw_output)

    assert parsed.summary == "結論"
    assert parsed.arguments[0].title == "理由"
    assert parsed.arguments[0].detail == "細節"
    assert parsed.risks == []
    assert parsed.recommendation == "採用"


def test_role_output_parser_extracts_first_json_object_from_surrounding_text() -> None:
    raw_output = 'prefix {"summary":"A","arguments":[],"risks":[],"recommendation":"B"} suffix'

    parsed = RoleOutputParser().parse(raw_output)

    assert parsed.summary == "A"
    assert parsed.recommendation == "B"


@pytest.mark.parametrize(
    "raw_output",
    [
        "not json",
        '{"summary":"missing required fields"}',
        '{"summary":"A","arguments":"bad","risks":[],"recommendation":"B"}',
    ],
)
def test_role_output_parser_raises_structured_error_for_invalid_output(
    raw_output: str,
) -> None:
    with pytest.raises(OutputParseError) as error:
        RoleOutputParser().parse(raw_output)

    assert error.value.raw_output == raw_output
