from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from ai_council.prompting.parser import RoleOutputParser

DEFAULT_OUTPUT_SCHEMA_ID = "role-output/v1"
ROLE_OUTPUT_V1_SCHEMA = (
    '{"summary":"string","arguments":[{"title":"string","detail":"string"}],'
    '"risks":[{"title":"string","detail":"string"}],"recommendation":"string"}'
)


class OutputParser(Protocol):
    def parse(self, raw_output: str) -> Any:
        ...


@dataclass(frozen=True)
class OutputSchemaCodec:
    id: str
    schema: str
    parser: OutputParser

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.schema.encode("utf-8")).hexdigest()

    def parse(self, raw_output: str) -> dict[str, Any]:
        parsed = self.parser.parse(raw_output)
        return asdict(parsed)


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
            id=DEFAULT_OUTPUT_SCHEMA_ID,
            schema=ROLE_OUTPUT_V1_SCHEMA,
            parser=RoleOutputParser(),
        )
    ]
)
