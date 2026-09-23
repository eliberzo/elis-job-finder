"""Read-only summary of recurring skills in recent job postings."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

from jobfinder.config import DB_PATH
from jobfinder.domain.company import company_identity, title_identity
from jobfinder.domain.locations import is_austin_proper_location
from jobfinder.domain.matching import detect_skills
from jobfinder.domain.relevance import posting_is_relevant
from jobfinder.infrastructure.storage import OFFICIAL_JOB_SOURCES


def _posting_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def analyze_jobs(
    rows: Iterable[Mapping[str, Any]], *, today: date, days: int = 30,
    scope: str = "austin", include_linkedin: bool = False,
    top_skills: int = 10, limit: int = 10,
) -> dict[str, Any]:
    """Count skills once per unique relevant role, then rank role overlap."""
    cutoff = today - timedelta(days=days)
    roles: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        job = dict(row)
        posted = _posting_date(job.get("date_posted"))
        source = str(job.get("source") or "").casefold()
        if posted is None or not cutoff <= posted <= today:
            continue
        if scope == "austin" and not is_austin_proper_location(job.get("location")):
            continue
        if source not in OFFICIAL_JOB_SOURCES and not (include_linkedin and source == "linkedin"):
            continue
        if not job.get("url") or not posting_is_relevant(job):
            continue
        key = (company_identity(job.get("company")), title_identity(job.get("title")))
        if not all(key):
            continue
        job["skills"] = detect_skills(str(job.get("description") or ""))
        job["posted"] = posted
        previous = roles.get(key)
        if previous is None or (
            source in OFFICIAL_JOB_SOURCES,
            posted,
        ) > (
            str(previous.get("source") or "").casefold() in OFFICIAL_JOB_SOURCES,
            previous["posted"],
        ):
            roles[key] = job

    counts = Counter(skill for job in roles.values() for skill in set(job["skills"]))
    common = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:top_skills]
    ranked = []
    for job in roles.values():
        overlap = [skill for skill, _ in common if skill in job["skills"]]
        ranked.append({
            "company": job["company"], "title": job["title"],
            "location": job["location"], "date_posted": job["posted"].isoformat(),
            "source": job["source"], "url": job["url"],
            "common_skill_count": len(overlap), "common_skills": overlap,
        })
    ranked.sort(key=lambda job: (
        -job["common_skill_count"], -date.fromisoformat(job["date_posted"]).toordinal(),
        str(job["company"]).casefold(), str(job["title"]).casefold(),
    ))
    return {
        "scope": scope, "days": days, "through": today.isoformat(),
        "sources": "official and LinkedIn" if include_linkedin else "official only",
        "unique_jobs": len(roles),
        "unique_companies": len({key[0] for key in roles}),
        "common_skills": [
            {"skill": skill, "jobs": count, "percent": round(100 * count / len(roles), 1)}
            for skill, count in common
        ],
        "jobs_with_common_skills": ranked[:limit],
    }


def report_from_db(path: Path = DB_PATH, **options: Any) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"No local job database at {path}; collect or import jobs first.")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT company,title,location,url,source,description,date_posted FROM jobs"
        ).fetchall()
    return analyze_jobs(rows, today=date.today(), **options)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize common skills in recent, relevant jobs without modifying data.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Local SQLite database (default: data/jobs.db)")
    parser.add_argument("--days", type=int, default=30, help="Maximum posting age (default: 30)")
    parser.add_argument("--scope", choices=("austin", "all"), default="austin")
    parser.add_argument("--include-linkedin", action="store_true", help="Add LinkedIn only after reviewing official roles")
    parser.add_argument("--top-skills", type=int, default=10)
    parser.add_argument("--limit", type=int, default=10, help="Maximum job examples")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()
    if args.days < 1 or args.top_skills < 1 or args.limit < 1:
        parser.error("--days, --top-skills, and --limit must be positive")
    try:
        result = report_from_db(
            args.db, days=args.days, scope=args.scope,
            include_linkedin=args.include_linkedin,
            top_skills=args.top_skills, limit=args.limit,
        )
    except FileNotFoundError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(f"{result['unique_jobs']} unique relevant {args.scope} jobs at {result['unique_companies']} companies "
          f"(posted in the last {args.days} days; {result['sources']}).")
    if not result["unique_jobs"]:
        print("No qualifying jobs. Collect fresh postings or widen --days/--scope.")
        return
    print("\nMost common skills (number and share of jobs):")
    for item in result["common_skills"]:
        print(f"  {item['skill']}: {item['jobs']} ({item['percent']}%)")
    print("\nJobs mentioning the most common skills (overlap, not resume-fit rank):")
    for job in result["jobs_with_common_skills"]:
        print(f"  {job['common_skill_count']} | {job['company']} — {job['title']} "
              f"[{job['date_posted']}; {job['source']}]"
              f"\n      Common skills: {', '.join(job['common_skills']) or 'none'}"
              f"\n      {job['url']}")
    print("\nPosting dates and URLs are not proof that a role is still open; confirm on the employer page.")


if __name__ == "__main__":
    main()
