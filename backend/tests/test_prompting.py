from __future__ import annotations

from pathlib import Path

import pytest

from ai_council.prompting.parser import OutputParseError, RoleOutputParser
from ai_council.prompting.renderer import PromptRenderer
from ai_council.prompting.schemas import DEFAULT_OUTPUT_SCHEMA_REGISTRY


ROLE_OUTPUT_V1_LITERAL = (
    '{"summary":"string","arguments":[{"title":"string","detail":"string"}],'
    '"risks":[{"title":"string","detail":"string"}],"recommendation":"string"}'
)
ROLE_OUTPUT_V1_HASH = "15a45919652be5c70d3fd1690a10d37f876f19a14b2a76cc0f21765def281377"

STRUCTURED_VERDICT_LITERAL = (
    '{"summary":"string","decision":"approve | approve-with-conditions | reject | '
    'insufficient-evidence","findings":[{"title":"string","detail":"string",'
    '"evidence_refs":["[證物一]"]}],"risks":[{"title":"string","detail":"string",'
    '"evidence_refs":["[證物一]"]}],"recommendation":"string","conditions":["string"],'
    '"unresolved_questions":["string"]}'
)


def test_structured_verdict_v1_registry_accepts_a_known_verdict_literal() -> None:
    codec = DEFAULT_OUTPUT_SCHEMA_REGISTRY.get("structured-verdict/v1")

    assert codec.schema == STRUCTURED_VERDICT_LITERAL
    assert codec.parse(
        '{"summary":"核准上線","decision":"approve-with-conditions",'
        '"findings":[{"title":"測試完整","detail":"驗收紀錄完整。",'
        '"evidence_refs":["[證物一]"]}],'
        '"risks":[{"title":"回滾風險","detail":"需先演練。",'
        '"evidence_refs":["[證物二]"]}],'
        '"recommendation":"完成演練後上線。","conditions":["完成回滾演練"],'
        '"unresolved_questions":["尖峰容量是否足夠？"]}'
    ) == {
        "summary": "核准上線",
        "decision": "approve-with-conditions",
        "findings": [
            {
                "title": "測試完整",
                "detail": "驗收紀錄完整。",
                "evidence_refs": ["[證物一]"],
            }
        ],
        "risks": [
            {
                "title": "回滾風險",
                "detail": "需先演練。",
                "evidence_refs": ["[證物二]"],
            }
        ],
        "recommendation": "完成演練後上線。",
        "conditions": ["完成回滾演練"],
        "unresolved_questions": ["尖峰容量是否足夠？"],
    }


@pytest.mark.parametrize(
    "raw_output",
    [
        '[]',
        '{"summary":"S","decision":"unknown","findings":[],"risks":[],'
        '"recommendation":"R","conditions":[],"unresolved_questions":[]}',
        '{"summary":"S","decision":"reject","findings":"bad","risks":[],'
        '"recommendation":"R","conditions":[],"unresolved_questions":[]}',
        '{"summary":"S","decision":"reject","findings":[{"title":"F",'
        '"detail":"D","evidence_refs":["證物一"]}],"risks":[],'
        '"recommendation":"R","conditions":[],"unresolved_questions":[]}',
        '{"summary":"S","decision":"reject","findings":[],"risks":[],'
        '"recommendation":"R","conditions":[1],"unresolved_questions":[]}',
    ],
)
def test_structured_verdict_v1_registry_rejects_invalid_payloads_as_parse_errors(
    raw_output: str,
) -> None:
    codec = DEFAULT_OUTPUT_SCHEMA_REGISTRY.get("structured-verdict/v1")

    with pytest.raises(OutputParseError) as error:
        codec.parse(raw_output)

    assert error.value.raw_output == raw_output


def test_role_output_v1_registry_preserves_literal_hash_and_parser_contract() -> None:
    codec = DEFAULT_OUTPUT_SCHEMA_REGISTRY.get("role-output/v1")

    assert codec.schema == ROLE_OUTPUT_V1_LITERAL
    assert codec.hash == ROLE_OUTPUT_V1_HASH
    assert codec.parse(
        '{"summary":"A","arguments":[{"title":"T","detail":"D"}],'
        '"risks":[],"recommendation":"B"}'
    ) == {
        "summary": "A",
        "arguments": [{"title": "T", "detail": "D"}],
        "risks": [],
        "recommendation": "B",
    }


@pytest.mark.parametrize(
    ("template_name", "role"),
    [
        ("blue_propose", "Blue"),
        ("red_critique", "Red"),
        ("blue_revise", "Blue"),
        ("judge_decide", "Judge"),
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


def test_renderer_injects_mode_inputs(tmp_path: Path) -> None:
    (tmp_path / "debate_statement_pro.md").write_text(
        "{{ topic }} | {{ position_a }} vs {{ position_b }}", encoding="utf-8"
    )
    renderer = PromptRenderer(tmp_path)

    rendered = renderer.render(
        template_name="debate_statement_pro",
        role="Pro",
        topic="T",
        prior_transcript="",
        required_json_schema="{}",
        inputs={"position_a": "先做後端", "position_b": "先做前端"},
    )

    assert rendered == "T | 先做後端 vs 先做前端"


def test_renderer_builtin_values_win_over_inputs(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text("{{ topic }}", encoding="utf-8")
    renderer = PromptRenderer(tmp_path)

    rendered = renderer.render(
        template_name="t",
        role="Pro",
        topic="real",
        prior_transcript="",
        required_json_schema="{}",
        inputs={"topic": "hijacked"},
    )

    assert rendered == "real"


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
