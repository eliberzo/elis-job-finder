"""Local handoff for structured records collected from browser-only career portals."""
from __future__ import annotations

import json
import sys
import base64
import termios
from collections.abc import Iterable
from typing import Any

from jobfinder.application.service import rescore_all
from jobfinder.domain.relevance import posting_is_relevant
from jobfinder.infrastructure.providers import _fresh_iso_listing, accenture_job_item, ea_avature_posting_item, gm_job_item, homedepot_job_item, ibm_avature_posting_item, lpl_posting_item, meta_job_item, paloalto_posting_item, paypal_job_item, procore_posting_item, pwc_posting_item, salesforce_job_item, servicenow_posting_item, tesla_job_item, uber_job_item, walmart_job_item
from jobfinder.infrastructure.storage import db, upsert_raw_job


def import_tesla_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Import Tesla details only when a fresh live-search observation proves recency."""
    stats: dict[str, Any] = {
        "received": 0, "validated_austin": 0, "accepted": 0, "created": 0,
        "updated": 0, "live_verified_new": 0, "undated_new_rejected": 0,
        "rejected_titles": [],
    }
    for record in records:
        stats["received"] += 1
        item = tesla_job_item(record)
        if not item:
            continue
        stats["validated_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        if not item.get("date_posted"):
            with db() as conn:
                exists = bool(conn.execute("SELECT 1 FROM jobs WHERE url=? LIMIT 1", (item["url"],)).fetchone())
            live_verified = _fresh_iso_listing(record.get("_live_listing_verified_at"), max_age_days=1)
            if not exists and not live_verified:
                stats["undated_new_rejected"] += 1
                continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
        if created and not item.get("date_posted"):
            stats["live_verified_new"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_gm_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate GM JSON-LD locally, preserve saves, then score after persistence."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = gm_job_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_procore_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate browser-collected Procore JSON-LD through the shared raw path."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = procore_posting_item(record, str(record.get("url") or record.get("_source_url") or ""))
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_paypal_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate browser-collected PayPal records through the shared raw path."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = paypal_job_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_paloalto_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate Palo Alto Networks JSON-LD locally before persistence/scoring."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = paloalto_posting_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_servicenow_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate ServiceNow JSON-LD locally before persistence and scoring."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = servicenow_posting_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_lpl_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate LPL Financial JSON-LD locally before persistence/scoring."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = lpl_posting_item(record, str(record.get("_source_url") or record.get("url") or ""))
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_pwc_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate PwC records joined from its branded portal and public Workday detail."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = pwc_posting_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_ibm_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate IBM Avature details collected from its browser-only search."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = ibm_avature_posting_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_ea_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate EA Avature details collected from its interactive public search."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = ea_avature_posting_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_homedepot_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate Home Depot's browser-exposed public job records locally."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        raw = f"<script>var current_job = {json.dumps(record)};</script>"
        item = homedepot_job_item(raw)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_salesforce_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate Salesforce details collected from its browser-only search."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = salesforce_job_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_meta_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate Meta details collected from its browser-only search."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = meta_job_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_uber_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate Uber details collected from its browser-only search."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = uber_job_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_walmart_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate Walmart details collected from its browser-only search."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = walmart_job_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def import_accenture_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate Accenture JobPosting JSON-LD collected from official details."""
    stats: dict[str, Any] = {"received": 0, "fresh_austin": 0, "accepted": 0, "created": 0, "updated": 0, "rejected_titles": []}
    for record in records:
        stats["received"] += 1
        item = accenture_job_item(record)
        if not item:
            continue
        stats["fresh_austin"] += 1
        if not posting_is_relevant(item):
            stats["rejected_titles"].append(item.get("title", ""))
            continue
        _, created = upsert_raw_job(item, sync=False)
        stats["accepted"] += 1
        stats["created" if created else "updated"] += 1
    stats["rescored"] = rescore_all() if stats["accepted"] else 0
    return stats


def main() -> None:
    if len(sys.argv) not in {2, 3} or sys.argv[1] not in {"tesla", "tesla-chunked", "gm", "gm-chunked", "procore", "procore-chunked", "paypal", "paypal-chunked", "paloalto", "paloalto-chunked", "servicenow", "servicenow-chunked", "lpl", "lpl-chunked", "pwc", "pwc-chunked", "ibm", "ibm-chunked", "ea", "ea-chunked", "homedepot", "homedepot-chunked", "salesforce", "salesforce-chunked", "meta", "meta-chunked", "uber", "uber-chunked", "walmart", "walmart-chunked", "accenture", "accenture-chunked"}:
        raise SystemExit("usage: python -m jobfinder.application.browser_import tesla|tesla-chunked|gm|gm-chunked|procore|procore-chunked|paypal|paypal-chunked|paloalto|paloalto-chunked|servicenow|servicenow-chunked|lpl|lpl-chunked|pwc|pwc-chunked|ibm|ibm-chunked|ea|ea-chunked|homedepot|homedepot-chunked|salesforce|salesforce-chunked|meta|meta-chunked|uber|uber-chunked|walmart|walmart-chunked|accenture|accenture-chunked [record-count]")
    expected = int(sys.argv[2]) if len(sys.argv) == 3 else None
    records: list[dict[str, Any]] = []
    if sys.argv[1].endswith("-chunked"):
        if sys.stdin.isatty():
            terminal = termios.tcgetattr(sys.stdin)
            terminal[3] &= ~(termios.ECHO | termios.ICANON)
            termios.tcsetattr(sys.stdin, termios.TCSANOW, terminal)
        chunks: list[str] = []
        for line in sys.stdin:
            value = line.strip()
            if value == "--record--":
                records.append(json.loads(base64.b64decode("".join(chunks)).decode("utf-8")))
                chunks = []
                if expected is not None and len(records) >= expected:
                    break
            elif value:
                chunks.append(value)
    else:
        for line in sys.stdin:
            if line.strip():
                records.append(json.loads(line))
            if expected is not None and len(records) >= expected:
                break
    if sys.argv[1].startswith("tesla"):
        importer = import_tesla_records
    elif sys.argv[1].startswith("accenture"):
        importer = import_accenture_records
    elif sys.argv[1].startswith("walmart"):
        importer = import_walmart_records
    elif sys.argv[1].startswith("uber"):
        importer = import_uber_records
    elif sys.argv[1].startswith("meta"):
        importer = import_meta_records
    elif sys.argv[1].startswith("salesforce"):
        importer = import_salesforce_records
    elif sys.argv[1].startswith("homedepot"):
        importer = import_homedepot_records
    elif sys.argv[1].startswith("ibm"):
        importer = import_ibm_records
    elif sys.argv[1].startswith("ea"):
        importer = import_ea_records
    elif sys.argv[1].startswith("pwc"):
        importer = import_pwc_records
    elif sys.argv[1].startswith("lpl"):
        importer = import_lpl_records
    elif sys.argv[1].startswith("paloalto"):
        importer = import_paloalto_records
    elif sys.argv[1].startswith("servicenow"):
        importer = import_servicenow_records
    elif sys.argv[1].startswith("procore"):
        importer = import_procore_records
    elif sys.argv[1].startswith("paypal"):
        importer = import_paypal_records
    else:
        importer = import_gm_records
    print(json.dumps(importer(records), ensure_ascii=False))


if __name__ == "__main__":
    main()
