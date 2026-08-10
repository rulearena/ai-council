from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Protocol

from ai_council.prompting.parser import (
    CourtroomIssueDraftParser,
    CourtroomCivilFinalParser,
    CourtroomCriminalFinalParser,
    CourtroomRulingParser,
    ChatMessageParser,
    OutputParseError,
    RoleOutputParser,
    StructuredVerdictParser,
)

DEFAULT_OUTPUT_SCHEMA_ID = "role-output/v1"
CHAT_MESSAGE_V1_ID = "chat-message/v1"
STRUCTURED_VERDICT_V1_ID = "structured-verdict/v1"
COURTROOM_ISSUE_DRAFT_V1_ID = "courtroom-issue-draft/v1"
COURTROOM_RULING_V1_ID = "courtroom-ruling/v1"
COURTROOM_CIVIL_FINAL_V1_ID = "courtroom-civil-final/v1"
COURTROOM_CRIMINAL_FINAL_V1_ID = "courtroom-criminal-final/v1"
ROLE_OUTPUT_V1_SCHEMA = (
    '{"summary":"string","arguments":[{"title":"string","detail":"string"}],'
    '"risks":[{"title":"string","detail":"string"}],"recommendation":"string"}'
)
CHAT_MESSAGE_V1_SCHEMA = '{"message":"string","attachment_refs":[{"source_ref":"<exact selected source_ref>","label":"<exact selected label>","segment_refs":["<exact allowed segment_ref>"]}]}'
STRUCTURED_VERDICT_V1_SCHEMA = (
    '{"summary":"string","decision":"approve | approve-with-conditions | reject | '
    'insufficient-evidence","findings":[{"title":"string","detail":"string",'
    '"evidence_refs":["[證物一]"]}],"risks":[{"title":"string","detail":"string",'
    '"evidence_refs":["[證物一]"]}],"recommendation":"string","conditions":["string"],'
    '"unresolved_questions":["string"]}'
)
COURTROOM_ISSUE_DRAFT_V1_SCHEMA = '{"issues":[{"title":"string"}]}'
COURTROOM_RULING_V1_SCHEMA = (
    '{"outcome":"proponent-wins | respondent-wins | partially-upheld | '
    'insufficient-evidence","reasoning":"string","evidence_refs":["[證物一]"],'
    '"unresolved_questions":["string"]}'
)
COURTROOM_CIVIL_FINAL_V1_SCHEMA = (
    '{"summary":"string","claims":[{"claim":"string","outcome":"upheld | '
    'partially-upheld | rejected | insufficient-evidence","reasoning":"string",'
    '"evidence_refs":["[證物一]"],"relief":{"obligation":"string",'
    '"monetary_amount":"string | null","calculation_basis":"string | null"}}],'
    '"unresolved_questions":["string"]}'
)
COURTROOM_CRIMINAL_FINAL_V1_SCHEMA = (
    '{"summary":"string","charges":[{"charge":"string","decision":"guilty | '
    'not-guilty | insufficient-evidence","reasoning":"string","evidence_refs":'
    '["[證物一]"]}],"sentencing_factors":["string"],"unresolved_questions":["string"]}'
)


class OutputParser(Protocol):
    def parse(self, raw_output: str) -> object:
        ...


@dataclass(frozen=True)
class OutputSchemaCodec:
    id: str
    schema: str
    parser: OutputParser

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.schema.encode("utf-8")).hexdigest()

    def parse(self, raw_output: object) -> dict[str, Any]:
        if not isinstance(raw_output, str):
            raise OutputParseError(
                "Model output must be a string",
                raw_output=raw_output,
            )
        try:
            parsed = self.parser.parse(raw_output)
        except OutputParseError:
            raise
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise OutputParseError(str(error), raw_output=raw_output) from error
        if isinstance(parsed, dict):
            return parsed
        if is_dataclass(parsed) and not isinstance(parsed, type):
            return asdict(parsed)
        raise TypeError("Output schema parsers must return a dict or dataclass instance")


class OutputSchemaRegistry:
    def __init__(self, codecs: list[OutputSchemaCodec]) -> None:
        self._by_id = {codec.id: codec for codec in codecs}
        if len(self._by_id) != len(codecs):
            raise ValueError("Duplicate output schema ID")

    def get(self, schema_id: str) -> OutputSchemaCodec:
        try:
            return self._by_id[schema_id]
        except KeyError as error:
            raise KeyError(f"Unknown output schema: {schema_id}") from error

    def contains(self, schema_id: str) -> bool:
        return schema_id in self._by_id


DEFAULT_OUTPUT_SCHEMA_REGISTRY = OutputSchemaRegistry(
    [
        OutputSchemaCodec(
            id=CHAT_MESSAGE_V1_ID,
            schema=CHAT_MESSAGE_V1_SCHEMA,
            parser=ChatMessageParser(),
        ),
        OutputSchemaCodec(
            id=DEFAULT_OUTPUT_SCHEMA_ID,
            schema=ROLE_OUTPUT_V1_SCHEMA,
            parser=RoleOutputParser(),
        ),
        OutputSchemaCodec(
            id=STRUCTURED_VERDICT_V1_ID,
            schema=STRUCTURED_VERDICT_V1_SCHEMA,
            parser=StructuredVerdictParser(),
        ),
        OutputSchemaCodec(
            id=COURTROOM_ISSUE_DRAFT_V1_ID,
            schema=COURTROOM_ISSUE_DRAFT_V1_SCHEMA,
            parser=CourtroomIssueDraftParser(),
        ),
        OutputSchemaCodec(
            id=COURTROOM_RULING_V1_ID,
            schema=COURTROOM_RULING_V1_SCHEMA,
            parser=CourtroomRulingParser(),
        ),
        OutputSchemaCodec(
            id=COURTROOM_CIVIL_FINAL_V1_ID,
            schema=COURTROOM_CIVIL_FINAL_V1_SCHEMA,
            parser=CourtroomCivilFinalParser(),
        ),
        OutputSchemaCodec(
            id=COURTROOM_CRIMINAL_FINAL_V1_ID,
            schema=COURTROOM_CRIMINAL_FINAL_V1_SCHEMA,
            parser=CourtroomCriminalFinalParser(),
        ),
    ]
)
