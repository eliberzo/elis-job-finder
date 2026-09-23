"""Application-facing use cases for Eli's resume, practice, and todo workspaces."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jobfinder.application.interview_prep import interview_expectations_view, leetcode_research_view
from jobfinder.application.resume_builder import add_resume_source, generate_resume_from_sources, list_resume_sources, load_resume_builder, resume_ai_status, resume_versions, save_resume_builder
from jobfinder.application.resume_targets import selected_resume_target_context
from jobfinder.config import RESUME_DIR
from jobfinder.infrastructure.practice_builder import load_practice_builder, save_practice_builder
from jobfinder.infrastructure.local_events import load_local_events, set_event_status
from jobfinder.infrastructure.storage import profile
from jobfinder.infrastructure.todos import list_todos, toggle_todo, toggle_todo_blocker
from jobfinder.infrastructure.goals import list_goals


def resume_workspace() -> dict[str, Any]:
    return {
        "resume": load_resume_builder(), "sources": list_resume_sources(), "versions": resume_versions(),
        "ai": resume_ai_status(), "targets": selected_resume_target_context(),
    }


def upload_resume_source(payload: dict[str, Any]) -> dict[str, Any]:
    return {"source": add_resume_source(payload), "sources": list_resume_sources()}


def generate_resume_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "resume": generate_resume_from_sources(payload), "sources": list_resume_sources(),
        "versions": resume_versions(), "targets": selected_resume_target_context(), "pdf": "/resume/actual",
    }


def save_resume_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    return {"resume": save_resume_builder(payload.get("resume", payload)), "pdf": "/resume/actual"}


def practice_workspace() -> dict[str, Any]:
    practice = load_practice_builder()
    practice["tracks"]["leetcode"]["research"] = leetcode_research_view()
    practice["expectations"] = interview_expectations_view()
    return {"practice": practice}


def save_practice_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    practice = save_practice_builder(payload.get("practice", payload))
    practice["tracks"]["leetcode"]["research"] = leetcode_research_view()
    practice["expectations"] = interview_expectations_view()
    return {"practice": practice}


def local_events_workspace() -> dict[str, Any]:
    return {"events": load_local_events()}


def update_local_event_status(event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return set_event_status(event_id, str(payload.get("status", "")))


def todo_workspace() -> dict[str, Any]:
    return {"todos": list_todos()}


def goals_workspace() -> dict[str, Any]:
    return {"goals": list_goals()}


def toggle_todo_item(todo_id: str) -> dict[str, Any]:
    return toggle_todo(todo_id)


def toggle_todo_item_blocker(todo_id: str) -> dict[str, Any]:
    return toggle_todo_blocker(todo_id)


def original_resume_path() -> Path | None:
    """Resolve the configured private resume while preventing path traversal."""
    resume_name = str(profile().get("resume_file", "")).rsplit("/", 1)[-1]
    resume_path = (RESUME_DIR / resume_name).resolve()
    if not resume_name or resume_path.parent != RESUME_DIR.resolve() or not resume_path.exists():
        return None
    return resume_path
