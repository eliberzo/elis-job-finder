"""Persistent, company-specific voice interview practice."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jobfinder.config import INTERVIEW_AUDIO_DIR, INTERVIEW_SESSIONS_PATH, OPENAI_MODEL

RESPONSES_URL = "https://api.openai.com/v1/responses"
TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"

GOOGLE_HR_QUESTIONS = [
    "Tell me about yourself and the thread connecting your recent work.",
    "Why Google, and why this role at this point in your career?",
    "What are you looking for in your next team and scope?",
    "Describe the largest technical initiative you personally owned end to end.",
    "Tell me about a time you influenced a difficult decision without formal authority.",
    "What is an important failure or mistake, and what changed because of it?",
    "How do you raise the effectiveness of engineers around you while remaining hands-on?",
    "What questions do you have for the recruiter or hiring team?",
]

INTERVIEW_PLANS = {
    "google-hr": {
        "id": "google-hr", "company": "Google", "round": "HR / recruiter screen",
        "role": "Senior / Staff Software Engineer", "questions": GOOGLE_HR_QUESTIONS,
        "description": "A concise recruiter conversation focused on motivation, scope, leadership, and communication.",
    }
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict[str, Any]]:
    if not INTERVIEW_SESSIONS_PATH.exists():
        return []
    try:
        value = json.loads(INTERVIEW_SESSIONS_PATH.read_text())
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(sessions: list[dict[str, Any]]) -> None:
    INTERVIEW_SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    INTERVIEW_SESSIONS_PATH.write_text(json.dumps(sessions, ensure_ascii=False, indent=2) + "\n")


def _public(session: dict[str, Any]) -> dict[str, Any]:
    result = dict(session)
    for answer in result.get("answers", []):
        answer.pop("audio_path", None)
    return result


def interview_workspace() -> dict[str, Any]:
    sessions = [_public(item) for item in reversed(_load())]
    return {
        "configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "plans": list(INTERVIEW_PLANS.values()), "sessions": sessions,
    }


def start_interview(payload: dict[str, Any]) -> dict[str, Any]:
    plan_id = str(payload.get("plan_id", "google-hr"))
    plan = INTERVIEW_PLANS.get(plan_id)
    if not plan:
        raise LookupError("Interview plan not found")
    session = {
        "id": uuid.uuid4().hex, "plan_id": plan_id, "company": plan["company"],
        "role": plan["role"], "round": plan["round"], "status": "active",
        "started_at": _now(), "completed_at": "", "question_index": 0,
        "current_question": plan["questions"][0], "current_kind": "primary",
        "followups_for_question": 0, "answers": [], "evaluation": None,
    }
    sessions = _load(); sessions.append(session); _save(sessions)
    return {"session": _public(session)}


def _api_key() -> str:
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value:
        raise RuntimeError("Voice interview AI is not configured. Set OPENAI_API_KEY before starting the app.")
    return value


def _multipart_audio(audio: bytes, filename: str, mime_type: str) -> tuple[bytes, str]:
    boundary = "----InterviewBoundary" + uuid.uuid4().hex
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\ngpt-transcribe\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {mime_type}\r\n\r\n".encode(),
        audio, f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), boundary


def _transcribe(audio: bytes, filename: str, mime_type: str) -> str:
    body, boundary = _multipart_audio(audio, filename, mime_type)
    request = urllib.request.Request(TRANSCRIPTIONS_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {_api_key()}", "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"OpenAI transcription failed ({exc.code}): {detail}") from exc
    return str(result.get("text", "")).strip()


def _response_text(request_body: dict[str, Any]) -> str:
    request = urllib.request.Request(RESPONSES_URL, data=json.dumps(request_body).encode(), method="POST", headers={
        "Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"OpenAI interview request failed ({exc.code}): {detail}") from exc
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return str(content.get("text", ""))
    raise RuntimeError("OpenAI returned no interview response")


def _followup(question: str, transcript: str) -> str:
    prompt = (
        "You are conducting a Google Senior/Staff software-engineering recruiter screen. "
        "Ask exactly one concise follow-up that probes missing specificity, personal ownership, measurable impact, or motivation. "
        "Do not coach, score, praise, criticize, or repeat the original question. Return only the question.\n\n"
        f"ORIGINAL QUESTION: {question}\nCANDIDATE ANSWER: {transcript}"
    )
    return _response_text({"model": OPENAI_MODEL, "store": False, "input": prompt}).strip()[:1000]


def submit_answer(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    sessions = _load()
    session = next((item for item in sessions if item.get("id") == session_id), None)
    if not session or session.get("status") != "active":
        raise LookupError("Active interview session not found")
    raw = str(payload.get("audio_base64", ""))
    if not raw:
        raise ValueError("No recorded answer was provided")
    audio = base64.b64decode(raw, validate=True)
    if len(audio) > 25 * 1024 * 1024:
        raise ValueError("Recorded answer is too large")
    mime_type = str(payload.get("mime_type", "audio/webm"))[:100]
    extension = ".mp4" if "mp4" in mime_type else ".webm"
    answer_id = uuid.uuid4().hex
    directory = INTERVIEW_AUDIO_DIR / session_id
    directory.mkdir(parents=True, exist_ok=True)
    audio_path = directory / f"{answer_id}{extension}"
    audio_path.write_bytes(audio)
    transcript = _transcribe(audio, audio_path.name, mime_type)
    if not transcript:
        raise ValueError("No speech could be transcribed from the recording")
    answer = {
        "id": answer_id, "question": session["current_question"], "kind": session["current_kind"],
        "transcript": transcript, "duration_seconds": round(float(payload.get("duration_seconds", 0)), 1),
        "recorded_at": _now(), "audio_url": f"/api/voice-interviews/{session_id}/audio/{answer_id}",
        "audio_path": str(audio_path),
    }
    session["answers"].append(answer)
    plan = INTERVIEW_PLANS[session["plan_id"]]
    if session["current_kind"] == "primary" and session["followups_for_question"] < 1:
        session["current_question"] = _followup(answer["question"], transcript)
        session["current_kind"] = "followup"
        session["followups_for_question"] = 1
    else:
        session["question_index"] += 1
        session["followups_for_question"] = 0
        if session["question_index"] >= len(plan["questions"]):
            session["current_question"] = ""
        else:
            session["current_question"] = plan["questions"][session["question_index"]]
        session["current_kind"] = "primary"
    _save(sessions)
    return {"session": _public(session), "answer": _public({"answers": [answer]})["answers"][0]}


EVALUATION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "overall_score": {"type": "integer", "minimum": 1, "maximum": 10},
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
        "competencies": {"type": "object", "additionalProperties": False, "properties": {
            key: {"type": "integer", "minimum": 1, "maximum": 10}
            for key in ("clarity", "specificity", "ownership", "impact", "leadership", "company_alignment")
        }, "required": ["clarity", "specificity", "ownership", "impact", "leadership", "company_alignment"]},
        "answer_feedback": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {"question": {"type": "string"}, "feedback": {"type": "string"}, "better_outline": {"type": "string"}},
            "required": ["question", "feedback", "better_outline"]}},
    },
    "required": ["overall_score", "summary", "strengths", "improvements", "competencies", "answer_feedback"],
}


def finish_interview(session_id: str) -> dict[str, Any]:
    sessions = _load(); session = next((item for item in sessions if item.get("id") == session_id), None)
    if not session:
        raise LookupError("Interview session not found")
    if not session.get("answers"):
        raise ValueError("Record at least one answer before finishing")
    evidence = [{"question": item["question"], "answer": item["transcript"], "duration_seconds": item["duration_seconds"]} for item in session["answers"]]
    prompt = (
        "Evaluate this Google Senior/Staff recruiter-screen practice transcript. Be candid, specific, and evidence-based. "
        "Score demonstrated communication only; do not infer accomplishments the candidate did not state. Identify progress-ready coaching and provide a concise better outline for every answer.\n\n"
        + json.dumps(evidence, ensure_ascii=False)
    )
    text = _response_text({"model": OPENAI_MODEL, "store": False, "input": prompt,
        "text": {"format": {"type": "json_schema", "name": "interview_evaluation", "strict": True, "schema": EVALUATION_SCHEMA}}})
    session["evaluation"] = json.loads(text)
    session["status"] = "completed"; session["completed_at"] = _now(); _save(sessions)
    return {"session": _public(session)}


def interview_audio(session_id: str, answer_id: str) -> tuple[bytes, str]:
    session = next((item for item in _load() if item.get("id") == session_id), None)
    answer = next((item for item in (session or {}).get("answers", []) if item.get("id") == answer_id), None)
    if not answer:
        raise LookupError("Interview recording not found")
    path = Path(answer["audio_path"])
    return path.read_bytes(), "audio/mp4" if path.suffix == ".mp4" else "audio/webm"
