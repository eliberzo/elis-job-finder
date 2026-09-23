"""State-changing job workflows used by HTTP, CLI, and future automations."""
from __future__ import annotations

from typing import Any

from jobfinder.application.collection import collect_company_boards, collect_linkedin
from jobfinder.application.compensation import enrich_missing_compensation
from jobfinder.application.service import parse_import, rescore_all, save_job
from jobfinder.infrastructure.storage import db, now, protect_actual_company, refresh_top_job_cache, sync_text_db, toggle_actual_company, toggle_practice_company


VALID_STATUSES = {"NEW", "OPENED", "APPLIED", "SKIPPED", "PROTECTED"}


def run_linkedin_collection(payload: dict[str, Any]) -> dict[str, Any]:
    result = collect_linkedin(payload)
    result["rescored"] = rescore_all()
    result["compensation"] = enrich_missing_compensation()
    return result


def run_company_board_collection(payload: dict[str, Any]) -> dict[str, Any]:
    result = collect_company_boards(payload)
    result["rescored"] = rescore_all()
    result["compensation"] = enrich_missing_compensation()
    return result


def import_jobs(raw: str, content_type: str) -> dict[str, Any]:
    created = updated = 0
    errors: list[str] = []
    for index, item in enumerate(parse_import(raw, content_type), 1):
        try:
            _, is_new = save_job(item)
            created += int(is_new)
            updated += int(not is_new)
        except Exception as exc:
            errors.append(f"Row {index}: {exc}")
    return {"created": created, "updated": updated, "errors": errors}


def rescore_and_enrich() -> dict[str, Any]:
    return {"updated": rescore_all(), "compensation": enrich_missing_compensation()}


def enrich_compensation() -> dict[str, Any]:
    return enrich_missing_compensation()


def toggle_actual(company: str) -> dict[str, bool]:
    saved = toggle_actual_company(company)
    rescore_all()
    return {"saved": saved}


def toggle_practice(company: str) -> dict[str, bool]:
    saved = toggle_practice_company(company)
    rescore_all()
    return {"saved": saved}


def update_job_status(job_id: int | str, status: str) -> dict[str, bool]:
    if status not in VALID_STATUSES:
        raise ValueError("Invalid status")
    with db() as conn:
        current = conn.execute("SELECT company,actual_saved FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not current:
            raise LookupError("Job not found")
        if status == "PROTECTED":
            company = str(current["company"])
        elif status == "OPENED" and current["actual_saved"]:
            conn.execute("UPDATE jobs SET opened_at=? WHERE id=?", (now(), job_id))
            company = ""
        else:
            timestamp = {"OPENED": "opened_at", "APPLIED": "applied_at", "SKIPPED": "skipped_at"}.get(status)
            if timestamp:
                conn.execute(f"UPDATE jobs SET status=?,{timestamp}=? WHERE id=?", (status, now(), job_id))
            else:
                conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
            company = ""
    if status == "PROTECTED":
        protect_actual_company(company)
        rescore_all()
        return {"ok": True, "saved_actual": True}
    refresh_top_job_cache()
    sync_text_db()
    return {"ok": True}
