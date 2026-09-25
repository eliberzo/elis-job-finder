"""Work-authorization and citizenship requirement detection for Eli's search."""
from __future__ import annotations

from typing import Any


def requires_security_clearance(text: Any) -> bool:
    value = str(text or "").casefold()
    waiver = any(term in value for term in (
        "no security clearance required",
        "security clearance is not required",
        "does not require a security clearance",
    ))
    return not waiver and any(term in value for term in (
        "security clearance", "ts/sci", "top secret clearance",
        "secret clearance", "polygraph clearance",
    ))


def requires_us_citizenship(text: Any) -> bool:
    value = str(text or "").casefold()
    permanent_resident_allowed = any(term in value for term in (
        "citizen or permanent resident", "citizen or lawful permanent resident",
        "citizen or us permanent resident", "citizen or u.s. permanent resident",
        "citizens or permanent residents", "citizens or lawful permanent residents",
        "citizen or green card", "citizens or green card holders",
        "u.s. citizen, lawful permanent resident", "us citizen, lawful permanent resident",
        "u.s. citizens, lawful permanent residents", "us citizens, lawful permanent residents",
    ))
    if permanent_resident_allowed:
        return False
    return any(term in value for term in (
        "u.s. citizenship is required", "u.s. citizenship required",
        "us citizenship is required", "us citizenship required",
        "requires u.s. citizenship", "requires us citizenship",
        "must be a u.s. citizen", "must be an u.s. citizen",
        "must be us citizen", "u.s. citizens only", "only u.s. citizens",
        "must be a citizen of the united states", "united states citizenship required",
    ))
