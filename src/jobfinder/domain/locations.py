"""Location classification shared by collection and ranking."""
from __future__ import annotations
import re
from typing import Any


# Nominal, non-rush-hour ranges from central Austin. This is deliberately a
# conservative allowlist for job-search protection, not a promise about a
# specific commute. Traffic, the exact office, and Eli's starting point vary.
AUSTIN_COMMUTE_PLACES = {
    "austin": {"label": "Austin", "minutes": "0–20", "tier": "proper"},
    "rollingwood": {"label": "Rollingwood", "minutes": "10–20", "tier": "core"},
    "west lake hills": {"label": "West Lake Hills", "minutes": "10–20", "tier": "core"},
    "sunset valley": {"label": "Sunset Valley", "minutes": "10–20", "tier": "core"},
    "del valle": {"label": "Del Valle", "minutes": "15–25", "tier": "core"},
    "wells branch": {"label": "Wells Branch", "minutes": "15–25", "tier": "core"},
    "pflugerville": {"label": "Pflugerville", "minutes": "20–30", "tier": "nearby"},
    "manor": {"label": "Manor", "minutes": "20–30", "tier": "nearby"},
    "round rock": {"label": "Round Rock", "minutes": "20–35", "tier": "nearby"},
    "cedar park": {"label": "Cedar Park", "minutes": "25–35", "tier": "nearby"},
    "bee cave": {"label": "Bee Cave", "minutes": "25–35", "tier": "nearby"},
    "buda": {"label": "Buda", "minutes": "25–35", "tier": "nearby"},
    "creedmoor": {"label": "Creedmoor", "minutes": "25–35", "tier": "nearby"},
    "mustang ridge": {"label": "Mustang Ridge", "minutes": "25–35", "tier": "nearby"},
    "lakeway": {"label": "Lakeway", "minutes": "30–40", "tier": "commute"},
    "leander": {"label": "Leander", "minutes": "30–40", "tier": "commute"},
    "hutto": {"label": "Hutto", "minutes": "30–40", "tier": "commute"},
    "kyle": {"label": "Kyle", "minutes": "30–40", "tier": "commute"},
    "webberville": {"label": "Webberville", "minutes": "30–40", "tier": "commute"},
    "dripping springs": {"label": "Dripping Springs", "minutes": "35–45", "tier": "edge"},
    "georgetown": {"label": "Georgetown", "minutes": "35–45", "tier": "edge"},
    "elgin": {"label": "Elgin", "minutes": "35–45", "tier": "edge"},
    "bastrop": {"label": "Bastrop", "minutes": "35–45", "tier": "edge"},
    "lockhart": {"label": "Lockhart", "minutes": "40–45", "tier": "edge"},
}


def austin_commute_place(location: Any) -> dict[str, str] | None:
    """Return the matched Austin-area place and nominal drive-time range."""
    value = re.sub(r"\s+", " ", str(location or "").strip().casefold())
    if "metropolitan" in value:
        return None
    segments = re.split(r"\s*(?:/|;|\||•)\s*", value)
    for segment in segments:
        for city, details in AUSTIN_COMMUTE_PLACES.items():
            city_pattern = re.escape(city).replace(r"\ ", r"\s+")
            city_first = rf"{city_pattern}(?:[\s,-]+(?:tx|texas))?(?:[\s,-]+(?:us|usa|united states(?: of america)?))?(?:\s*\([^)]*\))?"
            country_first = rf"(?:us|usa|united states(?: of america)?)[\s,-]+(?:tx|texas)[\s,-]+{city_pattern}(?:\s*\([^)]*\))?"
            country_city_first = rf"(?:us|usa|united states(?: of america)?)[\s,-]+{city_pattern}[\s,-]+(?:tx|texas)(?:\s*\([^)]*\))?"
            if re.fullmatch(rf"(?:{city_first}|{country_first}|{country_city_first})", segment.strip()):
                return dict(details)
    return None


def is_austin_commutable_location(location: Any) -> bool:
    return austin_commute_place(location) is not None


def is_austin_proper_location(location: Any) -> bool:
    value = re.sub(r"\s+", " ", str(location or "").strip().lower())
    if "metropolitan" in value:
        return False
    segments = re.split(r"\s*(?:/|;|\||•)\s*", value)
    # Austin-proper reporting is intentionally stricter than commute matching:
    # the source must name Texas rather than leaving the city/state ambiguous.
    austin_first = r"austin[\s,-]+(?:tx|texas)(?:[\s,-]+(?:us|usa|united states(?: of america)?))?(?:\s*\([^)]*\))?"
    country_first = r"(?:us|usa|united states(?: of america)?)[\s,-]+(?:tx|texas)[\s,-]+austin(?:\s*\([^)]*\))?"
    country_city_first = r"(?:us|usa|united states(?: of america)?)[\s,-]+austin[\s,-]+(?:tx|texas)(?:\s*\([^)]*\))?"
    explicit_city = r"(?:^|[,–—-]\s*)austin\s*,\s*(?:tx|texas)(?:\s*,?\s*(?:us|usa|united states(?: of america)?))?(?:$|\s|,)"
    return any(
        bool(re.fullmatch(f"(?:{austin_first}|{country_first}|{country_city_first})", segment.strip()))
        or bool(re.search(explicit_city, segment.strip()))
        for segment in segments
    )


FOREIGN_LOCATION_MARKERS = (
    "canada", "ontario", "toronto", "vancouver", "montreal",
    "ireland", "dublin", "india", "bengaluru", "bangalore", "hyderabad",
    "ukraine", "mexico", "spain", "barcelona", "united kingdom", "england",
    "scotland", "wales", "northern ireland", "london, uk", "london, england",
    "germany", "france", "poland", "romania", "brazil", "australia", "japan",
    "serbia", "belgrade", "netherlands", "sweden", "costa rica", "denmark",
    "norway", "finland", "belgium", "switzerland", "austria", "italy",
    "portugal", "israel", "tel aviv", "gurugram", "gurgaon", "singapore",
    "taiwan", "taipei", "hong kong", "south korea", "new zealand", "qatar",
    "united arab emirates", "uae", "south africa", "sydney", "melbourne",
    "saudi arabia", "riyadh", "cork",
)


def is_explicitly_non_us_location(location: Any) -> bool:
    """Return true only for an explicit foreign location; unknown remains eligible."""
    value = re.sub(r"\s+", " ", str(location or "").strip().casefold())
    # Do not confuse U.S. place names with countries embedded in them.
    foreign_scan = re.sub(r"\bnew mexico\b|\bnew england\b", "", value)
    if any(re.search(rf"(?<![a-z]){re.escape(marker)}(?![a-z])", foreign_scan) for marker in FOREIGN_LOCATION_MARKERS):
        return True
    # Short country codes need token boundaries so values such as "UK" are
    # recognized without misclassifying words that merely contain those letters.
    return bool(re.search(r"(?:^|[\s,(;/|])(?:uk|gb)(?:$|[\s,);/|])", value))
