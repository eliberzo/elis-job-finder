"""Read-only application views consumed by the HTTP presentation layer."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Mapping

from jobfinder.application.service import company_market_signals
from jobfinder.application.resume_builder import load_resume_builder, resume_version, resume_versions
from jobfinder.application.resume_targets import selected_resume_target_context, selected_resume_targets
from jobfinder.config import AUSTIN_PROPER_COMPANY_TARGET, CORPUS_JOB_TARGET
from jobfinder.domain.locations import austin_commute_place, is_austin_commutable_location, is_austin_proper_location, is_explicitly_non_us_location
from jobfinder.domain.matching import company_identity, detect_skills
from jobfinder.domain.resume_review import review_resume
from jobfinder.infrastructure.levels import salary_benchmark_map
from jobfinder.infrastructure.storage import actual_company_keys, db, is_strategic_company, job_json, practice_company_keys, profile


def filter_jobs_by_location_scope(jobs: list[dict[str, Any]], scope: str) -> list[dict[str, Any]]:
    if scope == "us":
        return [job for job in jobs if not is_explicitly_non_us_location(job.get("location"))]
    if scope == "foreign":
        return [job for job in jobs if is_explicitly_non_us_location(job.get("location"))]
    return jobs


def _builder_resume_text(resume: Mapping[str, Any]) -> str:
    return " ".join(
        [
            " ".join(str(value) for value in resume.get("contact", {}).values()),
            str(resume.get("summary", "")),
            " ".join(str(value) for value in resume.get("skills", {}).values()),
        ]
        + [" ".join(str(value) for value in item.get("bullets", [])) for item in resume.get("experience", [])]
    )


def resume_analysis_view(version_id: str = "current") -> dict[str, Any]:
    p = profile()
    if version_id == "current":
        current = load_resume_builder()
        resume_text = _builder_resume_text(current)
        resume_name = "Current builder resume"
    elif version_id == "v0":
        resume_text = str(p.get("resume_text", ""))
        resume_name = str(p.get("resume_file", "")).rsplit("/", 1)[-1]
    elif version := resume_version(version_id):
        resume_text = _builder_resume_text(version)
        resume_name = version.get("label", version_id)
    else:
        current = load_resume_builder()
        version_id = "current"
        resume_text = _builder_resume_text(current)
        resume_name = "Current builder resume"
    resume_skills = set(detect_skills(resume_text))
    demand: Counter[str] = Counter()
    rows = selected_resume_targets()
    for row in rows:
        skills = row.get("detected_skills") or []
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except (TypeError, json.JSONDecodeError):
                skills = []
        demand.update(str(skill) for skill in skills)
    demanded = [{"skill": skill, "jobs": count, "on_resume": skill in resume_skills} for skill, count in demand.most_common(18)]
    dated_rows = [row for row in rows if row.get("age_days") is not None]
    target_context = selected_resume_target_context(rows)
    return {
        "name": p.get("name") or "Eli",
        "location": p.get("current_location") or "Austin, TX",
        "target_scope": "selected_companies",
        "target_context": target_context,
        "resume_filename": resume_name,
        "selected_version": version_id,
        "versions": [{"id": "current", "label": "Current builder resume", "updated_at": ""}] + resume_versions(),
        "resume_skills": sorted(resume_skills),
        "strengths": [item for item in demanded if item["on_resume"]][:8],
        "gaps": [item for item in demanded if not item["on_resume"]][:8],
        "demanded": demanded,
        "review": review_resume(resume_text, rows, demand),
        "stats": {
            "jobs_analyzed": len(rows),
            "strong_matches": sum(float(row.get("actual_score") or 0) >= 8 for row in rows),
            "fresh_jobs": sum(int(row["age_days"]) <= 7 for row in dated_rows),
            "selected_companies": target_context["company_count"],
            "selected_roles": target_context["role_count"],
        },
    }


def jobs_view(params: Mapping[str, str]) -> dict[str, Any]:
    clauses: list[str] = []
    sql_params: list[Any] = []
    status, search = params.get("status", ""), params.get("q", "")
    location_scope = params.get("location", "us")
    saved_only = params.get("saved", "") == "1"
    practice_only = params.get("practice", "") == "1"
    selected_only = saved_only or practice_only
    if not selected_only:
        clauses.append("lower(title) NOT LIKE '%principal%' AND lower(title) NOT LIKE '%distinguished%' AND lower(title) NOT LIKE '%fellow%'")
    if status == "active":
        clauses.append("closed_at IS NULL")
        if not saved_only:
            clauses.append("status NOT IN ('APPLIED','SKIPPED','PROTECTED') AND company_key NOT IN (SELECT company_key FROM jobs WHERE status='APPLIED')")
            # Keep a user's selected rows accessible, but don't present dated,
            # expired discoveries as current opportunities in the active queue.
            clauses.append("(actual_saved=1 OR practice_saved=1 OR date_posted IS NULL OR trim(date_posted)='' OR date(date_posted) >= date('now','-30 days'))")
    elif status:
        clauses.append("status=?")
        sql_params.append(status)
    if not selected_only:
        clauses.append("company_key NOT IN (SELECT company_key FROM jobs WHERE practice_saved=1)")
        clauses.append("COALESCE(salary_max,market_compensation,suggested_salary,0) >= 200000")
    if search:
        clauses.append("(company LIKE ? OR title LIKE ? OR location LIKE ? OR detected_skills LIKE ? OR matches LIKE ?)")
        sql_params.extend([f"%{search}%"] * 5)
    if location_scope == "austin":
        clauses.append("(lower(trim(location)) IN ('austin, tx','austin, texas') OR lower(trim(location)) LIKE 'austin, tx (%' OR lower(trim(location)) LIKE 'austin, texas (%')")
    elif location_scope == "remote":
        clauses.append("work_arrangement='remote'")
    elif location_scope == "austin_remote":
        clauses.append("(work_arrangement='remote' OR lower(trim(location)) IN ('austin, tx','austin, texas') OR lower(trim(location)) LIKE 'austin, tx (%' OR lower(trim(location)) LIKE 'austin, texas (%')")
    elif location_scope == "elsewhere":
        clauses.append("work_arrangement!='remote' AND lower(trim(location)) NOT IN ('austin, tx','austin, texas') AND lower(trim(location)) NOT LIKE 'austin, tx (%' AND lower(trim(location)) NOT LIKE 'austin, texas (%'")
    orders = {
        "recent": "id DESC", "newest": "COALESCE(age_days,9999) ASC,actual_score DESC",
        "fit": "fit_score DESC,actual_score DESC",
        "comp": "COALESCE(salary_max,market_compensation,suggested_salary,0) DESC,actual_score DESC",
        "actual": "actual_score DESC,fit_score DESC,COALESCE(salary_max,market_compensation,suggested_salary,0) DESC",
        "score": "burn_cost ASC,practice_value DESC,fit_score DESC",
    }
    sort_key = params.get("sort", "score")
    order = orders["actual"] if saved_only and sort_key == "score" else orders.get(sort_key, orders["score"])
    sql = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY " + order
    with db() as conn:
        jobs = [job_json(row) for row in conn.execute(sql, sql_params)]
        applied = conn.execute("SELECT count(DISTINCT lower(company)) FROM jobs WHERE status='APPLIED'").fetchone()[0]
        corpus_total = int(conn.execute("SELECT count(*) FROM jobs").fetchone()[0])
        corpus_companies = int(conn.execute("SELECT count(DISTINCT company_key) FROM jobs").fetchone()[0])
        linkedin_jobs = int(conn.execute("SELECT count(*) FROM jobs WHERE source='linkedin'").fetchone()[0])
        # Everything not collected from LinkedIn is a direct employer/ATS
        # record, including browser-verified portals whose source label may be
        # introduced before a dedicated background adapter exists.
        direct_source_jobs = int(conn.execute(
            "SELECT count(*) FROM jobs WHERE source!='linkedin'"
        ).fetchone()[0])
        location_rows = list(conn.execute("SELECT company_key,location FROM jobs"))
        austin_companies = len({
            str(row[0]) for row in location_rows
            if is_austin_commutable_location(row[1])
        })
        austin_proper_companies = len({
            str(row[0]) for row in location_rows
            if is_austin_proper_location(row[1])
        })
    jobs = filter_jobs_by_location_scope(jobs, location_scope)
    saved_keys, practice_keys = actual_company_keys(), practice_company_keys()
    if saved_only:
        jobs = [job for job in jobs if job["company_key"] in saved_keys]
    if practice_only:
        jobs = [job for job in jobs if job["company_key"] in practice_keys]
    signals, benchmarks = company_market_signals(), salary_benchmark_map()
    for job in jobs:
        signal = signals.get(str(job.get("company", "")).casefold(), {})
        job["austin_job_count"] = int(signal.get("austin_jobs", 0))
        job["remote_job_count"] = int(signal.get("remote_jobs", 0))
        job["strategic_auto"] = is_strategic_company(str(job.get("company", "")))
        job["austin_presence"] = job["austin_job_count"] > 0
        commute = austin_commute_place(job.get("location"))
        job["austin_commute_place"] = commute.get("label") if commute else ""
        job["austin_commute_minutes"] = commute.get("minutes") if commute else ""
        job["remote_presence"] = job["remote_job_count"] > 0
        job["burn_eligible"] = bool(not job["austin_presence"] and not job["remote_presence"] and not job["strategic_auto"] and not job.get("actual_saved"))
        job["levels_benchmark"] = benchmarks.get(company_identity(job.get("company", "")))
    p = profile()
    return {
        "jobs": jobs, "applied": applied, "target": p["target_applications"],
        "actual_count": len(saved_keys), "practice_count": len(practice_keys),
        "corpus_total": corpus_total, "corpus_companies": corpus_companies,
        "austin_company_count": austin_companies,
        "corpus_progress": {
            "job_target": CORPUS_JOB_TARGET,
            "jobs_remaining": max(0, CORPUS_JOB_TARGET - corpus_total),
            "austin_proper_company_count": austin_proper_companies,
            "austin_proper_company_target": AUSTIN_PROPER_COMPANY_TARGET,
            "austin_companies_remaining": max(0, AUSTIN_PROPER_COMPANY_TARGET - austin_proper_companies),
            "linkedin_jobs": linkedin_jobs,
            "direct_source_jobs": direct_source_jobs,
        },
    }
