from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def test_pytest_temp_contract(tmp_path: Path) -> None:
    print(
        "PYTEST_WORKSPACE_PROBE="
        + json.dumps(
            {
                "tmp_path": str(tmp_path),
                "tmpdir": os.environ.get("TMPDIR"),
                "tempfile": tempfile.gettempdir(),
            },
            sort_keys=True,
        )
    )
