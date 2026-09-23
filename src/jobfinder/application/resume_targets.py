"""Build a focused resume-target cohort from companies selected to apply to."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from typing import Any, Iterable, Mapping

from jobfinder.domain.company import company_identity, title_identity
from jobfinder.domain.matching import detect_skills
from jobfinder.domain.relevance import posting_is_relevant
from jobfinder.infrastructure.storage import db


TARGET_SCORE_FLOOR = 7.0
TARGET_ROLE_LIMIT = 36
TARGET_ROLES_PER_COMPANY = 2
SPECIALIZED_TITLE_EXCLUSIONS = (
    "machine learning engineer", "ml engineer", "ml infra", "deep learning", "research", "scientist",
    "computer vision", "perception", "simulation", "embedded", "firmware",
    "kernel", "security", "frontend", "front-end", "mobile", "ios", "android",
    "engineering manager", "manager, software", "manager software",
)


def _as_job(row: Mapping[str, Any]) -> dict[str, Any]:
    return dict(row)


def _eligible_target(job: Mapping[str, Any]) -> bool:
    candidate = _as_job(job)
    title = str(candidate.get("title", "")).casefold()
    if float(candidate.get("actual_score") or 0) < TARGET_SCORE_FLOOR:
        return False
    if any(term in title for term in SPECIALIZED_TITLE_EXCLUSIONS):
        return False
    return posting_is_relevant(candidate)


def focus_selected_resume_targets(
    rows: Iterable[Mapping[str, Any]],
    limit: int = TARGET_ROLE_LIMIT,
    per_company: int = TARGET_ROLES_PER_COMPANY,
) -> list[dict[str, Any]]:
    """Keep the best distinct, relevant IC roles without letting one company dominate."""
    ordered = sorted(
        (_as_job(row) for row in rows if _eligible_target(row)),
        key=lambda job: (
            -float(job.get("actual_score") or 0),
            int(job.get("age_days")) if job.get("age_days") is not None else 9999,
            str(job.get("company", "")).casefold(),
            str(job.get("title", "")).casefold(),
        ),
    )
    result: list[dict[str, Any]] = []
    company_counts: defaultdict[str, int] = defaultdict(int)
    seen: set[tuple[str, str]] = set()
    for job in ordered:
        company = company_identity(job.get("company", ""))
        identity = (company, title_identity(job.get("title", "")))
        if not company or identity in seen or company_counts[company] >= per_company:
            continue
        seen.add(identity)
        company_counts[company] += 1
        job["detected_skills"] = detect_skills(str(job.get("description", "")))
        result.append(job)
        if len(result) >= limit:
            break
    return result


def selected_resume_targets(limit: int = TARGET_ROLE_LIMIT) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """SELECT id,company,company_key,title,location,url,description,date_posted,age_days,
                      actual_score,detected_skills,salary_max,market_compensation,status
               FROM jobs
               WHERE actual_saved=1 AND status NOT IN ('APPLIED','SKIPPED')
               ORDER BY actual_score DESC, COALESCE(age_days,9999), id DESC"""
        ).fetchall()
    return focus_selected_resume_targets(rows, limit=limit)


def _skills(job: Mapping[str, Any]) -> list[str]:
    value = job.get("detected_skills") or []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    return [str(skill) for skill in value if str(skill).strip()]


def selected_resume_target_context(targets: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    roles = list(targets) if targets is not None else selected_resume_targets()
    demand: Counter[str] = Counter()
    for role in roles:
        demand.update(_skills(role))
    companies = sorted({str(role.get("company", "")).strip() for role in roles if str(role.get("company", "")).strip()})
    return {
        "basis": "selected_companies",
        "role_count": len(roles),
        "company_count": len(companies),
        "companies": companies,
        "top_skills": [{"skill": skill, "jobs": count} for skill, count in demand.most_common(12)],
        "role_examples": [
            {
                "company": str(role.get("company", "")),
                "title": str(role.get("title", "")),
                "location": str(role.get("location", "")),
                "score": float(role.get("actual_score") or 0),
            }
            for role in roles[:8]
        ],
    }
