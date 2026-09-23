"""Single-table SQLite persistence plus human-readable JSONL mirrors."""
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import re
import sqlite3
from typing import Any

from jobfinder.domain.company import company_identity, title_identity
from jobfinder.domain.locations import is_austin_proper_location

from jobfinder.config import (
    ACTUAL_LIST_PATH,
    AUSTIN_PATH,
    DB_PATH,
    DEFAULT_PROFILE,
    PRACTICE_LIST_PATH,
    PROFILE_PATH,
    RESUME_DIR,
    SCHEMA,
    STRATEGIC_PATH,
    TEXT_DB_PATH,
    TOP_CACHE_PATH,
)
from jobfinder.domain.matching import detect_skills


JOB_FIELDS = [
    "company", "title", "location", "url", "source", "description", "date_posted",
    "easy_apply", "work_arrangement", "salary_text", "salary_min", "salary_max",
    "salary_type", "suggested_salary", "fit_score", "practice_value", "burn_cost",
    "recency_score", "age_days", "practice_score", "actual_score", "ai_application",
    "actual_reason", "reason", "matches", "concerns", "ranking_breakdown",
]

RAW_JOB_FIELDS = [
    "company", "title", "location", "url", "source", "description", "date_posted",
    "easy_apply", "work_arrangement", "salary_text", "salary_min", "salary_max", "salary_type",
]
OFFICIAL_JOB_SOURCES = {"greenhouse", "lever", "workable", "apple", "phenom", "amazon", "jibe", "jobvite", "workday", "ashby", "breezy", "pinpoint", "successfactors", "smartrecruiters", "icims", "bamboohr", "revolutpeople", "avionte", "avature", "adp", "employer", "google", "microsoft", "bain", "oracle", "jpmorgan", "realtor", "tesla", "temporal", "gm", "teamtailor", "recruitee", "schwab", "capitalone", "arm", "procore", "deloitte", "cisco", "homedepot", "paypal", "qualcomm", "servicenow", "paloalto", "lpl", "pwc", "rippling", "ripplehire", "tcs", "dell", "roku", "westernunion", "resideo", "paylocity", "paycor", "ukg", "kpmg", "salesforce", "meta", "uber", "walmart", "accenture"}
GENERIC_JOB_LOCATIONS = {"", "hybrid", "remote", "multiple locations", "united states", "us", "usa"}


def _official_requisition_key(source: str, url: str) -> str:
    """Return a stable provider identity when a canonical URL contains a mutable title slug."""
    source_key = str(source or "").casefold()
    if source_key == "realtor":
        match = re.search(r"careers\.realtor\.com/job/(\d+)(?:/|$)", str(url or ""), re.I)
        return f"realtor:{match.group(1)}" if match else ""
    if source_key == "westernunion":
        match = re.search(r"careers\.westernunion\.com/job-details/(\d+)(?:/|$)", str(url or ""), re.I)
        return f"westernunion:{match.group(1)}" if match else ""
    if source_key == "gm":
        match = re.search(r"search-careers\.gm\.com/(?:[a-z]{2}/)?jobs/(jr-[^/]+)(?:/|$)", str(url or ""), re.I)
        return f"gm:{match.group(1).casefold()}" if match else ""
    if source_key == "oracle":
        match = re.search(r"careers\.oracle\.com/(?:[a-z]{2}/)?sites/[^/]+/job/(\d+)(?:/|$)", str(url or ""), re.I)
        return f"oracle:{match.group(1)}" if match else ""
    if source_key == "workday":
        match = re.search(r"/[^/?#]*_((?:JR|REF|R)-?\d+[A-Z]*(?:-\d+)?)(?:[/?#]|$)", str(url or ""), re.I)
        return f"workday:{match.group(1).casefold()}" if match else ""
    if source_key == "adp":
        match = re.search(r"[?&]jobId=(\d+)(?:[&#]|$)", str(url or ""), re.I)
        return f"adp:{match.group(1)}" if match else ""
    if source_key == "successfactors":
        match = re.search(r"/(\d+)/?(?:[?#]|$)", str(url or ""), re.I)
        return f"successfactors:{match.group(1)}" if match else ""
    if source_key == "ripplehire":
        match = re.search(r"#detail/job/(\d+)(?:[/?#]|$)", str(url or ""), re.I)
        return f"ripplehire:{match.group(1)}" if match else ""
    if source_key == "tcs":
        match = re.search(r"#/jobs/(\d+)j(?:[/?#]|$)", str(url or ""), re.I)
        return f"tcs:{match.group(1)}" if match else ""
    if source_key == "smartrecruiters":
        match = re.search(r"smartrecruiters\.com/[^/]+/(\d+)(?:-|[/?#]|$)", str(url or ""), re.I)
        return f"smartrecruiters:{match.group(1)}" if match else ""
    if source_key == "icims":
        match = re.search(r"/jobs/(\d+)(?:/|$)", str(url or ""), re.I)
        return f"icims:{match.group(1)}" if match else ""
    if source_key == "homedepot":
        match = re.search(r"careers\.homedepot\.com/job/(\d+)(?:/|$)", str(url or ""), re.I)
        return f"homedepot:{match.group(1)}" if match else ""
    if source_key == "capitalone":
        match = re.search(r"capitalonecareers\.com/job/[^?#]+/1732/(\d+)(?:[/?#]|$)", str(url or ""), re.I)
        return f"capitalone:{match.group(1)}" if match else ""
    if source_key == "revolutpeople":
        match = re.search(r"/position/(?:[^/?#]*-)?([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?:[/?#]|$)", str(url or ""), re.I)
        return f"revolutpeople:{match.group(1).casefold()}" if match else ""
    if source_key == "ukg":
        match = re.search(r"[?&]opportunityId=([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?:[&#]|$)", str(url or ""), re.I)
        return f"ukg:{match.group(1).casefold()}" if match else ""
    if source_key == "paycor":
        match = re.search(r"[?&]gni=([0-9a-f]+)(?:[&#]|$)", str(url or ""), re.I)
        return f"paycor:{match.group(1).casefold()}" if match else ""
    if source_key == "avionte":
        match = re.search(r"[?&]rpid=([^&#]+)", str(url or ""), re.I)
        return f"avionte:{match.group(1)}" if match else ""
    if source_key == "amazon":
        match = re.search(r"amazon\.jobs/(?:[a-z]{2}/)?jobs?/(\d+)(?:/|$)", str(url or ""), re.I)
        return f"amazon:{match.group(1)}" if match else ""
    if source_key == "greenhouse":
        match = re.search(r"(?:/jobs/(\d+)(?:[/?#]|$)|[?&]gh_jid=(\d+)(?:[&#]|$))", str(url or ""), re.I)
        requisition_id = next((value for value in match.groups() if value), "") if match else ""
        return f"greenhouse:{requisition_id}" if requisition_id else ""
    if source_key == "jibe":
        match = re.search(r"/jobs/([a-z]*\d+)(?:[/?#]|$)", str(url or ""), re.I)
        return f"jibe:{match.group(1).casefold()}" if match else ""
    if source_key == "jobvite":
        match = re.search(r"/job/([^/?#]+)", str(url or ""), re.I)
        return f"jobvite:{match.group(1).casefold()}" if match else ""
    if source_key == "teamtailor":
        match = re.search(r"/jobs/(\d+)(?:-|[/?#]|$)", str(url or ""), re.I)
        return f"teamtailor:{match.group(1)}" if match else ""
    if source_key == "schwab":
        match = re.search(r"/\d+/(\d+)(?:[/?#]|$)", str(url or ""), re.I)
        return f"schwab:{match.group(1)}" if match else ""
    if source_key == "arm":
        match = re.search(r"/job/[^/]+/[^/]+/33099/(\d+)(?:[/?#]|$)", str(url or ""), re.I)
        return f"arm:{match.group(1)}" if match else ""
    if source_key == "deloitte":
        match = re.search(r"/JobDetail/(?:[^/?#]+/)?(\d+)(?:[/?#]|$)", str(url or ""), re.I)
        return f"deloitte:{match.group(1)}" if match else ""
    if source_key == "kpmg":
        match = re.search(r"[?&]jobId=(\d+)(?:[&#]|$)", str(url or ""), re.I)
        return f"kpmg:{match.group(1)}" if match else ""
    if source_key == "pwc":
        match = re.search(r"jobs-us\.pwc\.com/us/en/job/([^/?#]+)(?:/|$)", str(url or ""), re.I)
        return f"pwc:{match.group(1).casefold()}" if match else ""
    if source_key == "paypal":
        match = re.search(r"paypal\.eightfold\.ai/careers(?:/job/|\?[^#]*\bpid=)(\d+)(?:[&#/?]|$)", str(url or ""), re.I)
        return f"paypal:{match.group(1)}" if match else ""
    if source_key == "qualcomm":
        match = re.search(r"careers\.qualcomm\.com/careers(?:/job/|\?[^#]*\bpid=)(\d+)(?:[&#/?]|$)", str(url or ""), re.I)
        return f"qualcomm:{match.group(1)}" if match else ""
    if source_key == "salesforce":
        match = re.search(r"salesforce\.com/company/careers/jobs/(JR\d+)(?:[/?#]|$)", str(url or ""), re.I)
        return f"salesforce:{match.group(1).casefold()}" if match else ""
    if source_key == "meta":
        match = re.search(r"metacareers\.com/profile/job_details/(\d+)(?:[/?#]|$)", str(url or ""), re.I)
        return f"meta:{match.group(1)}" if match else ""
    if source_key == "servicenow":
        match = re.search(r"careers\.servicenow\.com/jobs/(\d+)(?:/|$)", str(url or ""), re.I)
        return f"servicenow:{match.group(1)}" if match else ""
    if source_key == "accenture":
        match = re.search(r"accenture\.com/us-en/careers/jobdetails\?[^#]*\bid=(R\d+)_en(?:[&#]|$)", str(url or ""), re.I)
        return f"accenture:{match.group(1).casefold()}" if match else ""
    if source_key == "cisco":
        match = re.search(r"careers\.cisco\.com/global/en/job/(\d+)(?:/|$)", str(url or ""), re.I)
        return f"cisco:{match.group(1)}" if match else ""
    if source_key == "avature" and re.search(r"careers\.ibm\.com/", str(url or ""), re.I):
        match = re.search(r"(?:/|[?&]jobId=)(\d+)(?:[&#/?]|$)", str(url or ""), re.I)
        return f"ibm:{match.group(1)}" if match else ""
    if source_key == "avature" and re.search(r"jobs\.ea\.com/", str(url or ""), re.I):
        match = re.search(r"/(\d+)(?:[/?#]|$)", str(url or ""), re.I)
        return f"ea:{match.group(1)}" if match else ""
    if source_key == "rippling":
        match = re.search(
            r"ats\.rippling\.com/rippling/jobs/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?:[/?#]|$)",
            str(url or ""),
            re.I,
        )
        if match:
            return f"rippling:{match.group(1).casefold()}"
        legacy = re.search(r"[a-z0-9-]+\.rippling-ats\.com/job/(\d+)(?:/|$)", str(url or ""), re.I)
        return f"rippling:{legacy.group(1)}" if legacy else ""
    return ""


def _descriptions_are_mirrors(first: str, second: str) -> bool:
    """Require substantial near-identical text before treating two postings as mirrors."""
    first_text = re.sub(r"[^a-z0-9]+", " ", str(first or "").casefold()).strip()
    second_text = re.sub(r"[^a-z0-9]+", " ", str(second or "").casefold()).strip()
    return bool(
        len(first_text) >= 400
        and len(second_text) >= 400
        and SequenceMatcher(None, first_text, second_text, autojunk=False).ratio() >= 0.90
    )


def _collapse_official_mirror_duplicates(conn: sqlite3.Connection, official_job_id: int) -> int:
    """Remove exact-link duplicates and near-identical mirrors after an official refresh."""
    official = conn.execute(
        "SELECT id,company_key,title,url,source,description,salary_min,salary_max,actual_saved,practice_saved,status,notes,"
        "opened_at,applied_at,skipped_at,protected_at FROM jobs WHERE id=?",
        (official_job_id,),
    ).fetchone()
    if not official or str(official["source"] or "").casefold() not in OFFICIAL_JOB_SOURCES:
        return 0
    removed = 0
    requisition_key = _official_requisition_key(str(official["source"]), str(official["url"]))
    exact_duplicates = [
        row for row in conn.execute(
            "SELECT id,url,actual_saved,practice_saved,status,notes,opened_at,applied_at,skipped_at,protected_at "
            "FROM jobs WHERE company_key=? AND source=? AND id<>?",
            (official["company_key"], official["source"], official_job_id),
        ).fetchall()
        if str(row["url"] or "") == str(official["url"] or "")
        or (requisition_key and _official_requisition_key(str(official["source"]), str(row["url"])) == requisition_key)
    ]
    if exact_duplicates:
        records = [official, *exact_duplicates]
        actual_saved = int(any(record["actual_saved"] for record in records))
        practice_saved = 0 if actual_saved else int(any(record["practice_saved"] for record in records))
        statuses = [str(record["status"] or "NEW") for record in records]
        status_priority = {"NEW": 0, "SKIPPED": 1, "OPENED": 2, "APPLIED": 3, "PROTECTED": 4}
        status = "PROTECTED" if actual_saved else max(statuses, key=lambda value: status_priority.get(value, 0))
        notes = "\n".join(dict.fromkeys(
            str(record["notes"] or "").strip() for record in records if str(record["notes"] or "").strip()
        ))
        timestamps = [
            next((record[field] for record in records if record[field]), None)
            for field in ("opened_at", "applied_at", "skipped_at", "protected_at")
        ]
        conn.execute(
            "UPDATE jobs SET actual_saved=?,practice_saved=?,status=?,notes=?,opened_at=?,applied_at=?,skipped_at=?,protected_at=? WHERE id=?",
            (actual_saved, practice_saved, status, notes, *timestamps, official_job_id),
        )
        for duplicate in exact_duplicates:
            conn.execute("DELETE FROM jobs WHERE id=?", (duplicate["id"],))
            removed += 1
    if len(re.sub(r"[^a-z0-9]+", " ", str(official["description"] or "").casefold()).strip()) < 400:
        return removed
    mirrors = conn.execute(
        f"SELECT id,title,description,salary_min,salary_max,actual_saved,practice_saved,status,notes,opened_at,applied_at,skipped_at,protected_at "
        f"FROM jobs WHERE company_key=? AND id<>? AND source NOT IN ({','.join('?' for _ in OFFICIAL_JOB_SOURCES)})",
        (official["company_key"], official_job_id, *sorted(OFFICIAL_JOB_SOURCES)),
    ).fetchall()
    for mirror in mirrors:
        if title_key(str(mirror["title"] or "")) != title_key(str(official["title"] or "")):
            continue
        compared_salary = False
        salary_mismatch = False
        for official_salary, mirror_salary in (
            (official["salary_min"], mirror["salary_min"]),
            (official["salary_max"], mirror["salary_max"]),
        ):
            if official_salary is not None and mirror_salary is not None:
                compared_salary = True
                salary_mismatch = salary_mismatch or abs(float(official_salary) - float(mirror_salary)) > 1.0
        if compared_salary and salary_mismatch:
            continue
        if not _descriptions_are_mirrors(str(official["description"] or ""), str(mirror["description"] or "")):
            continue
        actual_saved = int(bool(official["actual_saved"] or mirror["actual_saved"]))
        practice_saved = 0 if actual_saved else int(bool(official["practice_saved"] or mirror["practice_saved"]))
        status = "PROTECTED" if actual_saved else str(official["status"] or mirror["status"] or "NEW")
        notes = "\n".join(dict.fromkeys(value for value in (str(official["notes"] or "").strip(), str(mirror["notes"] or "").strip()) if value))
        conn.execute(
            "UPDATE jobs SET actual_saved=?,practice_saved=?,status=?,notes=?,"
            "opened_at=COALESCE(opened_at,?),applied_at=COALESCE(applied_at,?),"
            "skipped_at=COALESCE(skipped_at,?),protected_at=COALESCE(protected_at,?) WHERE id=?",
            (actual_saved, practice_saved, status, notes, mirror["opened_at"], mirror["applied_at"], mirror["skipped_at"], mirror["protected_at"], official_job_id),
        )
        conn.execute("DELETE FROM jobs WHERE id=?", (mirror["id"],))
        removed += 1
    return removed


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def company_key(name: str) -> str:
    return company_identity(name)


def title_key(title: str) -> str:
    return title_identity(title)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _extract_resume(profile_data: dict[str, Any]) -> dict[str, Any]:
    pdfs = sorted(RESUME_DIR.glob("*.pdf"))
    if pdfs:
        profile_data["resume_file"] = f"data/private/{pdfs[0].name}"
        if not profile_data.get("resume_text"):
            try:
                from pypdf import PdfReader
                text = "\n".join((page.extract_text() or "") for page in PdfReader(str(pdfs[0])).pages).strip()
                if text:
                    profile_data["resume_text"] = text
            except Exception as exc:
                print(f"Resume extraction pending: {exc}")
    text = profile_data.get("resume_text", "")
    if text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        email = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        phone = re.search(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", text)
        if not profile_data.get("name") and lines:
            profile_data["name"] = lines[0]
        if not profile_data.get("email") and email:
            profile_data["email"] = email.group(0)
        if not profile_data.get("phone") and phone:
            profile_data["phone"] = phone.group(0)
    return profile_data


def init_storage() -> None:
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = json.loads(PROFILE_PATH.read_text()) if PROFILE_PATH.exists() else {}
    merged = DEFAULT_PROFILE | current
    merged["weights"] = DEFAULT_PROFILE["weights"] | current.get("weights", {})
    merged.pop("thresholds", None)
    PROFILE_PATH.write_text(json.dumps(_extract_resume(merged), indent=2) + "\n")
    if not AUSTIN_PATH.exists():
        AUSTIN_PATH.write_text("# Companies with a meaningful Austin presence, one per line.\n")

    with db() as conn:
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        additions = {
            "recency_score": "REAL NOT NULL DEFAULT 0",
            "age_days": "INTEGER",
            "detected_skills": "TEXT NOT NULL DEFAULT '[]'",
            "actual_saved": "INTEGER NOT NULL DEFAULT 0",
            "practice_saved": "INTEGER NOT NULL DEFAULT 0",
            "top_rank": "INTEGER",
            "company_key": "TEXT NOT NULL DEFAULT ''",
            "actual_score": "REAL NOT NULL DEFAULT 0",
            "ai_application": "INTEGER NOT NULL DEFAULT 0",
            "actual_reason": "TEXT NOT NULL DEFAULT ''",
            "market_compensation": "REAL",
            "market_compensation_source": "TEXT NOT NULL DEFAULT ''",
            "market_compensation_url": "TEXT NOT NULL DEFAULT ''",
            "market_compensation_updated_at": "TEXT",
            "ranking_breakdown": "TEXT NOT NULL DEFAULT '{}'",
            "closed_at": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")
        for job_id, company in conn.execute("SELECT id,company FROM jobs"):
            conn.execute("UPDATE jobs SET company_key=? WHERE id=?", (company_key(str(company)), job_id))

        if _table_exists(conn, "job_skills"):
            for job_id, skills in conn.execute("SELECT job_id,group_concat(skill, char(31)) FROM job_skills GROUP BY job_id"):
                conn.execute("UPDATE jobs SET detected_skills=? WHERE id=?", (json.dumps(str(skills or "").split(chr(31)) if skills else []), job_id))

        if _table_exists(conn, "actual_companies"):
            for (company_name,) in conn.execute("SELECT company_name FROM actual_companies"):
                conn.execute("UPDATE jobs SET actual_saved=1,status='PROTECTED',protected_at=COALESCE(protected_at,?) WHERE lower(company)=lower(?)", (now(), company_name))

        conn.execute("DROP INDEX IF EXISTS idx_jobs_decision_status")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        for obsolete in ("decision", "score_fingerprint"):
            if obsolete in columns:
                try:
                    conn.execute(f"ALTER TABLE jobs DROP COLUMN {obsolete}")
                except sqlite3.OperationalError:
                    pass
        conn.execute("DROP TABLE IF EXISTS job_skills")
        conn.execute("DROP TABLE IF EXISTS actual_companies")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_actual_saved ON jobs(actual_saved)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_practice_saved ON jobs(practice_saved)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_top_rank ON jobs(top_rank)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company_key ON jobs(company_key)")
        for job_id, company in conn.execute("SELECT id,company FROM jobs"):
            if is_strategic_company(str(company)):
                conn.execute("UPDATE jobs SET actual_saved=1,practice_saved=0,status='PROTECTED',protected_at=COALESCE(protected_at,?) WHERE id=?", (now(), job_id))
        conn.execute("UPDATE jobs SET practice_saved=0,status='PROTECTED',protected_at=COALESCE(protected_at,?) WHERE actual_saved=1", (now(),))

    refresh_top_job_cache()
    sync_actual_companies()
    sync_practice_companies()
    sync_text_db()


def profile() -> dict[str, Any]:
    return json.loads(PROFILE_PATH.read_text())


def configured_austin_companies() -> set[str]:
    return {line.strip().casefold() for line in AUSTIN_PATH.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")}


def strategic_company_patterns() -> tuple[set[str], set[str]]:
    exact, prefixes = set(), set()
    if not STRATEGIC_PATH.exists():
        return exact, prefixes
    for line in STRATEGIC_PATH.read_text().splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.endswith("*"):
            prefixes.add(company_key(value[:-1]))
        else:
            exact.add(company_key(value))
    return exact, prefixes


def is_strategic_company(name: str) -> bool:
    key = company_key(name)
    exact, prefixes = strategic_company_patterns()
    return key in exact or any(key.startswith(prefix) for prefix in prefixes if prefix)


def persist_skills(conn: sqlite3.Connection, job_id: int, description: str) -> None:
    conn.execute("UPDATE jobs SET detected_skills=? WHERE id=?", (json.dumps(detect_skills(description)), job_id))


def upsert_job(item: dict[str, Any], sync: bool = True) -> tuple[int, bool]:
    values = [item.get(field, "" if field not in ("salary_min", "salary_max", "suggested_salary", "date_posted", "age_days") else None) for field in JOB_FIELDS]
    with db() as conn:
        existing = conn.execute("SELECT id FROM jobs WHERE url=?", (item["url"],)).fetchone()
        if existing:
            updates = ",".join(f"{field}=?" for field in JOB_FIELDS if field != "url")
            conn.execute(f"UPDATE jobs SET {updates} WHERE id=?", [item.get(field) for field in JOB_FIELDS if field != "url"] + [existing["id"]])
            job_id, created = int(existing["id"]), False
        else:
            marks = ",".join("?" for _ in JOB_FIELDS)
            cursor = conn.execute(f"INSERT INTO jobs ({','.join(JOB_FIELDS)},discovered_at) VALUES ({marks},?)", values + [now()])
            job_id, created = int(cursor.lastrowid), True
        key = company_key(str(item.get("company", "")))
        conn.execute("UPDATE jobs SET company_key=? WHERE id=?", (key, job_id))
        listed = is_strategic_company(str(item.get("company", ""))) or bool(conn.execute("SELECT 1 FROM jobs WHERE company_key=? AND actual_saved=1 LIMIT 1", (key,)).fetchone())
        practice_listed = bool(conn.execute("SELECT 1 FROM jobs WHERE company_key=? AND practice_saved=1 LIMIT 1", (key,)).fetchone())
        if listed:
            conn.execute("UPDATE jobs SET actual_saved=1,practice_saved=0,status='PROTECTED',protected_at=COALESCE(protected_at,?) WHERE id=?", (now(), job_id))
        elif practice_listed:
            conn.execute("UPDATE jobs SET practice_saved=1 WHERE id=?", (job_id,))
        persist_skills(conn, job_id, str(item.get("description", "")))
    if sync:
        refresh_top_job_cache()
        sync_actual_companies()
        sync_practice_companies()
        sync_text_db()
    return job_id, created


def upsert_raw_job(item: dict[str, Any], sync: bool = False) -> tuple[int, bool]:
    """Persist collector output without importing or invoking any scoring rules."""
    values = [item.get(field) for field in RAW_JOB_FIELDS]
    with db() as conn:
        existing = conn.execute(
            "SELECT id,url,location,date_posted,source,salary_text,salary_min,salary_max,salary_type FROM jobs WHERE url=?",
            (item["url"],),
        ).fetchone()
        refresh_url = False
        preserve_official_mirror = False
        incoming_source = str(item.get("source", "")).casefold()
        if not existing and incoming_source not in OFFICIAL_JOB_SOURCES:
            incoming_company_key = company_key(str(item.get("company", "")))
            incoming_title_key = title_key(str(item.get("title", "")))
            official_candidates = [
                row for row in conn.execute(
                    f"SELECT id,url,title,location,date_posted,source,description,salary_text,salary_min,salary_max,salary_type "
                    f"FROM jobs WHERE company_key=? AND source IN ({','.join('?' for _ in OFFICIAL_JOB_SOURCES)}) "
                    "ORDER BY date_posted DESC, id",
                    (incoming_company_key, *sorted(OFFICIAL_JOB_SOURCES)),
                ).fetchall()
                if title_key(str(row["title"] or "")) == incoming_title_key
            ]
            for candidate in official_candidates:
                salary_mismatch = any(
                    incoming is not None and stored is not None and abs(float(incoming) - float(stored)) > 1.0
                    for incoming, stored in (
                        (item.get("salary_min"), candidate["salary_min"]),
                        (item.get("salary_max"), candidate["salary_max"]),
                    )
                )
                if salary_mismatch or not _descriptions_are_mirrors(
                    str(item.get("description", "")), str(candidate["description"] or "")
                ):
                    continue
                existing = candidate
                preserve_official_mirror = True
                break
            # Aggregators often truncate or rewrite the employer description,
            # so description similarity alone cannot reliably identify a late
            # mirror. Once an official record exists for the normalized
            # company/title pair, keep that canonical row authoritative.
            if not existing and official_candidates:
                existing = official_candidates[0]
                preserve_official_mirror = True
        if not existing and str(item.get("source", "")).casefold() in OFFICIAL_JOB_SOURCES:
            incoming_company_key = company_key(str(item.get("company", "")))
            requisition_key = _official_requisition_key(str(item.get("source", "")), str(item.get("url", "")))
            if requisition_key:
                existing = next((
                    row for row in conn.execute(
                        "SELECT id,url,location,date_posted,source,salary_text,salary_min,salary_max,salary_type FROM jobs "
                        "WHERE company_key=? AND source=? ORDER BY date_posted DESC, id",
                        (incoming_company_key, item.get("source")),
                    ).fetchall()
                    if _official_requisition_key(str(row["source"]), str(row["url"])) == requisition_key
                ), None)
                refresh_url = bool(existing)
            incoming_title_key = title_key(str(item.get("title", "")))
            if not existing and requisition_key and is_austin_proper_location(item.get("location")):
                # Promote one same-title Austin aggregator row in place. The
                # canonical requisition becomes its URL without losing saved
                # selections; distinct official requisitions remain distinct.
                mirrors = [
                    row for row in conn.execute(
                        "SELECT id,url,title,location,date_posted,source,actual_saved,salary_text,salary_min,salary_max,salary_type "
                        "FROM jobs WHERE company_key=? AND source='linkedin'",
                        (incoming_company_key,),
                    ).fetchall()
                    if title_key(str(row["title"])) == incoming_title_key
                    and is_austin_proper_location(row["location"])
                ]
                if mirrors:
                    existing = max(mirrors, key=lambda row: (
                        int(row["actual_saved"] or 0), str(row["date_posted"] or ""), int(row["id"])
                    ))
                    refresh_url = True
            # A provider requisition ID is authoritative. Distinct canonical
            # requisitions may legitimately share a generic title such as
            # "Senior Software Engineer", so only use title fallback for
            # providers whose URLs do not expose a stable requisition key.
            candidates = [] if existing or requisition_key else [
                row for row in conn.execute(
                    "SELECT id,url,title,location,date_posted,source,salary_text,salary_min,salary_max,salary_type FROM jobs "
                    "WHERE company_key=? ORDER BY date_posted DESC, id",
                    (incoming_company_key,),
                ).fetchall()
                if title_key(str(row["title"])) == incoming_title_key
            ]
            incoming_salary = (item.get("salary_min"), item.get("salary_max"))
            if not existing and len(candidates) > 1 and any(value is not None for value in incoming_salary):
                def salary_distance(row: sqlite3.Row) -> tuple[float, str, int]:
                    distance = 0.0
                    compared = 0
                    for incoming, stored in zip(incoming_salary, (row["salary_min"], row["salary_max"])):
                        if incoming is not None and stored is not None:
                            distance += abs(float(incoming) - float(stored))
                            compared += 1
                    return (distance if compared else float("inf"), str(row["date_posted"] or ""), int(row["id"]))
                existing = min(candidates, key=salary_distance)
            elif not existing and candidates:
                existing = candidates[0]
            refresh_url = refresh_url or bool(existing)
        skip_older_duplicate = bool(
            existing and refresh_url
            and str(existing["source"] or "").casefold() == str(item.get("source", "")).casefold()
            and str(existing["date_posted"] or "") > str(item.get("date_posted") or "")
        )
        if existing:
            item = dict(item)
            incoming_is_official = str(item.get("source", "")).casefold() in OFFICIAL_JOB_SOURCES
            incoming_location = str(item.get("location", "")).strip().casefold()
            existing_location = str(existing["location"] or "").strip()
            if (
                incoming_is_official
                and incoming_location in GENERIC_JOB_LOCATIONS
                and existing_location.casefold() not in GENERIC_JOB_LOCATIONS
            ):
                item["location"] = existing_location
            if incoming_is_official and not item.get("date_posted") and existing["date_posted"]:
                item["date_posted"] = existing["date_posted"]
            if incoming_is_official and item.get("salary_max") is None and existing["salary_max"] is not None:
                for field in ("salary_text", "salary_min", "salary_max", "salary_type"):
                    item[field] = existing[field]
            if not skip_older_duplicate and not preserve_official_mirror:
                update_fields = [field for field in RAW_JOB_FIELDS if field != "url" or refresh_url]
                updates = ",".join(f"{field}=?" for field in update_fields)
                conn.execute(f"UPDATE jobs SET {updates} WHERE id=?", [item.get(field) for field in update_fields] + [existing["id"]])
                if incoming_is_official:
                    # A live first-party refresh is the only evidence that can
                    # reopen a previously employer-confirmed closed posting.
                    conn.execute("UPDATE jobs SET closed_at=NULL WHERE id=?", (existing["id"],))
            job_id, created = int(existing["id"]), False
        else:
            fields = ",".join(RAW_JOB_FIELDS)
            marks = ",".join("?" for _ in RAW_JOB_FIELDS)
            cursor = conn.execute(f"INSERT INTO jobs ({fields},discovered_at) VALUES ({marks},?)", values + [now()])
            job_id, created = int(cursor.lastrowid), True
        key = company_key(str(item.get("company", "")))
        conn.execute("UPDATE jobs SET company_key=? WHERE id=?", (key, job_id))
        listed = is_strategic_company(str(item.get("company", ""))) or bool(conn.execute("SELECT 1 FROM jobs WHERE company_key=? AND actual_saved=1 LIMIT 1", (key,)).fetchone())
        practice_listed = bool(conn.execute("SELECT 1 FROM jobs WHERE company_key=? AND practice_saved=1 LIMIT 1", (key,)).fetchone())
        if listed:
            conn.execute("UPDATE jobs SET actual_saved=1,practice_saved=0,status='PROTECTED',protected_at=COALESCE(protected_at,?) WHERE id=?", (now(), job_id))
        elif practice_listed:
            conn.execute("UPDATE jobs SET practice_saved=1 WHERE id=?", (job_id,))
        if not skip_older_duplicate and not preserve_official_mirror:
            persist_skills(conn, job_id, str(item.get("description", "")))
            _collapse_official_mirror_duplicates(conn, job_id)
    if sync:
        sync_actual_companies()
        sync_practice_companies()
        sync_text_db()
    return job_id, created


def _decode_json_fields(record: dict[str, Any]) -> dict[str, Any]:
    record.pop("decision", None)
    record.pop("score_fingerprint", None)
    for field in ("matches", "concerns", "detected_skills", "ranking_breakdown"):
        try:
            record[field] = json.loads(record.get(field) or "[]")
        except (json.JSONDecodeError, TypeError):
            record[field] = {} if field == "ranking_breakdown" else []
    record["actual_saved"] = bool(record.get("actual_saved"))
    record["practice_saved"] = bool(record.get("practice_saved"))
    record["company_key"] = company_key(str(record.get("company", "")))
    return record


def job_json(row: sqlite3.Row) -> dict[str, Any]:
    return _decode_json_fields(dict(row))


def actual_company_keys() -> set[str]:
    with db() as conn:
        return {str(row[0]) for row in conn.execute("SELECT DISTINCT company_key FROM jobs WHERE actual_saved=1")}


def practice_company_keys() -> set[str]:
    with db() as conn:
        return {str(row[0]) for row in conn.execute("SELECT DISTINCT company_key FROM jobs WHERE practice_saved=1")}


def toggle_actual_company(name: str) -> bool:
    key = company_key(name)
    if not key:
        raise ValueError("Company name is required")
    with db() as conn:
        exists = bool(conn.execute("SELECT 1 FROM jobs WHERE company_key=? AND actual_saved=1 LIMIT 1", (key,)).fetchone())
        if exists and is_strategic_company(name):
            return True
        if exists:
            conn.execute("UPDATE jobs SET actual_saved=0,status=CASE WHEN status='PROTECTED' THEN 'NEW' ELSE status END,protected_at=NULL WHERE company_key=?", (key,))
            saved = False
        else:
            conn.execute("UPDATE jobs SET actual_saved=1,practice_saved=0,status='PROTECTED',protected_at=COALESCE(protected_at,?) WHERE company_key=?", (now(), key))
            saved = True
    refresh_top_job_cache()
    sync_actual_companies()
    sync_practice_companies()
    sync_text_db()
    return saved


def protect_actual_company(name: str) -> None:
    key = company_key(name)
    if not key:
        raise ValueError("Company name is required")
    with db() as conn:
        conn.execute("UPDATE jobs SET actual_saved=1,practice_saved=0,status='PROTECTED',protected_at=COALESCE(protected_at,?) WHERE company_key=?", (now(), key))
    refresh_top_job_cache()
    sync_actual_companies()
    sync_practice_companies()
    sync_text_db()


def toggle_practice_company(name: str) -> bool:
    key = company_key(name)
    if not key: raise ValueError("Company name is required")
    if is_strategic_company(name):
        raise ValueError("Strategic companies are protected for actual applications and cannot be saved for practice")
    with db() as conn:
        exists = bool(conn.execute("SELECT 1 FROM jobs WHERE company_key=? AND practice_saved=1 LIMIT 1", (key,)).fetchone())
        if exists:
            conn.execute("UPDATE jobs SET practice_saved=0 WHERE company_key=?", (key,))
            saved = False
        else:
            conn.execute("""UPDATE jobs SET practice_saved=1,actual_saved=0,
                status=CASE WHEN status='PROTECTED' THEN 'NEW' ELSE status END,
                protected_at=NULL WHERE company_key=?""", (key,))
            saved = True
    refresh_top_job_cache()
    sync_actual_companies()
    sync_practice_companies()
    sync_text_db()
    return saved


def sync_actual_companies() -> None:
    with db() as conn:
        rows = [
            {"company_key": row[0], "company_name": row[1], "saved_at": row[2] or now()}
            for row in conn.execute("SELECT company_key,MIN(company),MIN(protected_at) FROM jobs WHERE actual_saved=1 GROUP BY company_key ORDER BY MIN(company)")
        ]
    temporary = ACTUAL_LIST_PATH.with_suffix(".jsonl.tmp")
    temporary.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""))
    temporary.replace(ACTUAL_LIST_PATH)


def sync_practice_companies() -> None:
    with db() as conn:
        rows = [
            {"company_key": row[0], "company_name": row[1], "saved_at": now()}
            for row in conn.execute("SELECT company_key,MIN(company) FROM jobs WHERE practice_saved=1 GROUP BY company_key ORDER BY MIN(company)")
        ]
    temporary = PRACTICE_LIST_PATH.with_suffix(".jsonl.tmp")
    temporary.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""))
    temporary.replace(PRACTICE_LIST_PATH)


def sync_text_db() -> None:
    with db() as conn:
        records = [_decode_json_fields(dict(row)) for row in conn.execute("SELECT * FROM jobs ORDER BY id")]
    temporary = TEXT_DB_PATH.with_suffix(".jsonl.tmp")
    temporary.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + ("\n" if records else ""))
    temporary.replace(TEXT_DB_PATH)


def refresh_top_job_cache(limit: int = 40) -> int:
    selected, seen_companies = [], set()
    with db() as conn:
        conn.execute("UPDATE jobs SET top_rank=NULL")
        rows = conn.execute("""SELECT * FROM jobs
            WHERE status NOT IN ('APPLIED','SKIPPED','PROTECTED') AND actual_saved=0 AND closed_at IS NULL
              AND COALESCE(salary_max,market_compensation,suggested_salary,0) >= 200000
            ORDER BY practice_score DESC, fit_score DESC, recency_score DESC,
                     COALESCE(salary_max,market_compensation,suggested_salary,0) DESC""").fetchall()
        for row in rows:
            key = company_key(str(row["company"]))
            if not key or key in seen_companies:
                continue
            seen_companies.add(key)
            selected.append(_decode_json_fields(dict(row)))
            if len(selected) >= limit:
                break
        for rank, record in enumerate(selected, 1):
            conn.execute("UPDATE jobs SET top_rank=? WHERE id=?", (rank, record["id"]))

    floor = float(selected[-1]["practice_score"]) if selected else 0.0
    cached_at = now()
    for rank, record in enumerate(selected, 1):
        record["skills"] = record.pop("detected_skills", [])
        record["cache_rank"] = rank
        record["cache_floor"] = floor
        record["score_above_floor"] = round(float(record["practice_score"]) - floor, 2)
        record["cached_at"] = cached_at
    temporary = TOP_CACHE_PATH.with_suffix(".jsonl.tmp")
    temporary.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in selected) + ("\n" if selected else ""))
    temporary.replace(TOP_CACHE_PATH)
    return len(selected)
