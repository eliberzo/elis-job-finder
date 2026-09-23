"""Build a selected-company LeetCode study view from sourced local research."""
from __future__ import annotations

from typing import Any

from jobfinder.domain.matching import company_identity
from jobfinder.infrastructure.interview_research import load_coding_curriculum, load_interview_research
from jobfinder.infrastructure.storage import db


COMPANY_FAMILIES = {
    "amazon": "Amazon / AWS", "amazonlab126": "Amazon / AWS", "amazonmusic": "Amazon / AWS",
    "amazonwebservicesaws": "Amazon / AWS", "nvidia": "NVIDIA", "nvidiaai": "NVIDIA",
    "microsoft": "Microsoft", "microsoftai": "Microsoft",
}


def company_family(name: str) -> str:
    return COMPANY_FAMILIES.get(company_identity(name), name.strip())


def selected_company_families() -> list[str]:
    with db() as conn:
        names = [str(row[0]) for row in conn.execute(
            "SELECT company FROM jobs WHERE actual_saved=1 GROUP BY company_key ORDER BY max(actual_score) DESC, company"
        )]
    return list(dict.fromkeys(company_family(name) for name in names))


def leetcode_research_view() -> dict[str, Any]:
    research = load_interview_research()
    curriculum = load_coding_curriculum()
    selected = selected_company_families()
    selected_keys = {company_identity(name) for name in selected}
    patterns: list[dict[str, Any]] = []
    covered: set[str] = set()
    for raw in research.get("patterns", []):
        if not isinstance(raw, dict):
            continue
        companies = [str(name) for name in raw.get("companies", []) if company_identity(name) in selected_keys]
        if not companies:
            continue
        item = dict(raw)
        item["companies"] = companies
        practice_links: list[dict[str, Any]] = []
        for raw_link in raw.get("practice_links", []):
            if not isinstance(raw_link, dict):
                continue
            link = dict(raw_link)
            fit = str(link.get("research_fit", "")).lower()
            if "corroborated" in fit or "repeated" in fit:
                quality = "Corroborated reports"
            elif "synthesis" in fit:
                quality = "Cross-report synthesis"
            elif "analogue" in fit:
                quality = "Structural analogue"
            else:
                quality = "Single public report"
            link["evidence_quality"] = quality
            practice_links.append(link)
        item["practice_links"] = practice_links
        patterns.append(item)
        covered.update(companies)
    patterns.sort(key=lambda item: (int(item.get("priority", 99)), str(item.get("title", ""))))
    sources = [source for source in research.get("sources", []) if isinstance(source, dict)]
    used_source_ids = {source_id for item in patterns for source_id in item.get("source_ids", [])}
    used_source_ids.update(
        source_id
        for track in curriculum.get("tracks", []) if isinstance(track, dict)
        for section in track.get("sections", []) if isinstance(section, dict)
        for exercise in section.get("exercises", []) if isinstance(exercise, dict)
        for source_id in exercise.get("source_ids", [])
    )
    sources = [source for source in sources if source.get("id") in used_source_ids]
    evidence_quality_summary: dict[str, int] = {}
    for item in patterns:
        for link in item.get("practice_links", []):
            quality = str(link.get("evidence_quality", "Unclassified"))
            evidence_quality_summary[quality] = evidence_quality_summary.get(quality, 0) + 1
    curriculum_tracks: list[dict[str, Any]] = []
    for raw_track in curriculum.get("tracks", []):
        if not isinstance(raw_track, dict):
            continue
        track = dict(raw_track)
        sections: list[dict[str, Any]] = []
        for raw_section in raw_track.get("sections", []):
            if not isinstance(raw_section, dict):
                continue
            section = dict(raw_section)
            exercises: list[dict[str, Any]] = []
            for raw_exercise in raw_section.get("exercises", []):
                if not isinstance(raw_exercise, dict):
                    continue
                exercise = dict(raw_exercise)
                exercise["companies"] = [
                    str(name) for name in raw_exercise.get("companies", [])
                    if company_identity(str(name)) in selected_keys
                ]
                exercises.append(exercise)
            section["exercises"] = exercises
            sections.append(section)
        track["sections"] = sections
        curriculum_tracks.append(track)
    return {
        **research,
        "patterns": patterns,
        "sources": sources,
        "selected_companies": selected,
        "covered_companies": sorted(covered),
        "uncovered_companies": [name for name in selected if name not in covered],
        "coverage_count": len(covered),
        "selected_count": len(selected),
        "evidence_quality_summary": evidence_quality_summary,
        "curriculum": {**curriculum, "tracks": curriculum_tracks},
    }


def interview_expectations_view() -> dict[str, Any]:
    """Build an evidence-backed planning model for Eli's likely interview loop."""
    research = leetcode_research_view()
    pattern_map = {str(item.get("id")): item for item in research["patterns"]}

    def companies_for(*pattern_ids: str) -> list[str]:
        names: list[str] = []
        for pattern_id in pattern_ids:
            names.extend(str(name) for name in pattern_map.get(pattern_id, {}).get("companies", []))
        return list(dict.fromkeys(names))

    algorithm_ids = {"graphs", "hashing-frequency", "arrays-strings-grids", "scheduling-heaps", "dynamic-programming"}
    practical_ids = {"production-coding", "object-machine-coding"}
    depth_ids = {"testing-edge-cases", "concurrency", "networking-binary"}
    official_algorithm_signals = {
        "Amazon / AWS": "Official preparation guidance includes data structures and algorithms",
        "Microsoft": "Official technical-interview guidance includes algorithms and data structures",
    }
    company_formats: list[dict[str, Any]] = []
    for company in research["selected_companies"]:
        company_patterns = [item for item in research["patterns"] if company in item.get("companies", [])]
        algorithm_signals = [item["title"] for item in company_patterns if item.get("id") in algorithm_ids]
        practical_signals = [item["title"] for item in company_patterns if item.get("id") in practical_ids]
        depth_signals = [item["title"] for item in company_patterns if item.get("id") in depth_ids]
        if company in official_algorithm_signals:
            algorithm_signals.insert(0, official_algorithm_signals[company])
        if algorithm_signals and practical_signals:
            format_name, dsa, practical = "Mixed", 50, 50
            reason = "Both algorithm and practical/machine-coding signals appear in the current research."
        elif practical_signals:
            format_name, dsa, practical = "Practical-leaning", 30, 70
            reason = "Practical implementation is evidenced; keep DSA warm until the recruiter confirms it is absent."
        elif algorithm_signals:
            format_name, dsa, practical = "DSA-leaning", 70, 30
            reason = "Algorithm patterns are evidenced; retain one practical session because the loop can still vary by team."
        else:
            format_name, dsa, practical = "Confirm with recruiter", 50, 50
            reason = "The local research does not establish a coding format for this selected company."
        company_formats.append({
            "company": company,
            "format": format_name,
            "dsa": dsa,
            "practical": practical,
            "reason": reason,
            "algorithm_signals": algorithm_signals,
            "practical_signals": practical_signals,
            "depth_signals": depth_signals,
            "evidence_count": len(company_patterns) + (1 if company in official_algorithm_signals else 0),
        })
    format_order = {"Mixed": 0, "Practical-leaning": 1, "DSA-leaning": 2, "Confirm with recruiter": 3}
    company_formats.sort(key=lambda item: (format_order[item["format"]], -item["evidence_count"], item["company"]))
    company_format_summary = {
        format_name: sum(1 for item in company_formats if item["format"] == format_name)
        for format_name in format_order
    }

    return {
        "updated_at": "2026-08-26",
        "scope": (
            "A planning model for Senior and Staff backend, platform, infrastructure, SRE, data-platform, "
            "distributed-systems, and applied-AI roles. Exact sequencing varies by company and team."
        ),
        "selected_count": research["selected_count"],
        "evidence_coverage_count": research["coverage_count"],
        "selected_companies": research["selected_companies"],
        "company_formats": company_formats,
        "company_format_summary": company_format_summary,
        "practice_allocation": {
            "headline": "Use 50/50 only inside coding—not across the whole interview",
            "explanation": (
                "Until the recruiter confirms the loop, split coding time evenly between algorithms and practical "
                "implementation. Across total preparation, coding is about 40%; system design, experience stories, "
                "and role depth decide a large part of a Senior/Staff outcome."
            ),
            "coding_split": [
                {"label": "Algorithms / DSA", "percent": 50, "detail": "Graphs, hashing, windows, heaps, and targeted DP."},
                {"label": "Practical coding", "percent": 50, "detail": "Runnable Python, APIs, state, testing, debugging, and concurrency."},
            ],
            "weekly_split": [
                {"label": "Coding", "percent": 40, "detail": "20% DSA + 20% practical"},
                {"label": "System design", "percent": 25, "detail": "Backend/platform architecture"},
                {"label": "Behavioral + project depth", "percent": 20, "detail": "Ownership, incidents, influence"},
                {"label": "Domain + company", "percent": 10, "detail": "Role-specific technical depth"},
                {"label": "Process + recovery", "percent": 5, "detail": "Recruiter alignment and rest"},
            ],
            "adjustments": [
                {"trigger": "Recruiter confirms DSA-only coding", "dsa": 70, "practical": 30, "note": "Keep one practical session weekly so production fluency does not decay."},
                {"trigger": "Recruiter confirms practical/machine coding", "dsa": 30, "practical": 70, "note": "Keep graph/hash warm-ups; spend most time writing and testing complete code."},
                {"trigger": "Recruiter says mixed or is vague", "dsa": 50, "practical": 50, "note": "Stay balanced and ask what each coding round evaluates."},
            ],
        },
        "practice_sessions": [
            {
                "title": "Algorithm session", "duration": "50 minutes", "frequency": "2× weekly",
                "steps": ["5 min: name the pattern and invariant", "30 min: solve one unseen medium", "10 min: test and fix", "5 min: explain complexity and one follow-up"],
                "rule": "Do not watch a solution before the 30-minute attempt. If stuck, take one hint, finish, and repeat the problem 48 hours later.",
            },
            {
                "title": "Practical coding session", "duration": "75–90 minutes", "frequency": "2× weekly",
                "steps": ["10 min: clarify and write acceptance criteria", "45–55 min: build runnable Python", "15 min: tests and failure handling", "10 min: refactor and explain tradeoffs"],
                "rule": "Stop at the card's Done-when boundary. Interview practice rewards a finished, tested slice—not an ambitious unfinished project.",
            },
            {
                "title": "System-design session", "duration": "60 minutes", "frequency": "1× weekly",
                "steps": ["5 min: requirements and scale", "10 min: API and data model", "25 min: components and data flow", "15 min: failures, operations, and cost", "5 min: summary and tradeoffs"],
                "rule": "Speak and draw as if an interviewer is present. Silent diagramming does not practice the actual round.",
            },
            {
                "title": "Experience-story session", "duration": "45 minutes", "frequency": "1× weekly",
                "steps": ["Pick 2 target competencies", "Tell each story in 3–4 minutes", "Add metrics and your decisions", "Answer two adversarial follow-ups"],
                "rule": "Use your real projects. Senior/Staff evidence needs scope, alternatives, influence, failure, and measurable results.",
            },
        ],
        "weekly_plan": [
            {"day": "Mon", "focus": "Algorithms", "work": "One graph/hash medium + verbal follow-up", "minutes": 50},
            {"day": "Tue", "focus": "Practical coding", "work": "One curated Python implementation slice", "minutes": 90},
            {"day": "Wed", "focus": "System design", "work": "One backend/platform design aloud", "minutes": 60},
            {"day": "Thu", "focus": "Algorithms + stories", "work": "One medium, then two project stories", "minutes": 90},
            {"day": "Fri", "focus": "Practical coding", "work": "Timed build, tests, and 10-minute retrospective", "minutes": 90},
            {"day": "Sat", "focus": "Mini loop", "work": "Coding + design + behavioral with short breaks", "minutes": 150},
            {"day": "Sun", "focus": "Review or rest", "work": "Re-solve one miss; otherwise recover", "minutes": 30},
        ],
        "readiness_gates": [
            {"area": "Algorithms", "ready": "Solve an unseen relevant medium in 35 minutes, test it, and answer one follow-up without rescue."},
            {"area": "Practical coding", "ready": "Finish a scoped Python component in 75 minutes with clean boundaries, tests, and explicit failure handling."},
            {"area": "System design", "ready": "Drive a 45-minute design from requirements through scale, data, failures, observability, and cost."},
            {"area": "Behavioral", "ready": "Deliver 8 distinct stories in 3–4 minutes each with decisions, metrics, mistakes, and learning."},
            {"area": "Full loop", "ready": "Complete a coding, design, and behavioral mini-loop in one sitting and identify no more than two repeat weaknesses."},
        ],
        "phases": [
            {
                "number": 1, "title": "Recruiter alignment", "duration": "Usually 25–45 min",
                "format": "Conversation",
                "expect": "Level, role fit, location, compensation range, work authorization, motivation, and process logistics.",
                "your_goal": "Give a crisp Senior-to-Staff backend/platform narrative and leave with the exact round map.",
            },
            {
                "number": 2, "title": "Technical screen", "duration": "Usually 45–90 min",
                "format": "Live coding or assessment",
                "expect": "One or two problems. The format may be DSA, practical implementation/debugging, or a combination. Expect follow-ups, tests, and complexity discussion.",
                "your_goal": "Clarify first, explain the plan, write runnable code, test it, and narrate tradeoffs without filling every second with speech.",
            },
            {
                "number": 3, "title": "Main interview loop", "duration": "Often 3–6 rounds",
                "format": "Virtual onsite or split sessions",
                "expect": "A mix of coding, system design, project or architecture depth, behavioral evidence, and a hiring-manager or role-specific conversation.",
                "your_goal": "Show repeatable Senior/Staff judgment: ownership, scope, reliability, influence, and hands-on technical depth—not just a correct algorithm.",
            },
            {
                "number": 4, "title": "Debrief and decision", "duration": "Company-dependent",
                "format": "Internal evaluation, then recruiter follow-up",
                "expect": "Interviewers submit independent evidence, then the company calibrates role fit and level. Some companies add references or a final executive conversation.",
                "your_goal": "Send concise follow-ups, record every question while fresh, and keep other applications moving until there is a written offer.",
            },
        ],
        "rounds": [
            {
                "id": "algorithms", "title": "Coding and algorithms", "likelihood": "Very likely", "rounds": "Often 1–2 rounds",
                "expect": "Arrays, strings, graphs, hashing, heaps, or DP with extensions and edge cases.",
                "strong": "A correct, runnable solution plus clear reasoning, complexity, tests, and response to hints.",
                "companies": companies_for("graphs", "hashing-frequency", "arrays-strings-grids", "scheduling-heaps", "dynamic-programming"),
            },
            {
                "id": "practical", "title": "Practical or machine coding", "likelihood": "Likely", "rounds": "Often 1 round",
                "expect": "Build, extend, or debug a small component using realistic requirements, APIs, state, and failure modes.",
                "strong": "Clean boundaries, executable code, explicit assumptions, production failure handling, and sensible tests.",
                "companies": companies_for("production-coding", "object-machine-coding"),
            },
            {
                "id": "design", "title": "System design", "likelihood": "Very likely", "rounds": "Usually 1 round",
                "expect": "Design a service or platform from requirements through data model, APIs, scale, reliability, operations, and cost.",
                "strong": "Drive the conversation, quantify scale, expose tradeoffs, handle failures, and connect decisions to experience.",
                "companies": [name for name in research["selected_companies"] if name in {"Amazon / AWS", "Microsoft", "Anthropic", "Uber", "Databricks", "MongoDB", "Cloudflare"}],
            },
            {
                "id": "experience", "title": "Experience and behavioral depth", "likelihood": "Almost certain", "rounds": "Usually 1–2 rounds",
                "expect": "Projects, incidents, disagreement, leadership, mentoring, ambiguity, failure, and measurable impact.",
                "strong": "Specific stories with your decisions, alternatives, metrics, mistakes, and what changed afterward.",
                "companies": [name for name in research["selected_companies"] if name in {"Amazon / AWS", "Microsoft", "Anthropic", "Google", "NVIDIA", "Uber"}],
            },
            {
                "id": "domain", "title": "Role-specific technical depth", "likelihood": "Possible", "rounds": "Zero or 1 round",
                "expect": "Concurrency, networking, database internals, reliability, AI-platform architecture, or another domain from the role.",
                "strong": "Ground answers in systems you operated, including failure modes, observability, migrations, and tradeoffs.",
                "companies": companies_for("concurrency", "networking-binary"),
            },
        ],
        "technical_pacing": [
            {"minutes": "0–5", "title": "Clarify", "action": "Restate the problem, ask about inputs and constraints, and work one example."},
            {"minutes": "5–10", "title": "Plan", "action": "Describe the data structure and algorithm, alternatives, complexity, and tricky invariants."},
            {"minutes": "10–35", "title": "Implement", "action": "Write runnable code in small steps. Keep names and boundaries clear; check in when assumptions change."},
            {"minutes": "35–45+", "title": "Test and extend", "action": "Run normal and edge cases, fix defects, state complexity, then handle the interviewer’s follow-up."},
        ],
        "recruiter_questions": [
            "How many coding rounds are there, and are they algorithms, practical coding, debugging, or a mix?",
            "Which language and interview tool will I use? Can I run tests and consult documentation?",
            "Is system design high-level architecture, low-level design, or both?",
            "What competency is assigned to each round, and is there a role-specific domain interview?",
            "Is the role level fixed before the loop, or calibrated from interview performance?",
            "Will the interviews run in one day or be split, and how long is each round?",
        ],
        "sources": [
            {
                "company": "Amazon / AWS", "label": "Amazon SDE II interview preparation",
                "url": "https://amazon.jobs/content/en/how-we-hire/sde-ii-interview-prep",
                "note": "Example: online coding/design assessment, four 55-minute loop interviews, at least one system-design question, runnable and tested code.",
            },
            {
                "company": "Microsoft", "label": "Microsoft technical interviewing",
                "url": "https://careers.microsoft.com/v2/global/en/hiring-tips/technical-interviewing.html",
                "note": "Example: 45-minute technical rounds emphasizing problem solving, design, compiled code, tests, algorithms, and data structures.",
            },
            {
                "company": "Anthropic", "label": "Anthropic careers: how we hire",
                "url": "https://www.anthropic.com/careers",
                "note": "Example: Google Meet interviews, live coding in Colab or CodeSignal, documentation lookup allowed, plus experience and motivation questions.",
            },
        ],
    }
