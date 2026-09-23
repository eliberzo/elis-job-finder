"""Canonical company and job-title identities shared across app layers."""
from __future__ import annotations

import re
from typing import Any


COMPANY_ALIASES = {
    "amazonlab126": "amazon",
    "amazonmusic": "amazon",
    "amazonwebservices": "amazon",
    "amazonwebservicesaws": "amazon",
    "aws": "amazon",
    # Eagle Eye Networks merged into Brivo in 2026 and now shares one careers
    # portal, product organization, and application surface.
    "brivoeagleeyenetworks": "brivo",
    "eagleeyenetworks": "brivo",
    # SecuredTouch is an acquired Ping Identity product/team name. LinkedIn
    # syndicates both labels for the same Greenhouse requisitions.
    "securedtouch": "pingidentity",
    "securedtouchacquiredbypingidentity": "pingidentity",
    # TrendAI is Trend Micro's enterprise AI-security business unit and its
    # canonical roles are hosted on Trend Micro's Workday tenant.
    "trendmicro": "trendai",
    "trendaienterprisebusinessunitoftrendmicro": "trendai",
    # EA's syndication label includes its ticker-style abbreviation, while
    # the employer portal uses the full company name.
    "electronicartsea": "electronicarts",
    "acrisureinnovation": "acrisure",
    "assaabloygroup": "assaabloy",
    "procoretechnologies": "procore",
}

TITLE_ALIASES = {
    # Same webAI requisition was syndicated with these modifiers reversed.
    "seniorplatformrustengineer": "seniorrustplatformengineer",
    # Ping's syndicated title appends the product area to the shorter employer
    # title even though the description and requisition are identical.
    "staffsoftwareengineerdataengineeringidentityaiagentgovernance": "staffsoftwareengineerdataengineering",
}


def company_identity(name: Any) -> str:
    value = re.sub(
        r"\b(incorporated|inc|llc|ltd|limited|corporation|corp)\b\.?",
        "",
        str(name or "").casefold(),
    )
    normalized = re.sub(r"[^a-z0-9]", "", value)
    return COMPANY_ALIASES.get(normalized, normalized)


def title_identity(title: Any) -> str:
    """Normalize harmless seniority punctuation for official-source deduping."""
    normalized = re.sub(r"\bsr\.?\b", "senior", str(title or "").casefold())
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    return TITLE_ALIASES.get(compact, compact)
