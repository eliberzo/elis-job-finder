import json
import http.client
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import shutil
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from jobfinder.application.austin_sweep import AUSTIN_QUERY_GROUPS, query_groups
from jobfinder.application.collection import PostingStartGate, dedupe_job_candidates, posting_is_austin_relevant, round_robin_company_candidates
from jobfinder.application.interview_prep import interview_expectations_view, leetcode_research_view
from jobfinder.application.resume_builder import normalize_resume_builder
from jobfinder.application.read_models import filter_jobs_by_location_scope, jobs_view, resume_analysis_view
from jobfinder.application.service import company_market_signals
from jobfinder.application.workflows import update_job_status
from jobfinder.config import ACTUAL_LIST_PATH, DB_PATH, DEFAULT_PROFILE, LEVELS_BANK_PATH, PROFILE_PATH, TOP_CACHE_PATH
from jobfinder.domain.locations import austin_commute_place, is_austin_commutable_location, is_austin_proper_location, is_explicitly_non_us_location
from jobfinder.domain.matching import detect_skills, score
from jobfinder.domain.ranking import RankingEngine
from jobfinder.domain.relevance import posting_is_relevant, title_is_candidate
from jobfinder.domain.resume_review import review_resume
from jobfinder.infrastructure.aggregator import clean_text, extract_salary, normalize_item
from jobfinder.infrastructure.levels import salary_benchmark_map
from jobfinder.infrastructure.providers import ASHBY_BOARDS, AVIONTE_BOARDS, BAMBOOHR_BOARDS, DELL_CAREERS_BASE, DELL_SEARCH_QUERIES, EXACTA_AUSTIN_BOARD, GREENHOUSE_BOARDS, JIBE_SITES, ORACLE_SEARCH_QUERIES, PAYLOCITY_SITES, PINPOINT_SITES, REVOLUTPEOPLE_SITES, RWE_AUSTIN_BOARD, SMARTRECRUITERS_COMPANIES, WORKDAY_SITES, _fresh_iso_listing, _fresh_workday_listing, _phenom_austin_jobs, _response_body, accenture_job_item, accenture_search_job_item, adobe_austin_jobs, amd_job_item, amazon_job_item, apple_austin_jobs, apple_job_item, arm_job_item, arm_search_listings, ashby_board_endpoint, ashby_job_item, ashby_posting_has_austin, avionte_job_item, bain_job_item, bamboohr_job_item, breezy_austin_listings, breezy_job_item, canonical_public_url, capitalone_job_item, capitalone_search_listings, circle_austin_jobs, cisco_austin_jobs, cisco_job_item, dell_job_item, deloitte_austin_jobs, deloitte_job_item, deloitte_search_listings, ea_avature_posting_item, gm_job_item, google_job_item, google_search_paths, greenhouse_display_location_has_austin, greenhouse_listing_has_austin, homedepot_austin_jobs, homedepot_job_item, homedepot_job_record, ibm_austin_jobs, ibm_avature_posting_item, ibm_search_job_item, icims_job_item, icims_search_listings, jibe_job_item, jpmorgan_job_item, kpmg_job_item, kpmg_search_listings, lever_company_jobs, lever_posting_item, lpl_posting_item, meta_austin_jobs, meta_job_item, microsoft_job_item, mphasis_job_item, oracle_job_item, oracle_listing_has_austin, paloalto_posting_item, paylocity_job_item, paylocity_search_listings, paypal_austin_jobs, paypal_job_item, phenom_job_item, phenom_listing_has_austin, phenom_search_items, pinpoint_job_item, pinpoint_rss_dates, procore_job_item, procore_search_urls, pwc_austin_jobs, pwc_posting_item, qualcomm_austin_jobs, qualcomm_job_item, realtor_job_item, recruitee_job_item, resideo_job_item, resideo_search_listings, revolutpeople_job_item, rippling_job_item, rippling_search_item, roku_austin_jobs, roku_job_item, roku_search_listings, salesforce_austin_jobs, salesforce_feed_job_item, salesforce_job_item, schwab_job_item, schwab_search_listings, servicenow_posting_item, smartrecruiters_job_item, successfactors_job_item, successfactors_search_listings, tcs_job_item, teamtailor_job_item, teamtailor_next_page_url, teamtailor_search_listings, temporal_job_item, temporal_search_listings, tesla_job_item, uber_job_item, walmart_job_item, western_union_job_item, western_union_workday_search_listings, workday_company_jobs, workday_job_item
from jobfinder.infrastructure.providers import PALOALTO_AUSTIN_BOARD, paloalto_austin_job_paths
from jobfinder.infrastructure.providers import ICIMS_SITES, LEVER_API_HOSTS, LEVER_BOARDS, LPL_AUSTIN_BOARD, SUCCESSFACTORS_SITES, greenhouse_company_jobs
from jobfinder.infrastructure.providers import ashby_company_jobs
from jobfinder.infrastructure.providers import JOBVITE_SITES, jobvite_job_item, jobvite_search_listings
from jobfinder.infrastructure.providers import RIPPLING_ATS_TENANTS, RIPPLING_LEGACY_SITES, rippling_legacy_job_item, rippling_legacy_search_listings, rippling_tenant_job_item, rippling_tenant_search_urls
from jobfinder.infrastructure.providers import PAYCOR_SITES, UKG_LEGACY_BOARDS, paycor_brand_date, paycor_job_item, paycor_search_listings, ukg_legacy_job_item, ukg_legacy_search_listings
from jobfinder.infrastructure.providers import ADP_SITES, EMPLOYER_PAGE_SITES, _adp_listing_has_austin, adp_job_item, employer_page_job_item
from jobfinder.infrastructure.providers import QUEST_GLOBAL_AUSTIN_BOARD, questglobal_austin_jobs
from jobfinder.infrastructure import storage
from jobfinder.infrastructure import practice_builder
from jobfinder.infrastructure import todos
from jobfinder.infrastructure.local_events import load_local_events


PROFILE = {
    "resume_text": "Python Kafka distributed systems microservices PostgreSQL cloud observability architecture",
    "skills": [],
    "weights": {"fit": 0.55, "practice": 0.45, "burn": 0.80, "recency": 0.30},
    "compensation_fallback": 200000,
}


class MatchingTests(unittest.TestCase):
    def test_dell_hcm_requires_fresh_exact_austin(self):
        posted = datetime.now(timezone.utc).date().isoformat()
        detail = {
            "Id": "300001",
            "Title": "Senior Software Engineer, Cloud Platform",
            "PrimaryLocation": "Austin, Texas, United States",
            "ExternalPostedStartDate": posted,
            "ExternalDescriptionStr": "Build distributed cloud services, APIs, databases, and Kubernetes platforms. " * 8,
            "ExternalResponsibilitiesStr": "Own backend architecture, observability, reliability, testing, and delivery.",
            "ExternalQualificationsStr": "Python, Java, Kafka, PostgreSQL, AWS, and container orchestration.",
            "WorkplaceType": "Hybrid",
        }
        item = dell_job_item(detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["company"], "Dell Technologies")
        self.assertEqual(item["source"], "dell")
        self.assertEqual(item["provider_job_id"], "300001")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["url"], f"{DELL_CAREERS_BASE}/job/300001")
        self.assertTrue(posting_is_relevant(item))
        self.assertIn("software development manager", DELL_SEARCH_QUERIES)
        self.assertIn("dell", storage.OFFICIAL_JOB_SOURCES)
        self.assertIsNone(dell_job_item(detail | {"PrimaryLocation": "Round Rock, Texas, United States"}))
        self.assertIsNone(dell_job_item(detail | {"ExternalPostedStartDate": "2026-05-01"}))

    def test_tcs_ibegin_requires_dated_exact_austin(self):
        posted = datetime.now(timezone.utc).date().isoformat()
        payload = {"data": {
            "jobId": 424108,
            "title": "Senior Java Engineer",
            "location": "Austin, TX",
            "country": "United States",
            "experience": "8 - 10 Years",
            "role": "Engineer",
            "skilldetail": "Java | Kafka | Restful",
            "description": "Build secure Java REST services, distributed systems, Kafka messaging, cloud services, databases, tests, and CI/CD. " * 4,
            "applyby": "2026-09-23 00:00:00",
            "minSalary": "$80,000",
            "maxSalary": "$125,000",
        }}
        item = tcs_job_item(payload, posted)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "tcs")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["salary_min"], 80000)
        self.assertIn("Apply by: 2026-09-23", item["description"])
        self.assertTrue(posting_is_relevant(item))
        self.assertIn("tcs", storage.OFFICIAL_JOB_SOURCES)
        self.assertIsNone(tcs_job_item({"data": payload["data"] | {"location": "Dallas, TX"}}, posted))
        self.assertIsNone(tcs_job_item(payload, ""))

    def test_mphasis_ripplehire_requires_fresh_exact_austin(self):
        payload = {"jobVO": {
            "jobSeq": "906302",
            "jobCode": "118326-37-1",
            "jobTitle": "Technical Lead",
            "jobStatus": "ACTIVE",
            "jobPostingDate": datetime.now(timezone.utc).strftime("%d-%b-%Y"),
            "jobDesc": "<p>Location: Austin, Texas</p><p>Lead .NET full-stack software, APIs, microservices, cloud platforms, and distributed systems.</p>" * 4,
            "otherDetails": "Salary range $60000 to $125000",
        }}
        item = mphasis_job_item(payload, "public-token")
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "ripplehire")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["provider_job_id"], "118326-37-1")
        self.assertEqual(item["salary_min"], 60000)
        self.assertTrue(posting_is_relevant(item))
        self.assertIn("ripplehire", storage.OFFICIAL_JOB_SOURCES)
        texas_only = {"jobVO": payload["jobVO"] | {"jobDesc": "Location: Client Site, Texas. Lead .NET full-stack software and APIs. " * 8}}
        self.assertIsNone(mphasis_job_item(texas_only, "public-token"))
        stale = {"jobVO": payload["jobVO"] | {"jobPostingDate": "01-Jun-2026"}}
        self.assertIsNone(mphasis_job_item(stale, "public-token"))

    def test_new_employer_portals_enforce_exact_austin_and_original_dates(self):
        self.assertEqual(BAMBOOHR_BOARDS["Cornelis Networks"], "cornelisnetworks")
        self.assertEqual(GREENHOUSE_BOARDS["Juul Labs"], "juullabs")
        self.assertEqual(JIBE_SITES["Lutron Electronics"]["base_url"], "https://careers.lutron.com")
        self.assertEqual(WORKDAY_SITES["Light & Wonder"]["tenant"], "lnw")
        self.assertEqual(GREENHOUSE_BOARDS["Sagent"], "sagent")
        self.assertIn("The Helper Bees", PAYLOCITY_SITES)
        self.assertEqual(WORKDAY_SITES["SciPlay"]["site"], "SciPlayExternalCareersSite")
        self.assertEqual(WORKDAY_SITES["Land.com Network"]["tenant"], "costar")
        self.assertEqual(WORKDAY_SITES["SHI International Corp."]["site"], "shicareers")
        self.assertEqual(ASHBY_BOARDS["Neurophos"], "neurophos")
        self.assertEqual(ASHBY_BOARDS["Scribd, Inc."], "ScribdInc")
        self.assertEqual(ASHBY_BOARDS["Crusoe"], "crusoe")
        self.assertEqual(GREENHOUSE_BOARDS["Lila Sciences"], "LilaSciences")
        self.assertEqual(WORKDAY_SITES["GEICO"]["site"], "External")
        self.assertEqual(WORKDAY_SITES["GEICO"]["search_text"], "Austin")
        self.assertEqual(SMARTRECRUITERS_COMPANIES["RRD"], "RRDonnelley")
        self.assertEqual(LEVER_BOARDS["TTEC Digital"], "ttecdigital")

        opening = {
            "jobOpeningShareUrl": "https://cornelisnetworks.bamboohr.com/careers/999",
            "jobOpeningName": "Senior Software Engineer, AI Platform",
            "datePosted": "2026-09-03",
            "atsLocation": {"city": "Austin", "state": "Texas", "country": "United States"},
            "description": "Build Python cloud APIs, distributed services, AI infrastructure, and Kubernetes platforms. " * 8,
        }
        item = bamboohr_job_item(
            "Cornelis Networks", "cornelisnetworks", "999", {"result": {"jobOpening": opening}}
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "bamboohr")
        self.assertEqual(item["provider_job_id"], "999")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertIn("bamboohr", storage.OFFICIAL_JOB_SOURCES)
        non_austin = opening | {"atsLocation": opening["atsLocation"] | {"city": "Dallas"}}
        self.assertIsNone(bamboohr_job_item(
            "Cornelis Networks", "cornelisnetworks", "999", {"result": {"jobOpening": non_austin}}
        ))
        stale = opening | {"datePosted": "2026-04-10"}
        self.assertIsNone(bamboohr_job_item(
            "Cornelis Networks", "cornelisnetworks", "999", {"result": {"jobOpening": stale}}
        ))

    def test_scribd_ashby_item_keeps_non_california_us_pay_band(self):
        item = ashby_job_item("Scribd, Inc.", {
            "title": "Staff Software Engineer, Core Infrastructure",
            "location": "Austin, Texas, United States",
            "jobUrl": "https://jobs.ashbyhq.com/ScribdInc/example",
            "publishedAt": "2026-08-18T12:00:00Z",
            "workplaceType": "Remote",
            "descriptionPlain": (
                "Build Rust and Python distributed storage services on AWS. "
                "In the state of California, the salary range is between $176,500 and $275,000. "
                "In the United States, outside of California, the reasonably expected salary range "
                "is between $145,000 [minimum local market] to $261,500 [maximum local market]."
            ),
        })
        self.assertIsNotNone(item)
        self.assertEqual(item["salary_text"], "$145,000 - $261,500")
        self.assertEqual(item["salary_min"], 145000.0)
        self.assertEqual(item["salary_max"], 261500.0)
        self.assertEqual(item["salary_type"], "base")

    def test_ukg_and_paycor_public_boards_require_fresh_exact_austin(self):
        fresh_date = datetime.now(timezone.utc).date().isoformat()
        board_url = UKG_LEGACY_BOARDS["UFCU"]
        board_id = board_url.rstrip("/").rsplit("/", 1)[-1]
        opportunity = {
            "Id": "75ff7a39-ad80-41cf-848b-6ee9fb7efb0c",
            "Title": "Manager, API Platform Engineering",
            "PostedDate": "2026-09-04T17:34:29.827Z",
            "Locations": [{"Address": {
                "City": "Austin", "PostalCode": "78759",
                "State": {"Code": "TX"}, "Country": {"Code": "USA"},
            }}],
        }
        board = "initialFeaturedOpportunities: " + json.dumps([opportunity]) + ",\nloadUrl: '/search'"
        listings = ukg_legacy_search_listings(board, board_url)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["location"], "Austin, TX 78759, USA")

        detail_opportunity = opportunity | {
            "Description": "Lead C# .NET APIs, microservices, Kubernetes, Azure, CI/CD, and distributed platform reliability. " * 8,
            "OpportunityIsClosed": False,
            "JobBoardMemberships": [{"JobBoardId": board_id, "ExternalPostedDate": "2026-09-04T17:34:29.827Z"}],
        }
        detail = "new US.Opportunity.CandidateOpportunityDetail(" + json.dumps(detail_opportunity) + ");"
        item = ukg_legacy_job_item("UFCU", detail, listings[0]["url"], board_id)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "ukg")
        self.assertEqual(item["date_posted"], "2026-09-04")
        self.assertIn("ukg", storage.OFFICIAL_JOB_SOURCES)
        non_austin = detail_opportunity | {"Locations": [{"Address": {
            "City": "Dallas", "State": {"Code": "TX"}, "Country": {"Code": "USA"},
        }}]}
        self.assertIsNone(ukg_legacy_job_item(
            "UFCU", "new US.Opportunity.CandidateOpportunityDetail(" + json.dumps(non_austin) + ");",
            listings[0]["url"], board_id,
        ))

        site = PAYCOR_SITES["Michael & Susan Dell Foundation"]
        paycor_home = '''<a href="https://recruitingbypaycor.com/career/JobIntroduction.action?clientId=x&amp;id=abc123&amp;source=&amp;lang=en" ns-qa="Senior Engineer - Austin, TX">Senior Engineer - Austin, TX</a>'''
        paycor_listings = paycor_search_listings(paycor_home, site)
        self.assertEqual(len(paycor_listings), 1)
        self.assertIn("gnk=job", paycor_listings[0]["url"])
        paycor_detail = '''
            <td id="gnewtonJobPosition"><b>Position:</b> Senior Engineer - Austin, TX</td>
            <td id="gnewtonJobLocationInfo">Austin, TX<br></td>
            <td id="gnewtonJobDescriptionText">We are seeking a full stack Senior Engineer to build .NET C# services, SQL data systems, Azure cloud infrastructure, React interfaces, and production APIs. Build reliable distributed backend software and automated tests. Design maintainable web applications, relational database integrations, continuous delivery processes, security controls, and production support tooling.</td>
        '''
        paycor_item = paycor_job_item(
            "Michael & Susan Dell Foundation", paycor_detail, paycor_listings[0]["url"], fresh_date
        )
        self.assertIsNotNone(paycor_item)
        self.assertEqual(paycor_item["source"], "paycor")
        self.assertTrue(posting_is_relevant(paycor_item))
        self.assertEqual(paycor_brand_date('{"datePublished":"2026-08-17T18:34:26+00:00"}'), "2026-08-17")
        self.assertIn("paycor", storage.OFFICIAL_JOB_SOURCES)

    def test_rippling_public_search_and_detail_require_fresh_exact_austin(self):
        job_id = "528f45e5-4c17-4fb7-affe-41e0c12c7c15"
        url = f"https://ats.rippling.com/rippling/jobs/{job_id}"
        listing = rippling_search_item({
            "objectID": job_id,
            "jobId": job_id,
            "name": "Senior Software Engineer, Data Platform",
            "locationNames": ["New York, NY", "Austin, TX"],
            "isRemote": True,
            "url": url,
        })
        self.assertIsNotNone(listing)
        self.assertEqual(listing["source"], "rippling")
        self.assertEqual(listing["work_arrangement"], "remote")
        self.assertIsNone(rippling_search_item({
            "jobId": job_id, "name": listing["title"], "locationNames": ["Dallas, TX"], "url": url,
        }))

        job = {
            "uuid": job_id,
            "name": listing["title"],
            "description": {
                "company": "Rippling builds workforce software.",
                "role": "Build Python cloud APIs, distributed data systems, Kafka services, and Kubernetes platforms. " * 7,
            },
            "workLocations": ["Austin, TX", "Remote (United States)"],
            "createdOn": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "unlistedFromSearch": False,
        }
        payload = {"props": {"pageProps": {"apiData": {"jobPost": job}}}}
        raw = f'<script type="application/json" id="__NEXT_DATA__">{json.dumps(payload)}</script>'
        item = rippling_job_item(raw, url)
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX")
        self.assertGreater(len(item["description"]), 400)
        self.assertEqual(storage._official_requisition_key("rippling", url), f"rippling:{job_id}")
        self.assertIn("rippling", storage.OFFICIAL_JOB_SOURCES)

        job["workLocations"] = ["Dallas, TX"]
        non_austin = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        self.assertIsNone(rippling_job_item(non_austin, url))
        job["workLocations"] = ["Austin, TX"]
        job["createdOn"] = "2026-01-01T12:00:00Z"
        stale = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        self.assertIsNone(rippling_job_item(stale, url))

    def test_closinglock_uses_public_rippling_tenant_board(self):
        tenant = RIPPLING_ATS_TENANTS["Closinglock"]
        job_id = "bc3a5556-20d2-421b-bd59-1cc24a25a13c"
        url = f"https://ats.rippling.com/{tenant}/jobs/{job_id}"
        board = f'<a href="/{tenant}/jobs/{job_id}">Senior Backend Engineer</a>' * 2
        self.assertEqual(rippling_tenant_search_urls(board, tenant), [url])
        job = {
            "uuid": job_id,
            "name": "Senior Backend Engineer",
            "description": {
                "company": "Closinglock secures real-estate transactions.",
                "role": "Build Python, FastAPI, relational database, AWS, Docker, and backend API systems. " * 7,
            },
            "workLocations": ["Austin, TX"],
            "createdOn": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "unlistedFromSearch": False,
        }
        payload = {"props": {"pageProps": {"apiData": {"jobPost": job}}}}
        raw = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        item = rippling_tenant_job_item("Closinglock", tenant, raw, url)
        self.assertIsNotNone(item)
        self.assertEqual(item["company"], "Closinglock")
        self.assertEqual(item["provider_job_id"], job_id)
        self.assertEqual(item["location"], "Austin, TX")

    def test_rugiet_legacy_rippling_feed_requires_fresh_exact_austin(self):
        base_url = RIPPLING_LEGACY_SITES["Rugiet"]
        url = f"{base_url}/job/980982/senior-software-engineer"
        rss = f'''<rss><channel><item>
            <title>Senior Software Engineer</title><link>{url}</link>
            <location>Remote - Austin, TX</location>
        </item><item>
            <title>Senior Software Engineer</title><link>{base_url}/job/123/dallas</link>
            <location>Dallas, TX</location>
        </item></channel></rss>'''
        listings = rippling_legacy_search_listings(rss, base_url)
        self.assertEqual([listing["url"] for listing in listings], [url])

        posting = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Senior Software Engineer",
            "datePosted": datetime.now(timezone.utc).isoformat(),
            "description": "Build Ruby on Rails APIs, PostgreSQL data models, AWS cloud infrastructure, and React full-stack services. " * 7,
            "jobLocation": {"@type": "Place", "address": {
                "@type": "PostalAddress", "addressLocality": "Austin",
                "addressRegion": "TX", "addressCountry": "US",
            }},
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script><div data-react-props="&quot;remote&quot;:true"></div>'
        item = rippling_legacy_job_item("Rugiet", raw, url)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "rippling")
        self.assertEqual(item["work_arrangement"], "remote")
        self.assertEqual(storage._official_requisition_key("rippling", url), "rippling:980982")

        non_austin = posting | {"jobLocation": {"address": {
            "addressLocality": "Dallas", "addressRegion": "TX", "addressCountry": "US",
        }}}
        self.assertIsNone(rippling_legacy_job_item(
            "Rugiet", f'<script type="application/ld+json">{json.dumps(non_austin)}</script>', url,
        ))
        stale = posting | {"datePosted": "2026-01-01T12:00:00Z"}
        self.assertIsNone(rippling_legacy_job_item(
            "Rugiet", f'<script type="application/ld+json">{json.dumps(stale)}</script>', url,
        ))

    def test_smartrecruiters_requires_fresh_exact_austin_and_stable_requisition(self):
        self.assertEqual(SMARTRECRUITERS_COMPANIES["Asure Software"], "asuresoftware")
        detail = {
            "id": "744000145354179",
            "active": True,
            "name": "Engineering Manager, Platform Services",
            "releasedDate": "2026-09-03T22:09:38.906Z",
            "postingUrl": "https://jobs.smartrecruiters.com/RenesasElectronics/744000145354179-engineering-manager-platform-services",
            "location": {
                "city": "Austin", "region": "Texas", "country": "us",
                "fullLocation": "Austin, Texas, United States", "hybrid": True,
            },
            "jobAd": {"sections": {
                "jobDescription": {"title": "Job Description", "text": "Build and lead Python cloud APIs, distributed services, data platforms, Kubernetes reliability, and backend engineering. " * 5},
                "qualifications": {"title": "Qualifications", "text": "Eight years of software engineering and technical leadership."},
            }},
        }
        item = smartrecruiters_job_item("Renesas Electronics", detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "smartrecruiters")
        self.assertEqual(item["work_arrangement"], "hybrid")
        self.assertEqual(
            storage._official_requisition_key("smartrecruiters", item["url"]),
            "smartrecruiters:744000145354179",
        )
        self.assertIn("smartrecruiters", storage.OFFICIAL_JOB_SOURCES)
        self.assertIsNone(smartrecruiters_job_item("Renesas Electronics", detail | {"releasedDate": "2026-06-01T12:00:00Z"}))
        self.assertIsNone(smartrecruiters_job_item("Renesas Electronics", detail | {"location": detail["location"] | {"city": "Dallas"}}))
        self.assertFalse(title_is_candidate({"title": "Senior Analog Engineering Manager"}))

    def test_data_platform_people_manager_requires_engineering_team_evidence(self):
        title = "Data Platform & Governance Manager"
        description = (
            "Lead the technical data platform strategy, manage and grow a team of data engineers, "
            "and set data engineering standards across distributed warehouses and reliable pipelines. "
        ) * 3
        self.assertTrue(title_is_candidate({"title": title, "description": description}))
        self.assertTrue(posting_is_relevant({"title": title, "description": description, "location": "Austin, TX"}))
        self.assertFalse(title_is_candidate({"title": title, "description": "Manage analysts and business reporting."}))
        self.assertFalse(title_is_candidate({"title": "Data Platform Product Manager", "description": description}))

    def test_servicenow_smartrecruiters_feed_keeps_branded_canonical_url(self):
        detail = {
            "id": "744000142150121", "refNumber": "JB0070832", "active": True,
            "name": "Senior Security Software Engineer, IAM - Moveworks",
            "releasedDate": datetime.now(timezone.utc).isoformat(),
            "postingUrl": "https://jobs.smartrecruiters.com/ServiceNow/744000142150121-senior-security-software-engineer-iam-moveworks",
            "location": {
                "city": "Austin", "region": "Texas", "country": "us",
                "fullLocation": "Austin, Texas, United States", "remote": True,
            },
            "jobAd": {"sections": {
                "jobDescription": {"title": "Job Description", "text": "Build production IAM software and secure AWS, Azure, Kubernetes, and cloud access platforms. " * 8},
                "qualifications": {"title": "Qualifications", "text": "Five years of software engineering and IAM automation experience."},
            }},
        }
        item = smartrecruiters_job_item("ServiceNow", detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "servicenow")
        self.assertEqual(item["provider_job_id"], "JB0070832")
        self.assertEqual(
            item["url"],
            "https://careers.servicenow.com/jobs/744000142150121/senior-security-software-engineer-iam-moveworks/",
        )
        self.assertEqual(item["work_arrangement"], "remote")
        self.assertEqual(
            storage._official_requisition_key("servicenow", item["url"]),
            "servicenow:744000142150121",
        )

    def test_icims_search_and_detail_require_exact_austin(self):
        board = '''<ul><li class="iCIMS_JobCardItem"><div class="header left"><span class="sr-only field-label">Location</span><span>US-TX-Austin</span></div><div class="title"><a href="https://careers-epeconsulting.icims.com/jobs/2313/senior-software-engineer/job?in_iframe=1" class="iCIMS_Anchor"><h3>Senior Software Engineer</h3></a></div></li><li class="iCIMS_JobCardItem"><span>US-MO-St. Louis</span><a href="https://careers-epeconsulting.icims.com/jobs/2314/staff-engineer/job?in_iframe=1"><h3>Staff Engineer</h3></a></li></ul>'''
        listings = icims_search_listings(board, "https://careers-epeconsulting.icims.com")
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["url"], "https://careers-epeconsulting.icims.com/jobs/2313/senior-software-engineer/job")
        posting = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Senior Software Engineer", "datePosted": "2026-08-25T04:00:00.000Z",
            "url": listings[0]["url"],
            "description": "Build Python cloud APIs, distributed systems, data platforms, Kubernetes reliability, and backend services. " * 6,
            "jobLocation": [{"address": {
                "addressLocality": "Austin", "addressRegion": "TX", "addressCountry": "US",
                "streetAddress": "Remote - US Or Canada",
            }}],
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        item = icims_job_item("Electric Power Engineers", raw, listings[0]["url"])
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "icims")
        self.assertEqual(item["work_arrangement"], "remote")
        self.assertEqual(storage._official_requisition_key("icims", item["url"]), "icims:2313")
        self.assertIn("icims", storage.OFFICIAL_JOB_SOURCES)
        posting["jobLocation"][0]["address"]["addressLocality"] = "Beirut"
        non_austin = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        self.assertIsNone(icims_job_item("Electric Power Engineers", non_austin, listings[0]["url"]))

    def test_kpmg_public_search_and_detail_require_fresh_exact_austin(self):
        search = json.dumps({
            "postings": {
                "size": 1,
                "jobs": '''<div class="search--item"><a href="/jobdetail/?jobId=136334"><div class="h4 mb-4">Manager, AI Engineer</div><div class="list-view"><div class="h5 text-dark-grey">Manager, AI Engineer</div><div class="text-xs text-dark-grey">Advisory | Atlanta, GA; Austin, TX</div></div></a></div>''',
            }
        })
        listings = kpmg_search_listings(search)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["provider_job_id"], "136334")
        detail = '''<a data-id="136334" data-locations="Atlanta, GA; Austin, TX"><h1 id="jd-title">Manager, AI Engineer</h1><p id="jd-location">Atlanta, GA; Austin, TX</p><div class="pt-4 job-description">Build and lead Python AI/ML cloud services, microservices, APIs, data pipelines, Kubernetes infrastructure, and distributed platforms. Build and lead Python AI/ML cloud services, microservices, APIs, data pipelines, Kubernetes infrastructure, and distributed platforms. California Salary Range: $153710 - $267030</div><div class="pb-4"></div><script type="application/ld+json">{"datePosted": "Sep 1, 2026"}</script>'''
        item = kpmg_job_item(detail, listings[0]["url"])
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "kpmg")
        self.assertEqual(item["date_posted"], "2026-09-01")
        self.assertIn("California Salary Range", item["salary_text"])
        self.assertIsNone(item["salary_max"])
        self.assertEqual(storage._official_requisition_key("kpmg", item["url"]), "kpmg:136334")
        self.assertIn("kpmg", storage.OFFICIAL_JOB_SOURCES)
        self.assertIsNone(kpmg_job_item(detail.replace("Austin, TX", "Dallas, TX"), listings[0]["url"]))
        self.assertIsNone(kpmg_job_item(detail.replace("Sep 1, 2026", "Jun 1, 2026"), listings[0]["url"]))

    def test_peak_performers_uses_public_avionte_posting(self):
        config = AVIONTE_BOARDS["Peak Performers"]
        listing = {
            "jobPostIdEnc": "FkatOi_OwvA",
            "jobTitle": "Senior Databricks Data Engineer",
            "location": "Austin, TX",
            "postDateUtc": "2026-09-03T21:15:46Z",
        }
        detail = {
            "description": "<p>Build Python Databricks data pipelines, Azure cloud services, APIs, and distributed infrastructure.</p> " * 6
            + "<p>Rate: $86.00/hour W2. Hybrid in Austin, Texas.</p>"
        }
        item = avionte_job_item("Peak Performers", config, listing, detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "avionte")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["salary_min"], 178880)
        self.assertEqual(item["salary_max"], 178880)
        self.assertEqual(item["url"], "https://www.peakperformers.org/browse-jobs?rpid=FkatOi_OwvA")
        self.assertEqual(storage._official_requisition_key("avionte", item["url"]), "avionte:FkatOi_OwvA")
        self.assertIn("avionte", storage.OFFICIAL_JOB_SOURCES)
        self.assertIsNone(avionte_job_item("Peak Performers", config, listing | {"location": "Dallas, TX"}, detail))
        self.assertIsNone(avionte_job_item("Peak Performers", config, listing | {"postDateUtc": "2026-06-01T12:00:00Z"}, detail))

    def test_paylocity_board_parser_builds_canonical_detail_links(self):
        board = '''<script>window.pageData = {"Jobs":[{"JobId":4048968,"JobTitle":"Sr. Software Engineer - Platform","PublishedDate":"2026-08-14T10:00:00-05:00","JobLocation":{"City":"Austin","State":"TX","Country":"USA"}}]};</script>'''
        listings = paylocity_search_listings(board)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["location"], "Austin, TX, USA")
        self.assertEqual(
            listings[0]["url"],
            "https://recruiting.paylocity.com/Recruiting/Jobs/Details/4048968",
        )

    def test_paylocity_detail_date_and_exact_location_are_authoritative(self):
        fresh_date = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        stale_date = (datetime.now(timezone.utc).date() - timedelta(days=60)).isoformat()
        posting = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Sr. Software Engineer - Platform",
            "datePosted": f"{fresh_date}T10:00:00-05:00",
            "description": "Build Python distributed cloud APIs, Kafka services, Kubernetes, and reliable data platforms. " * 8,
            "jobLocation": {
                "address": {
                    "addressLocality": "Austin",
                    "addressRegion": "TX",
                    "addressCountry": "US",
                }
            },
        }
        url = "https://recruiting.paylocity.com/Recruiting/Jobs/Details/4048968"
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        item = paylocity_job_item("American Innovations", raw, url)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "paylocity")
        self.assertEqual(item["date_posted"], fresh_date)
        self.assertIn("paylocity", storage.OFFICIAL_JOB_SOURCES)

        posting["datePosted"] = f"{stale_date}T16:20:51-05:00"
        stale = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        self.assertIsNone(paylocity_job_item("American Innovations", stale, url))

        posting["datePosted"] = f"{fresh_date}T10:00:00-05:00"
        posting["jobLocation"]["address"]["addressLocality"] = "Dallas"
        non_austin = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        self.assertIsNone(paylocity_job_item("American Innovations", non_austin, url))

    def test_salient_systems_uses_public_paylocity_board(self):
        self.assertEqual(
            PAYLOCITY_SITES["Salient Systems"],
            "https://recruiting.paylocity.com/Recruiting/Jobs/All/ac777e4c-5448-4eff-8245-1b815dd9cd72",
        )
        fresh_date = datetime.now(timezone.utc).date().isoformat()
        posting = {
            "@type": "JobPosting",
            "title": "Engineering Manager",
            "datePosted": fresh_date,
            "description": (
                "Lead the AWS cloud infrastructure and DevOps team powering our remote gateway, "
                "Terraform platform, CI/CD pipelines, and operational reliability. " * 8
            ),
            "jobLocation": {"address": {
                "addressLocality": "Austin", "addressRegion": "TX", "addressCountry": "US",
            }},
        }
        item = paylocity_job_item(
            "Salient Systems",
            f'<script type="application/ld+json">{json.dumps(posting)}</script>',
            "https://recruiting.paylocity.com/Recruiting/Jobs/Details/4127550",
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["work_arrangement"], "onsite/hybrid")

    def test_successfactors_provider_requires_fresh_exact_austin_microdata(self):
        self.assertEqual(
            RWE_AUSTIN_BOARD,
            "https://jobs.rwe.com/RWE/go/All-Jobs_RWE-%28EN%29/8740401/",
        )
        board = '''<tr class="data-row"><td><a href="/job/Austin-Staff-Engineer-TX/123/" class="jobTitle-link">Staff Engineer, Software</a></td><td><span class="jobLocation">Austin, TX, US</span></td><td><span class="jobDate">Aug 26, 2026</span></td></tr>'''
        listings = successfactors_search_listings(board, "https://careers.example.com")
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["url"], "https://careers.example.com/job/Austin-Staff-Engineer-TX/123/")
        detail = '''<span itemprop="jobLocation"><meta itemprop="addressLocality" content="Austin"><meta itemprop="addressRegion" content="TX"><meta itemprop="addressCountry" content="US"></span><meta itemprop="datePosted" content="Wed Aug 26 02:01:00 UTC 2026"><h1 id="job-title">Staff Engineer, Software</h1><span itemprop="description" class="jobdescription">Build Python distributed cloud APIs, Kafka services, Kubernetes, and reliable data platforms. Build Python distributed cloud APIs, Kafka services, Kubernetes, and reliable data platforms. Build Python distributed cloud APIs, Kafka services, Kubernetes, and reliable data platforms.</span>'''
        item = successfactors_job_item("Celestica", detail, listings[0]["url"])
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "successfactors")
        self.assertEqual(item["date_posted"], "2026-08-26")
        self.assertEqual(item["provider_job_id"], "123")
        self.assertEqual(storage._official_requisition_key("successfactors", listings[0]["url"]), "successfactors:123")
        self.assertIsNone(successfactors_job_item("Celestica", detail.replace('content="Austin"', 'content="Dallas"'), listings[0]["url"]))
        multi_location_detail = '''<span itemprop="jobLocation"><span itemprop="address"><meta itemprop="addressLocality" content="Chicago"><meta itemprop="addressRegion" content="IL"><meta itemprop="addressCountry" content="US"></span><span itemprop="address"><meta itemprop="addressLocality" content="Austin"><meta itemprop="addressRegion" content="TX"><meta itemprop="addressCountry" content="US"></span></span><meta itemprop="datePosted" content="Wed Aug 26 02:01:00 UTC 2026"><h1 id="job-title">Staff Engineer, Software</h1><span itemprop="description" class="jobdescription">Build Python distributed cloud APIs, Kafka services, Kubernetes, and reliable data platforms. Build Python distributed cloud APIs, Kafka services, Kubernetes, and reliable data platforms. Build Python distributed cloud APIs, Kafka services, Kubernetes, and reliable data platforms.</span>'''
        multi_location_item = successfactors_job_item("EY", multi_location_detail, "https://careers.ey.com/ey/job/example/456/")
        self.assertIsNotNone(multi_location_item)
        self.assertEqual(multi_location_item["location"], "Austin, TX, US")

        self.assertEqual(EXACTA_AUSTIN_BOARD, "https://jobs.churchilldowns.com/go/Exacta/9777700/")
        labelled_title = detail.replace(
            '<h1 id="job-title">Staff Engineer, Software</h1>',
            '<h1><span class="joblayouttoken-label">Title:</span><span itemprop="title">Sr. Software Engineer</span></h1>',
        )
        exacta_item = successfactors_job_item(
            "Exacta Systems",
            labelled_title,
            "https://jobs.churchilldowns.com/job/Austin-Sr_-Software-Engineer-TX/1362251500/",
        )
        self.assertIsNotNone(exacta_item)
        self.assertEqual(exacta_item["title"], "Sr. Software Engineer")

    def test_successfactors_tile_theme_and_monthly_salary_are_normalized(self):
        board = '''<li class="job-tile job-id-456"><a class="jobTitle-link fontcolor" href="/hhscjobs/job/AUSTIN-Senior-Java-Developer-TX/456/">Senior Java Developer</a><div id="job-456-desktop-section-location-value">AUSTIN, TX</div><div id="job-456-desktop-section-date-value">Aug 27, 2026</div></li>'''
        listings = successfactors_search_listings(board, "https://careers.hhs.texas.gov")
        self.assertEqual(len(listings), 1)
        detail = '''<span itemprop="jobLocation"><meta itemprop="addressLocality" content="Austin"><meta itemprop="addressRegion" content="TX"><meta itemprop="addressCountry" content="US"></span><meta itemprop="datePosted" content="Thu Aug 27 02:01:00 UTC 2026"><h1 id="job-title">Senior Java Developer</h1><span itemprop="description" class="jobdescription">Salary Range: $7,716.66 - $10,383.83 Pay Frequency: Monthly. Build full-stack Java cloud applications, APIs, databases, and distributed services. Build full-stack Java cloud applications, APIs, databases, and distributed services. Build full-stack Java cloud applications, APIs, databases, and distributed services.</span>'''
        item = successfactors_job_item("Texas Health and Human Services", detail, listings[0]["url"])
        self.assertIsNotNone(item)
        self.assertAlmostEqual(item["salary_min"], 92599.92)
        self.assertAlmostEqual(item["salary_max"], 124605.96)
        self.assertIn("annualized", item["salary_text"])

    def test_ey_austin_uses_its_published_other_offices_salary_band(self):
        detail = (
            '<span itemprop="jobLocation"><meta itemprop="addressLocality" content="Austin">'
            '<meta itemprop="addressRegion" content="TX"><meta itemprop="addressCountry" content="US"></span>'
            f'<meta itemprop="datePosted" content="{date.today().strftime("%b %d, %Y")}">'
            '<h1 id="job-title">Data Engineer - Senior - Consulting</h1>'
            '<span itemprop="description" class="jobdescription">Build data pipelines and cloud platforms. '
            'New York City offices – $128,400 to $192,500. '
            'All other offices locations in the US, including Sacramento – $106,900 to $176,500.'
            '</span>'
        )
        item = successfactors_job_item("EY", detail, "https://careers.ey.com/ey/job/test/1440687233/")
        self.assertIsNotNone(item)
        self.assertEqual(item["salary_min"], 106900)
        self.assertEqual(item["salary_max"], 176500)
        self.assertIn("Austin", item["salary_text"])

    def test_skill_detection_does_not_confuse_language_substrings(self):
        skills = detect_skills("JavaScript and NoSQL services with React.js")
        self.assertIn("JavaScript", skills)
        self.assertIn("NoSQL", skills)
        self.assertIn("React", skills)
        self.assertNotIn("Java", skills)
        self.assertNotIn("SQL", skills)
        self.assertTrue({"LLM deployment", "RAG", "Prompt engineering", "AI agents"}.issubset(
            detect_skills("Deploying LLMs into production, designing RAG pipelines, prompt engineering, and agent-based systems")
        ))

    def test_breezy_provider_uses_exact_austin_group_and_detail_location(self):
        board = (
            '<h2 class="group-header"><span>Austin, TX</span></h2><ul>'
            '<li><a href="/p/abc-staff-backend"><h2>Staff Backend Engineer</h2></a></li></ul>'
            '<h2 class="group-header"><span>Singapore</span></h2><ul>'
            '<li><a href="/p/xyz-senior-backend"><h2>Senior Backend Engineer</h2></a></li></ul>'
        )
        listings = breezy_austin_listings(board)
        self.assertEqual([item["title"] for item in listings], ["Staff Backend Engineer"])
        posting = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "url": "https://bitdeer.breezy.hr/p/abc-staff-backend?source=GoogleJobs",
            "title": "Staff Backend Engineer", "datePosted": "2026-08-25",
            "description": "Build Python distributed systems, cloud APIs, and Kubernetes infrastructure. " * 8,
            "baseSalary": {"value": {"unitText": "YEAR", "minValue": 180000, "maxValue": 260000}},
        }
        raw = (
            f'<script type="application/ld+json">{json.dumps(posting)}</script>'
            '<li class="location"><span>San Jose, CA / Austin, TX</span> - <span>Remote within</span></li>'
        )
        item = breezy_job_item("Bitdeer (NASDAQ: BTDR)", raw, listings[0]["url"])
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "breezy")
        self.assertEqual(item["salary_max"], 260000)
        self.assertNotIn("source=GoogleJobs", item["url"])
        self.assertEqual(item["work_arrangement"], "remote")
        self.assertIsNone(breezy_job_item("Bitdeer", raw.replace("Austin, TX", "Seattle, WA"), listings[0]["url"]))

    def test_pinpoint_provider_combines_full_json_with_rss_original_date(self):
        rss = '''<rss><channel><item><link>https://careers.brivo.com/jobs/564704</link><pubDate>Mon, 17 Aug 2026 18:00:00 +0000</pubDate></item></channel></rss>'''
        self.assertEqual(pinpoint_rss_dates(rss), {"564704": "2026-08-17"})
        job = {
            "title": "Senior Backend Engineer (Device Cloud Platform)",
            "url": "https://careers.brivo.com/en/postings/example",
            "description": "Build cloud-native backend services and distributed APIs. " * 8,
            "key_responsibilities": "Own Java and Python microservices on Kubernetes.",
            "skills_knowledge_expertise": "Kafka, Postgres, observability, and SRE practices.",
            "workplace_type": "onsite",
            "compensation": "$180,000 - $200,000 / year",
            "compensation_minimum": 180000,
            "compensation_maximum": 200000,
            "compensation_frequency": "year",
            "job": {"id": "564704"},
            "location": {"city": "Austin", "province": "Texas"},
        }
        fresh_date = datetime.now(timezone.utc).date().isoformat()
        item = pinpoint_job_item("Brivo", job, fresh_date)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "pinpoint")
        self.assertEqual(item["location"], "Austin, Texas")
        self.assertEqual(item["salary_max"], 200000)
        self.assertIsNone(pinpoint_job_item("Brivo", job | {"location": {"city": "Dallas", "province": "Texas"}}, fresh_date))

    def test_brivo_pinpoint_mapping_and_merged_company_identity(self):
        self.assertEqual(PINPOINT_SITES["Brivo"], "https://careers.brivo.com")
        self.assertEqual(storage.company_key("Eagle Eye Networks"), storage.company_key("Brivo"))
        self.assertEqual(storage.company_key("Brivo / Eagle Eye Networks"), storage.company_key("Brivo"))

    def test_ping_identity_acquired_brand_and_syndicated_title_share_identity(self):
        self.assertEqual(storage.company_key("SecuredTouch"), storage.company_key("Ping Identity"))
        self.assertEqual(
            storage.company_key("SecuredTouch (acquired by Ping Identity)"),
            storage.company_key("Ping Identity"),
        )
        self.assertEqual(
            storage.title_key("Staff Software Engineer, Data Engineering – Identity & AI Agent Governance"),
            storage.title_key("Staff Software Engineer, Data Engineering"),
        )

    def test_revionics_uses_first_party_austin_workday_search(self):
        config = WORKDAY_SITES["Revionics, an Aptos Company"]
        self.assertEqual(config["host"], "https://aptos.wd108.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "aptos")
        self.assertEqual(config["site"], "Revionics")
        self.assertEqual(config["search_text"], "Austin")

    def test_trendai_uses_trend_micro_public_workday_search(self):
        config = WORKDAY_SITES["TrendAI"]
        self.assertEqual(config["host"], "https://trendmicro.wd3.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "trendmicro")
        self.assertEqual(config["site"], "External")
        self.assertEqual(config["search_text"], "Austin")
        self.assertEqual(storage.company_key("Trend Micro"), storage.company_key("TrendAI"))

    def test_trimble_uses_exact_austin_workday_facet(self):
        config = WORKDAY_SITES["Trimble"]
        self.assertEqual(config["tenant"], "trimble")
        self.assertEqual(config["site"], "TrimbleCareers")
        self.assertEqual(config["applied_facets"]["locations"], ["ebb3832f7b201000fb2f72a75efd0000"])
        self.assertEqual(config["search_text"], "")

    def test_expedia_uses_exact_austin_workday_facet(self):
        config = WORKDAY_SITES["Expedia Group"]
        self.assertEqual(config["host"], "https://expedia.wd108.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "expedia")
        self.assertEqual(config["site"], "search")
        self.assertEqual(config["applied_facets"]["locations"], ["d9ad289ce9b701609c73e2940536397b"])
        self.assertEqual(config["search_text"], "")

    def test_ebay_uses_public_apply_workday_search(self):
        config = WORKDAY_SITES["eBay"]
        self.assertEqual(config["host"], "https://ebay.wd5.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "ebay")
        self.assertEqual(config["site"], "apply")
        self.assertEqual(config["search_text"], "Austin")

    def test_resideo_provider_uses_public_feed_and_exact_austin_detail(self):
        fresh_date = datetime.now(timezone.utc).date().isoformat()
        listing = {
            "title": "Staff Software Engineer - Connected Device & Platform",
            "locations": [{"city": "Austin", "state": "TX", "country": "United States"}],
            "detailUrl": "/jobs/staff-platform-engineer-austin",
        }
        self.assertEqual(len(resideo_search_listings({"jobs": [listing]})), 1)
        listing["locations"][0]["city"] = "Denver"
        self.assertEqual(resideo_search_listings({"jobs": [listing]}), [])
        posting = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Staff Software Engineer - Connected Device & Platform", "datePosted": f"{fresh_date}T12:00:00Z",
            "description": "Platform role", "identifier": {"value": "300025193091967"},
            "jobLocation": {"address": {"addressLocality": "Austin", "addressRegion": "TX", "addressCountry": "United States"}},
        }
        detail = "Build Azure distributed systems, APIs, Kubernetes, Postgres, observability, and event-driven services. " * 8
        detail += "The typical hiring salary for this role, ranges from USD $162320.0 to $225082.0 per year."
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script><div class="text-rich-text w-richtext">{detail}</div><section id="faqs">FAQ</section>'
        item = resideo_job_item(raw, "https://careers.resideo.com/jobs/staff-platform-engineer-austin")
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "resideo")
        self.assertEqual(item["salary_max"], 225082)

    def test_western_union_provider_requires_fresh_exact_austin_json_ld(self):
        listings = western_union_workday_search_listings({"jobPostings": [
            {"title": "Senior Software Engineer", "postedOn": "Posted 9 Days Ago", "externalPath": "/job/Austin/Senior-Software-Engineer_JR1"},
            {"title": "Director Application Security", "postedOn": "Posted 2 Days Ago", "externalPath": "/job/Austin/Director-Application-Security_JR2"},
            {"title": "Senior Frontend Engineer", "postedOn": "Posted 2 Days Ago", "externalPath": "/job/Austin/Senior-Frontend-Engineer_JR3"},
            {"title": "Senior Software Engineer", "postedOn": "Posted 30+ Days Ago", "externalPath": "/job/Austin/Stale_JR4"},
        ]})
        self.assertEqual([item["externalPath"] for item in listings], ["/job/Austin/Senior-Software-Engineer_JR1"])
        posting = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Staff Software Engineer - Digital Platform", "datePosted": "2026-08-25",
            "description": "Build AWS microservices, Kafka APIs, Postgres, and distributed systems. " * 8 + "Annual base salary range is $135,000 - 160,000 USD per year.",
            "identifier": {"value": "JR0130059"},
            "jobLocation": {"address": {"addressLocality": "Austin", "addressRegion": "TX", "addressCountry": "US"}},
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        item = western_union_job_item(raw, "https://careers.westernunion.com/job-details/1/staff-software-engineer-austin-tx/")
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "westernunion")
        self.assertEqual(item["location"], "Austin, TX, US")
        self.assertEqual(item["salary_max"], 160000)
        posting["jobLocation"]["address"]["addressLocality"] = "Denver"
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        self.assertIsNone(western_union_job_item(raw, "https://careers.westernunion.com/job-details/1/staff-software-engineer-denver/"))

        posting["jobLocation"]["address"]["addressRegion"] = "CO"
        current_job = {
            "primary_city": "Denver", "primary_state": "CO", "primary_country": "US",
            "addtnl_locations": [{"addtnl_city": "Austin", "addtnl_state": "TX", "addtnl_country": "US"}],
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script><script>var current_job = {json.dumps(current_job)};</script>'
        item = western_union_job_item(raw, "https://careers.westernunion.com/job-details/2/senior-security-engineer-denver-co/")
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Denver, CO, US / Austin, TX, US")

    def test_expanded_experienced_and_lead_title_band(self):
        self.assertTrue(title_is_candidate({"title": "Software Engineer II - Backend Java"}))
        self.assertTrue(title_is_candidate({"title": "Engineer II, Data (Cloud & AI)"}))
        self.assertTrue(title_is_candidate({"title": "Software Developer 3"}))
        self.assertTrue(title_is_candidate({"title": "MTS 2, Software Engineer"}))
        self.assertTrue(title_is_candidate({"title": "Senior Lead Software Engineer"}))
        self.assertTrue(title_is_candidate({"title": "Software Technical Leader, Platform"}))
        self.assertTrue(title_is_candidate({"title": "Senior Technology Lead, Engineering"}))
        self.assertTrue(title_is_candidate({"title": "Security Engineer II"}))
        self.assertTrue(title_is_candidate({"title": "Senior IAM Automation Engineer"}))
        self.assertTrue(title_is_candidate({"title": "Staff Engineer, AI Automation and Orchestration"}))
        self.assertTrue(title_is_candidate({"title": "Senior Staff Engineer - Golang"}))
        self.assertTrue(title_is_candidate({"title": "Senior ML Systems Engineer - AI Evaluation Foundations"}))
        self.assertTrue(title_is_candidate({"title": "Lead System Integration Engineer - Enterprise Transformation"}))
        self.assertFalse(title_is_candidate({"title": "Principal Software Engineer"}))
        self.assertFalse(title_is_candidate({"title": "Customer Engineer III, Platform, South, Google Cloud"}))
        self.assertFalse(title_is_candidate({"title": "Manufacturing Engineering Manager - DDP - (M4)"}))
        self.assertFalse(title_is_candidate({"title": "Sr Talent Team Lead - Software"}))

    def test_generic_staff_engineer_requires_dense_software_platform_evidence(self):
        self.assertTrue(title_is_candidate({
            "title": "Staff Engineer",
            "description": (
                "Build scalable data pipeline systems with Python, Java, Scala, Kafka, Spark, "
                "Hadoop, Postgres, Cassandra, SQL, and NoSQL. Software engineers automate "
                "delivery infrastructure and redesign services for scalability."
            ),
        }))
        self.assertFalse(title_is_candidate({
            "title": "Staff Engineer",
            "description": "Design electrical assemblies, thermal hardware, wiring, and mechanical fixtures.",
        }))

    def test_ranking_recognizes_mts_level_and_agentic_application_work(self):
        job = {
            "company": "eBay", "title": "MTS 2, Software Engineer", "location": "Austin, TX",
            "description": ("Build a Python and Kafka data platform with agentic LangGraph deployment pipelines. " * 8),
            "date_posted": "2026-08-25", "work_arrangement": "hybrid",
        }
        ranked = RankingEngine(PROFILE, set(), today=date(2026, 8, 28)).rank(job)
        self.assertGreaterEqual(ranked["fit_score"], 7)
        self.assertEqual(ranked["ai_application"], 1)
        self.assertIn("Senior-level", ranked["actual_reason"])

    def test_ebay_mts_level_uses_exact_levels_benchmark(self):
        from jobfinder.application.compensation import _benchmark_amount
        benchmark = {
            "median_total_comp": 236000,
            "senior_total_comp": 305014,
            "levels": [{"level": "MTS 2", "total_comp": 305014}],
        }
        self.assertEqual(_benchmark_amount({"title": "MTS 2, Software Engineer"}, benchmark), 305014)
        self.assertEqual(_benchmark_amount({"title": "Sr. Software Engineer, Robotaxi"}, benchmark), 305014)

    def test_homedepot_provider_requires_fresh_exact_austin_listing(self):
        fresh_date = datetime.now(timezone.utc).date()
        record = {
            "entity_status": "Open", "is_posted": True,
            "title": "Software Engineer II - Backend Java (Remote)",
            "primary_city": "Austin", "primary_state": "TX", "primary_country": "US",
            "open_date": fresh_date.strftime("%B %d, %Y"),
            "url": "https://careers.homedepot.com/job/123/software-engineer-ii/?source=test&source=test",
            "ref": "123", "location_type": "Remote",
            "level": "$80,000-$150,000",
            "description": "Build Java backend APIs, cloud services, distributed systems, and production observability. " * 8,
        }
        raw = f"<script>var current_job = {json.dumps(record)};</script>"
        item = homedepot_job_item(raw)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "homedepot")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["salary_max"], 150000)
        self.assertEqual(item["date_posted"], fresh_date.isoformat())
        self.assertEqual(item["url"].count("source="), 1)
        record["primary_city"] = "Atlanta"
        raw = f"<script>var current_job = {json.dumps(record)};</script>"
        self.assertIsNone(homedepot_job_item(raw))

    def test_homedepot_public_search_record_and_collector(self):
        record = {
            "entity_status": None,
            "title": "Staff Software Engineer - Cloud Platform (Remote)",
            "primary_city": "Austin", "primary_state": "TX", "primary_country": "US",
            "open_date": "2026-09-02T14:07:58",
            "url": "https://careers.homedepot.com/job/23797755/staff-software-engineer-cloud-platform-remote/",
            "ref": "Req191434", "location_type": "Remote",
            "level": "$170,000.00 - $250,000.00",
            "description": "Build cloud platform services, distributed systems, Java APIs, Kubernetes, and production observability. " * 8,
        }
        item = homedepot_job_record(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["provider_job_id"], "Req191434")
        self.assertEqual(item["date_posted"], "2026-09-02")
        self.assertEqual(item["salary_max"], 250000)
        self.assertEqual(storage._official_requisition_key("homedepot", item["url"]), "homedepot:23797755")

        payload = {"totalHits": 2, "searchResults": [
            {"job": record},
            {"job": dict(record, id=99, ref="ReqOver", title="Principal Software Engineer")},
        ]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        requested: list[str] = []

        def fake_urlopen(request, timeout=30):
            requested.append(request.full_url)
            return Response()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = homedepot_austin_jobs(max_pages=1, request_delay_seconds=0, search_queries=("software",))

        self.assertEqual(errors, [])
        self.assertEqual([value["provider_job_id"] for value in items], ["Req191434"])
        self.assertIn("jobsapi-google.m-cloud.io/api/job/search", requested[0])
        self.assertIn("locationFilter=", requested[0])

    def test_procore_provider_uses_filtered_links_and_exact_austin_json_ld(self):
        search = '''<a href="/jobs/search">Search</a>
        <script src="/assets/sites/controllers/jobs/filter_controller-e66637dc.js"></script>
        <a href="https://careers.procore.com/jobs/senior-platform-engineer-austin-texas-united-states">Role</a>
        <a href="https://careers.procore.com/jobs/senior-platform-engineer-austin-texas-united-states">Duplicate</a>'''
        self.assertEqual(procore_search_urls(search), ["https://careers.procore.com/jobs/senior-platform-engineer-austin-texas-united-states"])
        fresh_date = datetime.now(timezone.utc).date().isoformat()
        posting = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Senior Software Engineering Manager - AI Infrastructure",
            "datePosted": f"{fresh_date}T12:00:00Z",
            "description": "Lead Python cloud platform, distributed systems, APIs, Kubernetes, and observability engineering. " * 8 + "The base salary range is $180,000 to $260,000.",
            "identifier": {"value": "procore-123"},
            "url": "https://careers.procore.com/jobs/senior-software-engineering-manager-ai-infrastructure-austin-texas-united-states",
            "jobLocation": {"address": {"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "US"}},
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        item = procore_job_item(raw, posting["url"])
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "procore")
        self.assertEqual(item["salary_max"], 260000)
        posting["jobLocation"]["address"]["addressLocality"] = "Denver"
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        self.assertIsNone(procore_job_item(raw, posting["url"]))

    def test_official_same_title_dedupe_keeps_newest_requisition(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Official Dedupe Test", "title": "Senior Platform Software Engineer",
                    "location": "Austin, TX", "source": "oracle", "description": "Python backend platform services",
                    "easy_apply": 0, "work_arrangement": "onsite/hybrid", "salary_text": "", "salary_type": "unknown",
                }
                storage.upsert_raw_job({**base, "url": "https://example.com/new", "date_posted": "2026-08-26"})
                storage.upsert_raw_job({**base, "url": "https://example.com/old", "date_posted": "2026-08-12"})
                with storage.db() as conn:
                    row = conn.execute("SELECT url,date_posted FROM jobs WHERE company_key=?", (storage.company_key(base["company"]),)).fetchone()
                self.assertEqual((row["url"], row["date_posted"]), ("https://example.com/new", "2026-08-26"))
            finally:
                storage.DB_PATH = old_db

    def test_official_refresh_matches_same_title_requisition_by_salary(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Same Title Test", "title": "Sr Software Engineer",
                    "location": "Austin, TX", "description": "Python backend platform services " * 20,
                    "easy_apply": 0, "work_arrangement": "onsite/hybrid", "salary_text": "", "salary_type": "annual",
                }
                storage.upsert_raw_job(base | {"url": "https://linkedin.com/jobs/view/a", "source": "linkedin", "date_posted": "2026-08-25", "salary_min": 167149, "salary_max": 221500})
                storage.upsert_raw_job(base | {"url": "https://linkedin.com/jobs/view/b", "source": "linkedin", "date_posted": "2026-08-18", "salary_min": 172369, "salary_max": 221500})
                storage.upsert_raw_job(base | {"url": "https://paypal.example/jobs/a", "source": "paypal", "date_posted": "2026-08-24", "salary_min": 167149, "salary_max": 221500})
                storage.upsert_raw_job(base | {"url": "https://paypal.example/jobs/b", "source": "paypal", "date_posted": "2026-08-18", "salary_min": 172369, "salary_max": 221500})
                with storage.db() as conn:
                    rows = conn.execute("SELECT url,source,salary_min FROM jobs WHERE company='Same Title Test' ORDER BY salary_min").fetchall()
                self.assertEqual([(row["url"], row["source"], row["salary_min"]) for row in rows], [
                    ("https://paypal.example/jobs/a", "paypal", 167149),
                    ("https://paypal.example/jobs/b", "paypal", 172369),
                ])
            finally:
                storage.DB_PATH = old_db

    def test_official_refresh_preserves_known_date_and_salary_when_feed_omits_them(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Official Metadata Test", "title": "Senior Backend Software Engineer",
                    "location": "Austin, TX", "description": "Python backend platform services " * 20,
                    "easy_apply": 0, "work_arrangement": "onsite/hybrid",
                }
                first_id, _ = storage.upsert_raw_job(base | {
                    "url": "https://linkedin.com/jobs/view/metadata-test", "source": "linkedin",
                    "date_posted": "2026-08-25", "salary_text": "$210,000 - $250,000",
                    "salary_min": 210000, "salary_max": 250000, "salary_type": "posted",
                })
                refreshed_id, created = storage.upsert_raw_job(base | {
                    "url": "https://www.bain.com/careers/find-a-role/position/?jobid=metadata-test",
                    "source": "bain", "date_posted": None, "salary_text": "",
                    "salary_min": None, "salary_max": None, "salary_type": "",
                })
                with storage.db() as conn:
                    row = conn.execute("SELECT url,source,date_posted,salary_min,salary_max FROM jobs WHERE id=?", (first_id,)).fetchone()
                self.assertFalse(created)
                self.assertEqual(refreshed_id, first_id)
                self.assertEqual(row["source"], "bain")
                self.assertEqual(row["date_posted"], "2026-08-25")
                self.assertEqual((row["salary_min"], row["salary_max"]), (210000, 250000))
            finally:
                storage.DB_PATH = old_db

    def test_realtor_provider_normalizes_public_austin_record(self):
        record = {
            "id": 23584340, "title": "Staff Software Engineer, Backend",
            "primary_city": "Austin", "primary_state": "TX", "primary_country": "US",
            "addtnl_locations": [], "open_date": "2026-08-25T16:03:20Z",
            "url": "https://careers.realtor.com/job/23584340/staff-software-engineer-backend-austin-tx/",
            "description": "Build Python distributed cloud services and backend APIs. " * 8 + "Base pay range is $190,000 to $275,000.",
            "location_type": "Hybrid",
        }
        item = realtor_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "realtor")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["salary_max"], 275000)
        record["primary_city"] = "New York"
        self.assertIsNone(realtor_job_item(record))

    def test_tesla_provider_normalizes_embedded_official_job_state(self):
        record = {
            "id": "279676", "title": "Sr. Software Engineer, Factory Software",
            "location": "AUSTIN, Texas",
            "url": "/careers/search/job/sr-software-engineer-factory-software-279676",
            "jobDescription": "Build scalable server-side and backend systems.",
            "jobResponsibilities": "Lead architecture, implementation, testing, and production deployment.",
            "jobRequirements": "Python, Go, Java, Postgres, Kafka, distributed systems, CI/CD, monitoring, and logging.",
            "jobCompensationAndBenefits": "Benefits and equity eligibility.",
        }
        item = tesla_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "tesla")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertTrue(item["url"].endswith("-279676"))
        self.assertEqual(item["provider_job_id"], "279676")
        self.assertIsNone(item["date_posted"])
        record["datePosted"] = "2026-05-01"
        self.assertIsNone(tesla_job_item(record))
        record.pop("datePosted")
        record["location"] = "Palo Alto, California"
        self.assertIsNone(tesla_job_item(record))

    def test_temporal_search_reads_visible_canonical_cards(self):
        raw = """
        <a href="/careers/11111111-2222-3333-4444-555555555555">
          <span>Senior Software Engineer, Data Platform</span>
          <span><svg><path></path></svg> Austin, Texas</span>
        </a>
        <a href="/careers/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">
          <span>Staff Software Engineer, Security</span><span>United States</span>
        </a>
        """
        listings = temporal_search_listings(raw)
        self.assertEqual(len(listings), 2)
        self.assertEqual(listings[0]["title"], "Senior Software Engineer, Data Platform")
        self.assertEqual(listings[0]["location"], "Austin, Texas")
        self.assertEqual(listings[0]["url"], "https://temporal.io/careers/11111111-2222-3333-4444-555555555555")

    def test_temporal_provider_requires_fresh_explicit_austin_json_ld(self):
        posting = {
            "@type": "JobPosting",
            "title": "Senior Software Engineer, Data Platform",
            "description": "Build Go services, distributed data systems, APIs, Kubernetes, and reliable cloud infrastructure. " * 8 + "The base pay range is $180,000 - $230,000 per year.",
            "datePosted": "2026-09-01T12:00:00+00:00",
            "identifier": {"value": "11111111-2222-3333-4444-555555555555"},
            "jobLocation": {"address": {"addressLocality": "Austin, Texas"}},
            "jobLocationType": "TELECOMMUTE",
        }
        url = "https://temporal.io/careers/11111111-2222-3333-4444-555555555555"
        item = temporal_job_item(posting, url)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "temporal")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["provider_job_id"], posting["identifier"]["value"])
        self.assertEqual((item["salary_min"], item["salary_max"]), (180000, 230000))
        self.assertEqual(item["work_arrangement"], "remote")
        posting["jobLocation"]["address"]["addressLocality"] = "United States"
        self.assertIsNone(temporal_job_item(posting, url))
        posting["jobLocation"]["address"]["addressLocality"] = "Austin, Texas"
        posting["datePosted"] = "2026-04-29T12:00:00+00:00"
        self.assertIsNone(temporal_job_item(posting, url))

    def test_g2_official_ashby_board_is_configured_for_exact_austin(self):
        self.assertEqual(ASHBY_BOARDS["G2"], "G2")
        remote = {
            "title": "Senior Software Engineer",
            "location": "Remote (US)",
            "publishedAt": "2026-09-01T12:00:00+00:00",
            "jobUrl": "https://jobs.ashbyhq.com/G2/11111111-2222-3333-4444-555555555555",
        }
        self.assertFalse(ashby_posting_has_austin(remote))
        remote["secondaryLocations"] = [{
            "location": "Austin, TX",
            "address": {"postalAddress": {"addressLocality": "Austin", "addressRegion": "Texas"}},
        }]
        self.assertTrue(ashby_posting_has_austin(remote))
        hybrid = ashby_job_item("G2", remote | {
            "location": "Austin, TX",
            "secondaryLocations": [],
            "isRemote": True,
            "workplaceType": "Hybrid",
            "descriptionPlain": "Build backend and full-stack software.",
        })
        self.assertEqual(hybrid["work_arrangement"], "onsite/hybrid")

    def test_gm_provider_normalizes_fresh_austin_json_ld(self):
        record = {
            "datePosted": "2026-08-25T07:00:00+00:00",
            "hiringOrganization": {"name": "General Motors"},
            "jobLocation": [
                {"address": [{"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States of America"}]},
                {"address": [{"addressLocality": "Warren", "addressRegion": "Michigan", "addressCountry": "United States of America"}]},
            ],
            "title": "Senior Software Engineer – Microservices Platform",
            "identifier": "JR-202612620",
            "description": "Build Java and Spring Boot microservices, APIs, cloud services, Kubernetes, and observability. " * 8,
            "url": "https://search-careers.gm.com/en/jobs/jr-202612620/senior-software-engineer/",
        }
        item = gm_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "gm")
        self.assertIn("Austin, Texas", item["location"])
        self.assertEqual(item["provider_job_id"], "JR-202612620")
        record["jobLocation"][0]["address"][0]["addressLocality"] = "Detroit"
        self.assertIsNone(gm_job_item(record))

    def test_paloalto_provider_normalizes_browser_verified_json_ld(self):
        record = {
            "@type": "JobPosting",
            "datePosted": "2026-8-27",
            "hiringOrganization": {"name": "Palo Alto Networks, Inc."},
            "jobLocation": [
                {"address": {"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States"}},
                {"address": {"addressLocality": "Boston", "addressRegion": "Massachusetts", "addressCountry": "United States"}},
            ],
            "title": "Manager, Software Engineering - Cloud Infrastructure",
            "identifier": "JR-021389",
            "description": "Lead a software engineering team building distributed cloud infrastructure, CI/CD, APIs, and reliable backend services. " * 8 + "$165,000.00 - $267,500.00/yr",
            "url": "https://jobs.paloaltonetworks.com/en/job/austin/manager-software-engineering/47263/99412958512",
        }
        item = paloalto_posting_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "paloalto")
        self.assertEqual(item["location"], "Austin, TX / Multiple US locations")
        self.assertEqual(item["date_posted"], "2026-08-27")
        self.assertEqual(item["salary_max"], 267500)
        record["jobLocation"][0]["address"]["addressLocality"] = "Dallas"
        self.assertIsNone(paloalto_posting_item(record))

    def test_paloalto_public_austin_listing_extracts_only_candidate_job_paths(self):
        self.assertIn("/en/location/austin-jobs/", PALOALTO_AUSTIN_BOARD)
        raw = (
            '<a href="/en/job/new-york/manager-software-engineering-identity/47263/123">Manager</a>'
            '<a href="/en/job/new-york/principal-engineer-software/47263/124">Principal</a>'
            '<a href="/en/job/illinois/sr-staff-engineer-software/47263/125">Staff</a>'
        )
        self.assertEqual(paloalto_austin_job_paths(raw), [
            "/en/job/new-york/manager-software-engineering-identity/47263/123",
            "/en/job/illinois/sr-staff-engineer-software/47263/125",
        ])

    def test_lpl_provider_normalizes_browser_verified_json_ld(self):
        self.assertEqual(LPL_AUSTIN_BOARD, "https://career.lpl.com/search-results?keywords=Austin")
        self.assertIn("lpl", storage.OFFICIAL_JOB_SOURCES)
        fresh_date = datetime.now(timezone.utc).date().isoformat()
        record = {
            "@type": "JobPosting",
            "datePosted": fresh_date,
            "identifier": {"@type": "PropertyValue", "name": "LPL Financial", "value": "R-052354"},
            "jobLocation": [
                {"address": {"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States of America"}},
                {"address": {"addressLocality": "Fort Mill", "addressRegion": "South Carolina", "addressCountry": "United States of America"}},
            ],
            "title": "Sr. Application Security Engineer",
            "description": "Build and secure APIs, containers, Java services, CI/CD, and cloud application platforms. " * 8 + "Pay Range: $100,631.00 - $167,787.00 #LI-Hybrid",
        }
        item = lpl_posting_item(record, "https://career.lpl.com/job/R-052354/Sr-Application-Security-Engineer")
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "lpl")
        self.assertEqual(item["provider_job_id"], "R-052354")
        self.assertEqual(item["location"], "Austin, TX / Multiple US locations")
        self.assertEqual(item["salary_min"], 100631)
        self.assertEqual(item["salary_max"], 167787)
        record["jobLocation"][0]["address"]["addressLocality"] = "Dallas"
        self.assertIsNone(lpl_posting_item(record, "https://career.lpl.com/job/R-052354/Sr-Application-Security-Engineer"))

    def test_servicenow_provider_normalizes_browser_verified_json_ld(self):
        record = {
            "@type": "JobPosting",
            "datePosted": "2026-08-27",
            "identifier": "JB0070832",
            "jobLocation": {"address": {"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States"}},
            "jobLocationType": "TELECOMMUTE",
            "title": "Senior Security Software Engineer, IAM - Moveworks",
            "description": "Build production IAM software, Terraform automation, AWS and Azure cloud access, Kubernetes controls, and security observability. " * 8,
            "url": "https://careers.servicenow.com/jobs/744000142150121/senior-security-software-engineer-iam-moveworks/",
        }
        item = servicenow_posting_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "servicenow")
        self.assertEqual(item["provider_job_id"], "JB0070832")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["work_arrangement"], "remote")
        record["jobLocation"]["address"]["addressLocality"] = "Dallas"
        self.assertIsNone(servicenow_posting_item(record))
        record["jobLocation"]["address"]["addressLocality"] = "Austin"
        record["url"] = "https://example.com/jobs/744000142150121/role/"
        self.assertIsNone(servicenow_posting_item(record))

    def test_pwc_provider_normalizes_branded_portal_and_workday_record(self):
        record = {
            "@type": "JobPosting",
            "datePosted": "2026-08-25",
            "identifier": {"@type": "PropertyValue", "name": "PwC", "value": "719584WD"},
            "jobLocation": {"address": {"addressLocality": "Atlanta", "addressCountry": "United States of America"}},
            "title": "ERP AI Engineer - Manager",
            "description": "Lead Python, Java, cloud, API, data platform, and enterprise AI engineering delivery. " * 8 + "The salary range for this position is: $99,000 - $232,000.",
            "_source_url": "https://jobs-us.pwc.com/us/en/job/719584WD/ERP-AI-Engineer-Manager",
            "_all_locations": "GA-Atlanta\nTX-Austin\nTX-Dallas",
        }
        item = pwc_posting_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "pwc")
        self.assertEqual(item["provider_job_id"], "719584WD")
        self.assertEqual(item["location"], "Austin, TX / Multiple US locations")
        self.assertEqual(item["salary_min"], 99000)
        self.assertEqual(item["salary_max"], 232000)
        self.assertEqual(storage._official_requisition_key("pwc", item["url"]), "pwc:719584wd")
        changed_slug = "https://jobs-us.pwc.com/us/en/job/719584WD/Oracle-AI-Data-Analytics-Manager"
        self.assertEqual(storage._official_requisition_key("pwc", changed_slug), "pwc:719584wd")
        record["_all_locations"] = "GA-Atlanta\nTX-Dallas"
        self.assertIsNone(pwc_posting_item(record))

    def test_paypal_provider_normalizes_browser_record(self):
        fresh_date = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
        record = {
            "provider_job_id": "274922048863",
            "title": "Sr Software Engineer",
            "location": "Austin, Texas, United States of America",
            "url": "https://paypal.eightfold.ai/careers?pid=274922048863",
            "date_posted": fresh_date,
            "description": "Build Java, Go, Python, Kubernetes, Terraform, AWS, CI/CD, and distributed platform services. " * 8 + "Austin, TX | Salary: $167,149.00-221,500.00 per annum.",
        }
        item = paypal_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "paypal")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["salary_min"], 167149)
        self.assertEqual(item["salary_max"], 221500)
        self.assertEqual(storage._official_requisition_key("paypal", "https://paypal.eightfold.ai/careers/job/274922048863"), "paypal:274922048863")
        record["location"] = "San Jose, California, United States of America"
        self.assertIsNone(paypal_job_item(record))

    def test_paypal_collector_uses_public_search_and_detail_apis(self):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        search = {"data": {"count": 2, "positions": [
            {"id": 101, "name": "Staff Backend Software Engineer", "locations": ["Austin, Texas, United States of America", "San Jose, California, United States of America"], "postedTs": now_ts, "positionUrl": "/careers/job/101"},
            {"id": 102, "name": "Principal Software Engineer", "locations": ["Austin, Texas, United States of America"], "postedTs": now_ts, "positionUrl": "/careers/job/102"},
        ]}}
        detail = {"data": {
            "id": 101, "name": "Staff Backend Software Engineer",
            "locations": ["Austin, Texas, United States of America", "San Jose, California, United States of America"],
            "positionUrl": "/careers/job/101", "workLocationOption": "hybrid",
            "jobDescription": "Build Java and Python APIs, Kafka data platforms, Kubernetes services, and distributed systems. " * 10 + "Austin, Texas: ($170,000 - $250,000 Annually)",
        }}

        class Response:
            def __init__(self, payload): self.body = json.dumps(payload).encode()
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.body

        def fake_urlopen(request, timeout=30):
            return Response(detail if "position_details" in request.full_url else search)

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = paypal_austin_jobs(max_pages=1, request_delay_seconds=0)

        self.assertEqual(errors, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["provider_job_id"], "101")
        self.assertEqual(items[0]["location"], "Austin, TX / Multiple US locations")
        self.assertEqual(items[0]["salary_max"], 250000)

    def test_qualcomm_collector_uses_public_search_and_detail_apis(self):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        search = {"data": {"count": 2, "positions": [
            {"id": 201, "name": "Staff Cloud Platform Engineer", "standardizedLocations": ["Austin, TX, US", "San Diego, CA, US"], "postedTs": now_ts, "positionUrl": "/careers/job/201"},
            {"id": 202, "name": "CPU Physical Design Engineer - Staff", "standardizedLocations": ["Austin, TX, US"], "postedTs": now_ts, "positionUrl": "/careers/job/202"},
        ]}}
        detail = {"data": {
            "id": 201, "name": "Staff Cloud Platform Engineer",
            "standardizedLocations": ["Austin, TX, US", "San Diego, CA, US"],
            "positionUrl": "/careers/job/201", "workLocationOption": "hybrid",
            "jobDescription": "Build Java and Python APIs, Kafka data platforms, Kubernetes services, and distributed systems. " * 10 + "The pay range is $170,000 - $250,000.",
        }}
        requested_urls = []

        class Response:
            def __init__(self, payload): self.body = json.dumps(payload).encode()
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.body

        def fake_urlopen(request, timeout=30):
            requested_urls.append(request.full_url)
            return Response(detail if "position_details" in request.full_url else search)

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = qualcomm_austin_jobs(max_pages=1, request_delay_seconds=0)

        self.assertEqual(errors, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "qualcomm")
        self.assertEqual(items[0]["provider_job_id"], "201")
        self.assertEqual(items[0]["location"], "Austin, TX / Multiple US locations")
        self.assertEqual(items[0]["salary_max"], 250000)
        self.assertIn("domain=qualcomm.com", requested_urls[0])
        self.assertEqual(storage._official_requisition_key("qualcomm", items[0]["url"]), "qualcomm:201")
        rejected = dict(detail["data"])
        rejected["standardizedLocations"] = ["San Diego, CA, US"]
        self.assertIsNone(qualcomm_job_item({
            "provider_job_id": "201", "title": rejected["name"],
            "locations": rejected["standardizedLocations"], "url": rejected["positionUrl"],
            "date_posted": datetime.now(timezone.utc).date().isoformat(),
            "description": rejected["jobDescription"],
        }))

    def test_jpmorgan_provider_normalizes_fresh_austin_hcm_record(self):
        detail = {
            "Id": "210782628", "Title": "Sr Lead Software Engineer - Platform Engineering",
            "ExternalPostedStartDate": "2026-08-25T23:15:07+00:00",
            "PrimaryLocation": "Austin, TX, United States",
            "workLocation": [{"TownOrCity": "Austin", "Region2": "TX", "Country": "US"}],
            "ExternalDescriptionStr": "Build Java and Python distributed cloud platforms, APIs, Kubernetes, Kafka, and observability. " * 8 + "Base salary $180,000-$260,000.",
            "ExternalResponsibilitiesStr": "", "ExternalQualificationsStr": "", "WorkplaceType": "Hybrid",
        }
        item = jpmorgan_job_item(detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "jpmorgan")
        self.assertEqual(item["provider_job_id"], "210782628")
        self.assertEqual(item["salary_max"], 260000)
        detail["PrimaryLocation"] = "Jersey City, NJ, United States"
        detail["workLocation"] = []
        self.assertIsNone(jpmorgan_job_item(detail))

    def test_teamtailor_provider_normalizes_fullstack_austin_json_ld(self):
        record = {
            "title": "Senior Fullstack AI Engineer (React, Python)",
            "description": "Design Python APIs, React interfaces, distributed services, and cloud deployments. " * 8,
            "identifier": {"value": "8182099"},
            "datePosted": "2026-09-03T13:31:49+02:00",
            "jobLocation": [{"address": {"addressLocality": "Austin", "addressCountry": "US"}}],
        }
        item = teamtailor_job_item("TeamViewer", record, "https://careers.teamviewer.com/jobs/8182099-role")
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "teamtailor")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["provider_job_id"], "8182099")
        self.assertTrue(posting_is_relevant(item))
        record["jobLocation"][0]["address"]["addressLocality"] = "Berlin"
        self.assertIsNone(teamtailor_job_item("TeamViewer", record, "https://careers.teamviewer.com/jobs/8182099-role"))

    def test_teamtailor_search_parser_keeps_unique_canonical_job_links(self):
        raw = '''
        <a href="https://careers.teamviewer.com/jobs/8182099-senior-fullstack-ai-engineer">
          <h3 title="Senior Fullstack AI Engineer">Senior Fullstack AI Engineer</h3>
        </a>
        <a href="/jobs/8182099-senior-fullstack-ai-engineer?source=copy">
          <h3 title="Senior Fullstack AI Engineer">Senior Fullstack AI Engineer</h3>
        </a>
        '''
        self.assertEqual(teamtailor_search_listings(raw, "https://careers.teamviewer.com"), [{
            "url": "https://careers.teamviewer.com/jobs/8182099-senior-fullstack-ai-engineer",
            "title": "Senior Fullstack AI Engineer",
        }])

    def test_teamtailor_search_parser_finds_same_board_show_more_page(self):
        raw = '''
        <a href="/jobs/show_more?location=Austin&amp;page=2">Show 8 more</a>
        '''
        self.assertEqual(
            teamtailor_next_page_url(raw, "https://careers.teamviewer.com"),
            "https://careers.teamviewer.com/jobs/show_more?location=Austin&page=2",
        )

    def test_recruitee_provider_uses_original_date_and_exact_austin_address(self):
        fresh_date = datetime.now(timezone.utc).date().isoformat()
        posting = {
            "@context": "http://schema.org",
            "@type": "JobPosting",
            "title": "Senior Software Engineer – AI-Native Platform",
            "datePosted": fresh_date,
            "description": "Build reliable Python and Go distributed systems, cloud APIs, data platforms, and AI-assisted services. " * 8,
            "jobLocation": [{
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressCountry": "US",
                    "addressLocality": "Austin",
                    "addressRegion": "TX",
                },
            }],
        }
        url = "https://careers.lansweeper.com/o/senior-software-engineer-ai-native-platform"
        item = recruitee_job_item("Lansweeper", posting, url)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "recruitee")
        self.assertEqual(item["date_posted"], fresh_date)
        self.assertIn("recruitee", storage.OFFICIAL_JOB_SOURCES)

        posting["datePosted"] = "2026-05-08"
        self.assertIsNone(recruitee_job_item("Lansweeper", posting, url))
        posting["datePosted"] = fresh_date
        posting["jobLocation"][0]["address"]["addressLocality"] = "Dallas"
        self.assertIsNone(recruitee_job_item("Lansweeper", posting, url))

    def test_schwab_provider_parses_search_and_austin_json_ld(self):
        search = '''<section id="search-results-list"><ul><li><a href="/job/austin/sr-java/1/2" data-job-id="2">
        <h2>Sr. Java Software Engineer</h2><span class="job-location">Austin, TX</span></a></li></ul></section>'''
        listings = schwab_search_listings(search)
        self.assertEqual(listings, [{"path": "/job/austin/sr-java/1/2", "title": "Sr. Java Software Engineer", "location": "Austin, TX"}])
        posting = {
            "@type": "JobPosting", "title": "Sr. Java Software Engineer", "datePosted": "2026-8-25",
            "description": "Build Java Spring Boot APIs, Kafka services, distributed systems, cloud deployments, and CI/CD. " * 8,
            "identifier": "2026-121258", "url": "https://www.schwabjobs.com/job/austin/sr-java/1/2",
            "hiringOrganization": {"name": "Charles Schwab"},
            "jobLocation": [{"address": {"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States"}}],
            "baseSalary": {"value": {"minValue": 145000, "maxValue": 155000}},
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        item = schwab_job_item(raw)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "schwab")
        self.assertEqual(item["salary_max"], 155000)
        self.assertEqual(item["date_posted"], "2026-08-25")

    def test_capitalone_provider_parses_dated_austin_cards_and_location_pay(self):
        search = '''<section id="search-results-list"><ul><li><a href="/job/austin/staff-platform/1732/1001" data-job-id="1001">
        <span class="job-date-posted">09/03/2026</span><h2>Staff Platform Engineer</h2>
        <span class="job-location">Austin, TX</span></a></li></ul></section>'''
        self.assertEqual(capitalone_search_listings(search), [{
            "path": "/job/austin/staff-platform/1732/1001",
            "provider_job_id": "1001",
            "title": "Staff Platform Engineer",
            "location": "Austin, TX",
            "date_posted": "09/03/2026",
        }])
        posting = {
            "@type": "JobPosting", "title": "Staff Platform Engineer", "datePosted": "2026-9-3",
            "description": "Build distributed Python cloud platform services, Kubernetes APIs, Kafka, and observability. " * 8
                + "Austin, TX: $180,000 - $225,000. New York, NY: $210,000 - $260,000.",
            "identifier": "R123456", "url": "https://www.capitalonecareers.com/job/austin/staff-platform/1732/1001",
            "hiringOrganization": {"name": "Capital One"},
            "jobLocation": [
                {"address": {"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States"}},
                {"address": {"addressLocality": "New York", "addressRegion": "New York", "addressCountry": "United States"}},
            ],
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        item = capitalone_job_item(raw)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "capitalone")
        self.assertEqual(item["date_posted"], "2026-09-03")
        self.assertEqual(item["salary_max"], 225000)
        self.assertIn("Austin, Texas", item["location"])
        self.assertIn("capitalone", storage.OFFICIAL_JOB_SOURCES)
        posting["datePosted"] = "2026-05-01"
        self.assertIsNone(capitalone_job_item(f'<script type="application/ld+json">{json.dumps(posting)}</script>'))
        posting["datePosted"] = "2026-09-03"
        posting["jobLocation"][0]["address"]["addressLocality"] = "Dallas"
        self.assertIsNone(capitalone_job_item(f'<script type="application/ld+json">{json.dumps(posting)}</script>'))

    def test_arm_provider_parses_talentbrew_cards_and_exact_austin_job(self):
        search = '''<ul id="search-results-jobs" data-results-count="1"><li class="job-card fs-start">
        <a class="job-card__title" href="/job/austin/senior-devops-engineer/33099/100122542736" data-job-id="100122542736">Senior DevOps Engineer</a>
        <span class="location">Austin, Texas</span><span class="category">Software Engineering</span></li></ul>'''
        self.assertEqual(arm_search_listings(search), [{
            "path": "/job/austin/senior-devops-engineer/33099/100122542736",
            "provider_job_id": "100122542736",
            "title": "Senior DevOps Engineer",
            "location": "Austin, Texas",
            "category": "Software Engineering",
        }])
        posting = {
            "@type": "JobPosting", "title": "Senior DevOps Engineer", "datePosted": "2026-9-3",
            "description": "Build and operate cloud CI/CD platforms, Kubernetes services, APIs, and observability systems. " * 8,
            "identifier": "2026-19369", "url": "https://careers.arm.com/job/austin/senior-devops-engineer/33099/100122542736",
            "jobLocation": [{"address": {"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States"}}],
            "baseSalary": {"currency": "USD", "value": {"minValue": 161500, "maxValue": 218500, "unitText": "YEAR"}},
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        item = arm_job_item(raw)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "arm")
        self.assertEqual(item["date_posted"], "2026-09-03")
        self.assertEqual(item["salary_max"], 218500)
        self.assertTrue(is_austin_proper_location(item["location"]))
        self.assertIn("arm", storage.OFFICIAL_JOB_SOURCES)

    def test_partial_chunked_html_is_retained_for_source_resilience(self):
        class DroppedResponse:
            def read(self, _limit):
                raise http.client.IncompleteRead(b"<html><body>partial but parseable</body></html>")
        self.assertEqual(_response_body(DroppedResponse(), 100), b"<html><body>partial but parseable</body></html>")

    def test_deloitte_provider_parses_filtered_austin_job_page(self):
        posting = {
            "@context": "https://schema.org/", "@type": "JobPosting",
            "title": "Digital Workspace Platforms Engineering Manager",
            "description": "Lead software engineering for cloud platforms, APIs, and distributed services. " * 8 + "A reasonable estimate of the current range is $131,000 - $244,900.",
            "datePosted": "2026-08-26", "identifier": {"value": "364256"},
        }
        display = dict(posting, title="Digital Workspace Platforms Engineering Manager", identifier=None)
        raw = (
            '<article class="article--result"><a href="https://apply.deloitte.com/en_US/careers/JobDetail/Digital-Workspace-Platforms-Engineering-Manager/364256">'
            'Digital Workspace Platforms Engineering Manager</a><span>Deloitte US</span><span>Austin, Texas, United States</span></article>'
            f'<script type="application/ld+json">{json.dumps(posting)}</script>'
            f'<script type="application/ld+json">{json.dumps(display)}</script>'
            '<p class="paragraph">Austin, Texas, United States</p>'
        )
        self.assertEqual(deloitte_search_listings(raw), [{
            "url": "https://apply.deloitte.com/en_US/careers/JobDetail/Digital-Workspace-Platforms-Engineering-Manager/364256",
            "title": "Digital Workspace Platforms Engineering Manager", "location": "Austin, Texas, United States",
        }])
        filtered = raw.replace("Austin, Texas, United States", "Multiple Locations", 1)
        self.assertEqual(deloitte_search_listings(filtered, "Austin, Texas, United States")[0]["location"], "Austin, Texas, United States")
        url = "https://apply.deloitte.com/en_US/careers/JobDetail/Digital-Workspace-Platforms-Engineering-Manager/364256"
        item = deloitte_job_item(raw, url)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "deloitte")
        self.assertEqual(item["salary_max"], 244900)
        self.assertEqual(item["provider_job_id"], "364256")
        self.assertEqual(item["title"], "Digital Workspace Platforms Engineering Manager")
        self.assertIsNone(deloitte_job_item(raw, url, confirmed_location="Dallas, TX"))

    def test_deloitte_collector_uses_stable_official_austin_filter(self):
        url = "https://apply.deloitte.com/en_US/careers/JobDetail/Staff-Software-Engineer/365001"
        search = (
            f'<article class="article--result"><a href="{url}">Staff Software Engineer</a>'
            '<span>Deloitte US</span><span>Multiple Locations</span></article>'
        )
        posting = {
            "@type": "JobPosting", "title": "Staff Software Engineer",
            "datePosted": datetime.now(timezone.utc).date().isoformat(),
            "description": "Build secure Python APIs, distributed cloud services, and data platforms. " * 8,
            "identifier": {"value": "365001"},
        }
        detail = f'<script type="application/ld+json">{json.dumps(posting)}</script>'

        class Response:
            def __init__(self, body): self.body = body.encode()
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.body

        requested: list[str] = []

        def fake_urlopen(request, timeout=30):
            requested.append(request.full_url)
            return Response(detail if "/JobDetail/" in request.full_url else search)

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = deloitte_austin_jobs(max_pages=1, request_delay_seconds=0, search_delay_seconds=0)

        self.assertEqual(errors, [])
        self.assertEqual([item["provider_job_id"] for item in items], ["365001"])
        self.assertIn("9336=%5B690392%5D", requested[0])
        self.assertIn("9337=%5B2818%5D", requested[0])
        self.assertEqual(items[0]["location"], "Austin, TX")

    def test_deloitte_collector_retries_transient_connection_reset(self):
        search_url = "https://apply.deloitte.com/en_US/careers/JobDetail/Staff-Software-Engineer/365001"
        search = (
            f'<article class="article--result"><a href="{search_url}">Staff Software Engineer</a>'
            '<span>Deloitte US</span><span>Multiple Locations</span></article>'
        )
        posting = {
            "@type": "JobPosting", "title": "Staff Software Engineer",
            "datePosted": datetime.now(timezone.utc).date().isoformat(),
            "description": "Build secure Python APIs, distributed cloud services, and data platforms. " * 8,
            "identifier": {"value": "365001"},
        }
        detail = f'<script type="application/ld+json">{json.dumps(posting)}</script>'

        class Response:
            def __init__(self, body): self.body = body.encode()
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.body

        responses = [ConnectionResetError("reset"), Response(search), Response(detail)]
        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=responses), patch("jobfinder.infrastructure.providers.time.sleep"):
            items, errors = deloitte_austin_jobs(max_pages=1, request_delay_seconds=0, search_delay_seconds=0)

        self.assertEqual(errors, [])
        self.assertEqual([item["provider_job_id"] for item in items], ["365001"])

    def test_cisco_provider_requires_fresh_explicit_austin_location(self):
        fresh_date = datetime.now(timezone.utc).date().isoformat()
        detail = {"jobDetail": {"data": {"job": {
            "jobId": "2021235", "title": "Senior Software Engineer (Remote)",
            "multi_location": ["Portland, Oregon, United States of America", "Austin, Texas, United States of America"],
            "postedDate": f"{fresh_date}T00:00:00.000+0000", "RemoteType": "Remote",
            "description": "Build secure Python APIs and distributed cloud platform services. Base Pay Range: $139,300 - $203,600. " * 8,
        }}}}
        raw = f"<script>phApp.ddo = {json.dumps(detail)}; phApp.experimentData = {{}};</script>"
        item = cisco_job_item(raw)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "cisco")
        self.assertEqual(item["provider_job_id"], "2021235")
        self.assertEqual(item["work_arrangement"], "remote")
        self.assertEqual(item["salary_max"], 203600)
        detail["jobDetail"]["data"]["job"]["multi_location"] = ["Portland, Oregon, United States of America"]
        raw = f"<script>phApp.ddo = {json.dumps(detail)}; phApp.experimentData = {{}};</script>"
        self.assertIsNone(cisco_job_item(raw))

    def test_cisco_collector_stops_at_public_austin_facet_count(self):
        posted = datetime.now(timezone.utc).date().isoformat()
        listing = {
            "jobId": "2021235", "title": "Senior Software Engineer (Remote)",
            "multi_location": ["Portland, Oregon, United States of America", "Austin, Texas, United States of America"],
            "postedDate": posted,
        }
        search = {"eagerLoadRefineSearch": {"data": {
            "jobs": [listing],
            "aggregations": [{"field": "city", "value": {"Austin": 1}}],
        }}}
        detail = {"jobDetail": {"data": {"job": {
            **listing, "RemoteType": "Remote",
            "description": "Build secure Python APIs and distributed cloud platform services. " * 8,
        }}}}
        wrap = lambda value: f"<script>phApp.ddo = {json.dumps(value)}; phApp.experimentData = {{}};</script>"

        class Response:
            def __init__(self, body): self.body = body.encode()
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.body

        requested: list[str] = []

        def fake_urlopen(request, timeout=30):
            requested.append(request.full_url)
            return Response(wrap(detail if "/job/2021235/" in request.full_url else search))

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = cisco_austin_jobs(max_pages=130, request_delay_seconds=0)

        self.assertEqual(errors, [])
        self.assertEqual([item["provider_job_id"] for item in items], ["2021235"])
        self.assertEqual(len([url for url in requested if "search-results" in url]), 1)
        self.assertEqual(storage._official_requisition_key("cisco", items[0]["url"]), "cisco:2021235")

    def test_ibm_avature_provider_requires_explicit_austin_location(self):
        record = {
            "title": "Confluent - Staff Software Engineer - Infrastructure",
            "official_location": "Austin / Texas / United States",
            "url": "https://careers.ibm.com/en_US/careers/JobDetail/Confluent-Staff-Software-Engineer-Infrastructure/130914",
            "job_id": "130914",
            "date_posted": "2026-09-01",
            "description": "Build secure cloud infrastructure, distributed systems, backend APIs, and Kubernetes platform services. " * 8,
            "work_arrangement": "remote",
        }
        item = ibm_avature_posting_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "avature")
        self.assertEqual(item["provider_job_id"], "130914")
        self.assertEqual(item["location"], "Austin, TX / Multiple US locations")
        self.assertIsNone(ibm_avature_posting_item(dict(record, official_location="Lowell / Massachusetts / United States")))

    def test_ea_avature_provider_requires_fresh_exact_austin_detail(self):
        record = {
            "title": "Cloud Engineer",
            "canonical_title": "Senior Cloud Engineer",
            "official_location": "Austin, Texas, United States of America",
            "url": "https://jobs.ea.com/en_US/careers/JobDetail/Senior-Cloud-Engineer/215349",
            "job_id": "215349",
            "date_posted": "2026-09-01",
            "description": "Build scalable AWS infrastructure, Kubernetes platforms, backend microservices, and CI/CD automation. " * 8,
            "work_arrangement": "hybrid",
        }
        item = ea_avature_posting_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["title"], "Senior Cloud Engineer")
        self.assertEqual(item["provider_job_id"], "215349")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(storage._official_requisition_key("avature", item["url"]), "ea:215349")
        self.assertIsNone(ea_avature_posting_item(dict(record, official_location="Orlando, Florida, United States of America")))

    def test_ibm_public_search_adapter_keeps_only_explicit_austin_texas_hits(self):
        source = {
            "title": "Senior Software Engineer - Austin, TX",
            "url": "https://careers.ibm.com/careers/JobDetail?jobId=131607",
            "body": "Build distributed cloud infrastructure and backend platform services. " * 10,
            "dcdate": "2026-09-03",
            "field_keyword_05": "United States",
            "field_keyword_17": "Hybrid",
            "field_keyword_19": "Austin, US",
        }
        item = ibm_search_job_item(source)
        self.assertIsNotNone(item)
        self.assertEqual(item["provider_job_id"], "131607")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(storage._official_requisition_key("avature", item["url"]), "ibm:131607")
        self.assertIsNone(ibm_search_job_item(dict(source, title="Senior Software Engineer", field_keyword_19="Multiple Cities")))

        response = {"hits": {"hits": [{"_source": source}]}}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(response).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            items, errors = ibm_austin_jobs()
        self.assertEqual(errors, [])
        self.assertEqual([value["provider_job_id"] for value in items], ["131607"])

    def test_salesforce_provider_requires_fresh_explicit_austin_detail(self):
        record = {
            "title": "Enterprise Security Engineer, Senior & Lead",
            "official_locations": ["California - San Francisco", "Texas - Austin"],
            "url": "https://www.salesforce.com/company/careers/jobs/JR345894/enterprise-security-engineer/",
            "provider_job_id": "JR345894",
            "date_posted": "2026-08-31",
            "description": "Secure AI platforms, automate security tooling, review code, and protect distributed cloud services. " * 8,
        }
        item = salesforce_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "salesforce")
        self.assertEqual(item["provider_job_id"], "JR345894")
        self.assertEqual(item["location"], "Austin, TX / Multiple US locations")
        self.assertIsNone(salesforce_job_item(dict(record, official_locations=["Texas - Dallas"])))

    def test_salesforce_collector_uses_public_full_jobs_feed(self):
        record = {
            "Job_Posting_Title": "Senior Software Engineer — Data Platform",
            "Job_Requisition_Ref_ID": "JR359999",
            "Job_Requisition_Primary_Location": "California - San Francisco",
            "Job_Requisition_Additional_Locations": "Texas - Dallas; Texas - Austin",
            "External_Job_Posting_Start_Date": "2026-09-03",
            "Job_Description": "<p>Build distributed cloud data infrastructure, backend APIs, Kafka services, and Kubernetes platforms.</p>" * 8,
            "Pay_Transparency_Text_if_location_region_is__Non-Sales-NAT_US___Geo_A_SEL_": "The typical base salary range is $150,000 - $240,000 annually.",
        }
        payload = {"Report_Entry": [record, dict(record, Job_Requisition_Ref_ID="JR359998", Job_Requisition_Additional_Locations="Texas - Dallas")]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()) as urlopen:
            items, errors = salesforce_austin_jobs(request_delay_seconds=0)

        self.assertEqual(errors, [])
        self.assertEqual([item["provider_job_id"] for item in items], ["JR359999"])
        self.assertEqual(items[0]["url"], "https://www.salesforce.com/company/careers/jobs/JR359999/senior-software-engineer-data-platform/")
        self.assertEqual(items[0]["salary_min"], 150000)
        self.assertEqual(storage._official_requisition_key("salesforce", items[0]["url"]), "salesforce:jr359999")
        self.assertIn("jobs_2.json", urlopen.call_args.args[0].full_url)
        self.assertIsNotNone(salesforce_feed_job_item(record))

    def test_meta_provider_requires_fresh_explicit_austin_detail(self):
        record = {
            "title": "Staff Software Engineer, AI Infrastructure",
            "official_locations": ["Menlo Park, CA", "Austin, TX"],
            "url": "https://www.metacareers.com/profile/job_details/1234567890",
            "date_posted": datetime.now(timezone.utc).date().isoformat(),
            "description": "Build backend services, distributed systems, and cloud AI infrastructure. " * 8,
        }
        item = meta_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "meta")
        self.assertEqual(item["provider_job_id"], "1234567890")
        self.assertEqual(item["location"], "Austin, TX / Multiple US locations")
        self.assertIsNone(meta_job_item(dict(record, official_locations=["Menlo Park, CA"])))

    def test_meta_collector_uses_anonymous_search_and_json_ld_details(self):
        listing = {
            "id": "1234567890",
            "title": "Staff Software Engineer, AI Infrastructure",
            "locations": ["Menlo Park, CA", "Austin, TX"],
            "teams": ["Infrastructure"],
            "sub_teams": ["Engineering"],
        }
        manager_listing = {
            "id": "939416365875204",
            "title": "Data Platform & Governance Manager",
            "locations": ["Austin, TX", "Menlo Park, CA"],
        }
        posting = {
            "@type": "JobPosting",
            "title": listing["title"],
            "datePosted": datetime.now(timezone.utc).isoformat(),
            "jobLocation": [
                {"@type": "Place", "name": "Menlo Park, CA"},
                {"@type": "Place", "name": "Austin, TX"},
            ],
            "description": "Build backend services and distributed AI infrastructure.",
            "responsibilities": "Own cloud platforms, APIs, and Kubernetes reliability.",
            "qualifications": "Eight years of Python and systems engineering experience.",
        }
        manager_posting = {
            "@type": "JobPosting",
            "title": manager_listing["title"],
            "datePosted": datetime.now(timezone.utc).isoformat(),
            "jobLocation": [{"@type": "Place", "name": "Austin, TX"}],
            "description": "Lead data engineering and manage and grow a team of data engineers building distributed warehouses, backend pipelines, and cloud data infrastructure. " * 8,
        }
        search_html = '<script>["LSD",[],{"token":"public-anonymous-token"}]</script>'
        search_payload = {"data": {"job_search_with_featured_jobs_v2": {"all_jobs": [listing, manager_listing]}}}
        detail_html = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        manager_detail_html = f'<script type="application/ld+json">{json.dumps(manager_posting)}</script>'

        class Response:
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.value.encode()

        responses = [Response(search_html), Response(json.dumps(search_payload)), Response(detail_html), Response(manager_detail_html)]
        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=responses) as urlopen, patch("jobfinder.infrastructure.providers.time.sleep"):
            items, errors = meta_austin_jobs(request_delay_seconds=0)

        self.assertEqual(errors, [])
        self.assertEqual([item["provider_job_id"] for item in items], ["1234567890", "939416365875204"])
        self.assertEqual(items[0]["location"], "Austin, TX / Multiple US locations")
        self.assertIn("Kubernetes reliability", items[0]["description"])
        self.assertEqual(items[1]["location"], "Austin, TX")
        self.assertTrue(posting_is_austin_relevant(items[1]))
        self.assertEqual(storage._official_requisition_key("meta", items[0]["url"]), "meta:1234567890")
        self.assertEqual(urlopen.call_count, 4)

    def test_uber_provider_requires_fresh_explicit_austin_detail(self):
        record = {
            "title": "Staff Software Engineer, Backend Platform",
            "official_locations": ["Austin, Texas", "San Francisco, California"],
            "url": "https://jobs.uber.com/en/jobs/155811/",
            "date_posted": "2026-09-02",
            "description": "Build backend services, distributed systems, and cloud platform infrastructure. " * 8,
        }
        item = uber_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "uber")
        self.assertEqual(item["provider_job_id"], "155811")
        self.assertEqual(item["location"], "Austin, TX / Multiple US locations")
        self.assertIsNone(uber_job_item(dict(record, official_locations=["Sunnyvale, California"])))

    def test_walmart_provider_requires_fresh_explicit_austin_detail(self):
        record = {
            "title": "(USA) Senior, Software Engineer",
            "official_location": "Austin, TX 78701",
            "url": "https://careers.walmart.com/us/en/jobs/R-2615425",
            "date_posted": "2026-09-02",
            "description": "Build backend services, distributed systems, and cloud platform infrastructure. " * 8,
        }
        item = walmart_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "walmart")
        self.assertEqual(item["provider_job_id"], "R-2615425")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertIsNone(walmart_job_item(dict(record, official_location="Bentonville, AR")))

    def test_accenture_provider_requires_fresh_explicit_austin_jsonld(self):
        posting = {
            "@type": "JobPosting",
            "title": "AI Native Software Engineering Manager",
            "datePosted": "2026-09-01T20:25:29-07:00",
            "jobLocation": [
                {"address": {"addressLocality": "Austin", "addressRegion": "TX", "addressCountry": "USA"}},
                {"address": {"addressLocality": "Chicago", "addressRegion": "IL", "addressCountry": "USA"}},
            ],
            "identifier": {"value": "R00353532"},
            "description": "Build cloud-native AI agents and backend services.",
            "qualifications": "Python, Java, Kubernetes, distributed systems, and platform observability. " * 8,
            "_source_url": "https://www.accenture.com/us-en/careers/jobdetails?id=R00353532_en",
        }
        item = accenture_job_item(posting)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "accenture")
        self.assertEqual(item["provider_job_id"], "R00353532")
        self.assertEqual(item["location"], "Austin, TX / Multiple US locations")
        self.assertEqual(item["salary_text"], "")
        self.assertIsNone(item["salary_min"])
        self.assertIsNone(accenture_job_item(dict(posting, jobLocation=posting["jobLocation"][1:])))

    def test_accenture_search_feed_normalizes_full_record_and_stable_requisition(self):
        record = {
            "requisitionId": "R00353532",
            "title": "AI Native Software Engineering Manager",
            "updateDate": "2026-09-01T20:25:29.770-07:00",
            "location": ["Austin, TX", "Chicago, IL"],
            "jobDescriptionClean": "Build cloud-native AI agents and backend services. " * 8,
            "qualificationClean": "Python, Java, Kubernetes, distributed systems, and platform observability. " * 8,
            "workdaySkill": ["Cloud Architecture", "Software Engineering"],
            "remoteType": "Hybrid Eligible",
        }
        item = accenture_search_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["url"], "https://www.accenture.com/us-en/careers/jobdetails?id=R00353532_en")
        self.assertEqual(item["provider_job_id"], "R00353532")
        self.assertEqual(item["work_arrangement"], "hybrid")
        self.assertIn("Cloud Architecture", item["description"])
        self.assertEqual(
            storage._official_requisition_key("accenture", item["url"]),
            "accenture:r00353532",
        )
        self.assertIsNone(accenture_search_job_item(record | {"location": ["Chicago, IL"]}))

    def test_oracle_provider_normalizes_public_austin_detail(self):
        detail = {
            "Id": "338844", "Title": "Senior Software Development Engineer",
            "ExternalPostedStartDate": "2026-08-25T17:27:49+00:00",
            "PrimaryLocation": "United States",
            "secondaryLocations": [{"Name": "Austin, TX, United States"}],
            "ExternalDescriptionStr": "Build secure cloud infrastructure and distributed systems.",
            "ExternalResponsibilitiesStr": "Design backend APIs and operate production services. " * 6,
            "ExternalQualificationsStr": "US: Hiring Range in USD from: $179,200 to $259,500 per annum.",
            "WorkplaceType": "On-site",
            "requisitionFlexFields": [{"Prompt": "Does this position require a security clearance?", "Value": "No"}],
        }
        item = oracle_job_item(detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "oracle")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["salary_max"], 259500)
        self.assertTrue(item["url"].endswith("/338844"))
        detail["requisitionFlexFields"][0]["Value"] = "Yes"
        self.assertIsNone(oracle_job_item(detail))

    def test_oracle_search_accepts_primary_austin_location(self):
        self.assertTrue(oracle_listing_has_austin({
            "PrimaryLocation": "Austin, TX, United States",
            "secondaryLocations": [],
        }))
        self.assertTrue(oracle_listing_has_austin({
            "PrimaryLocation": "United States",
            "workLocation": [{"TownOrCity": "Austin", "Region2": "Texas", "Country": "United States"}],
        }))
        self.assertFalse(oracle_listing_has_austin({"PrimaryLocation": "Seattle, WA, United States"}))

    def test_oracle_search_covers_expanded_target_families(self):
        self.assertTrue({
            "software developer", "software development manager", "site reliability engineer",
            "platform engineer", "infrastructure engineer", "data engineer", "cloud engineer",
            "security engineer", "technical lead",
        }.issubset(ORACLE_SEARCH_QUERIES))

    def test_supply_chain_platform_planner_is_not_a_software_role(self):
        self.assertFalse(title_is_candidate({
            "title": "Senior Supply Demand Planner – Manufacturer Platform Planning",
            "description": "Plan cloud hardware supply and platform capacity.",
        }))

    def test_microsoft_provider_normalizes_public_position_detail(self):
        detail = {
            "name": "Senior Backend Software Engineer",
            "standardizedLocations": ["Austin, TX, US", "Redmond, WA, US"],
            "postedTs": 1787665121,
            "jobDescription": "Build Python distributed cloud services. " * 10 + "The typical base pay range is USD $119,800 - $234,700 per year.",
            "publicUrl": "https://apply.careers.microsoft.com/careers/job/123",
            "workLocationOption": "onsite",
            "efcustomTextWorkSite": ["0 days / week in-office – remote"],
        }
        item = microsoft_job_item(detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["date_posted"], "2026-08-25")
        self.assertEqual(item["salary_max"], 234700)
        self.assertEqual(item["work_arrangement"], "remote")

    def test_bain_provider_requires_known_fresh_date_and_uses_texas_salary(self):
        listing = {
            "JobId": "108807",
            "JobTitle": "Senior AI/ML Engineer",
            "JobDescription": (
                "Build production Python RAG systems. In Atlanta, the annualized salary range is "
                "$128,000 - $153,750. In Texas, the annualized salary range is $134,500 - $161,500."
            ),
            "Link": "/careers/find-a-role/position/?jobid=108807",
            "Location": ["Atlanta ", " Austin ", " Dallas "],
        }
        item = bain_job_item(listing, date.today().isoformat())
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["source"], "bain")
        self.assertEqual(item["salary_min"], 134500.0)
        self.assertEqual(item["salary_max"], 161500.0)
        self.assertIn("jobid=108807", item["url"])
        self.assertIsNone(bain_job_item(listing, None))

    def test_google_provider_normalizes_public_detail_payload(self):
        record = [None] * 21
        record[0] = "123"
        record[1] = "Senior Backend Software Engineer"
        record[3] = [None, "Build and test distributed services."]
        record[4] = [None, "Five years of Python backend experience."]
        record[9] = [["Austin, TX, USA", ["Austin, TX, USA"], "Austin", None, "TX", "US"]]
        record[10] = [None, "Cloud platform APIs and event systems. US: $174000 - $252000 (USD) + equity."]
        record[14] = [1787665121, 300000000]
        record[19] = [None, "Experience with Kafka and databases."]
        raw = "AF_initDataCallback({key: 'ds:0', hash: '1', data:" + json.dumps([record]) + ", sideChannel: {}});"
        item = google_job_item("jobs/results/123-senior-backend-software-engineer", raw)
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["date_posted"], "2026-08-25")
        self.assertEqual(item["salary_max"], 252000)
        self.assertEqual(item["source"], "google")
        links = google_search_paths('href="jobs/results/123-senior-backend-software-engineer?q=x" href="jobs/results/123-senior-backend-software-engineer"')
        self.assertEqual(links, ["jobs/results/123-senior-backend-software-engineer"])

    def test_ashby_provider_normalizes_public_job_and_freshness(self):
        record = {
            "title": "Staff Backend Software Engineer",
            "location": "New York City Office",
            "secondaryLocations": [{"location": "Remote US"}],
            "publishedAt": "2026-08-25T12:00:00+00:00",
            "isListed": True,
            "isRemote": True,
            "jobUrl": "https://jobs.ashbyhq.com/plaid/example",
            "descriptionPlain": "Build Python distributed systems and cloud APIs. " * 10 + "Base Salary $207,600 - $306,600.",
        }
        item = ashby_job_item("Plaid", record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "ashby")
        self.assertEqual(item["work_arrangement"], "remote")
        self.assertEqual(item["salary_max"], 306600)
        self.assertIn("Remote US", item["location"])
        self.assertTrue(_fresh_iso_listing("2026-08-25T12:00:00+00:00"))
        self.assertTrue(_fresh_iso_listing("2026-09-03T21:15:46.0971301Z"))
        self.assertFalse(_fresh_iso_listing("2026-05-01T12:00:00+00:00"))

    def test_ashby_austin_filter_accepts_only_explicit_texas_location(self):
        self.assertTrue(ashby_posting_has_austin({
            "location": "US-IL-Chicago-MSO",
            "secondaryLocations": [{"location": "Austin, TX"}],
        }))
        structured = {
            "title": "Staff Platform Engineer - Americas",
            "location": "Remote - US",
            "secondaryLocations": [{
                "location": "Austin",
                "address": {"postalAddress": {
                    "addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "USA",
                }},
            }],
            "jobUrl": "https://jobs.ashbyhq.com/ashby/example",
            "descriptionPlain": "Build cloud platform and distributed systems. " * 10,
        }
        self.assertTrue(ashby_posting_has_austin(structured))
        self.assertIn("Austin, Texas, USA", ashby_job_item("Ashby", structured)["location"])
        wrapped = structured | {"secondaryLocations": [{
            "location": "Remote (Austin, TX)",
            "address": {"postalAddress": {
                "addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States",
            }},
        }]}
        wrapped_location = ashby_job_item("Higharc", wrapped)["location"]
        self.assertIn("Austin, Texas, United States (Remote)", wrapped_location)
        self.assertTrue(is_austin_proper_location(wrapped_location))
        self.assertFalse(ashby_posting_has_austin({
            "location": "Remote, United States",
            "secondaryLocations": [{"location": "Boston, Massachusetts"}],
        }))

    def test_workday_provider_normalizes_public_austin_detail_and_freshness(self):
        detail = {"jobPostingInfo": {
            "title": "Senior Backend Software Engineer", "location": "US, CA, Santa Clara",
            "additionalLocations": ["US, TX, Austin", "US, OR, Hillsboro"],
            "startDate": "2026-08-25",
            "externalUrl": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-TX-Austin/example_JR1",
            "jobDescription": "Build Python distributed systems and cloud APIs. " * 10 + " The base salary range is 184,000 USD - 287,500 USD.",
        }}
        item = workday_job_item("NVIDIA", "https://nvidia.wd5.myworkdayjobs.com", "NVIDIAExternalCareerSite", "/job/example", detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["date_posted"], "2026-08-25")
        self.assertEqual(item["salary_max"], 287500)
        self.assertTrue(_fresh_workday_listing({"postedOn": "Posted Yesterday"}))
        self.assertTrue(_fresh_workday_listing({"postedOn": "Posted 14 Days Ago"}))
        self.assertFalse(_fresh_workday_listing({"postedOn": "Posted 30+ Days Ago"}))
        detail["jobPostingInfo"]["additionalLocations"] = ["US, OR, Hillsboro"]
        self.assertIsNone(workday_job_item("NVIDIA", "https://example.com", "site", "/job/example", detail))
        detail["jobPostingInfo"]["location"] = "US, Austin"
        self.assertIsNone(workday_job_item("NVIDIA", "https://example.com", "site", "/job/example", detail))
        detail["jobPostingInfo"]["location"] = "US TX Remote"
        detail["jobPostingInfo"]["jobDescription"] += " Hybrid or on-site working arrangement from the Revionics office based in Austin, Texas."
        self.assertIsNotNone(workday_job_item("Revionics", "https://example.com", "site", "/job/example", detail))

    def test_workday_company_collector_reports_connection_reset(self):
        with patch(
            "jobfinder.infrastructure.providers.urllib.request.urlopen",
            side_effect=ConnectionResetError("reset"),
        ):
            items, errors = workday_company_jobs(
                companies={"NVIDIA"}, max_pages=1, request_delay_seconds=0,
            )

        self.assertEqual(items, [])
        self.assertEqual(errors, ["NVIDIA Workday page 1: ConnectionResetError"])

    def test_workday_provider_maps_expedia_named_austin_office(self):
        detail = {"jobPostingInfo": {
            "title": "Software Development Engineer II - API Platform",
            "location": "Austin Domain 11 - HomeAway",
            "jobRequisitionLocation": {
                "descriptor": "Austin Domain 11 - HomeAway",
                "country": {"alpha2Code": "US"},
            },
            "startDate": "2026-09-01",
            "externalUrl": "https://expedia.wd108.myworkdayjobs.com/search/job/example_R-102851-1",
            "jobDescription": "Build JVM platform APIs and distributed cloud services. " * 10,
        }}
        item = workday_job_item("Expedia Group", "https://expedia.wd108.myworkdayjobs.com", "search", "/job/example", detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX")
        detail["jobPostingInfo"]["location"] = "Washington - Seattle Campus"
        detail["jobPostingInfo"]["additionalLocations"] = ["Austin Domain 11 - HomeAway"]
        self.assertIsNotNone(workday_job_item("Expedia Group", "https://example.com", "search", "/job/example", detail))
        detail["jobPostingInfo"]["jobRequisitionLocation"]["country"]["alpha2Code"] = "CA"
        self.assertIsNone(workday_job_item("Expedia Group", "https://example.com", "search", "/job/example", detail))

    def test_workday_provider_uses_expedia_austin_total_cash_not_first_city(self):
        detail = {"jobPostingInfo": {
            "title": "Senior Machine Learning Scientist - Agentic Experience",
            "location": "USA - California - San Jose",
            "additionalLocations": ["Austin Domain 11 - HomeAway"],
            "jobRequisitionLocation": {"country": {"alpha2Code": "US"}},
            "startDate": "2026-09-21",
            "externalUrl": "https://expedia.wd108.myworkdayjobs.com/search/job/example_R-107578-2",
            "jobDescription": (
                "Build production agentic AI systems. " * 12
                + "The total cash range for this position in San Jose is $187,000.00 to $261,500.00. "
                + "The total cash range for this position in Austin is $173,000.00 to $242,500.00."
            ),
        }}
        item = workday_job_item("Expedia Group", "https://expedia.wd108.myworkdayjobs.com", "search", "/job/example", detail)
        self.assertIsNotNone(item)
        self.assertEqual(item["salary_min"], 173000)
        self.assertEqual(item["salary_max"], 242500)
        self.assertEqual(item["salary_type"], "total")
        self.assertIn("Austin total cash", item["salary_text"])

    def test_workday_provider_requires_structured_us_austin_and_office_language(self):
        detail = {"jobPostingInfo": {
            "title": "Staff Software Engineer",
            "location": "Austin",
            "jobRequisitionLocation": {
                "descriptor": "Austin",
                "country": {"alpha2Code": "US"},
            },
            "startDate": "2026-08-24",
            "externalUrl": "https://trendmicro.wd3.myworkdayjobs.com/External/job/Austin/example_R0010128",
            "jobDescription": "This is a hybrid role based out of our Austin, TX office. "
            + "Build distributed cloud security services in Go and Kubernetes. " * 10,
        }}
        self.assertIsNotNone(workday_job_item(
            "TrendAI", "https://trendmicro.wd3.myworkdayjobs.com", "External", "/job/example", detail,
        ))
        detail["jobPostingInfo"]["jobRequisitionLocation"]["country"]["alpha2Code"] = "CA"
        self.assertIsNone(workday_job_item(
            "TrendAI", "https://trendmicro.wd3.myworkdayjobs.com", "External", "/job/example", detail,
        ))
        detail["jobPostingInfo"]["jobRequisitionLocation"]["country"]["alpha2Code"] = "US"
        detail["jobPostingInfo"]["jobDescription"] = "TrendAI has an Austin, TX office. " + "Build cloud services. " * 10
        self.assertIsNone(workday_job_item(
            "TrendAI", "https://trendmicro.wd3.myworkdayjobs.com", "External", "/job/example", detail,
        ))

    def test_snap_saved_company_uses_official_austin_workday_facet(self):
        config = WORKDAY_SITES["Snap Inc."]
        self.assertEqual(config["tenant"], "snapchat")
        self.assertEqual(config["site"], "snap")
        self.assertEqual(config["applied_facets"]["locations"], ["f84c7a1ec2ba1000d7878e08800c0000"])

    def test_q2_uses_official_exact_austin_workday_facet(self):
        config = WORKDAY_SITES["Q2"]
        self.assertEqual(config["host"], "https://q2ebanking.wd5.myworkdayjobs.com")
        self.assertEqual(config["applied_facets"]["locations"], ["0da4bb96663010308829a8dfd4e91994"])

    def test_commerce_uses_official_austin_workday_search(self):
        config = WORKDAY_SITES["Commerce"]
        self.assertEqual(config["host"], "https://bigcommerce.wd12.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "bigcommerce")
        self.assertEqual(config["site"], "Commerce")
        self.assertEqual(config["search_text"], "Austin")

    def test_texas_mutual_uses_official_austin_workday_search(self):
        config = WORKDAY_SITES["Texas Mutual Insurance Company"]
        self.assertEqual(config["host"], "https://texasmutual.wd1.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "texasmutual")
        self.assertEqual(config["site"], "texas_mutual_careers")
        self.assertEqual(config["search_text"], "Austin")

    def test_ut_austin_uses_official_workday_software_search(self):
        config = WORKDAY_SITES["The University of Texas at Austin"]
        self.assertEqual(config["host"], "https://utaustin.wd1.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "utaustin")
        self.assertEqual(config["site"], "UTstaff")
        self.assertEqual(config["search_text"], "Software")

    def test_apex_fintech_uses_official_austin_workday_search(self):
        config = WORKDAY_SITES["Apex Fintech Solutions"]
        self.assertEqual(config["host"], "https://peak6group.wd1.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "peak6group")
        self.assertEqual(config["site"], "apexfintechsolutions")
        self.assertEqual(config["search_text"], "Austin")
        self.assertEqual(config["applied_facets"], {})

    def test_cloudera_uses_official_austin_workday_search(self):
        config = WORKDAY_SITES["Cloudera"]
        self.assertEqual(config["host"], "https://cloudera.wd5.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "cloudera")
        self.assertEqual(config["site"], "External_Career")
        self.assertEqual(config["search_text"], "Austin")

    def test_assetmark_uses_official_austin_workday_search(self):
        config = WORKDAY_SITES["AssetMark"]
        self.assertEqual(config["host"], "https://assetmark.wd5.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "assetmark")
        self.assertEqual(config["site"], "AssetMark_Careers")
        self.assertEqual(config["search_text"], "Austin")
        self.assertEqual(config["applied_facets"], {})

    def test_dimensional_uses_official_austin_workday_search(self):
        config = WORKDAY_SITES["Dimensional Fund Advisors"]
        self.assertEqual(config["host"], "https://dimensional.wd5.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "dimensional")
        self.assertEqual(config["site"], "DFA_Careers")
        self.assertEqual(config["search_text"], "Austin")
        self.assertEqual(config["applied_facets"], {})

    def test_acrisure_uses_current_official_workday_site(self):
        config = WORKDAY_SITES["Acrisure"]
        self.assertEqual(config["host"], "https://acrisure.wd1.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "acrisure")
        self.assertEqual(config["site"], "Acrisure")
        self.assertEqual(config["search_text"], "Austin")

    def test_central_health_and_assa_abloy_use_public_ats_sites(self):
        self.assertEqual(ICIMS_SITES["Central Health"], "https://careers-centralhealth.icims.com")
        self.assertEqual(
            SUCCESSFACTORS_SITES["ASSA ABLOY Group"]["board_url"],
            "https://assaabloy.jobs2web.com/search/?q=&locationsearch=Austin",
        )

    def test_atoms_two_chairs_higharc_and_ensemble_use_employer_boards(self):
        self.assertEqual(GREENHOUSE_BOARDS["Atoms"], "atoms")
        self.assertEqual(GREENHOUSE_BOARDS["Two Chairs"], "twochairs")
        self.assertEqual(ASHBY_BOARDS["Higharc"], "higharc")
        config = WORKDAY_SITES["Ensemble Health Partners"]
        self.assertEqual(config["host"], "https://ensemblehp.wd5.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "ensemblehp")
        self.assertEqual(config["site"], "EnsembleHealthPartnersCareers")
        self.assertEqual(config["search_text"], "Austin")

    def test_optimizely_telnyx_invoca_qrypt_and_sixth_street_use_employer_boards(self):
        self.assertEqual(GREENHOUSE_BOARDS["Telnyx"], "telnyx54")
        self.assertEqual(GREENHOUSE_BOARDS["Setpoint"], "setpoint")
        self.assertEqual(SMARTRECRUITERS_COMPANIES["Invoca"], "Invoca")
        self.assertEqual(LEVER_BOARDS["Qrypt"], "qrypt")
        self.assertEqual(
            SUCCESSFACTORS_SITES["Optimizely"]["board_url"],
            "https://careers.optimizely.com/search/?q=&locationsearch=Austin",
        )
        config = WORKDAY_SITES["Sixth Street"]
        self.assertEqual(config["host"], "https://sixthstreet.wd1.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "sixthstreet")
        self.assertEqual(config["site"], "sixthstreetcareers")
        self.assertEqual(config["search_text"], "Austin")

    def test_natera_favor_duetto_yeti_and_hello_patient_use_employer_boards(self):
        self.assertEqual(GREENHOUSE_BOARDS["Natera"], "natera")
        self.assertEqual(GREENHOUSE_BOARDS["Duetto"], "duettoresearch")
        self.assertEqual(LEVER_BOARDS["Favor Delivery"], "askfavor")
        self.assertEqual(ASHBY_BOARDS["Hello Patient"], "hellopatient")
        config = WORKDAY_SITES["YETI"]
        self.assertEqual(config["host"], "https://yeticoolers.wd5.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "yeticoolers")
        self.assertEqual(config["site"], "YETI")
        self.assertEqual(config["search_text"], "Austin")

    def test_partly_navan_upshop_and_rockwell_use_employer_boards(self):
        self.assertEqual(ASHBY_BOARDS["Partly"], "partly.com")
        self.assertEqual(GREENHOUSE_BOARDS["Navan"], "tripactions")
        self.assertEqual(GREENHOUSE_BOARDS["Upshop"], "upshop")
        config = WORKDAY_SITES["Rockwell Automation"]
        self.assertEqual(config["host"], "https://rockwellautomation.wd1.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "rockwellautomation")
        self.assertEqual(config["site"], "External_Rockwell_Automation")
        self.assertEqual(config["search_text"], "Austin")

    def test_maintainx_atom_huntington_cirrus_and_osano_use_employer_boards(self):
        self.assertEqual(ASHBY_BOARDS["MaintainX"], "maintainx")
        self.assertEqual(LEVER_BOARDS["Atom Computing"], "atomcomputing")
        self.assertEqual(LEVER_BOARDS["Cirrus Logic"], "cirrus")
        self.assertEqual(LEVER_API_HOSTS["Cirrus Logic"], "https://api.eu.lever.co")
        self.assertEqual(GREENHOUSE_BOARDS["Osano"], "osano")
        config = WORKDAY_SITES["Huntington National Bank"]
        self.assertEqual(config["host"], "https://huntington.wd12.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "huntington")
        self.assertEqual(config["site"], "HNBcareers")
        self.assertEqual(config["search_text"], "Austin")

    def test_ambiq_iterable_and_kizen_use_exact_austin_greenhouse_boards(self):
        self.assertEqual(GREENHOUSE_BOARDS["Ambiq"], "ambiqmicroinc")
        self.assertEqual(GREENHOUSE_BOARDS["Iterable"], "iterable")
        self.assertEqual(GREENHOUSE_BOARDS["Kizen"], "kizen")

        now = datetime.now(timezone.utc).isoformat()
        payload = {"jobs": [{
            "id": 1,
            "first_published": now,
            "title": "Senior Backend Engineer",
            "location": {"name": "Remote - US"},
            "absolute_url": "https://job-boards.greenhouse.io/kizen/jobs/1",
            "content": "Kizen has an office in Austin, Texas. Build backend platform services.",
        }]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = greenhouse_company_jobs({"Kizen"})
        self.assertEqual(errors, [])
        self.assertEqual(jobs, [])

    def test_icon_and_hopper_use_exact_austin_employer_boards(self):
        self.assertEqual(GREENHOUSE_BOARDS["ICON"], "iconcareers")
        self.assertEqual(ASHBY_BOARDS["Hopper"], "hopper")
        now = datetime.now(timezone.utc).isoformat()
        hopper_payload = {"jobs": [{
            "id": "hopper-austin", "isListed": True, "publishedAt": now,
            "title": "Senior Full Stack Engineer", "location": "Austin - Remote",
            "address": {"postalAddress": {
                "addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States",
            }},
            "jobUrl": "https://jobs.ashbyhq.com/hopper/hopper-austin",
            "descriptionPlain": "Build backend and full-stack services for a distributed platform.",
        }, {
            "id": "hopper-boston", "isListed": True, "publishedAt": now,
            "title": "Senior Full Stack Engineer", "location": "Boston - Remote",
            "address": {"postalAddress": {
                "addressLocality": "Boston", "addressRegion": "Massachusetts", "addressCountry": "United States",
            }},
            "jobUrl": "https://jobs.ashbyhq.com/hopper/hopper-boston",
            "descriptionPlain": "Build backend and full-stack services for a distributed platform.",
        }]}
        icon_payload = {"jobs": [{
            "id": 1, "first_published": now, "title": "Senior Software Engineer, Data",
            "location": {"name": "Remote - US"},
            "offices": [{"name": "Austin", "location": "Austin, Texas"}],
            "absolute_url": "https://job-boards.greenhouse.io/iconcareers/jobs/1",
            "content": "Build data infrastructure and backend services.",
        }]}

        class Response:
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(self.payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(hopper_payload)):
            hopper_jobs, hopper_errors = ashby_company_jobs({"Hopper"})
        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(icon_payload)):
            icon_jobs, icon_errors = greenhouse_company_jobs({"ICON"})
        self.assertEqual(hopper_errors, [])
        self.assertEqual([job["url"] for job in hopper_jobs], ["https://jobs.ashbyhq.com/hopper/hopper-austin"])
        self.assertEqual(hopper_jobs[0]["location"], "Austin, Texas, United States (Remote)")
        self.assertEqual(icon_errors, [])
        self.assertEqual(icon_jobs, [])

    def test_avride_optiver_zynga_and_sonar_require_exact_austin_employer_locations(self):
        self.assertEqual(GREENHOUSE_BOARDS["Avride"], "avride")
        self.assertEqual(GREENHOUSE_BOARDS["Optiver"], "optiverus")
        self.assertEqual(GREENHOUSE_BOARDS["Zynga"], "zyngacareers")
        self.assertEqual(LEVER_BOARDS["Sonar"], "sonarsource")
        now = datetime.now(timezone.utc)
        greenhouse_payload = {"jobs": [{
            "id": 1, "first_published": now.isoformat(), "title": "Senior Software Engineer",
            "location": {"name": "Austin, Texas, United States"},
            "absolute_url": "https://job-boards.greenhouse.io/optiverus/jobs/1",
            "content": "Build backend data infrastructure and distributed systems.",
        }, {
            "id": 2, "first_published": now.isoformat(), "title": "Senior Software Engineer",
            "location": {"name": "Chicago, Illinois, United States"},
            "absolute_url": "https://job-boards.greenhouse.io/optiverus/jobs/2",
            "content": "The company also has an Austin office.",
        }]}
        lever_payload = [{
            "id": "sonar-austin", "text": "Site Reliability Engineering Lead",
            "createdAt": int(now.timestamp() * 1000),
            "categories": {"location": "Austin, Texas"},
            "hostedUrl": "https://jobs.lever.co/sonarsource/sonar-austin",
            "descriptionPlain": "Lead cloud platform reliability and backend infrastructure.",
        }, {
            "id": "sonar-geneva", "text": "Site Reliability Engineering Lead",
            "createdAt": int(now.timestamp() * 1000),
            "categories": {"location": "Geneva"},
            "hostedUrl": "https://jobs.lever.co/sonarsource/sonar-geneva",
            "descriptionPlain": "Lead cloud platform reliability and backend infrastructure.",
        }]

        class Response:
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(self.payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(greenhouse_payload)):
            optiver_jobs, optiver_errors = greenhouse_company_jobs({"Optiver"})
        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(lever_payload)):
            sonar_jobs, sonar_errors = lever_company_jobs({"Sonar"})
        self.assertEqual(optiver_errors, [])
        self.assertEqual([job["url"] for job in optiver_jobs], ["https://job-boards.greenhouse.io/optiverus/jobs/1"])
        self.assertEqual(optiver_jobs[0]["location"], "Austin, TX")
        self.assertEqual(sonar_errors, [])
        self.assertEqual([job["url"] for job in sonar_jobs], ["https://jobs.lever.co/sonarsource/sonar-austin"])
        self.assertTrue(title_is_candidate(sonar_jobs[0]))

    def test_new_direct_employer_adapters_fail_closed_on_non_austin_locations(self):
        now = datetime.now(timezone.utc).isoformat()
        ashby_payload = {"jobs": [{
            "id": "mx-austin", "isListed": True, "publishedAt": now,
            "title": "Senior Platform Developer", "location": "San Francisco",
            "secondaryLocations": [{"location": "Austin", "address": {"postalAddress": {
                "addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States",
            }}}],
            "jobUrl": "https://jobs.ashbyhq.com/maintainx/mx-austin",
            "descriptionPlain": "Build backend platform services and distributed systems.",
        }, {
            "id": "mx-us", "isListed": True, "publishedAt": now,
            "title": "Senior Platform Developer", "location": "United States",
            "jobUrl": "https://jobs.ashbyhq.com/maintainx/mx-us",
            "descriptionPlain": "MaintainX has an Austin office. Build backend services.",
        }]}
        greenhouse_payload = {"jobs": [{
            "id": 1, "first_published": now, "title": "Senior AI Engineer",
            "location": {"name": "Remote"},
            "absolute_url": "https://job-boards.greenhouse.io/osano/jobs/1",
            "content": "This role may require an in-person interview in Austin, Texas.",
        }]}
        lever_payload = [{
            "id": "atom-boulder", "text": "Senior Software Engineer",
            "createdAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "categories": {"location": "Boulder, CO"},
            "hostedUrl": "https://jobs.lever.co/atomcomputing/atom-boulder",
            "descriptionPlain": "Build backend distributed systems.",
        }]

        class Response:
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(self.payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(ashby_payload)):
            maintainx_jobs, _ = ashby_company_jobs({"MaintainX"})
        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(greenhouse_payload)):
            osano_jobs, _ = greenhouse_company_jobs({"Osano"})
        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(lever_payload)) as mocked:
            atom_jobs, _ = lever_company_jobs({"Atom Computing"})
        self.assertEqual([job["url"] for job in maintainx_jobs], ["https://jobs.ashbyhq.com/maintainx/mx-austin"])
        self.assertEqual(osano_jobs, [])
        self.assertEqual(atom_jobs, [])
        self.assertIn("https://api.lever.co/v0/postings/atomcomputing", mocked.call_args.args[0].full_url)

    def test_partly_navan_and_upshop_require_structured_exact_austin(self):
        ashby_payload = {"jobs": [{
            "id": "partly-austin",
            "isListed": True,
            "publishedAt": datetime.now(timezone.utc).isoformat(),
            "title": "Staff Software Engineer",
            "location": "Austin",
            "address": {"postalAddress": {
                "addressLocality": "Austin",
                "addressRegion": "Texas",
                "addressCountry": "United States",
            }},
            "jobUrl": "https://jobs.ashbyhq.com/partly.com/partly-austin",
            "descriptionPlain": "Build backend distributed systems and cloud data infrastructure.",
        }, {
            "id": "partly-remote",
            "isListed": True,
            "publishedAt": datetime.now(timezone.utc).isoformat(),
            "title": "Staff Software Engineer",
            "location": "Remote - United States",
            "jobUrl": "https://jobs.ashbyhq.com/partly.com/partly-remote",
            "descriptionPlain": "Partly is headquartered in Austin. Build backend distributed systems.",
        }]}
        navan_payload = {"jobs": [{
            "id": 1,
            "first_published": datetime.now(timezone.utc).isoformat(),
            "title": "Senior Backend Engineer",
            "location": {"name": "Austin, TX"},
            "absolute_url": "https://navan.com/careers/openings?gh_jid=1",
            "content": "Build Node.js backend services on AWS.",
        }]}
        upshop_payload = {"jobs": [{
            "id": 2,
            "first_published": datetime.now(timezone.utc).isoformat(),
            "title": "Engineering Manager",
            "location": {"name": "Miami"},
            "offices": [{"name": "Austin", "location": "Austin, Texas"}],
            "absolute_url": "https://job-boards.greenhouse.io/upshop/jobs/2",
            "content": "Lead backend platform engineers.",
        }]}

        class Response:
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(self.payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(ashby_payload)):
            partly_jobs, partly_errors = ashby_company_jobs({"Partly"})
        self.assertEqual(partly_errors, [])
        self.assertEqual([job["url"] for job in partly_jobs], ["https://jobs.ashbyhq.com/partly.com/partly-austin"])

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(navan_payload)):
            navan_jobs, navan_errors = greenhouse_company_jobs({"Navan"})
        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response(upshop_payload)):
            upshop_jobs, upshop_errors = greenhouse_company_jobs({"Upshop"})
        self.assertEqual(navan_errors + upshop_errors, [])
        self.assertEqual([job["url"] for job in navan_jobs], ["https://navan.com/careers/openings?gh_jid=1"])
        self.assertEqual(upshop_jobs, [])

    def test_peak6_uses_its_own_official_workday_site(self):
        config = WORKDAY_SITES["PEAK6"]
        self.assertEqual(config["host"], "https://peak6group.wd1.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "peak6group")
        self.assertEqual(config["site"], "PEAK6")
        self.assertEqual(config["search_text"], "Austin")

    def test_overhaul_uses_public_adp_and_requires_structured_austin(self):
        config = ADP_SITES["Overhaul"]
        location = {
            "address": {
                "cityName": "Austin",
                "countrySubdivisionLevel1": {"codeValue": "TX"},
            },
            "nameCode": {"shortName": "Overhaul, Austin, TX, US"},
        }
        listing = {
            "itemID": "9201000000000_1",
            "requisitionTitle": "Senior Platform Engineer",
            "postDate": datetime.now(timezone.utc).isoformat(),
            "requisitionLocations": [location],
            "customFieldGroup": {"stringFields": [{
                "stringValue": "600123",
                "nameCode": {"codeValue": "ExternalJobID"},
            }]},
        }
        detail = {
            **listing,
            "requisitionDescription": "Build distributed backend APIs, Kubernetes cloud infrastructure, databases, and platform services. " * 8,
        }
        self.assertTrue(_adp_listing_has_austin(listing))
        item = adp_job_item("Overhaul", config, listing, detail)
        self.assertEqual(item["source"], "adp")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["provider_job_id"], "9201000000000_1")
        self.assertTrue(item["url"].endswith("&jobId=600123"))
        self.assertEqual(storage._official_requisition_key("adp", item["url"]), "adp:600123")
        self.assertIn("adp", storage.OFFICIAL_JOB_SOURCES)
        foreign = {**listing, "requisitionLocations": [{
            "address": {"cityName": "Austin", "countrySubdivisionLevel1": {"codeValue": "TX"}},
            "nameCode": {"shortName": "Austin office, CA"},
        }]}
        self.assertFalse(_adp_listing_has_austin(foreign))
        self.assertIsNone(adp_job_item("Overhaul", config, foreign, detail))

    def test_pickup_static_employer_page_supplies_canonical_austin_role(self):
        config = EMPLOYER_PAGE_SITES["PICKUP AI"]
        board = (
            '<div class="rounded-lg border"><h3>Senior Software Engineer</h3>'
            '<a href="/careers/software-engineer">Apply Now</a>'
            '<span>Austin, TX (Hybrid)</span><span>$150,000 - $200,000</span></div>'
            '<div class="rounded-lg border"><h3>Sales Representative</h3></div>'
        )
        detail = (
            '<main><h1>Senior Software Engineer</h1><h2>About the Role</h2><p>'
            + "Build full-stack TypeScript, React, Node.js, backend APIs, PostgreSQL, and cloud platform services. " * 7
            + '</p><h2>Ready to Apply?</h2></main>'
        )
        item = employer_page_job_item("PICKUP AI", config, board, detail)
        self.assertEqual(item["url"], "https://pickupjobs.co/careers/software-engineer")
        self.assertEqual(item["source"], "employer")
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["salary_min"], 150000.0)
        self.assertEqual(item["salary_max"], 200000.0)
        self.assertIn("employer", storage.OFFICIAL_JOB_SOURCES)
        self.assertIsNone(employer_page_job_item(
            "PICKUP AI", config, board.replace("Austin, TX", "Remote, US"), detail,
        ))

    def test_field_systems_hardware_manager_is_not_software_scope(self):
        self.assertFalse(posting_is_relevant({
            "title": "Field Systems Engineering Manager",
            "location": "Austin, TX",
            "description": (
                "Lead ruggedized acoustic sensing hardware and field devices, sensors, power and signal electronics, "
                "firmware, electrical troubleshooting, and on-site deployments. " * 5
            ),
        }))

    def test_zendesk_uses_official_austin_workday_search(self):
        config = WORKDAY_SITES["Zendesk"]
        self.assertEqual(config["host"], "https://zendesk.wd1.myworkdayjobs.com")
        self.assertEqual(config["tenant"], "zendesk")
        self.assertEqual(config["site"], "zendesk")
        self.assertEqual(config["search_text"], "Austin")

    def test_intel_workday_combines_austin_and_software_facets(self):
        config = WORKDAY_SITES["Intel"]
        self.assertEqual(config["tenant"], "intel")
        self.assertEqual(config["applied_facets"]["locations"], ["1e4a4eb3adf1016541777876bf8111cf"])
        self.assertEqual(config["applied_facets"]["jobFamilyGroup"], ["ace7a3d23b7e01a0544279031a0ec85c"])

    def test_solarwinds_uses_official_greenhouse_board(self):
        self.assertEqual(GREENHOUSE_BOARDS["Avride"], "avride")
        self.assertEqual(GREENHOUSE_BOARDS["CharterUP"], "charterup")
        self.assertEqual(GREENHOUSE_BOARDS["DoorDash"], "doordashusa")
        self.assertEqual(GREENHOUSE_BOARDS["SolarWinds"], "solarwinds")
        self.assertEqual(GREENHOUSE_BOARDS["SpaceX"], "spacex")
        self.assertEqual(GREENHOUSE_BOARDS["Vectra AI"], "vectranetworks")
        self.assertEqual(GREENHOUSE_BOARDS["Speechify"], "speechify")
        self.assertEqual(GREENHOUSE_BOARDS["Take-Two Interactive"], "taketwo")
        self.assertEqual(GREENHOUSE_BOARDS["Vestwell"], "vestwell")
        self.assertEqual(GREENHOUSE_BOARDS["Scorability"], "scorability")
        self.assertEqual(GREENHOUSE_BOARDS["inKind"], "inkind")
        self.assertEqual(GREENHOUSE_BOARDS["Auctane"], "auctane")
        self.assertEqual(GREENHOUSE_BOARDS["Monks"], "monks")
        self.assertEqual(GREENHOUSE_BOARDS["Robots & Pencils"], "robotsandpencils")
        self.assertEqual(GREENHOUSE_BOARDS["ZoomInfo"], "zoominfo")

    def test_monks_verified_austin_office_label_is_normalized(self):
        today = datetime.now(timezone.utc).isoformat()
        payload = {"jobs": [{
            "id": 1,
            "first_published": today,
            "title": "Senior DevOps Engineer",
            "location": {"name": "Austin"},
            "absolute_url": "https://www.monks.com/careers/1/job?gh_jid=1",
            "content": "Build cloud platform infrastructure and distributed backend services. " * 12,
        }, {
            "id": 2,
            "first_published": today,
            "title": "Senior DevOps Engineer",
            "location": {"name": "New York"},
            "absolute_url": "https://www.monks.com/careers/2/job?gh_jid=2",
            "content": "Build cloud platform infrastructure and distributed backend services. " * 12,
        }]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = greenhouse_company_jobs({"Monks"})
        self.assertEqual(errors, [])
        self.assertEqual([job["url"] for job in jobs], ["https://www.monks.com/careers/1/job?gh_jid=1"])
        self.assertEqual(jobs[0]["location"], "Austin, TX")

    def test_zoominfo_greenhouse_feed_uses_exact_austin_and_branded_url(self):
        today = datetime.now(timezone.utc).isoformat()
        payload = {"jobs": [{
            "id": 8451789002,
            "requisition_id": "JR107262",
            "first_published": today,
            "title": "Senior Software Engineer",
            "location": {"name": "Austin, Texas, United States"},
            "absolute_url": "https://www.zoominfo.com/careers?gh_jid=8451789002",
            "content": "Build Python FastAPI backend services and agentic AI systems. " * 12
            + "US base salary $140,000 — $220,000 USD.",
        }, {
            "id": 2,
            "requisition_id": "JR2",
            "first_published": today,
            "title": "Senior Software Engineer",
            "location": {"name": "Remote, United States"},
            "absolute_url": "https://www.zoominfo.com/careers?gh_jid=2",
            "content": "Build Python FastAPI backend services. " * 12,
        }]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = greenhouse_company_jobs({"ZoomInfo"})
        self.assertEqual(errors, [])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["location"], "Austin, TX")
        self.assertEqual(jobs[0]["salary_max"], 220000)
        self.assertEqual(
            jobs[0]["url"],
            "https://www.zoominfo.com/careers/jr107262/senior-software-engineer?gh_jid=8451789002",
        )

    def test_exact_austin_greenhouse_boards_require_public_location_label(self):
        self.assertTrue(greenhouse_display_location_has_austin({
            "location": {"name": "Austin, Texas, United States"},
            "offices": [{"name": "Remote", "location": ""}],
        }))
        self.assertFalse(greenhouse_display_location_has_austin({
            "location": {"name": "Remote"},
            "offices": [{"name": "Austin", "location": "Austin, Texas, United States"}],
        }))

    def test_affirm_and_mongodb_reject_bare_austin_greenhouse_labels(self):
        today = datetime.now(timezone.utc).isoformat()
        payload = {"jobs": [{
            "id": 1, "first_published": today, "title": "Senior Backend Engineer",
            "location": {"name": "Austin; San Francisco"},
            "absolute_url": "https://example.test/jobs/1",
            "content": "Build distributed backend services and cloud data platforms. " * 12,
        }, {
            "id": 2, "first_published": today, "title": "Staff Platform Engineer",
            "location": {"name": "Austin, Texas, United States; New York, New York, United States"},
            "absolute_url": "https://example.test/jobs/2",
            "content": "Build distributed backend services and cloud data platforms. " * 12,
        }]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        for company in ("Affirm", "MongoDB", "Seekr", "CharterUP"):
            with self.subTest(company=company), patch(
                "jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()
            ):
                jobs, errors = greenhouse_company_jobs({company})
            self.assertEqual(errors, [])
            self.assertEqual([job["title"] for job in jobs], ["Staff Platform Engineer"])
            self.assertEqual(jobs[0]["location"], "Austin, TX")

    def test_telnyx_greenhouse_board_rejects_non_austin_global_roles(self):
        today = datetime.now(timezone.utc).isoformat()
        payload = {"jobs": [{
            "id": 1,
            "first_published": today,
            "title": "Senior Backend Engineer",
            "location": {"name": "Dublin, Ireland; Remote"},
            "absolute_url": "https://job-boards.greenhouse.io/telnyx54/jobs/1",
            "content": "Build distributed backend APIs and cloud data platforms. " * 12,
        }, {
            "id": 2,
            "first_published": today,
            "title": "Senior Backend Engineer",
            "location": {"name": "Austin, Texas; Dublin, Ireland"},
            "absolute_url": "https://job-boards.greenhouse.io/telnyx54/jobs/2",
            "content": "Build distributed backend APIs and cloud data platforms. " * 12,
        }]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = greenhouse_company_jobs({"Telnyx"})
        self.assertEqual(errors, [])
        self.assertEqual([job["url"] for job in jobs], ["https://job-boards.greenhouse.io/telnyx54/jobs/2"])
        self.assertEqual(jobs[0]["location"], "Austin, TX")

    def test_code_and_theory_uses_exact_austin_greenhouse_metadata(self):
        self.assertEqual(GREENHOUSE_BOARDS["Code and Theory"], "codeandtheory")
        self.assertTrue(greenhouse_listing_has_austin({
            "location": {"name": "Austin, Texas, United States; New York, New York, United States"},
        }))
        self.assertFalse(greenhouse_listing_has_austin({
            "location": {"name": "New York, New York, United States; Remote"},
        }))

    def test_enverus_uses_public_jobvite_board_and_exact_austin_detail(self):
        self.assertEqual(JOBVITE_SITES["Enverus"], "https://jobs.jobvite.com/enverus")
        board = '<a href="/enverus/job/on4cAfwX">Staff Software Engineer - 26218</a>'
        self.assertEqual(jobvite_search_listings(board, JOBVITE_SITES["Enverus"]), [{
            "title": "Staff Software Engineer - 26218",
            "url": "https://jobs.jobvite.com/enverus/job/on4cAfwX",
        }])
        posting = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Staff Software Engineer - 26218",
            "datePosted": "2026-08-27",
            "description": "Build Python, Go, Kafka, Kubernetes, and distributed backend data infrastructure. " * 10
            + " Salary Range: $170,000 - $210,000.",
            "jobLocation": [
                {"address": {"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States"}},
                {"address": {"addressLocality": "Remote", "addressRegion": "United States", "addressCountry": "United States"}},
            ],
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        item = jobvite_job_item("Enverus", raw, "https://jobs.jobvite.com/enverus/job/on4cAfwX")
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["date_posted"], "2026-08-27")
        self.assertEqual(item["salary_max"], 210000)
        self.assertEqual(item["source"], "jobvite")
        posting["jobLocation"][0]["address"]["addressLocality"] = "Dallas"
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        self.assertIsNone(jobvite_job_item("Enverus", raw, "https://jobs.jobvite.com/enverus/job/on4cAfwX"))
        posting["jobLocation"][0]["address"]["addressLocality"] = "Austin"
        posting["datePosted"] = "2026-05-27"
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        self.assertIsNone(jobvite_job_item("Enverus", raw, "https://jobs.jobvite.com/enverus/job/on4cAfwX"))
        self.assertEqual(
            canonical_public_url("https://jobs.example/job?gh_jid=123&gh_jid=123"),
            "https://jobs.example/job?gh_jid=123",
        )

    def test_greenhouse_display_location_rejects_unrelated_austin_office(self):
        record = {
            "location": {"name": "New York, NY | King of Prussia, PA"},
            "offices": [{"name": "Austin", "location": "Austin, Texas, United States"}],
        }
        self.assertFalse(greenhouse_display_location_has_austin(record))
        record["location"]["name"] += " | Austin, TX"
        self.assertTrue(greenhouse_display_location_has_austin(record))

    def test_2k_cloudbeds_disco_panic_button_seekr_storable_and_vulncheck_use_official_greenhouse_boards(self):
        self.assertEqual(GREENHOUSE_BOARDS["2K"], "2k")
        self.assertEqual(GREENHOUSE_BOARDS["Cloudbeds"], "cloudbeds")
        self.assertEqual(GREENHOUSE_BOARDS["DISCO"], "disco")
        self.assertEqual(GREENHOUSE_BOARDS["Panic Button"], "panicbutton")
        self.assertNotIn("Postman", GREENHOUSE_BOARDS)
        self.assertEqual(WORKDAY_SITES["Postman"]["tenant"], "postman")
        self.assertEqual(WORKDAY_SITES["Postman"]["site"], "careers")
        self.assertEqual(GREENHOUSE_BOARDS["Seekr"], "seekr")
        self.assertEqual(GREENHOUSE_BOARDS["Storable"], "storable")
        self.assertEqual(GREENHOUSE_BOARDS["VulnCheck"], "vulncheck")
        self.assertEqual(GREENHOUSE_BOARDS["Qualia"], "qualia")

    def test_cloudflare_greenhouse_requires_explicit_austin_office(self):
        self.assertTrue(greenhouse_listing_has_austin({
            "location": {"name": "Hybrid"},
            "offices": [{"name": "Austin, TX", "location": "Austin, TX, United States"}],
            "metadata": [],
        }))
        self.assertTrue(greenhouse_listing_has_austin({
            "location": {"name": "In-Office"},
            "offices": [],
            "metadata": [{"name": "Job Posting Location", "value": ["Austin, US", "London, UK"]}],
        }))
        self.assertFalse(greenhouse_listing_has_austin({
            "location": {"name": "Hybrid"},
            "offices": [{"name": "Lisbon, Portugal"}],
            "metadata": [{"name": "Job Posting Location", "value": ["Lisbon, Portugal"]}],
        }))

    def test_duetto_greenhouse_board_excludes_country_wide_copy(self):
        now = datetime.now(timezone.utc).isoformat()
        payload = {"jobs": [{
            "id": 1,
            "title": "Senior DevOps Engineer",
            "location": {"name": "United States"},
            "absolute_url": "https://job-boards.greenhouse.io/duettoresearch/jobs/1",
            "first_published": now,
            "content": "Build cloud platform infrastructure.",
        }, {
            "id": 2,
            "title": "Senior DevOps Engineer",
            "location": {"name": "Austin, TX"},
            "absolute_url": "https://job-boards.greenhouse.io/duettoresearch/jobs/2",
            "first_published": now,
            "content": "Build cloud platform infrastructure in Austin.",
        }]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = greenhouse_company_jobs({"Duetto"})
        self.assertEqual(errors, [])
        self.assertEqual([job["url"] for job in jobs], ["https://job-boards.greenhouse.io/duettoresearch/jobs/2"])

    def test_setpoint_greenhouse_board_requires_displayed_austin_texas(self):
        now = datetime.now(timezone.utc).isoformat()
        payload = {"jobs": [{
            "id": 1,
            "title": "Senior Full Stack Engineer",
            "location": {"name": "New York, NY (Hybrid)"},
            "absolute_url": "https://job-boards.greenhouse.io/setpoint/jobs/1",
            "first_published": now,
            "content": "Build Python APIs and TypeScript applications.",
        }, {
            "id": 2,
            "title": "Senior Full Stack Engineer",
            "location": {"name": "Austin, TX (Hybrid)"},
            "absolute_url": "https://job-boards.greenhouse.io/setpoint/jobs/2",
            "first_published": now,
            "content": "Build Python APIs and TypeScript applications in Austin.",
        }]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = greenhouse_company_jobs({"Setpoint"})
        self.assertEqual(errors, [])
        self.assertEqual([job["url"] for job in jobs], ["https://job-boards.greenhouse.io/setpoint/jobs/2"])
        self.assertEqual(jobs[0]["location"], "Austin, TX")

    def test_orum_uses_official_ashby_board(self):
        self.assertEqual(ASHBY_BOARDS["Fluidstack"], "fluidstack")
        self.assertEqual(ASHBY_BOARDS["PAR Technology"], "par technology")
        self.assertEqual(
            ashby_board_endpoint(ASHBY_BOARDS["PAR Technology"]),
            "https://api.ashbyhq.com/posting-api/job-board/par%20technology",
        )
        self.assertEqual(ASHBY_BOARDS["Orum"], "orum")
        self.assertEqual(ASHBY_BOARDS["Upside"], "upside")
        self.assertEqual(ASHBY_BOARDS["Ontic"], "ontic")
        self.assertEqual(ASHBY_BOARDS["Saronic Technologies"], "saronic")
        self.assertEqual(ASHBY_BOARDS["Zello"], "Zello")
        self.assertEqual(ASHBY_BOARDS["Edlink"], "edlink")
        self.assertEqual(ASHBY_BOARDS["CompanyCam"], "companycam")
        paid = ashby_job_item("Fluidstack", {
            "title": "Staff Detection Engineer",
            "location": "Austin, TX",
            "jobUrl": "https://jobs.ashbyhq.com/fluidstack/example",
            "publishedAt": "2026-09-01T12:00:00Z",
            "descriptionPlain": "Build Python detection-as-code pipelines across cloud infrastructure and distributed security systems.",
            "compensation": {"scrapeableCompensationSalarySummary": "$224K - $344K", "summaryComponents": [{
                "compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "USD", "minValue": 224000, "maxValue": 344000,
            }]},
        })
        self.assertEqual(paid["salary_min"], 224000)
        self.assertEqual(paid["salary_max"], 344000)

    def test_ashby_and_par_boards_reject_non_austin_postings_early(self):
        now = datetime.now(timezone.utc).isoformat()
        payload = {"jobs": [{
            "id": "remote", "isListed": True, "publishedAt": now,
            "title": "Senior Backend Engineer", "location": "Remote - United States",
            "jobUrl": "https://jobs.ashbyhq.com/example/remote",
            "descriptionPlain": "Build distributed backend services and cloud platforms. " * 12,
        }, {
            "id": "austin", "isListed": True, "publishedAt": now,
            "title": "Staff Platform Engineer", "location": "Austin",
            "address": {"postalAddress": {
                "addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States",
            }},
            "jobUrl": "https://jobs.ashbyhq.com/example/austin",
            "descriptionPlain": "Build distributed backend services and cloud platforms. " * 12,
        }]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        for company in ("Ashby", "PAR Technology"):
            with self.subTest(company=company), patch(
                "jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()
            ):
                jobs, errors = ashby_company_jobs({company})
            self.assertEqual(errors, [])
            self.assertEqual([job["title"] for job in jobs], ["Staff Platform Engineer"])
            self.assertEqual(jobs[0]["location"], "Austin, Texas, United States")

    def test_ashby_primary_postal_address_supplies_exact_austin_evidence(self):
        job = {
            "title": "Senior Software Engineer, Backend",
            "location": "Austin",
            "address": {"postalAddress": {
                "addressLocality": "Austin",
                "addressRegion": "Texas",
                "addressCountry": "United States",
            }},
            "jobUrl": "https://jobs.ashbyhq.com/edlink/example",
            "descriptionPlain": "Build TypeScript and Node.js APIs with PostgreSQL and Kubernetes.",
            "publishedAt": "2026-09-01T12:00:00Z",
        }
        self.assertTrue(ashby_posting_has_austin(job))
        item = ashby_job_item("Edlink", job)
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, Texas, United States")

    def test_hello_patient_ashby_board_excludes_new_york_copy(self):
        now = datetime.now(timezone.utc).isoformat()
        payload = {"jobs": [{
            "id": "ny",
            "isListed": True,
            "publishedAt": now,
            "title": "Software Engineer II",
            "location": "New York, NY",
            "jobUrl": "https://jobs.ashbyhq.com/hellopatient/ny",
            "descriptionPlain": "Build Python backend services.",
        }, {
            "id": "austin",
            "isListed": True,
            "publishedAt": now,
            "title": "Software Engineer II",
            "location": "Austin, Texas",
            "jobUrl": "https://jobs.ashbyhq.com/hellopatient/austin",
            "descriptionPlain": "Build Python backend services in Austin.",
        }]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = ashby_company_jobs({"Hello Patient"})
        self.assertEqual(errors, [])
        self.assertEqual([job["url"] for job in jobs], ["https://jobs.ashbyhq.com/hellopatient/austin"])

    def test_biorce_uses_public_revolut_people_posting_with_original_date(self):
        self.assertEqual(REVOLUTPEOPLE_SITES["Biorce"]["tenant"], "biorce")
        posting = {
            "id": "8daffd27-d4e1-4525-a83e-65e923037be1",
            "title": "Engineering Manager, SaaS",
            "locations": [{"name": "Austin", "type": "office", "country": {"name": "United States"}}],
            "description": "<p>Lead software engineering for a distributed SaaS platform with Python, APIs, and Kubernetes.</p>" * 4,
            "creation_date_time": datetime.now(timezone.utc).date().isoformat() + "T12:00:00Z",
        }
        item = revolutpeople_job_item("Biorce", "biorce", posting)
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["source"], "revolutpeople")
        self.assertEqual(item["provider_job_id"], posting["id"])
        self.assertTrue(item["url"].endswith("/position/" + posting["id"]))
        posting["creation_date_time"] = "2020-01-01T12:00:00Z"
        self.assertIsNone(revolutpeople_job_item("Biorce", "biorce", posting))

    def test_webai_uses_official_ashby_board_and_title_alias(self):
        self.assertEqual(ASHBY_BOARDS["webAI"], "webai")
        self.assertEqual(ASHBY_BOARDS["Ashby"], "ashby")
        from jobfinder.infrastructure.storage import title_key
        self.assertEqual(title_key("Senior Platform Rust Engineer"), title_key("Senior Rust Platform Engineer"))

    def test_boom_uses_official_ashby_board(self):
        self.assertEqual(ASHBY_BOARDS["Boom"], "boom")

    def test_grocery_tv_uses_official_greenhouse_board(self):
        self.assertEqual(GREENHOUSE_BOARDS["Grocery TV"], "gtv")

    def test_sentilink_uses_official_remote_ashby_board(self):
        self.assertEqual(ASHBY_BOARDS["SentiLink"], "sentilink")
        item = ashby_job_item("SentiLink", {
            "title": "Senior Software Engineer, Platform/Backend",
            "location": "United States",
            "workplaceType": "Remote",
            "isRemote": True,
            "jobUrl": "https://jobs.ashbyhq.com/sentilink/example",
            "publishedAt": "2026-08-27T18:02:26+00:00",
            "descriptionPlain": "Build Python distributed systems. Compensation: $170,000/year - $230,000/year.",
        })
        self.assertEqual(item["location"], "Remote - United States")
        self.assertEqual(item["salary_max"], 230000)

    def test_amd_jibe_provider_normalizes_austin_salary_and_canonical_link(self):
        fresh_date = datetime.now(timezone.utc).date().isoformat()
        record = {"data": {
            "slug": "86642", "title": "Senior Linux Software Engineer",
            "city": "Austin", "country_code": "US", "short_location": "Austin, Texas",
            "posted_date": f"{fresh_date}T12:27:00+0000",
            "description": "Build Linux cloud platform and distributed systems software. " * 8,
            "tags2": ["USD $168,000.00/Yr."], "tags3": ["USD $252,000.00/Yr."],
        }}
        item = amd_job_item(record)
        self.assertIsNotNone(item)
        self.assertEqual(item["salary_min"], 168000)
        self.assertEqual(item["salary_max"], 252000)
        self.assertEqual(item["date_posted"], fresh_date)
        self.assertEqual(item["url"], "https://careers.amd.com/careers-home/jobs/86642?lang=en-us")
        record["data"]["city"] = "Santa Clara"
        self.assertIsNone(amd_job_item(record))
        record["data"]["city"] = "Austin"
        record["data"]["posted_date"] = "2026-06-20T12:27:00+0000"
        self.assertIsNone(amd_job_item(record))

    def test_amd_jibe_provider_rejects_conflicting_detail_location(self):
        record = {"data": {
            "slug": "91413", "title": "Senior Datacenter Platform/Debug Engineer",
            "city": "Austin", "country_code": "US", "short_location": "Austin, Texas",
            "posted_date": "2026-09-02T12:27:00+0000",
            "description": (
                "Support datacenter GPU and server platforms across hardware, firmware, "
                "software, validation, and infrastructure teams. " * 6
                + " LOCATION: Rockdale, Texas | 100% Onsite THIS ROLE IS NOT ELIGIBLE FOR VISA SUPPORT"
            ),
        }}
        self.assertIsNone(amd_job_item(record))

    def test_generic_jibe_provider_requires_fresh_explicit_austin_location(self):
        record = {"data": {
            "slug": "218140", "title": "Staff Data Engineer-AI Platform",
            "city": "Austin", "state": "Texas", "country_code": "US",
            "posted_date": "2026-09-03T15:46:00+0000",
            "description": "Build Python data pipelines, cloud APIs, and distributed AI platform services. " * 8,
            "tags": ["USD $144,300.00/Yr."],
            "tags2": ["Digital Data Engineering"], "location_type": "OFFICE",
        }}
        item = jibe_job_item("H-E-B", "https://careers.heb.com", record)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "jibe")
        self.assertEqual(item["provider_job_id"], "218140")
        self.assertEqual(item["url"], "https://careers.heb.com/jobs/218140?lang=en-us")
        self.assertEqual(item["salary_text"], "From $144,300")
        self.assertEqual(item["salary_min"], 144300)
        self.assertIsNone(item["salary_max"])
        record["data"]["posted_date"] = "2026-06-01T15:46:00+0000"
        self.assertIsNone(jibe_job_item("H-E-B", "https://careers.heb.com", record))
        record["data"]["posted_date"] = "2026-09-03T15:46:00+0000"
        record["data"]["city"] = "San Antonio"
        self.assertIsNone(jibe_job_item("H-E-B", "https://careers.heb.com", record))

    def test_generic_jibe_provider_accepts_explicit_austin_additional_location(self):
        fresh_date = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
        record = {"data": {
            "slug": "34613", "title": "Senior Data Engineer",
            "city": "Raleigh", "state": "North Carolina", "country_code": "US",
            "additional_locations": [
                {"city": "Phoenix", "state": "Arizona", "country_code": "US"},
                {"city": "Austin", "state": "Texas", "country": "United States"},
            ],
            "posted_date": f"{fresh_date}T21:29:00+0000",
            "description": "Build Python data pipelines, cloud APIs, and distributed platform services. " * 8,
            "location_type": "ANY", "tags2": ["Remote"],
        }}
        item = jibe_job_item("First Citizens Bank", "https://jobs.firstcitizens.com", record)
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["work_arrangement"], "remote")
        record["data"]["additional_locations"][1] = {
            "city": "Dallas", "state": "Texas", "country": "United States",
        }
        self.assertIsNone(jibe_job_item("First Citizens Bank", "https://jobs.firstcitizens.com", record))

    def test_amazon_provider_requires_an_explicit_austin_location(self):
        fresh_date = (datetime.now(timezone.utc) - timedelta(days=5)).date()
        posted_date = f"{fresh_date.strftime('%B')} {fresh_date.day}, {fresh_date.year}"
        job = {
            "title": "Senior Software Development Engineer, OpenSearch",
            "job_path": "/en/jobs/123/senior-software-development-engineer-opensearch",
            "posted_date": posted_date,
            "location": "US, WA, Seattle",
            "locations": [
                json.dumps({"city": "Seattle", "normalizedCountryCode": "USA", "type": "ONSITE"}),
                json.dumps({"city": "Austin", "normalizedCountryCode": "USA", "type": "ONSITE"}),
            ],
            "description": (
                "Build reliable distributed systems and cloud platform services. " * 8
                + " USA, TX, Austin - 168,100.00 - 227,400.00 USD annually"
            ),
            "basic_qualifications": "Five years of backend software development.",
        }
        item = amazon_job_item(job)
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX")
        self.assertEqual(item["date_posted"], fresh_date.isoformat())
        self.assertEqual(item["source"], "amazon")
        self.assertEqual(item["salary_text"], "$168,100 - $227,400")
        self.assertEqual(item["salary_min"], 168100)
        self.assertEqual(item["salary_max"], 227400)
        self.assertEqual(item["salary_type"], "base")
        job["posted_date"] = "July 1, 2026"
        self.assertIsNone(amazon_job_item(job))
        job["posted_date"] = "August 24, 2026"
        job["locations"] = [json.dumps({"city": "Seattle", "normalizedCountryCode": "USA"})]
        self.assertIsNone(amazon_job_item(job))

    def test_ranking_engine_matches_compatibility_function(self):
        job = {
            "company": "Example Co", "title": "Staff Backend Software Engineer", "location": "Austin, TX",
            "description": "Python Kafka distributed systems microservices architecture " * 10,
            "date_posted": "2026-08-25", "salary_min": 220000, "salary_max": 280000,
        }
        self.assertEqual(RankingEngine(PROFILE, set(), {}).rank(job), score(job, PROFILE, set(), {}))

    def test_ranking_engine_exposes_structured_rule_breakdown(self):
        job = {
            "company": "Example Co", "title": "Staff Backend Software Engineer", "location": "Austin, TX",
            "description": "Python Kafka distributed systems microservices architecture " * 10,
            "date_posted": "2026-08-25", "salary_max": 280000,
        }
        result = RankingEngine(PROFILE, set(), {}, today=date(2026, 8, 26)).rank(job)
        breakdown = json.loads(result["ranking_breakdown"])
        self.assertEqual(result["age_days"], 1)
        self.assertIn("fit", breakdown)
        self.assertIn("practice", breakdown)
        self.assertTrue(all({"rule", "points", "explanation"} <= set(rule) for rules in breakdown.values() for rule in rules))
        self.assertAlmostEqual(sum(rule["points"] for rule in breakdown["application"]), result["actual_score"])

    def test_local_events_are_upcoming_sorted_and_source_linked(self):
        data = load_local_events()
        self.assertEqual(data["city"], "Austin, TX")
        self.assertEqual(data["events"], sorted(data["events"], key=lambda event: event["starts_at"]))
        self.assertTrue(all(event["url"].startswith("https://") for event in data["events"]))
        self.assertTrue(all(0 <= event["fit_score"] <= 100 for event in data["events"]))
        self.assertTrue(all(event["recommendation"] in {"recommended", "consider", "low"} for event in data["events"]))
        recruiting = next(event for event in data["events"] if event["id"] == "hackerx-austin-2026-09")
        self.assertEqual(recruiting["recommendation"], "recommended")
        self.assertIn("backend engineering", recruiting["skill_matches"])
        self.assertIn("meet recruiters", recruiting["fit_reason"].lower())

    def test_location_scope_defaults_can_exclude_or_isolate_foreign_roles(self):
        jobs = [
            {"location": "Austin, TX", "title": "US"},
            {"location": "London, UK", "title": "Foreign"},
            {"location": "London, England", "title": "Foreign England"},
            {"location": "Aarhus, Denmark", "title": "Foreign Denmark"},
            {"location": "Singapore", "title": "Foreign Singapore"},
        ]
        self.assertEqual([job["title"] for job in filter_jobs_by_location_scope(jobs, "us")], ["US"])
        self.assertEqual(
            [job["title"] for job in filter_jobs_by_location_scope(jobs, "foreign")],
            ["Foreign", "Foreign England", "Foreign Denmark", "Foreign Singapore"],
        )
        self.assertEqual(len(filter_jobs_by_location_scope(jobs, "")), 5)

    def test_levels_bank_maps_major_company_family_aliases(self):
        benchmarks = salary_benchmark_map()
        self.assertIs(benchmarks["amazonmusic"], benchmarks["amazon"])
        self.assertIs(benchmarks["microsoftai"], benchmarks["microsoft"])
        self.assertIs(benchmarks["nvidiaai"], benchmarks["nvidia"])
        self.assertEqual(benchmarks["realtorcom"]["staff_total_comp"], 223294)

    def test_phenom_provider_parses_search_and_full_job_detail(self):
        search = {"eagerLoadRefineSearch": {"data": {"jobs": [{
            "jobId": "R123", "title": "Staff Backend Software Engineer",
            "country": "United States of America", "location": "Austin, Texas, United States of America",
        }]}}}
        detail = {"jobDetail": {"data": {"job": {
            "jobId": "R123", "title": "Staff Backend Software Engineer",
            "multi_location": [{"location": "Austin, Texas, United States of America"}],
            "postedDate": "2026-08-26T00:00:00.000+0000",
            "description": "<p>Backend distributed systems platform APIs. Base Pay Range: $240,000 - $290,000.</p>" * 8,
        }}}}
        wrap = lambda value: f"<script>phApp.ddo = {json.dumps(value)}; phApp.experimentData = {{}};</script>"
        listings = phenom_search_items(wrap(search))
        item = phenom_job_item("Adobe", "https://careers.adobe.com/us/en", listings[0], wrap(detail))
        self.assertEqual(item["source"], "phenom")
        self.assertEqual(item["location"], "Austin, Texas, United States of America")
        self.assertEqual(item["salary_max"], 290000)
        self.assertIn("R123/Staff-Backend-Software-Engineer", item["url"])
        self.assertTrue(posting_is_relevant(item))

    def test_phenom_accepts_compact_timezone_and_requires_explicit_austin(self):
        self.assertTrue(_fresh_iso_listing("2026-08-27T00:00:00.000+0000"))
        self.assertTrue(phenom_listing_has_austin({"multi_location": ["Work At Home, Austin, Texas,United States"]}))
        self.assertTrue(phenom_listing_has_austin({"multi_location": ["Austin, United States of America, 78759"]}))
        self.assertTrue(phenom_listing_has_austin({"city": "Austin", "state": "Texas"}))
        self.assertTrue(phenom_listing_has_austin({"multi_location": ["TX-Austin", "NY-New York"]}))
        self.assertFalse(phenom_listing_has_austin({"multi_location": ["Round Rock, Texas,United States"]}))

    def test_staff_cloud_engineer_is_in_explicit_target_scope(self):
        job = {
            "title": "Staff Cloud Engineer",
            "location": "Austin, TX",
            "description": "Lead platform engineering for Kubernetes, Terraform, CI/CD, Python automation, and reliable cloud infrastructure. " * 8,
        }
        self.assertTrue(title_is_candidate(job))
        self.assertTrue(posting_is_relevant(job))

    def test_technical_senior_associate_and_manager_variants_are_in_scope(self):
        for title in (
            "Data Engineer - Senior Manager",
            "Payer Dev, Git & ML-Ops Engineer, Senior Associate",
            "GenAI Python Systems Engineer – Senior Associate",
        ):
            with self.subTest(title=title):
                self.assertTrue(title_is_candidate({"title": title}))

    def test_product_owner_vp_variants_and_description_level_director_are_excluded(self):
        self.assertFalse(title_is_candidate({"title": "Engineering Manager-Technical Product Owner"}))
        self.assertFalse(title_is_candidate({"title": "VPII, Software Engineering Manager & AI Lead"}))
        self.assertFalse(title_is_candidate({"title": "AVP- Senior Software Engineer"}))
        director = {
            "title": "GenAI Python Systems Engineer – Senior Manager",
            "location": "Austin, TX",
            "description": "Management Level Senior Manager. As a Director, lead Python APIs, cloud data platforms, and distributed systems. " * 6,
        }
        self.assertFalse(posting_is_relevant(director))

    def test_phenom_austin_collector_keeps_scanning_after_candidate_free_page(self):
        page_one = {"eagerLoadRefineSearch": {"data": {"jobs": [{
            "jobId": "R1", "title": "Customer Service Representative",
            "location": "Austin, Texas, United States of America", "postedDate": "2026-08-26",
        }]}}}
        page_two = {"eagerLoadRefineSearch": {"data": {"jobs": [{
            "jobId": "R2", "title": "Staff Backend Software Engineer",
            "location": "Austin, Texas, United States of America", "postedDate": "2026-08-27",
        }]}}}
        detail = {"jobDetail": {"data": {"job": {
            "jobId": "R2", "title": "Staff Backend Software Engineer",
            "multi_location": [{"location": "Austin, Texas, United States of America"}],
            "postedDate": "2026-08-27T00:00:00.000+0000",
            "description": "Build Python, Java, cloud APIs, distributed systems, and data platforms. " * 12,
        }}}}
        wrap = lambda value: f"<script>phApp.ddo = {json.dumps(value)}; phApp.experimentData = {{}};</script>"

        class Response:
            def __init__(self, body): self.body = body.encode()
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _limit): return self.body

        def fake_urlopen(request, timeout=30):
            url = request.full_url
            if "/job/R2/" in url:
                return Response(wrap(detail))
            return Response(wrap(page_two if "from=10" in url else page_one))

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = _phenom_austin_jobs(
                "Example", "https://careers.example.com/us/en",
                "https://careers.example.com/us/en/search-results?location=Austin", 2, 0, 30,
            )
        self.assertEqual(errors, [])
        self.assertEqual([item["title"] for item in items], ["Staff Backend Software Engineer"])

    def test_adobe_austin_collector_uses_public_exact_city_query(self):
        today = datetime.now(timezone.utc).date().isoformat()
        search = {"eagerLoadRefineSearch": {"data": {"jobs": [
            {
                "jobId": "R200", "title": "Senior Backend Software Engineer",
                "multi_location": ["Austin, Texas, United States of America"],
                "postedDate": today,
            },
            {
                "jobId": "R201", "title": "Senior Product Manager",
                "multi_location": ["Austin, Texas, United States of America"],
                "postedDate": today,
            },
        ]}}}
        detail = {"jobDetail": {"data": {"job": {
            "jobId": "R200", "title": "Senior Backend Software Engineer",
            "multi_location": [{"location": "Austin, Texas, United States of America"}],
            "postedDate": today,
            "description": "Build Java APIs, cloud platforms, and distributed data services. " * 12,
        }}}}
        wrap = lambda value: f"<script>phApp.ddo = {json.dumps(value)}; phApp.experimentData = {{}};</script>"
        requested_urls = []

        class Response:
            def __init__(self, body): self.body = body.encode()
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.body

        def fake_urlopen(request, timeout=30):
            requested_urls.append(request.full_url)
            return Response(wrap(detail if "/job/R200/" in request.full_url else search))

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = adobe_austin_jobs(max_pages=1, request_delay_seconds=0)
        self.assertEqual(errors, [])
        self.assertEqual([item["title"] for item in items], ["Senior Backend Software Engineer"])
        self.assertEqual(items[0]["location"], "Austin, Texas, United States of America")
        self.assertIn("qcity=Austin&from=0", requested_urls[0])
        self.assertNotIn("s=1", requested_urls[0])

    def test_quest_global_collector_uses_public_exact_city_query(self):
        today = datetime.now(timezone.utc).date().isoformat()
        search = {"eagerLoadRefineSearch": {"data": {"jobs": [{
            "jobId": "P-122027", "title": "Senior AI/ML Engineer",
            "city": "Austin", "state": "Texas", "postedDate": today,
        }]}}}
        detail = {"jobDetail": {"data": {"job": {
            "jobId": "P-122027", "title": "Senior AI/ML Engineer",
            "postedDate": today,
            "multi_location": [{"location": "Austin, Texas, United States"}],
            "description": "Build Python APIs, LLM systems, cloud platforms, and distributed services. Pay Range: $95000-$105000. " * 10,
        }}}}
        wrap = lambda value: f"<script>phApp.ddo = {json.dumps(value)}; phApp.experimentData = {{}};</script>"
        requested_urls = []

        class Response:
            def __init__(self, body): self.body = body.encode()
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.body

        def fake_urlopen(request, timeout=30):
            requested_urls.append(request.full_url)
            return Response(wrap(detail if "/job/P-122027/" in request.full_url else search))

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = questglobal_austin_jobs(max_pages=1, request_delay_seconds=0)
        self.assertEqual(errors, [])
        self.assertEqual([item["title"] for item in items], ["Senior AI/ML Engineer"])
        self.assertEqual(items[0]["company"], "Quest Global")
        self.assertEqual(items[0]["salary_max"], 105000)
        self.assertIn("qcity=Austin&from=0", requested_urls[0])
        self.assertTrue(QUEST_GLOBAL_AUSTIN_BOARD.endswith("qcity=Austin"))

    def test_circle_collector_scans_public_inventory_for_exact_austin(self):
        today = datetime.now(timezone.utc).date().isoformat()
        search = {"eagerLoadRefineSearch": {"data": {"jobs": [{
            "jobId": "JR-CIRCLE-1", "title": "Senior Backend Software Engineer",
            "country": "United States of America", "postedDate": today,
            "multi_location": ["Austin, Texas, United States of America"],
        }, {
            "jobId": "JR-CIRCLE-2", "title": "Staff Software Engineer",
            "country": "United States of America", "postedDate": today,
            "multi_location": ["San Francisco, California, United States of America"],
        }]}}}
        detail = {"jobDetail": {"data": {"job": {
            "jobId": "JR-CIRCLE-1", "title": "Senior Backend Software Engineer",
            "postedDate": today,
            "multi_location": ["Austin, Texas, United States of America"],
            "description": "Build Python APIs, cloud platforms, and distributed data services. " * 12,
        }}}}
        wrap = lambda value: f"<script>phApp.ddo = {json.dumps(value)}; phApp.experimentData = {{}};</script>"
        requested_urls = []

        class Response:
            def __init__(self, body): self.body = body.encode()
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.body

        def fake_urlopen(request, timeout=30):
            requested_urls.append(request.full_url)
            return Response(wrap(detail if "/job/JR-CIRCLE-1/" in request.full_url else search))

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = circle_austin_jobs(max_pages=1, request_delay_seconds=0)
        self.assertEqual(errors, [])
        self.assertEqual([item["title"] for item in items], ["Senior Backend Software Engineer"])
        self.assertEqual(items[0]["company"], "Circle")
        self.assertEqual(items[0]["location"], "Austin, Texas, United States of America")
        self.assertIn("search-results?s=1&from=0", requested_urls[0])

    def test_pwc_collector_uses_full_public_inventory_and_canonical_source(self):
        search = {"eagerLoadRefineSearch": {"data": {"jobs": [{
            "jobId": "751001WD", "title": "AI Engineer Manager",
            "multi_location": ["NY-New York", "TX-Austin"],
            "postedDate": datetime.now(timezone.utc).date().isoformat(),
        }]}}}
        detail = {"jobDetail": {"data": {"job": {
            "jobId": "751001WD", "title": "AI Engineer Manager",
            "multi_location": ["NY-New York", "TX-Austin"],
            "postedDate": datetime.now(timezone.utc).date().isoformat(),
            "description": "Lead Python APIs, AI platforms, cloud data systems, and distributed services. " * 10,
        }}}}
        wrap = lambda value: f"<script>phApp.ddo = {json.dumps(value)}; phApp.experimentData = {{}};</script>"

        class Response:
            def __init__(self, body): self.body = body.encode()
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return self.body

        def fake_urlopen(request, timeout=30):
            return Response(wrap(detail if "/job/751001WD/" in request.full_url else search))

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            items, errors = pwc_austin_jobs(max_pages=1, request_delay_seconds=0)

        self.assertEqual(errors, [])
        self.assertEqual(items[0]["source"], "pwc")
        self.assertEqual(items[0]["provider_job_id"], "751001WD")
        self.assertEqual(items[0]["location"], "Austin, TX / Multiple US locations")
        self.assertIn("jobs-us.pwc.com/us/en/job/751001WD/", items[0]["url"])

    def test_roku_parses_exact_austin_search_and_job_detail(self):
        search = '<tr role="link" data-job-url="https://www.weareroku.com/jobs/senior-data-engineer-austin-texas-united-states"><a aria-label="Title: Senior Data Engineer"></a></tr>'
        self.assertEqual(roku_search_listings(search)[0]["title"], "Senior Data Engineer")
        posting = {
            "@type": "JobPosting", "title": "Senior Data Engineer", "datePosted": "2026-08-27T00:00:00Z",
            "description": "<p>Build Python data pipelines and distributed cloud systems. Pay range $220,000 - $270,000.</p>",
            "identifier": {"value": "123"},
            "jobLocation": [{"address": {"addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "US"}}],
        }
        raw = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        item = roku_job_item(raw, "https://www.weareroku.com/jobs/senior-data-engineer-austin-texas-united-states")
        self.assertEqual(item["source"], "roku")
        self.assertEqual(item["location"], "Austin, Texas, US")
        self.assertEqual(item["salary_max"], 270000)

        posting["description"] += " This role is based in Bangalore, India, and requires hybrid working."
        contradictory = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        self.assertIsNone(roku_job_item(
            contradictory,
            "https://www.weareroku.com/jobs/senior-data-engineer-austin-texas-united-states",
        ))

    def test_roku_collector_reports_waf_challenge_instead_of_empty_inventory(self):
        class Response:
            status = 202

            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return b"<script>window.awsWafCookieDomainList = ['clinchtalent.com'];</script>"

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = roku_austin_jobs(request_delay_seconds=0)

        self.assertEqual(jobs, [])
        self.assertEqual(errors, ["Roku search: HTTP 202 AWS WAF challenge"])

    def test_roku_collector_reports_missing_public_cards_instead_of_empty_inventory(self):
        class Response:
            status = 200

            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return b"<main><div id='app'></div></main>"

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = roku_austin_jobs(request_delay_seconds=0)

        self.assertEqual(jobs, [])
        self.assertEqual(errors, ["Roku search: listing cards unavailable in public HTTP response; browser verification required"])

    def test_lever_posting_normalizes_description_date_and_salary(self):
        item = lever_posting_item("Esper", {
            "text":"Staff Software Engineer, Infrastructure", "hostedUrl":"https://jobs.lever.co/esper/1",
            "categories":{"location":"Austin, Texas"}, "createdAt":86400000,
            "descriptionPlain":"Cloud platform", "lists":[{"content":"Kubernetes &amp; distributed systems"}],
            "salaryRange":{"min":210000, "max":260000, "interval":"year"},
        })
        self.assertEqual(item["date_posted"], "1970-01-02")
        self.assertEqual(item["salary_max"], 260000)
        self.assertIn("Kubernetes & distributed systems", item["description"])

    def test_lever_company_jobs_excludes_stale_postings_before_persistence(self):
        now = datetime.now(timezone.utc)
        payload = [
            {
                "text": "Senior Backend Engineer", "hostedUrl": "https://jobs.lever.co/bumble/fresh",
                "categories": {"location": "Austin, Texas"},
                "createdAt": int((now - timedelta(days=5)).timestamp() * 1000),
                "descriptionPlain": "Build distributed backend services.",
            },
            {
                "text": "Staff Platform Engineer", "hostedUrl": "https://jobs.lever.co/bumble/stale",
                "categories": {"location": "Austin, Texas"},
                "createdAt": int((now - timedelta(days=45)).timestamp() * 1000),
                "descriptionPlain": "Build cloud infrastructure.",
            },
        ]

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = lever_company_jobs({"Bumble"})

        self.assertEqual(errors, [])
        self.assertEqual([job["url"] for job in jobs], ["https://jobs.lever.co/bumble/fresh"])

    def test_public_board_collectors_report_remote_disconnects(self):
        with patch(
            "jobfinder.infrastructure.providers.urllib.request.urlopen",
            side_effect=http.client.RemoteDisconnected("peer closed connection"),
        ):
            greenhouse_jobs, greenhouse_errors = greenhouse_company_jobs({"Affirm"})
            lever_jobs, lever_errors = lever_company_jobs({"Bumble"})

        self.assertEqual(greenhouse_jobs, [])
        self.assertEqual(greenhouse_errors, ["Affirm: RemoteDisconnected"])
        self.assertEqual(lever_jobs, [])
        self.assertEqual(lever_errors, ["Bumble: RemoteDisconnected"])

    def test_qrypt_lever_board_requires_explicit_austin(self):
        now = datetime.now(timezone.utc)
        payload = [{
            "text": "Senior Backend Engineer",
            "hostedUrl": "https://jobs.lever.co/qrypt/remote",
            "categories": {"location": "Remote, United States"},
            "createdAt": int((now - timedelta(days=2)).timestamp() * 1000),
            "descriptionPlain": "Build distributed backend services.",
        }, {
            "text": "Senior Cloud Engineer",
            "hostedUrl": "https://jobs.lever.co/qrypt/austin",
            "categories": {"location": "Austin, TX"},
            "createdAt": int((now - timedelta(days=3)).timestamp() * 1000),
            "descriptionPlain": "Build cloud infrastructure and APIs.",
        }]

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = lever_company_jobs({"Qrypt"})
        self.assertEqual(errors, [])
        self.assertEqual([job["url"] for job in jobs], ["https://jobs.lever.co/qrypt/austin"])

    def test_favor_delivery_lever_board_excludes_texas_wide_copy(self):
        now = datetime.now(timezone.utc)
        payload = [{
            "text": "Engineering Manager",
            "hostedUrl": "https://jobs.lever.co/askfavor/texas",
            "categories": {"location": "Texas"},
            "createdAt": int((now - timedelta(days=2)).timestamp() * 1000),
            "descriptionPlain": "Lead a backend engineering team.",
        }, {
            "text": "Engineering Manager",
            "hostedUrl": "https://jobs.lever.co/askfavor/austin",
            "categories": {"location": "Austin, TX"},
            "createdAt": int((now - timedelta(days=3)).timestamp() * 1000),
            "descriptionPlain": "Lead a backend engineering team in Austin.",
        }]

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(payload).encode()

        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", return_value=Response()):
            jobs, errors = lever_company_jobs({"Favor Delivery"})
        self.assertEqual(errors, [])
        self.assertEqual([job["url"] for job in jobs], ["https://jobs.lever.co/askfavor/austin"])

    def test_collector_deduplicates_links_and_company_title_within_a_batch(self):
        items = [
            {"company":"Alpha", "title":"Senior Backend Engineer", "url":"https://jobs.example/1"},
            {"company":"Alpha", "title":"Senior Backend Engineer", "url":"https://jobs.example/repost"},
            {"company":"Beta", "title":"Staff Platform Engineer", "url":"https://jobs.example/2"},
            {"company":"Gamma", "title":"Staff Platform Engineer", "url":"https://jobs.example/2"},
        ]
        selected = dedupe_job_candidates(items, set(), set())
        self.assertEqual([(item["company"], item["title"]) for item in selected], [
            ("Alpha", "Senior Backend Engineer"), ("Beta", "Staff Platform Engineer"),
        ])

    def test_collector_deduplicates_normalized_company_and_title_variants(self):
        items = [
            {"company":"Seekr", "title":"AI Engineer/Scientist - Staff", "url":"https://jobs.example/1"},
            {"company":"Seekr, Inc.", "title":"AI Engineer/Scientist, Staff", "url":"https://jobs.example/2"},
        ]
        selected = dedupe_job_candidates(items, set(), set())
        self.assertEqual(len(selected), 1)

    def test_ats_candidates_are_round_robin_across_companies(self):
        items = [
            {"company": "Alpha", "title": "A1"}, {"company": "Alpha", "title": "A2"}, {"company": "Alpha", "title": "A3"},
            {"company": "Beta", "title": "B1"}, {"company": "Beta", "title": "B2"}, {"company": "Gamma", "title": "G1"},
        ]
        selected = round_robin_company_candidates(items, limit=4, max_per_company=2)
        self.assertEqual([(item["company"], item["title"]) for item in selected], [
            ("Alpha", "A1"), ("Beta", "B1"), ("Gamma", "G1"), ("Alpha", "A2"),
        ])

    def test_apple_provider_reports_socket_timeouts_without_aborting_collection(self):
        with patch("jobfinder.infrastructure.providers.urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            jobs, errors = apple_austin_jobs(max_pages=1)
        self.assertEqual(jobs, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("timeout", errors[0].lower())

    def test_apple_detail_requires_fresh_structured_austin_and_ignores_other_location_pay(self):
        job = {
            "postingTitle": "Senior Software Engineer, Apple Ads",
            "postingDateMeta": date.today().isoformat(),
            "jobNumber": "200680227",
            "locations": [
                {"id": "postLocation-AST", "city": "Austin", "stateProvince": "Texas", "countryName": "United States"},
                {"id": "postLocation-CUP", "city": "Cupertino", "stateProvince": "California", "countryName": "United States"},
            ],
            "localizations": {"en_US": {"posting": {
                "jobSummary": "Build internet-scale backend systems and cloud services. " * 5,
                "description": "Design distributed microservices, data pipelines, and reliable APIs. " * 5,
                "responsibilities": "Operate low-latency platforms and mentor engineers.",
                "minimumQualifications": "Java, Kafka, Kubernetes, and observability.",
            }}},
            "postingFooters": [{
                "postLocationId": "postLocation-CUP",
                "localizations": {"en_US": [{"content": "California base pay range is $184,700 to $324,800."}]},
            }],
        }
        def page(value):
            payload = {"loaderData": {"jobDetails": {"jobsData": value}}}
            return f'<script>window.__staticRouterHydrationData = JSON.parse({json.dumps(json.dumps(payload))});</script>'
        url = "https://jobs.apple.com/en-us/details/200680227-0157/senior-software-engineer-apple-ads?team=SFTWR"
        item = apple_job_item(page(job), url)
        self.assertIsNotNone(item)
        self.assertEqual(item["location"], "Austin, TX / Multiple US locations")
        self.assertEqual(item["provider_job_id"], "200680227")
        self.assertEqual(item["salary_text"], "")
        self.assertIsNone(item["salary_min"])
        self.assertIsNone(apple_job_item(page(dict(job, locations=job["locations"][1:])), url))
        self.assertIsNone(apple_job_item(page(dict(job, postingDateMeta="2026-01-01")), url))

    def test_linkedin_detail_gate_enforces_two_second_minimum(self):
        current = [0.0]
        sleeps = []
        def clock(): return current[0]
        def sleeper(seconds):
            sleeps.append(seconds)
            current[0] += seconds
        gate = PostingStartGate(0.1, clock=clock, sleeper=sleeper)
        gate.wait(); gate.wait(); gate.wait()
        self.assertEqual(gate.interval_seconds, 2.0)
        self.assertEqual(sleeps, [2.0, 2.0])

    def test_austin_sweep_queries_are_diverse_unique_and_on_level(self):
        queries = query_groups(AUSTIN_QUERY_GROUPS + (" Senior Software Engineer ",))
        self.assertGreaterEqual(len(queries), 40)
        self.assertEqual(len(queries), len({query.casefold() for query in queries}))
        self.assertTrue(all(any(level in query.lower() for level in ("senior", "staff", "manager", "engineer ii", "engineer iii", "engineer 2", "engineer 3", "lead")) for query in queries))
        self.assertTrue(all("principal" not in query.lower() for query in queries))

    def test_resume_review_keeps_confirmed_but_unwritten_skills_as_rewrite_advice(self):
        demand = __import__("collections").Counter({"Kubernetes": 12, "TypeScript": 8, "Data pipelines": 6})
        jobs = [{"title": "Staff AI Platform Engineer", "description": "Generative AI LLM platform"}]
        review = review_resume("Senior backend engineer. Led architecture. Improved latency by 40%.", jobs, demand)
        advice = " ".join(item["action"] for item in review["recommendations"])
        self.assertIn("Core Skills", advice)
        self.assertEqual(review["ai_roles"], 1)
        self.assertEqual(review["dimensions"][3]["assessment"], "Missing from the document")

    def test_collector_relevance_rejects_unrelated_and_frontend_roles(self):
        description = "Backend distributed systems API platform " * 30
        self.assertTrue(posting_is_relevant({
            "title": "CTIO-AI Engineer-Sr Associate",
            "description": ("Developing AI/ML systems and integrating AI into products. "
                            "Deploying LLMs into production and designing and optimizing RAG pipelines. ") * 5,
            "location": "Austin, TX / Multiple US locations",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "CTIO-AI Engineer-Sr Associate",
            "description": "Advise clients on AI strategy, budgets, stakeholder meetings, and vendor selection. " * 6,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Epic Payer Platform, Senior Associate",
            "description": ("Deliver strategies in Operations Consulting, analyze operational challenges, "
                            "manage client engagements, and improve payer modernization processes. ") * 6,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Engineering Manager, Design System",
            "description": ("Lead a design system team building reusable components, design tokens, and theming "
                            "across web, iOS, and Android. Guide generic API design for UI components. ") * 6,
            "location": "Austin, TX",
        }))
        self.assertTrue(posting_is_relevant({"title": "Staff Backend Software Engineer", "description": description}))
        self.assertTrue(posting_is_relevant({"title": "Staff Database Engineer", "description": "database infrastructure distributed systems " * 30}))
        self.assertTrue(posting_is_relevant({"title": "Staff Data Engineer", "description": "data platform cloud infrastructure distributed systems " * 30}))
        self.assertTrue(posting_is_relevant({"title": "Senior Machine Learning Engineer", "description": "Python machine learning platform distributed systems " * 30, "location": "Austin, TX"}))
        self.assertTrue(posting_is_relevant({"title": "Staff AI Engineer", "description": "Python applied AI platform cloud infrastructure " * 30, "location": "Austin, TX"}))
        self.assertTrue(posting_is_relevant({
            "title": "Security Research Engineer III",
            "description": ("Build internal tooling, data pipelines, cloud infrastructure, and infrastructure as code. "
                            "Develop Python automation and CI/CD for security-data ETL pipelines. ") * 12,
            "location": "Austin, Texas | Remote",
        }))
        disguised_principal = "The role is a principal-level technical leader building backend platform infrastructure. " * 12
        self.assertFalse(posting_is_relevant({"title": "Staff Platform Engineer", "description": disguised_principal, "location": "Austin, TX"}))
        named_disguised_principal = "The Staff Platform Engineer is a principal-level technical leader building backend platform infrastructure. " * 12
        self.assertFalse(posting_is_relevant({"title": "Staff Platform Engineer", "description": named_disguised_principal, "location": "Austin, TX"}))
        principal_level_individual_contributor = "This role is for a principal-level individual contributor in Data Engineering building cloud data pipelines and distributed platform infrastructure. " * 12
        self.assertFalse(posting_is_relevant({"title": "Staff Data Engineer", "description": principal_level_individual_contributor, "location": "Austin, TX"}))
        technical_system_engineer = "Own software engineering and platform engineering across distributed systems, infrastructure as code, CI/CD, cloud services, backend Java, and site reliability. " * 12
        self.assertTrue(posting_is_relevant({"title": "Sr. System Engineer", "description": technical_system_engineer, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Cashier", "description": description}))
        self.assertFalse(posting_is_relevant({"title": "Senior Product Designer, Monetization Platform", "description": description}))
        self.assertFalse(posting_is_relevant({"title": "Senior Counsel, Capital Markets", "description": description}))
        self.assertFalse(posting_is_relevant({"title": "Staff Product Data Scientist, Infrastructure", "description": description}))
        self.assertTrue(posting_is_relevant({"title": "Senior API Engineer", "description": description}))
        self.assertTrue(posting_is_relevant({"title": "Engineering Manager, Backend Platform", "description": description, "location": "Austin, TX"}))
        self.assertTrue(posting_is_relevant({"title": "Software Development Manager", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Product Manager, Platform", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr Fiber Deploy TIPM, Global Connectivity Infrastructure Development", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({
            "title": "Security Engineer II, Stores AppSec",
            "description": ("Conduct application security reviews and penetration tests, document findings, and advise service owners on remediation. " * 8),
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Senior Technical Project Manager for Healthcare Data Engineering", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Customer Engineering Manager, Majors - Texas", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Solutions Engineering Manager, Iberia & Italy", "description": description, "location": "Hybrid"}))
        self.assertFalse(posting_is_relevant({"title": "Electrical Engineering Manager", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Product Engineering Manager", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Production Engineering Manager", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Applications Engineering Manager", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Project Engineering Manager - Water", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Mechanical Engineering Manager", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. Power Design Engineer, DC GPU Platform Design", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "VP, Software Engineering Manager", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Engineering Manager", "description": "Rapid manufacturing capabilities and team leadership. " * 20, "location": "Austin, TX"}))
        self.assertTrue(posting_is_relevant({"title": "Engineering Manager", "description": "Lead a software engineering team building backend APIs and distributed systems. " * 20, "location": "Austin, TX"}))
        self.assertTrue(posting_is_relevant({"title": "Manager, Engineering", "description": "Manage software engineers, own cloud software architecture, write code, and build backend APIs. " * 20, "location": "Austin, TX"}))
        self.assertTrue(posting_is_relevant({"title": "Mainframe Software Engineering Manager", "description": "Lead a software engineering team modernizing backend applications with CI/CD, APIs, SRE, and cloud integrations. " * 20, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. Water Systems Engineer, DC Design Engineering", "description": "Design water treatment systems, utility connections, piping, construction specifications, and data center facilities. " * 20, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Platform PnP Engineer",
            "description": "Lead platform power and performance strategy for AI compute platforms. "
                           "Drive silicon and platform power-performance architecture, including power delivery and thermal solutions. " * 8,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Microsoft 365 Platform Engineer – Automation, Agents, & Copilot",
            "description": "Administer Microsoft 365 Apps and SharePoint Online, develop Power Automate flows in Copilot Studio, and manage license administration. " * 8,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "AI/ML Logic Design Engineer-Senior",
            "description": "Design NPU microarchitecture and RTL development. Drive RTL design in SystemVerilog through synthesis and tape-out. " * 8,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Senior System Software Engineer - GPU Power Management",
            "description": "Architect GPU power-management software through pre-silicon validation, silicon bring-up and device-driver architecture, embedded or real-time software. " * 8,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Manager, Systems Software Engineering",
            "description": "Own device-management systems and services, procurement, mobile lifecycle management, and enterprise printing services for cloud platform IT. " * 8,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Application Software Engineer",
            "description": "The Test Engineer position is within Supply Chain Operations and plays a critical role in server production. Build cloud test infrastructure and support the production floor. " * 8,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Staff Threat Detection Engineer",
            "description": "Run threat hunting across SIEM platforms and purple team exercises. Build security operations dashboards and incident response automation. " * 8,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Security Engineer - Detection & Response",
            "description": "Lead threat hunting and incident response through SIEM and SOAR, write detection rules, and perform endpoint forensics. Build Python automation for cloud telemetry. " * 8,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Sr Systems Development Engineer, AWS AI/ML Servers", "description": "Debug accelerator server hardware, firmware, kernels, PCIe topology, GPU diagnostics, and Linux drivers. " * 20, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Director of Engineering", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Staff Frontend Software Engineer", "description": description}))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Web Software Architect, AI Experiences",
            "description": ("Own the web frontend architect direction, frontend architecture standards, "
                            "component library, React design systems, accessibility, and user experience. ") * 12,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Senior ASIC Front End Infrastructure Engineer", "description": description}))
        self.assertFalse(posting_is_relevant({"title": "Staff Backend Software Engineer", "description": description, "location": "Toronto, Canada"}))

    def test_collector_relevance_rejects_fullstack_hardware_and_clearance_only_roles(self):
        description = "Backend platform infrastructure distributed systems " * 20
        self.assertTrue(posting_is_relevant({"title": "Fullstack Staff Software Engineer", "description": description + " React TypeScript", "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior C++ Software Engineer - Chip Design Tools", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior System Software Engineer, CUDA Driver for Windows", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({
            "title": "Senior System Software Engineer - Performance",
            "description": ("Develop software for next-generation SoCs in pre-silicon and post-silicon phases. "
                            "Analyze hardware policies, device drivers and real-time programming for ARM systems. ") * 10,
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Senior HPC Support Engineer - Ethernet and AI Infrastructure", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. Software Engineer - Wheeled Controls", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Staff Software Engineer - Humanoid Controls", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Manager, Software Engineering - Robotics Manipulation", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Robotics Systems Engineer II, Tech Deployment", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Systems Engineer - Chassis",
            "description": description + " Structural mechanics, actuation, power distribution, thermal management, wiring harnesses, and drivetrain integration.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Senior System Integration Engineer - Soft Goods / Gloves / Grip", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. Delivery Consultant - Migrations, Cloud Platform", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. Supplier Quality Engineer, Infrastructure Reliability & Quality", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Physical Security Engineering Manager, Data Center Design Engineering", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Software Engineer II, Annapurna Labs ML Acceleration System Software", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Software Development Engineer II, Post-Silicon Validation", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Software Engineer - SoC DevOps", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Software Engineer – Benchmarking, Performance & Competitive Analysis",
            "description": description + " Embedded systems performance analysis for semiconductor silicon and SoC products using RTOS, oscilloscopes, logic analyzers, and hardware emulation.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Engineering Manager – ERCOT Modeling Team",
            "description": description + " Lead electrical engineering studies of the power grid using PSS/E and PSCAD for generator interconnection and dynamic stability.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Power Systems Engineer III",
            "description": description + " Perform power system impact and generator interconnection studies for the electrical power grid using PSS/E, PSCAD, and dynamic stability analysis.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Software Development Engineer II, Post-Silicon Validation", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Software Dev Engineer II", "description": description + " Design, develop, implement, test, and document embedded or distributed software applications.", "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({
            "title": "Staff Engineer, Software (.Net)",
            "description": description + " Familiarity working with hardware devices, card readers, serial communication, CANBUS, and real-time embedded development.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Software Development Engineer, OneMHS Software Controls and Science",
            "description": description + " Build software controls for warehouse automation, material handling equipment, industrial control systems, and Human Machine Interfacing platforms.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Sr. Software Engineer - Radio", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. Software Engineer II, Linux Sensor - CTIO", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. Software Engineer II, MacOS Sensor - CTIO", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. Software Engineer II, Sensor - Mac, Linux, or Windows (Hybrid)", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Software Developer - OneStream/EPM Development", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Data Engineer (BI)", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Staff Software Engineer, Linux Kernel & Driver Development", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Virtual Platform Software Engineer, Machine Learning Accelerators", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. RF Software Engineer (Starlink)", "description": description, "location": "Bastrop, TX"}))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Systems Software Engineer",
            "description": description + " Ability to obtain a security clearance.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Site Reliability Engineer",
            "description": description + " Must possess and maintain TS/SCI w/Poly security clearance.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({
            "title": "Senior Backend Software Engineer",
            "description": description + " U.S. citizenship is required for this role.",
            "location": "Austin, TX",
        }))
        self.assertTrue(posting_is_relevant({
            "title": "Senior Backend Software Engineer",
            "description": description + " Must be a U.S. person as defined by applicable export-control regulations.",
            "location": "Austin, TX",
        }))
        self.assertTrue(posting_is_relevant({
            "title": "Senior Backend Software Engineer",
            "description": description + " Applicant must be a U.S. Citizen, lawful permanent resident of the U.S., or protected individual.",
            "location": "Austin, TX",
        }))
        self.assertTrue(posting_is_relevant({
            "title": "Senior Backend Software Engineer",
            "description": description + " Must be a U.S. citizen or lawful permanent resident.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Senior AI Tech Architect - AI Platforms", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Reliability Engineer", "description": description + " Reliability test plan and stress based MTBF analysis.", "location": "Austin, TX"}))
        self.assertTrue(posting_is_relevant({"title": "Senior Software Engineer", "description": description + " Full stack ownership using React and Node.", "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Software Engineer", "description": description + " This is a front-end focused Angular role.", "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({
            "title": "Sr Software Engineer",
            "description": ("Build mobile applications and own the iOS app lifecycle using Swift, "
                            "Objective-C, UIKit, and SwiftUI. Optimize mobile app performance. ") * 10,
            "location": "Austin, TX",
        }))
        self.assertTrue(posting_is_relevant({
            "title": "Senior Software Engineer",
            "description": description + " Build backend microservices and APIs for mobile application clients.",
            "location": "Austin, TX",
        }))
        self.assertTrue(posting_is_relevant({
            "title": "Staff Software Engineer, Control Plane",
            "description": description + " Own C++ management APIs and collaborate with front end focused engineers on the React console.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Senior Software Engineer, Runtime", "description": description + " Own the scheduler the rest of the engine is built on for our game engine.", "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Compiler Engineer Infrastructure", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Virtual Platform Functional Modeling Engineer", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. Software Development Engineer", "description": description + " Develop compilers and network distribution software for semiconductor operations.", "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Staff Engineer, Software - Open BMC", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({
            "title": "Staff Engineer, Software",
            "description": description + " Own the HW/SW interface, board management controllers, and low-level drivers.",
            "location": "Austin, TX",
        }))
        self.assertFalse(posting_is_relevant({"title": "Sr. Software Engineer, Sensor Event Runtime", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Software Engineer - Studio Tools", "description": description + " Build user-facing applications with UX designers and UI frameworks.", "location": "Austin, TX"}))
        self.assertTrue(posting_is_relevant({"title": "Senior Staff Machine Learning Engineer", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Staff Machine Learning Research Engineer", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Staff ML Engineer, Perception Research", "description": description, "location": "Mountain View, CA"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Machine Learning Engineer, Developer Advocacy", "description": description, "location": "Remote - US"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Product Solutions Architect - LLM Observability", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Software Engineer - Enterprise Architecture & AI Solutions Engineering", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior AI Engineer", "description": description + " Build an AI-assisted silicon design framework.", "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Sr. PD Methodology Engineer, Cloud Scale Machine Learning", "description": description, "location": "Austin, TX"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Backend Engineer", "description": description, "location": "Remote Portugal"}))
        self.assertFalse(posting_is_relevant({"title": "Senior Data Engineer", "description": description, "location": "Tel Aviv, Israel"}))
        self.assertFalse(posting_is_relevant({"title": "Staff Data Engineer", "description": description, "location": "Gurugram"}))

    def test_salary_parser_accepts_labeled_range_without_dollar_sign(self):
        salary = extract_salary("Additional Information Base Pay Range: 198,240.00 - 272,580.00 USD Annual")
        self.assertEqual(salary["salary_max"], 272580)

    def test_salary_parser_accepts_per_year_suffix_inside_range(self):
        salary = extract_salary("Compensation: $170,000/year - $230,000/year + equity")
        self.assertEqual(salary["salary_min"], 170000)
        self.assertEqual(salary["salary_max"], 230000)

    def test_salary_parser_accepts_usd_after_each_dollar_amount(self):
        salary = extract_salary("The salary range for this role is $126,000. USD - $174,000. USD.")
        self.assertEqual(salary["salary_min"], 126000)
        self.assertEqual(salary["salary_max"], 174000)

    def test_salary_parser_accepts_unseparated_five_digit_range(self):
        salary = extract_salary("Pay Range: $95000-$105000")
        self.assertEqual(salary["salary_min"], 95000)
        self.assertEqual(salary["salary_max"], 105000)

    def test_salary_parser_accepts_between_and_range_before_separate_ote(self):
        salary = extract_salary(
            "The base pay range is expected to be between $188,641 and $320,335/year "
            "with an expected OTE between $212,000 and $360,000/year."
        )
        self.assertEqual(salary["salary_min"], 188641)
        self.assertEqual(salary["salary_max"], 320335)
        self.assertEqual(salary["salary_type"], "base")

    def test_salary_parser_does_not_read_remote_as_ote(self):
        salary = extract_salary(
            "#LI-REMOTE (Pay Transparency Range: $186,000 - $280,000) "
            "The national base salary range for this role is posted above."
        )
        self.assertEqual(salary["salary_type"], "base")

    def test_salary_parser_recognizes_ote_as_a_whole_word(self):
        salary = extract_salary("Expected OTE: $212,000 - $360,000 per year")
        self.assertEqual(salary["salary_type"], "total")

    def test_salary_parser_recognizes_a_following_base_salary_explanation(self):
        salary = extract_salary(
            "The pay range for this position is between $100,000 - 160,000 plus Incentive Bonus. "
            "Starting salary may vary based on the role and location. Our total rewards package "
            "includes a base salary determined based on experience and skill set."
        )
        self.assertEqual(salary["salary_min"], 100000)
        self.assertEqual(salary["salary_max"], 160000)
        self.assertEqual(salary["salary_type"], "base")

    def test_salary_parser_annualizes_hourly_text_range(self):
        salary = extract_salary("Pay Range: $40.10-$66.83/hour")
        self.assertAlmostEqual(salary["salary_min"], 83408)
        self.assertAlmostEqual(salary["salary_max"], 139006.4)
        self.assertIn("annualized", salary["salary_text"])

    def test_normalizer_displays_structured_salary_range(self):
        job = normalize_item({
            "company":"Pay Co", "title":"Senior Backend Software Engineer", "location":"Austin, TX",
            "url":"https://jobs.example/pay", "description":"Backend distributed systems " * 20,
            "salary_min":235450, "salary_max":304700,
        })
        self.assertEqual(job["salary_text"], "$235,450 - $304,700")

    def test_encoded_ats_html_is_cleaned(self):
        self.assertEqual(clean_text("&lt;p&gt;Backend &amp;amp; API&lt;/p&gt;"), "Backend & API")

    def test_principal_backend_title_is_over_target_level(self):
        job = {"company": "Principal Co", "title": "Principal Backend Software Engineer", "description": "Python distributed systems API platform " * 20, "location": "Austin, TX", "salary_max": 280000}
        result = score(job, PROFILE, set(), {})
        self.assertIn("Principal-level overreach", json.loads(result["concerns"]))
        self.assertFalse(posting_is_relevant(job))

    def test_austin_proper_excludes_metro_area(self):
        self.assertTrue(is_austin_proper_location("Austin, TX"))
        self.assertTrue(is_austin_proper_location("Austin, Texas (Hybrid)"))
        self.assertTrue(is_austin_proper_location("US TX Austin"))
        self.assertTrue(is_austin_proper_location("US TX Austin / US NY New York"))
        self.assertTrue(is_austin_proper_location("USA - Austin, TX"))
        self.assertTrue(is_austin_proper_location("Austin, Texas, United States of America / Mountain View, California, United States of America"))
        self.assertTrue(is_austin_proper_location("Work At Home, Austin, Texas, United States"))
        self.assertTrue(is_austin_proper_location("100 Main Street, Austin, Texas, United States"))
        self.assertFalse(is_austin_proper_location("Austin"))
        self.assertFalse(is_austin_proper_location("Austin, Texas Metropolitan Area"))
        self.assertFalse(is_austin_proper_location("Round Rock, TX"))

    def test_company_board_boundary_requires_exact_austin_and_relevance(self):
        base = {
            "company": "Saved Co",
            "title": "Senior Backend Software Engineer",
            "description": "Python distributed systems API platform " * 20,
        }
        self.assertTrue(posting_is_austin_relevant({**base, "location": "Austin, TX"}))
        self.assertFalse(posting_is_austin_relevant({**base, "location": "San Francisco, CA"}))
        self.assertFalse(posting_is_austin_relevant({**base, "location": "Austin, Texas Metropolitan Area"}))
        self.assertFalse(posting_is_austin_relevant({**base, "location": "Austin, TX", "title": "Frontend UI Engineer"}))

    def test_austin_commute_zone_includes_bastrop_but_not_distant_cities(self):
        self.assertTrue(is_austin_commutable_location("Bastrop, TX"))
        self.assertTrue(is_austin_commutable_location("US TX Round Rock / Redmond, WA"))
        self.assertEqual(austin_commute_place("Bastrop, TX")["minutes"], "35–45")
        self.assertFalse(is_austin_commutable_location("San Marcos, TX"))
        self.assertFalse(is_austin_commutable_location("Austin, Texas Metropolitan Area"))

    def test_short_foreign_country_code_is_detected_without_substring_false_positive(self):
        self.assertTrue(is_explicitly_non_us_location("Remote UK"))
        self.assertTrue(is_explicitly_non_us_location("London, GB"))
        self.assertFalse(is_explicitly_non_us_location("Truckee, CA"))
        self.assertFalse(is_explicitly_non_us_location("Work At Home, Indianapolis, Indiana, United States"))
        self.assertFalse(is_explicitly_non_us_location("Work At Home, Santa Fe, New Mexico, United States"))

    def test_relevance_keeps_multi_location_role_with_exact_austin_and_foreign_office(self):
        self.assertTrue(posting_is_relevant({
            "title": "Machine Learning Engineer III",
            "location": "Kirkland, Washington, United States of America; Vancouver, British Columbia, Canada; Austin, Texas, United States of America",
            "description": "Build and operate production Python data pipelines, cloud infrastructure, APIs, and machine learning platform systems. " * 8,
        }))

    def test_technical_sourcing_role_is_not_a_software_candidate(self):
        self.assertFalse(posting_is_relevant({
            "title": "Senior Cloud Software Engineer Technical Sourcing Specialist",
            "location": "Austin, TX",
            "description": "Recruit and source cloud software engineering candidates. " * 10,
        }))

    def test_manager_and_lead_title_order_variants_are_candidates(self):
        self.assertTrue(title_is_candidate({"title": "Senior Manager - Software Development Engineering"}))
        self.assertTrue(title_is_candidate({"title": "Lead Java Software Engineer"}))
        self.assertTrue(title_is_candidate({"title": "Manager, Software Development & Engineering"}))
        self.assertTrue(title_is_candidate({"title": "Software Development & Engineering Lead"}))
        self.assertTrue(title_is_candidate({"title": "Manager, Engineering Observability"}))
        self.assertTrue(title_is_candidate({"title": "Manager, Secrets Management Platform"}))
        self.assertTrue(title_is_candidate({"title": "Cyber Full Stack Manager"}))
        self.assertTrue(title_is_candidate({"title": "Cyber Forward Deployed Engineer - Manager"}))
        self.assertTrue(title_is_candidate({"title": "Senior Java Engineer - AWS (Remote)"}))
        self.assertTrue(title_is_candidate({"title": "Java Tech Lead - Digital Banking (Remote)"}))
        self.assertTrue(title_is_candidate({"title": "Systems Engineer III - Automation (Remote)"}))
        self.assertFalse(title_is_candidate({"title": "Systems Engineer III - Software Packager (Remote)"}))
        self.assertFalse(title_is_candidate({"title": "Network Infrastructure Engineer III (Remote)"}))
        self.assertFalse(title_is_candidate({"title": "Senior Mainframe DB2 Database Administrator"}))
        self.assertFalse(posting_is_relevant({
            "title": "Sr Manager, Software Development & Engineering Senior",
            "location": "Austin, Texas, United States",
            "description": "Software Development Engineer in Test (SDET) Lead driving quality engineering, testing strategy, automation frameworks, and test coverage. " * 8,
        }))

    def test_bastrop_company_is_protected_from_practice_burn(self):
        job = {
            "company": "SpaceX", "title": "Senior Backend Software Engineer", "location": "Bastrop, TX",
            "description": "Python distributed systems backend platform API infrastructure " * 10,
            "date_posted": "2026-08-25", "salary_max": 260000,
        }
        result = score(job, PROFILE, set(), {"spacex": {"austin_jobs": 1, "remote_jobs": 0}})
        self.assertEqual(result["burn_cost"], 8.5)
        self.assertIn("Austin commute zone", result["actual_reason"])
        self.assertTrue(is_explicitly_non_us_location("Belgrade, Serbia"))

    def test_remote_company_signal_raises_burn_without_decision_metadata(self):
        job = {
            "company": "Signal Co",
            "title": "Senior Backend Software Engineer",
            "location": "United States (Remote)",
            "description": "Python Kafka distributed systems microservices platform architecture",
            "date_posted": "2026-08-25",
        }
        result = score(job, PROFILE, set(), {"signal co": {"austin_jobs": 0, "remote_jobs": 4}})
        self.assertEqual(result["burn_cost"], 8.0)
        self.assertNotIn("decision", result)
        self.assertGreaterEqual(result["practice_score"], 0)

    def test_actual_score_rewards_target_comp_ai_and_austin(self):
        base = {"company": "Actual Co", "title": "Senior Backend Software Engineer", "description": "Python Kafka distributed systems backend platform API " * 10, "date_posted": "2026-08-25", "salary_max": 220000}
        target = base | {"title": "Staff Backend Software Engineer", "location": "Austin, TX", "salary_max": 280000, "description": base["description"] + " generative AI application platform"}
        self.assertGreater(score(target, PROFILE, set(), {})["actual_score"], score(base, PROFILE, set(), {})["actual_score"])

    def test_actual_score_separates_visibility_floor_from_240k_target(self):
        job = {"company": "Comp Co", "title": "Staff Backend Software Engineer", "description": "Python Kafka distributed systems API platform " * 10, "location": "Remote - US", "date_posted": "2026-08-25"}
        target = score(job | {"salary_max": 244100}, PROFILE, set(), {})
        below = score(job | {"salary_max": 203400}, PROFILE, set(), {})
        self.assertGreaterEqual(target["actual_score"] - below["actual_score"], 2.0)
        self.assertIn("below $240k target", below["actual_reason"])

    def test_specialized_ml_role_is_penalized_without_resume_evidence(self):
        common = {
            "company":"AI Co", "location":"Austin, TX", "date_posted":"2026-08-25", "salary_max":280000,
            "description":"Python distributed systems cloud platform machine learning production services " * 20,
        }
        ml = score(common | {"title":"Senior Machine Learning Engineer"}, PROFILE, set(), {})
        backend = score(common | {"title":"Senior Backend Software Engineer"}, PROFILE, set(), {})
        self.assertLess(ml["actual_score"], backend["actual_score"])
        self.assertIn("not evidenced", " ".join(json.loads(ml["concerns"])))

    def test_old_posting_is_forced_below_fresh_equivalent(self):
        base = {
            "company": "Freshness Co",
            "title": "Staff Backend Software Engineer",
            "location": "Austin, TX",
            "description": "Python Kafka distributed systems microservices generative AI application " * 10,
            "salary_max": 300000,
        }
        today = datetime.now(timezone.utc).date()
        fresh = score(base | {"date_posted": today.isoformat()}, PROFILE, set(), {})
        old = score(base | {"date_posted": (today - timedelta(days=90)).isoformat()}, PROFILE, set(), {})
        self.assertGreaterEqual(fresh["actual_score"] - old["actual_score"], 5.0)
        self.assertLessEqual(old["actual_score"], 1.5)

    def test_sourced_market_compensation_fills_missing_posted_salary(self):
        job = {
            "company": "Market Co",
            "title": "Staff Backend Software Engineer",
            "location": "Austin, TX",
            "description": "Python Kafka distributed systems microservices generative AI application " * 10,
            "date_posted": "2026-08-25",
        }
        missing = score(job, PROFILE, set(), {})
        enriched = score(job | {"market_compensation": 300000}, PROFILE, set(), {})
        self.assertGreater(enriched["actual_score"], missing["actual_score"])
        self.assertIn("market compensation meets", enriched["actual_reason"])

    def test_foreign_role_cannot_compete_in_match_ranking(self):
        job = {
            "company": "Foreign Co",
            "title": "Staff Backend Software Engineer",
            "location": "Remote - Ireland",
            "description": "Python Kafka distributed systems microservices generative AI application " * 10,
            "date_posted": "2026-08-25",
            "market_compensation": 500000,
        }
        result = score(job, PROFILE, set(), {})
        self.assertEqual(result["actual_score"], 0)
        self.assertIn("outside the U.S.", result["actual_reason"])

    def test_permanent_resident_is_ineligible_for_citizenship_or_clearance_role(self):
        base = {
            "company": "Defense Co", "title": "Senior Backend Software Engineer", "location": "Austin, TX",
            "description": "Python backend distributed systems platform infrastructure " * 20,
            "date_posted": "2026-08-26", "salary_max": 280000,
        }
        resident_profile = {**PROFILE, "permanent_resident": True, "us_person": True, "us_citizen": False}
        citizen_only = score({**base, "description": base["description"] + " U.S. citizenship is required."}, resident_profile, set(), {})
        clearance = score({**base, "description": base["description"] + " Must obtain a security clearance."}, resident_profile, set(), {})
        us_person = score({**base, "description": base["description"] + " Must be a U.S. person under export-control rules."}, resident_profile, set(), {})
        self.assertEqual(citizen_only["actual_score"], 0)
        self.assertEqual(clearance["actual_score"], 0)
        self.assertGreater(us_person["actual_score"], 0)
        self.assertIn("saved profile is ineligible", citizen_only["actual_reason"])

    def test_incomplete_description_cannot_enter_actual_ranking(self):
        job = {"company": "Incomplete Co", "title": "Staff Backend Software Engineer", "description": "Short public preview", "location": "Austin, TX", "date_posted": "2026-08-25", "salary_max": 320000}
        result = score(job, PROFILE, set(), {})
        self.assertEqual(result["actual_score"], 0)
        self.assertIn("refresh before ranking", result["actual_reason"].lower())

    def test_saved_company_keeps_quality_ranking_despite_protection(self):
        job = {
            "company": "Saved Co",
            "title": "Senior Backend Software Engineer",
            "location": "Boston, MA",
            "description": "Python Kafka distributed systems microservices platform architecture",
            "date_posted": "2026-08-25",
        }
        protected = score(job, PROFILE, {"saved co"}, {})
        unsaved = score(job, PROFILE, set(), {})
        self.assertEqual(protected["burn_cost"], 10)
        self.assertGreaterEqual(protected["practice_score"], unsaved["practice_score"] - 1.0)


class PersistenceTests(unittest.TestCase):
    @staticmethod
    def _research_selected_companies():
        from jobfinder.infrastructure.interview_research import load_interview_research

        research = load_interview_research()
        names = {name for pattern in research["patterns"] for name in pattern.get("companies", [])}
        return sorted(names | {"Cisco", "Visa", "Salesforce", "Postman"})

    def test_closed_saved_posting_stays_saved_but_leaves_active_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            with patch.object(storage, "DB_PATH", temporary_db):
                with storage.db() as conn:
                    row = conn.execute(
                        "SELECT id,title FROM jobs WHERE actual_saved=1 AND location LIKE 'Austin%' LIMIT 1"
                    ).fetchone()
                    self.assertIsNotNone(row)
                    job_id, title = int(row["id"]), str(row["title"])
                    conn.execute("UPDATE jobs SET closed_at=? WHERE id=?", ("2026-09-23T00:00:00Z", job_id))
                all_saved = jobs_view({"saved": "1", "location": "austin", "q": title})
                active_saved = jobs_view({"saved": "1", "location": "austin", "status": "active", "q": title})
                self.assertIn(job_id, {job["id"] for job in all_saved["jobs"]})
                self.assertNotIn(job_id, {job["id"] for job in active_saved["jobs"]})

    def test_active_queue_hides_stale_unsaved_jobs(self):
        from datetime import date, timedelta

        cutoff = date.today() - timedelta(days=30)
        result = jobs_view({"location": "austin", "status": "active"})
        for job in result["jobs"]:
            posted = job.get("date_posted")
            if posted and not job.get("actual_saved") and not job.get("practice_saved"):
                self.assertGreaterEqual(date.fromisoformat(posted[:10]), cutoff)

    def test_active_queue_shows_fresh_selected_real_jobs_but_not_stale_selections(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            with patch.object(storage, "DB_PATH", temporary_db):
                with storage.db() as conn:
                    today = date.today().isoformat()
                    stale = (date.today() - timedelta(days=45)).isoformat()
                    for suffix, posted in (("fresh", today), ("stale", stale)):
                        conn.execute(
                            "INSERT INTO jobs (company,company_key,title,location,url,source,description,date_posted,salary_max,actual_saved,status,discovered_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            ("Queue Test Employer", "queue test employer", "Senior Backend Software Engineer", "Austin, TX",
                             f"https://example.com/queue-test-{suffix}", "employer", "Build distributed backend systems. " * 12,
                             posted, 250000, 1, "PROTECTED", datetime.now(timezone.utc).isoformat()),
                        )
                active = jobs_view({"location": "austin", "status": "active", "q": "Queue Test Employer"})
                urls = {job["url"] for job in active["jobs"]}
                self.assertIn("https://example.com/queue-test-fresh", urls)
                self.assertNotIn("https://example.com/queue-test-stale", urls)

    def test_job_read_model_owns_query_and_company_presentation_signals(self):
        result = jobs_view({"location": "us", "status": "active", "sort": "actual"})
        with storage.db() as conn:
            self.assertEqual(result["corpus_total"], conn.execute("SELECT count(*) FROM jobs").fetchone()[0])
        self.assertEqual(result["corpus_progress"]["job_target"], 3000)
        self.assertEqual(result["corpus_progress"]["austin_proper_company_target"], 300)
        austin_company_count = result["corpus_progress"]["austin_proper_company_count"]
        self.assertGreater(austin_company_count, 0)
        self.assertEqual(
            austin_company_count + result["corpus_progress"]["austin_companies_remaining"],
            result["corpus_progress"]["austin_proper_company_target"],
        )
        self.assertEqual(
            result["corpus_progress"]["direct_source_jobs"] + result["corpus_progress"]["linkedin_jobs"],
            result["corpus_total"],
        )
        self.assertTrue(result["jobs"])
        self.assertTrue(all(job["company_key"] for job in result["jobs"]))
        self.assertTrue(all("austin_presence" in job and "burn_eligible" in job for job in result["jobs"]))

    def test_http_presentation_layer_contains_no_job_sql_or_status_mutation(self):
        source = (Path(__file__).parents[1] / "src/jobfinder/presentation/webapp.py").read_text()
        self.assertNotIn("SELECT * FROM jobs", source)
        self.assertNotIn("UPDATE jobs SET", source)
        self.assertNotIn("jobfinder.infrastructure", source)
        self.assertIn("jobs_view(params)", source)
        self.assertIn("update_job_status", source)

    def test_browser_features_are_split_from_job_table_presentation(self):
        static = Path(__file__).parents[1] / "web/static"
        core = (static / "app.js").read_text()
        resume = (static / "resume.js").read_text()
        practice = (static / "practice.js").read_text()
        todo = (static / "todo.js").read_text()
        self.assertNotIn("function loadResumeAnalysis", core)
        self.assertNotIn("function loadPracticeBuilder", core)
        self.assertNotIn("function loadTodos", core)
        self.assertIn("function loadResumeAnalysis", resume)
        self.assertIn("function loadPracticeBuilder", practice)
        self.assertIn("function loadTodos", todo)
        self.assertNotIn("Editable drill notes", practice)
        self.assertNotIn("practice-drill-editor", practice)

    def test_workflow_rejects_invalid_status_before_mutating_database(self):
        with self.assertRaisesRegex(ValueError, "Invalid status"):
            update_job_status(1, "INTERVIEWING")

    def test_profile_defaults_leave_work_authorization_unspecified(self):
        self.assertEqual(DEFAULT_PROFILE["work_authorization"], "")
        self.assertIsNone(DEFAULT_PROFILE["requires_sponsorship"])
        self.assertIsNone(DEFAULT_PROFILE["permanent_resident"])
        self.assertIsNone(DEFAULT_PROFILE["us_person"])
        self.assertIsNone(DEFAULT_PROFILE["us_citizen"])

    def test_practice_builder_persists_four_tracks_and_each_track_todo(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_path = Path(directory) / "practice_builder.json"
            with patch.object(practice_builder, "PRACTICE_BUILDER_PATH", temporary_path):
                data = practice_builder.load_practice_builder()
                self.assertEqual(tuple(data["tracks"]), practice_builder.TRACK_ORDER)
                self.assertTrue(all(track["todo"]["text"] for track in data["tracks"].values()))
                data["tracks"]["hr"]["items"][0]["answer"] = "A saved answer"
                data["tracks"]["leetcode"]["pattern_progress"] = {
                    "production-coding": {"status": "practicing", "updated_at": "2026-08-26T16:00:00Z"},
                    "invalid-pattern": {"status": "mastered", "updated_at": "ignored"},
                }
                data["tracks"]["leetcode"]["exercise_progress"] = {
                    "prod-transform-records": {"completed": True, "completed_at": "2026-08-26T17:00:00Z"},
                }
                practice_builder.save_practice_builder(data)
                saved = practice_builder.load_practice_builder()
                self.assertEqual(saved["tracks"]["hr"]["items"][0]["answer"], "A saved answer")
                self.assertEqual(saved["tracks"]["leetcode"]["title"], "Coding skill builder")
                self.assertEqual(saved["tracks"]["leetcode"]["pattern_progress"]["production-coding"]["status"], "practicing")
                self.assertNotIn("invalid-pattern", saved["tracks"]["leetcode"]["pattern_progress"])
                self.assertTrue(saved["tracks"]["leetcode"]["exercise_progress"]["prod-transform-records"]["completed"])
                self.assertEqual(saved["tracks"]["leetcode"]["exercise_progress"]["prod-transform-records"]["completed_at"], "2026-08-26T17:00:00Z")

    def test_leetcode_research_is_sourced_and_scoped_to_selected_companies(self):
        with patch("jobfinder.application.interview_prep.selected_company_families", return_value=self._research_selected_companies()):
            research = leetcode_research_view()
        selected = set(research["selected_companies"])
        self.assertGreaterEqual(research["selected_count"], 20)
        self.assertGreaterEqual(research["coverage_count"], 12)
        self.assertGreaterEqual(len(research["patterns"]), 8)
        self.assertEqual(research["patterns"][0]["title"], "Production-style implementation and debugging")
        self.assertTrue(all(set(pattern["companies"]) <= selected for pattern in research["patterns"]))
        source_ids = {source["id"] for source in research["sources"]}
        self.assertTrue(all(source.get("url", "").startswith("https://") for source in research["sources"]))
        self.assertTrue(all(set(pattern["source_ids"]) <= source_ids for pattern in research["patterns"]))
        self.assertTrue(all(len(pattern.get("practice_links", [])) >= 2 for pattern in research["patterns"]))
        self.assertTrue(all(
            link.get("url", "").startswith("https://")
            and link.get("label") and link.get("note") and link.get("platform")
            and link.get("access") in {"Free", "Freemium"}
            and link.get("access_tier") in {"free", "freemium"}
            and link.get("access_detail") and link.get("level") and link.get("time") and link.get("deliverable")
            and link.get("prompt") and link.get("research_fit") and link.get("research_confidence")
            and link.get("target_companies") and link.get("source_ids")
            for pattern in research["patterns"] for link in pattern["practice_links"]
        ))
        self.assertTrue(all(
            set(link["source_ids"]) <= set(pattern["source_ids"])
            and set(link["target_companies"]) <= set(pattern["companies"])
            for pattern in research["patterns"] for link in pattern["practice_links"]
        ))
        practice_links = [link for pattern in research["patterns"] for link in pattern["practice_links"]]
        self.assertEqual(len(practice_links), 18)
        weak_problem_labels = {
            "Build a focused HTTP API client", "Build a focused Redis server", "Print in Order",
            "Fizz Buzz Multithreaded", "Group Anagrams", "Longest Substring Without Repeating Characters",
            "Task Scheduler", "Merge K Sorted Lists", "Word Break", "Design Underground System",
            "Build an application load balancer", "Build an API rate limiter",
        }
        self.assertFalse(weak_problem_labels & {link["label"] for link in practice_links})
        self.assertNotIn("testing-edge-cases", {pattern["id"] for pattern in research["patterns"]})
        self.assertEqual(sum(research["evidence_quality_summary"].values()), len(practice_links))
        self.assertGreaterEqual(research["evidence_quality_summary"]["Single public report"], 1)
        self.assertGreaterEqual(research["evidence_quality_summary"]["Corroborated reports"], 1)
        quality_by_label = {link["label"]: link["evidence_quality"] for link in practice_links}
        self.assertEqual(quality_by_label["Create-loan workflow with hierarchy edge cases"], "Single public report")
        self.assertEqual(quality_by_label["Dependency ordering / Alien Dictionary"], "Corroborated reports")
        generic_endings = ("/catalog", "/tracks/python", "/tag/hash-table/", "/tag/concurrency/")
        self.assertFalse(any(
            link["url"].rstrip("/").endswith(tuple(value.rstrip("/") for value in generic_endings))
            for pattern in research["patterns"] for link in pattern["practice_links"]
        ))
        self.assertFalse(any(
            "codecrafters" in link["url"] or "exercism" in link["url"] or link["access"] != "Free"
            for pattern in research["patterns"] for link in pattern["practice_links"]
        ))
        curriculum = research["curriculum"]
        self.assertEqual([track["id"] for track in curriculum["tracks"]], ["production", "whiteboard", "principles"])
        self.assertEqual([len(track["sections"]) for track in curriculum["tracks"]], [3, 6, 3])
        exercises = [exercise for track in curriculum["tracks"] for section in track["sections"] for exercise in section["exercises"]]
        self.assertEqual(len(exercises), 63)
        whiteboard = next(track for track in curriculum["tracks"] if track["id"] == "whiteboard")
        whiteboard_exercises = [exercise for section in whiteboard["sections"] for exercise in section["exercises"]]
        self.assertEqual(len(whiteboard_exercises), 45)
        self.assertEqual(len({exercise["id"] for exercise in whiteboard_exercises}), 45)
        self.assertTrue(all(exercise["companies"] and exercise["evidence"] for exercise in whiteboard_exercises))
        principles = next(track for track in curriculum["tracks"] if track["id"] == "principles")
        principles_exercises = [exercise for section in principles["sections"] for exercise in section["exercises"]]
        self.assertTrue(all(
            exercise.get("context") and exercise.get("deliverables")
            and exercise.get("hints") and exercise.get("walkthrough")
            and exercise.get("resource_url")
            for exercise in principles_exercises
        ))
        self.assertEqual({exercise["difficulty"] for exercise in exercises}, {"Easy", "Medium", "Hard"})
        self.assertTrue(all(exercise["prompt"] and exercise["checkpoints"] and exercise["done_when"] for exercise in exercises))
        self.assertTrue(all(set(exercise["companies"]) <= selected for exercise in exercises))
        self.assertTrue(all(set(exercise["source_ids"]) <= source_ids for exercise in exercises))
        linked_exercises = [exercise for exercise in exercises if exercise.get("resource_url")]
        self.assertGreaterEqual(len(linked_exercises), 10)
        self.assertTrue(all(
            exercise["resource_url"].startswith("https://")
            and exercise.get("resource_label")
            and exercise.get("resource_access") in {"Free", "Free with account", "Free reference", "LeetCode Premium"}
            for exercise in linked_exercises
        ))

    def test_interview_expectations_are_sourced_and_company_scoped(self):
        with patch("jobfinder.application.interview_prep.selected_company_families", return_value=self._research_selected_companies()):
            expectations = interview_expectations_view()
        selected = set(expectations["selected_companies"])
        self.assertEqual(len(expectations["phases"]), 4)
        self.assertGreaterEqual(len(expectations["rounds"]), 5)
        self.assertEqual(len(expectations["technical_pacing"]), 4)
        self.assertGreaterEqual(len(expectations["recruiter_questions"]), 5)
        self.assertEqual(sum(item["percent"] for item in expectations["practice_allocation"]["coding_split"]), 100)
        self.assertEqual(sum(item["percent"] for item in expectations["practice_allocation"]["weekly_split"]), 100)
        self.assertEqual(len(expectations["practice_sessions"]), 4)
        self.assertEqual(len(expectations["weekly_plan"]), 7)
        self.assertGreaterEqual(len(expectations["readiness_gates"]), 5)
        self.assertTrue(all(set(item["companies"]) <= selected for item in expectations["rounds"]))
        self.assertTrue(all(source["url"].startswith("https://") for source in expectations["sources"]))
        formats = expectations["company_formats"]
        self.assertEqual({item["company"] for item in formats}, selected)
        self.assertEqual(sum(expectations["company_format_summary"].values()), len(selected))
        self.assertTrue(all(item["dsa"] + item["practical"] == 100 for item in formats))
        self.assertTrue(all(item["format"] in {
            "Mixed", "Practical-leaning", "DSA-leaning", "Confirm with recruiter"
        } for item in formats))
        format_by_company = {item["company"]: item["format"] for item in formats}
        self.assertEqual(format_by_company["Amazon / AWS"], "Mixed")
        self.assertEqual(format_by_company["Microsoft"], "Mixed")
        self.assertTrue(all(
            item["algorithm_signals"] and item["practical_signals"]
            for item in formats if item["format"] == "Mixed"
        ))

    def test_spacex_redmond_roles_inherit_company_level_austin_presence(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            with patch.object(storage, "DB_PATH", temporary_db):
                with storage.db() as conn:
                    for location, suffix in (("Austin, TX", "austin"), ("Redmond, WA", "redmond")):
                        conn.execute(
                            "INSERT INTO jobs (company,company_key,title,location,url,description,discovered_at) VALUES (?,?,?,?,?,?,?)",
                            ("SpaceX", "spacex", "Senior Software Engineer", location,
                             f"https://example.com/spacex-{suffix}", "Backend platform software engineering.",
                             datetime.now(timezone.utc).isoformat()),
                        )
                signals = company_market_signals()
                self.assertGreaterEqual(signals["spacex"]["austin_jobs"], 1)
                with storage.db() as conn:
                    redmond = conn.execute(
                        "SELECT count(*) FROM jobs WHERE company_key='spacex' AND location LIKE 'Redmond,%'"
                    ).fetchone()[0]
                self.assertEqual(redmond, 1)

    def test_every_selected_role_has_visible_compensation(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT company,title,location,salary_max,market_compensation,
                          market_compensation_source,market_compensation_url
                   FROM jobs WHERE actual_saved=1"""
            ).fetchall()
        missing = [row for row in rows if not (row["salary_max"] or row["market_compensation"])]
        self.assertEqual(missing, [])
        for row in rows:
            if row["salary_max"] is None:
                self.assertTrue(row["market_compensation_source"])
                self.assertTrue(row["market_compensation_url"] or "target-floor" in row["market_compensation_source"])

    def test_official_ats_refreshes_matching_linkedin_row_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company":"Promotion Test Co", "title":"Staff Backend Engineer", "location":"Austin, TX",
                    "description":"Python distributed systems platform " * 20, "date_posted":"2026-08-20",
                    "easy_apply":0, "work_arrangement":"onsite/hybrid", "salary_text":"", "salary_min":None,
                    "salary_max":None, "salary_type":"unknown",
                }
                first_id, created = storage.upsert_raw_job(base | {"url":"https://linkedin.com/jobs/view/1", "source":"linkedin"})
                refreshed_id, refreshed_created = storage.upsert_raw_job(base | {"url":"https://jobs.lever.co/promotion/1", "source":"lever", "date_posted":"2026-08-26", "location":"Hybrid"})
                self.assertTrue(created)
                self.assertFalse(refreshed_created)
                self.assertEqual(first_id, refreshed_id)
                with storage.db() as conn:
                    row = conn.execute("SELECT count(*),url,source,date_posted,location FROM jobs WHERE company='Promotion Test Co'").fetchone()
                self.assertEqual((row[0], row[1], row[2], row[3], row[4]), (1, "https://jobs.lever.co/promotion/1", "lever", "2026-08-26", "Austin, TX"))
            finally:
                storage.DB_PATH = old_db

    def test_live_official_refresh_reopens_confirmed_closed_posting(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            with patch.object(storage, "DB_PATH", temporary_db):
                item = {
                    "company": "Reopen Test Co", "title": "Senior Backend Engineer",
                    "location": "Austin, TX", "url": "https://jobs.lever.co/reopen-test/123",
                    "source": "lever", "description": "Python distributed systems platform " * 20,
                    "date_posted": date.today().isoformat(), "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid", "salary_text": "",
                    "salary_min": None, "salary_max": None, "salary_type": "unknown",
                }
                job_id, created = storage.upsert_raw_job(item)
                self.assertTrue(created)
                with storage.db() as conn:
                    conn.execute("UPDATE jobs SET closed_at=? WHERE id=?", ("2026-09-23T00:00:00Z", job_id))
                refreshed_id, refreshed_created = storage.upsert_raw_job(item)
                self.assertEqual(refreshed_id, job_id)
                self.assertFalse(refreshed_created)
                with storage.db() as conn:
                    self.assertIsNone(conn.execute("SELECT closed_at FROM jobs WHERE id=?", (job_id,)).fetchone()[0])

    def test_keyed_official_requisition_promotes_saved_austin_linkedin_row(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Canonical Promotion Test Co", "title": "Senior Platform Engineer",
                    "location": "Austin, TX", "description": "Build cloud platform software and backend APIs. " * 15,
                    "date_posted": "2026-09-15", "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid", "salary_text": "", "salary_min": None,
                    "salary_max": None, "salary_type": "unknown",
                }
                old_id, _ = storage.upsert_raw_job(base | {
                    "url": "https://linkedin.com/jobs/view/canonical-promotion", "source": "linkedin",
                })
                with storage.db() as conn:
                    conn.execute("UPDATE jobs SET actual_saved=1 WHERE id=?", (old_id,))
                new_url = "https://careers.oracle.com/en/sites/jobsearch/job/999990"
                new_id, created = storage.upsert_raw_job(base | {
                    "url": new_url, "source": "oracle", "date_posted": "2026-09-22",
                })
                self.assertFalse(created)
                self.assertEqual(new_id, old_id)
                with storage.db() as conn:
                    row = conn.execute("SELECT url,source,actual_saved FROM jobs WHERE id=?", (old_id,)).fetchone()
                    self.assertEqual(tuple(row), (new_url, "oracle", 1))
            finally:
                storage.DB_PATH = old_db

    def test_official_refresh_collapses_near_identical_aggregator_mirror(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                description = "Build Python distributed systems, APIs, Kafka, Postgres, and cloud services. " * 20
                base = {
                    "company": "Mirror Test Co", "title": "Staff Platform Engineer", "location": "Austin, TX",
                    "description": description, "date_posted": "2026-08-20", "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid", "salary_text": "", "salary_min": None,
                    "salary_max": None, "salary_type": "unknown",
                }
                storage.upsert_raw_job(base | {"url": "https://linkedin.com/jobs/view/austin-copy", "source": "linkedin"})
                storage.upsert_raw_job(base | {"url": "https://linkedin.com/jobs/view/denver-copy", "source": "linkedin", "location": "Denver, CO"})
                official_id, created = storage.upsert_raw_job(base | {"url": "https://careers.example.com/jobs/123", "source": "resideo", "description": "Job description " + description})
                self.assertFalse(created)
                with storage.db() as conn:
                    rows = conn.execute("SELECT id,url,source FROM jobs WHERE company_key=?", (storage.company_key("Mirror Test Co"),)).fetchall()
                self.assertEqual([(row["id"], row["url"], row["source"]) for row in rows], [(official_id, "https://careers.example.com/jobs/123", "resideo")])
            finally:
                storage.DB_PATH = old_db

    def test_late_aggregator_mirror_keeps_existing_official_record(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                description = "Build Python distributed systems, APIs, Kafka, Postgres, and cloud services. " * 20
                base = {
                    "company": "Late Mirror Test Co", "title": "Staff Platform Engineer", "location": "Austin, TX",
                    "description": description, "date_posted": "2026-08-20", "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid", "salary_text": "$180,000 - $240,000",
                    "salary_min": 180000, "salary_max": 240000, "salary_type": "base",
                }
                official_id, created = storage.upsert_raw_job(
                    base | {"url": "https://careers.example.com/jobs/late-123", "source": "procore"}
                )
                self.assertTrue(created)
                with storage.db() as conn:
                    conn.execute("UPDATE jobs SET notes='keep official' WHERE id=?", (official_id,))
                mirror_id, mirror_created = storage.upsert_raw_job(
                    base | {"url": "https://linkedin.com/jobs/view/late-123", "source": "linkedin"}
                )
                self.assertFalse(mirror_created)
                self.assertEqual(mirror_id, official_id)
                with storage.db() as conn:
                    rows = conn.execute(
                        "SELECT id,url,source,notes FROM jobs WHERE company_key=?",
                        (storage.company_key("Late Mirror Test Co"),),
                    ).fetchall()
                self.assertEqual(
                    [(row["id"], row["url"], row["source"], row["notes"]) for row in rows],
                    [(official_id, "https://careers.example.com/jobs/late-123", "procore", "keep official")],
                )
            finally:
                storage.DB_PATH = old_db

    def test_late_aggregator_title_match_keeps_official_record_despite_rewritten_description(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Canonical Title Test Co",
                    "title": "Senior Backend Engineer",
                    "location": "Austin, TX",
                    "date_posted": "2026-09-03",
                    "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid",
                    "salary_text": "",
                    "salary_min": None,
                    "salary_max": None,
                    "salary_type": "unknown",
                }
                official_id, _ = storage.upsert_raw_job(base | {
                    "url": "https://jobs.example.com/canonical-123",
                    "source": "procore",
                    "description": "Build Python APIs and distributed backend services. " * 20,
                })
                mirror_id, created = storage.upsert_raw_job(base | {
                    "url": "https://linkedin.com/jobs/view/canonical-123",
                    "source": "linkedin",
                    "description": "A heavily rewritten syndicated summary with Java, Kafka, and cloud platform ownership. " * 8,
                })
                self.assertFalse(created)
                self.assertEqual(mirror_id, official_id)
                with storage.db() as conn:
                    rows = conn.execute(
                        "SELECT url,source FROM jobs WHERE company_key=?",
                        (storage.company_key(base["company"]),),
                    ).fetchall()
                self.assertEqual([(row["url"], row["source"]) for row in rows], [("https://jobs.example.com/canonical-123", "procore")])
            finally:
                storage.DB_PATH = old_db

    def test_official_refresh_collapses_same_requisition_url_after_title_change(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                old_url = "https://careers.realtor.com/job/123/senior-cloud-platform-engineer-austin-tx/"
                new_url = "https://careers.realtor.com/job/123/sr-site-reliability-engineer-austin-tx/"
                base = {
                    "company": "Requisition Rename Co", "location": "Austin, TX",
                    "description": "Build Python distributed systems platform services. " * 12,
                    "date_posted": "2026-08-20", "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid", "salary_text": "", "salary_min": None,
                    "salary_max": None, "salary_type": "unknown", "source": "realtor",
                }
                old_id, _ = storage.upsert_raw_job(base | {"title": "Senior Cloud Platform Engineer", "url": old_url})
                with storage.db() as conn:
                    conn.execute("UPDATE jobs SET actual_saved=1,status='PROTECTED',notes='keep me' WHERE id=?", (old_id,))
                    conn.execute(
                        "INSERT INTO jobs (company,company_key,title,location,url,source,description,date_posted,easy_apply,work_arrangement,salary_text,salary_type,status,discovered_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("Requisition Rename Co", storage.company_key("Requisition Rename Co"), "Sr. Site Reliability Engineer", "Austin, TX", new_url,
                         "realtor", base["description"], "2026-08-27", 0, "onsite/hybrid", "", "unknown", "NEW", storage.now()),
                    )
                    new_id = int(conn.execute("SELECT max(id) FROM jobs").fetchone()[0])
                    removed = storage._collapse_official_mirror_duplicates(conn, new_id)
                self.assertEqual(removed, 1)
                with storage.db() as conn:
                    rows = conn.execute("SELECT id,title,actual_saved,status,notes FROM jobs WHERE company_key=?", (storage.company_key("Requisition Rename Co"),)).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["id"], rows[0]["title"], rows[0]["actual_saved"], rows[0]["status"], rows[0]["notes"]),
                                 (new_id, "Sr. Site Reliability Engineer", 1, "PROTECTED", "keep me"))
            finally:
                storage.DB_PATH = old_db

    def test_western_union_refresh_reuses_requisition_when_title_slug_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Western Union", "title": "Staff Software Engineer - Digital Platform",
                    "location": "Austin, TX, US", "source": "westernunion",
                    "description": "Build Python distributed systems platform services. " * 12,
                    "date_posted": "2026-08-25", "easy_apply": 0, "work_arrangement": "onsite/hybrid",
                    "salary_text": "", "salary_min": None, "salary_max": None, "salary_type": "unknown",
                }
                old_id, _ = storage.upsert_raw_job(base | {
                    "url": "https://careers.westernunion.com/job-details/23367620/staff-software-engineer-austin-tx/",
                })
                refreshed_id, created = storage.upsert_raw_job(base | {
                    "url": "https://careers.westernunion.com/job-details/23367620/staff-software-engineer-digital-platform-austin-tx/",
                })
                self.assertFalse(created)
                self.assertEqual(refreshed_id, old_id)
                with storage.db() as conn:
                    row = conn.execute("SELECT url FROM jobs WHERE id=?", (old_id,)).fetchone()
                self.assertEqual(row["url"], "https://careers.westernunion.com/job-details/23367620/staff-software-engineer-digital-platform-austin-tx/")
            finally:
                storage.DB_PATH = old_db

    def test_gm_refresh_reuses_requisition_when_title_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "General Motors", "location": "Austin, Texas", "source": "gm",
                    "description": "Build Python distributed systems and cloud platform services. " * 12,
                    "date_posted": "2026-08-20", "easy_apply": 0, "work_arrangement": "onsite/hybrid",
                    "salary_text": "", "salary_min": None, "salary_max": None, "salary_type": "unknown",
                }
                old_id, _ = storage.upsert_raw_job(base | {
                    "title": "Senior Full Stack Software Engineer",
                    "url": "https://search-careers.gm.com/en/jobs/jr-202616138/senior-full-stack-software-engineer/",
                })
                refreshed_id, created = storage.upsert_raw_job(base | {
                    "title": "Enterprise AI Platform Manager",
                    "url": "https://search-careers.gm.com/en/jobs/jr-202616138/enterprise-ai-platform-manager/",
                })
                self.assertFalse(created)
                self.assertEqual(refreshed_id, old_id)
                with storage.db() as conn:
                    row = conn.execute("SELECT title,url FROM jobs WHERE id=?", (old_id,)).fetchone()
                self.assertEqual(
                    (row["title"], row["url"]),
                    ("Enterprise AI Platform Manager", "https://search-careers.gm.com/en/jobs/jr-202616138/enterprise-ai-platform-manager/"),
                )
            finally:
                storage.DB_PATH = old_db

    def test_gm_distinct_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "General Motors", "title": "Senior Software Engineer",
                    "location": "Austin, Texas", "source": "gm",
                    "description": "Build Python distributed systems and cloud platform services. " * 12,
                    "date_posted": "2026-09-01", "easy_apply": 0, "work_arrangement": "onsite/hybrid",
                    "salary_text": "", "salary_min": None, "salary_max": None, "salary_type": "unknown",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://search-careers.gm.com/en/jobs/jr-100/senior-software-engineer/",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://search-careers.gm.com/en/jobs/jr-200/senior-software-engineer/",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_oracle_distinct_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Oracle", "title": "Senior Software Engineer, Core Infrastructure",
                    "location": "Austin, TX", "source": "oracle",
                    "description": "Build Java distributed systems and cloud platform services. " * 12,
                    "date_posted": "2026-09-01", "easy_apply": 0, "work_arrangement": "onsite/hybrid",
                    "salary_text": "$79,200 to $209,500", "salary_min": 79200,
                    "salary_max": 209500, "salary_type": "unknown",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://careers.oracle.com/en/sites/jobsearch/job/999991",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://careers.oracle.com/en/sites/jobsearch/job/999992",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_workday_distinct_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "NVIDIA", "title": "Senior Software Engineer, Cloud Platform",
                    "location": "Austin, TX", "source": "workday",
                    "description": "Build Python distributed systems and cloud platform services. " * 12,
                    "date_posted": "2026-09-01", "easy_apply": 0, "work_arrangement": "onsite/hybrid",
                    "salary_text": "$184,000 - $356,500", "salary_min": 184000,
                    "salary_max": 356500, "salary_type": "year",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-TX-Austin/Cloud-Platform_JR999991",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-TX-Austin/Cloud-Platform_JR999992",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_workday_ref_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Visa", "title": "Senior Software Engineer",
                    "location": "Austin, TX", "source": "workday",
                    "description": "Build Java distributed systems and cloud platform services. " * 12,
                    "date_posted": "2026-09-01", "easy_apply": 0, "work_arrangement": "onsite/hybrid",
                    "salary_text": "", "salary_min": None, "salary_max": None, "salary_type": "unknown",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://visa.wd5.myworkdayjobs.com/Visa/job/US---Austin-TX/Senior-Software-Engineer_REF099991W",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://visa.wd5.myworkdayjobs.com/Visa/job/US---Austin-TX/Senior-Software-Engineer_REF099992W",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_amazon_distinct_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Amazon Web Services (AWS)",
                    "title": "Senior Software Development Engineer, Cloud Platform",
                    "location": "Austin, TX",
                    "source": "amazon",
                    "description": "Build backend distributed cloud systems with Java and AWS. " * 20,
                    "date_posted": "2026-09-03",
                    "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid",
                    "salary_text": "",
                    "salary_min": None,
                    "salary_max": None,
                    "salary_type": "unknown",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://www.amazon.jobs/en/jobs/999991/senior-software-development-engineer-cloud-platform",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://www.amazon.jobs/en/jobs/999992/senior-software-development-engineer-cloud-platform",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_greenhouse_distinct_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Cloudflare",
                    "title": "Senior Software Engineer, Distributed Platform",
                    "location": "Austin, TX",
                    "source": "greenhouse",
                    "description": "Build backend distributed cloud systems with Go and Kubernetes. " * 20,
                    "date_posted": "2026-09-03",
                    "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid",
                    "salary_text": "",
                    "salary_min": None,
                    "salary_max": None,
                    "salary_type": "unknown",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://boards.greenhouse.io/cloudflare/jobs/999991?gh_jid=999991",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://boards.greenhouse.io/cloudflare/jobs/999992?gh_jid=999992",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_jibe_distinct_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "AMD",
                    "title": "Senior Platform Software Engineer",
                    "location": "Austin, TX",
                    "source": "jibe",
                    "description": "Build backend distributed cloud systems with Python and Kubernetes. " * 20,
                    "date_posted": "2026-09-03",
                    "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid",
                    "salary_text": "",
                    "salary_min": None,
                    "salary_max": None,
                    "salary_type": "unknown",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://careers.amd.com/careers-home/jobs/999991?lang=en-us",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://careers.amd.com/careers-home/jobs/999992?lang=en-us",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_teamtailor_distinct_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "TeamViewer",
                    "title": "Senior AI Platform Engineer",
                    "location": "Austin, TX",
                    "source": "teamtailor",
                    "description": "Build backend distributed AI platforms with Python and Kubernetes. " * 20,
                    "date_posted": "2026-09-03",
                    "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid",
                    "salary_text": "",
                    "salary_min": None,
                    "salary_max": None,
                    "salary_type": "unknown",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://careers.teamviewer.com/jobs/999991-senior-ai-platform-engineer",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://careers.teamviewer.com/jobs/999992-senior-ai-platform-engineer",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_schwab_distinct_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Charles Schwab",
                    "title": "Senior Software Developer",
                    "location": "Austin, Texas, United States",
                    "source": "schwab",
                    "description": "Build backend distributed cloud services with Python and Kafka. " * 20,
                    "date_posted": "2026-09-01",
                    "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid",
                    "salary_text": "",
                    "salary_min": None,
                    "salary_max": None,
                    "salary_type": "unknown",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://www.schwabjobs.com/job/austin/senior-software-developer/33727/999991",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://www.schwabjobs.com/job/austin/senior-software-developer/33727/999992",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_deloitte_distinct_requisitions_with_same_title_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "company": "Deloitte Requisition Regression",
                    "title": "Cyber Forward Deployed Engineer - Manager",
                    "location": "Austin, TX",
                    "source": "deloitte",
                    "description": "Lead secure cloud software platforms and distributed API services. " * 20,
                    "date_posted": "2026-09-01",
                    "easy_apply": 0,
                    "work_arrangement": "onsite/hybrid",
                    "salary_text": "",
                    "salary_min": None,
                    "salary_max": None,
                    "salary_type": "unknown",
                }
                first_id, first_created = storage.upsert_raw_job(base | {
                    "url": "https://apply.deloitte.com/en_US/careers/JobDetail/First-Slug/362386",
                })
                second_id, second_created = storage.upsert_raw_job(base | {
                    "url": "https://apply.deloitte.com/en_US/careers/JobDetail/Renamed-Slug/362390",
                })
                self.assertTrue(first_created)
                self.assertTrue(second_created)
                self.assertNotEqual(first_id, second_id)
            finally:
                storage.DB_PATH = old_db

    def test_company_and_title_variants_dedupe_to_one_official_record(self):
        self.assertEqual(storage.company_key("Procore"), storage.company_key("Procore Technologies"))
        self.assertEqual(storage.company_key("Amazon"), storage.company_key("Amazon Web Services (AWS)"))
        self.assertEqual(storage.company_key("Electronic Arts"), storage.company_key("Electronic Arts (EA)"))
        self.assertEqual(storage.company_key("Acrisure"), storage.company_key("Acrisure Innovation"))
        self.assertEqual(storage.company_key("ASSA ABLOY"), storage.company_key("ASSA ABLOY Group"))
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            old_db = storage.DB_PATH
            try:
                storage.DB_PATH = temporary_db
                base = {
                    "title":"Sr. Backend Engineer", "location":"Austin, TX",
                    "description":"Python distributed systems platform " * 20, "date_posted":"2026-08-20",
                    "easy_apply":0, "work_arrangement":"onsite/hybrid", "salary_text":"", "salary_min":None,
                    "salary_max":None, "salary_type":"unknown",
                }
                first_id, _ = storage.upsert_raw_job(base | {"company":"Procore Technologies", "url":"https://linkedin.com/jobs/view/2", "source":"linkedin"})
                with storage.db() as conn:
                    conn.execute("UPDATE jobs SET company_key=? WHERE id=?", (storage.company_key("Procore Technologies"), first_id))
                refreshed_id, created = storage.upsert_raw_job(base | {"company":"Procore", "title":"Senior Backend Engineer", "url":"https://careers.procore.com/jobs/2", "source":"procore"})
                self.assertFalse(created)
                self.assertEqual(first_id, refreshed_id)
            finally:
                storage.DB_PATH = old_db

    def test_resume_builder_normalizes_editable_sections(self):
        result = normalize_resume_builder({
            "contact": {"name": " Eli Test ", "headline": "Staff Backend Engineer"},
            "summary": " Impact-focused summary ",
            "skills": {"Languages": "Python, TypeScript"},
            "experience": [{"company": "Example", "role": "Senior Engineer", "location": "Austin, TX", "dates": "2024 - Present", "bullets": [" Built a platform ", ""]}],
            "education": [],
        })
        self.assertEqual(result["contact"]["name"], "Eli Test")
        self.assertEqual(result["skills"], {"Languages": "Python, TypeScript"})
        self.assertEqual(result["experience"][0]["bullets"], ["Built a platform"])
        self.assertEqual(result["education"], [])

    def test_resume_analysis_targets_relevant_roles_at_selected_companies(self):
        result = resume_analysis_view()
        self.assertEqual(result["selected_version"], "current")
        self.assertEqual(result["target_scope"], "selected_companies")
        self.assertGreater(result["stats"]["selected_roles"], 0)
        self.assertLessEqual(result["stats"]["selected_roles"], 36)
        self.assertGreater(result["stats"]["selected_companies"], 0)
        self.assertEqual(result["stats"]["selected_roles"], result["target_context"]["role_count"])
        self.assertTrue(result["target_context"]["top_skills"])
        self.assertNotIn("Machine Learning Engineer", " ".join(item["title"] for item in result["target_context"]["role_examples"]))
        self.assertIn("target_skill_coverage", result["review"])

    def test_todo_list_persists_in_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            old_path = todos.TODO_PATH
            try:
                todos.TODO_PATH = Path(directory) / "todos.jsonl"
                todos.save_todos([{"id": "email", "order": 1, "status": "todo"}])
                completed = todos.toggle_todo("email")
                self.assertEqual(completed["status"], "done")
                self.assertIn("T", completed["completed_at"])
                self.assertEqual(todos.list_todos()[0]["status"], "done")
                reopened = todos.toggle_todo("email")
                self.assertEqual(reopened["status"], "todo")
                self.assertNotIn("completed_at", reopened)
                self.assertEqual(todos.toggle_todo_blocker("email")["status"], "blocked")
                self.assertEqual(todos.toggle_todo_blocker("email")["status"], "todo")
            finally:
                todos.TODO_PATH = old_path

    def test_top_cache_has_40_unique_companies_links_and_skills(self):
        rows = [json.loads(line) for line in TOP_CACHE_PATH.read_text().splitlines()]
        self.assertGreater(len(rows), 0)
        self.assertLessEqual(len(rows), 40)
        self.assertEqual(len({row["company_key"] for row in rows}), len(rows))
        self.assertTrue(all(row.get("url", "").startswith("http") for row in rows))
        self.assertTrue(all(isinstance(row.get("skills"), list) for row in rows))
        self.assertTrue(all((row.get("salary_max") or row.get("suggested_salary") or 0) >= 200000 for row in rows))

    def test_levels_bank_is_attributed_and_has_compensation(self):
        rows = [json.loads(line) for line in LEVELS_BANK_PATH.read_text().splitlines()]
        self.assertGreaterEqual(len(rows), 10)
        self.assertTrue(all(row.get("source") == "Levels.fyi" and row.get("source_url", "").startswith("https://www.levels.fyi/") for row in rows))
        self.assertTrue(all(row.get("median_total_comp") or row.get("senior_total_comp") for row in rows))

    def test_stronger_job_enters_cache_and_evicts_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_db = Path(directory) / "jobs.db"
            temporary_cache = Path(directory) / "top_jobs.jsonl"
            shutil.copy2(DB_PATH, temporary_db)
            old_db, old_cache = storage.DB_PATH, storage.TOP_CACHE_PATH
            try:
                storage.DB_PATH, storage.TOP_CACHE_PATH = temporary_db, temporary_cache
                with storage.db() as conn:
                    conn.execute("""INSERT INTO jobs
                        (company,company_key,title,location,url,description,work_arrangement,
                         salary_max,fit_score,practice_value,burn_cost,recency_score,practice_score,
                         reason,matches,concerns,detected_skills,status,discovered_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        ("Cache Challenger", "cachechallenger", "Staff Backend Engineer", "Boston, MA",
                         "https://example.com/cache-challenger", "Python distributed systems", "onsite",
                         300000, 10, 10, 1, 10, 99, "Test cache challenger", "[]", "[]", '["Python"]', "NEW", "2026-08-25T00:00:00+00:00"))
                cache_count = storage.refresh_top_job_cache()
                self.assertGreater(cache_count, 0)
                self.assertLessEqual(cache_count, 40)
                rows = [json.loads(line) for line in temporary_cache.read_text().splitlines()]
                self.assertEqual(rows[0]["company"], "Cache Challenger")
                self.assertEqual(len(rows), cache_count)
            finally:
                storage.DB_PATH, storage.TOP_CACHE_PATH = old_db, old_cache

    def test_resume_property_matches_private_path(self):
        profile = json.loads(PROFILE_PATH.read_text())
        self.assertEqual(profile["resume_file"], "data/private/resume.pdf")

    def test_saved_actual_companies_are_protected(self):
        companies = [json.loads(line)["company_name"] for line in ACTUAL_LIST_PATH.read_text().splitlines()]
        with sqlite3.connect(DB_PATH) as conn:
            for company in companies:
                statuses = {row[0] for row in conn.execute("SELECT status FROM jobs WHERE lower(company)=lower(?)", (company,))}
                self.assertEqual(statuses, {"PROTECTED"})

    def test_practice_save_is_company_level_and_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            temporary_db = root / "jobs.db"
            shutil.copy2(DB_PATH, temporary_db)
            names = ("DB_PATH", "TOP_CACHE_PATH", "ACTUAL_LIST_PATH", "PRACTICE_LIST_PATH", "TEXT_DB_PATH")
            old = {name: getattr(storage, name) for name in names}
            try:
                storage.DB_PATH = temporary_db
                storage.TOP_CACHE_PATH = root / "top.jsonl"
                storage.ACTUAL_LIST_PATH = root / "actual.jsonl"
                storage.PRACTICE_LIST_PATH = root / "practice.jsonl"
                storage.TEXT_DB_PATH = root / "jobs.jsonl"
                with storage.db() as conn:
                    candidates = [row[0] for row in conn.execute("SELECT DISTINCT company FROM jobs WHERE actual_saved=0 AND company!='' LIMIT 50")]
                company = next(name for name in candidates if not storage.is_strategic_company(str(name)))
                self.assertTrue(storage.toggle_practice_company(str(company)))
                with storage.db() as conn:
                    self.assertEqual({row[0] for row in conn.execute("SELECT practice_saved FROM jobs WHERE company_key=?", (storage.company_key(str(company)),))}, {1})
                self.assertFalse(storage.toggle_practice_company(str(company)))
            finally:
                for name, value in old.items(): setattr(storage, name, value)

    def test_obsolete_decision_column_is_removed(self):
        with sqlite3.connect(DB_PATH) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        self.assertTrue({"decision", "score_fingerprint"}.isdisjoint(columns))

    def test_sqlite_uses_one_denormalized_table(self):
        with sqlite3.connect(DB_PATH) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        self.assertEqual(tables, {"jobs"})
        self.assertTrue({"company_key", "detected_skills", "actual_saved", "practice_saved", "top_rank"}.issubset(columns))
        with sqlite3.connect(DB_PATH) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs WHERE actual_saved=1 AND practice_saved=1").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
