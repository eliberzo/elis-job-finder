"""Local text persistence for sourced interview-pattern research."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from jobfinder.config import DATA_DIR


INTERVIEW_RESEARCH_PATH = DATA_DIR / "leetcode_research.json"
CODING_CURRICULUM_PATH = DATA_DIR / "coding_curriculum.json"
WHITEBOARD_QUESTION_BANK_PATH = DATA_DIR / "whiteboard_question_bank.json"
EMPTY_RESEARCH: dict[str, Any] = {
    "version": 1,
    "updated_at": "",
    "scope": "",
    "methodology": "",
    "patterns": [],
    "sources": [],
}


def load_interview_research() -> dict[str, Any]:
    if not INTERVIEW_RESEARCH_PATH.exists():
        return deepcopy(EMPTY_RESEARCH)
    try:
        value = json.loads(INTERVIEW_RESEARCH_PATH.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        return deepcopy(EMPTY_RESEARCH)
    return value if isinstance(value, dict) else deepcopy(EMPTY_RESEARCH)


def load_coding_curriculum() -> dict[str, Any]:
    """Load the progressive curriculum separately from raw interview reports."""
    if not CODING_CURRICULUM_PATH.exists():
        return {"version": 1, "updated_at": "", "principle": "", "tracks": []}
    try:
        value = json.loads(CODING_CURRICULUM_PATH.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        return {"version": 1, "updated_at": "", "principle": "", "tracks": []}
    if not isinstance(value, dict):
        return {"version": 1, "updated_at": "", "principle": "", "tracks": []}
    # The larger whiteboard bank changes much more often than the production and
    # principles tracks. Keep it independently reviewable while presenting one
    # curriculum to the application.
    if WHITEBOARD_QUESTION_BANK_PATH.exists():
        try:
            whiteboard = json.loads(WHITEBOARD_QUESTION_BANK_PATH.read_text())
        except (OSError, json.JSONDecodeError, TypeError):
            whiteboard = None
        if isinstance(whiteboard, dict) and isinstance(whiteboard.get("sections"), list):
            for track in value.get("tracks", []):
                if isinstance(track, dict) and track.get("id") == "whiteboard":
                    track["sections"] = whiteboard["sections"]
                    track["description"] = whiteboard.get("description", track.get("description", ""))
                    track["interview_shape"] = whiteboard.get("interview_shape", track.get("interview_shape", ""))
                    break
    return value
