"""JSONL-backed career goals, intentionally separate from actionable todos."""
from __future__ import annotations

import json
from typing import Any

from jobfinder.config import GOALS_PATH


def list_goals() -> list[dict[str, Any]]:
    if not GOALS_PATH.exists():
        return []
    rows = [json.loads(line) for line in GOALS_PATH.read_text().splitlines() if line.strip()]
    return sorted(rows, key=lambda row: (int(row.get("order", 999)), str(row.get("id", ""))))
