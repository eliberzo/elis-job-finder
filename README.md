# Eli's Job Finder

A local-first, resume-ranked job finder for Eli. It collects public job postings, persists full descriptions and links, extracts skills, groups roles by company, and maintains a moving Top 40 opportunity window.

This repository contains application code only. The `data/` directory, generated resumes, local databases, saved selections, and interview recordings stay on your machine and are not checked in.

Raw collection and resume ranking are separate pipelines. LinkedIn guest pages use a bounded detail-fetch pool and a single persistence queue; permitted Greenhouse, Lever, Workable, and Apple feeds span AI, infrastructure, fintech, developer tools, SaaS, security, and consumer companies. Official-board intake is round-robin by company and capped per company to preserve diversity without relying on LinkedIn throttling; the UI labels direct ATS listings separately from LinkedIn results.

## Start

```bash
./setup.sh   # first time only
./run.sh
```

The app opens at <http://127.0.0.1:8765>.

## Download fresh jobs and find common requirements

The Git repository intentionally has **no job snapshot**. On first launch, the app creates its local `data/` directory and database. To build a fresh collection:

1. Run `./setup.sh` once, then `./run.sh`. Add a resume in the app if you want personalized ranking; collection itself does not require one.
2. Start with official employer listings: paste first-party job URLs into **＋ Import** (one per line), or import CSV with a `url` column or JSON job records. The app saves full descriptions, dates, pay when present, skills, locations, and canonical links in `data/jobs.db` and `data/jobs.jsonl`.
3. Use **Priority company sites** to refresh supported employer/ATS boards. It deep-crawls companies already saved to apply or scoring above 8, so seed a new database with a few employer URLs first. Supported adapters and company boards are in `src/jobfinder/infrastructure/providers.py`; inaccessible, authenticated, or CAPTCHA-protected listings are skipped.
4. For broader discovery *after* first-party work, use **Find on LinkedIn** in the app, or run a bounded Austin sweep from a second terminal:

   ```bash
   PYTHONPATH=src .venv/bin/python -m jobfinder.application.austin_sweep \
     --days 7 --max-queries 4 --limit-per-query 100 --workers 2
   ```

   This uses public guest listings, rate-limits detail requests, and may take several minutes. It neither signs in nor bypasses security checks. The sweep saves raw postings before re-scoring; reruns deduplicate by URL and company/title.

To see **what employers ask for most often** and **which jobs mention the most common skills**, run:

```bash
PYTHONPATH=src .venv/bin/python -m jobfinder.application.corpus_report --days 14 --limit 20
```

The read-only report defaults to relevant, official-source jobs that explicitly name Austin, Texas. It counts each normalized company/title once, shows the frequency of skills such as Python, distributed systems, cloud platforms, and Kubernetes, then lists jobs with the greatest overlap among the ten most frequent skills. These are common-requirement matches, **not** the personalized opportunity ranking. Use `--scope all` for other U.S. locations, `--include-linkedin` for fallback sources, or `--json > data/common-skills.json` for a private machine-readable report. Run `--help` for all options. A recent posting date does not prove a job is still open; verify it on the employer page before applying.

Keep any exported lists under `data/` so they stay out of Git. This project does not contact employers or submit applications.

AI resume generation uses the OpenAI Responses API. Set an API key before starting the app. Uploaded files and extracted text are stored locally; their extracted text is sent to OpenAI only when you click **Generate with AI**.

```bash
export OPENAI_API_KEY="your-api-key"
# Optional; defaults to gpt-5.4-mini
export OPENAI_MODEL="gpt-5.4-mini"
./run.sh
```

## Private data

All user-specific and collected data is under `data/`, separate from code and web styles:

- `data/private/resume.pdf` — source resume
- `data/resume_builder.json` — editable rebuilt-resume content; saving it regenerates the application PDF
- `data/resume_sources.json` — locally extracted text from resume-builder uploads
- `data/resume_versions.json` — saved and AI-generated resume snapshots
- `data/profile.json` — extracted resume text and scoring preferences
- `data/jobs.db` — canonical SQLite database
- `data/jobs.jsonl` — human-readable full text mirror
- `data/top_jobs.jsonl` — moving Top 40 company-opportunity cache
- `data/levels_salary_benchmarks.jsonl` — attributed Levels.fyi total-compensation reference bank for strategic companies
- `data/practice_companies.jsonl` — companies deliberately saved for practice applications
- `data/actual_companies.jsonl` — companies saved/protected for a serious application
- `data/practice_builder.json` — editable interview questions, answers, and per-track research todos
- `data/leetcode_research.json` — attributed public company-interview signals and source links
- `data/whiteboard_question_bank.json` — 45-question company-informed whiteboard curriculum and completion IDs
- `data/austin_companies.txt` — optional manually known Austin-heavy companies

Every job record keeps its source URL. Extracted skills, actual-application membership, and Top 40 rank are stored directly as properties on the single `jobs` table and copied into the JSONL records and cache.

## Discovery and ranking

The LinkedIn collector uses public pages only. It searches the selected markets plus Austin proper and a separate fully remote U.S. pass. A global request gate ensures LinkedIn job-detail downloads start at least two seconds apart across all workers. It does not use a login, cookies, CAPTCHA bypass, or auto-application.

For broad Austin coverage, run `PYTHONPATH=src .venv/bin/python -m jobfinder.application.austin_sweep --target-companies 300`. The sweep rotates bounded hourly batches across more than 40 Senior and Staff backend, platform, infrastructure, SRE, data, distributed-systems, cloud, and applied-AI query groups. It persists and deduplicates raw postings during collection, then runs resume scoring and compensation enrichment once at the end.

Ranking combines resume fit, interview-practice value, posting recency, compensation, and strategic burn. Austin presence and multiple fully remote openings increase company-level burn. Saving a company for actual application and the diamond/protected action are the same operation.

Refresh the salary reference bank with `cd src && ../.venv/bin/python -m jobfinder.infrastructure.levels`. Levels.fyi figures are crowdsourced annual total compensation (base, annualized stock, and bonus), displayed beside—but never conflated with—the job posting's salary range.

Missing compensation is handled by a separate enrichment job. On startup, after collection, or from **$ Fill compensation**, it finds jobs with Match score above 7 and no posted pay, attaches a sourced company/level total-compensation benchmark when available, uses a clearly labeled conservative estimate otherwise, and re-scores the corpus. It can also run directly with `cd src && ../.venv/bin/python -m jobfinder.application.compensation`.

`data/top_jobs.jsonl` stores the best current role from each of the 40 strongest companies. After imports, discovery, status changes, or re-scoring, the cache is rebuilt: stronger opportunities enter and the weakest cached companies fall out. The complete corpus remains in `data/jobs.db` and `data/jobs.jsonl`.

## Project layout

```text
src/jobfinder/
  application/       orchestration and discovery workflow
  domain/            resume matching and ranking rules
  infrastructure/    LinkedIn collection and local persistence
  presentation/      HTTP/API server
web/
  templates/         HTML presentation
  static/            JavaScript and styles
data/
  private/           resume
  exports/           legacy/manual exports, if any
  *.db, *.jsonl      persisted application data
tests/               workflow and ranking tests
```

## Import formats

- One public job URL per line
- CSV containing a `url` column
- JSON list of URLs or job objects

Public pages with `JobPosting` JSON-LD are extracted automatically. Sites that block public requests remain importable through CSV or JSON with the job details included.

The **Resume builder** tab is a real editor for contact details, target headline, summary, skill groups, experience, impact bullets, and education. Changes are stored separately from the original resume and regenerate `output/pdf/application-resume.pdf` on save. The checked-in default is blank; Eli's saved resume content remains only in ignored local data.

The UI includes a separate **Voice interview** workspace alongside the existing tabs. Its first plan is a Google Senior/Staff HR screen: it records each spoken answer, stores the audio and transcript locally, generates a targeted follow-up, and creates a scored evaluation when the session ends. Previous attempts are preserved for comparison. **Practice builder** remains unchanged and contains the editable HR, behavioral, system-design, and coding banks.

Voice interview recordings are stored under `data/private/interview_audio/`; session transcripts and feedback are stored in `data/interview_sessions.json`. The browser never receives `OPENAI_API_KEY`. Audio is sent through the local server to OpenAI for transcription, and transcripts are sent for follow-up generation and final evaluation.
