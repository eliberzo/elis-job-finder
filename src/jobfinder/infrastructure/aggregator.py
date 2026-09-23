"""Public job collection and extraction adapters. Never uses credentials or bypasses."""
from __future__ import annotations
import html
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

def clean_text(value: Any) -> str:
    if value is None: return ""
    decoded = html.unescape(str(value))
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", decoded))).strip()

def source_name(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    return host.split(".")[0] or "manual"

def extract_salary(text: str, data: dict | None = None) -> dict[str, Any]:
    salary_text, lo, hi, salary_type = "", None, None, "unknown"
    if data:
        base = data.get("baseSalary") or {}; val = base.get("value") if isinstance(base, dict) else {}
        if isinstance(val, dict):
            lo, hi, unit = val.get("minValue"), val.get("maxValue"), str(val.get("unitText", "")).upper()
            if unit in ("HOUR", "HOURLY"):
                lo = float(lo)*2080 if lo else None; hi = float(hi)*2080 if hi else None
            salary_type = "base"
    annual_suffix = r"(?:\s*/\s*(?:yr|year)|\s+per\s+(?:yr|year))?"
    currency_suffix = r"(?:\s*\.?\s*(?:USD|US\s+dollars?))?"
    pattern = re.compile(r"\$\s*(\d{2,6})(?:[,.](\d{3}))?(?:\.\d{2})?\s*[kK]?" + currency_suffix + annual_suffix + r"\s*(?:-|–|—|to)\s*\$?\s*(\d{2,6})(?:[,.](\d{3}))?(?:\.\d{2})?\s*[kK]?" + currency_suffix + annual_suffix, re.I)
    match = pattern.search(text)
    if not match:
        pattern = re.compile(r"(?:base\s+pay\s+range|salary\s+range|pay\s+range)\s*:?\s*\$?\s*(\d{2,6})(?:[,.](\d{3}))?(?:\.\d{2})?\s*[kK]?" + currency_suffix + annual_suffix + r"\s*(?:-|–|—|to)\s*\$?\s*(\d{2,6})(?:[,.](\d{3}))?(?:\.\d{2})?\s*[kK]?" + currency_suffix + annual_suffix, re.I)
        match = pattern.search(text)
    if not match:
        # Some employers phrase the disclosed range as "between $X and $Y"
        # rather than using a dash. Requiring "between" keeps unrelated dollar
        # amounts joined by prose from being mistaken for one range.
        pattern = re.compile(r"\bbetween\s+\$\s*(\d{2,6})(?:[,.](\d{3}))?(?:\.\d{2})?\s*[kK]?" + annual_suffix + r"\s+and\s+\$?\s*(\d{2,6})(?:[,.](\d{3}))?(?:\.\d{2})?\s*[kK]?" + annual_suffix, re.I)
        match = pattern.search(text)
    if match:
        def money(a: str, b: str | None) -> float:
            n = float(a + (b or "")); return n*1000 if not b and n < 1000 else n
        salary_text, lo, hi = match.group(0).strip(), lo or money(match.group(1), match.group(2)), hi or money(match.group(3), match.group(4))
        nearby = text[max(0, match.start()-50):match.end()+80].lower()
        if re.search(r"(?:/|per\s+)(?:hr|hour)\b", nearby):
            hourly_values = re.findall(r"\d{1,3}(?:\.\d{1,2})?", match.group(0).replace(",", ""))
            if len(hourly_values) >= 2:
                lo, hi = float(hourly_values[0]) * 2080, float(hourly_values[1]) * 2080
                salary_text = f"{salary_text} (annualized)"
                salary_type = "base"
        else:
            # Classify from the matched range and its leading label. A second
            # OTE range that follows a base-pay range must not relabel the first.
            leading = text[max(0, match.start()-100):match.start()].lower()
            matched_text = match.group(0).lower()
            following = text[match.end():match.end()+400].lower()
            total_labeled = bool(re.search(r"(?:total\s+comp(?:ensation)?|\bote\b)", f"{leading} {matched_text}"))
            base_labeled = "base" in leading or "base" in matched_text or bool(re.search(
                r"\bbase\s+salary\s+range\b[^.]{0,80}\b(?:posted|shown|listed)\s+above\b",
                following,
            )) or bool(re.search(r"\bbase\s+salary\s+(?:is\s+)?determined\b", following))
            salary_type = "total" if total_labeled else "base" if base_labeled else salary_type
    return {"salary_text": salary_text, "salary_min": lo, "salary_max": hi, "salary_type": salary_type}


def format_salary_range(salary_min: Any, salary_max: Any) -> str:
    """Render structured employer pay when the source omits a display string."""
    try:
        lo = float(salary_min) if salary_min is not None else None
        hi = float(salary_max) if salary_max is not None else None
    except (TypeError, ValueError):
        return ""
    if lo is not None and hi is not None:
        return f"${lo:,.0f} - ${hi:,.0f}"
    if hi is not None:
        return f"Up to ${hi:,.0f}"
    if lo is not None:
        return f"From ${lo:,.0f}"
    return ""

def fetch_job(url: str) -> dict[str, Any]:
    result = {"url": url, "source": source_name(url), "company": "", "title": "", "location": "", "description": "", "date_posted": None, "easy_apply": 0, "work_arrangement": "unknown"}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PracticeJobFinder/1.0", "Accept": "text/html,application/xhtml+xml"})
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(2_500_000).decode(response.headers.get_content_charset() or "utf-8", "replace")
        objects = []
        for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
            try:
                import json
                obj = json.loads(html.unescape(block)); objects.extend(obj if isinstance(obj, list) else [obj])
            except Exception: pass
        job = next((x for x in objects if isinstance(x, dict) and (x.get("@type") == "JobPosting" or "JobPosting" in (x.get("@type") or []))), {})
        if job:
            org, loc = job.get("hiringOrganization") or {}, job.get("jobLocation") or job.get("applicantLocationRequirements") or {}
            if isinstance(loc, list): loc = loc[0] if loc else {}
            addr = loc.get("address", loc) if isinstance(loc, dict) else {}
            location = addr if isinstance(addr, str) else ", ".join(str(addr.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry") if addr.get(k))
            result.update(company=clean_text(org.get("name") if isinstance(org, dict) else org), title=clean_text(job.get("title")),
                location=clean_text(location), description=clean_text(job.get("description")), date_posted=job.get("datePosted"))
            employment = str(job.get("jobLocationType", "")).lower()
            result["work_arrangement"] = "remote" if "telecommute" in employment or "remote" in result["location"].lower() else "onsite"
            result.update(extract_salary(result["description"], job))
        else:
            title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
            desc = re.search(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\'](.*?)["\']', raw, re.I | re.S)
            result["title"], result["description"] = clean_text(title.group(1) if title else "")[:240], clean_text(desc.group(1) if desc else "")
            result.update(extract_salary(clean_text(raw)))
        result["easy_apply"] = int("easy apply" in raw.lower())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        result["concerns"] = [f"Could not fetch public page: {type(exc).__name__}; edit details after import"]
    return result

def normalize_item(item: Any) -> dict[str, Any]:
    if isinstance(item, str): return fetch_job(item.strip())
    if not isinstance(item, dict): raise ValueError("Each job must be a URL or object")
    url = str(item.get("url") or item.get("job_url") or item.get("link") or "").strip()
    if not url: raise ValueError("Job is missing url")
    fetched = fetch_job(url) if not item.get("description") else {"url": url, "source": source_name(url)}
    aliases = {"job_title": "title", "city": "location", "job_description": "description", "posted": "date_posted"}
    for key, value in item.items(): fetched[aliases.get(key, key)] = value
    salary = extract_salary(str(fetched.get("salary_text", "")) + " " + str(fetched.get("description", "")))
    for key, value in salary.items():
        if value in (None, "") or (key == "salary_type" and value == "unknown"): continue
        if fetched.get(key) in (None, "", "unknown"): fetched[key] = value
    if not fetched.get("salary_text"):
        fetched["salary_text"] = format_salary_range(fetched.get("salary_min"), fetched.get("salary_max"))
    return fetched

def linkedin_search(keywords: str, locations: list[str], days: int, limit: int, work_types: str = "1,3") -> tuple[list[dict[str, Any]], list[str]]:
    results, errors, seen = [], [], set(); seconds = max(1, min(days, 30))*86400
    per_location = max(1, math.ceil(limit / len(locations)))
    for location in locations:
        try:
            found = 0
            for start in range(0, per_location, 25):
                params = urllib.parse.urlencode({"keywords": keywords, "location": location, "f_TPR": f"r{seconds}", "f_WT": work_types, "sortBy": "DD", "start": start})
                endpoint = "https://www.linkedin.com/jobs/search/?" if start == 0 else "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                req = urllib.request.Request(endpoint + params, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"})
                with urllib.request.urlopen(req, timeout=15) as response: raw = response.read(4_000_000).decode(response.headers.get_content_charset() or "utf-8", "replace")
                lower = raw.lower()
                if any(x in lower for x in ("let's do a quick security check", "complete this security verification", "unusual activity from your account")):
                    errors.append(f"{location}: LinkedIn requested verification; collection stopped"); break
                page_found = 0
                cards = re.findall(r"<li[^>]*>(.*?</li>)", raw, re.I | re.S)
                for card in cards:
                    link = re.search(r'href=["\'](https://(?:www\.)?linkedin\.com/jobs/view/[^"\']+)', card, re.I)
                    if not link: continue
                    url = html.unescape(link.group(1)).split("?")[0]
                    if url in seen: continue
                    title = re.search(r'<h3[^>]*class=["\'][^"\']*base-search-card__title[^"\']*["\'][^>]*>(.*?)</h3>', card, re.I | re.S)
                    company = re.search(r'<h4[^>]*class=["\'][^"\']*base-search-card__subtitle[^"\']*["\'][^>]*>(.*?)</h4>', card, re.I | re.S)
                    city = re.search(r'<span[^>]*class=["\'][^"\']*job-search-card__location[^"\']*["\'][^>]*>(.*?)</span>', card, re.I | re.S)
                    posted = re.search(r'<time[^>]*datetime=["\']([^"\']+)', card, re.I)
                    if not title: continue
                    result_location = clean_text(city.group(1)) if city else location
                    arrangement = "remote" if work_types == "2" or "remote" in result_location.lower() else "onsite/hybrid"
                    seen.add(url); found += 1; page_found += 1
                    results.append({"url": url, "source": "linkedin", "title": clean_text(title.group(1)), "company": clean_text(company.group(1)) if company else "", "location": result_location, "date_posted": posted.group(1) if posted else None, "work_arrangement": arrangement, "_search_market": location})
                    if found >= per_location: break
                if found >= per_location or page_found == 0: break
                time.sleep(.6)
            if found == 0: errors.append(f"{location}: no public result cards were returned")
            time.sleep(.6)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc: errors.append(f"{location}: {type(exc).__name__}")
    buckets = [[x for x in results if x.get("_search_market") == location] for location in locations]
    return [bucket[i] for i in range(per_location) for bucket in buckets if i < len(bucket)][:limit], errors
