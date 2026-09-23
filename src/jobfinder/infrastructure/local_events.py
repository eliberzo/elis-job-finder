"""Locally persisted, source-linked professional events."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from typing import Any

from jobfinder.config import LOCAL_EVENTS_PATH, PROFILE_PATH


STATUSES = ("new", "interested", "going", "passed")
DEFAULT_LOCAL_EVENTS = {
    "version": 1,
    "city": "Austin, TX",
    "updated_at": "2026-08-26",
    "events": [
        {"id":"h3-atx-2026-09","title":"H³ ATX — Hardware Happy Hour","category":"networking","starts_at":"2026-09-03T17:00:00-05:00","ends_at":"2026-09-03T19:00:00-05:00","venue":"The Pub – Triangle","address":"815 W 47th St, Austin, TX 78751","organizer":"H³ ATX","description":"Monthly networking for hardware, deep-tech, robotics, IoT, renewables, and computing-device builders.","url":"https://www.eventbrite.com/e/h3-atx-hardware-happy-hour-september-2026-tickets-1998113481210","source":"Eventbrite","cost":"Check listing","status":"new"},
        {"id":"hackerx-austin-2026-09","title":"HackerX Austin Tech Job Fair","category":"recruiting","starts_at":"2026-09-03T18:00:00-05:00","ends_at":"","venue":"Austin — venue on registration","address":"Austin, TX","organizer":"HackerX","description":"Invite-based rapid-interview recruiting event for software engineers and local technology employers.","url":"https://hackerx.org/tech-job-fairs/united-states/texas/austin/","source":"HackerX","cost":"Free for approved candidates","status":"new"},
        {"id":"dc512-2026-09","title":"DC512 September Meetup","category":"learn","starts_at":"2026-09-07T19:00:00-05:00","ends_at":"2026-09-07T22:00:00-05:00","venue":"Celis Brewery Beer Garden","address":"10001 Metric Blvd, Austin, TX","organizer":"DC512","description":"Austin security meetup with short community firetalks, CVE walkthroughs, and informal networking.","url":"https://www.meetup.com/defcon512/","source":"Meetup","cost":"Check listing","status":"new"},
        {"id":"jobfairx-austin-2026-09","title":"Austin Technology Virtual Job Fair","category":"recruiting","starts_at":"2026-09-11T11:00:00-05:00","ends_at":"2026-09-11T15:00:00-05:00","venue":"Online — Austin employers","address":"Virtual","organizer":"JobFairX","description":"Technology-focused virtual job fair with employer matching and scheduled video interviews.","url":"https://jobfairx.com/job-fairs/texas/austin/next-technology","source":"JobFairX","cost":"Free for job seekers","status":"new"},
        {"id":"hacktx-2026","title":"HackTX 2026","category":"hackathon","starts_at":"2026-10-24T09:00:00-05:00","ends_at":"2026-10-25T17:00:00-05:00","venue":"The University of Texas at Austin","address":"Austin, TX","organizer":"Freetail Hackers","description":"A 24-hour Austin hackathon for technologists to build projects, meet sponsors, and work alongside the local developer community.","url":"https://hacktx.com/","source":"HackTX","cost":"Apply by September 11","status":"new"}
    ],
    "source_links": [
        {"label":"Meetup — Austin tech","url":"https://www.meetup.com/find/?keywords=technology&location=us--tx--Austin&source=EVENTS"},
        {"label":"Eventbrite — Austin tech","url":"https://www.eventbrite.com/d/tx--austin/tech-events/"},
        {"label":"Austin Startup Meetup","url":"https://www.austinstartupmeetup.com/"},
        {"label":"Built In Austin events","url":"https://www.builtinaustin.com/events"}
    ]
}


def _clean(value: Any, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _candidate_profile() -> dict[str, Any]:
    try:
        value = json.loads(PROFILE_PATH.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _personalize_event(item: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Add an explainable attendance recommendation from resume evidence."""
    resume = " ".join([str(candidate.get("resume_text", "")), *map(str, candidate.get("skills", []))]).lower()
    event_text = " ".join(str(item.get(key, "")) for key in ("title", "category", "organizer", "description")).lower()
    signals = [
        ("distributed systems", ("distributed", "infrastructure", "platform")),
        ("Kafka and event-driven systems", ("kafka", "streaming", "messaging", "event-driven")),
        ("Python", ("python",)),
        ("cloud engineering", ("cloud", "gcp", "aws", "azure")),
        ("observability and reliability", ("observability", "reliability", "sre", "monitoring")),
        ("technical leadership", ("leadership", "architecture", "senior engineer", "engineering leader")),
        ("backend engineering", ("backend", "software engineer", "developer")),
    ]
    matches = [label for label, terms in signals if any(term in resume and term in event_text for term in terms)]
    category = item.get("category")
    score = {"recruiting": 68, "learn": 38, "networking": 32, "hackathon": 30}.get(category, 25)
    score += min(24, len(matches) * 8)
    if category == "recruiting" and any(term in event_text for term in ("software engineer", "technology", "tech job")):
        score += 12
    if "virtual" in event_text or "online" in event_text:
        score += 5
    score = min(100, score)
    if score >= 75:
        tier, label = "recommended", "You should attend"
    elif score >= 50:
        tier, label = "consider", "Consider if convenient"
    else:
        tier, label = "low", "Low priority for you"

    if category == "recruiting" and matches:
        reason = f"Go meet recruiters: your senior-level {', '.join(matches[:2])} experience should stand out, and you can learn what local teams need."
    elif category == "recruiting":
        reason = "Go meet recruiters: your senior engineering background should stand out, and the conversations can reveal what Austin employers need."
    elif matches:
        reason = f"Direct overlap with your {', '.join(matches[:2])} experience."
    elif category == "hackathon":
        reason = "Potential networking value, but it is less targeted to your senior backend search."
    else:
        reason = "Little direct overlap with your backend, platform, and distributed-systems background."
    item.update({"fit_score": score, "recommendation": tier, "recommendation_label": label, "fit_reason": reason, "skill_matches": matches})
    return item


def load_local_events(candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    if not LOCAL_EVENTS_PATH.exists():
        save_local_events(DEFAULT_LOCAL_EVENTS)
    try:
        source = json.loads(LOCAL_EVENTS_PATH.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        source = deepcopy(DEFAULT_LOCAL_EVENTS)
    result = deepcopy(DEFAULT_LOCAL_EVENTS)
    result["city"] = _clean(source.get("city"), 100) or result["city"]
    result["updated_at"] = _clean(source.get("updated_at"), 30) or result["updated_at"]
    if isinstance(source.get("events"), list):
        result["events"] = []
        for index, raw in enumerate(source["events"][:200]):
            if not isinstance(raw, dict) or not _clean(raw.get("title"), 200):
                continue
            item = {key: _clean(raw.get(key), 2000) for key in ("id","title","category","starts_at","ends_at","venue","address","organizer","description","url","source","cost","status")}
            item["id"] = item["id"] or f"event-{index + 1}"
            item["category"] = item["category"] if item["category"] in ("learn","hackathon","recruiting","networking") else "networking"
            item["status"] = item["status"] if item["status"] in STATUSES else "new"
            result["events"].append(_personalize_event(item, candidate or _candidate_profile()))
    result["events"].sort(key=lambda item: item["starts_at"])
    result["today"] = date.today().isoformat()
    return result


def save_local_events(payload: Any) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else DEFAULT_LOCAL_EVENTS
    LOCAL_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_EVENTS_PATH.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n")
    return load_local_events() if source is not DEFAULT_LOCAL_EVENTS else deepcopy(DEFAULT_LOCAL_EVENTS)


def set_event_status(event_id: str, status: str) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError("Unknown event status")
    data = load_local_events()
    event = next((item for item in data["events"] if item["id"] == event_id), None)
    if not event:
        raise LookupError("Event not found")
    event["status"] = status
    data.pop("today", None)
    LOCAL_EVENTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {"event": event, "events": load_local_events()}
