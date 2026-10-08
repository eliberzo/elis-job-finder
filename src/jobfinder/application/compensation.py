"""Backfill sourced market compensation for strong jobs missing posted pay."""
from __future__ import annotations

import re
from typing import Any

from jobfinder.domain.locations import is_explicitly_non_us_location
from jobfinder.infrastructure.levels import salary_benchmark_map
from jobfinder.infrastructure.storage import db, now, sync_text_db


MATCH_THRESHOLD = 7.0


def _benchmark_amount(job: dict[str, Any], benchmark: dict[str, Any]) -> float | None:
    title = str(job.get("title", "")).casefold()
    for company_level in ("mts 2", "mts 1"):
        if company_level in title:
            exact = next(
                (level for level in benchmark.get("levels", []) if str(level.get("level", "")).casefold() == company_level),
                None,
            )
            if exact and exact.get("total_comp"):
                return float(exact["total_comp"])
    if "staff" in title and benchmark.get("staff_total_comp"):
        return float(benchmark["staff_total_comp"])
    if (any(level in title for level in ("senior", "staff", "principal", "mts 1", "mts 2"))
            or re.search(r"\bsr\.?\b", title)) and benchmark.get("senior_total_comp"):
        return float(benchmark["senior_total_comp"])
    if benchmark.get("median_total_comp"):
        return float(benchmark["median_total_comp"])
    return None


def enrich_missing_compensation(min_score: float = MATCH_THRESHOLD) -> dict[str, Any]:
    """Fill missing pay for strong jobs and every role selected to apply.

    External total compensation stays separate from the posting's salary fields so
    it is never presented as an employer-published range.
    """
    benchmarks = salary_benchmark_map()
    sourced = 0
    companies: set[str] = set()

    with db() as conn:
        rows = [dict(row) for row in conn.execute(
            """SELECT * FROM jobs
               WHERE (actual_score>? OR actual_saved=1) AND salary_max IS NULL
                 AND (market_compensation IS NULL OR market_compensation_source='Conservative target-floor estimate')
               ORDER BY actual_score DESC""",
            (min_score,),
        )]
        for job in rows:
            foreign = is_explicitly_non_us_location(job.get("location"))
            benchmark = benchmarks.get(str(job.get("company_key", "")))
            amount = _benchmark_amount(job, benchmark) if benchmark else None
            source_url = str(benchmark.get("source_url") or "") if benchmark else ""
            # A different job's base range and the profile's target floor are
            # not evidence of this posting's total compensation.
            if not amount or not source_url:
                continue
            source = str(benchmark.get("source") or "Levels.fyi")
            if foreign:
                source = f"{source} U.S. reference"
            conn.execute(
                """UPDATE jobs SET market_compensation=?,market_compensation_source=?,
                   market_compensation_url=?,market_compensation_updated_at=? WHERE id=?""",
                (amount, source, source_url, now(), job["id"]),
            )
            sourced += 1
            companies.add(str(job.get("company", "")))

    updated_rows = sourced
    if updated_rows:
        # Import locally to avoid a service/enrichment module cycle.
        from jobfinder.application.service import rescore_all
        rescore_all()
    else:
        sync_text_db()
    return {
        "threshold": min_score,
        "updated": updated_rows,
        "sourced": sourced,
        "company_benchmarked": 0,
        "estimated": 0,
        "companies": sorted(companies, key=str.casefold),
    }


if __name__ == "__main__":
    from jobfinder.infrastructure.storage import init_storage

    init_storage()
    print(enrich_missing_compensation())
