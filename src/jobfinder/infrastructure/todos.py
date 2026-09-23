"""Small JSONL-backed task list for job-search setup and workflow work."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from jobfinder.config import TODO_PATH


def list_todos() -> list[dict[str, Any]]:
    if not TODO_PATH.exists(): return []
    rows = []
    for line in TODO_PATH.read_text().splitlines():
        if line.strip(): rows.append(json.loads(line))
    return sorted(rows, key=lambda row: (int(row.get("order", 999)), str(row.get("id", ""))))


def save_todos(rows: list[dict[str, Any]]) -> None:
    TODO_PATH.parent.mkdir(parents=True, exist_ok=True)
    TODO_PATH.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def toggle_todo(todo_id: str) -> dict[str, Any]:
    rows = list_todos()
    for row in rows:
        if row.get("id") == todo_id:
            if row.get("status") == "done":
                row["status"] = "todo"
                row.pop("completed_at", None)
            else:
                row["status"] = "done"
                row["completed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            save_todos(rows)
            return row
    raise ValueError("Todo item not found")


def toggle_todo_blocker(todo_id: str) -> dict[str, Any]:
    rows = list_todos()
    for row in rows:
        if row.get("id") == todo_id:
            if row.get("status") == "done":
                raise ValueError("Completed items must be reopened before changing blocker status")
            row["status"] = "todo" if row.get("status") == "blocked" else "blocked"
            save_todos(rows)
            return row
    raise ValueError("Todo item not found")
