"""Resume-quality review rules, separate from collection and job scoring."""
from __future__ import annotations

from collections import Counter
import re
from typing import Any, Iterable

from jobfinder.domain.matching import detect_skills


def _demand(demand: Counter[str], skill: str) -> int:
    return int(demand.get(skill, 0))


def review_resume(resume_text: str, jobs: Iterable[Any], demand: Counter[str]) -> dict[str, Any]:
    """Evaluate positioning and evidence for the selected target-job cohort.

    This intentionally assesses only what is explicit in the current resume. User-
    confirmed experience belongs in the rewrite plan until a revised PDF exists.
    """
    text = resume_text or ""
    lower = text.lower()
    job_rows = list(jobs)
    ai_roles = sum(
        bool(re.search(r"\b(ai|artificial intelligence|machine learning|llm|generative ai|genai)\b",
                       f"{row['title']} {row['description']}", re.I))
        for row in job_rows
    )
    quantified_patterns = re.findall(
        r"(?:\$\s?\d[\d,.]*[KMB]?\+?|\b\d+(?:\.\d+)?%|\b(?:million|billion)s?\b|"
        r"~?\b\d[\d,]*\+?\s+(?:engineers|employees|incidents|reviews|services|systems|teams|calls|orders|seconds?|s\b))",
        text,
        re.I,
    )
    leadership_signals = sum(lower.count(term) for term in (
        "lead system designer", "technical lead", "led a team", "led a core team", "managed a team",
        "owned", "roadmap", "architecture", "mentor", "cross-team", "platform standards",
    ))
    ai_evidence = bool(re.search(r"\b(ai|artificial intelligence|machine learning|llm|generative ai|genai)\b|agent-orchestration", lower))
    explicit_staff_title = bool(re.search(r"\b(staff|principal)\b", lower))
    explicit_senior_title = bool(re.search(r"\bsenior\b", lower))
    resume_skills = set(detect_skills(text))
    top_demand = demand.most_common(12)
    demand_total = sum(count for _, count in top_demand)
    covered_total = sum(count for skill, count in top_demand if skill in resume_skills)
    skill_coverage = round(covered_total / demand_total * 100) if demand_total else 0
    missing_skills = [(skill, count) for skill, count in top_demand if skill not in resume_skills]
    staff_score = 9 if leadership_signals >= 8 else 8 if leadership_signals >= 5 else 6
    quantified_count = len(set(match.casefold() for match in quantified_patterns))

    dimensions = [
        {
            "name": "Backend positioning", "score": 9,
            "assessment": "Strong",
            "evidence": "The headline, summary, and recent work consistently establish backend, distributed-systems, and platform depth.",
        },
        {
            "name": "Quantified impact", "score": min(10, 5 + quantified_count),
            "assessment": "Strong" if quantified_count >= 5 else "Needs more proof",
            "evidence": f"{quantified_count} measurable scale or outcome signals are visible across financial automation, latency, reliability, business impact, and team scope.",
        },
        {
            "name": "Staff-level scope", "score": staff_score,
            "assessment": "Strong staff-adjacent evidence" if staff_score >= 8 else "Credible, but undersold",
            "evidence": f"The resume contains {leadership_signals} leadership and ownership signals; show cross-team scope and measurable outcomes to support Staff-level applications.",
        },
        {
            "name": "AI application relevance", "score": 7 if ai_evidence else 2,
            "assessment": "Visible" if ai_evidence else "Missing from the document",
            "evidence": (
                f"{ai_roles} selected target roles contain AI or ML language, and the resume now shows agent-orchestration in production delivery."
                if ai_evidence else f"{ai_roles} selected target roles contain AI or ML language, while the current resume does not show applied-AI delivery."
            ),
        },
        {
            "name": "Target-title alignment", "score": 9 if explicit_staff_title else 8 if explicit_senior_title and staff_score >= 8 else 6,
            "assessment": "Strong" if explicit_staff_title else "Strong Senior; Staff scope is inferential",
            "evidence": "Use a target headline supported by the experience, while accurately preserving held titles.",
        },
        {
            "name": "Selected-role ATS coverage", "score": min(10, 5 + round(skill_coverage / 20)),
            "assessment": "Strong" if skill_coverage >= 75 else "Good foundation, targeted gaps remain",
            "evidence": f"The resume covers {skill_coverage}% of weighted demand across the twelve most common skills in the selected target cohort.",
        },
    ]

    recommendations = []
    if missing_skills:
        gap_text = ", ".join(f"{skill} ({count} roles)" for skill, count in missing_skills[:4])
        recommendations.append({
            "priority": "P0", "title": "Close only evidence-backed selected-role gaps",
            "why": f"The most common terms not explicit in the resume are {gap_text}.",
            "action": "If your career evidence supports them, add the relevant terms to Core Skills and prove each important one in an accomplishment bullet. Do not add a keyword solely because a target job requests it.",
        })
    if ai_roles and not ai_evidence:
        recommendations.append({
            "priority": "P0", "title": "Add one credible applied-AI proof point",
            "why": f"AI language appears in {ai_roles} selected target roles.",
            "action": "Add a production AI-enabled workflow with your exact contribution, reliability controls, and a defensible outcome. Do not imply ML research experience.",
        })
    elif ai_evidence:
        recommendations.append({
            "priority": "P1", "title": "Keep AI orchestration concrete",
            "why": f"AI or ML language appears in {ai_roles} selected roles, and your standalone orchestration bullet is relevant without positioning you as an ML researcher.",
            "action": "Keep any orchestration claim concrete. Add a productivity or cycle-time result only if you can defend the measurement.",
        })
    recommendations.extend([
        {
            "priority": "P1", "title": "Preserve the strongest production-impact examples",
            "why": "Selected roles value production ownership, quantified impact, team leadership, and cross-team standards.",
            "action": "Keep the strongest evidence-backed bullets prominent instead of replacing them with lower-scope implementation detail.",
        },
        {
            "priority": "P1", "title": "Keep projected scale explicitly future-facing",
            "why": "Projected future scale should not read as achieved throughput.",
            "action": "Retain language such as 'expected to scale' or 'projected to scale' so the bullet stays ambitious and interview-defensible.",
        },
        {
            "priority": "P2", "title": "Preserve the one-page hierarchy",
            "why": "Selected roles reward recent platform scope, production ownership, and cross-team influence more than additional detail from older work.",
            "action": "Keep the single-column one-page format and add new content only by replacing a weaker bullet.",
        },
    ])

    headline = (
        "Strong fit for selected Senior backend/platform roles, with credible Staff-adjacent scope; the remaining gaps are mostly stack-specific rather than leadership or impact gaps."
        if staff_score >= 8 else
        "Strong Senior backend resume; make cross-team scope and selected-role technical coverage more explicit."
    )

    return {
        "dimensions": dimensions,
        "recommendations": recommendations,
        "headline": headline,
        "word_count": len(re.findall(r"\b\w+\b", text)),
        "quantified_outcomes": quantified_count,
        "ai_roles": ai_roles,
        "target_skill_coverage": skill_coverage,
    }
