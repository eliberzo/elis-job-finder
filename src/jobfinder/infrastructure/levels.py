"""Small, attributed Levels.fyi salary benchmark bank for strategic companies."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import subprocess
import time
from typing import Any

from jobfinder.config import LEVELS_BANK_PATH
from jobfinder.domain.matching import company_identity


TARGETS = {
    "AMD": ("amd", []),
    "Affirm": ("affirm", []),
    "Meta": ("meta", ["Facebook"]),
    "Amazon": ("amazon", ["Amazon Web Services", "AWS", "Amazon Lab126", "Lab126", "Amazon Music"]),
    "Apple": ("apple", []),
    "Bumble": ("bumble", ["Bumble Inc."]),
    "Cloudflare": ("cloudflare", []),
    "CrowdStrike": ("crowdstrike", []),
    "eBay": ("ebay", []),
    "Netflix": ("netflix", []),
    "Google": ("google", ["Alphabet", "Google DeepMind", "DeepMind"]),
    "Microsoft": ("microsoft", []),
    "Nvidia": ("nvidia", ["NVIDIA", "NVIDIA AI"]),
    "MongoDB": ("mongodb", []),
    "Oracle": ("oracle", []),
    "Pinterest": ("pinterest", []),
    "Plaid": ("plaid", []),
    "realtor.com": ("realtorcom", ["Realtor.com"]),
    "Reddit": ("reddit", ["Reddit, Inc."]),
    "Roblox": ("roblox", []),
    "Snap": ("snap", ["Snap Inc.", "Snapchat"]),
    "Walmart": ("walmart", []),
    "OpenAI": ("openai", []),
    "Anthropic": ("anthropic", []),
    "xAI": ("xai", []),
    "Databricks": ("databricks", []),
    "Scale AI": ("scale-ai", []),
    "CoreWeave": ("coreweave", []),
    "Perplexity": ("perplexity-ai", ["Perplexity AI"]),
    "Cohere": ("cohere", []),
    "Mistral AI": ("mistral-ai", []),
    "Hugging Face": ("hugging-face", []),
    "Cerebras Systems": ("cerebras-systems", []),
    "Groq": ("groq", []),
    "Waymo": ("waymo", []),
    "Tesla": ("tesla", []),
    "Palantir": ("palantir", []),
    "Snowflake": ("snowflake", []),
}

# Public Levels.fyi pages whose agent-readable Markdown currently returns no
# parseable body. Keep the last verified U.S. level values attributed here so
# the local text bank remains complete and auditable.
CURATED_BENCHMARKS = {
    "Bumble": {
        "company": "Bumble", "company_key": "bumble", "aliases": ["Bumble Inc."],
        "role": "Software Engineer", "location": "United States", "currency": "USD",
        "median_total_comp": 136500, "senior_level": "L4 Senior Software Engineer",
        "senior_total_comp": 268083, "staff_total_comp": None, "levels": [],
        "source": "Levels.fyi", "source_url": "https://www.levels.fyi/companies/bumble/salaries/software-engineer/locations/united-states",
        "source_updated": "July 29, 2026", "fetched_at": "2026-08-26T00:00:00+00:00",
        "note": "Crowdsourced U.S. annual total compensation; not a posted salary range.",
    },
    "realtor.com": {
        "company": "realtor.com", "company_key": "realtorcom", "aliases": ["Realtor.com"],
        "role": "Software Engineer", "location": "United States", "currency": "USD",
        "median_total_comp": 165000, "senior_level": "T3 Senior Software Engineer",
        "senior_total_comp": 204171, "staff_total_comp": 223294, "levels": [],
        "source": "Levels.fyi", "source_url": "https://www.levels.fyi/companies/realtorcom/salaries/software-engineer",
        "source_updated": "August 22, 2026", "fetched_at": "2026-08-26T00:00:00+00:00",
        "note": "Crowdsourced U.S. annual total compensation; not a posted salary range.",
    },
}


def _dollars(value: str | None) -> int | None:
    if not value: return None
    clean = value.replace("$", "").replace(",", "").strip().upper()
    multiplier = 1_000_000 if clean.endswith("M") else 1_000 if clean.endswith("K") else 1
    try: return round(float(clean.rstrip("KM")) * multiplier)
    except ValueError: return None


def _fetch_target(company: str, slug: str, aliases: list[str]) -> dict[str, Any] | None:
    source_url = f"https://www.levels.fyi/companies/{slug}/salaries/software-engineer"
    try:
        response = subprocess.run(["curl", "-fsS", "--max-time", "20", source_url + ".md"], check=True, capture_output=True, text=True)
        markdown = response.stdout[:2_000_000]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    median_match = re.search(r"Median Total Compensation:\s*\$([\d,.]+\s*[KM]?)", markdown, re.I)
    updated_match = re.search(r"Last Updated:\s*([^\n]+)", markdown, re.I)
    levels = []
    for level, amount in re.findall(r"^\|\s*([^|]+?)\s*\|\s*\$([\d,.]+\s*[KM]?)\s*\|", markdown, re.M):
        if level.strip().lower() != "level": levels.append({"level": level.strip(), "total_comp": _dollars(amount)})
    senior_match = re.search(r"A Senior Software Engineer at .*? is level\s+([^,\.]+).*?Median total compensation.*?\$([\d,.]+\s*[KM]?)", markdown, re.I | re.S)
    staff_level = next((item for item in levels if "staff" in item["level"].casefold() and "senior staff" not in item["level"].casefold()), None)
    return {
        "company": company,
        "company_key": company_identity(company),
        "aliases": aliases,
        "role": "Software Engineer",
        "location": "United States",
        "currency": "USD",
        "median_total_comp": _dollars(median_match.group(1)) if median_match else None,
        "senior_level": senior_match.group(1).strip() if senior_match else None,
        "senior_total_comp": _dollars(senior_match.group(2)) if senior_match else None,
        "staff_total_comp": staff_level.get("total_comp") if staff_level else None,
        "levels": levels,
        "source": "Levels.fyi",
        "source_url": source_url,
        "source_updated": updated_match.group(1).strip() if updated_match else None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "note": "Crowdsourced annual total compensation (base + annualized stock + bonus); not a posted base-salary range.",
    }


def download_salary_bank() -> dict[str, Any]:
    existing = {**CURATED_BENCHMARKS, **{item["company"]: item for item in load_salary_bank()}}
    records, missing = [], []
    # Levels.fyi publishes agent-readable Markdown. Fetch gently and sequentially
    # so the local refresh does not trip its public endpoint's rate limiter.
    for company, (slug, aliases) in TARGETS.items():
        record = _fetch_target(company, slug, aliases)
        if record and (record["median_total_comp"] or record["levels"]):
            existing[company] = record
        else:
            missing.append(company)
        time.sleep(.35)
    records = sorted(existing.values(), key=lambda item: item["company"].casefold())
    if records:
        LEVELS_BANK_PATH.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records))
    return {"saved": len(records), "missing": sorted(missing), "path": str(LEVELS_BANK_PATH)}


def load_salary_bank() -> list[dict[str, Any]]:
    if not LEVELS_BANK_PATH.exists(): return []
    return [json.loads(line) for line in LEVELS_BANK_PATH.read_text().splitlines() if line.strip()]


def salary_benchmark_map() -> dict[str, dict[str, Any]]:
    result = {}
    for record in load_salary_bank():
        for name in [record["company"], *record.get("aliases", [])]: result[company_identity(name)] = record
    family_aliases = {
        "amazonwebservicesaws": "amazon", "amazonlab126": "amazon", "amazonmusic": "amazon",
        "microsoftai": "microsoft", "nvidiaai": "nvidia", "bumble": "bumble",
        "snap": "snap", "snapchat": "snap", "reddit": "reddit", "realtorcom": "realtorcom",
    }
    for alias, parent in family_aliases.items():
        if parent in result: result[alias] = result[parent]
    return result


if __name__ == "__main__":
    print(json.dumps(download_salary_bank(), indent=2))
