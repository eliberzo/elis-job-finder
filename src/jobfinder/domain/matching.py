"""Pure resume matching, scoring, and ranking rules."""
from __future__ import annotations
import re
from typing import Any

from jobfinder.domain.ranking import (
    RankingEngine,
    company_identity,
    has_austin_presence_evidence,
    infer_work_arrangement,
    posting_recency,
)

SKILL_TERMS = {
    "Python": ["python"], "Java": ["java"], "Go": ["golang", "go language"], "C++": ["c++"],
    "JavaScript": ["javascript"], "TypeScript": ["typescript"], "Kafka": ["kafka"],
    "Event-driven systems": ["event-driven", "event driven"], "Distributed systems": ["distributed system", "distributed systems"],
    "Microservices": ["microservice", "microservices"], "PostgreSQL": ["postgresql", "postgres"], "SQL": ["sql"],
    "GCP": ["gcp", "google cloud"], "AWS": ["aws", "amazon web services"], "Azure": ["azure"],
    "Kubernetes": ["kubernetes", "k8s"], "Docker": ["docker"], "Observability": ["observability"],
    "Reliability / SRE": ["reliability", "site reliability", "sre"], "System design": ["system design"],
    "API design": ["api design", "rest api", "rest apis", "graphql"], "Redis": ["redis"],
    "NoSQL": ["nosql", "dynamodb", "cassandra", "mongodb"], "Data pipelines": ["data pipeline", "data pipelines", "etl"],
    "Leadership": ["leadership", "technical leadership", "tech lead", "managed a team", "mentor", "mentoring"],
    "Machine learning": ["machine learning", "deep learning"], "React": ["react.js", "reactjs", "react"],
    "LLM deployment": ["deploying llms", "production llms", "llm deployment"],
    "RAG": ["rag pipeline", "rag pipelines", "retrieval-augmented generation"],
    "Prompt engineering": ["prompt engineering"],
    "AI agents": ["agent-based systems", "agentic ai", "ai agents"],
}

def detect_skills(text: str) -> list[str]:
    haystack = text.casefold()
    return [
        skill for skill, terms in SKILL_TERMS.items()
        if any(re.search(rf"(?<![a-z0-9+#]){re.escape(term.casefold())}(?![a-z0-9+#])", haystack) for term in terms)
    ]

def score(job: dict[str, Any], profile: dict[str, Any], protected: set[str], market_signals: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    """Compatibility entry point for callers that do not need a reusable engine."""
    return RankingEngine(profile, protected, market_signals).rank(job)
