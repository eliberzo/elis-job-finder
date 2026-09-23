"""Explainable job-ranking engine and its independently testable rule groups."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import re
from typing import Any

from jobfinder.domain.company import company_identity
from jobfinder.domain.eligibility import requires_security_clearance, requires_us_citizenship
from jobfinder.domain.locations import austin_commute_place, is_austin_commutable_location, is_austin_proper_location, is_explicitly_non_us_location


MATCH_LABELS = {
    "Python": ("python",), "Kafka / events": ("kafka", "event-driven", "event driven", "streaming"),
    "Distributed systems": ("distributed system",), "Microservices": ("microservice",),
    "Postgres / SQL": ("postgres", "sql"), "Cloud": ("gcp", "google cloud", "aws", "azure", "cloud"),
    "Observability": ("observability", "reliability", "sre", "monitoring"),
    "Technical leadership": ("technical leadership", "tech lead", "mentor", "architecture"),
}
ROLE_PENALTIES = (
    ("front-end-heavy", ("frontend", "front-end", "ui engineer"), 2.8, True),
    ("specialized ML/research", ("machine learning researcher", "research scientist", "computer vision"), 3.0, True),
    ("embedded/C++ specialization", ("embedded", "firmware", "c++"), 2.4, True),
    ("principal-level overreach", ("principal", "distinguished", "fellow"), 3.5, True),
    ("executive engineering role", ("director of engineering", "vp engineering"), 3.5, True),
)
BACKEND_TERMS = ("backend", "back-end", "platform", "distributed", "api", "microservice")
SENIOR_TERMS = (
    "senior", "sr.", "sr ", "staff", "mts 1", "mts 2",
    "software engineer ii", "software engineer iii", "software engineer 2", "software engineer 3",
    "engineer ii", "engineer iii", "engineer 2", "engineer 3",
    "technical lead", "tech lead", "lead software engineer",
    "engineering manager", "software development manager", "manager, software engineering",
)
APPLIED_AI_TERMS = (
    "generative ai", "genai", "large language model", "llm", "ai-powered", "ai powered",
    "artificial intelligence", "machine learning platform", "ai application", "agentic", "langgraph",
)


def clamp(value: float) -> float:
    return round(max(0, min(10, value)), 1)


def infer_work_arrangement(job: dict[str, Any]) -> str:
    location, title = str(job.get("location", "")).lower(), str(job.get("title", "")).lower()
    opening = title + " " + str(job.get("description", ""))[:1800].lower()
    phrases = ("location: remote", "fully remote", "mostly remote", "remote position", "work remotely", "100% remote", "remote-first", "remote first", "completely remote")
    return "remote" if "remote" in location or "remote" in title or any(x in opening for x in phrases) else str(job.get("work_arrangement") or "unknown")


def posting_recency(date_posted: Any, today: date | None = None) -> tuple[int | None, float]:
    if not date_posted:
        return None, 2.0
    try:
        evaluation_date = today or datetime.now(timezone.utc).date()
        age = max(0, (evaluation_date - datetime.fromisoformat(str(date_posted)[:10]).date()).days)
    except (ValueError, TypeError):
        return None, 2.0
    return age, 10.0 if age <= 1 else 9.0 if age <= 3 else 8.0 if age <= 7 else 4.0 if age <= 14 else 1.0 if age <= 30 else 0.0


def has_austin_presence_evidence(job: dict[str, Any]) -> bool:
    text = str(job.get("description", "")).lower()
    for match in re.finditer(r"austin(?:,?\s+tx|,?\s+texas)?", text):
        context = text[max(0, match.start() - 180):match.end() + 180]
        if any(signal in context for signal in ("office", "headquarter", "engineering hub", "based in", "available locations", "in-person in")):
            return True
    return False


@dataclass(frozen=True)
class RuleResult:
    rule: str
    points: float
    explanation: str

    def as_dict(self) -> dict[str, str | float]:
        return {"rule": self.rule, "points": round(self.points, 2), "explanation": self.explanation}


@dataclass(frozen=True)
class JobSignals:
    job: dict[str, Any]
    text: str
    title: str
    location: str
    company: str
    resume: str
    arrangement: str
    age_days: int | None
    recency: float
    matches: list[str]
    backend: bool
    senior: bool
    full_stack: bool
    clearance_ineligible: bool
    citizenship_ineligible: bool
    commute_place: dict[str, str] | None


class RankingEngine:
    """Ranks jobs using explicit fit, practice, strategic-cost, and application rules."""

    def __init__(self, profile: dict[str, Any], protected: set[str], market_signals: dict[str, dict[str, int]] | None = None, today: date | None = None):
        self.profile = profile
        self.protected = {company_identity(name) for name in protected}
        self.market_signals = market_signals or {}
        self.today = today

    def rank(self, job: dict[str, Any]) -> dict[str, Any]:
        ctx, source_concerns = self._signals(job)
        fit, fit_rules, fit_concerns = self._fit_score(ctx)
        practice, practice_rules = self._practice_score(ctx)
        burn, is_protected, strategy_rules, strategy_concerns = self._strategic_cost(ctx)
        total = self._combined_practice_score(ctx, fit, practice, burn, is_protected)
        actual, ai_application, application_rules, application_concerns = self._application_score(ctx, fit)
        suggested, salary_concerns = self._suggested_salary(ctx)
        reason, actual_reason = self._explanations(ctx, fit, practice, burn, ai_application)
        concerns = source_concerns + strategy_concerns + fit_concerns + application_concerns + salary_concerns
        breakdown = {
            "fit": [rule.as_dict() for rule in fit_rules],
            "practice": [rule.as_dict() for rule in practice_rules],
            "strategy": [rule.as_dict() for rule in strategy_rules],
            "application": [rule.as_dict() for rule in application_rules],
        }
        return {
            "fit_score": fit, "practice_value": practice, "burn_cost": burn, "recency_score": ctx.recency,
            "age_days": ctx.age_days, "practice_score": total, "reason": reason,
            "actual_score": actual, "ai_application": ai_application, "actual_reason": actual_reason,
            "matches": json.dumps(ctx.matches[:5]), "concerns": json.dumps(list(dict.fromkeys(concerns))[:5]),
            "ranking_breakdown": json.dumps(breakdown),
            "suggested_salary": suggested, "work_arrangement": ctx.arrangement,
        }

    def _signals(self, job: dict[str, Any]) -> tuple[JobSignals, list[str]]:
        text = " ".join(str(job.get(k, "")) for k in ("title", "description", "location")).lower()
        title, location = str(job.get("title", "")).lower(), str(job.get("location", "")).lower()
        raw = job.get("concerns", [])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = [raw] if raw else []
        concerns = [x for x in raw if isinstance(x, str) and x.startswith("Could not fetch public page")]
        resume = (self.profile.get("resume_text", "") + " " + " ".join(self.profile.get("skills", []))).lower()
        matches = [label for label, terms in MATCH_LABELS.items() if any(x in text for x in terms) and any(x in resume for x in terms)]
        age_days, recency = posting_recency(job.get("date_posted"), self.today)
        return JobSignals(
            job, text, title, location, company_identity(job.get("company")), resume,
            infer_work_arrangement(job), age_days, recency, matches,
            any(x in text for x in BACKEND_TERMS), any(x in title for x in SENIOR_TERMS),
            any(x in title for x in ("full stack", "full-stack", "fullstack")) and not any(x in title for x in ("backend", "back-end")),
            requires_security_clearance(text) and self.profile.get("us_citizen") is False,
            requires_us_citizenship(text) and self.profile.get("us_citizen") is False,
            austin_commute_place(location),
        ), concerns

    def _fit_score(self, ctx: JobSignals) -> tuple[float, list[RuleResult], list[str]]:
        concerns: list[str] = []
        skill_points = min(2.8, len(ctx.matches) * .42)
        rules = [RuleResult("baseline", 3.2, "Baseline software-engineering fit")]
        fit = 3.2
        if ctx.senior:
            fit += 1.6; rules.append(RuleResult("senior_alignment", 1.6, "Title matches the target seniority"))
        if ctx.backend:
            fit += 1.7; rules.append(RuleResult("backend_alignment", 1.7, "Role contains backend/platform signals"))
        if skill_points:
            fit += skill_points; rules.append(RuleResult("matching_skills", skill_points, f"Matched {len(ctx.matches)} resume skill groups"))
        if not ctx.senior:
            concerns.append("Seniority alignment is unclear")
        if not ctx.backend:
            fit -= 1.4
            concerns.append("Backend/platform focus is unclear"); rules.append(RuleResult("backend_mismatch", -1.4, "Backend/platform focus is unclear"))
        if ctx.full_stack:
            fit -= 1.8
            concerns.append("Full-stack title is less aligned than a backend-focused role"); rules.append(RuleResult("full_stack_title", -1.8, "Full-stack title is less aligned"))
        for label, terms, penalty, title_only in ROLE_PENALTIES:
            if any(term in (ctx.title if title_only else ctx.text) for term in terms):
                fit -= penalty
                concerns.append(label.capitalize()); rules.append(RuleResult(label, -penalty, f"Role matches the {label} category"))
        if ctx.clearance_ineligible:
            fit -= 4.0
            concerns.append("Security clearance requires U.S. citizenship"); rules.append(RuleResult("clearance_ineligible", -4.0, "Clearance requires U.S. citizenship"))
        if ctx.citizenship_ineligible:
            fit -= 4.0
            concerns.append("U.S. citizenship requirement"); rules.append(RuleResult("citizenship_ineligible", -4.0, "Role requires U.S. citizenship"))
        has_ai_evidence = bool(re.search(r"\b(?:ai|ml|llm)\b|machine learning|deep learning|artificial intelligence|knowledge graph", ctx.resume))
        specialized_ai = any(term in ctx.title for term in ("machine learning", "ml engineer", "llm engineer", "knowledge graph", "computer vision"))
        general_ai = any(term in ctx.title for term in ("ai engineer", "ai/ml engineer", "applied ai"))
        if specialized_ai and not has_ai_evidence:
            fit -= 2.8
            concerns.append("Specialized AI/ML experience is not evidenced in the resume"); rules.append(RuleResult("specialized_ai_gap", -2.8, "Resume lacks evidence for a specialized AI/ML role"))
        elif general_ai and not has_ai_evidence:
            fit -= 1.2
            concerns.append("Applied-AI experience is not evidenced in the resume"); rules.append(RuleResult("applied_ai_gap", -1.2, "Resume lacks evidence for an applied-AI role"))
        language = re.search(r"(?:\(|\b)(java|php|rust|golang|c\+\+|typescript|node\.js)(?:\)|\b)", ctx.title) or re.search(r"(?:deep|expert|advanced|strong|proven)[^.]{0,45}\b(java|php|rust|golang|c\+\+|typescript|node\.js)\b", ctx.text)
        if language and "python" not in ctx.text:
            fit -= 3.0
            concerns.append(f"Primary language mismatch ({language.group(1)})"); rules.append(RuleResult("language_mismatch", -3.0, f"Primary language appears to be {language.group(1)}"))
        years = [int(x) for x in re.findall(r"(\d{1,2})\+?\s+years(?:\s+of)?(?:\s+(?:professional|software|engineering|relevant))?\s+experience", ctx.text)]
        if years and max(years) > 12:
            fit -= .5
            concerns.append(f"Lists {max(years)}+ years"); rules.append(RuleResult("experience_overreach", -.5, f"Posting lists {max(years)}+ years"))
        return clamp(fit), rules, concerns

    def _practice_score(self, ctx: JobSignals) -> tuple[float, list[RuleResult]]:
        rules = [RuleResult("baseline", 4.4, "Baseline interview-practice value")]
        value = 4.4 + (1.3 if ctx.senior else 0) + (1.1 if ctx.backend else 0)
        if ctx.senior: rules.append(RuleResult("senior_loop", 1.3, "Provides senior-level interview practice"))
        if ctx.backend: rules.append(RuleResult("backend_loop", 1.1, "Provides backend/platform interview practice"))
        value += 1 if any(x in ctx.text for x in ("system design", "architecture", "distributed")) else 0
        if any(x in ctx.text for x in ("system design", "architecture", "distributed")): rules.append(RuleResult("system_design", 1.0, "Contains system-design signals"))
        value += .5 if any(x in ctx.text for x in ("coding", "algorithms", "data structures")) else 0
        if any(x in ctx.text for x in ("coding", "algorithms", "data structures")): rules.append(RuleResult("coding_loop", .5, "Contains coding-loop signals"))
        value -= .8 if ctx.full_stack else 0
        if ctx.full_stack: rules.append(RuleResult("full_stack_title", -.8, "Less aligned practice loop"))
        value += .3 if ctx.job.get("easy_apply") else 0
        if ctx.job.get("easy_apply"): rules.append(RuleResult("easy_apply", .3, "Lower-friction practice application"))
        for label, terms, _, title_only in ROLE_PENALTIES:
            if any(x in (ctx.title if title_only else ctx.text) for x in terms):
                value -= 1.5; rules.append(RuleResult(label, -1.5, f"Less useful practice due to {label}"))
        return clamp(value), rules

    def _strategic_cost(self, ctx: JobSignals) -> tuple[float, bool, list[RuleResult], list[str]]:
        concerns: list[str] = []
        rules = [RuleResult("baseline", 1.5, "Default strategic opportunity cost")]
        burn, is_protected = 1.5, ctx.company in self.protected
        signal = next((value for name, value in self.market_signals.items() if ctx.company == company_identity(name)), {})
        austin_jobs, remote_jobs = int(signal.get("austin_jobs", 0)), int(signal.get("remote_jobs", 0))
        austin_presence = austin_jobs > 0 or has_austin_presence_evidence(ctx.job) or is_austin_commutable_location(ctx.location)
        if is_protected:
            burn = 10
            concerns.insert(0, "Protected company"); rules.append(RuleResult("protected_company", 8.5, "Company is reserved for a serious application"))
        if austin_presence:
            previous = burn
            burn = max(burn, 8.5)
            count = max(1, austin_jobs)
            concerns.insert(0, f"Company has Austin presence ({count} local posting{'s' if count != 1 else ''})—protect for an actual application"); rules.append(RuleResult("austin_presence", burn - previous, "Company has Austin-area presence"))
        if is_austin_proper_location(ctx.location):
            burn = max(burn, 8.5)
            concerns.append("Austin-proper opportunity—save for a serious search")
        elif ctx.commute_place:
            burn = max(burn, 8.5)
            concerns.append(f"Austin commute-zone opportunity ({ctx.commute_place['label']}, ~{ctx.commute_place['minutes']} min nominal)—save for a serious search")
        if remote_jobs >= 3:
            previous = burn
            burn = max(burn, 8.0)
            concerns.insert(0, f"Company has {remote_jobs} fully remote postings—protect for an actual application"); rules.append(RuleResult("remote_company", burn - previous, "Company has several fully remote openings"))
        if ctx.arrangement == "remote":
            burn = max(burn, 6.0)
        if ctx.arrangement == "remote" and remote_jobs < 3:
            concerns.append("Remote role; company needs more remote openings before full strategic protection")
        if any(x in ctx.text for x in ("principal", "distinguished", "founding engineer")):
            burn = max(burn, 4.5)
        return round(burn, 1), is_protected, rules, concerns

    def _combined_practice_score(self, ctx: JobSignals, fit: float, practice: float, burn: float, is_protected: bool) -> float:
        effective_hi = ctx.job.get("salary_max") or ctx.job.get("market_compensation")
        bonus = .8 if effective_hi and float(effective_hi) >= 300000 else .6 if effective_hi and float(effective_hi) >= 250000 else .3 if effective_hi and float(effective_hi) >= 200000 else -2.0 if effective_hi else 0.0
        weights = self.profile["weights"]
        ranking_burn = 2.5 if is_protected else burn
        return clamp(fit * weights["fit"] + practice * weights["practice"] - ranking_burn * weights["burn"] + (ctx.recency - 5) * weights.get("recency", .30) + bonus)

    def _application_score(self, ctx: JobSignals, fit: float) -> tuple[float, int, list[RuleResult], list[str]]:
        concerns: list[str] = []
        effective_hi = ctx.job.get("salary_max") or ctx.job.get("market_compensation")
        staff = "staff" in ctx.title and "principal" not in ctx.title
        ai_application = int(any(term in ctx.text for term in APPLIED_AI_TERMS))
        level_points = 1.0 if staff else .65 if ctx.senior else -1.0
        compensation_points = 1.5 if effective_hi and float(effective_hi) >= 300000 else 1.1 if effective_hi and float(effective_hi) >= 240000 else -1.2 if effective_hi and float(effective_hi) >= 200000 else -2.5 if effective_hi else -.5
        geography_points = 1.0 if is_austin_proper_location(ctx.location) else .7 if ctx.commute_place else .8 if ctx.arrangement == "remote" else 0
        actual = fit * .55 + level_points + compensation_points + geography_points + (.7 if ai_application else 0)
        rules = [
            RuleResult("resume_fit", fit * .55, "Weighted resume-fit contribution"),
            RuleResult("level", level_points, "Seniority-level contribution"),
            RuleResult("compensation", compensation_points, "Contribution from posted or market compensation"),
        ]
        if geography_points:
            rules.append(RuleResult("geography", geography_points, "Austin-area or remote-work contribution"))
        if ai_application:
            rules.append(RuleResult("applied_ai", .7, "Role contains applied-AI signals"))
        if ctx.age_days is None:
            freshness_points = -2.5
        elif ctx.age_days <= 7:
            freshness_points = .4
        elif ctx.age_days <= 14:
            freshness_points = -1.8
        elif ctx.age_days <= 30:
            freshness_points = -3.8
        else:
            freshness_points = min(-5.5, 1.5 - actual)
        actual += freshness_points
        rules.append(RuleResult("freshness", freshness_points, "Posting-age contribution"))
        if is_explicitly_non_us_location(ctx.location) or ctx.clearance_ineligible or ctx.citizenship_ineligible:
            rules.append(RuleResult("eligibility_gate", -actual, "Eligibility gate forces the application score to zero"))
            actual = 0
        if len(str(ctx.job.get("description", "")).strip()) < 250:
            rules.append(RuleResult("description_gate", -actual, "Incomplete description forces the application score to zero"))
            actual = 0
            concerns.append("Description incomplete—refresh before ranking")
        normalized = clamp(actual)
        if normalized != actual:
            rules.append(RuleResult("score_normalization", normalized - actual, "Application scores are rounded and constrained to the 0–10 range"))
        return normalized, ai_application, rules, concerns

    def _suggested_salary(self, ctx: JobSignals) -> tuple[int | None, list[str]]:
        lo, hi = ctx.job.get("salary_min"), ctx.job.get("salary_max")
        suggested = round(((float(lo) * .35 + float(hi) * .65) if lo and hi else float(self.profile["compensation_fallback"])) / 5000) * 5000
        if ctx.job.get("salary_type") == "total":
            return None, ["Compensation is total/ambiguous—review before answering"]
        return suggested, []

    def _explanations(self, ctx: JobSignals, fit: float, practice: float, burn: float, ai_application: int) -> tuple[str, str]:
        lo, hi, market = ctx.job.get("salary_min"), ctx.job.get("salary_max"), ctx.job.get("market_compensation")
        good = ", ".join(ctx.matches[:3]) or "general software engineering"
        freshness = "fresh listing" if ctx.age_days is not None and ctx.age_days <= 7 else "older listing" if ctx.age_days is not None and ctx.age_days > 14 else "posting age unclear"
        reason = f"{'Strong' if fit >= 7 else 'Plausible' if fit >= 5 else 'Weak'} {good} match; {'useful Senior loop' if practice >= 6.5 else 'limited practice signal'}; {freshness}; {'low strategic cost' if burn <= 3 else 'high-value opportunity—consider saving for actual'}."
        freshness_reason = "fresh (7 days or less)" if ctx.age_days is not None and ctx.age_days <= 7 else "aging (8–14 days)" if ctx.age_days is not None and ctx.age_days <= 14 else "stale (15–30 days)" if ctx.age_days is not None and ctx.age_days <= 30 else "very stale (over 30 days)" if ctx.age_days is not None else "posting date unknown"
        compensation_reason = "posted compensation meets $240k target" if hi and float(hi) >= 240000 else "posted compensation below $240k target" if hi else "market compensation meets $240k target" if market and float(market) >= 240000 else "market compensation below $240k target" if market else "compensation unknown"
        geography = "outside the U.S. target market" if is_explicitly_non_us_location(ctx.location) else "Austin proper" if is_austin_proper_location(ctx.location) else f"Austin commute zone ({ctx.commute_place['label']}, ~{ctx.commute_place['minutes']} min nominal)" if ctx.commute_place else "remote from Austin" if ctx.arrangement == "remote" else "no Austin/remote bonus"
        level = "Staff-level" if "staff" in ctx.title and "principal" not in ctx.title else "Senior-level" if ctx.senior else "Seniority mismatch"
        actual_reason = "Description incomplete; refresh before ranking." if len(str(ctx.job.get("description", "")).strip()) < 250 else "Security clearance requires U.S. citizenship; the saved profile is ineligible." if ctx.clearance_ineligible else "Role explicitly requires U.S. citizenship; the saved profile is ineligible." if ctx.citizenship_ineligible else f"{level}; {compensation_reason}; {'applied-AI relevance' if ai_application else 'no clear applied-AI signal'}; {geography}; {freshness_reason}."
        return reason, actual_reason
