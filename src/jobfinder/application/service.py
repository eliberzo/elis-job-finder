"""Application use-cases connecting collection, matching, and persistence."""
from __future__ import annotations
import csv
import io
import json
from typing import Any

from jobfinder.domain.locations import is_austin_commutable_location
from jobfinder.domain.matching import has_austin_presence_evidence, infer_work_arrangement, score
from jobfinder.infrastructure.aggregator import extract_salary, format_salary_range, normalize_item
from jobfinder.infrastructure.storage import actual_company_keys, configured_austin_companies, db, persist_skills, profile, refresh_top_job_cache, sync_text_db, upsert_job

def company_market_signals(extra: dict[str, Any] | None = None) -> dict[str, dict[str, int]]:
    signals: dict[str, dict[str, int]] = {name: {"austin_jobs": 1, "remote_jobs": 0} for name in configured_austin_companies()}
    with db() as conn:
        rows = [dict(row) for row in conn.execute("SELECT company,location,description,work_arrangement FROM jobs")]
    if extra: rows.append(extra)
    for row in rows:
        company = str(row.get("company", "")).strip().casefold()
        if not company: continue
        signal = signals.setdefault(company, {"austin_jobs": 0, "remote_jobs": 0})
        if is_austin_commutable_location(row.get("location")) or has_austin_presence_evidence(row): signal["austin_jobs"] += 1
        if infer_work_arrangement(row) == "remote": signal["remote_jobs"] += 1
    return signals

def add_market_signal(signals: dict[str, dict[str, int]], job: dict[str, Any]) -> dict[str, dict[str, int]]:
    company = str(job.get("company", "")).strip().casefold()
    if not company: return signals
    updated = dict(signals)
    signal = dict(updated.get(company, {"austin_jobs": 0, "remote_jobs": 0}))
    if is_austin_commutable_location(job.get("location")) or has_austin_presence_evidence(job): signal["austin_jobs"] += 1
    if infer_work_arrangement(job) == "remote": signal["remote_jobs"] += 1
    updated[company] = signal
    return updated

def protected_for_scoring() -> set[str]: return actual_company_keys()

def prepare_job(item: Any, signals: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    prepared = normalize_item(item)
    prepared.update(score(prepared, profile(), protected_for_scoring(), add_market_signal(company_market_signals() if signals is None else signals, prepared)))
    return prepared

def save_job(item: Any, sync: bool = True) -> tuple[int, bool]: return upsert_job(prepare_job(item), sync)

def parse_import(raw: str, content_type: str) -> list[Any]:
    raw = raw.strip()
    if not raw: return []
    if "json" in content_type or raw.startswith("[") or raw.startswith("{"):
        data = json.loads(raw); return data if isinstance(data, list) else data.get("jobs", [data])
    if "," in raw.splitlines()[0] and any(x in raw.splitlines()[0].lower() for x in ("url", "company", "title")):
        return list(csv.DictReader(io.StringIO(raw)))
    return [line.strip() for line in raw.splitlines() if line.strip() and not line.lstrip().startswith("#")]

def rescore_all() -> int:
    p, protected, signals = profile(), protected_for_scoring(), company_market_signals()
    with db() as conn:
        rows = conn.execute("SELECT * FROM jobs").fetchall()
        for row in rows:
            values = score(dict(row), p, protected, signals); fields = list(values)
            conn.execute("UPDATE jobs SET " + ",".join(f"{x}=?" for x in fields) + " WHERE id=?", [values[x] for x in fields] + [row["id"]])
            persist_skills(conn, int(row["id"]), str(row["description"] or ""))
    refresh_top_job_cache(); sync_text_db(); return len(rows)

def repair_salary_data() -> int:
    repaired = 0
    with db() as conn:
        for row in conn.execute("SELECT id,description,salary_text,salary_min,salary_max FROM jobs"):
            display = format_salary_range(row["salary_min"], row["salary_max"])
            if not str(row["salary_text"] or "").strip() and display:
                conn.execute("UPDATE jobs SET salary_text=? WHERE id=?", (display, row["id"]))
                repaired += 1
                continue
            values = extract_salary(str(row["description"] or ""))
            if values.get("salary_max") and (not row["salary_max"] or float(values["salary_max"]) != float(row["salary_max"])):
                conn.execute("UPDATE jobs SET salary_text=?,salary_min=?,salary_max=?,salary_type=? WHERE id=?",
                             (values["salary_text"], values["salary_min"], values["salary_max"], values["salary_type"], row["id"]))
                repaired += 1
    return repaired
