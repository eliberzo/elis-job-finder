"""Raw collection use-case. Deliberately independent of resume matching and scoring."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
import re
import time
from threading import Lock, Thread
from typing import Any

from jobfinder.domain.locations import is_austin_proper_location
from jobfinder.domain.relevance import posting_is_relevant, title_is_candidate
from jobfinder.infrastructure.aggregator import clean_text, linkedin_search, normalize_item
from jobfinder.infrastructure.providers import ADOBE_AUSTIN_BOARD, AMD_AUSTIN_BOARD, AMAZON_AUSTIN_BOARD, APPLE_AUSTIN_BOARD, ARM_AUSTIN_BOARD, ASHBY_BOARDS, BAIN_JOBS_API, BITDEER_CAREERS_BASE, CAPITAL_ONE_AUSTIN_BOARD, CELESTICA_AUSTIN_BOARD, CIRCLE_AUSTIN_BOARD, CISCO_AUSTIN_BOARD, CVS_AUSTIN_BOARD, DELL_CAREERS_BASE, DELOITTE_AUSTIN_BOARD, EXACTA_AUSTIN_BOARD, EY_SEARCH_BASE, GOOGLE_AUSTIN_BOARD, GREENHOUSE_BOARDS, HHSC_SEARCH_BASE, HOME_DEPOT_JOBS_API, IBM_AUSTIN_BOARD, JIBE_SITES, JPMORGAN_CAREERS_BASE, KPMG_JOBS_API, LEVER_BOARDS, LPL_AUSTIN_BOARD, MASTERCARD_AUSTIN_BOARD, META_AUSTIN_BOARD, MICROSOFT_CAREERS_BASE, MPHASIS_RIPPLEHIRE_BOARD, ORACLE_CAREERS_BASE, PAYPAL_CAREERS_BASE, PHENOM_SITES, PROCORE_AUSTIN_ENGINEERING_BOARD, PWC_AUSTIN_BOARD, QUALCOMM_CAREERS_BASE, REALTOR_CAREERS_BASE, RESIDEO_JOBS_API, RIPPLING_CAREERS_BASE, ROKU_AUSTIN_BOARD, RWE_AUSTIN_BOARD, SALESFORCE_JOBS_FEED, SCHWAB_AUSTIN_BOARD, SNOWFLAKE_ASHBY_BOARD, SUCCESSFACTORS_SITES, TCS_IBEGIN_BOARD, TEAMVIEWER_AUSTIN_BOARD, TEMPORAL_CAREERS_BOARD, WESTERN_UNION_AUSTIN_URLS, WORKABLE_BOARDS, WORKDAY_SITES, adobe_austin_jobs, amd_austin_jobs, amazon_austin_jobs, apple_austin_jobs, arm_austin_jobs, ashby_company_jobs, bain_austin_jobs, bitdeer_austin_jobs, capitalone_austin_jobs, celestica_austin_jobs, circle_austin_jobs, cisco_austin_jobs, cvs_austin_jobs, dell_austin_jobs, deloitte_austin_jobs, exacta_austin_jobs, ey_austin_jobs, google_austin_jobs, greenhouse_company_jobs, hhsc_austin_jobs, homedepot_austin_jobs, ibm_austin_jobs, jibe_company_jobs, jpmorgan_austin_jobs, kpmg_austin_jobs, lever_company_jobs, lpl_austin_jobs, mastercard_austin_jobs, meta_austin_jobs, microsoft_austin_jobs, mphasis_company_jobs, oracle_austin_jobs, paypal_austin_jobs, phenom_company_jobs, procore_austin_jobs, pwc_austin_jobs, qualcomm_austin_jobs, realtor_austin_jobs, resideo_austin_jobs, rippling_austin_jobs, roku_austin_jobs, rwe_austin_jobs, salesforce_austin_jobs, schwab_austin_jobs, snowflake_austin_jobs, successfactors_company_jobs, tcs_austin_jobs, teamviewer_austin_jobs, temporal_austin_jobs, western_union_austin_jobs, workable_company_jobs, workday_company_jobs
from jobfinder.infrastructure.providers import PALOALTO_AUSTIN_BOARD, paloalto_austin_jobs
from jobfinder.infrastructure.providers import PAYLOCITY_SITES, PINPOINT_SITES, paylocity_company_jobs, pinpoint_company_jobs
from jobfinder.infrastructure.providers import REVOLUTPEOPLE_SITES, revolutpeople_company_jobs
from jobfinder.infrastructure.providers import AVIONTE_BOARDS, avionte_company_jobs
from jobfinder.infrastructure.providers import ICIMS_SITES, RIPPLING_ATS_TENANTS, RIPPLING_LEGACY_SITES, SMARTRECRUITERS_COMPANIES, icims_company_jobs, rippling_legacy_company_jobs, rippling_tenant_company_jobs, smartrecruiters_company_jobs
from jobfinder.infrastructure.providers import ACCENTURE_AUSTIN_BOARD, accenture_austin_jobs
from jobfinder.infrastructure.providers import JOBVITE_SITES, jobvite_company_jobs
from jobfinder.infrastructure.providers import BAMBOOHR_BOARDS, bamboohr_company_jobs
from jobfinder.infrastructure.providers import PAYCOR_SITES, UKG_LEGACY_BOARDS, paycor_company_jobs, ukg_legacy_company_jobs
from jobfinder.infrastructure.providers import ADP_SITES, EMPLOYER_PAGE_SITES, adp_company_jobs, employer_page_company_jobs
from jobfinder.infrastructure.providers import QUEST_GLOBAL_AUSTIN_BOARD, questglobal_austin_jobs
from jobfinder.infrastructure.storage import OFFICIAL_JOB_SOURCES, company_key, db, title_key, upsert_raw_job


class PostingStartGate:
    """Serialize request starts while allowing response processing to stay parallel."""

    def __init__(self, interval_seconds: float = 2.0, clock=time.monotonic, sleeper=time.sleep):
        self.interval_seconds = max(2.0, float(interval_seconds))
        self.clock = clock
        self.sleeper = sleeper
        self.lock = Lock()
        self.next_start = 0.0

    def wait(self) -> None:
        with self.lock:
            delay = self.next_start - self.clock()
            if delay > 0:
                self.sleeper(delay)
            self.next_start = self.clock() + self.interval_seconds


def dedupe_job_candidates(items: list[dict[str, Any]], existing_urls: set[str], existing_job_keys: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """Keep the first unseen canonical link and company/title identity."""
    seen_urls = {value.strip() for value in existing_urls if value.strip()}
    seen_keys = {(company_key(company), title_key(title)) for company, title in existing_job_keys}
    selected: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url", "")).strip()
        key = (company_key(str(item.get("company", ""))), title_key(str(item.get("title", ""))))
        if not url or not all(key) or url in seen_urls or key in seen_keys:
            continue
        seen_urls.add(url)
        seen_keys.add(key)
        selected.append(item)
    return selected


def posting_is_austin_relevant(item: dict[str, Any]) -> bool:
    """Require exact Austin evidence at the final company-board boundary."""
    return is_austin_proper_location(str(item.get("location", ""))) and posting_is_relevant(item)


def collect_linkedin(data: dict[str, Any]) -> dict[str, Any]:
    """Fetch, normalize, and queue raw records; no profile or rank logic is used."""
    keywords = clean_text(data.get("keywords") or "Senior Backend Engineer")
    locations = [clean_text(value) for value in re.split(r"[;\n]+", str(data.get("locations") or "")) if clean_text(value)]
    if not locations: raise ValueError("Enter at least one target city")
    if not any(is_austin_proper_location(value) for value in locations): locations.append("Austin, TX")
    limit = max(1, min(int(data.get("limit", 300)), 350))
    days = max(1, min(int(data.get("days", 7)), 30))
    items, errors = linkedin_search(keywords, locations, days, min(limit * 2, 700), work_types="1,3")
    if data.get("include_remote", True):
        remote_items, remote_errors = linkedin_search(keywords, ["United States"], days, min(max(75, limit), 350), work_types="2")
        errors.extend(remote_errors)
        seen_urls = {str(item.get("url")) for item in items}
        items.extend(item for item in remote_items if str(item.get("url")) not in seen_urls)

    title_candidates = [item for item in items if title_is_candidate(item)]
    rejected = len(items) - len(title_candidates)
    with db() as conn:
        existing_urls = {str(row[0]) for row in conn.execute("SELECT url FROM jobs")}
        existing_job_keys = {(str(row[0]), str(row[1])) for row in conn.execute("SELECT company,title FROM jobs")}
    candidates = dedupe_job_candidates(title_candidates, existing_urls, existing_job_keys)
    duplicates_skipped = len(title_candidates) - len(candidates)
    workers = max(1, min(int(data.get("workers", 4)), 4))
    detail_delay_seconds = max(2.0, min(float(data.get("detail_delay_seconds", 2.0)), 30.0))
    detail_gate = PostingStartGate(detail_delay_seconds)

    write_queue: Queue[dict[str, Any] | None] = Queue(maxsize=50)
    writer_stats = {"created": 0, "updated": 0, "accepted": 0, "rejected": 0}
    writer_errors: list[str] = []

    def persist_worker() -> None:
        while True:
            item = write_queue.get()
            try:
                if item is None: return
                if writer_stats["accepted"] >= limit: continue
                if not posting_is_relevant(item):
                    writer_stats["rejected"] += 1
                    continue
                _, is_new = upsert_raw_job(item, sync=False)
                writer_stats["created"] += int(is_new)
                writer_stats["updated"] += int(not is_new)
                writer_stats["accepted"] += 1
            except Exception as exc:
                writer_errors.append(f"{(item or {}).get('title','result')}: {type(exc).__name__}")
            finally:
                write_queue.task_done()

    writer = Thread(target=persist_worker, name="job-persistence", daemon=True)
    writer.start()

    def paced_normalize(item: dict[str, Any]) -> dict[str, Any]:
        detail_gate.wait()
        return normalize_item(item)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job-detail") as pool:
        futures = {pool.submit(paced_normalize, item): item for item in candidates}
        for future in as_completed(futures):
            try: write_queue.put(future.result())
            except Exception as exc: errors.append(f"{futures[future].get('title','result')}: {type(exc).__name__}")
    write_queue.put(None)
    write_queue.join()
    writer.join()
    errors.extend(writer_errors)
    rejected += writer_stats["rejected"]
    with db() as conn:
        total = int(conn.execute("SELECT count(*) FROM jobs").fetchone()[0])
    return {"found": len(items), "candidates": len(candidates), "accepted": writer_stats["accepted"], "rejected": rejected,
            "created": writer_stats["created"], "updated": writer_stats["updated"], "duplicates_skipped": duplicates_skipped,
            "workers": workers, "detail_delay_seconds": detail_delay_seconds, "total": total, "errors": errors}


def round_robin_company_candidates(items: list[dict[str, Any]], limit: int, max_per_company: int) -> list[dict[str, Any]]:
    """Interleave companies so one large ATS board cannot consume the batch."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = str(item.get("company", "")).strip().casefold()
        if key:
            buckets.setdefault(key, []).append(item)
    selected: list[dict[str, Any]] = []
    for position in range(max_per_company):
        for bucket in buckets.values():
            if position < len(bucket):
                selected.append(bucket[position])
                if len(selected) >= limit:
                    return selected
    return selected


def priority_company_keys() -> set[str]:
    """Companies worth a deeper official-site crawl: high match or saved to apply."""
    with db() as conn:
        rows = conn.execute(
            """SELECT company_key FROM jobs GROUP BY company_key
               HAVING MAX(actual_score) > 8 OR MAX(actual_saved) = 1"""
        )
        return {str(row[0]) for row in rows if str(row[0]).strip()}


def _priority_provider_names(mapping: dict[str, str], targets: set[str]) -> set[str]:
    return {name for name in mapping if company_key(name) in targets}


def collect_company_boards(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deep-crawl official sites for high-match and saved-to-apply companies."""
    options = data or {}
    limit = max(1, min(int(options.get("limit", 1000)), 2000))
    apple_pages = max(1, min(int(options.get("apple_pages", 8)), 8))
    targets = priority_company_keys()
    greenhouse_names = _priority_provider_names(GREENHOUSE_BOARDS, targets)
    ashby_names = _priority_provider_names(ASHBY_BOARDS, targets)
    workable_names = _priority_provider_names(WORKABLE_BOARDS, targets)
    lever_names = _priority_provider_names(LEVER_BOARDS, targets)
    phenom_names = _priority_provider_names(PHENOM_SITES, targets)
    # Adobe has a durable exact-Austin query; avoid the older broad US
    # keyword crawl now that the focused adapter covers the requested scope.
    phenom_names.discard("Adobe")
    jibe_names = _priority_provider_names(JIBE_SITES, targets)
    jobvite_names = _priority_provider_names(JOBVITE_SITES, targets)
    workday_names = _priority_provider_names(WORKDAY_SITES, targets)
    paylocity_names = _priority_provider_names(PAYLOCITY_SITES, targets)
    pinpoint_names = _priority_provider_names(PINPOINT_SITES, targets)
    revolutpeople_names = _priority_provider_names(REVOLUTPEOPLE_SITES, targets)
    avionte_names = _priority_provider_names(AVIONTE_BOARDS, targets)
    smartrecruiters_names = _priority_provider_names(SMARTRECRUITERS_COMPANIES, targets)
    icims_names = _priority_provider_names(ICIMS_SITES, targets)
    successfactors_names = _priority_provider_names(SUCCESSFACTORS_SITES, targets)
    bamboohr_names = _priority_provider_names(BAMBOOHR_BOARDS, targets)
    # These curated employer-linked boards are intentionally small. Poll all
    # of them even if a closed mirror temporarily leaves no high-score row.
    paycor_names = set(PAYCOR_SITES)
    ukg_names = set(UKG_LEGACY_BOARDS)
    # Tenant boards are deliberately curated and usually small. Keep polling
    # them even after a stale/closed last role leaves no local row to qualify
    # the company for the score-derived target set.
    rippling_tenant_names = set(RIPPLING_ATS_TENANTS)
    rippling_legacy_names = set(RIPPLING_LEGACY_SITES)
    # These employer-linked inventories are intentionally tiny. Continue
    # polling them after a closed last role leaves no score-derived target.
    adp_names = set(ADP_SITES)
    employer_page_names = set(EMPLOYER_PAGE_SITES)
    adp_items, adp_errors = adp_company_jobs(
        adp_names,
        request_delay_seconds=max(2.0, float(options.get("adp_delay_seconds", 2.0))),
    )
    employer_page_items, employer_page_errors = employer_page_company_jobs(employer_page_names)
    greenhouse_items, errors = greenhouse_company_jobs(greenhouse_names)
    ashby_items, ashby_errors = ashby_company_jobs(ashby_names)
    workable_items, workable_errors = workable_company_jobs(workable_names)
    lever_items, lever_errors = lever_company_jobs(lever_names)
    phenom_items, phenom_errors = phenom_company_jobs(
        phenom_names,
        max_pages=max(1, min(int(options.get("phenom_pages", 20)), 30)),
    )
    adobe_items, adobe_errors = adobe_austin_jobs(
        max_pages=max(1, min(int(options.get("adobe_pages", 2)), 2)),
        request_delay_seconds=max(2.0, float(options.get("adobe_delay_seconds", 2.0))),
    ) if company_key("Adobe") in targets else ([], [])
    questglobal_items, questglobal_errors = questglobal_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("questglobal_delay_seconds", 2.0))),
    ) if company_key("Quest Global") in targets else ([], [])
    circle_items, circle_errors = circle_austin_jobs(
        max_pages=max(1, min(int(options.get("circle_pages", 7)), 10)),
        request_delay_seconds=max(2.0, float(options.get("circle_delay_seconds", 2.0))),
    ) if company_key("Circle") in targets else ([], [])
    jibe_items, jibe_errors = jibe_company_jobs(
        jibe_names,
        max_pages=max(1, min(int(options.get("jibe_pages", 9)), 10)),
        request_delay_seconds=max(2.0, float(options.get("jibe_delay_seconds", 2.0))),
    )
    jobvite_items, jobvite_errors = jobvite_company_jobs(
        jobvite_names,
        request_delay_seconds=max(2.0, float(options.get("jobvite_delay_seconds", 2.0))),
    )
    apple_items, apple_errors = apple_austin_jobs(max_pages=apple_pages) if company_key("Apple") in targets else ([], [])
    amazon_items, amazon_errors = amazon_austin_jobs(
        max_pages=max(1, min(int(options.get("amazon_pages", 8)), 8)),
        request_delay_seconds=max(2.0, float(options.get("amazon_delay_seconds", 2.0))),
    ) if company_key("Amazon") in targets else ([], [])
    amd_items, amd_errors = amd_austin_jobs(
        max_pages=max(1, min(int(options.get("amd_pages", 3)), 3)),
    ) if company_key("AMD") in targets else ([], [])
    arm_items, arm_errors = arm_austin_jobs(
        max_pages=max(1, min(int(options.get("arm_pages", 5)), 5)),
        request_delay_seconds=max(2.0, float(options.get("arm_delay_seconds", 2.0))),
    ) if company_key("Arm") in targets else ([], [])
    capitalone_items, capitalone_errors = capitalone_austin_jobs(
        max_pages=max(1, min(int(options.get("capitalone_pages", 3)), 3)),
        request_delay_seconds=max(2.0, float(options.get("capitalone_delay_seconds", 2.0))),
    ) if company_key("Capital One") in targets else ([], [])
    google_items, google_errors = google_austin_jobs(
        max_pages=max(1, min(int(options.get("google_pages", 3)), 5)),
        request_delay_seconds=max(2.0, float(options.get("google_delay_seconds", 2.0))),
    ) if company_key("Google") in targets else ([], [])
    microsoft_items, microsoft_errors = microsoft_austin_jobs(
        max_pages=max(1, min(int(options.get("microsoft_pages", 4)), 6)),
        request_delay_seconds=max(2.0, float(options.get("microsoft_delay_seconds", 2.0))),
    ) if {company_key("Microsoft"), company_key("Microsoft AI")} & targets else ([], [])
    if company_key("Bain & Company") in targets:
        with db() as conn:
            bain_known_dates = {
                str(row[0]): str(row[1])
                for row in conn.execute(
                    "SELECT title,date_posted FROM jobs WHERE company_key=? AND date_posted IS NOT NULL",
                    (company_key("Bain & Company"),),
                )
            }
        bain_items, bain_errors = bain_austin_jobs(bain_known_dates)
    else:
        bain_items, bain_errors = [], []
    oracle_items, oracle_errors = oracle_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("oracle_delay_seconds", 2.0))),
    ) if company_key("Oracle") in targets else ([], [])
    jpmorgan_items, jpmorgan_errors = jpmorgan_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("jpmorgan_delay_seconds", 2.0))),
    ) if company_key("JPMorganChase") in targets else ([], [])
    dell_items, dell_errors = dell_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("dell_delay_seconds", 2.0))),
    ) if company_key("Dell Technologies") in targets else ([], [])
    procore_items, procore_errors = procore_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("procore_delay_seconds", 2.0))),
    ) if company_key("Procore") in targets else ([], [])
    realtor_items, realtor_errors = realtor_austin_jobs() if company_key("Realtor.com") in targets else ([], [])
    teamviewer_items, teamviewer_errors = teamviewer_austin_jobs() if company_key("TeamViewer") in targets else ([], [])
    schwab_items, schwab_errors = schwab_austin_jobs(
        max_pages=max(1, min(int(options.get("schwab_pages", 9)), 9)),
        request_delay_seconds=max(2.0, float(options.get("schwab_delay_seconds", 2.0))),
    ) if company_key("Charles Schwab") in targets else ([], [])
    deloitte_items, deloitte_errors = deloitte_austin_jobs(
        max_pages=max(1, min(int(options.get("deloitte_pages", 50)), 50)),
        request_delay_seconds=max(2.0, float(options.get("deloitte_delay_seconds", 2.0))),
        search_delay_seconds=max(1.0, float(options.get("deloitte_search_delay_seconds", 1.0))),
    ) if company_key("Deloitte") in targets else ([], [])
    rippling_items, rippling_errors = rippling_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("rippling_delay_seconds", 2.0))),
    ) if company_key("Rippling") in targets else ([], [])
    rippling_tenant_items, rippling_tenant_errors = rippling_tenant_company_jobs(
        rippling_tenant_names,
        request_delay_seconds=max(2.0, float(options.get("rippling_tenant_delay_seconds", 2.0))),
    )
    rippling_legacy_items, rippling_legacy_errors = rippling_legacy_company_jobs(
        rippling_legacy_names,
        request_delay_seconds=max(2.0, float(options.get("rippling_legacy_delay_seconds", 2.0))),
    )
    temporal_items, temporal_errors = temporal_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("temporal_delay_seconds", 2.0))),
    )
    pwc_items, pwc_errors = pwc_austin_jobs(
        max_pages=max(1, min(int(options.get("pwc_pages", 100)), 100)),
        request_delay_seconds=max(2.0, float(options.get("pwc_delay_seconds", 2.0))),
    ) if company_key("PwC") in targets else ([], [])
    paypal_items, paypal_errors = paypal_austin_jobs(
        max_pages=max(1, min(int(options.get("paypal_pages", 3)), 3)),
        request_delay_seconds=max(2.0, float(options.get("paypal_delay_seconds", 2.0))),
    ) if company_key("PayPal") in targets else ([], [])
    paloalto_items, paloalto_errors = paloalto_austin_jobs(
        max_pages=max(1, min(int(options.get("paloalto_pages", 5)), 5)),
        request_delay_seconds=max(2.0, float(options.get("paloalto_delay_seconds", 2.0))),
    )
    qualcomm_items, qualcomm_errors = qualcomm_austin_jobs(
        max_pages=max(1, min(int(options.get("qualcomm_pages", 10)), 12)),
        request_delay_seconds=max(2.0, float(options.get("qualcomm_delay_seconds", 2.0))),
    ) if company_key("Qualcomm") in targets else ([], [])
    salesforce_items, salesforce_errors = salesforce_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("salesforce_delay_seconds", 2.0))),
    ) if company_key("Salesforce") in targets else ([], [])
    meta_items, meta_errors = meta_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("meta_delay_seconds", 2.0))),
    ) if company_key("Meta") in targets else ([], [])
    accenture_items, accenture_errors = accenture_austin_jobs(
        max_pages=max(1, min(int(options.get("accenture_pages", 10)), 10)),
        request_delay_seconds=max(2.0, float(options.get("accenture_delay_seconds", 2.0))),
    ) if company_key("Accenture") in targets else ([], [])
    cisco_items, cisco_errors = cisco_austin_jobs(
        max_pages=max(1, min(int(options.get("cisco_pages", 130)), 130)),
        request_delay_seconds=max(2.0, float(options.get("cisco_delay_seconds", 2.0))),
    ) if company_key("Cisco") in targets else ([], [])
    ibm_items, ibm_errors = ibm_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("ibm_delay_seconds", 2.0))),
    ) if company_key("IBM") in targets else ([], [])
    homedepot_items, homedepot_errors = homedepot_austin_jobs(
        max_pages=max(1, min(int(options.get("homedepot_pages", 2)), 3)),
        request_delay_seconds=max(2.0, float(options.get("homedepot_delay_seconds", 2.0))),
    ) if company_key("The Home Depot") in targets else ([], [])
    snowflake_items, snowflake_errors = snowflake_austin_jobs() if company_key("Snowflake") in targets else ([], [])
    workday_items, workday_errors = workday_company_jobs(
        workday_names,
        max_pages=max(1, min(int(options.get("workday_pages", 10)), 10)),
        request_delay_seconds=max(2.0, float(options.get("workday_delay_seconds", 2.0))),
    )
    cvs_items, cvs_errors = cvs_austin_jobs(
        max_pages=max(1, min(int(options.get("cvs_pages", 24)), 24)),
        request_delay_seconds=max(2.0, float(options.get("cvs_delay_seconds", 2.0))),
    ) if company_key("CVS Health") in targets else ([], [])
    mastercard_items, mastercard_errors = mastercard_austin_jobs(
        max_pages=max(1, min(int(options.get("mastercard_pages", 3)), 6)),
        request_delay_seconds=max(2.0, float(options.get("mastercard_delay_seconds", 2.0))),
    ) if company_key("Mastercard") in targets else ([], [])
    lpl_items, lpl_errors = lpl_austin_jobs(
        max_pages=max(1, min(int(options.get("lpl_pages", 6)), 6)),
        request_delay_seconds=max(2.0, float(options.get("lpl_delay_seconds", 2.0))),
    ) if company_key("LPL Financial") in targets else ([], [])
    roku_items, roku_errors = roku_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("roku_delay_seconds", 2.0))),
    ) if company_key("Roku") in targets else ([], [])
    western_union_items, western_union_errors = western_union_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("western_union_delay_seconds", 2.0))),
    ) if company_key("Western Union") in targets else ([], [])
    resideo_items, resideo_errors = resideo_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("resideo_delay_seconds", 2.0))),
    ) if company_key("Resideo") in targets else ([], [])
    bitdeer_items, bitdeer_errors = bitdeer_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("bitdeer_delay_seconds", 2.0))),
    ) if company_key("Bitdeer (NASDAQ: BTDR)") in targets else ([], [])
    celestica_items, celestica_errors = celestica_austin_jobs(
        max_pages=max(1, min(int(options.get("celestica_pages", 2)), 2)),
        request_delay_seconds=max(2.0, float(options.get("celestica_delay_seconds", 2.0))),
    ) if company_key("Celestica") in targets else ([], [])
    rwe_items, rwe_errors = rwe_austin_jobs(
        max_pages=max(1, min(int(options.get("rwe_pages", 8)), 8)),
        request_delay_seconds=max(2.0, float(options.get("rwe_delay_seconds", 2.0))),
    ) if company_key("RWE") in targets else ([], [])
    exacta_items, exacta_errors = exacta_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("exacta_delay_seconds", 2.0))),
    ) if company_key("Exacta Systems") in targets else ([], [])
    kpmg_items, kpmg_errors = kpmg_austin_jobs(
        max_pages=max(1, min(int(options.get("kpmg_pages", 9)), 9)),
        request_delay_seconds=max(2.0, float(options.get("kpmg_delay_seconds", 2.0))),
    ) if company_key("KPMG US") in targets else ([], [])
    hhsc_items, hhsc_errors = hhsc_austin_jobs(
        request_delay_seconds=max(2.0, float(options.get("hhsc_delay_seconds", 2.0))),
    ) if company_key("Texas Health and Human Services") in targets else ([], [])
    ey_items, ey_errors = ey_austin_jobs(
        max_pages=max(1, min(int(options.get("ey_pages", 4)), 4)),
        request_delay_seconds=max(2.0, float(options.get("ey_delay_seconds", 2.0))),
    ) if company_key("EY") in targets else ([], [])
    revolutpeople_items, revolutpeople_errors = revolutpeople_company_jobs(
        revolutpeople_names,
        request_delay_seconds=max(2.0, float(options.get("revolutpeople_delay_seconds", 2.0))),
    )
    avionte_items, avionte_errors = avionte_company_jobs(
        avionte_names,
        request_delay_seconds=max(2.0, float(options.get("avionte_delay_seconds", 2.0))),
    )
    smartrecruiters_items, smartrecruiters_errors = smartrecruiters_company_jobs(
        smartrecruiters_names,
        max_pages=max(1, min(int(options.get("smartrecruiters_pages", 3)), 5)),
        request_delay_seconds=max(2.0, float(options.get("smartrecruiters_delay_seconds", 2.0))),
    )
    icims_items, icims_errors = icims_company_jobs(
        icims_names,
        max_pages=max(1, min(int(options.get("icims_pages", 3)), 5)),
        request_delay_seconds=max(2.0, float(options.get("icims_delay_seconds", 2.0))),
    )
    successfactors_items, successfactors_errors = successfactors_company_jobs(
        successfactors_names,
        max_pages=max(1, min(int(options.get("successfactors_pages", 2)), 5)),
        request_delay_seconds=max(2.0, float(options.get("successfactors_delay_seconds", 2.0))),
    )
    bamboohr_items, bamboohr_errors = bamboohr_company_jobs(
        bamboohr_names,
        request_delay_seconds=max(2.0, float(options.get("bamboohr_delay_seconds", 2.0))),
    )
    paylocity_items, paylocity_errors = paylocity_company_jobs(
        paylocity_names,
        request_delay_seconds=max(2.0, float(options.get("paylocity_delay_seconds", 2.0))),
    )
    pinpoint_items, pinpoint_errors = pinpoint_company_jobs(pinpoint_names)
    paycor_items, paycor_errors = paycor_company_jobs(
        paycor_names,
        request_delay_seconds=max(2.0, float(options.get("paycor_delay_seconds", 2.0))),
    )
    ukg_items, ukg_errors = ukg_legacy_company_jobs(
        ukg_names,
        request_delay_seconds=max(2.0, float(options.get("ukg_delay_seconds", 2.0))),
    )
    mphasis_items, mphasis_errors = mphasis_company_jobs(
        request_delay_seconds=max(2.0, float(options.get("mphasis_delay_seconds", 2.0))),
    )
    with db() as conn:
        tcs_known_dates = {
            str(row[0]): str(row[1])
            for row in conn.execute(
                "SELECT title,date_posted FROM jobs WHERE company_key=? AND date_posted IS NOT NULL",
                (company_key("Tata Consultancy Services"),),
            )
        }
    tcs_items, tcs_errors = tcs_austin_jobs(
        tcs_known_dates,
        request_delay_seconds=max(2.0, float(options.get("tcs_delay_seconds", 2.0))),
        max_pages=max(1, min(int(options.get("tcs_pages", 10)), 10)),
    )
    items = adp_items + employer_page_items + greenhouse_items + ashby_items + workable_items + lever_items + phenom_items + adobe_items + questglobal_items + circle_items + jibe_items + jobvite_items + apple_items + amazon_items + amd_items + arm_items + capitalone_items + google_items + microsoft_items + bain_items + oracle_items + jpmorgan_items + dell_items + procore_items + realtor_items + teamviewer_items + schwab_items + deloitte_items + rippling_items + rippling_tenant_items + rippling_legacy_items + temporal_items + pwc_items + paypal_items + paloalto_items + qualcomm_items + salesforce_items + meta_items + accenture_items + cisco_items + ibm_items + homedepot_items + snowflake_items + workday_items + cvs_items + mastercard_items + lpl_items + roku_items + western_union_items + resideo_items + bitdeer_items + celestica_items + rwe_items + exacta_items + kpmg_items + hhsc_items + ey_items + revolutpeople_items + avionte_items + smartrecruiters_items + icims_items + successfactors_items + bamboohr_items + paylocity_items + pinpoint_items + paycor_items + ukg_items + mphasis_items + tcs_items
    errors.extend(adp_errors)
    errors.extend(employer_page_errors)
    errors.extend(ashby_errors)
    errors.extend(workable_errors)
    errors.extend(lever_errors)
    errors.extend(phenom_errors)
    errors.extend(adobe_errors)
    errors.extend(questglobal_errors)
    errors.extend(circle_errors)
    errors.extend(jibe_errors)
    errors.extend(jobvite_errors)
    errors.extend(apple_errors)
    errors.extend(amazon_errors)
    errors.extend(amd_errors)
    errors.extend(arm_errors)
    errors.extend(capitalone_errors)
    errors.extend(google_errors)
    errors.extend(microsoft_errors)
    errors.extend(bain_errors)
    errors.extend(oracle_errors)
    errors.extend(jpmorgan_errors)
    errors.extend(dell_errors)
    errors.extend(procore_errors)
    errors.extend(realtor_errors)
    errors.extend(teamviewer_errors)
    errors.extend(schwab_errors)
    errors.extend(deloitte_errors)
    errors.extend(rippling_errors)
    errors.extend(rippling_tenant_errors)
    errors.extend(rippling_legacy_errors)
    errors.extend(temporal_errors)
    errors.extend(pwc_errors)
    errors.extend(paypal_errors)
    errors.extend(paloalto_errors)
    errors.extend(qualcomm_errors)
    errors.extend(salesforce_errors)
    errors.extend(meta_errors)
    errors.extend(accenture_errors)
    errors.extend(cisco_errors)
    errors.extend(ibm_errors)
    errors.extend(homedepot_errors)
    errors.extend(snowflake_errors)
    errors.extend(workday_errors)
    errors.extend(cvs_errors)
    errors.extend(mastercard_errors)
    errors.extend(lpl_errors)
    errors.extend(roku_errors)
    errors.extend(western_union_errors)
    errors.extend(resideo_errors)
    errors.extend(bitdeer_errors)
    errors.extend(celestica_errors)
    errors.extend(rwe_errors)
    errors.extend(exacta_errors)
    errors.extend(kpmg_errors)
    errors.extend(hhsc_errors)
    errors.extend(ey_errors)
    errors.extend(revolutpeople_errors)
    errors.extend(avionte_errors)
    errors.extend(smartrecruiters_errors)
    errors.extend(icims_errors)
    errors.extend(successfactors_errors)
    errors.extend(bamboohr_errors)
    errors.extend(paylocity_errors)
    errors.extend(pinpoint_errors)
    errors.extend(paycor_errors)
    errors.extend(ukg_errors)
    errors.extend(mphasis_errors)
    errors.extend(tcs_errors)
    # Generic ATS collectors intentionally expose their employer's full fresh
    # inventory. Reassert the queue's exact-Austin invariant after all provider
    # results are merged so a broad board can never leak a global role into the
    # local Opportunity Queue.
    relevant = [item for item in items if posting_is_austin_relevant(item)]
    rejected = len(items) - len(relevant)
    with db() as conn:
        existing_urls = {str(row[0]) for row in conn.execute("SELECT url FROM jobs")}
        existing_official_job_keys = {
            (str(row[0]).casefold(), str(row[1]).casefold())
            for row in conn.execute(
                f"SELECT company,title FROM jobs WHERE source IN ({','.join('?' for _ in OFFICIAL_JOB_SOURCES)})",
                tuple(sorted(OFFICIAL_JOB_SOURCES)),
            )
        }
    max_per_company = max(1, min(int(options.get("max_per_company", 25)), 50))
    # A direct ATS posting may replace a matching LinkedIn row with a fresher,
    # canonical company link. Existing official rows remain duplicates.
    eligible = dedupe_job_candidates(relevant, existing_urls, existing_official_job_keys)
    candidates = round_robin_company_candidates(eligible, limit, max_per_company)
    duplicates_skipped = len(relevant) - len(eligible)
    diversity_capped = len(relevant) - duplicates_skipped - len(candidates)
    created = updated = 0
    for item in candidates:
        try:
            _, is_new = upsert_raw_job(item, sync=False)
            created += int(is_new); updated += int(not is_new)
        except Exception as exc: errors.append(f"{item.get('title','result')}: {type(exc).__name__}")
    with db() as conn:
        total = int(conn.execute("SELECT count(*) FROM jobs").fetchone()[0])
    boards = (
        len(adp_names) + len(employer_page_names) + len(greenhouse_names) + len(ashby_names) + len(workable_names) + len(lever_names) + len(phenom_names) + len(jibe_names) + len(jobvite_names) + len(workday_names) + len(revolutpeople_names) + len(avionte_names) + len(smartrecruiters_names) + len(icims_names) + len(successfactors_names) + len(bamboohr_names) + len(paylocity_names) + len(pinpoint_names) + len(rippling_legacy_names)
        + int(company_key("Apple") in targets and bool(APPLE_AUSTIN_BOARD))
        + int(company_key("Amazon") in targets and bool(AMAZON_AUSTIN_BOARD))
        + int(company_key("AMD") in targets and bool(AMD_AUSTIN_BOARD))
        + int(company_key("Arm") in targets and bool(ARM_AUSTIN_BOARD))
        + int(company_key("Capital One") in targets and bool(CAPITAL_ONE_AUSTIN_BOARD))
        + int(company_key("Adobe") in targets and bool(ADOBE_AUSTIN_BOARD))
        + int(company_key("Quest Global") in targets and bool(QUEST_GLOBAL_AUSTIN_BOARD))
        + int(company_key("Circle") in targets and bool(CIRCLE_AUSTIN_BOARD))
        + int(company_key("Google") in targets and bool(GOOGLE_AUSTIN_BOARD))
        + int(bool({company_key("Microsoft"), company_key("Microsoft AI")} & targets) and bool(MICROSOFT_CAREERS_BASE))
        + int(company_key("Bain & Company") in targets and bool(BAIN_JOBS_API))
        + int(company_key("Oracle") in targets and bool(ORACLE_CAREERS_BASE))
        + int(company_key("JPMorganChase") in targets and bool(JPMORGAN_CAREERS_BASE))
        + int(company_key("Dell Technologies") in targets and bool(DELL_CAREERS_BASE))
        + int(company_key("Procore") in targets and bool(PROCORE_AUSTIN_ENGINEERING_BOARD))
        + int(company_key("Realtor.com") in targets and bool(REALTOR_CAREERS_BASE))
        + int(company_key("TeamViewer") in targets and bool(TEAMVIEWER_AUSTIN_BOARD))
        + int(company_key("Charles Schwab") in targets and bool(SCHWAB_AUSTIN_BOARD))
        + int(company_key("Deloitte") in targets and bool(DELOITTE_AUSTIN_BOARD))
        + int(company_key("Rippling") in targets and bool(RIPPLING_CAREERS_BASE))
        + int(company_key("PwC") in targets and bool(PWC_AUSTIN_BOARD))
        + int(company_key("PayPal") in targets and bool(PAYPAL_CAREERS_BASE))
        + int(bool(PALOALTO_AUSTIN_BOARD))
        + int(company_key("Qualcomm") in targets and bool(QUALCOMM_CAREERS_BASE))
        + int(company_key("Salesforce") in targets and bool(SALESFORCE_JOBS_FEED))
        + int(company_key("Meta") in targets and bool(META_AUSTIN_BOARD))
        + int(company_key("Accenture") in targets and bool(ACCENTURE_AUSTIN_BOARD))
        + int(company_key("Cisco") in targets and bool(CISCO_AUSTIN_BOARD))
        + int(company_key("IBM") in targets and bool(IBM_AUSTIN_BOARD))
        + int(company_key("The Home Depot") in targets and bool(HOME_DEPOT_JOBS_API))
        + int(company_key("Snowflake") in targets and bool(SNOWFLAKE_ASHBY_BOARD))
        + int(company_key("CVS Health") in targets and bool(CVS_AUSTIN_BOARD))
        + int(company_key("Mastercard") in targets and bool(MASTERCARD_AUSTIN_BOARD))
        + int(company_key("LPL Financial") in targets and bool(LPL_AUSTIN_BOARD))
        + int(company_key("Roku") in targets and bool(ROKU_AUSTIN_BOARD))
        + int(company_key("Western Union") in targets and bool(WESTERN_UNION_AUSTIN_URLS))
        + int(company_key("Resideo") in targets and bool(RESIDEO_JOBS_API))
        + int(company_key("Bitdeer (NASDAQ: BTDR)") in targets and bool(BITDEER_CAREERS_BASE))
        + int(company_key("Celestica") in targets and bool(CELESTICA_AUSTIN_BOARD))
        + int(company_key("RWE") in targets and bool(RWE_AUSTIN_BOARD))
        + int(company_key("Exacta Systems") in targets and bool(EXACTA_AUSTIN_BOARD))
        + int(company_key("KPMG US") in targets and bool(KPMG_JOBS_API))
        + int(company_key("Texas Health and Human Services") in targets and bool(HHSC_SEARCH_BASE))
        + int(company_key("EY") in targets and bool(EY_SEARCH_BASE))
        + int(bool(TEMPORAL_CAREERS_BOARD))
        + int(bool(MPHASIS_RIPPLEHIRE_BOARD))
        + int(bool(TCS_IBEGIN_BOARD))
    )
    return {"provider": "priority company sites", "boards": boards, "target_companies": len(targets), "found": len(items), "relevant": len(relevant),
            "created": created, "updated": updated, "duplicates_skipped": duplicates_skipped,
            "diversity_capped": diversity_capped, "candidate_companies": len({str(item.get('company', '')).casefold() for item in candidates}), "max_per_company": max_per_company,
            "rejected": rejected, "total": total, "errors": errors}
