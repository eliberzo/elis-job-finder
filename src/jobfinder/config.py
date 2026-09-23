"""Application configuration and on-disk paths."""
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RESUME_DIR = DATA_DIR / "private"
WEB_DIR = PROJECT_ROOT / "web"
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf"
ACTUAL_RESUME_PATH = OUTPUT_DIR / "application-resume.pdf"
RESUME_BUILDER_PATH = DATA_DIR / "resume_builder.json"
RESUME_VERSIONS_PATH = DATA_DIR / "resume_versions.json"
RESUME_SOURCES_PATH = DATA_DIR / "resume_sources.json"
DB_PATH = DATA_DIR / "jobs.db"
TEXT_DB_PATH = DATA_DIR / "jobs.jsonl"
ACTUAL_LIST_PATH = DATA_DIR / "actual_companies.jsonl"
PRACTICE_LIST_PATH = DATA_DIR / "practice_companies.jsonl"
TOP_CACHE_PATH = DATA_DIR / "top_jobs.jsonl"
LEVELS_BANK_PATH = DATA_DIR / "levels_salary_benchmarks.jsonl"
PROFILE_PATH = DATA_DIR / "profile.json"
TODO_PATH = DATA_DIR / "todos.jsonl"
GOALS_PATH = DATA_DIR / "goals.jsonl"
PRACTICE_BUILDER_PATH = DATA_DIR / "practice_builder.json"
LOCAL_EVENTS_PATH = DATA_DIR / "local_events.json"
INTERVIEW_SESSIONS_PATH = DATA_DIR / "interview_sessions.json"
INTERVIEW_AUDIO_DIR = DATA_DIR / "private" / "interview_audio"
AUSTIN_PATH = DATA_DIR / "austin_companies.txt"
STRATEGIC_PATH = DATA_DIR / "strategic_companies.txt"
TEMPLATE_PATH = WEB_DIR / "templates" / "index.html"
STATIC_DIR = WEB_DIR / "static"
HOST, PORT = "127.0.0.1", 8765
CORPUS_JOB_TARGET = 3000
AUSTIN_PROPER_COMPANY_TARGET = 300
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")

DEFAULT_PROFILE = {
    "name": "", "current_location": "Austin, TX", "willing_to_relocate": True,
    "work_authorization": "", "requires_sponsorship": None,
    "permanent_resident": None, "us_person": None, "us_citizen": None,
    "security_clearance": "",
    "email": "", "phone": "", "compensation_fallback": 200000,
    "target_applications": 20, "resume_file": "", "resume_text": "",
    "skills": ["Python", "Kafka", "distributed systems", "microservices", "PostgreSQL", "SQL",
               "GCP", "cloud", "observability", "reliability", "system design", "technical leadership"],
    "weights": {"fit": 0.55, "practice": 0.45, "burn": 0.80, "recency": 0.30},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
 company_key TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '', url TEXT NOT NULL UNIQUE, source TEXT NOT NULL DEFAULT 'manual',
 description TEXT NOT NULL DEFAULT '', date_posted TEXT, easy_apply INTEGER NOT NULL DEFAULT 0,
 work_arrangement TEXT NOT NULL DEFAULT 'unknown', salary_text TEXT NOT NULL DEFAULT '',
 salary_min REAL, salary_max REAL, salary_type TEXT NOT NULL DEFAULT 'unknown', suggested_salary REAL,
 market_compensation REAL, market_compensation_source TEXT NOT NULL DEFAULT '',
 market_compensation_url TEXT NOT NULL DEFAULT '', market_compensation_updated_at TEXT,
 fit_score REAL NOT NULL DEFAULT 0, practice_value REAL NOT NULL DEFAULT 0, burn_cost REAL NOT NULL DEFAULT 0,
 recency_score REAL NOT NULL DEFAULT 0, age_days INTEGER, practice_score REAL NOT NULL DEFAULT 0,
 actual_score REAL NOT NULL DEFAULT 0, ai_application INTEGER NOT NULL DEFAULT 0, actual_reason TEXT NOT NULL DEFAULT '',
 reason TEXT NOT NULL DEFAULT '', matches TEXT NOT NULL DEFAULT '[]',
 concerns TEXT NOT NULL DEFAULT '[]', detected_skills TEXT NOT NULL DEFAULT '[]',
 actual_saved INTEGER NOT NULL DEFAULT 0, practice_saved INTEGER NOT NULL DEFAULT 0, top_rank INTEGER,
 status TEXT NOT NULL DEFAULT 'NEW', discovered_at TEXT NOT NULL,
 opened_at TEXT, applied_at TEXT, skipped_at TEXT, protected_at TEXT, closed_at TEXT, notes TEXT NOT NULL DEFAULT '',
 CHECK (actual_saved IN (0,1)), CHECK (practice_saved IN (0,1)),
 CHECK (NOT (actual_saved=1 AND practice_saved=1))
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""
