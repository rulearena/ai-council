from __future__ import annotations

import os
from pathlib import Path

from ai_council.api import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]

app = create_app(
    data_dir=Path(os.environ.get("AI_COUNCIL_DATA_DIR", PROJECT_ROOT / "data")),
    model_config_path=Path(
        os.environ.get(
            "AI_COUNCIL_MODEL_CONFIG_PATH",
            PROJECT_ROOT / "config" / "models.yaml",
        )
    ),
    prompt_dir=Path(os.environ.get("AI_COUNCIL_PROMPT_DIR", PROJECT_ROOT / "prompts")),
)
