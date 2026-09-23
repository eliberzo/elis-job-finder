"""Persisted interview-practice questions, answers, and per-track todos."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from jobfinder.config import PRACTICE_BUILDER_PATH


TRACK_ORDER = ("hr", "behavioral", "system_design", "leetcode")
CODING_SKILL_STATUSES = ("not_started", "learning", "practicing", "ready")

DEFAULT_PRACTICE_BUILDER = {
    "version": 1,
    "tracks": {
        "hr": {
            "title": "HR pitch builder",
            "description": "Build a concise recruiter pitch around level, strengths, location, and compensation expectations.",
            "todo": {"text": "Research recruiter-screen questions from Selected to apply roles, rank them by frequency, and add them here.", "done": False},
            "items": [
                {"id": "hr-1", "question": "Tell me about yourself.", "answer": "I’m a senior backend engineer focused on distributed systems, reliable cloud platforms, and high-throughput services. I’m targeting Senior-to-Staff individual-contributor roles where I can combine hands-on delivery with technical leadership."},
                {"id": "hr-2", "question": "What are you looking for next?", "answer": "A backend or platform role with meaningful system-design ownership, strong engineering peers, and either an Austin-area presence or a genuinely remote working model."},
            ],
        },
        "behavioral": {
            "title": "Behavioral builder",
            "description": "Turn career examples into short, evidence-based stories using situation, action, and measurable result.",
            "todo": {"text": "Mine behavioral themes from Selected to apply job descriptions, rank recurring competencies, and create targeted prompts.", "done": False},
            "items": [
                {"id": "behavioral-1", "question": "Tell me about a difficult production incident you led through.", "answer": "Draft a STAR story: context and customer impact, your diagnosis, how you coordinated the response, the technical fix, and the measurable reliability improvement."},
                {"id": "behavioral-2", "question": "Tell me about a time you influenced without authority.", "answer": "Draft a specific example showing the disagreement, the data or prototype you used, how you aligned stakeholders, and what changed afterward."},
            ],
        },
        "system_design": {
            "title": "System design builder",
            "description": "Practice explaining requirements, tradeoffs, architecture, scale, reliability, and operational ownership.",
            "todo": {"text": "Extract system-design topics from high-ranked Selected to apply roles and prioritize them by company and role frequency.", "done": False},
            "items": [
                {"id": "system-design-1", "question": "Design a reliable, high-throughput event ingestion platform.", "answer": "Cover requirements and scale first, then partitioning, Kafka or equivalent queues, idempotency, storage, backpressure, observability, replay, failure recovery, and cost tradeoffs."},
                {"id": "system-design-2", "question": "Design a multi-tenant job collection and ranking pipeline.", "answer": "Discuss source adapters, rate limiting, durable ingestion, deduplication, enrichment, scoring isolation, reprocessing, freshness, auditability, and tenant-level data boundaries."},
            ],
        },
        "leetcode": {
            "title": "Coding skill builder",
            "description": "Build interview-ready coding skills across practical implementation, algorithms, testing, concurrency, and systems-oriented exercises.",
            "todo": {"text": "Research coding questions associated with Selected to apply companies, rank them by recurrence and relevance, and add them here.", "done": False},
            "pattern_progress": {},
            "exercise_progress": {},
            "items": [
                {"id": "leetcode-1", "question": "Return the top K most frequent values from a stream.", "answer": "Start with a frequency map, then compare heap and bucket approaches. State O(n log k) time and O(n) space for the heap solution, plus empty-input and tie behavior."},
                {"id": "leetcode-2", "question": "Implement an LRU cache.", "answer": "Use a hash map plus doubly linked list for O(1) get and put. Explain eviction, updates to existing keys, capacity-one behavior, and pointer invariants."},
            ],
        },
    },
}


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def normalize_practice_builder(payload: Any) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    source_tracks = source.get("tracks", {}) if isinstance(source.get("tracks", {}), dict) else {}
    result = deepcopy(DEFAULT_PRACTICE_BUILDER)
    for key in TRACK_ORDER:
        incoming = source_tracks.get(key, {}) if isinstance(source_tracks.get(key, {}), dict) else {}
        track = result["tracks"][key]
        track["title"] = _clean(incoming.get("title", track["title"]), 100) or track["title"]
        track["description"] = _clean(incoming.get("description", track["description"]), 500) or track["description"]
        todo = incoming.get("todo", {}) if isinstance(incoming.get("todo", {}), dict) else {}
        track["todo"] = {
            "text": _clean(todo.get("text", track["todo"]["text"]), 800) or track["todo"]["text"],
            "done": bool(todo.get("done", False)),
        }
        if key == "leetcode":
            progress = incoming.get("pattern_progress", {}) if isinstance(incoming.get("pattern_progress", {}), dict) else {}
            normalized_progress: dict[str, dict[str, str]] = {}
            for pattern_id, raw in list(progress.items())[:100]:
                cleaned_id = _clean(pattern_id, 100)
                value = raw if isinstance(raw, dict) else {"status": raw}
                status = _clean(value.get("status"), 30)
                if cleaned_id and status in CODING_SKILL_STATUSES:
                    normalized_progress[cleaned_id] = {
                        "status": status,
                        "updated_at": _clean(value.get("updated_at"), 50),
                    }
            track["pattern_progress"] = normalized_progress
            exercise_progress = incoming.get("exercise_progress", {}) if isinstance(incoming.get("exercise_progress", {}), dict) else {}
            normalized_exercise_progress: dict[str, dict[str, Any]] = {}
            for exercise_id, raw in list(exercise_progress.items())[:300]:
                cleaned_id = _clean(exercise_id, 120)
                value = raw if isinstance(raw, dict) else {"completed": raw}
                if cleaned_id:
                    normalized_exercise_progress[cleaned_id] = {
                        "completed": bool(value.get("completed", False)),
                        "completed_at": _clean(value.get("completed_at"), 50),
                    }
            track["exercise_progress"] = normalized_exercise_progress
        items = incoming.get("items")
        if isinstance(items, list):
            normalized = []
            for index, item in enumerate(items[:50]):
                if not isinstance(item, dict):
                    continue
                question = _clean(item.get("question"), 1000)
                answer = _clean(item.get("answer"), 12000)
                if not question and not answer:
                    continue
                normalized.append({
                    "id": _clean(item.get("id"), 100) or f"{key}-{index + 1}",
                    "question": question,
                    "answer": answer,
                })
            track["items"] = normalized
    return result


def load_practice_builder() -> dict[str, Any]:
    if not PRACTICE_BUILDER_PATH.exists():
        save_practice_builder(DEFAULT_PRACTICE_BUILDER)
    try:
        return normalize_practice_builder(json.loads(PRACTICE_BUILDER_PATH.read_text()))
    except (OSError, json.JSONDecodeError, TypeError):
        return deepcopy(DEFAULT_PRACTICE_BUILDER)


def save_practice_builder(payload: Any) -> dict[str, Any]:
    data = normalize_practice_builder(payload)
    PRACTICE_BUILDER_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRACTICE_BUILDER_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return data
