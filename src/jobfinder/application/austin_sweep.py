"""Austin-wide discovery orchestration.

Collection remains profile-independent. Each query is persisted first; resume
scoring and compensation enrichment run once after the crawl completes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from typing import Any, Iterable

from jobfinder.application.collection import collect_linkedin
from jobfinder.application.compensation import enrich_missing_compensation
from jobfinder.application.service import rescore_all
from jobfinder.domain.locations import is_austin_proper_location
from jobfinder.infrastructure.storage import db


AUSTIN_QUERY_GROUPS = (
    "Senior Software Engineer",
    "Staff Software Engineer",
    "Senior Backend Engineer",
    "Staff Backend Engineer",
    "Senior Platform Engineer",
    "Staff Platform Engineer",
    "Senior Infrastructure Engineer",
    "Staff Infrastructure Engineer",
    "Senior Site Reliability Engineer",
    "Staff Site Reliability Engineer",
    "Senior Data Engineer",
    "Staff Data Engineer",
    "Senior Database Engineer",
    "Senior Distributed Systems Engineer",
    "Senior Cloud Engineer",
    "Staff Cloud Engineer",
    "Senior AI Engineer",
    "Staff AI Engineer",
    "Senior Machine Learning Platform Engineer",
    "Staff Machine Learning Platform Engineer",
    "Senior Python Engineer",
    "Staff Python Engineer",
    "Senior Golang Engineer",
    "Senior Java Backend Engineer",
    "Senior Kafka Engineer",
    "Senior Kubernetes Engineer",
    "Senior DevOps Engineer",
    "Senior Cloud Platform Engineer",
    "Staff Cloud Platform Engineer",
    "Senior Data Platform Engineer",
    "Staff Data Platform Engineer",
    "Senior ML Infrastructure Engineer",
    "Staff ML Infrastructure Engineer",
    "Senior AI Platform Engineer",
    "Staff AI Platform Engineer",
    "Senior API Engineer",
    "Senior Microservices Engineer",
    "Senior Observability Engineer",
    "Senior Reliability Engineer",
    "Senior Security Platform Engineer",
    "Senior Payments Software Engineer",
    "Staff Payments Software Engineer",
    "Engineering Manager Software",
    "Software Engineering Manager",
    "Software Development Manager",
    "Engineering Manager Backend",
    "Engineering Manager Platform",
    "Engineering Manager Infrastructure",
    "Engineering Manager Data",
    "Engineering Manager Machine Learning",
    "Engineering Manager Site Reliability",
    "Engineering Manager Cloud",
    "Engineering Manager AI",
    "Senior Engineering Manager",
    "Manager Software Development",
    "Manager Backend Engineering",
    "Manager Platform Engineering",
    "Manager Infrastructure Engineering",
    "Manager Data Engineering",
    "Manager Machine Learning Engineering",
    "Manager Cloud Engineering",
    "Engineering Manager",
    "Senior Software Engineering Manager",
    "Development Engineering Manager",
    "Data Engineering Manager",
    "Platform Engineering Manager",
    "Infrastructure Engineering Manager",
    "Cloud Engineering Manager",
    "AI Engineering Manager",
    "Senior Full Stack Software Engineer",
    "Staff Full Stack Software Engineer",
    "Senior Fullstack Engineer",
    "Staff Fullstack Engineer",
    "Engineering Manager Full Stack",
    "Software Engineer II",
    "Software Engineer III",
    "Software Engineer 2",
    "Software Engineer 3",
    "Backend Engineer II",
    "Backend Engineer III",
    "Full Stack Engineer II",
    "Full Stack Engineer III",
    "Technical Lead Software",
    "Lead Backend Engineer",
    "Platform Engineer II",
    "Platform Engineer III",
    "Data Engineer II",
    "Data Engineer III",
    "DevOps Engineer II",
    "DevOps Engineer III",
    "Site Reliability Engineer II",
    "Site Reliability Engineer III",
)


def austin_corpus_metrics() -> dict[str, int]:
    """Return persisted Austin-proper coverage without relying on UI filters."""
    with db() as conn:
        rows = conn.execute("SELECT company_key,location FROM jobs").fetchall()
        total = int(conn.execute("SELECT count(*) FROM jobs").fetchone()[0])
    austin_rows = [row for row in rows if is_austin_proper_location(row["location"])]
    return {
        "total_jobs": total,
        "austin_jobs": len(austin_rows),
        "austin_companies": len({str(row["company_key"]) for row in austin_rows if row["company_key"]}),
    }


def query_groups(values: Iterable[str] | None = None) -> list[str]:
    """Normalize and deduplicate query groups while preserving their order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values or AUSTIN_QUERY_GROUPS:
        cleaned = " ".join(str(value).split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def collect_austin_sweep(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rotate through relevant job families until Austin coverage reaches target."""
    options = data or {}
    target = max(1, int(options.get("target_companies", 300)))
    days = max(1, min(int(options.get("days", 30)), 30))
    limit = max(25, min(int(options.get("limit_per_query", 350)), 350))
    workers = max(1, min(int(options.get("workers", 4)), 4))
    queries = query_groups(options.get("queries"))
    max_queries = max(1, min(int(options.get("max_queries", 8)), len(queries)))
    default_offset = datetime.now(timezone.utc).hour * max_queries
    configured_offset = options.get("query_offset")
    query_offset = int(default_offset if configured_offset is None else configured_offset) % len(queries)
    queries = (queries[query_offset:] + queries[:query_offset])[:max_queries]
    before = austin_corpus_metrics()
    batches: list[dict[str, Any]] = []
    created = accepted = found = 0
    errors: list[str] = []

    for query in queries:
        if austin_corpus_metrics()["austin_companies"] >= target:
            break
        result = collect_linkedin({
            "keywords": query,
            "locations": "Austin, TX",
            "days": days,
            "limit": limit,
            "workers": workers,
            "include_remote": False,
        })
        metrics = austin_corpus_metrics()
        batch = {
            "query": query,
            "found": int(result["found"]),
            "accepted": int(result["accepted"]),
            "created": int(result["created"]),
            "austin_companies": metrics["austin_companies"],
            "errors": result["errors"],
        }
        batches.append(batch)
        print(json.dumps(batch), flush=True)
        found += batch["found"]
        accepted += batch["accepted"]
        created += batch["created"]
        errors.extend(f"{query}: {message}" for message in result["errors"])

    rescored = rescore_all()
    compensation = enrich_missing_compensation()
    after = austin_corpus_metrics()
    return {
        "target_companies": target,
        "before": before,
        "after": after,
        "companies_added": after["austin_companies"] - before["austin_companies"],
        "austin_jobs_added": after["austin_jobs"] - before["austin_jobs"],
        "jobs_added": after["total_jobs"] - before["total_jobs"],
        "found": found,
        "accepted": accepted,
        "created": created,
        "queries_run": len(batches),
        "query_offset": query_offset,
        "batches": batches,
        "errors": errors,
        "rescored": rescored,
        "compensation": compensation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Mine relevant Austin-proper Senior/Staff engineering roles.")
    parser.add_argument("--target-companies", type=int, default=300)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit-per-query", type=int, default=350)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-queries", type=int, default=8)
    parser.add_argument("--query-offset", type=int)
    args = parser.parse_args()
    print(json.dumps(collect_austin_sweep(vars(args)), indent=2))


if __name__ == "__main__":
    main()
