"""Permitted public job-board providers independent of profile scoring."""
from __future__ import annotations

import html
import json
import http.client
import http.cookiejar
import re
import socket
import subprocess
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from typing import Any
import xml.etree.ElementTree as ET

from jobfinder.domain.locations import is_explicitly_non_us_location
from jobfinder.domain.relevance import title_is_candidate
from jobfinder.infrastructure.aggregator import clean_text, extract_salary, format_salary_range


def _response_body(response: Any, max_bytes: int) -> bytes:
    """Return a response body, retaining useful partial HTML after a dropped chunk."""
    try:
        return response.read(max_bytes)
    except http.client.IncompleteRead as exc:
        return exc.partial


GREENHOUSE_BOARDS = {
    "2K": "2k",
    # Sagent's employer careers page renders this public Greenhouse inventory.
    # Its broad US board requires the displayed posting label itself to name
    # Austin, Texas before a role can enter the Austin queue.
    "Sagent": "sagent",
    # Juul's employer careers page embeds this public board. Its inventory is
    # broad, so the public posting label must name Austin, Texas exactly.
    "Juul Labs": "juullabs",
    "Avride": "avride",
    "Optiver": "optiverus",
    "Zynga": "zyngacareers",
    "CharterUP": "charterup",
    # Strategic AI companies
    "Anthropic": "anthropic",
    "Databricks": "databricks",
    "Scale AI": "scaleai",
    "Seekr": "seekr",
    "CoreWeave": "coreweave",
    "Waymo": "waymo",
    "xAI": "xai",
    # Diverse infrastructure, fintech, SaaS, security, and consumer companies
    "Stripe": "stripe",
    "Affirm": "affirm",
    "Reddit": "reddit",
    "Figma": "figma",
    "Discord": "discord",
    "Coinbase": "coinbase",
    # Setpoint's employer careers page links to this public Greenhouse board.
    # Its inventory spans three offices, so only postings whose public label
    # explicitly names Austin, Texas may enter the local queue.
    "Setpoint": "setpoint",
    # Monks' Austin, Texas employer-office page renders openings from this
    # public board. Greenhouse shortens that office label to "Austin", so the
    # collector below accepts that city label only for this verified tenant.
    "Monks": "monks",
    # Robots & Pencils' employer careers page fetches this public board
    # directly; its postings expose Austin, TX in the displayed location.
    "Robots & Pencils": "robotsandpencils",
    # ZoomInfo's employer careers inventory is backed by this public board.
    # Its branded detail may challenge interactive browsers, while the public
    # feed supplies complete content and authoritative first-published dates.
    "ZoomInfo": "zoominfo",
    # DoorDash's branded careers search links to this public board. The board
    # contains broad multi-city hiring, so consumers must still require the
    # public posting location itself to name Austin, Texas.
    "DoorDash": "doordashusa",
    "Robinhood": "robinhood",
    "Samsara": "samsara",
    "MongoDB": "mongodb",
    "Twilio": "twilio",
    "Datadog": "datadog",
    "DISCO": "disco",
    "Dropbox": "dropbox",
    "Cloudbeds": "cloudbeds",
    "Lyft": "lyft",
    "Airbnb": "airbnb",
    "Pinterest": "pinterest",
    "CLEAR": "clear",
    "Qualia": "qualia",
    "WeInfuse": "wimanagementllc",
    "Instacart": "instacart",
    "Brex": "brex",
    "Okta": "okta",
    "Asana": "asana",
    "Roblox": "roblox",
    "Elastic": "elastic",
    "Grafana Labs": "grafanalabs",
    "Cockroach Labs": "cockroachlabs",
    "Vercel": "vercel",
    "Cloudflare": "cloudflare",
    # Code and Theory's branded careers pages and application iframe are
    # backed by this public Greenhouse board. Exact Austin metadata is required
    # below because the board also publishes US-remote and New York roles.
    "Code and Theory": "codeandtheory",
    "SolarWinds": "solarwinds",
    "SpaceX": "spacex",
    "Vectra AI": "vectranetworks",
    "Speechify": "speechify",
    "Take-Two Interactive": "taketwo",
    "Vestwell": "vestwell",
    # These employer careers pages embed the corresponding public Greenhouse
    # boards. Their office associations are broader than the displayed job
    # location, so collection below requires the public-facing Austin, Texas
    # label before a posting can enter the Austin queue.
    "Scorability": "scorability",
    "inKind": "inkind",
    # Both companies expose large public boards with broad US/remote hiring.
    # Only the employer's displayed Austin, Texas location is eligible below.
    "Auctane": "auctane",
    # Austin-headquartered or Austin-hub employers
    "AlertMedia": "alertmedia",
    "Axonius": "axonius",
    "Liftoff": "liftoff",
    "SpyCloud": "spycloud",
    "Self Financial": "selffinancial",
    "Apptronik": "apptronik",
    "Braze": "braze",
    "Ping Identity": "pingidentity",
    "Pantheon": "pantheon",
    "Panic Button": "panicbutton",
    "Storable": "storable",
    "VulnCheck": "vulncheck",
    # Grocery TV's employer careers page is this public Greenhouse board.
    # The inventory also contains regional field roles, so only postings whose
    # displayed work-location names Austin, Texas may enter the Austin queue.
    "Grocery TV": "gtv",
    "Qualia": "qualia",
    # Both employer sites embed these public boards. Atoms publishes a large
    # global inventory and Two Chairs publishes broad US-remote roles, so the
    # collector below requires the displayed location itself to name Austin,
    # Texas rather than inferring eligibility from an office or remote label.
    "Atoms": "atoms",
    "Two Chairs": "twochairs",
    # Telnyx's careers page embeds this public board. Its inventory is global,
    # so only the displayed posting location may establish Austin eligibility.
    "Telnyx": "telnyx54",
    # Natera's branded careers site and Duetto's embedded openings both use
    # these public boards. Their inventories are broad, so the public-facing
    # posting label must independently name Austin, Texas below.
    "Natera": "natera",
    "Duetto": "duettoresearch",
    # Navan's branded openings page publishes stable Greenhouse requisition
    # identities through the legacy TripActions tenant. Upshop's employer
    # careers page likewise uses a public Greenhouse feed. Both inventories
    # span many cities, so the displayed posting location must name Austin.
    "Navan": "tripactions",
    "Upshop": "upshop",
    # Osano's board is fully remote and occasionally mentions Austin in
    # interview logistics. Only a displayed Austin, Texas work location may
    # qualify a role for this queue.
    "Osano": "osano",
    # These employer careers pages expose the corresponding public Greenhouse
    # boards. Each inventory spans multiple cities (and, for Iterable, broad
    # U.S.-remote hiring), so only the displayed work-location field may
    # establish Austin eligibility.
    "Ambiq": "ambiqmicroinc",
    "ICON": "iconcareers",
    "Iterable": "iterable",
    "Kizen": "kizen",
    # Lila Sciences' employer careers page links to this public Greenhouse
    # board. Its inventory is concentrated outside Texas, so only a posting
    # whose displayed work-location names Austin, Texas may enter the queue.
    "Lila Sciences": "LilaSciences",
}

JOBVITE_SITES = {
    # Enverus links its employer careers page directly to this public Jobvite
    # board. Detail JSON-LD contains original dates and every work location.
    "Enverus": "https://jobs.jobvite.com/enverus",
}

PAYLOCITY_SITES = {
    "American Innovations": "https://recruiting.paylocity.com/Recruiting/Jobs/All/6bbc9270-99ae-49bf-8574-e19054e57eee",
    # The Helper Bees' employer careers page links directly to this public
    # Paylocity board; detail JSON-LD supplies the original date and address.
    "The Helper Bees": "https://recruiting.paylocity.com/Recruiting/Jobs/All/dd6084ee-7df4-419b-84bb-577af4a22b9b/THE-HELPER-BEES-INC",
    # Salient's own careers page links to this public Paylocity board. The
    # detail JSON-LD provides exact Austin location and a current posted date.
    "Salient Systems": "https://recruiting.paylocity.com/Recruiting/Jobs/All/ac777e4c-5448-4eff-8245-1b815dd9cd72",
}

UKG_LEGACY_BOARDS = {
    # UFCU's employer careers page links to this anonymous UKG/UltiPro board.
    # The server-rendered page exposes the public posting date, requisition,
    # full description, and structured work address without authentication.
    "UFCU": "https://recruiting.ultipro.com/UNI1053/JobBoard/9b1b7eec-8714-d785-6d27-8ee3d0405521",
}

# Mphasis's employer careers link creates an anonymous public RippleHire
# candidate session. The issued careers token is read from the redirect on
# every run rather than stored, and the JSON search remains scoped to Texas
# until each detail independently names Austin, Texas.
MPHASIS_RIPPLEHIRE_BOARD = "https://mphasis.ripplehire.com/ripplehire/careers"
TCS_IBEGIN_BOARD = "https://ibegin.tcsapps.com/candidate/"

PAYCOR_SITES = {
    # The foundation's branded careers page embeds this public Paycor/Newton
    # tenant. The branded detail URL supplies the original publication date;
    # the Paycor detail supplies the complete description and location.
    "Michael & Susan Dell Foundation": {
        "client_id": "8a3b93ee47c3692e0147c61264763985",
        "career_url": "https://recruitingbypaycor.com/career",
        "parent_url": "https://www.dell.org/careers/",
        "canonical_detail": "https://www.dell.org/careers/job-description/",
    },
}

PINPOINT_SITES = {
    # Brivo and Eagle Eye Networks now share this first-party Pinpoint board.
    # The JSON feed contains full postings while RSS supplies original dates.
    "Brivo": "https://careers.brivo.com",
}

ASHBY_BOARDS = {
    "Ashby": "ashby",
    "Boom": "boom",
    # Scribd's employer careers page links directly to this public board.
    # Scribd Flex listings span many US cities, so structured Austin, Texas
    # work-location evidence is required below rather than inferred from a
    # remote-US label or company address.
    "Scribd, Inc.": "ScribdInc",
    # Crusoe's employer careers page publishes its openings through this
    # public board. Its large multi-office inventory likewise requires exact
    # Austin, Texas location metadata before collection.
    "Crusoe": "crusoe",
    "Fluidstack": "fluidstack",
    "PAR Technology": "par technology",
    "Plaid": "plaid",
    "Orum": "orum",
    "Ontic": "ontic",
    "SentiLink": "sentilink",
    "webAI": "webai",
    "Upside": "upside",
    "Saronic Technologies": "saronic",
    "Zello": "Zello",
    # Edlink's employer careers page is this public Ashby board. The visible
    # label is only "Austin", but its structured primary postal address names
    # Austin, Texas and is therefore the authoritative location evidence.
    "Edlink": "edlink",
    # CompanyCam's employer site embeds this public board. The company hires
    # broadly across the US, so exact Austin evidence is required below.
    "CompanyCam": "companycam",
    # G2's branded open-positions page embeds this public board. G2 also lists
    # broad US-remote roles, so collection requires explicit Austin metadata.
    "G2": "G2",
    # Higharc's employer careers page is this public Ashby board. Its primary
    # labels are often country-wide remote, while structured secondary work
    # locations provide the authoritative Austin, Texas evidence.
    "Higharc": "higharc",
    # Hello Patient publishes separate Austin and New York copies of the same
    # title. Preserve only the posting whose structured location names Austin.
    "Hello Patient": "hellopatient",
    # Partly's employer board publishes city-specific roles. Require its
    # structured Austin, Texas address rather than headquarters language in
    # the description before accepting a posting into the Austin queue.
    "Partly": "partly.com",
    # MaintainX moved from its retired Greenhouse tenant to this employer-
    # linked Ashby board after joining Autodesk. Its multi-city records carry
    # structured postal addresses used by the exact-Austin gate below.
    "MaintainX": "maintainx",
    # Hopper publishes city-specific remote copies of the same title. The
    # structured postal address is authoritative when the visible label says
    # only "Austin - Remote".
    "Hopper": "hopper",
    # Neurophos publishes its live jobs through this public Ashby board. The
    # inventory spans Austin and California, so the structured work-location
    # fields remain the sole source of Austin eligibility.
    "Neurophos": "neurophos",
}
SNOWFLAKE_ASHBY_BOARD = "snowflake"

REVOLUTPEOPLE_SITES = {
    # Biorce's first-party site links directly to this public tenant board.
    # Its own contact page identifies the ATS's Austin office as Austin, TX.
    "Biorce": {"tenant": "biorce", "austin_office": "Austin"},
}

SMARTRECRUITERS_COMPANIES = {
    "Renesas Electronics": "RenesasElectronics",
    # Asure's employer careers page links to this public tenant. Its lone
    # current result is a stale sales role, but keeping the board configured
    # prevents an aggregator repost date from reviving retired engineering ads.
    "Asure Software": "asuresoftware",
    # ServiceNow's branded Radancy careers application is Cloudflare-guarded,
    # but every live card maps to this public first-party SmartRecruiters feed.
    "ServiceNow": "ServiceNow",
    # Invoca's branded openings page is backed by this public tenant. The
    # shared adapter independently requires an exact Austin, Texas address.
    "Invoca": "Invoca",
    # RRD's employer job-listings page embeds this public SmartRecruiters
    # tenant. The shared adapter independently enforces Austin, Texas and the
    # original release date before retaining a posting.
    "RRD": "RRDonnelley",
}

BAMBOOHR_BOARDS = {
    # Cornelis embeds this public BambooHR tenant on its employer careers page.
    # The list and detail endpoints expose structured city/state/country,
    # original posting dates, and complete descriptions without authentication.
    "Cornelis Networks": "cornelisnetworks",
}

ICIMS_SITES = {
    "Electric Power Engineers": "https://careers-epeconsulting.icims.com",
    "Central Health": "https://careers-centralhealth.icims.com",
}

SUCCESSFACTORS_SITES = {
    # ASSA ABLOY's public jobs2web search is server rendered and its detail
    # microdata provides exact city/state, original date, and full content.
    "ASSA ABLOY Group": {
        "base_url": "https://assaabloy.jobs2web.com",
        "board_url": "https://assaabloy.jobs2web.com/search/?q=&locationsearch=Austin",
    },
    # Optimizely's employer search is server-rendered SuccessFactors. Detail
    # microdata is authoritative: the current Austin-labelled role publishes
    # an incorrect Oklahoma region and therefore fails the Texas gate closed.
    "Optimizely": {
        "base_url": "https://careers.optimizely.com",
        "board_url": "https://careers.optimizely.com/search/?q=&locationsearch=Austin",
    },
}

AVIONTE_BOARDS = {
    # Peak Performers embeds this public Avionté board on its own careers page.
    "Peak Performers": {
        "host": "https://hire.myavionte.com",
        "build_id": "xt3qAtSYsKo",
        "job_board_id": "BJnvI_0f5cc",
        "public_url": "https://www.peakperformers.org/browse-jobs",
    },
}

WORKABLE_BOARDS = {"Multi Media LLC": "multimediallc"}
LEVER_BOARDS = {
    "Esper": "esper",
    "Bumble": "bumbleinc",
    "Aledade": "aledade",
    "Findhelp": "findhelp",
    "Circuit": "getcircuit",
    "CSC Generation": "cscgeneration-2",
    "Arrive Logistics": "arrivelogistics",
    # Favor publishes distinct Texas-wide and Austin copies of some titles.
    # Use the employer's canonical local identity and require the exact city.
    "Favor Delivery": "askfavor",
    "Qvest US": "qvest.us",
    "Confluera": "confluera",
    "Luxury Presence": "luxurypresence",
    # Qrypt links its employer careers page to this public Lever board. Its
    # non-Austin and below-target postings must not enter the Austin corpus.
    "Qrypt": "qrypt",
    # Atom Computing's employer careers page links directly to this public
    # Lever board. Current listings span Boulder and Austin, so an explicit
    # Austin work-location label is required below.
    "Atom Computing": "atomcomputing",
    # Cirrus Logic publishes through Lever's European data region even for
    # Austin roles; the regional API host is configured separately below.
    "Cirrus Logic": "cirrus",
    # Sonar's employer careers page links to this public Lever board. The
    # global inventory includes city-specific copies, so only the displayed
    # Austin, Texas posting may enter the Austin queue.
    "Sonar": "sonarsource",
    # TTEC Digital's employer careers page links to this public Lever board.
    # Its remote inventory is copied across cities, so an explicit Austin,
    # Texas category is required before a posting may enter this queue.
    "TTEC Digital": "ttecdigital",
}
LEVER_API_HOSTS = {"Cirrus Logic": "https://api.eu.lever.co"}
APPLE_AUSTIN_BOARD = "https://jobs.apple.com/en-us/search?location=austin-AST&sort=newest"
AMAZON_AUSTIN_BOARD = "https://www.amazon.jobs/en/search?normalized_city_name%5B%5D=Austin"
AMAZON_SEARCH_QUERIES = (
    "software",
    "systems development",
    "data engineer",
    "engineering manager",
    "security engineering",
    "site reliability",
    "platform engineer",
    "cloud engineer",
    "devops",
)
AMD_AUSTIN_BOARD = "https://careers.amd.com/careers-home/jobs?location=Austin%2C%20TX"
GOOGLE_CAREERS_ROOT = "https://www.google.com/about/careers/applications/"
GOOGLE_AUSTIN_BOARD = urllib.parse.urljoin(GOOGLE_CAREERS_ROOT, "jobs/results/")
MICROSOFT_CAREERS_BASE = "https://apply.careers.microsoft.com"
BAIN_CAREERS_BASE = "https://www.bain.com"
BAIN_JOBS_API = f"{BAIN_CAREERS_BASE}/en/api/jobsearch/keyword/get"
ORACLE_CAREERS_BASE = "https://careers.oracle.com"
ORACLE_API_BASE = "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest"
ORACLE_SITE_NUMBER = "CX_45001"
ORACLE_SEARCH_QUERIES = (
    "software engineer",
    "software developer",
    "engineering manager",
    "software development manager",
    "site reliability engineer",
    "platform engineer",
    "infrastructure engineer",
    "data engineer",
    "cloud engineer",
    "security engineer",
    "technical lead",
)
JPMORGAN_CAREERS_BASE = "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001"
JPMORGAN_API_BASE = "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest"
JPMORGAN_SITE_NUMBER = "CX_1001"
DELL_CAREERS_BASE = "https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers"
DELL_API_BASE = "https://enterpriseplatform.dell.com/hcmRestApi/resources/latest"
DELL_SITE_NUMBER = "CX_1001"
DELL_SEARCH_QUERIES = (
    "software engineer",
    "software developer",
    "engineering manager",
    "software development manager",
    "site reliability engineer",
    "platform engineer",
    "data engineer",
    "cloud engineer",
    "security engineer",
    "technical lead",
)
REALTOR_CAREERS_BASE = "https://careers.realtor.com"
REALTOR_JOB_API = "https://jobsapi-internal.m-cloud.io/api/job"
REALTOR_ORG_ID = "2421"
PROCORE_CAREERS_BASE = "https://careers.procore.com"
PROCORE_AUSTIN_ENGINEERING_BOARD = (
    f"{PROCORE_CAREERS_BASE}/jobs/search?cities%5B%5D=Austin"
    "&dropdown_field_1_uids%5B%5D=bbb6f64252a7db61b48dd4f3433bcbb6"
)
TESLA_CAREERS_BASE = "https://www.tesla.com"
TEMPORAL_CAREERS_BASE = "https://temporal.io"
TEMPORAL_CAREERS_BOARD = f"{TEMPORAL_CAREERS_BASE}/careers"
GM_CAREERS_BASE = "https://search-careers.gm.com"
GM_AUSTIN_BOARD = (
    f"{GM_CAREERS_BASE}/en/jobs/?country=United+States+of+America"
    "&region=Texas&location=Austin&pagesize=100#results"
)
TEAMVIEWER_CAREERS_BASE = "https://careers.teamviewer.com"
TEAMVIEWER_AUSTIN_BOARD = f"{TEAMVIEWER_CAREERS_BASE}/jobs?location=Austin"
SCHWAB_CAREERS_BASE = "https://www.schwabjobs.com"
SCHWAB_AUSTIN_BOARD = f"{SCHWAB_CAREERS_BASE}/search-jobs?k=software&l=Austin%2C%20Texas"
CAPITAL_ONE_CAREERS_BASE = "https://www.capitalonecareers.com"
CAPITAL_ONE_AUSTIN_BOARD = (
    f"{CAPITAL_ONE_CAREERS_BASE}/location/austin-jobs/"
    "1732/6252001-4736286-4737316-4671654/4"
)
ARM_CAREERS_BASE = "https://careers.arm.com"
ARM_AUSTIN_BOARD = f"{ARM_CAREERS_BASE}/location/austin-jobs/33099/6252001-4736286-4671654/4"
DELOITTE_CAREERS_BASE = "https://apply.deloitte.com"
DELOITTE_AUSTIN_BOARD = f"{DELOITTE_CAREERS_BASE}/en_US/careers/SearchJobs/"
DELOITTE_TEXAS_OPTION_ID = "690392"
DELOITTE_AUSTIN_OPTION_ID = "2818"
CISCO_CAREERS_BASE = "https://careers.cisco.com/global/en"
CISCO_AUSTIN_BOARD = f"{CISCO_CAREERS_BASE}/search-results?s=1"
IBM_CAREERS_BASE = "https://careers.ibm.com"
IBM_AUSTIN_BOARD = "https://www.ibm.com/careers/search?q=Austin"
IBM_SEARCH_API = "https://www-api.ibm.com/search/api/v2"
HOME_DEPOT_CAREERS_BASE = "https://careers.homedepot.com"
HOME_DEPOT_JOBS_API = "https://jobsapi-google.m-cloud.io/api/job/search"
HOME_DEPOT_COMPANY_NAME = "companies/8454851f-07b7-4e4c-9b5f-00e0ffbfcb09"
HOME_DEPOT_SEARCH_QUERIES = (
    "software",
    "engineer",
    "engineering manager",
    "data engineer",
    "site reliability",
    "platform engineer",
    "cloud engineer",
    "security engineer",
)
PAYPAL_CAREERS_BASE = "https://paypal.eightfold.ai/careers"
PAYPAL_SEARCH_API = "https://paypal.eightfold.ai/api/pcsx/search"
PAYPAL_DETAIL_API = "https://paypal.eightfold.ai/api/pcsx/position_details"
QUALCOMM_CAREERS_BASE = "https://careers.qualcomm.com/careers"
QUALCOMM_SEARCH_API = "https://careers.qualcomm.com/api/pcsx/search"
QUALCOMM_DETAIL_API = "https://careers.qualcomm.com/api/pcsx/position_details"
SALESFORCE_CAREERS_BASE = "https://www.salesforce.com/company/careers/jobs"
SALESFORCE_JOBS_FEED = "https://a.sfdcstatic.com/digital/xsf/careers/prod/jobs_2.json"
SALESFORCE_JOBS_BACKUP_FEED = "https://a.sfdcstatic.com/digital/xsf/careers/prod/jobs_2_backup.json"
META_CAREERS_BASE = "https://www.metacareers.com"
META_AUSTIN_BOARD = f"{META_CAREERS_BASE}/jobsearch/?offices%5B0%5D=Austin%2C%20TX"
META_GRAPHQL_API = f"{META_CAREERS_BASE}/api/graphql/"
# Anonymous persisted query shipped by Meta's public careers client. The
# collector validates the response shape so a rotated document fails closed.
META_SEARCH_DOCUMENT_ID = "27129360303422352"
ACCENTURE_CAREERS_BASE = "https://www.accenture.com"
ACCENTURE_AUSTIN_BOARD = f"{ACCENTURE_CAREERS_BASE}/us-en/careers/jobsearch?ct=Austin%2C%20TX"
ACCENTURE_JOBS_API = f"{ACCENTURE_CAREERS_BASE}/api/accenture/elastic/findjobs"
RIPPLING_CAREERS_BASE = "https://www.rippling.com/careers/open-roles"
RIPPLING_ALGOLIA_APP_ID = "6FNAX3TBEF"
# Public, search-only browser key shipped by Rippling's official careers page.
RIPPLING_ALGOLIA_SEARCH_KEY = "416caa4690f002ff6fe4a2097623640b"
RIPPLING_ALGOLIA_INDEX = "careers_en-US_production"
RIPPLING_ATS_TENANTS = {
    # Closinglock's own careers page is this public Rippling ATS tenant. The
    # board HTML exposes stable detail links and each detail includes the
    # original createdOn timestamp and explicit work locations.
    "Closinglock": "closinglock",
}
RIPPLING_LEGACY_SITES = {
    # Rugiet's branded careers board uses Rippling ATS's HiringThing-hosted
    # public RSS and JSON-LD pages. Detail metadata supplies the exact Austin
    # address and original publication date without authentication.
    "Rugiet": "https://rugiet-health.rippling-ats.com",
}
PWC_CAREERS_BASE = "https://jobs-us.pwc.com/us/en"
PWC_AUSTIN_BOARD = f"{PWC_CAREERS_BASE}/search-results"
PHENOM_SITES = {
    "Adobe": "https://careers.adobe.com/us/en",
}
QUEST_GLOBAL_CAREERS_BASE = "https://careers.quest-global.com/global/en"
QUEST_GLOBAL_AUSTIN_BOARD = f"{QUEST_GLOBAL_CAREERS_BASE}/search-results/?qcity=Austin"
ADOBE_AUSTIN_BOARD = (
    "https://careers.adobe.com/us/en/search-results/?qcity=Austin"
)
CIRCLE_CAREERS_BASE = "https://careers.circle.com/us/en"
CIRCLE_AUSTIN_BOARD = f"{CIRCLE_CAREERS_BASE}/search-results?s=1"
CVS_CAREERS_BASE = "https://jobs.cvshealth.com/us/en"
CVS_AUSTIN_BOARD = (
    f"{CVS_CAREERS_BASE}/search-results?category=Innovation%20and%20Technology"
    "&p=ChIJLwPMoJm1RIYRetVp1EtGm10&location=Austin%2C%20Texas%2C%20USA"
)
MASTERCARD_CAREERS_BASE = "https://careers.mastercard.com/us/en"
MASTERCARD_AUSTIN_BOARD = f"{MASTERCARD_CAREERS_BASE}/search-results"
LPL_CAREERS_BASE = "https://career.lpl.com"
LPL_AUSTIN_BOARD = f"{LPL_CAREERS_BASE}/search-results?keywords=Austin"
PALOALTO_CAREERS_BASE = "https://jobs.paloaltonetworks.com"
PALOALTO_AUSTIN_BOARD = f"{PALOALTO_CAREERS_BASE}/en/location/austin-jobs/47263/6252001-4736286-4671654/4"
ROKU_CAREERS_BASE = "https://www.weareroku.com"
ROKU_AUSTIN_BOARD = f"{ROKU_CAREERS_BASE}/jobs/search?cities%5B%5D=Austin&page=1&query="
WESTERN_UNION_CAREERS_BASE = "https://careers.westernunion.com"
WESTERN_UNION_WORKDAY_HOST = "https://westernunion.wd5.myworkdayjobs.com"
WESTERN_UNION_WORKDAY_TENANT = "westernunion"
WESTERN_UNION_WORKDAY_SITE = "WesternUnionJobs"
WESTERN_UNION_AUSTIN_URLS = (
    f"{WESTERN_UNION_CAREERS_BASE}/job-details/23367620/staff-software-engineer-digital-platform-austin-tx/",
    f"{WESTERN_UNION_CAREERS_BASE}/job-details/23629119/senior-software-engineer-payments-platform-austin-tx/",
    f"{WESTERN_UNION_CAREERS_BASE}/job-details/23539222/senior-information-security-engineer-denver-co/",
)
RESIDEO_CAREERS_BASE = "https://careers.resideo.com"
RESIDEO_JOBS_API = f"{RESIDEO_CAREERS_BASE}/app/api/jobs"
BITDEER_CAREERS_BASE = "https://bitdeer.breezy.hr"
CELESTICA_CAREERS_BASE = "https://careers.celestica.com"
CELESTICA_AUSTIN_BOARD = f"{CELESTICA_CAREERS_BASE}/go/Engineering-Jobs-Austin-TX/9765701/"
RWE_CAREERS_BASE = "https://jobs.rwe.com"
RWE_AUSTIN_BOARD = f"{RWE_CAREERS_BASE}/RWE/go/All-Jobs_RWE-%28EN%29/8740401/"
EXACTA_CAREERS_BASE = "https://jobs.churchilldowns.com"
EXACTA_AUSTIN_BOARD = f"{EXACTA_CAREERS_BASE}/go/Exacta/9777700/"
KPMG_CAREERS_BASE = "https://www.kpmguscareers.com"
KPMG_JOBS_API = (
    f"{KPMG_CAREERS_BASE}/wp-content/themes/understrap-child-main/"
    "page-templates/google/get-jobs.php"
)
HHSC_CAREERS_BASE = "https://careers.hhs.texas.gov"
HHSC_SEARCH_BASE = f"{HHSC_CAREERS_BASE}/hhscjobs/search/"
EY_CAREERS_BASE = "https://careers.ey.com"
EY_SEARCH_BASE = f"{EY_CAREERS_BASE}/ey/search/"
JIBE_SITES = {
    "First Citizens Bank": {
        "base_url": "https://jobs.firstcitizens.com",
        "keywords": ("software", "data engineer", "engineering manager"),
    },
    "H-E-B": {
        "base_url": "https://careers.heb.com",
        # The public Jibe UI exposes Digital as a stable first-party category.
        # It currently narrows Austin's mostly retail inventory to five roles
        # in one request, including manager and data-platform title variants.
        "searches": ({"categories": "Digital"},),
    },
    # Lutron's branded careers site is backed by this public Jibe API. The
    # shared normalizer requires structured Austin/Texas/US location fields
    # and an original posting date no older than 30 days.
    "Lutron Electronics": {
        "base_url": "https://careers.lutron.com",
        "searches": ({"keywords": "software"},),
    },
}
ADP_SITES = {
    "Overhaul": {
        "cid": "0607f7e2-b2c8-4bd9-9db0-502820edc413",
        "cc_id": "19000101_000001",
        # Overhaul's employer Careers link opens this anonymous public ADP
        # board. The backing read-only API exposes complete descriptions and
        # structured city/state fields without authentication.
        "board_url": (
            "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
            "?cid=0607f7e2-b2c8-4bd9-9db0-502820edc413"
            "&ccId=19000101_000001&lang=en_US"
        ),
    },
}
EMPLOYER_PAGE_SITES = {
    "PICKUP AI": {
        # PICKUP publishes this opening directly in server-rendered HTML. Its
        # overview supplies the authoritative Austin/hybrid location and pay;
        # the linked detail page supplies the complete role description.
        "board_url": "https://pickupjobs.co/careers",
        "detail_url": "https://pickupjobs.co/careers/software-engineer",
        "detail_path": "/careers/software-engineer",
        "title": "Senior Software Engineer",
    },
}
WORKDAY_SITES = {
    "GEICO": {
        "host": "https://geico.wd1.myworkdayjobs.com",
        "tenant": "geico",
        "site": "External",
        # GEICO's branded careers homepage may challenge unattended clients,
        # while this anonymous public Workday search and detail feed remains
        # stable. Detail normalization is authoritative for exact Austin.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Land.com Network": {
        "host": "https://costar.wd1.myworkdayjobs.com",
        "tenant": "costar",
        "site": "CoStarCareers",
        # Land.com's employer listing is published through parent CoStar's
        # public Workday tenant. Search cards and details must both survive the
        # normal freshness and exact-Austin checks.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "SHI International Corp.": {
        "host": "https://shi.wd12.myworkdayjobs.com",
        "tenant": "shi",
        "site": "shicareers",
        # SHI's careers page links to this public Workday site. Text search is
        # broad, so detail records remain authoritative for Austin eligibility.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Light & Wonder": {
        "host": "https://lnw.wd5.myworkdayjobs.com",
        "tenant": "lnw",
        "site": "LightWonderExternalCareers",
        # The employer board returns exact Austin cards and full details.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "SciPlay": {
        "host": "https://lnw.wd5.myworkdayjobs.com",
        "tenant": "lnw",
        "site": "SciPlayExternalCareersSite",
        # SciPlay's employer careers application is this public Workday site.
        # Exact location and original date are validated on the detail record.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Huntington National Bank": {
        "host": "https://huntington.wd12.myworkdayjobs.com",
        "tenant": "huntington",
        "site": "HNBcareers",
        # The employer's public tenant supports Austin text search. Workday
        # details remain authoritative for multi-location city/state evidence.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Rockwell Automation": {
        "host": "https://rockwellautomation.wd1.myworkdayjobs.com",
        "tenant": "rockwellautomation",
        "site": "External_Rockwell_Automation",
        # The public board supports Austin text search. Workday detail remains
        # authoritative for exact location, and 30+ day cards fail freshness.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Acrisure": {
        "host": "https://acrisure.wd1.myworkdayjobs.com",
        "tenant": "acrisure",
        "site": "Acrisure",
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Ensemble Health Partners": {
        "host": "https://ensemblehp.wd5.myworkdayjobs.com",
        "tenant": "ensemblehp",
        "site": "EnsembleHealthPartnersCareers",
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Sixth Street": {
        "host": "https://sixthstreet.wd1.myworkdayjobs.com",
        "tenant": "sixthstreet",
        "site": "sixthstreetcareers",
        # The employer's current-opportunities page embeds this exact tenant.
        # Workday details remain authoritative for Austin and freshness.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "TrendAI": {
        "host": "https://trendmicro.wd3.myworkdayjobs.com",
        "tenant": "trendmicro",
        "site": "External",
        # TrendAI is Trend Micro's AI-security business unit. Its branded
        # postings are published through this public Workday site and each
        # Austin result is revalidated against the complete employer detail.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "The University of Texas at Austin": {
        "host": "https://utaustin.wd1.myworkdayjobs.com",
        "tenant": "utaustin",
        "site": "UTstaff",
        # UT does not publish a location facet. Its public software search is
        # deliberately narrowed here, and detail records must still name
        # Austin, TX rather than an ambiguous campus before they are accepted.
        "applied_facets": {},
        "search_text": "Software",
    },
    "Texas Mutual Insurance Company": {
        "host": "https://texasmutual.wd1.myworkdayjobs.com",
        "tenant": "texasmutual",
        "site": "texas_mutual_careers",
        "applied_facets": {},
        "search_text": "Austin",
    },
    "eBay": {
        "host": "https://ebay.wd5.myworkdayjobs.com",
        "tenant": "ebay",
        # eBay's branded Phenom portal sends applications through this public
        # Workday site. Its search and detail feeds expose canonical current
        # Austin listings without relying on aggregator mirrors.
        "site": "apply",
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Apex Fintech Solutions": {
        "host": "https://peak6group.wd1.myworkdayjobs.com",
        "tenant": "peak6group",
        "site": "apexfintechsolutions",
        # Apex's first-party branded portal is backed by this public Workday
        # site. Text search returns multi-location postings; detail records are
        # still required to name Austin before they enter the corpus.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Cloudera": {
        "host": "https://cloudera.wd5.myworkdayjobs.com",
        "tenant": "cloudera",
        "site": "External_Career",
        "applied_facets": {},
        "search_text": "Austin",
    },
    "AssetMark": {
        "host": "https://assetmark.wd5.myworkdayjobs.com",
        "tenant": "assetmark",
        "site": "AssetMark_Careers",
        # AssetMark's public board exposes Austin listings through text search;
        # detail normalization still requires an explicit Austin, Texas work
        # location before a role can enter the queue.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Dimensional Fund Advisors": {
        "host": "https://dimensional.wd5.myworkdayjobs.com",
        "tenant": "dimensional",
        "site": "DFA_Careers",
        # The visible search label can be only "Austin". Detail normalization
        # remains authoritative and must independently supply Texas evidence.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "PEAK6": {
        "host": "https://peak6group.wd1.myworkdayjobs.com",
        "tenant": "peak6group",
        "site": "PEAK6",
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Zendesk": {
        "host": "https://zendesk.wd1.myworkdayjobs.com",
        "tenant": "zendesk",
        "site": "zendesk",
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Postman": {
        # The former Greenhouse board is inactive. Postman's public careers
        # page links to this Workday tenant, including an Austin posting.
        "host": "https://postman.wd108.myworkdayjobs.com",
        "tenant": "postman",
        "site": "careers",
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Commerce": {
        "host": "https://bigcommerce.wd12.myworkdayjobs.com",
        "tenant": "bigcommerce",
        "site": "Commerce",
        # Text search includes multi-location Austin roles. Detail
        # normalization remains authoritative and requires explicit Austin.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Expedia Group": {
        "host": "https://expedia.wd108.myworkdayjobs.com",
        "tenant": "expedia",
        "site": "search",
        # Expedia's public careers site is backed by this exact Austin office
        # facet. Detail normalization remains authoritative for multi-location
        # roles and still requires an explicit Austin, Texas work location.
        "applied_facets": {"locations": ["d9ad289ce9b701609c73e2940536397b"]},
        "search_text": "",
    },
    "Applied Materials": {
        "host": "https://amat.wd1.myworkdayjobs.com",
        "tenant": "amat",
        "site": "External",
        "applied_facets": {"locations": ["16f3e0f5ed5d444cb77484050e203944"]},
        "search_text": "",
    },
    "Broadcom": {
        "host": "https://broadcom.wd1.myworkdayjobs.com",
        "tenant": "broadcom",
        "site": "External_Career",
        "applied_facets": {"locations": ["877d747df719100213665b4fa1470000", "877d747df71910021366662e2df00000"]},
        "search_text": "",
    },
    "CrowdStrike": {
        "host": "https://crowdstrike.wd5.myworkdayjobs.com",
        "tenant": "crowdstrike",
        "site": "crowdstrikecareers",
        "applied_facets": {"locations": ["27086a67c26901b86b4bc6cb6f01eb1d"]},
        "search_text": "",
    },
    "Intel": {
        "host": "https://intel.wd1.myworkdayjobs.com",
        "tenant": "intel",
        "site": "External",
        # Intel's Austin office is hardware-heavy. Combining the exact Austin
        # location and Software Engineering family facets keeps collection
        # focused before any resume-specific scoring occurs.
        "applied_facets": {
            "locations": ["1e4a4eb3adf1016541777876bf8111cf"],
            "jobFamilyGroup": ["ace7a3d23b7e01a0544279031a0ec85c"],
        },
        "search_text": "",
    },
    "NVIDIA": {
        "host": "https://nvidia.wd5.myworkdayjobs.com",
        "tenant": "nvidia",
        "site": "NVIDIAExternalCareerSite",
        # Workday's text search misses multi-location roles whose primary office is
        # elsewhere. This public location facet returns every posting that names
        # Austin as either a primary or additional work location.
        "applied_facets": {"locations": ["91336993fab910af6d702b631b94c2de"]},
        "search_text": "",
    },
    "Revionics, an Aptos Company": {
        "host": "https://aptos.wd108.myworkdayjobs.com",
        "tenant": "aptos",
        "site": "Revionics",
        # Revionics' first-party careers page links directly to this board.
        # Detail normalization remains authoritative for exact Austin location.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Trimble": {
        "host": "https://trimble.wd1.myworkdayjobs.com",
        "tenant": "trimble",
        "site": "TrimbleCareers",
        # Trimble's exact Austin facet also catches multi-location postings
        # whose primary Workday location is outside Texas.
        "applied_facets": {"locations": ["ebb3832f7b201000fb2f72a75efd0000"]},
        "search_text": "",
    },
    "Visa": {
        "host": "https://visa.wd5.myworkdayjobs.com",
        "tenant": "visa",
        "site": "Visa",
        # Visa's public Workday search supports Austin as search text. Detail
        # normalization still requires an explicit Austin, Texas work location.
        "applied_facets": {},
        "search_text": "Austin",
    },
    "Q2": {
        "host": "https://q2ebanking.wd5.myworkdayjobs.com",
        "tenant": "q2ebanking",
        "site": "Q2",
        # This exact public location facet avoids matching Austin references
        # in descriptions or postings whose work location is elsewhere.
        "applied_facets": {"locations": ["0da4bb96663010308829a8dfd4e91994"]},
        "search_text": "",
    },
    "Snap Inc.": {
        "host": "https://wd1.myworkdaysite.com",
        "tenant": "snapchat",
        "site": "snap",
        # Snap's public career site is backed by this Workday Austin facet.
        # The facet is more reliable than a text search for multi-location jobs.
        "applied_facets": {"locations": ["f84c7a1ec2ba1000d7878e08800c0000"]},
        "search_text": "",
    },
    "YETI": {
        "host": "https://yeticoolers.wd5.myworkdayjobs.com",
        "tenant": "yeticoolers",
        "site": "YETI",
        # The branded employer board supports Austin text search; Workday
        # detail normalization remains authoritative for exact city/state.
        "applied_facets": {},
        "search_text": "Austin",
    },
}


def _fresh_iso_listing(value: Any, max_age_days: int = 30) -> bool:
    """Keep live-feed records that were published recently enough to act on."""
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        normalized = raw.replace("Z", "+00:00")
        # Phenom emits offsets such as ``+0000``, which ``fromisoformat`` does
        # not accept consistently across the Python versions used locally.
        normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)
        # Avionté emits seven fractional-second digits while Python accepts at
        # most six. Truncate excess precision without changing the timestamp.
        normalized = re.sub(r"(\.\d{6})\d+(?=(?:[+-]\d{2}:\d{2})?$)", r"\1", normalized)
        published = datetime.fromisoformat(normalized)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    age = (datetime.now(timezone.utc).date() - published.date()).days
    return 0 <= age <= max_age_days


def mphasis_job_item(
    payload: dict[str, Any],
    token: str,
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one fresh Mphasis detail that explicitly names Austin, Texas."""
    job = payload.get("jobVO") if isinstance(payload, dict) else None
    if not isinstance(job, dict) or clean_text(job.get("jobStatus")).casefold() not in {"", "active"}:
        return None
    description = clean_text(job.get("jobDesc"))
    if not re.search(r"\baustin\s*,\s*(?:tx|texas)\b", description, re.I):
        return None
    raw_date = clean_text(job.get("jobPostingDate"))
    posted = ""
    if raw_date:
        try:
            posted = datetime.strptime(raw_date, "%d-%b-%Y").date().isoformat()
        except ValueError:
            posted = raw_date[:10]
    if not posted:
        publish_details = job.get("publishDetails") if isinstance(job.get("publishDetails"), dict) else {}
        posted = clean_text(publish_details.get("CAREER_SITE"))[:10]
    if not _fresh_iso_listing(posted, max_age_days=max_age_days):
        return None
    job_seq = clean_text(job.get("jobSeq"))
    title = clean_text(job.get("jobTitle"))
    if not job_seq or not title or not description:
        return None
    query = urllib.parse.urlencode({"token": clean_text(token), "source": "CAREERSITE"})
    item = {
        "company": "Mphasis",
        "title": title,
        "location": "Austin, TX",
        "url": f"https://mphasis.ripplehire.com/candidate/?{query}#detail/job/{job_seq}",
        "source": "ripplehire",
        "description": description,
        "date_posted": posted,
        "provider_job_id": clean_text(job.get("jobCode")) or job_seq,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in description.casefold() else ("hybrid" if "hybrid" in description.casefold() else "onsite"),
    }
    compensation_text = clean_text(" ".join(str(value or "") for value in (
        description, job.get("otherDetails"), job.get("compensationInfo"), job.get("compensationRange"),
    )))
    item.update(extract_salary(compensation_text, job))
    if not item.get("salary_text"):
        item["salary_text"] = format_salary_range(item.get("salary_min"), item.get("salary_max"))
    return item


def mphasis_company_jobs(
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh exact-Austin jobs from Mphasis's public RippleHire site."""
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    user_agent = "Mozilla/5.0 EliOpportunityQueue/1.0"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        request = urllib.request.Request(MPHASIS_RIPPLEHIRE_BOARD, headers={"User-Agent": user_agent, "Accept": "text/html"})
        with opener.open(request, timeout=30) as response:
            landing_url = response.geturl()
            _response_body(response, 2_000_000)
        token = clean_text((urllib.parse.parse_qs(urllib.parse.urlsplit(landing_url).query).get("token") or [""])[0])
        if not token:
            return [], ["Mphasis RippleHire landing: missing public careers token"]
        params = {
            "page": 0,
            "search": "*:*",
            "token": token,
            "source": "CAREERSITE",
            "pagesize": 100,
            "location": "Texas",
        }
        body = urllib.parse.urlencode({
            "careerSiteUrlParams": json.dumps(params, separators=(",", ":")),
            "lang": "en",
        }).encode("utf-8")
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": landing_url.split("#", 1)[0],
        }
        search_request = urllib.request.Request(
            "https://mphasis.ripplehire.com/candidate/candidatejobsearch",
            data=body,
            method="POST",
            headers=headers,
        )
        with opener.open(search_request, timeout=30) as response:
            payload = json.loads(_response_body(response, 10_000_000).decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
        return [], [f"Mphasis RippleHire search: {type(exc).__name__}"]

    listings = payload.get("jobVoList") or [] if isinstance(payload, dict) else []
    if not isinstance(listings, list):
        return [], ["Mphasis RippleHire search: ValueError"]
    total = int(payload.get("totalJobCount") or 0)
    if total > len(listings):
        return [], [f"Mphasis RippleHire search: incomplete public result set ({len(listings)}/{total})"]
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for listing in listings:
        if not isinstance(listing, dict):
            continue
        job_seq = clean_text(listing.get("jobSeq"))
        if not job_seq:
            continue
        time.sleep(delay)
        query = urllib.parse.urlencode({"token": token, "jobSeq": job_seq, "source": "CAREERSITE", "lang": "en"})
        try:
            detail_request = urllib.request.Request(
                f"https://mphasis.ripplehire.com/candidate/candidatejobdetail?{query}",
                headers=headers,
            )
            with opener.open(detail_request, timeout=30) as response:
                detail = json.loads(_response_body(response, 20_000_000).decode("utf-8", "replace"))
            item = mphasis_job_item(detail, token, max_age_days=max_age_days)
            if item and item["url"] not in seen:
                seen.add(item["url"])
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Mphasis RippleHire {job_seq}: {type(exc).__name__}")
    return results, errors


def tcs_job_item(
    payload: dict[str, Any],
    posted_date: str,
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one dated, exact-Austin detail from TCS's public iBegin API."""
    job = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(job, dict):
        return None
    title = clean_text(job.get("title"))
    location = clean_text(job.get("location"))
    country = clean_text(job.get("country"))
    if location.casefold() not in {"austin, tx", "austin, texas"} or country.casefold() not in {"", "united states", "usa", "us"}:
        return None
    if not posted_date or not _fresh_iso_listing(posted_date, max_age_days=max_age_days):
        return None
    job_id = clean_text(job.get("jobId"))
    base_description = clean_text(job.get("description"))
    if not job_id or not title or not base_description:
        return None
    apply_by = clean_text(job.get("applyby"))[:10]
    metadata = [
        f"Experience: {clean_text(job.get('experience'))}" if clean_text(job.get("experience")) else "",
        f"Role: {clean_text(job.get('role'))}" if clean_text(job.get("role")) else "",
        f"Desired skills: {clean_text(job.get('skilldetail'))}" if clean_text(job.get("skilldetail")) else "",
        f"Apply by: {apply_by}" if apply_by else "",
    ]
    description = clean_text(" ".join([base_description, *[value for value in metadata if value]]))
    item = {
        "company": "Tata Consultancy Services",
        "title": title,
        "location": "Austin, TX",
        "url": f"{TCS_IBEGIN_BOARD}#/jobs/{job_id}J",
        "source": "tcs",
        "description": description,
        "date_posted": posted_date,
        "provider_job_id": job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in description.casefold() else ("hybrid" if "hybrid" in description.casefold() else "onsite"),
    }
    min_salary = clean_text(job.get("minSalary"))
    max_salary = clean_text(job.get("maxSalary"))
    structured_range = f"Salary range: {min_salary}-{max_salary}" if min_salary and max_salary else ""
    compensation_text = clean_text(" ".join((description, structured_range)))
    item.update(extract_salary(compensation_text, job))
    if not item.get("salary_text"):
        item["salary_text"] = format_salary_range(item.get("salary_min"), item.get("salary_max"))
    return item


def _tcs_json_post(endpoint: str, payload: dict[str, Any], headers: dict[str, str], max_bytes: int) -> dict[str, Any]:
    """POST public iBegin JSON, falling back to curl for its legacy TLS edge."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    try:
        request = urllib.request.Request(endpoint, data=body, method="POST", headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = _response_body(response, max_bytes)
    except urllib.error.URLError:
        command = ["curl", "-fsS", "-L", "--max-time", "30"]
        for name, value in headers.items():
            command.extend(("-H", f"{name}: {value}"))
        command.extend(("--data-binary", "@-", endpoint))
        completed = subprocess.run(command, input=body, capture_output=True, timeout=35, check=False)
        if completed.returncode:
            detail = completed.stderr.decode("utf-8", "replace").strip()[:200]
            raise urllib.error.URLError(detail or f"curl exit {completed.returncode}")
        raw = completed.stdout[:max_bytes]
    parsed = json.loads(raw.decode("utf-8", "replace"))
    if not isinstance(parsed, dict):
        raise ValueError("TCS iBegin response was not an object")
    return parsed


def tcs_austin_jobs(
    known_posted_dates: dict[str, str] | None = None,
    request_delay_seconds: float = 2.0,
    max_pages: int = 10,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Refresh dated local mirrors through TCS's anonymous public iBegin APIs.

    iBegin publishes application deadlines but not original publication dates.
    New undated rows are intentionally withheld; a dated aggregator discovery
    can be upgraded canonically on a later pass without inventing a date.
    """
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    known_dates = {
        clean_text(title).casefold(): clean_text(value)
        for title, value in (known_posted_dates or {}).items()
        if clean_text(title) and clean_text(value)
    }
    headers = {
        "User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": TCS_IBEGIN_BOARD,
    }
    endpoint = urllib.parse.urljoin(TCS_IBEGIN_BOARD, "api/v1/jobs/searchJ")
    listings: list[dict[str, Any]] = []
    expected_total: int | None = None
    pages = max(1, min(int(max_pages), 10))
    for page in range(1, pages + 1):
        if page > 1:
            time.sleep(delay)
        search_payload = {
            "jobTitle": None,
            "jobCity": "Austin",
            "jobFunction": None,
            "jobExperience": None,
            "jobSkill": None,
            "pageNumber": str(page),
            "userText": "",
            "jobTitleOrder": None,
            "jobCityOrder": None,
            "jobFunctionOrder": None,
            "jobExperienceOrder": None,
            "applyByOrder": None,
            "regular": True,
            "walkin": True,
        }
        try:
            payload = _tcs_json_post(endpoint, search_payload, headers, 10_000_000)
            data = payload.get("data") if isinstance(payload, dict) else None
            page_items = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(page_items, list):
                return [], [f"TCS iBegin search page {page}: ValueError"]
            expected_total = int(data.get("totalJobs") or 0) if expected_total is None else expected_total
            listings.extend(value for value in page_items if isinstance(value, dict))
            if not page_items or len(listings) >= expected_total:
                break
        except (urllib.error.URLError, TimeoutError, socket.timeout, subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
            return [], [f"TCS iBegin search page {page}: {type(exc).__name__}"]
    if expected_total is not None and len(listings) < expected_total:
        return [], [f"TCS iBegin search: incomplete public result set ({len(listings)}/{expected_total})"]

    results: list[dict[str, Any]] = []
    for listing in listings:
        title = clean_text(listing.get("jobTitle"))
        location = clean_text(listing.get("location"))
        posted_date = known_dates.get(title.casefold(), "")
        preliminary = {
            "title": title,
            "description": clean_text(listing.get("skills")),
        }
        if location.casefold() not in {"austin, tx", "austin, texas"} or not posted_date or not title_is_candidate(preliminary):
            continue
        external_id = clean_text(listing.get("id"))
        job_id = external_id[:-1] if external_id.casefold().endswith("j") else external_id
        if not job_id:
            continue
        time.sleep(delay)
        try:
            detail = _tcs_json_post(
                urllib.parse.urljoin(TCS_IBEGIN_BOARD, "api/v1/job/desc"),
                {"jobId": job_id},
                headers,
                20_000_000,
            )
            item = tcs_job_item(detail, posted_date, max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"TCS iBegin {job_id}: {type(exc).__name__}")
    return results, errors


def canonical_public_url(value: Any) -> str:
    """Remove repeated query pairs while preserving an employer's public URL."""
    raw = clean_text(value)
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    pairs = list(dict.fromkeys(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)))
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(pairs), parsed.fragment))


def rippling_search_item(hit: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one exact-Austin record from Rippling's public careers index."""
    locations = hit.get("locationNames") or []
    if not isinstance(locations, list) or not any(
        clean_text(value).casefold() in {"austin, tx", "austin, texas"}
        for value in locations
    ):
        return None
    job_id = clean_text(hit.get("jobId") or hit.get("objectID"))
    url = canonical_public_url(hit.get("url"))
    match = re.fullmatch(
        r"https://ats\.rippling\.com/rippling/jobs/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?",
        url,
        re.I,
    )
    if not job_id or not match or match.group(1).casefold() != job_id.casefold():
        return None
    return {
        "company": "Rippling",
        "title": clean_text(hit.get("name")),
        "location": "Austin, TX",
        "url": url.rstrip("/"),
        "source": "rippling",
        "provider_job_id": job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if hit.get("isRemote") else "onsite/hybrid",
    }


def _rippling_job_post(raw: str) -> dict[str, Any]:
    """Read the server-rendered public ATS record from a Rippling job page."""
    match = re.search(
        r'<script\b(?=[^>]*\bid=["\']__NEXT_DATA__["\'])[^>]*>(.*?)</script>',
        raw,
        re.I | re.S,
    )
    if not match:
        raise ValueError("Rippling structured job data was not found")
    payload = json.loads(match.group(1))
    page_props = ((payload.get("props") or {}).get("pageProps") or {}) if isinstance(payload, dict) else {}
    api_data = page_props.get("apiData") or {}
    job = api_data.get("jobPost") or {}
    if not isinstance(job, dict) or not job:
        raise ValueError("Rippling job detail is missing")
    return job


def rippling_tenant_search_urls(raw: str, tenant: str) -> list[str]:
    """Extract stable detail links from one public Rippling ATS tenant board."""
    tenant_value = clean_text(tenant).strip("/")
    if not tenant_value:
        return []
    pattern = re.compile(
        rf"/{re.escape(tenant_value)}/jobs/([0-9a-f]{{8}}(?:-[0-9a-f]{{4}}){{3}}-[0-9a-f]{{12}})",
        re.I,
    )
    return [
        f"https://ats.rippling.com/{tenant_value}/jobs/{job_id}"
        for job_id in dict.fromkeys(match.casefold() for match in pattern.findall(raw))
    ]


def rippling_tenant_job_item(
    company: str,
    tenant: str,
    raw: str,
    url: str,
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one fresh public Rippling ATS detail for any configured tenant."""
    job = _rippling_job_post(raw)
    if job.get("unlistedFromSearch") is True:
        return None
    locations = job.get("workLocations") or []
    if not isinstance(locations, list) or not any(
        clean_text(value).casefold() in {"austin, tx", "austin, texas"}
        for value in locations
    ):
        return None
    posted = clean_text(job.get("createdOn"))[:10]
    if not _fresh_iso_listing(posted, max_age_days=max_age_days):
        return None
    job_id = clean_text(job.get("uuid"))
    canonical_url = canonical_public_url(job.get("url") or url).rstrip("/")
    match = re.fullmatch(
        rf"https://ats\.rippling\.com/{re.escape(clean_text(tenant).strip('/'))}/jobs/"
        r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})",
        canonical_url,
        re.I,
    )
    if not job_id or not match or match.group(1).casefold() != job_id.casefold():
        return None
    description_fields = job.get("description") or {}
    if not isinstance(description_fields, dict):
        description_fields = {}
    description = clean_text(" ".join(
        str(description_fields.get(key) or "") for key in ("company", "role")
    ))
    item = {
        "company": company,
        "title": clean_text(job.get("name")),
        "location": "Austin, TX",
        "url": canonical_url,
        "source": "rippling",
        "description": description,
        "date_posted": posted,
        "provider_job_id": job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if any("remote" in clean_text(value).casefold() for value in locations) else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if item["title"] and description else None


def rippling_job_item(raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one fresh Rippling corporate ATS detail for compatibility."""
    return rippling_tenant_job_item("Rippling", "rippling", raw, url, max_age_days=max_age_days)


def rippling_tenant_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh exact-Austin targets from configured public Rippling tenants."""
    delay = max(2.0, float(request_delay_seconds))
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    headers = {"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"}
    for company, tenant in RIPPLING_ATS_TENANTS.items():
        if companies is not None and company not in companies:
            continue
        board_url = f"https://ats.rippling.com/{tenant}/jobs"
        try:
            request = urllib.request.Request(board_url, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"{company} Rippling ATS board: {type(exc).__name__}")
            continue
        for url in rippling_tenant_search_urls(raw, tenant):
            time.sleep(delay)
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = _response_body(response, 20_000_000).decode("utf-8", "replace")
                item = rippling_tenant_job_item(
                    company, tenant, detail, url, max_age_days=max_age_days,
                )
                if item and title_is_candidate(item):
                    results.append(item)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} Rippling ATS {url.rsplit('/', 1)[-1]}: {type(exc).__name__}")
    return results, errors


def rippling_legacy_search_listings(raw: str, base_url: str) -> list[dict[str, str]]:
    """Read exact-Austin summaries from a public HiringThing/Rippling RSS feed."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    expected_host = urllib.parse.urlsplit(base_url).netloc.casefold()
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in root.findall(".//item"):
        title = clean_text(node.findtext("title"))
        location = clean_text(node.findtext("location"))
        url = canonical_public_url(node.findtext("link"))
        parsed = urllib.parse.urlsplit(url)
        match = re.fullmatch(r"/job/(\d+)/[^/?#]+/?", parsed.path, re.I)
        if (
            not title
            or parsed.netloc.casefold() != expected_host
            or not match
            or not re.search(r"\bAustin,?\s+(?:TX|Texas)\b", location, re.I)
            or url in seen
        ):
            continue
        seen.add(url)
        results.append({
            "provider_job_id": match.group(1),
            "title": title,
            "location": location,
            "url": url.rstrip("/"),
        })
    return results


def rippling_legacy_job_item(
    company: str,
    raw: str,
    url: str,
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one fresh HiringThing-era Rippling JSON-LD job posting."""
    posting: dict[str, Any] | None = None
    for value in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            posting = candidate
            break
    if not posting:
        return None
    address = ((posting.get("jobLocation") or {}).get("address") or {})
    city = clean_text(address.get("addressLocality"))
    region = clean_text(address.get("addressRegion"))
    country = clean_text(address.get("addressCountry"))
    if (
        city.casefold() != "austin"
        or region.casefold() not in {"tx", "texas"}
        or country.casefold() not in {"us", "usa", "united states"}
    ):
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days=max_age_days):
        return None
    canonical_url = canonical_public_url(url).rstrip("/")
    match = re.search(r"/job/(\d+)(?:/|$)", urllib.parse.urlsplit(canonical_url).path, re.I)
    title = clean_text(posting.get("title"))
    description = clean_text(posting.get("description"))
    item = {
        "company": company,
        "title": title,
        "location": ", ".join(value for value in (city, region, country) if value),
        "url": canonical_url,
        "source": "rippling",
        "description": description,
        "date_posted": posted,
        "provider_job_id": match.group(1) if match else "",
        "easy_apply": 0,
        "work_arrangement": "remote" if re.search(r'(?:"|&quot;)remote(?:"|&quot;):true', raw, re.I) else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and description and match else None


def rippling_legacy_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh exact-Austin jobs from configured legacy Rippling boards."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    headers = {"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html, application/rss+xml"}
    for company, base_url in RIPPLING_LEGACY_SITES.items():
        if companies is not None and company not in companies:
            continue
        try:
            request = urllib.request.Request(f"{base_url.rstrip('/')}/api/rss.xml", headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"{company} Rippling RSS: {type(exc).__name__}")
            continue
        candidates = [
            listing for listing in rippling_legacy_search_listings(raw, base_url)
            if title_is_candidate(listing)
        ]
        for index, listing in enumerate(candidates):
            if index:
                time.sleep(delay)
            try:
                request = urllib.request.Request(listing["url"], headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = _response_body(response, 20_000_000).decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} Rippling {listing['provider_job_id']}: {type(exc).__name__}")
                continue
            item = rippling_legacy_job_item(company, detail, listing["url"], max_age_days=max_age_days)
            if item and title_is_candidate(item):
                results.append(item)
    return results, errors


def rippling_austin_jobs(
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin targets from Rippling's public Algolia and ATS surfaces."""
    delay = max(2.0, float(request_delay_seconds))
    search_endpoint = (
        f"https://{RIPPLING_ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/"
        f"{urllib.parse.quote(RIPPLING_ALGOLIA_INDEX, safe='')}/query"
    )
    body = json.dumps({
        "query": "",
        "hitsPerPage": 100,
        "facetFilters": ["locationNames:Austin, TX"],
        "facets": ["departmentName", "locationNames"],
    }).encode("utf-8")
    try:
        request = urllib.request.Request(
            search_endpoint,
            data=body,
            method="POST",
            headers={
                "User-Agent": "EliOpportunityQueue/1.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-algolia-application-id": RIPPLING_ALGOLIA_APP_ID,
                "x-algolia-api-key": RIPPLING_ALGOLIA_SEARCH_KEY,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read(10_000_000))
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
        return [], [f"Rippling search: {type(exc).__name__}"]
    hits = payload.get("hits") or [] if isinstance(payload, dict) else []
    if not isinstance(hits, list):
        return [], ["Rippling search: ValueError"]
    total = int(payload.get("nbHits") or 0)
    if total > len(hits):
        return [], [f"Rippling search: incomplete public result set ({len(hits)}/{total})"]
    candidates = [
        item for hit in hits if isinstance(hit, dict)
        if (item := rippling_search_item(hit)) and title_is_candidate(item)
    ]
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for listing in candidates:
        time.sleep(delay)
        try:
            request = urllib.request.Request(
                listing["url"],
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 20_000_000).decode("utf-8", "replace")
            item = rippling_job_item(raw, listing["url"], max_age_days=max_age_days)
            if item and title_is_candidate(item) and item["url"] not in seen:
                seen.add(item["url"])
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Rippling {listing['provider_job_id']}: {type(exc).__name__}")
    return results, errors


def smartrecruiters_job_item(
    company: str,
    detail: dict[str, Any],
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one fresh SmartRecruiters posting with an exact Austin address."""
    location = detail.get("location") if isinstance(detail.get("location"), dict) else {}
    city = clean_text(location.get("city"))
    region = clean_text(location.get("region"))
    country = clean_text(location.get("country"))
    if (
        city.casefold() != "austin"
        or region.casefold() not in {"tx", "texas"}
        or country.casefold() not in {"us", "usa", "united states"}
    ):
        return None
    posted = clean_text(detail.get("releasedDate"))[:10]
    if detail.get("active") is False or not _fresh_iso_listing(posted, max_age_days):
        return None
    sections = (detail.get("jobAd") or {}).get("sections") if isinstance(detail.get("jobAd"), dict) else {}
    if not isinstance(sections, dict):
        sections = {}
    description = clean_text(" ".join(
        " ".join((clean_text(section.get("title")), clean_text(section.get("text"))))
        for section in sections.values()
        if isinstance(section, dict)
    ))
    title = clean_text(detail.get("name"))
    posting_url = canonical_public_url(detail.get("postingUrl"))
    source = "smartrecruiters"
    provider_job_id = clean_text(detail.get("id") or detail.get("refNumber"))
    if clean_text(company).casefold() == "servicenow":
        posting_id = clean_text(detail.get("id"))
        normalized_title = "".join(
            character
            for character in unicodedata.normalize("NFKD", title)
            if not unicodedata.combining(character)
        ).casefold()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized_title).strip("-") or "job-details"
        posting_url = f"https://careers.servicenow.com/jobs/{posting_id}/{slug}/" if posting_id else ""
        source = "servicenow"
        provider_job_id = clean_text(detail.get("refNumber") or posting_id)
    item = {
        "company": company,
        "title": title,
        "location": clean_text(location.get("fullLocation")) or f"{city}, {region}, {country.upper()}",
        "url": posting_url,
        "source": source,
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if location.get("remote") else ("hybrid" if location.get("hybrid") else "onsite"),
    }
    item.update(extract_salary(description, detail))
    if not item.get("salary_text"):
        item["salary_text"] = format_salary_range(item.get("salary_min"), item.get("salary_max"))
    return item if item["title"] and item["url"] and description else None


def smartrecruiters_company_jobs(
    companies: set[str] | None = None,
    max_pages: int = 1,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin jobs from permitted public SmartRecruiters feeds."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    headers = {"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"}
    for company, tenant in SMARTRECRUITERS_COMPANIES.items():
        if companies is not None and company not in companies:
            continue
        listings: list[dict[str, Any]] = []
        total = 1
        for page in range(max(1, int(max_pages))):
            offset = page * 100
            if offset >= total:
                break
            if page:
                time.sleep(delay)
            query = urllib.parse.urlencode({"limit": 100, "offset": offset, "city": "Austin"})
            request = urllib.request.Request(
                f"https://api.smartrecruiters.com/v1/companies/{tenant}/postings?{query}",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read(20_000_000).decode("utf-8", "replace"))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} SmartRecruiters search: {type(exc).__name__}")
                break
            total = int(payload.get("totalFound") or 0) if isinstance(payload, dict) else 0
            listings.extend(job for job in payload.get("content", []) if isinstance(job, dict))
        candidates = [job for job in listings if (
            title_is_candidate({"title": clean_text(job.get("name"))})
            and _fresh_iso_listing(job.get("releasedDate"), max_age_days)
        )]
        for job in candidates:
            provider_job_id = clean_text(job.get("id"))
            if not provider_job_id:
                continue
            time.sleep(delay)
            request = urllib.request.Request(
                f"https://api.smartrecruiters.com/v1/companies/{tenant}/postings/{provider_job_id}",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = json.loads(response.read(20_000_000).decode("utf-8", "replace"))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} SmartRecruiters {provider_job_id}: {type(exc).__name__}")
                continue
            item = smartrecruiters_job_item(company, detail, max_age_days=max_age_days)
            if item:
                results.append(item)
    return results, errors


def bamboohr_job_item(
    company: str,
    subdomain: str,
    job_id: str,
    detail: dict[str, Any],
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize a fresh BambooHR posting with exact Austin work metadata."""
    opening = (detail.get("result") or {}).get("jobOpening") or {}
    if not isinstance(opening, dict):
        return None
    location = opening.get("atsLocation") or opening.get("location") or {}
    if not isinstance(location, dict) or not (
        clean_text(location.get("city")).casefold() == "austin"
        and clean_text(location.get("state") or location.get("province")).casefold() in {"tx", "texas"}
        and clean_text(location.get("country")).casefold() in {"us", "usa", "united states", "united states of america"}
    ):
        return None
    posted = clean_text(opening.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    title = clean_text(opening.get("jobOpeningName"))
    description = clean_text(opening.get("description"))
    url = canonical_public_url(opening.get("jobOpeningShareUrl") or f"https://{subdomain}.bamboohr.com/careers/{job_id}")
    item = {
        "company": company,
        "title": title,
        "location": "Austin, TX",
        "url": url,
        "source": "bamboohr",
        "description": description,
        "date_posted": posted,
        "provider_job_id": clean_text(job_id),
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote position" in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(f"{clean_text(opening.get('compensation'))} {description}"))
    return item if title and description and url else None


def bamboohr_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect target roles from configured public BambooHR career feeds."""
    requested = {value.casefold() for value in companies} if companies is not None else None
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for company, subdomain in BAMBOOHR_BOARDS.items():
        if requested is not None and company.casefold() not in requested:
            continue
        list_url = f"https://{subdomain}.bamboohr.com/careers/list"
        try:
            request = urllib.request.Request(list_url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(5_000_000))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company} BambooHR list: {type(exc).__name__}")
            continue
        for listing in payload.get("result") or []:
            if not isinstance(listing, dict) or not title_is_candidate({"title": clean_text(listing.get("jobOpeningName"))}):
                continue
            location = listing.get("atsLocation") or listing.get("location") or {}
            if not isinstance(location, dict) or not (
                clean_text(location.get("city")).casefold() == "austin"
                and clean_text(location.get("state") or location.get("province")).casefold() in {"tx", "texas"}
                and clean_text(location.get("country")).casefold() in {"us", "usa", "united states", "united states of america"}
            ):
                continue
            job_id = clean_text(listing.get("id"))
            try:
                detail_url = f"https://{subdomain}.bamboohr.com/careers/{urllib.parse.quote(job_id)}/detail"
                request = urllib.request.Request(detail_url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = json.loads(response.read(8_000_000))
                item = bamboohr_job_item(company, subdomain, job_id, detail, max_age_days=max_age_days)
                if item:
                    results.append(item)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} BambooHR {job_id}: {type(exc).__name__}")
            if request_delay_seconds:
                time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def icims_search_listings(raw: str, base_url: str) -> list[dict[str, str]]:
    """Extract exact-Austin cards from a server-rendered public iCIMS board."""
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    cards = re.findall(
        r'<li\s+class=["\'][^"\']*\biCIMS_JobCardItem\b[^"\']*["\'][^>]*>(.*?)</li>',
        raw,
        re.I | re.S,
    )
    for card in cards:
        if not re.search(r"\bUS-(?:TX|Texas)-Austin\b", clean_text(card), re.I):
            continue
        link = re.search(
            r'<a[^>]+href=["\']([^"\']+/jobs/\d+/[^"\']+/job(?:\?[^"\']*)?)["\'][^>]*>.*?<h3[^>]*>(.*?)</h3>',
            card,
            re.I | re.S,
        )
        if not link:
            continue
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(f"{base_url}/", link.group(1).replace("&amp;", "&")))
        url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        if url in seen:
            continue
        seen.add(url)
        results.append({"url": url, "title": clean_text(link.group(2)), "location": "Austin, TX, US"})
    return results


def icims_job_item(company: str, raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one fresh iCIMS JSON-LD posting with an exact Austin address."""
    posting: dict[str, Any] | None = None
    for value in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            posting = candidate
            break
    if not posting:
        return None
    raw_locations = posting.get("jobLocation")
    locations = raw_locations if isinstance(raw_locations, list) else [raw_locations]
    austin_address: dict[str, Any] | None = None
    for location in locations:
        address = location.get("address") if isinstance(location, dict) else None
        if not isinstance(address, dict):
            continue
        if (
            clean_text(address.get("addressLocality")).casefold() == "austin"
            and clean_text(address.get("addressRegion")).casefold() in {"tx", "texas"}
            and clean_text(address.get("addressCountry")).casefold() in {"us", "usa", "united states"}
        ):
            austin_address = address
            break
    if not austin_address:
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(posting.get("description"))
    provider_match = re.search(r"/jobs/(\d+)(?:/|$)", urllib.parse.urlsplit(url).path, re.I)
    item = {
        "company": company,
        "title": clean_text(posting.get("title")),
        "location": "Austin, TX, US",
        "url": canonical_public_url(posting.get("url") or url),
        "source": "icims",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_match.group(1) if provider_match else "",
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in clean_text(austin_address.get("streetAddress")).casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    if not item.get("salary_text"):
        item["salary_text"] = format_salary_range(item.get("salary_min"), item.get("salary_max"))
    return item if item["title"] and item["url"] and description else None


def icims_company_jobs(
    companies: set[str] | None = None,
    max_pages: int = 2,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin roles from public iCIMS listing and detail pages."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    headers = {"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"}
    for company, base_url in ICIMS_SITES.items():
        if companies is not None and company not in companies:
            continue
        listings: list[dict[str, str]] = []
        for page in range(max(1, int(max_pages))):
            if page:
                time.sleep(delay)
            query = urllib.parse.urlencode({
                "pr": page,
                "in_iframe": 1,
                "searchRelation": "keyword_all",
                "ss": 1,
            })
            request = urllib.request.Request(f"{base_url}/jobs/search?{query}", headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read(20_000_000).decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} iCIMS search page {page + 1}: {type(exc).__name__}")
                break
            listings.extend(icims_search_listings(raw, base_url))
        seen: set[str] = set()
        for listing in listings:
            if listing["url"] in seen or not title_is_candidate(listing):
                continue
            seen.add(listing["url"])
            time.sleep(delay)
            # iCIMS' standalone route can be a JavaScript shell; the public
            # iframe representation contains the same canonical posting plus
            # complete JobPosting JSON-LD used for deterministic parsing.
            detail_endpoint = f"{listing['url']}?in_iframe=1"
            request = urllib.request.Request(detail_endpoint, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read(20_000_000).decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} iCIMS {listing['title']}: {type(exc).__name__}")
                continue
            item = icims_job_item(company, raw, listing["url"], max_age_days=max_age_days)
            if item:
                results.append(item)
    return results, errors


def pinpoint_rss_dates(raw: str) -> dict[str, str]:
    """Map Pinpoint job ids to their original publication date from RSS."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    dates: dict[str, str] = {}
    for item in root.findall("./channel/item"):
        link = clean_text(item.findtext("link"))
        match = re.search(r"/jobs/(\d+)(?:$|[/?#])", link)
        published = clean_text(item.findtext("pubDate"))
        if not match or not published:
            continue
        try:
            dates[match.group(1)] = parsedate_to_datetime(published).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            continue
    return dates


def pinpoint_job_item(
    company: str,
    job: dict[str, Any],
    date_posted: str,
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one fresh Pinpoint posting that explicitly names Austin."""
    location = job.get("location") if isinstance(job.get("location"), dict) else {}
    city = clean_text(location.get("city"))
    province = clean_text(location.get("province"))
    if city.casefold() != "austin" or province.casefold() not in {"tx", "texas"}:
        return None
    if not _fresh_iso_listing(date_posted, max_age_days):
        return None
    title = clean_text(job.get("title"))
    if not title:
        return None
    description = clean_text(" ".join(str(job.get(field) or "") for field in (
        "description", "key_responsibilities", "skills_knowledge_expertise", "benefits",
    )))
    if not description:
        return None
    job_record = job.get("job") if isinstance(job.get("job"), dict) else {}
    provider_job_id = clean_text(job_record.get("id") or job.get("id"))
    salary_min = job.get("compensation_minimum")
    salary_max = job.get("compensation_maximum")
    frequency = clean_text(job.get("compensation_frequency")).casefold()
    if frequency in {"hour", "hourly"}:
        try:
            salary_min = float(salary_min) * 2080 if salary_min is not None else None
            salary_max = float(salary_max) * 2080 if salary_max is not None else None
        except (TypeError, ValueError):
            salary_min = salary_max = None
    salary = extract_salary(description)
    if salary_min is not None or salary_max is not None:
        salary.update(
            salary_text=clean_text(job.get("compensation")) or format_salary_range(salary_min, salary_max),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_type="base",
        )
    item = {
        "company": company,
        "title": title,
        "location": f"Austin, {province}",
        "url": canonical_public_url(job.get("url")),
        "source": "pinpoint",
        "description": description,
        "date_posted": date_posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": clean_text(job.get("workplace_type")) or "onsite/hybrid",
    }
    item.update(salary)
    if not item.get("salary_text"):
        item["salary_text"] = format_salary_range(item.get("salary_min"), item.get("salary_max"))
    return item if item["url"] else None


def pinpoint_company_jobs(
    companies: set[str] | None = None,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect full public Pinpoint postings, using RSS for original dates."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for company, base_url in PINPOINT_SITES.items():
        if companies is not None and company not in companies:
            continue
        try:
            headers = {"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json, application/rss+xml"}
            rss_request = urllib.request.Request(f"{base_url}/jobs.rss", headers=headers)
            with urllib.request.urlopen(rss_request, timeout=30) as response:
                dates = pinpoint_rss_dates(response.read(15_000_000).decode("utf-8", "replace"))
            feed_request = urllib.request.Request(f"{base_url}/postings.json?page=1&per_page=100", headers=headers)
            with urllib.request.urlopen(feed_request, timeout=30) as response:
                payload = json.loads(response.read(30_000_000).decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company} Pinpoint: {type(exc).__name__}")
            continue
        for job in payload.get("data", []) if isinstance(payload, dict) else []:
            if not isinstance(job, dict):
                continue
            job_record = job.get("job") if isinstance(job.get("job"), dict) else {}
            date_posted = dates.get(clean_text(job_record.get("id")), "")
            item = pinpoint_job_item(company, job, date_posted, max_age_days=max_age_days)
            if item and title_is_candidate(item):
                results.append(item)
    return results, errors


def breezy_austin_listings(raw: str) -> list[dict[str, str]]:
    """Extract unique jobs from an official Breezy Austin, TX group.

    Breezy repeats multi-location postings under every location heading. Scoping
    extraction to the exact Austin group supplies company-site evidence without
    accidentally treating a company's general Austin presence as job evidence.
    """
    header = re.search(
        r'<h2\s+class=["\']group-header["\'][^>]*>.*?<span>\s*Austin,\s*TX\s*</span>.*?</h2>',
        raw,
        re.I | re.S,
    )
    if not header:
        return []
    following = raw[header.end():]
    next_header = re.search(r'<h2\s+class=["\']group-header["\']', following, re.I)
    block = following[:next_header.start()] if next_header else following
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for path, title in re.findall(
        r'<a\s+href=["\']([^"\']+/p/[^"\']+|/p/[^"\']+)["\'][^>]*>\s*<h2>(.*?)</h2>',
        block,
        re.I | re.S,
    ):
        url = canonical_public_url(urllib.parse.urljoin(f"{BITDEER_CAREERS_BASE}/", path))
        if url in seen:
            continue
        seen.add(url)
        results.append({"url": url, "title": clean_text(title), "location": "Austin, TX"})
    return results


def breezy_job_item(company: str, raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one fresh Breezy detail page that explicitly names Austin."""
    posting: dict[str, Any] | None = None
    for value in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            posting = candidate
            break
    if not posting:
        return None
    location_match = re.search(r'<li\s+class=["\']location["\'][^>]*>(.*?)</li>', raw, re.I | re.S)
    visible_location = clean_text(location_match.group(1)) if location_match else ""
    # Remove Breezy's untranslated remote label while preserving the actual
    # employer-supplied location text shown on the posting.
    visible_location = re.sub(r"%LABEL_[A-Z0-9_]+%", "", visible_location).strip(" -")
    if not re.search(r"\bAustin,?\s+(?:TX|Texas)\b", visible_location, re.I):
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(posting.get("description"))
    # Prefer the board link: Breezy's JobPosting URL adds a GoogleJobs tracking
    # parameter that is not part of the employer's stable job identity.
    canonical_url = canonical_public_url(url or posting.get("url"))
    provider_match = re.search(r"/p/([a-z0-9]+)", urllib.parse.urlsplit(canonical_url).path, re.I)
    item = {
        "company": company,
        "title": clean_text(posting.get("title")),
        "location": visible_location,
        "url": canonical_url,
        "source": "breezy",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_match.group(1) if provider_match else "",
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in clean_text(location_match.group(1) if location_match else "").casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    if not item.get("salary_text"):
        item["salary_text"] = format_salary_range(item.get("salary_min"), item.get("salary_max"))
    return item if item["title"] and item["url"] and description else None


def bitdeer_austin_jobs(request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect current Austin-explicit Bitdeer engineering roles from Breezy."""
    request = urllib.request.Request(
        f"{BITDEER_CAREERS_BASE}/",
        headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(20_000_000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
        return [], [f"Bitdeer board: {type(exc).__name__}"]
    candidates = [listing for listing in breezy_austin_listings(raw) if title_is_candidate(listing)]
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    for listing in candidates:
        time.sleep(delay)
        try:
            detail_request = urllib.request.Request(
                listing["url"],
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(detail_request, timeout=30) as response:
                detail = response.read(15_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Bitdeer {listing['title']}: {type(exc).__name__}")
            continue
        item = breezy_job_item("Bitdeer (NASDAQ: BTDR)", detail, listing["url"], max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, errors


def successfactors_search_listings(raw: str, base_url: str) -> list[dict[str, str]]:
    """Parse canonical jobs from a server-rendered SAP SuccessFactors table."""
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in re.findall(r'<tr\s+class=["\']data-row["\'][^>]*>(.*?)</tr>', raw, re.I | re.S):
        link = re.search(r'<a[^>]+href=["\']([^"\']+/job/[^"\']+|/job/[^"\']+)["\'][^>]*class=["\']jobTitle-link["\'][^>]*>(.*?)</a>', row, re.I | re.S)
        location = re.search(r'<span\s+class=["\']jobLocation["\'][^>]*>(.*?)</span>', row, re.I | re.S)
        posted = re.search(r'<span\s+class=["\']jobDate(?:\s+visible-phone)?["\'][^>]*>(.*?)</span>', row, re.I | re.S)
        if not link or not location:
            continue
        url = canonical_public_url(urllib.parse.urljoin(f"{base_url}/", link.group(1).replace("&amp;", "&")))
        if url in seen:
            continue
        seen.add(url)
        results.append({
            "url": url,
            "title": clean_text(link.group(2)),
            "location": clean_text(location.group(1)),
            "date_posted": clean_text(posted.group(1)) if posted else "",
        })
    # Newer SuccessFactors themes render search results as repeated job tiles
    # instead of table rows. Parse the desktop fields once and dedupe the
    # tablet/mobile copies of the same canonical link.
    tiles = re.findall(r'<li\s+class=["\'][^"\']*\bjob-tile\b[^"\']*["\'][^>]*>(.*?)(?=<li\s+class=["\'][^"\']*\bjob-tile\b|</ul>|$)', raw, re.I | re.S)
    for tile in tiles:
        link = re.search(r'<a[^>]+class=["\'][^"\']*jobTitle-link[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', tile, re.I | re.S)
        if not link:
            # Some themes place href before class.
            link = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]+class=["\'][^"\']*jobTitle-link[^"\']*["\'][^>]*>(.*?)</a>', tile, re.I | re.S)
        location = re.search(r'-desktop-section-location-value["\'][^>]*>(.*?)</div>', tile, re.I | re.S)
        posted = re.search(r'-desktop-section-date-value["\'][^>]*>(.*?)</div>', tile, re.I | re.S)
        if not link or not location:
            continue
        url = canonical_public_url(urllib.parse.urljoin(f"{base_url}/", link.group(1).replace("&amp;", "&")))
        if url in seen:
            continue
        seen.add(url)
        results.append({
            "url": url,
            "title": clean_text(link.group(2)),
            "location": clean_text(location.group(1)),
            "date_posted": clean_text(posted.group(1)) if posted else "",
        })
    return results


def _successfactors_date(value: Any) -> str:
    raw = clean_text(value)
    for pattern in ("%a %b %d %H:%M:%S UTC %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def _successfactors_itemprop(raw: str, prop: str) -> str:
    """Read a microdata value without depending on HTML attribute order."""
    tag = re.search(
        rf'<meta\b(?=[^>]*\bitemprop=["\']{re.escape(prop)}["\'])[^>]*>',
        raw,
        re.I,
    )
    if not tag:
        return ""
    content = re.search(r'\bcontent=["\']([^"\']*)', tag.group(0), re.I)
    return clean_text(content.group(1) if content else "")


def _successfactors_locations(raw: str) -> list[tuple[str, str, str]]:
    """Return every structured SuccessFactors job location, in page order."""
    locations: list[tuple[str, str, str]] = []
    for address in re.findall(
        r'<span\b(?=[^>]*\bitemprop=["\']address["\'])[^>]*>(.*?)</span>',
        raw,
        re.I | re.S,
    ):
        location = tuple(_successfactors_itemprop(address, prop) for prop in (
            "addressLocality", "addressRegion", "addressCountry",
        ))
        if any(location) and location not in locations:
            locations.append(location)
    if not locations:
        legacy = tuple(_successfactors_itemprop(raw, prop) for prop in (
            "addressLocality", "addressRegion", "addressCountry",
        ))
        if any(legacy):
            locations.append(legacy)
    return locations


def _successfactors_description(raw: str) -> str:
    """Extract all text below the nested microdata description span."""
    class DescriptionParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.depth = 0
            self.parts: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = dict(attrs)
            if tag.casefold() == "span" and values.get("itemprop", "").casefold() == "description":
                self.depth = 1
            elif self.depth and tag.casefold() == "span":
                self.depth += 1
            elif self.depth and tag.casefold() == "br":
                self.parts.append(" ")

        def handle_endtag(self, tag: str) -> None:
            if self.depth and tag.casefold() == "span":
                self.depth -= 1

        def handle_data(self, data: str) -> None:
            if self.depth:
                self.parts.append(data)

    parser = DescriptionParser()
    parser.feed(raw)
    return clean_text(" ".join(parser.parts))


def successfactors_job_item(company: str, raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a fresh, Austin-explicit SAP SuccessFactors detail page."""
    title_match = re.search(r'<h1[^>]+id=["\']job-title["\'][^>]*>(.*?)</h1>', raw, re.I | re.S)
    if not title_match:
        title_match = re.search(
            r'<h1\b[^>]*>.*?<span\b(?=[^>]*\bitemprop=["\']title["\'])[^>]*>(.*?)</span>.*?</h1>',
            raw,
            re.I | re.S,
        )
    locations = _successfactors_locations(raw)
    austin_location = next((location for location in locations if (
        location[0].casefold() == "austin" and location[1].casefold() in {"tx", "texas"}
    )), None)
    if not austin_location:
        return None
    city, region, country = austin_location
    posted = _successfactors_date(_successfactors_itemprop(raw, "datePosted"))
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = _successfactors_description(raw)
    provider_match = re.search(r"/(\d+)/?$", urllib.parse.urlsplit(url).path)
    item = {
        "company": company,
        "title": clean_text(title_match.group(1) if title_match else ""),
        "location": ", ".join(value for value in (city, region, country) if value),
        "url": canonical_public_url(url),
        "source": "successfactors",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_match.group(1) if provider_match else "",
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote position: yes" in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    if re.search(r"Pay Frequency:\s*Monthly", description, re.I):
        low, high = item.get("salary_min"), item.get("salary_max")
        if low is None or high is None:
            monthly = re.search(
                r"Salary Range:\s*\$\s*([\d,]+(?:\.\d+)?)\s*(?:-|–|—|to)\s*\$\s*([\d,]+(?:\.\d+)?)",
                description,
                re.I,
            )
            if monthly:
                low, high = (float(value.replace(",", "")) for value in monthly.groups())
        if low is not None and high is not None and float(high) < 20_000:
            item["salary_min"] = float(low) * 12
            item["salary_max"] = float(high) * 12
            item["salary_text"] = f"{format_salary_range(item['salary_min'], item['salary_max'])} annualized from monthly range"
            item["salary_type"] = "base"
    if company.casefold() == "ey":
        # EY publishes multiple regional ranges in one detail. Austin belongs
        # to its "all other US offices" band, not the first NYC/DC/CA band.
        austin_pay = re.search(
            r"All other offices[^$]{0,120}\$\s*([\d,]+)\s*(?:-|–|—|to)\s*\$\s*([\d,]+)",
            description,
            re.I,
        )
        if austin_pay:
            low, high = sorted(float(value.replace(",", "")) for value in austin_pay.groups())
            item.update({
                "salary_text": f"{format_salary_range(low, high)} (Austin: all other US offices)",
                "salary_min": low, "salary_max": high, "salary_type": "base",
            })
    return item if item["title"] and item["url"] and description else None


def successfactors_company_jobs(
    companies: set[str] | None = None,
    max_pages: int = 2,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin roles from configured public SuccessFactors sites."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    headers = {"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"}
    for company, config in SUCCESSFACTORS_SITES.items():
        if companies is not None and company not in companies:
            continue
        base_url = str(config["base_url"])
        board_url = str(config["board_url"])
        listings: dict[str, dict[str, str]] = {}
        for page in range(max(1, int(max_pages))):
            if page:
                time.sleep(delay)
            parsed = urllib.parse.urlsplit(board_url)
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            query["startrow"] = str(page * 25)
            endpoint = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))
            try:
                request = urllib.request.Request(endpoint, headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read(20_000_000).decode("utf-8", "replace")
                page_items = successfactors_search_listings(raw, base_url)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} SuccessFactors search page {page + 1}: {type(exc).__name__}")
                break
            before = len(listings)
            for listing in page_items:
                if title_is_candidate(listing):
                    listings[listing["url"]] = listing
            if not page_items or len(listings) == before:
                break
        for listing in listings.values():
            time.sleep(delay)
            try:
                request = urllib.request.Request(listing["url"], headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read(20_000_000).decode("utf-8", "replace")
                item = successfactors_job_item(company, raw, listing["url"], max_age_days=max_age_days)
                if item:
                    results.append(item)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} SuccessFactors {listing['title']}: {type(exc).__name__}")
    return results, errors


def celestica_austin_jobs(max_pages: int = 2, request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Audit Celestica's exact-Austin SuccessFactors pages with paced details."""
    errors: list[str] = []
    listings: dict[str, dict[str, str]] = {}
    delay = max(2.0, float(request_delay_seconds))
    for page in range(max(1, max_pages)):
        if page:
            time.sleep(delay)
        path = "" if page == 0 else f"{page * 25}/"
        endpoint = f"{CELESTICA_AUSTIN_BOARD}{path}?q=&sortColumn=referencedate&sortDirection=desc"
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Celestica search page {page + 1}: {type(exc).__name__}")
            break
        for listing in successfactors_search_listings(raw, CELESTICA_CAREERS_BASE):
            if re.search(r"\bAustin,?\s+(?:TX|Texas)\b", listing["location"], re.I) and title_is_candidate(listing):
                listings[listing["url"]] = listing
    results: list[dict[str, Any]] = []
    for listing in listings.values():
        time.sleep(delay)
        try:
            request = urllib.request.Request(listing["url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Celestica {listing['title']}: {type(exc).__name__}")
            continue
        item = successfactors_job_item("Celestica", raw, listing["url"], max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, errors


def rwe_austin_jobs(max_pages: int = 8, request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Audit RWE's exact-Austin SuccessFactors pages with paced details."""
    errors: list[str] = []
    listings: dict[str, dict[str, str]] = {}
    delay = max(2.0, float(request_delay_seconds))
    for page in range(max(1, max_pages)):
        if page:
            time.sleep(delay)
        path = "" if page == 0 else f"{page * 25}/"
        endpoint = f"{RWE_AUSTIN_BOARD}{path}?q=&sortColumn=referencedate&sortDirection=desc"
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"RWE search page {page + 1}: {type(exc).__name__}")
            break
        page_listings = successfactors_search_listings(raw, RWE_CAREERS_BASE)
        for listing in page_listings:
            if re.search(r"\bAustin,?\s+(?:TX|Texas)\b", listing["location"], re.I) and title_is_candidate(listing):
                listings[listing["url"]] = listing
        if len(page_listings) < 25:
            break
    results: list[dict[str, Any]] = []
    for listing in listings.values():
        time.sleep(delay)
        try:
            request = urllib.request.Request(listing["url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"RWE {listing['title']}: {type(exc).__name__}")
            continue
        item = successfactors_job_item("RWE", raw, listing["url"], max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, errors


def exacta_austin_jobs(request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh senior software roles from Exacta's public CDI board."""
    delay = max(2.0, float(request_delay_seconds))
    errors: list[str] = []
    endpoint = f"{EXACTA_AUSTIN_BOARD}?q=&sortColumn=referencedate&sortDirection=desc"
    try:
        request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(20_000_000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
        return [], [f"Exacta Systems search: {type(exc).__name__}"]
    listings = [
        listing for listing in successfactors_search_listings(raw, EXACTA_CAREERS_BASE)
        if re.search(r"\bAustin,?\s+(?:TX|Texas)\b", listing["location"], re.I)
        and title_is_candidate(listing)
    ]
    results: list[dict[str, Any]] = []
    for listing in listings:
        time.sleep(delay)
        try:
            request = urllib.request.Request(listing["url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Exacta Systems {listing['title']}: {type(exc).__name__}")
            continue
        item = successfactors_job_item("Exacta Systems", raw, listing["url"], max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, errors


def kpmg_search_listings(raw: str) -> list[dict[str, str]]:
    """Parse canonical Austin-tagged listings from KPMG's public search response."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    postings = payload.get("postings") if isinstance(payload, dict) else {}
    fragment = postings.get("jobs") if isinstance(postings, dict) else ""
    if not isinstance(fragment, str):
        return []

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'<a\s+href=["\'](?P<path>/jobdetail/\?jobId=(?P<id>\d+))["\'][^>]*>'
        r'.*?<div\s+class=["\']h4\s+mb-4["\'][^>]*>(?P<title>.*?)</div>'
        r'.*?<div\s+class=["\'][^"\']*\blist-view\b[^"\']*["\'][^>]*>'
        r'.*?<div\s+class=["\']h5\s+text-dark-grey["\'][^>]*>.*?</div>\s*'
        r'<div\s+class=["\']text-xs\s+text-dark-grey["\'][^>]*>(?P<location>.*?)</div>',
        re.I | re.S,
    )
    for match in pattern.finditer(fragment):
        location = clean_text(match.group("location"))
        if not re.search(r"\bAustin,?\s+(?:TX|Texas)\b", location, re.I):
            continue
        url = f"{KPMG_CAREERS_BASE}/jobdetail/?jobId={match.group('id')}"
        if url in seen:
            continue
        seen.add(url)
        results.append({
            "provider_job_id": match.group("id"),
            "title": clean_text(match.group("title")),
            "location": location,
            "url": url,
        })
    return results


def _kpmg_date(value: Any) -> str:
    raw = clean_text(value)
    for pattern in ("%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def kpmg_job_item(raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one fresh KPMG detail whose own location list names Austin."""
    title = re.search(r'<h1\b[^>]*\bid=["\']jd-title["\'][^>]*>(.*?)</h1>', raw, re.I | re.S)
    location = re.search(r'<p\b[^>]*\bid=["\']jd-location["\'][^>]*>(.*?)</p>', raw, re.I | re.S)
    posted = re.search(r'"datePosted"\s*:\s*"([^"]+)', raw, re.I)
    description = re.search(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bjob-description\b[^"\']*["\'][^>]*>'
        r'(.*?)</div>\s*<div\b[^>]*\bclass=["\'][^"\']*\bpb-4\b[^"\']*["\'][^>]*>',
        raw,
        re.I | re.S,
    )
    title_text = clean_text(title.group(1) if title else "")
    location_text = clean_text(location.group(1) if location else "")
    posted_date = _kpmg_date(posted.group(1) if posted else "")
    description_text = clean_text(description.group(1) if description else "")
    if (
        not title_text
        or not re.search(r"\bAustin,?\s+(?:TX|Texas)\b", location_text, re.I)
        or not _fresh_iso_listing(posted_date, max_age_days)
        or not description_text
    ):
        return None
    provider_match = re.search(r"[?&]jobId=(\d+)", url, re.I)
    item = {
        "company": "KPMG US",
        "title": title_text,
        "location": location_text,
        "url": f"{KPMG_CAREERS_BASE}/jobdetail/?jobId={provider_match.group(1)}" if provider_match else canonical_public_url(url),
        "source": "kpmg",
        "description": description_text,
        "date_posted": posted_date,
        "provider_job_id": provider_match.group(1) if provider_match else "",
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in location_text.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description_text))
    california_range = re.search(
        r"California\s+Salary\s+Range:\s*\$\s*([\d,]+)\s*(?:-|–|—|to)\s*\$\s*([\d,]+)",
        description_text,
        re.I,
    )
    if california_range:
        low, high = (float(value.replace(",", "")) for value in california_range.groups())
        # Texas did not have a listed local range at collection time. Retain
        # the disclosed context without letting a California range drive rank.
        item.update({
            "salary_text": f"California Salary Range: ${low:,.0f} - ${high:,.0f}",
            "salary_min": None,
            "salary_max": None,
            "salary_type": "unknown",
        })
    return item


def kpmg_austin_jobs(
    max_pages: int = 12,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect KPMG's fresh Austin technical roles from its public search feed."""
    delay = max(2.0, float(request_delay_seconds))
    listings: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for page in range(1, max(1, min(int(max_pages), 12)) + 1):
        if page > 1:
            time.sleep(delay)
        params = urllib.parse.urlencode({
            "ajax": "1",
            "location-filter": "Austin, TX|",
            "spage": page,
            "order": "",
        })
        try:
            request = urllib.request.Request(
                f"{KPMG_JOBS_API}?{params}",
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(5_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"KPMG US search page {page}: {type(exc).__name__}")
            break
        page_items = kpmg_search_listings(raw)
        for listing in page_items:
            if title_is_candidate(listing):
                listings[listing["url"]] = listing
        try:
            page_size = int((json.loads(raw).get("postings") or {}).get("size") or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            page_size = 0
        if page_size < 12:
            break

    results: list[dict[str, Any]] = []
    for listing in listings.values():
        time.sleep(delay)
        try:
            request = urllib.request.Request(
                listing["url"],
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"KPMG US {listing['title']}: {type(exc).__name__}")
            continue
        item = kpmg_job_item(raw, listing["url"], max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, errors


def hhsc_austin_jobs(request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect targeted Austin software roles from HHSC's public portal."""
    queries = (
        "Senior Java", "Senior Cloud Software", "Senior Database",
        "Security Engineering Manager", "Senior .NET", "Staff Software",
    )
    delay = max(2.0, float(request_delay_seconds))
    listings: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for index, query in enumerate(queries):
        if index:
            time.sleep(delay)
        params = urllib.parse.urlencode({"createNewAlert": "false", "q": query, "locationsearch": "Austin"})
        endpoint = f"{HHSC_SEARCH_BASE}?{params}"
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"HHSC search {query}: {type(exc).__name__}")
            continue
        for listing in successfactors_search_listings(raw, HHSC_CAREERS_BASE):
            if re.search(r"\bAustin,?\s+(?:TX|Texas)\b", listing["location"], re.I) and title_is_candidate(listing):
                listings[listing["url"]] = listing
    results: list[dict[str, Any]] = []
    for listing in listings.values():
        time.sleep(delay)
        try:
            request = urllib.request.Request(listing["url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"HHSC {listing['title']}: {type(exc).__name__}")
            continue
        item = successfactors_job_item("Texas Health and Human Services", raw, listing["url"], max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, errors


def ey_austin_jobs(
    max_pages: int = 4,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin-explicit engineering roles from EY SuccessFactors."""
    delay = max(2.0, float(request_delay_seconds))
    listings: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for page in range(max(1, min(int(max_pages), 4))):
        if page:
            time.sleep(delay)
        params = {
            "q": "software",
            "locationsearch": "Austin, TX",
            "sortColumn": "referencedate",
            "sortDirection": "desc",
        }
        if page:
            params["startrow"] = page * 25
        endpoint = f"{EY_SEARCH_BASE}?{urllib.parse.urlencode(params)}"
        try:
            request = urllib.request.Request(
                endpoint,
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(30_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"EY search page {page + 1}: {type(exc).__name__}")
            break
        page_items = successfactors_search_listings(raw, EY_CAREERS_BASE)
        for listing in page_items:
            if title_is_candidate(listing):
                listings[listing["url"]] = listing
        if len(page_items) < 25:
            break

    results: list[dict[str, Any]] = []
    for listing in listings.values():
        time.sleep(delay)
        try:
            request = urllib.request.Request(
                listing["url"],
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(30_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"EY {listing['title']}: {type(exc).__name__}")
            continue
        item = successfactors_job_item("EY", raw, listing["url"], max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, errors


def revolutpeople_job_item(
    company: str,
    tenant: str,
    posting: dict[str, Any],
    austin_office: str = "Austin",
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one public Revolut People posting with verified Austin-office evidence."""
    locations = posting.get("locations") or []
    has_austin = any(
        isinstance(value, dict)
        and clean_text(value.get("name")).casefold() == austin_office.casefold()
        and clean_text((value.get("country") or {}).get("name")).casefold() in {"united states", "us", "usa"}
        for value in locations
    )
    if not has_austin:
        return None
    posted = clean_text(posting.get("creation_date_time"))[:10]
    if not _fresh_iso_listing(posted, max_age_days=max_age_days):
        return None
    provider_job_id = clean_text(posting.get("id"))
    if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", provider_job_id, re.I):
        return None
    description = clean_text(posting.get("description"))
    title = clean_text(posting.get("title"))
    item = {
        "company": company,
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple locations",
        "url": f"https://revolutpeople.com/{urllib.parse.quote(tenant, safe='')}/public/careers/position/{provider_job_id}",
        "source": "revolutpeople",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if any(
            isinstance(value, dict)
            and clean_text(value.get("name")).casefold() == austin_office.casefold()
            and clean_text(value.get("type")).casefold() == "remote"
            for value in locations
        ) else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if title and description else None


def revolutpeople_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read fresh Austin-explicit roles from configured public Revolut People tenants."""
    requested = {value.casefold() for value in companies} if companies is not None else None
    delay = max(2.0, float(request_delay_seconds))
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for company, config in REVOLUTPEOPLE_SITES.items():
        if requested is not None and company.casefold() not in requested:
            continue
        tenant = clean_text(config.get("tenant"))
        austin_office = clean_text(config.get("austin_office")) or "Austin"
        base = f"https://revolutpeople.com/api/{urllib.parse.quote(tenant, safe='')}/external/v2/postings"
        try:
            request = urllib.request.Request(base, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                listings = json.loads(response.read(10_000_000))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        if not isinstance(listings, list):
            errors.append(f"{company}: invalid listing payload")
            continue
        candidates = [
            listing for listing in listings
            if isinstance(listing, dict)
            and title_is_candidate(listing)
            and any(
                isinstance(value, dict)
                and clean_text(value.get("name")).casefold() == austin_office.casefold()
                and clean_text((value.get("country") or {}).get("name")).casefold() in {"united states", "us", "usa"}
                for value in listing.get("locations") or []
            )
        ]
        for listing in candidates:
            time.sleep(delay)
            provider_job_id = clean_text(listing.get("id"))
            endpoint = f"{base}/{urllib.parse.quote(provider_job_id, safe='')}"
            try:
                request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = json.loads(response.read(10_000_000))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} {clean_text(listing.get('title'))}: {type(exc).__name__}")
                continue
            if not isinstance(detail, dict):
                continue
            item = revolutpeople_job_item(company, tenant, detail, austin_office, max_age_days=max_age_days)
            if item:
                results.append(item)
    return results, errors


def avionte_job_item(
    company: str,
    config: dict[str, str],
    listing: dict[str, Any],
    detail: dict[str, Any],
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one fresh, exact-Austin posting from a public Avionté board."""
    location = clean_text(listing.get("location"))
    if not re.search(r"\bAustin,?\s+(?:TX|Texas)\b", location, re.I):
        return None
    posted = clean_text(listing.get("postDateUtc"))[:10]
    if not _fresh_iso_listing(posted, max_age_days=max_age_days):
        return None
    title = clean_text(listing.get("jobTitle"))
    if not title_is_candidate({"title": title}):
        return None
    provider_job_id = clean_text(listing.get("jobPostIdEnc"))
    public_url = clean_text(config.get("public_url"))
    if not provider_job_id or not public_url:
        return None
    description = clean_text(detail.get("description"))
    # Avionté appends a JSON-LD copy of the posting to the visible HTML. Keep
    # the complete human-facing description without storing that duplicate.
    description = description.split(' {"@context"', 1)[0].strip()
    if not description:
        return None
    item = {
        "company": company,
        "title": title,
        "location": location,
        "url": f"{public_url}?{urllib.parse.urlencode({'rpid': provider_job_id})}",
        "source": "avionte",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in description.casefold() and "hybrid" not in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    if not item.get("salary_max"):
        hourly = re.search(
            r"\b(?:rate|pay(?:\s+rate)?)\s*:?\s*\$\s*(\d{1,3}(?:\.\d{1,2})?)\s*(?:/|per\s+)(?:hr|hour)\b",
            description,
            re.I,
        )
        if hourly:
            rate = float(hourly.group(1))
            annual = rate * 2080
            item.update({
                "salary_text": f"${rate:,.2f}/hour (${annual:,.0f} annualized)",
                "salary_min": annual,
                "salary_max": annual,
                "salary_type": "base",
            })
    return item


def avionte_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read fresh exact-Austin roles from configured public Avionté boards."""
    requested = {value.casefold() for value in companies} if companies is not None else None
    delay = max(2.0, float(request_delay_seconds))
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for company, config in AVIONTE_BOARDS.items():
        if requested is not None and company.casefold() not in requested:
            continue
        host = clean_text(config.get("host")).rstrip("/")
        build_id = clean_text(config.get("build_id"))
        board_id = clean_text(config.get("job_board_id"))
        headers = {
            "User-Agent": "EliOpportunityQueue/1.0",
            "Accept": "application/json",
            "X-Compas-Careers-BuildIdEnc": build_id,
            "X-Compas-Careers-JobBoardIdEnc": board_id,
        }
        endpoint = f"{host}/sonar/v2/jobBoard/{urllib.parse.quote(build_id, safe='')}/{urllib.parse.quote(board_id, safe='')}"
        try:
            request = urllib.request.Request(endpoint, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(20_000_000))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        job_posts = payload.get("jobPosts") if isinstance(payload, dict) else None
        listings = list(job_posts.values()) if isinstance(job_posts, dict) else job_posts
        if not isinstance(listings, list):
            errors.append(f"{company}: invalid listing payload")
            continue
        candidates = [
            listing for listing in listings
            if isinstance(listing, dict)
            and title_is_candidate({"title": clean_text(listing.get("jobTitle"))})
            and re.search(r"\bAustin,?\s+(?:TX|Texas)\b", clean_text(listing.get("location")), re.I)
            and _fresh_iso_listing(listing.get("postDateUtc"), max_age_days=max_age_days)
        ]
        for listing in candidates:
            time.sleep(delay)
            provider_job_id = clean_text(listing.get("jobPostIdEnc"))
            detail_url = f"{host}/sonar/v2/jobBoard/jobPost/{urllib.parse.quote(provider_job_id, safe='')}/description"
            try:
                request = urllib.request.Request(detail_url, headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = json.loads(response.read(5_000_000))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} {clean_text(listing.get('jobTitle'))}: {type(exc).__name__}")
                continue
            if not isinstance(detail, dict):
                continue
            item = avionte_job_item(company, config, listing, detail, max_age_days=max_age_days)
            if item:
                results.append(item)
    return results, errors


def ashby_job_item(company: str, job: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one record from Ashby's documented public job-board surface."""
    secondary = job.get("secondaryLocations") or []
    primary_label = clean_text(job.get("location"))
    primary_address = job.get("address") or {}
    primary_postal = primary_address.get("postalAddress") or {} if isinstance(primary_address, dict) else {}
    primary_city = clean_text(primary_postal.get("addressLocality")) if isinstance(primary_postal, dict) else ""
    primary_region = clean_text(primary_postal.get("addressRegion")) if isinstance(primary_postal, dict) else ""
    primary_country = clean_text(primary_postal.get("addressCountry")) if isinstance(primary_postal, dict) else ""
    original_primary_label = primary_label
    if primary_city and primary_region and (
        not primary_label
        or primary_label.casefold() == primary_city.casefold()
        or re.search(rf"\b{re.escape(primary_city)}\b", primary_label, re.I)
    ):
        primary_label = ", ".join(dict.fromkeys(
            part for part in (primary_city, primary_region, primary_country) if part
        ))
        if "remote" in original_primary_label.casefold():
            primary_label += " (Remote)"
    location_parts = [primary_label]
    for value in secondary if isinstance(secondary, list) else []:
        if isinstance(value, dict):
            label = clean_text(value.get("location") or value.get("name") or value.get("title"))
            original_label = label
            address = value.get("address") or {}
            postal = address.get("postalAddress") or {} if isinstance(address, dict) else {}
            city = clean_text(postal.get("addressLocality")) if isinstance(postal, dict) else ""
            region = clean_text(postal.get("addressRegion")) if isinstance(postal, dict) else ""
            country = clean_text(postal.get("addressCountry")) if isinstance(postal, dict) else ""
            if city and region and (
                label.casefold() == city.casefold()
                or re.search(rf"\b{re.escape(city)}\b", label, re.I)
            ):
                label = ", ".join(dict.fromkeys(part for part in (city, region, country) if part))
                if "remote" in original_label.casefold():
                    label += " (Remote)"
            location_parts.append(label)
        else:
            location_parts.append(clean_text(value))
    location = " / ".join(dict.fromkeys(value for value in location_parts if value))
    description = clean_text(job.get("descriptionPlain") or job.get("descriptionHtml"))
    workplace_type = clean_text(job.get("workplaceType")).casefold()
    arrangement = "remote" if "remote" in workplace_type or (not workplace_type and job.get("isRemote")) else "onsite/hybrid"
    if arrangement == "remote" and location.casefold() in {"united states", "us", "usa"}:
        location = "Remote - United States"
    item = {
        "company": company,
        "title": clean_text(job.get("title")),
        "location": location,
        "url": clean_text(job.get("jobUrl")),
        "source": "ashby",
        "description": description,
        "date_posted": str(job.get("publishedAt") or "")[:10] or None,
        "easy_apply": 0,
        "work_arrangement": arrangement,
    }
    item.update(extract_salary(description))
    compensation = job.get("compensation") or {}
    if not item.get("salary_max") and isinstance(compensation, dict):
        for component in compensation.get("summaryComponents") or []:
            if not isinstance(component, dict):
                continue
            if clean_text(component.get("compensationType")).casefold() != "salary":
                continue
            if clean_text(component.get("currencyCode")).upper() != "USD":
                continue
            if "YEAR" not in clean_text(component.get("interval")).upper():
                continue
            try:
                low, high = sorted((float(component.get("minValue")), float(component.get("maxValue"))))
            except (TypeError, ValueError):
                continue
            item.update({
                "salary_text": clean_text(compensation.get("scrapeableCompensationSalarySummary")) or f"${low:,.0f} - ${high:,.0f}",
                "salary_min": low,
                "salary_max": high,
                "salary_type": "base",
            })
            break
    if not item.get("salary_max"):
        pay = re.search(r"\bUS:\s*\$\s*(\d{5,6})\s*(?:-|–|—|to)\s*\$?\s*(\d{5,6})\b", description, re.I)
        if pay:
            low, high = sorted(float(value) for value in pay.groups())
            item.update({
                "salary_text": f"${low:,.0f} - ${high:,.0f}",
                "salary_min": low,
                "salary_max": high,
                "salary_type": "base",
            })
    # Some remote-US postings (including Scribd Flex) publish separate
    # California and non-California bands with explanatory text between each
    # bound. Austin belongs to the latter, so prefer that explicitly scoped
    # band over a generic parser's first (California) match.
    pay = re.search(
        r"\b(?:United States|US)\s*,?\s*outside of California.{0,600}?"
        r"\$\s*([\d,]{5,7}).{0,600}?(?:to|[-–—])\s*\$\s*([\d,]{5,7})\b",
        description,
        re.I,
    )
    if pay:
        low, high = sorted(float(value.replace(",", "")) for value in pay.groups())
        item.update({
            "salary_text": f"${low:,.0f} - ${high:,.0f}",
            "salary_min": low,
            "salary_max": high,
            "salary_type": "base",
        })
    return item if item["title"] and item["url"] else None


def ashby_posting_has_austin(job: dict[str, Any]) -> bool:
    """Require Austin, Texas in an Ashby posting's explicit work locations."""
    locations = [clean_text(job.get("location"))]
    primary_address = job.get("address") or {}
    primary_postal = primary_address.get("postalAddress") or {} if isinstance(primary_address, dict) else {}
    if isinstance(primary_postal, dict):
        locations.append(", ".join(part for part in (
            clean_text(primary_postal.get("addressLocality")),
            clean_text(primary_postal.get("addressRegion")),
            clean_text(primary_postal.get("addressCountry")),
        ) if part))
    for value in job.get("secondaryLocations") or []:
        if isinstance(value, dict):
            label = clean_text(value.get("location") or value.get("name") or value.get("title"))
            address = value.get("address") or {}
            postal = address.get("postalAddress") or {} if isinstance(address, dict) else {}
            city = clean_text(postal.get("addressLocality")) if isinstance(postal, dict) else ""
            region = clean_text(postal.get("addressRegion")) if isinstance(postal, dict) else ""
            country = clean_text(postal.get("addressCountry")) if isinstance(postal, dict) else ""
            locations.append(", ".join(part for part in (city, region, country) if part) or label)
        else:
            locations.append(clean_text(value))
    return any(re.search(r"\bAustin,?\s+(?:TX|Texas)\b", value, re.I) for value in locations)


def snowflake_austin_jobs(max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin-explicit target roles from Snowflake's public Ashby board."""
    endpoint = f"https://api.ashbyhq.com/posting-api/job-board/{SNOWFLAKE_ASHBY_BOARD}"
    request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read(25_000_000))
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
        return [], [f"Snowflake: {type(exc).__name__}"]
    results: list[dict[str, Any]] = []
    for job in payload.get("jobs") or []:
        if not isinstance(job, dict) or not job.get("isListed", True):
            continue
        if not _fresh_iso_listing(job.get("publishedAt"), max_age_days):
            continue
        if not title_is_candidate({"title": clean_text(job.get("title"))}) or not ashby_posting_has_austin(job):
            continue
        item = ashby_job_item("Snowflake", job)
        if item:
            results.append(item)
    return results, []


def ashby_board_endpoint(board: str) -> str:
    """Build a valid public Ashby endpoint for board names containing spaces."""
    return f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(str(board), safe='')}"


def ashby_company_jobs(companies: set[str] | None = None, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Read fresh postings from configured public Ashby job-board feeds."""
    requested = {value.casefold() for value in companies} if companies is not None else None
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for company, board in ASHBY_BOARDS.items():
        if requested is not None and company.casefold() not in requested:
            continue
        endpoint = f"{ashby_board_endpoint(board)}?includeCompensation=true"
        request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read(20_000_000))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        for job in payload.get("jobs", []):
            if not isinstance(job, dict) or not job.get("isListed", True) or not _fresh_iso_listing(job.get("publishedAt"), max_age_days):
                continue
            if company in {"Ashby", "PAR Technology", "Scribd, Inc.", "Crusoe", "Saronic Technologies", "Zello", "Edlink", "CompanyCam", "G2", "Higharc", "Hello Patient", "Partly", "MaintainX", "Hopper", "Neurophos"} and not ashby_posting_has_austin(job):
                continue
            item = ashby_job_item(company, job)
            if item:
                results.append(item)
    return results, errors


def google_search_paths(raw: str) -> list[str]:
    """Extract canonical detail paths from a server-rendered Google Careers page."""
    return list(dict.fromkeys(re.findall(r'href="(jobs/results/\d+-[^"?]+)', raw, re.I)))


def google_job_item(external_path: str, raw: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize Google's public ds:0 detail payload without using an account."""
    match = re.search(r"key:\s*['\"]ds:0['\"].*?data:(.*?),\s*sideChannel:", raw, re.S)
    if not match:
        return None
    try:
        record = json.loads(match.group(1))[0]
        title = clean_text(record[1])
        locations = [clean_text(value[0]) for value in record[9] if isinstance(value, list) and value]
        timestamp = float(record[14][0])
        posted = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not any(re.search(r"\bAustin,?\s+TX\b", value, re.I) for value in locations):
        return None
    age = (datetime.now(timezone.utc).date() - posted.date()).days
    if age < 0 or age > max_age_days:
        return None
    fragments: list[str] = []
    for index in (4, 10, 3, 19):
        value = record[index] if index < len(record) else None
        if isinstance(value, list) and len(value) > 1 and value[1]:
            fragments.append(str(value[1]))
    description = clean_text(" ".join(fragments))
    item = {
        "company": "Google",
        "title": title,
        "location": "Austin, TX",
        "url": urllib.parse.urljoin(GOOGLE_CAREERS_ROOT, external_path),
        "source": "google",
        "description": description,
        "date_posted": posted.date().isoformat(),
        "easy_apply": 0,
        "work_arrangement": "remote" if any("remote" in value.casefold() for value in locations) else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    if not item.get("salary_max"):
        pay = re.search(r"\bUS:\s*\$\s*(\d{5,6})\s*(?:-|–|—|to)\s*\$?\s*(\d{5,6})\b", description, re.I)
        if pay:
            low, high = sorted(float(value) for value in pay.groups())
            item.update({
                "salary_text": f"${low:,.0f} - ${high:,.0f}",
                "salary_min": low,
                "salary_max": high,
                "salary_type": "base",
            })
    return item if item["title"] and item["url"] else None


def google_austin_jobs(max_pages: int = 3, request_delay_seconds: float = 2.0) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh, Austin-explicit target roles from Google Careers' public pages."""
    errors: list[str] = []
    paths: dict[str, str] = {}
    for query in (
        "software engineer", "software developer", "engineering manager", "software development manager",
        "site reliability engineer", "platform engineer", "data engineer", "security engineer",
        "machine learning engineer", "engineer ii", "engineer iii", "technical lead",
    ):
        for page in range(1, max(1, max_pages) + 1):
            params = urllib.parse.urlencode({"location": "Austin, TX, USA", "q": query, "page": page})
            endpoint = f"{GOOGLE_AUSTIN_BOARD}?{params}"
            try:
                request = urllib.request.Request(endpoint, headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "text/html"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read(12_000_000).decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"Google {query} page {page}: {type(exc).__name__}")
                break
            page_paths = google_search_paths(raw)
            if not page_paths:
                break
            before = len(paths)
            for path in page_paths:
                slug_title = path.split("-", 1)[-1].replace("-", " ")
                if title_is_candidate({"title": slug_title}):
                    paths[path] = slug_title
            if page > 1 and len(paths) == before:
                break
            if request_delay_seconds:
                time.sleep(max(0.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    for path in paths:
        endpoint = urllib.parse.urljoin(GOOGLE_CAREERS_ROOT, path)
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 12_000_000).decode("utf-8", "replace")
            item = google_job_item(path, raw)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Google {paths[path]}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(0.0, request_delay_seconds))
    return results, errors


def microsoft_job_item(detail: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one Microsoft public Eightfold position detail."""
    locations = [clean_text(value) for value in (detail.get("standardizedLocations") or detail.get("locations") or [])]
    if not any(re.fullmatch(r"Austin,?\s+TX,?\s+(?:US|USA)", value, re.I) for value in locations):
        return None
    try:
        posted = datetime.fromtimestamp(float(detail.get("postedTs")), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    age = (datetime.now(timezone.utc).date() - posted.date()).days
    if age < 0 or age > max_age_days:
        return None
    description = clean_text(detail.get("jobDescription"))
    workplace = " ".join((
        clean_text(detail.get("workLocationOption")),
        " ".join(clean_text(value) for value in (detail.get("efcustomTextWorkSite") or [])),
    )).casefold()
    item = {
        "company": "Microsoft",
        "title": clean_text(detail.get("name")),
        "location": "Austin, TX",
        "url": clean_text(detail.get("publicUrl")) or urllib.parse.urljoin(MICROSOFT_CAREERS_BASE, clean_text(detail.get("positionUrl"))),
        "source": "microsoft",
        "description": description,
        "date_posted": posted.date().isoformat(),
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in workplace or "0 days" in workplace else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if item["title"] and item["url"] else None


def bain_job_item(listing: dict[str, Any], date_posted: str | None, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize an Austin-explicit Bain role when a trustworthy posting date is available.

    Bain's first-party search payload contains full descriptions and locations but no
    publication timestamp. Callers must provide a known date (for example, from an
    existing aggregator mirror) so an undated role cannot receive an artificial
    freshness boost.
    """
    locations = [clean_text(value) for value in (listing.get("Location") or [])]
    if not any(value.casefold() == "austin" for value in locations):
        return None
    if not _fresh_iso_listing(date_posted, max_age_days=max_age_days):
        return None
    title = clean_text(listing.get("JobTitle"))
    if not title_is_candidate({"title": title}):
        return None
    description = clean_text(listing.get("JobDescription"))
    link = clean_text(listing.get("Link"))
    item = {
        "company": "Bain & Company",
        "title": title,
        "location": "Austin, TX",
        "url": canonical_public_url(urllib.parse.urljoin(BAIN_CAREERS_BASE, link)),
        "source": "bain",
        "description": description,
        "date_posted": date_posted,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in description.casefold() and "hybrid" not in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    texas_range = re.search(
        r"In Texas[^$]{0,220}\$([\d,]+(?:\.\d+)?)\s*(?:-|–|to)\s*\$([\d,]+(?:\.\d+)?)",
        description,
        re.I,
    )
    if texas_range:
        salary_min = float(texas_range.group(1).replace(",", ""))
        salary_max = float(texas_range.group(2).replace(",", ""))
        item.update({
            "salary_text": format_salary_range(salary_min, salary_max),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_type": "posted",
        })
    return item if item["title"] and item["url"] else None


def bain_austin_jobs(known_dates: dict[str, str] | None = None, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Read Bain's public job-search API without inventing missing publication dates."""
    params = urllib.parse.urlencode({"start": 0, "results": 500, "filters": "", "searchValue": "Austin"})
    request = urllib.request.Request(
        f"{BAIN_JOBS_API}?{params}",
        headers={
            "User-Agent": "EliOpportunityQueue/1.0",
            "Accept": "application/json",
            "Referer": f"{BAIN_CAREERS_BASE}/careers/find-a-role/",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read(20_000_000))
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
        return [], [f"Bain Austin search: {type(exc).__name__}"]
    dates = {clean_text(key).casefold(): value for key, value in (known_dates or {}).items() if value}
    results: list[dict[str, Any]] = []
    for listing in payload.get("results") or []:
        title = clean_text(listing.get("JobTitle"))
        item = bain_job_item(listing, dates.get(title.casefold()), max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, []


def microsoft_austin_jobs(max_pages: int = 4, request_delay_seconds: float = 2.0) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin-explicit roles from Microsoft's public Eightfold API."""
    errors: list[str] = []
    listings: dict[str, dict[str, Any]] = {}
    for query in ("software engineer", "engineering manager", "site reliability engineer", "data engineer"):
        for page in range(max(1, max_pages)):
            params = urllib.parse.urlencode({
                "domain": "microsoft.com", "query": query, "location": "Austin", "start": page * 10,
            })
            endpoint = f"{MICROSOFT_CAREERS_BASE}/api/pcsx/search?{params}"
            try:
                request = urllib.request.Request(endpoint, headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read(12_000_000))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"Microsoft {query} page {page + 1}: {type(exc).__name__}")
                break
            data = payload.get("data") or {}
            positions = data.get("positions") or []
            if not positions:
                break
            for listing in positions:
                position_id = str(listing.get("id") or "")
                if position_id and title_is_candidate({"title": clean_text(listing.get("name"))}) and _fresh_iso_listing(
                    datetime.fromtimestamp(float(listing.get("postedTs")), tz=timezone.utc).isoformat() if listing.get("postedTs") else None
                ):
                    listings[position_id] = listing
            if (page + 1) * 10 >= int(data.get("count") or 0):
                break
            if request_delay_seconds:
                time.sleep(max(0.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    for position_id, listing in listings.items():
        params = urllib.parse.urlencode({"position_id": position_id, "domain": "microsoft.com"})
        endpoint = f"{MICROSOFT_CAREERS_BASE}/api/pcsx/position_details?{params}"
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(12_000_000))
            item = microsoft_job_item(payload.get("data") or {})
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Microsoft {clean_text(listing.get('name'))}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(0.0, request_delay_seconds))
    return results, errors


def oracle_listing_has_austin(listing: dict[str, Any]) -> bool:
    """Accept Austin whether Oracle marks it primary or as an extra location."""
    locations: list[str] = [clean_text(listing.get("PrimaryLocation"))]
    for field in ("secondaryLocations", "otherWorkLocations", "workLocation"):
        for value in listing.get(field) or []:
            if not isinstance(value, dict):
                locations.append(clean_text(value))
                continue
            locations.append(clean_text(value.get("Name") or value.get("LocationName")))
            locations.append(", ".join(filter(None, (
                clean_text(value.get("TownOrCity")),
                clean_text(value.get("Region2")),
                clean_text(value.get("Country")),
            ))))
    return any(re.fullmatch(r"Austin,?\s+(?:TX|Texas)(?:,?\s+(?:US|United States))?", value, re.I) for value in locations)


def oracle_job_item(detail: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one public Oracle Candidate Experience requisition detail."""
    if not oracle_listing_has_austin(detail):
        return None
    posted = clean_text(detail.get("ExternalPostedStartDate"))
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    for field in detail.get("requisitionFlexFields") or []:
        if not isinstance(field, dict):
            continue
        prompt = clean_text(field.get("Prompt")).casefold()
        value = clean_text(field.get("Value")).casefold()
        if "security clearance" in prompt and value not in {"", "no", "none", "not required"}:
            return None
    description = clean_text(" ".join(str(detail.get(field) or "") for field in (
        "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr",
    )))
    item = {
        "company": "Oracle",
        "title": clean_text(detail.get("Title")),
        "location": "Austin, TX",
        "url": f"{ORACLE_CAREERS_BASE}/en/sites/jobsearch/job/{clean_text(detail.get('Id'))}",
        "source": "oracle",
        "description": description,
        "date_posted": posted[:10] or None,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in clean_text(detail.get("WorkplaceType")).casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if item["title"] and item["url"] else None


def oracle_austin_jobs(request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin-explicit target roles from Oracle's public HCM API."""
    errors: list[str] = []
    listings: dict[str, dict[str, Any]] = {}
    search_url = f"{ORACLE_API_BASE}/recruitingCEJobRequisitions"
    for query in ORACLE_SEARCH_QUERIES:
        params = urllib.parse.urlencode({
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations,requisitionList.otherWorkLocations,requisitionList.workLocation",
            "finder": f'findReqs;siteNumber={ORACLE_SITE_NUMBER},limit=200,offset=0,keyword="{query}",location=Austin > TX > United States',
        })
        try:
            request = urllib.request.Request(f"{search_url}?{params}", headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(25_000_000))
            for result in payload.get("items") or []:
                for listing in result.get("requisitionList") or []:
                    posting_id = clean_text(listing.get("Id"))
                    if posting_id and title_is_candidate({"title": clean_text(listing.get("Title"))}) and _fresh_iso_listing(listing.get("PostedDate"), max_age_days):
                        if oracle_listing_has_austin(listing):
                            listings[posting_id] = listing
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Oracle {query}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(0.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    detail_url = f"{ORACLE_API_BASE}/recruitingCEJobRequisitionDetails"
    for posting_id, listing in listings.items():
        params = urllib.parse.urlencode({
            "onlyData": "true", "expand": "all",
            "finder": f"ById;Id={posting_id},siteNumber={ORACLE_SITE_NUMBER}",
        })
        try:
            request = urllib.request.Request(f"{detail_url}?{params}", headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(12_000_000))
            item = oracle_job_item((payload.get("items") or [{}])[0], max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError, IndexError) as exc:
            errors.append(f"Oracle {clean_text(listing.get('Title'))}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(0.0, request_delay_seconds))
    return results, errors


def dell_job_item(detail: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one public Dell Candidate Experience requisition detail."""
    if not oracle_listing_has_austin(detail):
        return None
    posted = clean_text(detail.get("ExternalPostedStartDate"))
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(" ".join(str(detail.get(field) or "") for field in (
        "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr",
    )))
    posting_id = clean_text(detail.get("Id"))
    title = clean_text(detail.get("Title"))
    item = {
        "company": "Dell Technologies",
        "title": title,
        "location": "Austin, TX",
        "url": f"{DELL_CAREERS_BASE}/job/{posting_id}",
        "source": "dell",
        "description": description,
        "date_posted": posted[:10] or None,
        "provider_job_id": posting_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in clean_text(detail.get("WorkplaceType")).casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if title and posting_id and description else None


def dell_austin_jobs(request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh, explicitly Austin target roles from Dell's public HCM API."""
    errors: list[str] = []
    listings: dict[str, dict[str, Any]] = {}
    search_url = f"{DELL_API_BASE}/recruitingCEJobRequisitions"
    for query in DELL_SEARCH_QUERIES:
        params = urllib.parse.urlencode({
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations,requisitionList.otherWorkLocations,requisitionList.workLocation",
            "finder": f'findReqs;siteNumber={DELL_SITE_NUMBER},limit=200,offset=0,keyword="{query}",location=Austin > TX > United States',
        })
        try:
            request = urllib.request.Request(f"{search_url}?{params}", headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(25_000_000))
            for result in payload.get("items") or []:
                for listing in result.get("requisitionList") or []:
                    posting_id = clean_text(listing.get("Id"))
                    if (
                        posting_id
                        and title_is_candidate({"title": clean_text(listing.get("Title"))})
                        and _fresh_iso_listing(listing.get("PostedDate"), max_age_days)
                        and oracle_listing_has_austin(listing)
                    ):
                        listings[posting_id] = listing
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Dell {query}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    detail_url = f"{DELL_API_BASE}/recruitingCEJobRequisitionDetails"
    for posting_id, listing in listings.items():
        params = urllib.parse.urlencode({
            "onlyData": "true", "expand": "all",
            "finder": f"ById;Id={posting_id},siteNumber={DELL_SITE_NUMBER}",
        })
        try:
            request = urllib.request.Request(f"{detail_url}?{params}", headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(12_000_000))
            item = dell_job_item((payload.get("items") or [{}])[0], max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError, IndexError) as exc:
            errors.append(f"Dell {clean_text(listing.get('Title'))}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def jpmorgan_job_item(detail: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one JPMorganChase public Oracle HCM requisition detail."""
    locations: list[str] = [clean_text(detail.get("PrimaryLocation"))]
    for field in ("secondaryLocations", "otherWorkLocations"):
        for value in detail.get(field) or []:
            locations.append(clean_text(value.get("Name")) if isinstance(value, dict) else clean_text(value))
    for value in detail.get("workLocation") or []:
        if isinstance(value, dict):
            city = clean_text(value.get("TownOrCity"))
            region = clean_text(value.get("Region2"))
            country = clean_text(value.get("Country"))
            locations.append(", ".join(part for part in (city, region, country) if part))
    if not any(re.fullmatch(r"Austin,?\s+(?:TX|Texas)(?:,?\s+(?:US|United States))?", value, re.I) for value in locations):
        return None
    posted = clean_text(detail.get("ExternalPostedStartDate"))
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(" ".join(str(detail.get(field) or "") for field in (
        "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr",
    )))
    posting_id = clean_text(detail.get("Id"))
    title = clean_text(detail.get("Title"))
    item = {
        "company": "JPMorganChase",
        "title": title,
        "location": "Austin, TX",
        "url": f"{JPMORGAN_CAREERS_BASE}/job/{posting_id}",
        "source": "jpmorgan",
        "description": description,
        "date_posted": posted[:10] or None,
        "provider_job_id": posting_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in clean_text(detail.get("WorkplaceType")).casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if title and posting_id and description else None


def jpmorgan_austin_jobs(request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin software roles from JPMorganChase's public HCM API."""
    errors: list[str] = []
    listings: dict[str, dict[str, Any]] = {}
    search_url = f"{JPMORGAN_API_BASE}/recruitingCEJobRequisitions"
    for query in ("software engineer", "engineering manager", "data engineer"):
        params = urllib.parse.urlencode({
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations,requisitionList.otherWorkLocations,requisitionList.workLocation",
            "finder": f'findReqs;siteNumber={JPMORGAN_SITE_NUMBER},limit=200,offset=0,keyword="{query}",location=Austin > TX > United States',
        })
        try:
            request = urllib.request.Request(f"{search_url}?{params}", headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(25_000_000))
            for result in payload.get("items") or []:
                for listing in result.get("requisitionList") or []:
                    posting_id = clean_text(listing.get("Id"))
                    locations = [clean_text(listing.get("PrimaryLocation"))]
                    locations.extend(clean_text(value.get("Name")) for value in listing.get("secondaryLocations") or [] if isinstance(value, dict))
                    for value in listing.get("workLocation") or []:
                        if isinstance(value, dict):
                            locations.append(", ".join(clean_text(value.get(field)) for field in ("TownOrCity", "Region2", "Country") if clean_text(value.get(field))))
                    if (
                        posting_id
                        and title_is_candidate({"title": clean_text(listing.get("Title"))})
                        and _fresh_iso_listing(listing.get("PostedDate"), max_age_days)
                        and any(re.fullmatch(r"Austin,?\s+(?:TX|Texas)(?:,?\s+(?:US|United States))?", value, re.I) for value in locations)
                    ):
                        listings[posting_id] = listing
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"JPMorganChase {query}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    detail_url = f"{JPMORGAN_API_BASE}/recruitingCEJobRequisitionDetails"
    for posting_id, listing in listings.items():
        params = urllib.parse.urlencode({
            "onlyData": "true", "expand": "all",
            "finder": f"ById;Id={posting_id},siteNumber={JPMORGAN_SITE_NUMBER}",
        })
        try:
            request = urllib.request.Request(f"{detail_url}?{params}", headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(12_000_000))
            item = jpmorgan_job_item((payload.get("items") or [{}])[0], max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError, IndexError) as exc:
            errors.append(f"JPMorganChase {clean_text(listing.get('Title'))}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def realtor_job_item(job: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one Realtor.com record from its official careers search feed."""
    locations = [{
        "city": clean_text(job.get("primary_city")),
        "state": clean_text(job.get("primary_state")),
        "country": clean_text(job.get("primary_country")),
    }]
    for location in job.get("addtnl_locations") or []:
        if isinstance(location, dict):
            locations.append({
                "city": clean_text(location.get("addtnl_city")),
                "state": clean_text(location.get("addtnl_state")),
                "country": clean_text(location.get("addtnl_country")),
            })
    if not any(
        value["city"].casefold() == "austin"
        and value["state"].casefold() in {"tx", "texas"}
        and value["country"].casefold() in {"us", "usa", "united states"}
        for value in locations
    ):
        return None
    posted = clean_text(job.get("open_date"))
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(job.get("description"))
    job_id = clean_text(job.get("id"))
    url = clean_text(job.get("url"))
    if not url.startswith(REALTOR_CAREERS_BASE) and job_id:
        slug = re.sub(r"[^a-z0-9]+", "-", clean_text(job.get("title")).casefold()).strip("-")
        url = f"{REALTOR_CAREERS_BASE}/job/{job_id}/{slug}-austin-tx/"
    arrangement_text = " ".join((
        clean_text(job.get("location_type")), clean_text(job.get("employment_type")), description,
    )).casefold()
    item = {
        "company": "Realtor.com",
        "title": clean_text(job.get("title")),
        "location": "Austin, TX",
        "url": url,
        "source": "realtor",
        "description": description,
        "date_posted": posted[:10] or None,
        "easy_apply": 0,
        "work_arrangement": "remote" if re.search(r"\bremote\b", arrangement_text) else "onsite/hybrid",
    }
    item.update(extract_salary(" ".join((clean_text(job.get("salary")), description))))
    return item if item["title"] and item["url"] else None


def realtor_austin_jobs(max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin-explicit roles from Realtor.com's public search API."""
    params = urllib.parse.urlencode({
        "callback": "CWS.jobs.jobCallback", "Limit": 100,
        "Organization": REALTOR_ORG_ID, "offset": 1,
    })
    request = urllib.request.Request(
        f"{REALTOR_JOB_API}?{params}",
        headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/javascript, application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(25_000_000).decode("utf-8", "replace")
        match = re.match(r"^[^(]+\((.*)\)\s*$", raw, re.S)
        if not match:
            raise ValueError("unexpected JSONP response")
        payload = json.loads(match.group(1))
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
        return [], [f"Realtor.com: {type(exc).__name__}"]
    results: list[dict[str, Any]] = []
    for job in payload.get("queryResult") or []:
        if not isinstance(job, dict) or not title_is_candidate({"title": clean_text(job.get("title"))}):
            continue
        item = realtor_job_item(job, max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, []


def procore_search_urls(raw: str) -> list[str]:
    """Extract canonical detail links from Procore's public filtered result page."""
    urls: list[str] = []
    for path in re.findall(r'href=["\']([^"\']*/jobs/[^"\']+)["\']', raw, re.I):
        url = canonical_public_url(urllib.parse.urljoin(PROCORE_CAREERS_BASE, path))
        parsed_path = urllib.parse.urlsplit(url).path.rstrip("/")
        if not re.fullmatch(r"/jobs/[^/]+", parsed_path) or parsed_path == "/jobs/search" or url in urls:
            continue
        urls.append(url)
    return urls


def procore_job_item(raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one Procore JobPosting page with an explicit Austin location."""
    posting: dict[str, Any] | None = None
    for value in re.findall(r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            posting = candidate
            break
    if not posting:
        return None
    return procore_posting_item(posting, url, max_age_days=max_age_days)


def procore_posting_item(posting: dict[str, Any], url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize structured Procore data from either HTTP or a browser handoff."""
    locations: list[str] = []
    has_austin = False
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    for place in raw_locations:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        addresses = address if isinstance(address, list) else [address]
        for value in addresses:
            if not isinstance(value, dict):
                continue
            city = clean_text(value.get("addressLocality"))
            state = clean_text(value.get("addressRegion"))
            country = clean_text(value.get("addressCountry"))
            if city.casefold() == "austin" and state.casefold() in {"tx", "texas"} and country.casefold() in {"us", "usa", "united states"}:
                has_austin = True
            label = ", ".join(part for part in (city, state, country) if part)
            if label:
                locations.append(label)
    if not has_austin:
        return None
    posted = clean_text(posting.get("datePosted"))
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(posting.get("description"))
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    title = clean_text(posting.get("title"))
    item = {
        "company": "Procore",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": canonical_public_url(posting.get("url") or url),
        "source": "procore",
        "description": description,
        "date_posted": posted[:10] or None,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{title} {description}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and item["url"] and description else None


def paloalto_posting_item(posting: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize browser-verified Palo Alto Networks JobPosting JSON-LD."""
    if not isinstance(posting, dict) or posting.get("@type") != "JobPosting":
        return None
    raw_posted = clean_text(posting.get("datePosted"))
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw_posted)
    posted = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}" if match else raw_posted[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    locations: list[str] = []
    has_austin = False
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    for place in raw_locations:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        region = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        if city.casefold() == "austin" and region.casefold() in {"texas", "tx"}:
            has_austin = True
        label = ", ".join(value for value in (city, region, country) if value)
        if label:
            locations.append(label)
    if not has_austin:
        return None
    description = clean_text(posting.get("description"))
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    title = clean_text(posting.get("title"))
    item = {
        "company": "Palo Alto Networks",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": canonical_public_url(posting.get("url")),
        "source": "paloalto",
        "description": description,
        "date_posted": posted or None,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and item["url"] and description else None


def paloalto_austin_job_paths(raw: str) -> list[str]:
    """Job links on the employer's server-rendered Austin listing page."""
    paths: list[str] = []
    for href in re.findall(r'href=["\']([^"\']*/en/job/[^"\']+)["\']', raw, re.I):
        path = urllib.parse.urlparse(html.unescape(href)).path
        slug = path.split("/")[-3].replace("-", " ") if len(path.split("/")) >= 3 else ""
        if path.startswith("/en/job/") and title_is_candidate({"title": slug}) and path not in paths:
            paths.append(path)
    return paths


def paloalto_austin_jobs(
    max_pages: int = 5,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin roles from Palo Alto's public pages and JSON-LD.

    Its official interactive Austin page is also server-rendered. The public
    detail pages expose JobPosting JSON-LD with full descriptions and dates.
    """
    robots = urllib.robotparser.RobotFileParser()
    robots.set_url(f"{PALOALTO_CAREERS_BASE}/robots.txt")
    try:
        robots.read()
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        return [], [f"Palo Alto Networks robots: {type(exc).__name__}"]
    if not robots.can_fetch("EliOpportunityQueue/1.0", PALOALTO_AUSTIN_BOARD):
        return [], ["Palo Alto Networks: robots disallow Austin listing"]
    paths: list[str] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    for page in range(1, max(1, max_pages) + 1):
        if page > 1:
            time.sleep(delay)
        url = PALOALTO_AUSTIN_BOARD if page == 1 else f"{PALOALTO_AUSTIN_BOARD}/{page}"
        if not robots.can_fetch("EliOpportunityQueue/1.0", url):
            errors.append(f"Palo Alto Networks: robots disallow Austin page {page}")
            break
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(3_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Palo Alto Networks Austin page {page}: {type(exc).__name__}")
            break
        page_paths = paloalto_austin_job_paths(raw)
        for path in page_paths:
            if path not in paths:
                paths.append(path)
        if len(page_paths) < 15:
            break
    results: list[dict[str, Any]] = []
    for path in paths:
        url = f"{PALOALTO_CAREERS_BASE}{path}"
        if not robots.can_fetch("EliOpportunityQueue/1.0", url):
            errors.append(f"Palo Alto Networks: robots disallow {path.rsplit('/', 1)[-1]}")
            continue
        time.sleep(delay)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(3_000_000).decode("utf-8", "replace")
            for script in re.findall(r'<script\b[^>]*\btype=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
                posting = json.loads(script)
                for record in posting if isinstance(posting, list) else [posting]:
                    item = paloalto_posting_item(record, max_age_days=max_age_days)
                    if item and title_is_candidate(item):
                        results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Palo Alto Networks {path.rsplit('/', 1)[-1]}: {type(exc).__name__}")
    return results, errors


def servicenow_posting_item(posting: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize browser-verified ServiceNow JobPosting JSON-LD."""
    if not isinstance(posting, dict) or posting.get("@type") != "JobPosting":
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    locations: list[str] = []
    has_austin = False
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    for place in raw_locations:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        region = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        if city.casefold() == "austin" and region.casefold() in {"texas", "tx"}:
            has_austin = True
        label = ", ".join(value for value in (city, region, country) if value)
        if label:
            locations.append(label)
    if not has_austin:
        return None
    url = canonical_public_url(posting.get("url") or posting.get("mainEntityOfPage"))
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.casefold() != "careers.servicenow.com" or not re.fullmatch(r"/jobs/\d+/[^/]+/", parsed.path):
        return None
    description = clean_text(posting.get("description"))
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    title = clean_text(posting.get("title"))
    item = {
        "company": "ServiceNow",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": url,
        "source": "servicenow",
        "description": description,
        "date_posted": posted or None,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if posting.get("jobLocationType") == "TELECOMMUTE" or "remote" in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and description and provider_job_id else None


def lpl_posting_item(posting: dict[str, Any], url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize LPL Financial JobPosting JSON-LD from its public Austin portal."""
    if not isinstance(posting, dict) or posting.get("@type") != "JobPosting":
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    locations: list[str] = []
    has_austin = False
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    for place in raw_locations:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        region = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        if city.casefold() == "austin" and region.casefold() in {"texas", "tx"}:
            has_austin = True
        label = ", ".join(value for value in (city, region, country) if value)
        if label:
            locations.append(label)
    if not has_austin:
        return None
    description = clean_text(posting.get("description"))
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    title = clean_text(posting.get("title"))
    item = {
        "company": "LPL Financial",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": canonical_public_url(posting.get("url") or url),
        "source": "lpl",
        "description": description,
        "date_posted": posted or None,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "#li-remote" in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and item["url"] and description else None


def pwc_posting_item(posting: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize browser-verified PwC/Workday data from the public PwC portal."""
    if not isinstance(posting, dict) or posting.get("@type") != "JobPosting":
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    location_lines = [clean_text(value) for value in str(posting.get("_all_locations") or "").splitlines() if clean_text(value)]
    if not any(value.casefold() == "tx-austin" for value in location_lines):
        return None
    description = clean_text(posting.get("description"))
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    title = clean_text(posting.get("title"))
    source_url = canonical_public_url(posting.get("_source_url"))
    if not re.fullmatch(r"https://jobs-us\.pwc\.com/us/en/job/[^/?#]+/[^?#]+", source_url):
        return None
    item = {
        "company": "PwC",
        "title": title,
        "location": "Austin, TX" if len(location_lines) == 1 else "Austin, TX / Multiple US locations",
        "url": source_url,
        "source": "pwc",
        "description": description,
        "date_posted": posted or None,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{title} {description}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and item["url"] and description else None


def procore_austin_jobs(request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect Procore's fresh Austin engineering roles from its public portal."""
    errors: list[str] = []
    request = urllib.request.Request(PROCORE_AUSTIN_ENGINEERING_BOARD, headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            search_raw = response.read(10_000_000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
        return [], [f"Procore search: {type(exc).__name__}"]
    results: list[dict[str, Any]] = []
    urls = procore_search_urls(search_raw)
    if not urls:
        return [], ["Procore search: empty or security-filtered result surface"]
    for url in urls:
        try:
            detail_request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(detail_request, timeout=30) as response:
                raw = response.read(10_000_000).decode("utf-8", "replace")
            item = procore_job_item(raw, url, max_age_days=max_age_days)
            if item and title_is_candidate(item):
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Procore {url.rsplit('/', 1)[-1]}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def tesla_job_item(job: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a Tesla job record embedded in its official careers page state."""
    location = clean_text(job.get("location"))
    if not re.fullmatch(r"Austin,?\s+(?:TX|Texas)", location, re.I):
        return None
    posted = clean_text(job.get("datePosted") or job.get("postedDate"))[:10]
    if posted and not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(" ".join(str(job.get(field) or "") for field in (
        "jobDescription", "jobResponsibilities", "jobRequirements",
    )))
    path = clean_text(job.get("url"))
    item = {
        "company": "Tesla",
        "title": clean_text(job.get("title")),
        "location": "Austin, TX",
        "url": urllib.parse.urljoin(TESLA_CAREERS_BASE, path),
        "source": "tesla",
        "description": description,
        # Tesla's public detail state currently exposes no creation date. Keep
        # this unknown rather than fabricating recency from the discovery time.
        "date_posted": posted or None,
        "provider_job_id": clean_text(job.get("provider_job_id") or job.get("id")),
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in location.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(" ".join((clean_text(job.get("jobCompensationAndBenefits")), description))))
    return item if item["title"] and item["url"] and description else None


class _TemporalCareerCardsParser(HTMLParser):
    """Read visible title/location spans from Temporal's server-rendered cards."""

    _PATH = re.compile(r"/careers/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/?$", re.I)

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_path = ""
        self.span_depth = 0
        self.span_parts: list[str] = []
        self.spans: list[str] = []
        self.cards: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.casefold() == "a" and self._PATH.fullmatch(values.get("href") or ""):
            self.current_path = values.get("href") or ""
            self.span_depth = 0
            self.span_parts = []
            self.spans = []
        elif self.current_path and tag.casefold() == "span":
            if not self.span_depth:
                self.span_parts = []
            self.span_depth += 1

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if self.current_path and lowered == "span" and self.span_depth:
            self.span_depth -= 1
            if not self.span_depth:
                value = clean_text(" ".join(self.span_parts))
                if value:
                    self.spans.append(value)
        elif self.current_path and lowered == "a":
            if len(self.spans) >= 2:
                self.cards.append({
                    "url": urllib.parse.urljoin(TEMPORAL_CAREERS_BASE, self.current_path),
                    "title": self.spans[0],
                    "location": self.spans[-1],
                })
            self.current_path = ""
            self.span_depth = 0
            self.span_parts = []
            self.spans = []

    def handle_data(self, data: str) -> None:
        if self.current_path and self.span_depth:
            self.span_parts.append(data)


def temporal_search_listings(raw: str) -> list[dict[str, str]]:
    """Extract canonical jobs and visible locations from Temporal's careers page."""
    parser = _TemporalCareerCardsParser()
    parser.feed(raw)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for card in parser.cards:
        url = canonical_public_url(card["url"])
        if url in seen:
            continue
        seen.add(url)
        results.append(card | {"url": url})
    return results


def temporal_job_item(posting: dict[str, Any], url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a fresh Temporal JobPosting that explicitly names Austin, Texas."""
    if not isinstance(posting, dict) or posting.get("@type") != "JobPosting":
        return None
    posted = clean_text(posting.get("datePosted"))
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    locations: list[str] = []
    has_austin = False
    for place in raw_locations:
        if not isinstance(place, dict):
            continue
        raw_addresses = place.get("address") or []
        if isinstance(raw_addresses, dict):
            raw_addresses = [raw_addresses]
        for address in raw_addresses:
            if not isinstance(address, dict):
                continue
            city = clean_text(address.get("addressLocality"))
            region = clean_text(address.get("addressRegion"))
            country = clean_text(address.get("addressCountry"))
            city_names_texas = bool(re.fullmatch(r"Austin,?\s+(?:TX|Texas)", city, re.I))
            city_and_region = city.casefold() == "austin" and region.casefold() in {"tx", "texas"}
            country_is_us = not country or country.casefold() in {"us", "usa", "united states", "united states of america"}
            has_austin = has_austin or country_is_us and (city_names_texas or city_and_region)
            label = ", ".join(value for value in (city, region, country) if value)
            if label:
                locations.append(label)
    if not has_austin:
        return None
    description = clean_text(posting.get("description"))
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    title = clean_text(posting.get("title"))
    item = {
        "company": "Temporal",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": canonical_public_url(url),
        "source": "temporal",
        "description": description,
        "date_posted": posted[:10] or None,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if clean_text(posting.get("jobLocationType")).casefold() == "telecommute" else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and item["url"] and description else None


def temporal_austin_jobs(request_delay_seconds: float = 2.0, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect Temporal jobs only when the visible official card names Austin, Texas."""
    request = urllib.request.Request(
        TEMPORAL_CAREERS_BOARD,
        headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = _response_body(response, 25_000_000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
        return [], [f"Temporal search: {type(exc).__name__}"]
    listings = temporal_search_listings(raw)
    if not listings:
        return [], ["Temporal search: empty or security-filtered result surface"]
    candidates = [
        listing for listing in listings
        if re.fullmatch(r"Austin,?\s+(?:TX|Texas)(?:,?\s+(?:US|USA|United States))?", listing["location"], re.I)
        and title_is_candidate(listing)
    ]
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for listing in candidates:
        try:
            detail_request = urllib.request.Request(
                listing["url"],
                headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(detail_request, timeout=30) as response:
                detail_raw = _response_body(response, 15_000_000).decode("utf-8", "replace")
            posting: dict[str, Any] | None = None
            for value in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', detail_raw, re.I | re.S):
                try:
                    candidate = json.loads(value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                    posting = candidate
                    break
            item = temporal_job_item(posting or {}, listing["url"], max_age_days=max_age_days)
            if item and title_is_candidate(item):
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Temporal {listing['url'].rsplit('/', 1)[-1]}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def gm_job_item(job: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one official GM JobPosting JSON-LD record.

    GM's Happydance search page is browser-rendered and currently rejects
    unattended HTTP clients. Keeping the JSON-LD normalizer here lets a
    browser-assisted collection pass persist canonical records without mixing
    collection with matching or scoring.
    """
    if not isinstance(job, dict) or not _fresh_iso_listing(job.get("datePosted"), max_age_days):
        return None
    locations: list[str] = []
    has_austin = False
    for place in job.get("jobLocation") or []:
        if not isinstance(place, dict):
            continue
        addresses = place.get("address") or []
        if isinstance(addresses, dict):
            addresses = [addresses]
        for address in addresses:
            if not isinstance(address, dict):
                continue
            city = clean_text(address.get("addressLocality"))
            region = clean_text(address.get("addressRegion"))
            country = clean_text(address.get("addressCountry"))
            label = ", ".join(value for value in (city, region, country) if value)
            if label:
                locations.append(label)
            if city.casefold() == "austin" and region.casefold() in {"texas", "tx"}:
                has_austin = True
    if not has_austin:
        return None
    description = clean_text(job.get("description"))
    item = {
        "company": clean_text((job.get("hiringOrganization") or {}).get("name")) or "General Motors",
        "title": clean_text(job.get("title")),
        "location": " / ".join(dict.fromkeys(locations)),
        "url": clean_text(job.get("url") or job.get("mainEntityOfPage")),
        "source": "gm",
        "description": description,
        "date_posted": str(job.get("datePosted") or "")[:10] or None,
        "provider_job_id": clean_text(job.get("identifier")),
        "easy_apply": 0,
        "work_arrangement": "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if item["title"] and item["url"] and description else None


def paypal_job_item(job: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a record from PayPal's public Eightfold portal."""
    if not isinstance(job, dict) or not _fresh_iso_listing(job.get("date_posted"), max_age_days):
        return None
    raw_locations = job.get("locations") or []
    if not isinstance(raw_locations, list):
        raw_locations = []
    locations = [clean_text(value) for value in raw_locations if clean_text(value)]
    location = clean_text(job.get("location"))
    if location and not locations:
        locations = [value for value in re.split(r"\s*(?:\n|/|;)\s*", location) if value]
    if not any(re.search(r"\bAustin\s*,\s*(?:TX|Texas)\b", value, re.I) for value in locations):
        return None
    description = clean_text(job.get("description"))
    title = clean_text(job.get("title"))
    provider_job_id = clean_text(job.get("provider_job_id"))
    url = canonical_public_url(job.get("url"))
    if not url and provider_job_id:
        url = f"{PAYPAL_CAREERS_BASE}?pid={urllib.parse.quote(provider_job_id)}"
    item = {
        "company": "PayPal",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 and "+" not in location else "Austin, TX / Multiple US locations",
        "url": url,
        "source": "paypal",
        "description": description,
        "date_posted": str(job.get("date_posted") or "")[:10] or None,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{job.get('work_location_option', '')} {job.get('location_flexibility', '')} {location} {description}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if title and url and description else None


def paypal_austin_jobs(
    max_pages: int = 3,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin targets from PayPal's public Eightfold APIs."""
    listings: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    total = 0
    for page in range(max(1, max_pages)):
        params = urllib.parse.urlencode({
            "domain": "paypal.com",
            "query": "",
            "location": "Austin, Texas",
            "start": page * 10,
            "sort_by": "distance",
            "filter_distance": "80",
            "filter_include_remote": "1",
            "filter_include_relocation": "0",
        })
        try:
            request = urllib.request.Request(
                f"{PAYPAL_SEARCH_API}?{params}",
                headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(12_000_000))
            data = payload.get("data") or {}
            page_items = data.get("positions") or []
            total = max(total, int(data.get("count") or 0))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"PayPal search page {page + 1}: {type(exc).__name__}")
            break
        for listing in page_items:
            if not isinstance(listing, dict):
                continue
            listing_id = clean_text(listing.get("id"))
            locations = [clean_text(value) for value in listing.get("locations") or []]
            posted_ts = listing.get("postedTs")
            try:
                posted = datetime.fromtimestamp(float(posted_ts), tz=timezone.utc).date().isoformat()
            except (TypeError, ValueError, OverflowError, OSError):
                posted = ""
            if (
                listing_id
                and title_is_candidate({"title": clean_text(listing.get("name"))})
                and any(re.fullmatch(r"Austin,\s*(?:TX|Texas),\s*(?:US|United States of America)", value, re.I) for value in locations)
                and _fresh_iso_listing(posted, max_age_days)
            ):
                listing["_date_posted"] = posted
                listings[listing_id] = listing
        if len(page_items) < 10 or (total and (page + 1) * 10 >= total):
            break
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    for listing_id, listing in listings.items():
        params = urllib.parse.urlencode({
            "position_id": listing_id,
            "domain": "paypal.com",
            "hl": "en",
            "queried_location": "Austin, Texas",
        })
        try:
            request = urllib.request.Request(
                f"{PAYPAL_DETAIL_API}?{params}",
                headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(12_000_000))
            detail = payload.get("data") or {}
            item = paypal_job_item({
                "provider_job_id": clean_text(detail.get("id") or listing_id),
                "title": clean_text(detail.get("name") or listing.get("name")),
                "locations": detail.get("locations") or listing.get("locations") or [],
                "location": " / ".join(detail.get("locations") or listing.get("locations") or []),
                "url": urllib.parse.urljoin(PAYPAL_CAREERS_BASE + "/", clean_text(detail.get("positionUrl") or listing.get("positionUrl"))),
                "date_posted": listing.get("_date_posted"),
                "description": detail.get("jobDescription"),
                "work_location_option": detail.get("workLocationOption"),
                "location_flexibility": detail.get("locationFlexibility"),
            }, max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"PayPal {listing_id}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def qualcomm_job_item(job: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a record from Qualcomm's public Eightfold portal."""
    if not isinstance(job, dict) or not _fresh_iso_listing(job.get("date_posted"), max_age_days):
        return None
    raw_locations = job.get("locations") or []
    if not isinstance(raw_locations, list):
        raw_locations = []
    locations = [clean_text(value) for value in raw_locations if clean_text(value)]
    if not any(re.fullmatch(
        r"Austin,\s*(?:TX|Texas),\s*(?:US|United States(?: of America)?)",
        value,
        re.I,
    ) for value in locations):
        return None
    title = clean_text(job.get("title"))
    description = clean_text(job.get("description"))
    provider_job_id = clean_text(job.get("provider_job_id"))
    url = canonical_public_url(job.get("url"))
    if not url and provider_job_id:
        url = f"{QUALCOMM_CAREERS_BASE}/job/{urllib.parse.quote(provider_job_id)}"
    location_text = " / ".join(locations)
    item = {
        "company": "Qualcomm",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": url,
        "source": "qualcomm",
        "description": description,
        "date_posted": str(job.get("date_posted") or "")[:10] or None,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{job.get('work_location_option', '')} {job.get('location_flexibility', '')} {location_text} {description}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if title and url and description else None


def qualcomm_austin_jobs(
    max_pages: int = 10,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin target roles from Qualcomm's public Eightfold APIs."""
    listings: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    total = 0
    for page in range(max(1, max_pages)):
        params = urllib.parse.urlencode({
            "domain": "qualcomm.com",
            "query": "",
            "location": "Austin, Texas",
            "start": page * 10,
            "sort_by": "distance",
            "filter_distance": "80",
            "filter_include_remote": "0",
            "filter_include_relocation": "0",
        })
        try:
            request = urllib.request.Request(
                f"{QUALCOMM_SEARCH_API}?{params}",
                headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(12_000_000))
            data = payload.get("data") or {}
            page_items = data.get("positions") or []
            total = max(total, int(data.get("count") or 0))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"Qualcomm search page {page + 1}: {type(exc).__name__}")
            break
        for listing in page_items:
            if not isinstance(listing, dict):
                continue
            listing_id = clean_text(listing.get("id"))
            locations = [clean_text(value) for value in listing.get("standardizedLocations") or []]
            posted_ts = listing.get("postedTs")
            try:
                posted = datetime.fromtimestamp(float(posted_ts), tz=timezone.utc).date().isoformat()
            except (TypeError, ValueError, OverflowError, OSError):
                posted = ""
            if (
                listing_id
                and title_is_candidate({"title": clean_text(listing.get("name"))})
                and any(re.fullmatch(r"Austin,\s*(?:TX|Texas),\s*(?:US|United States(?: of America)?)", value, re.I) for value in locations)
                and _fresh_iso_listing(posted, max_age_days)
            ):
                listing["_date_posted"] = posted
                listings[listing_id] = listing
        if len(page_items) < 10 or (total and (page + 1) * 10 >= total):
            break
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    for listing_id, listing in listings.items():
        params = urllib.parse.urlencode({
            "position_id": listing_id,
            "domain": "qualcomm.com",
            "hl": "en",
            "queried_location": "Austin, Texas",
        })
        try:
            request = urllib.request.Request(
                f"{QUALCOMM_DETAIL_API}?{params}",
                headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(12_000_000))
            detail = payload.get("data") or {}
            detail_locations = detail.get("standardizedLocations") or listing.get("standardizedLocations") or []
            item = qualcomm_job_item({
                "provider_job_id": clean_text(detail.get("id") or listing_id),
                "title": clean_text(detail.get("name") or listing.get("name")),
                "locations": detail_locations,
                "url": urllib.parse.urljoin(QUALCOMM_CAREERS_BASE + "/", clean_text(detail.get("positionUrl") or listing.get("positionUrl"))),
                "date_posted": listing.get("_date_posted"),
                "description": detail.get("jobDescription"),
                "work_location_option": detail.get("workLocationOption"),
                "location_flexibility": detail.get("locationFlexibility"),
            }, max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"Qualcomm {listing_id}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def teamtailor_job_item(company: str, job: dict[str, Any], url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one official Teamtailor JobPosting JSON-LD record."""
    if not isinstance(job, dict) or not _fresh_iso_listing(job.get("datePosted"), max_age_days):
        return None
    locations: list[str] = []
    has_austin = False
    for place in job.get("jobLocation") or []:
        if not isinstance(place, dict):
            continue
        addresses = place.get("address") or []
        if isinstance(addresses, dict):
            addresses = [addresses]
        for address in addresses:
            if not isinstance(address, dict):
                continue
            city = clean_text(address.get("addressLocality"))
            country = clean_text(address.get("addressCountry"))
            if city.casefold() == "austin" and country.casefold() in {"us", "usa", "united states"}:
                has_austin = True
                locations.append("Austin, TX")
            elif city:
                locations.append(", ".join(value for value in (city, country) if value))
    if not has_austin:
        return None
    description = clean_text(job.get("description"))
    identifier = job.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    item = {
        "company": company,
        "title": clean_text(job.get("title")),
        "location": " / ".join(dict.fromkeys(locations)),
        "url": clean_text(url),
        "source": "teamtailor",
        "description": description,
        "date_posted": str(job.get("datePosted") or "")[:10] or None,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item if item["title"] and item["url"] and description else None


def teamtailor_search_listings(raw: str, base_url: str) -> list[dict[str, str]]:
    """Extract unique public Teamtailor job links and visible titles from a filtered board."""
    listings: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']*/jobs/\d+[^"\']*)["\'][^>]*>(.*?)</a>', raw, re.I | re.S):
        url = canonical_public_url(urllib.parse.urljoin(base_url, match.group(1)))
        title_match = re.search(r'\btitle=["\']([^"\']+)["\']', match.group(2), re.I)
        title = clean_text(title_match.group(1) if title_match else match.group(2))
        identity_match = re.search(r"/jobs/(\d+)(?:-|/|$)", urllib.parse.urlsplit(url).path)
        identity = identity_match.group(1) if identity_match else url
        if url and identity not in seen:
            seen.add(identity)
            listings.append({"url": url, "title": title})
    return listings


def teamtailor_next_page_url(raw: str, base_url: str) -> str:
    """Return the public Teamtailor show-more URL, constrained to this board."""
    base = urllib.parse.urlsplit(base_url)
    for value in re.findall(r'href=["\']([^"\']*/jobs/show_more\?[^"\']+)["\']', raw, re.I):
        url = canonical_public_url(urllib.parse.urljoin(base_url, html.unescape(value)))
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc == base.netloc and parsed.path == "/jobs/show_more":
            return url
    return ""


def _teamtailor_job_posting(raw: str) -> dict[str, Any] | None:
    for match in re.finditer(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw,
        re.I | re.S,
    ):
        try:
            payload = json.loads(match.group(1).strip())
        except (json.JSONDecodeError, TypeError):
            continue
        records = payload if isinstance(payload, list) else [payload]
        for record in records:
            if isinstance(record, dict) and str(record.get("@type", "")).casefold() == "jobposting":
                return record
    return None


def teamviewer_austin_jobs(
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
    max_pages: int = 5,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin-explicit roles from TeamViewer's public Teamtailor pages."""
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    candidates_by_id: dict[str, dict[str, str]] = {}
    next_url = TEAMVIEWER_AUSTIN_BOARD
    seen_pages: set[str] = set()
    for page in range(max(1, int(max_pages))):
        if not next_url or next_url in seen_pages:
            break
        if page:
            time.sleep(delay)
        seen_pages.add(next_url)
        try:
            request = urllib.request.Request(
                next_url,
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(15_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"TeamViewer search page {page + 1}: {type(exc).__name__}")
            break
        for listing in teamtailor_search_listings(raw, TEAMVIEWER_CAREERS_BASE):
            match = re.search(r"/jobs/(\d+)(?:-|/|$)", urllib.parse.urlsplit(listing["url"]).path)
            identity = match.group(1) if match else listing["url"]
            if title_is_candidate({"title": listing["title"]}):
                candidates_by_id[identity] = listing
        next_url = teamtailor_next_page_url(raw, TEAMVIEWER_CAREERS_BASE)

    results: list[dict[str, Any]] = []
    candidates = list(candidates_by_id.values())
    for index, listing in enumerate(candidates):
        if index:
            time.sleep(delay)
        try:
            request = urllib.request.Request(
                listing["url"],
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                detail_raw = response.read(12_000_000).decode("utf-8", "replace")
            posting = _teamtailor_job_posting(detail_raw)
            item = teamtailor_job_item("TeamViewer", posting or {}, listing["url"], max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"TeamViewer {listing['title']}: {type(exc).__name__}")
    return results, errors


def recruitee_job_item(company: str, job: dict[str, Any], url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one browser-verified Recruitee JobPosting JSON-LD record.

    Some custom-domain Recruitee boards reject unattended clients. The browser
    supplies only the public structured record; validation and persistence stay
    in the collector layer and remain independent of resume scoring.
    """
    if not isinstance(job, dict) or job.get("@type") != "JobPosting":
        return None
    posted = str(job.get("datePosted") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    places = job.get("jobLocation") or []
    if isinstance(places, dict):
        places = [places]
    locations: list[str] = []
    has_austin = False
    for place in places:
        if not isinstance(place, dict):
            continue
        addresses = place.get("address") or []
        if isinstance(addresses, dict):
            addresses = [addresses]
        for address in addresses:
            if not isinstance(address, dict):
                continue
            city = clean_text(address.get("addressLocality"))
            region = clean_text(address.get("addressRegion"))
            country = clean_text(address.get("addressCountry"))
            if city.casefold() == "austin" and region.casefold() in {"tx", "texas"} and country.casefold() in {"us", "usa", "united states"}:
                has_austin = True
                locations.append("Austin, TX")
            elif city:
                locations.append(", ".join(value for value in (city, region, country) if value))
    if not has_austin:
        return None
    description = clean_text(job.get("description"))
    identifier = job.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    if not provider_job_id:
        provider_job_id = clean_text(url).rstrip("/").rsplit("/", 1)[-1]
    title = clean_text(job.get("title"))
    item = {
        "company": company,
        "title": title,
        "location": " / ".join(dict.fromkeys(locations)),
        "url": canonical_public_url(url),
        "source": "recruitee",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{title} {description}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, job))
    return item if title and item["url"] and description else None


def arm_search_listings(raw: str) -> list[dict[str, str]]:
    """Extract server-rendered Arm Austin result cards from TalentBrew HTML."""
    section = re.search(r'<ul[^>]*id="search-results-jobs"[^>]*>(.*?)</ul>', raw, re.I | re.S)
    source = section.group(1) if section else ""
    results: list[dict[str, str]] = []
    for card in re.findall(r'<li[^>]*class="[^"]*job-card[^"]*"[^>]*>(.*?)</li>', source, re.I | re.S):
        link = re.search(r'<a[^>]*href="([^"]+)"[^>]*data-job-id="([^"]+)"[^>]*>(.*?)</a>', card, re.I | re.S)
        location = re.search(r'<span[^>]*class="location"[^>]*>(.*?)</span>', card, re.I | re.S)
        category = re.search(r'<span[^>]*class="category"[^>]*>(.*?)</span>', card, re.I | re.S)
        if link and location:
            results.append({
                "path": clean_text(link.group(1)),
                "provider_job_id": clean_text(link.group(2)),
                "title": clean_text(link.group(3)),
                "location": clean_text(location.group(1)),
                "category": clean_text(category.group(1)) if category else "",
            })
    return results


def arm_job_item(raw: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one fresh exact-Austin Arm JobPosting detail page."""
    match = re.search(r'<script\s+type="application/ld\+json">(.*?)</script>', raw, re.I | re.S)
    if not match:
        return None
    try:
        job = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    posted_match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(job.get("datePosted") or "").strip())
    posted = f"{posted_match.group(1)}-{int(posted_match.group(2)):02d}-{int(posted_match.group(3)):02d}" if posted_match else ""
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    locations: list[str] = []
    has_austin = False
    job_locations = job.get("jobLocation") or []
    if isinstance(job_locations, dict):
        job_locations = [job_locations]
    for place in job_locations:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        region = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        label = ", ".join(value for value in (city, region, country) if value)
        if label:
            locations.append(label)
        if city.casefold() == "austin" and region.casefold() in {"texas", "tx"}:
            has_austin = True
    if not has_austin:
        return None
    description = clean_text(job.get("description"))
    identifier = job.get("identifier") or ""
    if isinstance(identifier, dict):
        identifier = identifier.get("value") or identifier.get("name") or ""
    item = {
        "company": "Arm",
        "title": clean_text(job.get("title")),
        "location": " / ".join(dict.fromkeys(locations)),
        "url": canonical_public_url(clean_text(job.get("url"))),
        "source": "arm",
        "description": description,
        "date_posted": posted,
        "provider_job_id": clean_text(identifier),
        "easy_apply": 0,
        "work_arrangement": "onsite/hybrid",
    }
    item.update(extract_salary(description, job))
    return item if item["title"] and item["url"] and description else None


def arm_austin_jobs(max_pages: int = 5, request_delay_seconds: float = 2.0) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target-title records from Arm's public Austin TalentBrew pages."""
    listings: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for page in range(1, max(1, max_pages) + 1):
        endpoint = ARM_AUSTIN_BOARD if page == 1 else f"{ARM_AUSTIN_BOARD}/{page}"
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 12_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Arm search page {page}: {type(exc).__name__}")
            break
        page_items = arm_search_listings(raw)
        if not page_items:
            break
        for listing in page_items:
            if title_is_candidate(listing) and re.search(r"\bAustin,?\s+(?:TX|Texas)\b", listing["location"], re.I):
                listings[listing["path"]] = listing
        if page < max_pages:
            time.sleep(max(2.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    for path, listing in listings.items():
        endpoint = urllib.parse.urljoin(ARM_CAREERS_BASE, path)
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 12_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Arm {listing['title']}: {type(exc).__name__}")
            continue
        item = arm_job_item(raw)
        if item:
            results.append(item)
        time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def schwab_search_listings(raw: str) -> list[dict[str, str]]:
    """Extract server-rendered Schwab result cards without profile logic."""
    section = re.search(r'<section\s+id="search-results-list"[^>]*>(.*?)</section>', raw, re.I | re.S)
    source = section.group(1) if section else raw
    results: list[dict[str, str]] = []
    for card in re.findall(r'<li>(.*?)</li>', source, re.I | re.S):
        path = re.search(r'<a\s+href="(/job/[^"]+)"[^>]*data-job-id=', card, re.I)
        title = re.search(r'<h2>(.*?)</h2>', card, re.I | re.S)
        location = re.search(r'<span\s+class="job-location">(.*?)</span>', card, re.I | re.S)
        if path and title and location:
            results.append({
                "path": clean_text(path.group(1)),
                "title": clean_text(title.group(1)),
                "location": clean_text(location.group(1)),
            })
    return results


def capitalone_search_listings(raw: str) -> list[dict[str, str]]:
    """Extract dated cards from Capital One's exact-Austin TalentBrew page."""
    section = re.search(r'<section\s+id="search-results-list"[^>]*>(.*?)</section>', raw, re.I | re.S)
    source = section.group(1) if section else raw
    results: list[dict[str, str]] = []
    for card in re.findall(r'<li>(.*?)</li>', source, re.I | re.S):
        path = re.search(r'<a\s+href="(/job/[^"]+)"[^>]*data-job-id="([^"]+)"', card, re.I)
        title = re.search(r'<h2>(.*?)</h2>', card, re.I | re.S)
        location = re.search(r'<span\s+class="job-location">(.*?)</span>', card, re.I | re.S)
        posted = re.search(r'<span\s+class="job-date-posted">(.*?)</span>', card, re.I | re.S)
        if path and title and location:
            results.append({
                "path": clean_text(path.group(1)),
                "provider_job_id": clean_text(path.group(2)),
                "title": clean_text(title.group(1)),
                "location": clean_text(location.group(1)),
                "date_posted": clean_text(posted.group(1)) if posted else "",
            })
    return results


def capitalone_job_item(raw: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a fresh exact-Austin Capital One JobPosting detail."""
    match = re.search(r'<script\s+type="application/ld\+json">(.*?)</script>', raw, re.I | re.S)
    if not match:
        return None
    try:
        job = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    posted_match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(job.get("datePosted") or "").strip())
    posted = f"{posted_match.group(1)}-{int(posted_match.group(2)):02d}-{int(posted_match.group(3)):02d}" if posted_match else ""
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    locations: list[str] = []
    has_austin = False
    for place in job.get("jobLocation") or []:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        region = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        label = ", ".join(value for value in (city, region, country) if value)
        if label:
            locations.append(label)
        if city.casefold() == "austin" and region.casefold() in {"texas", "tx"}:
            has_austin = True
    if not has_austin:
        return None
    description = clean_text(job.get("description"))
    identifier = job.get("identifier") or ""
    if isinstance(identifier, dict):
        identifier = identifier.get("value") or identifier.get("name") or ""
    item = {
        "company": "Capital One",
        "title": clean_text(job.get("title")),
        "location": " / ".join(dict.fromkeys(locations)),
        "url": canonical_public_url(clean_text(job.get("url"))),
        "source": "capitalone",
        "description": description,
        "date_posted": posted,
        "provider_job_id": clean_text(identifier),
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{job.get('title', '')} {description}".casefold() else "onsite/hybrid",
    }
    austin_pay = re.search(
        r"Austin\s*,\s*TX\s*:\s*\$([\d,]+(?:\.\d+)?)\s*-\s*\$([\d,]+(?:\.\d+)?)",
        description,
        re.I,
    )
    if austin_pay:
        low = float(austin_pay.group(1).replace(",", ""))
        high = float(austin_pay.group(2).replace(",", ""))
        item.update({
            "salary_text": f"${low:,.0f} - ${high:,.0f}",
            "salary_min": low,
            "salary_max": high,
            "salary_type": "year",
        })
    else:
        item.update(extract_salary(description, job))
    return item if item["title"] and item["url"] and description else None


def capitalone_austin_jobs(max_pages: int = 3, request_delay_seconds: float = 2.0) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect Capital One's fresh target roles from its public Austin pages."""
    listings: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    total_pages = 1
    for page in range(1, max(1, max_pages) + 1):
        if page > total_pages:
            break
        endpoint = CAPITAL_ONE_AUSTIN_BOARD if page == 1 else f"{CAPITAL_ONE_AUSTIN_BOARD}/{page}"
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 12_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Capital One search page {page}: {type(exc).__name__}")
            break
        page_match = re.search(r'data-total-pages="(\d+)"', raw, re.I)
        if page_match:
            total_pages = max(1, min(int(page_match.group(1)), max_pages))
        page_items = capitalone_search_listings(raw)
        for listing in page_items:
            if title_is_candidate(listing) and re.search(r"\bAustin,?\s+(?:TX|Texas)\b", listing["location"], re.I):
                listings[listing["path"]] = listing
        if page < total_pages:
            time.sleep(max(2.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    for path, listing in listings.items():
        endpoint = urllib.parse.urljoin(CAPITAL_ONE_CAREERS_BASE, path)
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 12_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Capital One {listing['provider_job_id']}: {type(exc).__name__}")
            continue
        item = capitalone_job_item(raw)
        if item:
            results.append(item)
        time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def schwab_job_item(raw: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize an official Schwab JobPosting JSON-LD detail page."""
    match = re.search(r'<script\s+type="application/ld\+json">(.*?)</script>', raw, re.I | re.S)
    if not match:
        return None
    try:
        job = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    posted_match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(job.get("datePosted") or "").strip())
    posted = f"{posted_match.group(1)}-{int(posted_match.group(2)):02d}-{int(posted_match.group(3)):02d}" if posted_match else ""
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    has_austin = False
    locations: list[str] = []
    for place in job.get("jobLocation") or []:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        region = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        label = ", ".join(value for value in (city, region, country) if value)
        if label:
            locations.append(label)
        if city.casefold() == "austin" and region.casefold() in {"texas", "tx"}:
            has_austin = True
    if not has_austin:
        return None
    description = clean_text(job.get("description"))
    item = {
        "company": "Charles Schwab",
        "title": clean_text(job.get("title")),
        "location": " / ".join(dict.fromkeys(locations)),
        "url": clean_text(job.get("url")),
        "source": "schwab",
        "description": description,
        "date_posted": posted,
        "provider_job_id": clean_text(job.get("identifier")),
        "easy_apply": 0,
        "work_arrangement": "onsite/hybrid",
    }
    item.update(extract_salary(description, job))
    if not item.get("salary_text") and (item.get("salary_min") is not None or item.get("salary_max") is not None):
        low = item.get("salary_min") or item.get("salary_max")
        high = item.get("salary_max") or item.get("salary_min")
        item["salary_text"] = f"${float(low):,.0f} - ${float(high):,.0f} annualized"
    return item if item["title"] and item["url"] and description else None


def schwab_austin_jobs(max_pages: int = 9, request_delay_seconds: float = 2.0) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin-explicit Schwab roles from public HTML pages."""
    listings: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for page in range(1, max(1, max_pages) + 1):
        params = urllib.parse.urlencode({"k": "software", "l": "Austin, Texas", "p": page})
        endpoint = f"{SCHWAB_CAREERS_BASE}/search-jobs?{params}"
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 12_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Schwab search page {page}: {type(exc).__name__}")
            break
        page_items = schwab_search_listings(raw)
        if not page_items:
            break
        for listing in page_items:
            if title_is_candidate(listing) and re.search(r"\bAustin,?\s+(?:TX|Texas)\b", listing["location"], re.I):
                listings[listing["path"]] = listing
        if page < max_pages:
            time.sleep(1.0)

    results: list[dict[str, Any]] = []
    for path, listing in listings.items():
        endpoint = urllib.parse.urljoin(SCHWAB_CAREERS_BASE, path)
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = _response_body(response, 15_000_000).decode("utf-8", "replace")
            item = schwab_job_item(raw)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Schwab {listing['title']}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def deloitte_search_listings(raw: str, confirmed_location: str | None = None) -> list[dict[str, str]]:
    """Parse Deloitte result rows, optionally carrying an official search-filter location."""
    listings: list[dict[str, str]] = []
    for block in re.findall(r'<article\b[^>]*class="[^"]*article--result[^"]*"[^>]*>(.*?)</article>', raw, re.I | re.S):
        match = re.search(r'<a\b[^>]*href="([^"]*/JobDetail/[^"]+)"[^>]*>(.*?)</a>', block, re.I | re.S)
        if not match:
            continue
        spans = re.findall(r'<span\b[^>]*>(.*?)</span>', block, re.I | re.S)
        location = clean_text(confirmed_location) if confirmed_location else (clean_text(spans[-1]) if spans else "")
        if not re.fullmatch(r"Austin,?\s+Texas,?\s+United States", location, re.I):
            continue
        listings.append({"url": clean_text(match.group(1)), "title": clean_text(match.group(2)), "location": location})
    return listings


def deloitte_job_item(raw: str, url: str, confirmed_location: str | None = None, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a Deloitte JobPosting page with first-party Austin evidence."""
    postings: list[dict[str, Any]] = []
    for value in re.findall(r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting" and candidate.get("title"):
            postings.append(candidate)
    if not postings:
        return None
    location_evidence = clean_text(confirmed_location) if confirmed_location else clean_text(raw)
    if not re.search(r"\bAustin,?\s+(?:TX|Texas)(?:,?\s+United States)?\b", location_evidence, re.I):
        return None
    posting = max(postings, key=lambda value: len(clean_text(value.get("description"))))
    posted = str(posting.get("datePosted") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(posting.get("description"))
    identifier = next((value.get("identifier") for value in postings if value.get("identifier")), {})
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    display_title = min((clean_text(value.get("title")) for value in postings if clean_text(value.get("title"))), key=len)
    item = {
        "company": "Deloitte",
        "title": display_title,
        "location": "Austin, TX",
        "url": clean_text(url),
        "source": "deloitte",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if item["title"] and item["url"] and description else None


def deloitte_austin_jobs(
    max_pages: int = 50,
    request_delay_seconds: float = 2.0,
    search_delay_seconds: float = 1.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from Deloitte's public Austin-filtered pages."""
    confirmed_location = "Austin, Texas, United States"
    listings: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for page in range(max(1, max_pages)):
        params = urllib.parse.urlencode({
            "9336": f"[{DELOITTE_TEXAS_OPTION_ID}]",
            "9336_format": "5912",
            "9337": f"[{DELOITTE_AUSTIN_OPTION_ID}]",
            "9337_format": "5912",
            "listFilterMode": "1",
            "jobRecordsPerPage": "10",
            "jobOffset": str(page * 10),
            "sort": "relevancy",
        })
        endpoint = f"{DELOITTE_AUSTIN_BOARD}?{params}"
        request = urllib.request.Request(
            endpoint,
            headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
        )
        raw = ""
        search_error: Exception | None = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = _response_body(response, 15_000_000).decode("utf-8", "replace")
                search_error = None
                break
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, ValueError) as exc:
                search_error = exc
                if attempt == 0:
                    time.sleep(max(1.0, float(search_delay_seconds)))
        if search_error is not None:
            errors.append(f"Deloitte search page {page + 1}: {type(search_error).__name__}")
            break
        page_items = deloitte_search_listings(raw, confirmed_location)
        if not page_items:
            break
        for listing in page_items:
            if title_is_candidate(listing):
                listings[listing["url"]] = listing
        if len(page_items) < 10:
            break
        time.sleep(max(1.0, float(search_delay_seconds)))

    results: list[dict[str, Any]] = []
    detail_delay = max(2.0, float(request_delay_seconds))
    for index, (endpoint, listing) in enumerate(listings.items()):
        if index:
            time.sleep(detail_delay)
        request = urllib.request.Request(
            endpoint,
            headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
        )
        raw = ""
        detail_error: Exception | None = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = _response_body(response, 15_000_000).decode("utf-8", "replace")
                detail_error = None
                break
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, ValueError) as exc:
                detail_error = exc
                if attempt == 0:
                    time.sleep(detail_delay)
        if detail_error is not None:
            errors.append(f"Deloitte {listing['title']}: {type(detail_error).__name__}")
            continue
        item = deloitte_job_item(
            raw,
            endpoint,
            confirmed_location=confirmed_location,
            max_age_days=max_age_days,
        )
        if item:
            results.append(item)
    return results, errors


def cisco_job_item(raw: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a Cisco Phenom detail reached through the official Austin filter."""
    payload = _phenom_ddo(raw).get("jobDetail") or {}
    job = ((payload.get("data") or {}).get("job") or {}) if isinstance(payload, dict) else {}
    if not isinstance(job, dict) or not job:
        return None
    locations = job.get("multi_location") or []
    if not isinstance(locations, list):
        locations = []
    location_text = " / ".join(clean_text(value.get("location") if isinstance(value, dict) else value) for value in locations)
    location_text = location_text or clean_text(job.get("location") or job.get("cityStateCountry"))
    if not re.search(r"\bAustin,?\s+Texas\b", location_text, re.I):
        return None
    posted = str(job.get("postedDate") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    listing = {
        "jobId": clean_text(job.get("jobId") or job.get("reqId")),
        "title": clean_text(job.get("title")),
        "multi_location": locations,
    }
    item = phenom_job_item("Cisco", CISCO_CAREERS_BASE, listing, raw)
    item.update({
        "source": "cisco",
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "provider_job_id": listing["jobId"],
        "work_arrangement": "remote" if "remote" in clean_text(job.get("RemoteType") or job.get("remoteType") or job.get("remote")).casefold() else "onsite/hybrid",
    })
    return item


def cisco_austin_jobs(
    max_pages: int = 130,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from Cisco's public Phenom inventory.

    Cisco's city facet is browser-state-dependent, but each server-rendered
    offset page includes complete multi-location data and the authoritative
    Austin facet count. Scan until every Austin requisition represented by
    that count has been observed, continuing through the full inventory when
    the default result order does not cluster the Austin records.
    """
    listings: dict[str, dict[str, Any]] = {}
    austin_ids: set[str] = set()
    expected_austin: int | None = None
    errors: list[str] = []
    for page in range(max(1, max_pages)):
        separator = "&" if "?" in CISCO_AUSTIN_BOARD else "?"
        endpoint = f"{CISCO_AUSTIN_BOARD}{separator}from={page * 10}"
        try:
            request = urllib.request.Request(
                endpoint,
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(8_000_000).decode("utf-8", "replace")
            ddo = _phenom_ddo(raw).get("eagerLoadRefineSearch") or {}
            data = ddo.get("data") or {} if isinstance(ddo, dict) else {}
            page_items = [item for item in data.get("jobs") or [] if isinstance(item, dict)]
            if page == 0:
                for aggregation in data.get("aggregations") or []:
                    if isinstance(aggregation, dict) and aggregation.get("field") == "city":
                        values = aggregation.get("value") or {}
                        if isinstance(values, dict) and "Austin" in values:
                            expected_austin = int(values["Austin"])
                            break
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Cisco search page {page + 1}: {type(exc).__name__}")
            break
        if not page_items:
            break
        for listing in page_items:
            job_id = clean_text(listing.get("jobId") or listing.get("reqId"))
            if not job_id or not phenom_listing_has_austin(listing):
                continue
            austin_ids.add(job_id)
            if _fresh_iso_listing(listing.get("postedDate"), max_age_days) and title_is_candidate(listing):
                listings[job_id] = listing
        if expected_austin is not None and len(austin_ids) >= expected_austin:
            break
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    for job_id, listing in listings.items():
        title = clean_text(listing.get("title"))
        slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
        endpoint = f"{CISCO_CAREERS_BASE}/job/{job_id}/{slug}"
        try:
            request = urllib.request.Request(
                endpoint,
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(8_000_000).decode("utf-8", "replace")
            item = cisco_job_item(raw, max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Cisco {job_id}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def ibm_avature_posting_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a browser-collected IBM Avature detail with explicit Austin evidence."""
    title = clean_text(record.get("title"))
    description = clean_text(record.get("description"))
    url = canonical_public_url(record.get("url") or record.get("canonical") or record.get("_source_url"))
    location_evidence = clean_text(record.get("official_location") or record.get("location"))
    if not (
        re.search(r"\bAustin\b", location_evidence, re.I)
        and re.search(r"\bTexas\b", location_evidence, re.I)
        and re.search(r"\bUnited States\b", location_evidence, re.I)
    ):
        return None
    posted = str(record.get("date_posted") or record.get("datePosted") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    provider_job_id = clean_text(record.get("provider_job_id") or record.get("job_id"))
    if not provider_job_id:
        match = re.search(r"/(\d+)(?:[/?#]|$)", url)
        provider_job_id = match.group(1) if match else ""
    arrangement = clean_text(record.get("work_arrangement"))
    if not arrangement:
        arrangement = "remote" if re.search(r"\b(?:remote|work from home)\b", description, re.I) else "onsite/hybrid"
    item = {
        "company": "IBM",
        "title": title,
        "location": "Austin, TX / Multiple US locations",
        "url": url,
        "source": "avature",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": arrangement,
    }
    item.update(extract_salary(description, record))
    return item if title and url and description else None


def ea_avature_posting_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize an EA Avature detail captured from the public careers portal.

    EA's displayed heading may omit the level even when the canonical slug and
    detail body identify a senior role. Browser callers therefore supply the
    complete official title they observed, while this boundary independently
    enforces a fresh date, exact Austin address, canonical EA URL, and full
    description before the record can be persisted.
    """
    title = clean_text(record.get("canonical_title") or record.get("title"))
    description = clean_text(record.get("description"))
    url = canonical_public_url(record.get("url") or record.get("canonical") or record.get("_source_url"))
    location_evidence = clean_text(record.get("official_location") or record.get("location"))
    if not (
        re.search(r"\bAustin\b", location_evidence, re.I)
        and re.search(r"\bTexas\b", location_evidence, re.I)
        and re.search(r"\bUnited States(?: of America)?\b", location_evidence, re.I)
    ):
        return None
    if not re.search(r"^https://jobs\.ea\.com/", url, re.I):
        return None
    posted = str(record.get("date_posted") or record.get("datePosted") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    provider_job_id = clean_text(record.get("provider_job_id") or record.get("job_id"))
    if not provider_job_id:
        match = re.search(r"/(\d+)(?:[/?#]|$)", url)
        provider_job_id = match.group(1) if match else ""
    if not provider_job_id:
        return None
    arrangement = clean_text(record.get("work_arrangement"))
    if not arrangement:
        arrangement = "remote" if re.search(r"\bremote\b", description, re.I) else "onsite/hybrid"
    item = {
        "company": "Electronic Arts",
        "title": title,
        "location": "Austin, TX",
        "url": url,
        "source": "avature",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": arrangement,
    }
    item.update(extract_salary(description, record))
    return item if title and url and description else None


def ibm_search_job_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize an IBM public-search hit with explicit Austin, Texas text.

    IBM's search index exposes authoritative dates and full descriptions, but
    renders multi-city roles as ``Multiple Cities``. Keep those records in the
    browser-verification path and only automate hits whose official title or
    body itself names Austin, Texas.
    """
    title = clean_text(record.get("title"))
    description = clean_text(record.get("body") or record.get("description"))
    url = canonical_public_url(record.get("url"))
    country = clean_text(record.get("field_keyword_05"))
    display_location = clean_text(record.get("field_keyword_19"))
    location_evidence = " ".join((title, description))
    if country.casefold() != "united states" or not re.search(
        r"\bAustin,?\s+(?:TX|Texas)\b", location_evidence, re.I
    ):
        return None
    posted = str(record.get("dcdate") or record.get("effectivedate") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    match = re.search(r"[?&]jobId=(\d+)(?:[&#]|$)", url, re.I)
    provider_job_id = match.group(1) if match else ""
    if not provider_job_id:
        return None
    arrangement = "remote" if clean_text(record.get("field_keyword_17")).casefold() == "remote" else "onsite/hybrid"
    item = {
        "company": "IBM",
        "title": title,
        "location": "Austin, TX" if display_location.casefold() == "austin, us" else "Austin, TX / Multiple US locations",
        "url": url,
        "source": "avature",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": arrangement,
    }
    item.update(extract_salary(description, record))
    return item if title and url and description else None


def ibm_austin_jobs(
    max_pages: int = 10,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect IBM roles whose public search record explicitly names Austin, Texas."""
    payload = {
        "appId": "careers",
        "scopes": ["careers2"],
        "size": 100,
        "from": 0,
        "query": {
            "bool": {
                "must": [{
                    "simple_query_string": {
                        "query": "Austin",
                        "fields": ["keywords^1", "body^1", "url^2", "description^2", "h1s_content^2", "title^3"],
                    }
                }]
            }
        },
        "_source": [
            "title", "url", "body", "description", "dcdate", "effectivedate",
            "field_keyword_05", "field_keyword_08", "field_keyword_17",
            "field_keyword_18", "field_keyword_19",
        ],
    }
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for page in range(max(1, max_pages)):
        payload["from"] = page * 100
        try:
            request = urllib.request.Request(
                IBM_SEARCH_API,
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "User-Agent": "EliOpportunityQueue/1.0",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                response_payload = json.loads(_response_body(response, 20_000_000))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"IBM public search page {page + 1}: {type(exc).__name__}")
            break
        hits = (((response_payload.get("hits") or {}).get("hits") or []) if isinstance(response_payload, dict) else [])
        for hit in hits:
            source = hit.get("_source") or {} if isinstance(hit, dict) else {}
            if not isinstance(source, dict) or not title_is_candidate(source):
                continue
            item = ibm_search_job_item(source, max_age_days=max_age_days)
            if item:
                results.append(item)
        total = int((((response_payload.get("hits") or {}).get("total") or {}).get("value") or 0))
        if len(hits) < 100 or (page + 1) * 100 >= total:
            break
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def salesforce_job_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a browser-collected Salesforce detail with explicit Austin evidence."""
    title = clean_text(record.get("title"))
    description = clean_text(record.get("description"))
    url = canonical_public_url(record.get("url") or record.get("_source_url"))
    locations = record.get("official_locations") or record.get("locations") or []
    if not isinstance(locations, list):
        locations = [locations]
    location_text = " / ".join(clean_text(value) for value in locations)
    if not re.search(r"(?:\bTexas\s*-\s*Austin\b|\bAustin,?\s+(?:TX|Texas)\b)", location_text, re.I):
        return None
    if not re.fullmatch(r"https://www\.salesforce\.com/company/careers/jobs/JR\d+/[^?#]+/?", url, re.I):
        return None
    posted = str(record.get("date_posted") or record.get("datePosted") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    provider_job_id = clean_text(record.get("provider_job_id"))
    if not provider_job_id:
        match = re.search(r"/(JR\d+)(?:/|$)", url, re.I)
        provider_job_id = match.group(1).upper() if match else ""
    arrangement = clean_text(record.get("work_arrangement"))
    if not arrangement:
        arrangement = "remote" if "remote" in location_text.casefold() else "onsite/hybrid"
    item = {
        "company": "Salesforce",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": url,
        "source": "salesforce",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": arrangement,
    }
    item.update(extract_salary(description, record))
    return item if title and url and description else None


def salesforce_feed_job_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one posting from Salesforce's public static careers feed."""
    if not isinstance(record, dict):
        return None
    title = clean_text(record.get("Job_Posting_Title"))
    provider_job_id = clean_text(record.get("Job_Requisition_Ref_ID")).upper()
    if not re.fullmatch(r"JR\d+", provider_job_id) or not title:
        return None
    locations = [clean_text(record.get("Job_Requisition_Primary_Location"))]
    locations.extend(
        clean_text(value)
        for value in str(record.get("Job_Requisition_Additional_Locations") or "").split(";")
    )
    locations = [value for value in locations if value]
    if not any(re.fullmatch(r"Texas\s*-\s*Austin", value, re.I) for value in locations):
        return None
    posted = str(record.get("External_Job_Posting_Start_Date") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    normalized_title = "".join(
        character
        for character in unicodedata.normalize("NFKD", title)
        if not unicodedata.combining(character)
    ).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized_title).strip("-") or "job-details"
    description = " ".join(
        clean_text(record.get(field))
        for field in (
            "Job_Description",
            "Fair_Chance_Ordinance_Statement",
            "US_Compensation_Verbiage_Statement",
            "Pay_Transparency_Text_if_location_region_is__Non-Sales-NAT_US___Geo_A_SEL_",
        )
        if clean_text(record.get(field))
    )
    return salesforce_job_item({
        "title": title,
        "official_locations": locations,
        "url": f"{SALESFORCE_CAREERS_BASE}/{provider_job_id}/{slug}/",
        "provider_job_id": provider_job_id,
        "date_posted": posted,
        "description": description,
    }, max_age_days=max_age_days)


def salesforce_austin_jobs(
    max_age_days: int = 30,
    request_delay_seconds: float = 2.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh exact-Austin roles from Salesforce's public careers feed."""
    payload: dict[str, Any] | None = None
    last_error: Exception | None = None
    for position, url in enumerate((SALESFORCE_JOBS_FEED, SALESFORCE_JOBS_BACKUP_FEED)):
        if position and request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                candidate = json.loads(_response_body(response, 20_000_000))
            if not isinstance(candidate, dict) or not isinstance(candidate.get("Report_Entry"), list):
                raise ValueError("unexpected Salesforce jobs payload")
            payload = candidate
            break
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
    if payload is None:
        return [], [f"Salesforce public jobs feed: {type(last_error).__name__ if last_error else 'Unavailable'}"]

    results: list[dict[str, Any]] = []
    for record in payload.get("Report_Entry") or []:
        if not isinstance(record, dict) or not title_is_candidate({"title": record.get("Job_Posting_Title")}):
            continue
        item = salesforce_feed_job_item(record, max_age_days=max_age_days)
        if item:
            results.append(item)
    return results, []


def meta_job_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a browser-collected Meta detail with explicit Austin evidence."""
    title = clean_text(record.get("title"))
    description = clean_text(record.get("description"))
    url = canonical_public_url(record.get("url") or record.get("_source_url"))
    locations = record.get("official_locations") or record.get("locations") or []
    if not isinstance(locations, list):
        locations = [locations]
    location_text = " / ".join(clean_text(value) for value in locations)
    if not re.search(r"\bAustin,?\s+(?:TX|Texas)\b", location_text, re.I):
        return None
    if not re.fullmatch(r"https://www\.metacareers\.com/profile/job_details/\d+/?", url, re.I):
        return None
    posted = str(record.get("date_posted") or record.get("datePosted") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    provider_job_id = clean_text(record.get("provider_job_id"))
    if not provider_job_id:
        match = re.search(r"/job_details/(\d+)(?:/|$)", url, re.I)
        provider_job_id = match.group(1) if match else ""
    arrangement = clean_text(record.get("work_arrangement"))
    if not arrangement:
        arrangement = "remote" if "remote" in location_text.casefold() else "onsite/hybrid"
    item = {
        "company": "Meta",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": url,
        "source": "meta",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": arrangement,
    }
    item.update(extract_salary(description, record))
    return item if title and url and description else None


def meta_posting_item(
    posting: dict[str, Any],
    url: str,
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize Meta's public JobPosting JSON-LD with exact Austin evidence."""
    if not isinstance(posting, dict) or posting.get("@type") != "JobPosting":
        return None
    locations: list[str] = []
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    for place in raw_locations:
        if not isinstance(place, dict):
            continue
        label = clean_text(place.get("name"))
        address = place.get("address") or {}
        if not label and isinstance(address, dict):
            label = ", ".join(
                value
                for value in (
                    clean_text(address.get("addressLocality")),
                    clean_text(address.get("addressRegion")),
                    clean_text(address.get("addressCountry")),
                )
                if value
            )
        if label:
            locations.append(label)
    description = clean_text(" ".join(
        str(posting.get(field) or "")
        for field in ("description", "responsibilities", "qualifications", "skills")
    ))
    record = dict(posting)
    record.update({
        "title": posting.get("title"),
        "official_locations": locations,
        "url": url,
        "date_posted": posting.get("datePosted"),
        "description": description,
    })
    return meta_job_item(record, max_age_days=max_age_days)


def meta_austin_jobs(
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect Meta roles from its anonymous official search and detail pages."""
    delay = max(2.0, float(request_delay_seconds))
    headers = {
        "User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        request = urllib.request.Request(META_AUSTIN_BOARD, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            search_html = _response_body(response, 8_000_000).decode("utf-8", "replace")
        token_match = re.search(r'\["LSD",\[\],\{"token":"([^"]+)"', search_html)
        if not token_match:
            raise ValueError("missing anonymous request token")
        token = token_match.group(1)
        search_input = {
            "q": None,
            "divisions": [],
            "offices": ["Austin, TX"],
            "roles": [],
            "leadership_levels": [],
            "saved_jobs": [],
            "saved_searches": [],
            "sub_teams": [],
            "teams": [],
            "is_leadership": False,
            "is_remote_only": False,
            "sort_by_new": False,
            "results_per_page": None,
        }
        form = urllib.parse.urlencode({
            "__user": "0",
            "__a": "1",
            "__comet_req": "15",
            "lsd": token,
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "CareersJobSearchResultsV2DataQuery",
            "variables": json.dumps({
                "isLoggedIn": False,
                "search_input": search_input,
                "viewasUserID": None,
            }, separators=(",", ":")),
            "server_timestamps": "true",
            "doc_id": META_SEARCH_DOCUMENT_ID,
        }).encode()
        time.sleep(delay)
        request = urllib.request.Request(
            META_GRAPHQL_API,
            data=form,
            headers={
                "User-Agent": headers["User-Agent"],
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": META_AUSTIN_BOARD,
                "X-FB-LSD": token,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw_payload = _response_body(response, 20_000_000).decode("utf-8", "replace")
        raw_payload = re.sub(r"^for\s*\(;;\);", "", raw_payload).strip()
        payload = json.loads(raw_payload)
        search = (payload.get("data") or {}).get("job_search_with_featured_jobs_v2") or {}
        listings = search.get("all_jobs") or [] if isinstance(search, dict) else []
        if not isinstance(listings, list):
            raise ValueError("unexpected Meta search payload")
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, TypeError, json.JSONDecodeError) as exc:
        return [], [f"Meta public search: {type(exc).__name__}"]

    candidates: dict[str, dict[str, Any]] = {}
    for listing in listings:
        if not isinstance(listing, dict):
            continue
        # Search cards omit the description needed to distinguish a data-platform
        # people manager from a reporting/product manager. Admit the title for
        # detail retrieval; meta_posting_item applies the full relevance gate.
        title = clean_text(listing.get("title")).casefold()
        data_platform_manager = "data platform" in title and "manager" in title and "product" not in title
        if not (title_is_candidate(listing) or data_platform_manager):
            continue
        locations = listing.get("locations") or []
        if not isinstance(locations, list) or not any(
            re.fullmatch(r"Austin,?\s+(?:TX|Texas)", clean_text(value), re.I)
            for value in locations
        ):
            continue
        provider_job_id = clean_text(listing.get("id"))
        if re.fullmatch(r"\d+", provider_job_id):
            candidates[provider_job_id] = listing

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for provider_job_id in candidates:
        time.sleep(delay)
        url = f"{META_CAREERS_BASE}/profile/job_details/{provider_job_id}/"
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                detail_html = _response_body(response, 8_000_000).decode("utf-8", "replace")
            posting: dict[str, Any] | None = None
            for value in re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                detail_html,
                re.I | re.S,
            ):
                try:
                    candidate = json.loads(value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                    posting = candidate
                    break
            if posting is None:
                raise ValueError("missing JobPosting detail")
            item = meta_posting_item(posting, url, max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"Meta {provider_job_id}: {type(exc).__name__}")
    return results, errors


def uber_job_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a browser-collected Uber detail with explicit Austin evidence."""
    title = clean_text(record.get("title"))
    description = clean_text(record.get("description"))
    url = canonical_public_url(record.get("url") or record.get("_source_url"))
    locations = record.get("official_locations") or record.get("locations") or []
    if not isinstance(locations, list):
        locations = [locations]
    location_text = " / ".join(clean_text(value) for value in locations)
    if not re.search(r"\bAustin,?\s+(?:TX|Texas)\b", location_text, re.I):
        return None
    if not re.fullmatch(r"https://jobs\.uber\.com/en/jobs/\d+/?", url, re.I):
        return None
    posted = str(record.get("date_posted") or record.get("datePosted") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    provider_job_id = clean_text(record.get("provider_job_id"))
    if not provider_job_id:
        match = re.search(r"/jobs/(\d+)(?:/|$)", url, re.I)
        provider_job_id = match.group(1) if match else ""
    arrangement = clean_text(record.get("work_arrangement"))
    if not arrangement:
        arrangement = "remote" if "remote" in location_text.casefold() else "onsite/hybrid"
    item = {
        "company": "Uber",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": url,
        "source": "uber",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": arrangement,
    }
    item.update(extract_salary(description, record))
    return item if title and url and description else None


def walmart_job_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a browser-collected Walmart detail with explicit Austin evidence."""
    title = clean_text(record.get("title"))
    description = clean_text(record.get("description"))
    url = canonical_public_url(record.get("url") or record.get("_source_url"))
    location_text = clean_text(record.get("official_location") or record.get("location"))
    if not re.search(r"\bAustin,?\s+(?:TX|Texas)\b", location_text, re.I):
        return None
    if not re.fullmatch(r"https://careers\.walmart\.com/us/en/jobs/R-\d+/?", url, re.I):
        return None
    posted = str(record.get("date_posted") or record.get("datePosted") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    provider_job_id = clean_text(record.get("provider_job_id"))
    if not provider_job_id:
        match = re.search(r"/jobs/(R-\d+)(?:/|$)", url, re.I)
        provider_job_id = match.group(1).upper() if match else ""
    arrangement = clean_text(record.get("work_arrangement"))
    if not arrangement:
        arrangement = "remote" if "remote" in location_text.casefold() else "onsite/hybrid"
    item = {
        "company": "Walmart",
        "title": title,
        "location": "Austin, TX",
        "url": url,
        "source": "walmart",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_job_id,
        "easy_apply": 0,
        "work_arrangement": arrangement,
    }
    item.update(extract_salary(description, record))
    return item if title and url and description else None


def accenture_job_item(posting: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize Accenture's official JobPosting JSON-LD with exact Austin evidence."""
    if not isinstance(posting, dict) or posting.get("@type") != "JobPosting":
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    locations: list[str] = []
    has_austin = False
    for place in raw_locations:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        region = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        if city.casefold() == "austin" and region.casefold() in {"tx", "texas"}:
            has_austin = True
        label = ", ".join(value for value in (city, region, country) if value and value.casefold() != "unavailable")
        if label:
            locations.append(label)
    if not has_austin:
        return None
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    if not re.fullmatch(r"R\d+", provider_job_id, re.I):
        return None
    source_url = canonical_public_url(posting.get("_source_url") or posting.get("url"))
    parsed = urllib.parse.urlsplit(source_url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    if parsed.netloc.casefold() != "www.accenture.com" or parsed.path != "/us-en/careers/jobdetails" or query.get("id", "").casefold() != f"{provider_job_id}_en".casefold():
        return None
    canonical_url = f"https://www.accenture.com/us-en/careers/jobdetails?id={provider_job_id.upper()}_en"
    description = clean_text(" ".join(str(posting.get(key) or "") for key in ("description", "responsibilities", "qualifications", "skills")))
    title = clean_text(posting.get("title"))
    item = {
        "company": "Accenture",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": canonical_url,
        "source": "accenture",
        "description": description,
        "date_posted": posted or None,
        "provider_job_id": provider_job_id.upper(),
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in description.casefold() else "onsite/hybrid",
    }
    # Accenture publishes several state-specific ranges on multi-location jobs.
    # Never attach another state's range to the Austin record.
    texas_range = re.search(
        r"(?:In\s+)?Texas[^$]{0,220}\$([\d,]+(?:\.\d+)?)\s*(?:-|–|to)\s*\$([\d,]+(?:\.\d+)?)",
        description,
        re.I,
    )
    if texas_range:
        salary_min = float(texas_range.group(1).replace(",", ""))
        salary_max = float(texas_range.group(2).replace(",", ""))
        item.update({
            "salary_text": format_salary_range(salary_min, salary_max),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_type": "posted",
        })
    else:
        item.update({"salary_text": "", "salary_min": None, "salary_max": None, "salary_type": "unknown"})
    return item if title and description else None


def accenture_search_job_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one record from Accenture's public exact-Austin search API."""
    if not isinstance(record, dict):
        return None
    raw_locations = record.get("location") or []
    if isinstance(raw_locations, str):
        raw_locations = [raw_locations]
    locations = [clean_text(value) for value in raw_locations if clean_text(value)]
    if not any(value.casefold() in {"austin, tx", "austin, texas"} for value in locations):
        return None
    provider_job_id = clean_text(record.get("requisitionId")).upper()
    if not re.fullmatch(r"R\d+", provider_job_id):
        return None
    title = clean_text(record.get("title"))
    raw_families = record.get("jobFamilyGroup") or []
    if isinstance(raw_families, str):
        raw_families = [raw_families]
    families = {clean_text(value).casefold() for value in raw_families if clean_text(value)}
    engineering_families = {
        "software engineering", "ai & data", "technology & information architectures", "security",
    }
    if not families.intersection(engineering_families) and not re.search(
        r"\b(?:engineer(?:ing)?|developer|site reliability|sre)\b", title, re.I,
    ):
        return None
    skills: list[str] = []
    for key in ("workdaySkill", "mustHaveSkills", "goodToHaveSkills"):
        value = record.get(key) or []
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            skills.extend(clean_text(item) for item in value if clean_text(item))
    job_locations = []
    for value in locations:
        city, separator, region = value.rpartition(",")
        job_locations.append({"address": {
            "addressLocality": clean_text(city if separator else value),
            "addressRegion": clean_text(region) if separator else "",
            "addressCountry": "USA",
        }})
    posting = {
        "@type": "JobPosting",
        "title": title,
        "datePosted": clean_text(record.get("updateDate")),
        "jobLocation": job_locations,
        "identifier": {"value": provider_job_id},
        "description": clean_text(record.get("jobDescription") or record.get("jobDescriptionClean")),
        "qualifications": clean_text(record.get("qualification") or record.get("qualificationClean")),
        "skills": " ".join(dict.fromkeys(skills)),
        "_source_url": f"{ACCENTURE_CAREERS_BASE}/us-en/careers/jobdetails?id={provider_job_id}_en",
    }
    item = accenture_job_item(posting, max_age_days=max_age_days)
    if not item:
        return None
    remote_type = clean_text(record.get("remoteType")).casefold()
    if "remote" in remote_type and "hybrid" not in remote_type:
        item["work_arrangement"] = "remote"
    elif "hybrid" in remote_type:
        item["work_arrangement"] = "hybrid"
    return item


def accenture_austin_jobs(
    max_pages: int = 10,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin jobs from Accenture's public careers search API."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    delay = max(2.0, float(request_delay_seconds))
    total = 1
    fetched = 0
    page_size = 100
    for page in range(max(1, int(max_pages))):
        if fetched >= total:
            break
        if page:
            time.sleep(delay)
        fields = {
            "startIndex": page * page_size,
            "maxResultSize": page_size,
            "jobKeyword": "",
            "jobCountry": "USA",
            "jobLanguage": "en",
            "countrySite": "us-en",
            "sortBy": 2,
            "searchType": "vectorSearch",
            "enableQueryBoost": "true",
            "minScore": 0.7,
            "getFeedbackJudgmentEnabled": "true",
            "useCleanEmbedding": "true",
            "score": "true",
            "totalHits": "true",
            "debugQuery": "false",
            "jobFilters": json.dumps([{
                "fieldName": "location.keyword", "items": ["Austin, TX"], "multiSelect": False,
            }], separators=(",", ":")),
        }
        request = urllib.request.Request(
            ACCENTURE_JOBS_API,
            data=urllib.parse.urlencode(fields).encode(),
            headers={
                "User-Agent": "EliOpportunityQueue/1.0",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(_response_body(response, 100_000_000).decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Accenture search page {page + 1}: {type(exc).__name__}")
            break
        data = payload.get("data") or [] if isinstance(payload, dict) else []
        if not isinstance(data, list):
            errors.append("Accenture search: ValueError")
            break
        total_hits = payload.get("totalHits") if isinstance(payload, dict) else {}
        total = int((total_hits or {}).get("total") or 0) if isinstance(total_hits, dict) else 0
        fetched += len(data)
        for record in data:
            if not isinstance(record, dict) or not title_is_candidate({"title": clean_text(record.get("title"))}):
                continue
            if not _fresh_iso_listing(record.get("updateDate"), max_age_days):
                continue
            item = accenture_search_job_item(record, max_age_days=max_age_days)
            if item and item["url"] not in seen:
                seen.add(item["url"])
                results.append(item)
        if not data:
            break
    if fetched < total:
        errors.append(f"Accenture search: incomplete public result set ({fetched}/{total})")
    return results, errors


def homedepot_job_record(job: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one Home Depot public search/detail record with exact Austin evidence."""
    if not isinstance(job, dict) or clean_text(job.get("entity_status")).casefold() not in {"", "open"}:
        return None
    if job.get("is_posted") is False:
        return None
    city = clean_text(job.get("primary_city"))
    state = clean_text(job.get("primary_state"))
    country = clean_text(job.get("primary_country"))
    if city.casefold() != "austin" or state.casefold() not in {"tx", "texas"} or country.casefold() not in {"us", "usa", "united states"}:
        return None
    raw_date = clean_text(job.get("open_date"))
    try:
        posted = datetime.strptime(raw_date, "%B %d, %Y").date().isoformat()
    except ValueError:
        posted = raw_date[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    title = clean_text(job.get("title"))
    description = clean_text(job.get("description"))
    url = canonical_public_url(job.get("url"))
    location_type = clean_text(job.get("location_type"))
    item = {
        "company": "The Home Depot",
        "title": title,
        "location": "Austin, TX",
        "url": url,
        "source": "homedepot",
        "description": description,
        "date_posted": posted,
        "provider_job_id": clean_text(job.get("ref") or job.get("clientid") or job.get("id")),
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{location_type} {title}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(f"{clean_text(job.get('level'))} {description}"))
    return item if title and url and description else None


def homedepot_job_item(raw: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a Home Depot detail page when its official work location is Austin."""
    match = re.search(r"var\s+current_job\s*=\s*(\{.*?\})\s*;</script>", raw, re.I | re.S)
    if not match:
        return None
    try:
        job = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return homedepot_job_record(job, max_age_days=max_age_days)


def homedepot_austin_jobs(
    max_pages: int = 2,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
    search_queries: tuple[str, ...] = HOME_DEPOT_SEARCH_QUERIES,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from Home Depot's public exact-Austin search API."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    delay = max(2.0, float(request_delay_seconds))
    request_count = 0
    headers = {"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"}
    location_filter = json.dumps({"address": "Austin, TX"}, separators=(",", ":"))
    for search_query in search_queries:
        for page in range(max(1, int(max_pages))):
            if request_count:
                time.sleep(delay)
            request_count += 1
            params = urllib.parse.urlencode({
                "companyName": HOME_DEPOT_COMPANY_NAME,
                "query": search_query,
                "pageSize": 100,
                "offset": page * 100,
                "locationFilter": location_filter,
                "orderBy": "posting_publish_time desc",
            })
            request = urllib.request.Request(f"{HOME_DEPOT_JOBS_API}?{params}", headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read(25_000_000))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"The Home Depot {search_query} page {page + 1}: {type(exc).__name__}")
                break
            rows = payload.get("searchResults") or [] if isinstance(payload, dict) else []
            for row in rows:
                job = row.get("job") if isinstance(row, dict) else None
                if not isinstance(job, dict):
                    continue
                stable_id = clean_text(job.get("ref") or job.get("clientid") or job.get("id") or job.get("url"))
                if not stable_id or stable_id in seen_ids:
                    continue
                if not title_is_candidate({"title": clean_text(job.get("title"))}):
                    continue
                item = homedepot_job_record(job, max_age_days=max_age_days)
                if item:
                    seen_ids.add(stable_id)
                    results.append(item)
            total = int(payload.get("totalHits") or 0) if isinstance(payload, dict) else 0
            if (page + 1) * 100 >= total or not rows:
                break
    return results, errors


def amazon_job_item(job: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one Amazon Jobs record only when Austin is an official work location."""
    parsed_locations: list[dict[str, Any]] = []
    for raw_location in job.get("locations") or []:
        if isinstance(raw_location, dict):
            parsed_locations.append(raw_location)
            continue
        try:
            value = json.loads(str(raw_location))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            parsed_locations.append(value)
    austin_locations = [
        value for value in parsed_locations
        if clean_text(value.get("city") or value.get("normalizedCityName")).casefold() == "austin"
        and clean_text(value.get("normalizedCountryCode") or value.get("countryIso3a")).casefold() in {"usa", "us"}
    ]
    primary_location = clean_text(job.get("location"))
    if not austin_locations and not re.search(r"\b(?:US,\s*TX,\s*)?Austin\b", primary_location, re.I):
        return None

    description = clean_text(" ".join(str(job.get(key) or "") for key in (
        "description", "basic_qualifications", "preferred_qualifications",
    )))
    posted = None
    raw_date = clean_text(job.get("posted_date"))
    if raw_date:
        try:
            posted = datetime.strptime(re.sub(r"\s+", " ", raw_date), "%B %d, %Y").date().isoformat()
        except ValueError:
            posted = raw_date[:10] or None
    if not posted or not _fresh_iso_listing(posted, max_age_days):
        return None
    remote = any(clean_text(value.get("type")).casefold() == "remote" for value in austin_locations)
    path = str(job.get("job_path") or "").strip()
    if not path:
        return None
    item = {
        "company": "Amazon",
        "title": clean_text(job.get("title")),
        "location": "Austin, TX",
        "url": urllib.parse.urljoin("https://www.amazon.jobs", path),
        "source": "amazon",
        "description": description,
        "date_posted": posted,
        "easy_apply": 0,
        "work_arrangement": "remote" if remote else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    if not item.get("salary_max"):
        # Amazon appends location-specific compensation after its benefits
        # boilerplate without a dollar sign or nearby "salary range" label.
        # Bind the fallback to the Austin line so another city's range cannot
        # be attributed to an Austin record.
        pay = re.search(
            r"\bUSA,\s*TX,\s*Austin\s*-\s*([\d,]+(?:\.\d+)?)\s*-\s*([\d,]+(?:\.\d+)?)\s*USD\s+annually\b",
            description,
            re.I,
        )
        if pay:
            low, high = sorted(float(value.replace(",", "")) for value in pay.groups())
            item.update({
                "salary_text": f"${low:,.0f} - ${high:,.0f}",
                "salary_min": low,
                "salary_max": high,
                "salary_type": "base",
            })
    return item


def amazon_austin_jobs(
    max_pages: int = 8,
    request_delay_seconds: float = 0.5,
    max_age_days: int = 30,
    search_queries: tuple[str, ...] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect target-family Austin postings from Amazon's public first-party feed."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    page_size = 100
    request_count = 0
    for query in search_queries or AMAZON_SEARCH_QUERIES:
        for page in range(max(1, max_pages)):
            if request_count and request_delay_seconds:
                time.sleep(max(0.0, request_delay_seconds))
            request_count += 1
            params = urllib.parse.urlencode({
                "base_query": query,
                "normalized_city_name[]": "Austin",
                "offset": page * page_size,
                "result_limit": page_size,
                "sort": "recent",
            })
            endpoint = f"https://www.amazon.jobs/en/search.json?{params}"
            try:
                request = urllib.request.Request(
                    endpoint,
                    headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read(30_000_000))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"Amazon Austin {query!r} page {page + 1}: {type(exc).__name__}")
                break
            jobs = payload.get("jobs") or []
            if not isinstance(jobs, list) or not jobs:
                break
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                item = amazon_job_item(job, max_age_days=max_age_days)
                if item and item["url"] not in seen:
                    seen.add(item["url"])
                    results.append(item)
            if len(jobs) < page_size:
                break
    return results, errors


def amd_job_item(record: dict[str, Any], max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize one fresh AMD Jibe record only when the official location is Austin."""
    job = record.get("data") if isinstance(record.get("data"), dict) else record
    city = clean_text(job.get("city"))
    country = clean_text(job.get("country_code") or job.get("country"))
    if city.casefold() != "austin" or country.casefold() not in {"us", "usa", "united states"}:
        return None
    slug = clean_text(job.get("slug") or job.get("req_id"))
    title = clean_text(job.get("title"))
    if not slug or not title:
        return None
    posted = str(job.get("posted_date") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(" ".join(str(job.get(key) or "") for key in (
        "description", "responsibilities", "qualifications",
    )))
    # AMD's Austin search occasionally returns a requisition whose structured
    # city is Austin even though the employer-written location line names a
    # different Texas city. Treat the detail text as authoritative when that
    # conflict is explicit instead of manufacturing an Austin-proper record.
    stated_location = re.search(
        r"\bLOCATION\s*:\s*(.*?)(?=\s+(?:THIS ROLE|LI-|Benefits offered|AMD and)\b|$)",
        description,
        re.I,
    )
    if stated_location and not re.search(r"\bAustin(?:,\s*(?:TX|Texas))?\b", stated_location.group(1), re.I):
        return None
    salary_bits: list[str] = []
    for key in ("tags2", "tags3"):
        values = job.get(key) or []
        if isinstance(values, list):
            salary_bits.extend(clean_text(value) for value in values if clean_text(value))
    salary_source = " - ".join(salary_bits) if len(salary_bits) >= 2 else description
    item = {
        "company": "AMD",
        "title": title,
        "location": "Austin, TX",
        "url": f"https://careers.amd.com/careers-home/jobs/{urllib.parse.quote(slug)}?lang=en-us",
        "source": "jibe",
        "description": description,
        "date_posted": posted,
        "easy_apply": 0,
        "work_arrangement": "remote" if str(job.get("location_type") or "").upper() == "ANY" else "onsite/hybrid",
    }
    item.update(extract_salary(salary_source))
    salary_values = []
    for value in salary_bits[:2]:
        match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", value)
        if match:
            salary_values.append(float(match.group(1).replace(",", "")))
    if len(salary_values) == 2:
        low, high = sorted(salary_values)
        item.update({
            "salary_text": f"${low:,.0f} - ${high:,.0f}",
            "salary_min": low,
            "salary_max": high,
            "salary_type": "year",
        })
    return item


def amd_austin_jobs(
    max_pages: int = 3,
    request_delay_seconds: float = 0.5,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect Austin-explicit jobs from AMD's public Jibe search API."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    page_size = 100
    for page in range(1, max(1, max_pages) + 1):
        params = urllib.parse.urlencode({
            "categories": "Engineering",
            "page": page,
            "location": "Austin, TX",
            "woe": 7,
            "regionCode": "US",
            "stretchUnit": "MILES",
            "stretch": 10,
            "limit": page_size,
            "sortBy": "relevance",
        })
        endpoint = f"https://careers.amd.com/api/jobs?{params}"
        try:
            request = urllib.request.Request(
                endpoint,
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(30_000_000))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"AMD Austin page {page}: {type(exc).__name__}")
            break
        jobs = payload.get("jobs") or []
        if not isinstance(jobs, list) or not jobs:
            break
        for record in jobs:
            if not isinstance(record, dict):
                continue
            item = amd_job_item(record, max_age_days=max_age_days)
            if item and item["url"] not in seen:
                seen.add(item["url"])
                results.append(item)
        if len(jobs) < page_size:
            break
        if request_delay_seconds and page < max_pages:
            time.sleep(max(0.0, request_delay_seconds))
    return results, errors


def jibe_job_item(
    company: str,
    base_url: str,
    record: dict[str, Any],
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one public Jibe record only when Austin is an explicit location."""
    job = record.get("data") if isinstance(record.get("data"), dict) else record
    locations = [job]
    locations.extend(
        location for location in (job.get("additional_locations") or [])
        if isinstance(location, dict)
    )
    has_austin_location = any(
        clean_text(location.get("city")).casefold() == "austin"
        and clean_text(location.get("state")).casefold() in {"tx", "texas"}
        and clean_text(location.get("country_code") or location.get("country")).casefold()
        in {"us", "usa", "united states"}
        for location in locations
    )
    if not has_austin_location:
        return None
    posted = str(job.get("posted_date") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    slug = clean_text(job.get("slug") or job.get("req_id"))
    title = clean_text(job.get("title"))
    if not slug or not title:
        return None
    description_parts: list[str] = []
    for key in ("description", "responsibilities", "qualifications"):
        value = clean_text(job.get(key))
        if value and not any(value == prior or value in prior or prior in value for prior in description_parts):
            description_parts.append(value)
    description = " ".join(description_parts)
    arrangement_text = " ".join((
        clean_text(job.get("location_type")),
        " ".join(clean_text(value) for value in (job.get("tags2") or []) if clean_text(value)),
        clean_text(job.get("location_name")),
    )).casefold()
    item = {
        "company": company,
        "title": title,
        "location": "Austin, TX",
        "url": f"{base_url.rstrip('/')}/jobs/{urllib.parse.quote(slug)}?lang=en-us",
        "source": "jibe",
        "description": description,
        "date_posted": posted,
        "provider_job_id": slug,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in arrangement_text or clean_text(job.get("location_type")).upper() == "ANY" else "onsite/hybrid",
    }
    salary_tags: list[str] = []
    for key in ("tags", "tags2", "tags3"):
        values = job.get(key) or []
        if isinstance(values, list):
            salary_tags.extend(clean_text(value) for value in values if clean_text(value))
    salary = extract_salary(" ".join((*salary_tags, description)))
    if salary.get("salary_min") is None and salary.get("salary_max") is None:
        annual_values: list[float] = []
        for value in salary_tags:
            match = re.search(
                r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:/\s*(?:yr|year)|per\s+year|annual)",
                value,
                re.I,
            )
            if match:
                annual_values.append(float(match.group(1).replace(",", "")))
        if annual_values:
            low, high = min(annual_values), max(annual_values)
            salary = {
                "salary_text": f"${low:,.0f} - ${high:,.0f}" if high != low else f"From ${low:,.0f}",
                "salary_min": low,
                "salary_max": high if high != low else None,
                "salary_type": "base",
            }
    item.update(salary)
    return item


def jibe_company_jobs(
    companies: set[str] | None = None,
    max_pages: int = 9,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin-explicit target roles from configured public Jibe APIs."""
    requested = {value.casefold() for value in companies} if companies is not None else None
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for company, config in JIBE_SITES.items():
        if requested is not None and company.casefold() not in requested:
            continue
        base_url = str(config["base_url"])
        searches = config.get("searches") or tuple({"keywords": value} for value in (config.get("keywords") or ("software",)))
        for search in searches:
            if not isinstance(search, dict):
                continue
            keywords = clean_text(search.get("keywords"))
            search_label = keywords or clean_text(search.get("categories")) or "all"
            for page in range(1, max(1, max_pages) + 1):
                query = {
                    "location": "Austin, TX",
                    "stretchUnit": "MILES",
                    "stretch": 10,
                    "page": page,
                }
                query.update({key: value for key, value in search.items() if value is not None})
                params = urllib.parse.urlencode(query)
                endpoint = f"{base_url.rstrip('/')}/api/jobs?{params}"
                try:
                    request = urllib.request.Request(
                        endpoint,
                        headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"},
                    )
                    with urllib.request.urlopen(request, timeout=30) as response:
                        payload = json.loads(response.read(30_000_000))
                except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                    errors.append(f"{company} Jibe {search_label} page {page}: {type(exc).__name__}")
                    break
                jobs = payload.get("jobs") or []
                if not isinstance(jobs, list) or not jobs:
                    break
                for record in jobs:
                    if not isinstance(record, dict):
                        continue
                    item = jibe_job_item(company, base_url, record, max_age_days=max_age_days)
                    if item and title_is_candidate(item) and item["url"] not in seen:
                        seen.add(item["url"])
                        results.append(item)
                total = int(payload.get("totalCount") or 0)
                if len(jobs) < 10 or page * 10 >= total:
                    break
                if request_delay_seconds:
                    time.sleep(max(2.0, request_delay_seconds))
            if request_delay_seconds:
                time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def workday_job_item(
    company: str,
    host: str,
    site: str,
    external_path: str,
    detail: dict[str, Any],
) -> dict[str, Any] | None:
    """Normalize one public Workday detail record with an explicit Austin location."""
    posting = detail.get("jobPostingInfo") or {}
    if not isinstance(posting, dict):
        return None
    primary_location = clean_text(posting.get("location") or (posting.get("jobRequisitionLocation") or {}).get("descriptor"))
    additional_locations = posting.get("additionalLocations") or []
    if not isinstance(additional_locations, list):
        additional_locations = []
    locations = [primary_location] + [clean_text(value) for value in additional_locations]
    description = clean_text(posting.get("jobDescription"))
    explicit_austin_location = any(re.search(
        r"(?:\bAustin\b[^/]{0,40}\b(?:TX|Texas)\b|\b(?:TX|Texas)\b[^/]{0,40}\bAustin\b)",
        location,
        re.I,
    ) for location in locations)
    # Some Workday sites use a generic Texas-remote location record while the
    # employer's own posting explicitly binds the role to its Austin office.
    # Accept only strong work-location language; a company-presence mention is
    # not enough to count the role as Austin-proper.
    explicit_austin_office = bool(re.search(
        r"(?:hybrid|on[- ]site|working arrangement|work(?:ing)? (?:from|at))[^.]{0,140}"
        r"(?:office[^.]{0,50})?based in Austin,?\s+Texas\b",
        description,
        re.I,
    ))
    requisition_location = posting.get("jobRequisitionLocation") or {}
    location_country = requisition_location.get("country") or {}
    # Trend Micro's Workday tenant publishes the structured city as simply
    # "Austin" while the employer description names the hybrid Austin, TX
    # office. Require both signals plus the US country code so a passing
    # company-presence reference cannot become Austin-proper evidence.
    structured_austin_office = bool(
        any(location.casefold() == "austin" for location in locations)
        and str(location_country.get("alpha2Code") or "").casefold() == "us"
        and re.search(
            r"(?:\bhybrid\b|\bon[- ]site\b|\bwork(?:ing)?\b)[^.]{0,140}"
            r"\bAustin,?\s+(?:TX|Texas)\b[^.]{0,60}\boffice\b",
            description,
            re.I,
        )
    )
    # Expedia's public careers detail renders this exact Workday office as
    # "United States - Texas - Austin" while the backing ATS descriptor uses
    # its internal office name. Accept only that named US office, never a broad
    # Expedia remote or multi-location record.
    expedia_austin_office = bool(
        company.casefold() == "expedia group"
        and any(location.casefold() == "austin domain 11 - homeaway" for location in locations)
        and str(location_country.get("alpha2Code") or "").casefold() == "us"
    )
    if not explicit_austin_location and not explicit_austin_office and not structured_austin_office and not expedia_austin_office:
        return None
    url = clean_text(posting.get("externalUrl"))
    if not url:
        url = f"{host.rstrip('/')}/{site}{external_path}"
    item = {
        "company": company,
        "title": clean_text(posting.get("title")),
        "location": "Austin, TX",
        "url": url,
        "source": "workday",
        "description": description,
        "date_posted": str(posting.get("startDate") or "")[:10] or None,
        "easy_apply": 0,
        "work_arrangement": "remote" if any("remote" in location.casefold() for location in locations) else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    # Expedia publishes separate cash ranges by Workday location. The first
    # range may be for San Jose even when Austin is an eligible work location.
    if company.casefold() == "expedia group":
        austin_cash = re.search(
            r"total cash range for this position in Austin is\s*\$([\d,]+(?:\.\d+)?)"
            r"\s*(?:to|-|–)\s*\$([\d,]+(?:\.\d+)?)",
            description,
            re.I,
        )
        if austin_cash:
            low, high = sorted(float(value.replace(",", "")) for value in austin_cash.groups())
            item.update({
                "salary_text": f"Austin total cash: ${low:,.0f} - ${high:,.0f}",
                "salary_min": low,
                "salary_max": high,
                "salary_type": "total",
            })
    if not item.get("salary_max"):
        match = re.search(
            r"base salary range is\s+([\d,]+(?:\.\d+)?)\s+USD\s*-\s*([\d,]+(?:\.\d+)?)\s+USD",
            description,
            re.I,
        )
        if match:
            low, high = sorted(float(value.replace(",", "")) for value in match.groups())
            item.update({
                "salary_text": f"${low:,.0f} - ${high:,.0f}",
                "salary_min": low,
                "salary_max": high,
                "salary_type": "year",
            })
    return item if item["title"] and item["url"] else None


def _fresh_workday_listing(listing: dict[str, Any], max_age_days: int = 30) -> bool:
    posted = clean_text(listing.get("postedOn")).casefold()
    if not posted or "today" in posted or "yesterday" in posted or "hour" in posted:
        return True
    match = re.search(r"(\d+)\s+day", posted)
    return bool(match and int(match.group(1)) <= max_age_days and "+" not in posted)


def _adp_external_job_id(job: dict[str, Any]) -> str:
    fields = (job.get("customFieldGroup") or {}).get("stringFields") or []
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = clean_text((field.get("nameCode") or {}).get("codeValue"))
        if name.casefold() == "externaljobid":
            return clean_text(field.get("stringValue"))
    return ""


def _adp_listing_has_austin(job: dict[str, Any]) -> bool:
    """Require ADP's structured address and US label to identify Austin."""
    for location in job.get("requisitionLocations") or []:
        if not isinstance(location, dict):
            continue
        address = location.get("address") or {}
        short_name = clean_text((location.get("nameCode") or {}).get("shortName"))
        if (
            clean_text(address.get("cityName")).casefold() == "austin"
            and clean_text((address.get("countrySubdivisionLevel1") or {}).get("codeValue")).casefold() in {"tx", "texas"}
            and bool(re.search(r"(?:^|,\s*)US$", short_name, re.I))
        ):
            return True
    return False


def adp_job_item(
    company: str,
    config: dict[str, str],
    listing: dict[str, Any],
    detail: dict[str, Any],
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one fresh, exact-Austin public ADP requisition."""
    if not _adp_listing_has_austin(listing) or not _adp_listing_has_austin(detail):
        return None
    posted = clean_text(detail.get("postDate") or listing.get("postDate"))[:10]
    if not _fresh_iso_listing(posted, max_age_days=max_age_days):
        return None
    title = clean_text(detail.get("requisitionTitle") or listing.get("requisitionTitle"))
    description = clean_text(detail.get("requisitionDescription"))
    if not title_is_candidate({"title": title, "description": description}) or not description:
        return None
    external_id = _adp_external_job_id(detail) or _adp_external_job_id(listing)
    item_id = clean_text(detail.get("itemID") or listing.get("itemID"))
    if not external_id or not item_id:
        return None
    item = {
        "company": company,
        "title": title,
        "location": "Austin, TX",
        "url": f"{config['board_url']}&jobId={urllib.parse.quote(external_id)}",
        "source": "adp",
        "description": description,
        "date_posted": posted,
        "provider_job_id": item_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{title} {description}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, detail))
    return item


def adp_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin roles from configured anonymous public ADP feeds."""
    requested = {value.casefold() for value in companies} if companies is not None else None
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    base = "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
    headers = {
        "User-Agent": "EliOpportunityQueue/1.0",
        "Accept": "application/json",
        "Accept-Language": "en_US",
        "locale": "en_US",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
        "x-forwarded-host": "workforcenow.adp.com",
    }
    for company, config in ADP_SITES.items():
        if requested is not None and company.casefold() not in requested:
            continue
        query = urllib.parse.urlencode({
            "cid": config["cid"], "ccId": config["cc_id"], "lang": "en_US", "locale": "en_US",
            "$skip": 0, "$top": 100, "userQuery": "",
        })
        try:
            request = urllib.request.Request(f"{base}?{query}", headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read(12_000_000))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company} ADP search: {type(exc).__name__}")
            continue
        candidates = [
            job for job in payload.get("jobRequisitions") or []
            if isinstance(job, dict)
            and _adp_listing_has_austin(job)
            and _fresh_iso_listing(clean_text(job.get("postDate"))[:10], max_age_days=max_age_days)
            and title_is_candidate({"title": clean_text(job.get("requisitionTitle"))})
            and clean_text(job.get("itemID"))
        ]
        for listing in candidates:
            if request_delay_seconds:
                time.sleep(max(2.0, float(request_delay_seconds)))
            item_id = clean_text(listing.get("itemID"))
            detail_query = urllib.parse.urlencode({
                "cid": config["cid"], "ccId": config["cc_id"], "lang": "en_US", "locale": "en_US",
            })
            try:
                request = urllib.request.Request(f"{base}/{urllib.parse.quote(item_id)}?{detail_query}", headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = json.loads(response.read(12_000_000))
                item = adp_job_item(company, config, listing, detail, max_age_days=max_age_days)
                if item:
                    results.append(item)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} ADP {item_id}: {type(exc).__name__}")
    return results, errors


def employer_page_job_item(
    company: str,
    config: dict[str, str],
    board_raw: str,
    detail_raw: str,
) -> dict[str, Any] | None:
    """Normalize a configured job whose employer publishes static HTML pages."""
    title = config["title"]
    title_at = board_raw.find(title)
    if title_at < 0:
        return None
    next_card = board_raw.find('class="rounded-lg border', title_at + len(title))
    card_raw = board_raw[title_at:next_card if next_card >= 0 else title_at + 5000]
    if config["detail_path"] not in card_raw or not re.search(r"\bAustin\s*,\s*(?:TX|Texas)\b", clean_text(card_raw), re.I):
        return None
    heading = re.search(rf"<h1\b[^>]*>\s*{re.escape(title)}\s*</h1>", detail_raw, re.I)
    if not heading:
        return None
    end = detail_raw.find("Ready to Apply?", heading.end())
    detail_segment = detail_raw[heading.start():end if end >= 0 else heading.start() + 25000]
    description = clean_text(detail_segment)
    if len(description) < 250 or not title_is_candidate({"title": title, "description": description}):
        return None
    item = {
        "company": company,
        "title": title,
        "location": "Austin, TX",
        "url": canonical_public_url(config["detail_url"]),
        "source": "employer",
        "description": description,
        # This employer page does not expose an original posting date. The
        # storage refresh preserves an earlier discovery date when available.
        "date_posted": None,
        "easy_apply": 0,
        "work_arrangement": "onsite/hybrid",
    }
    item.update(extract_salary(clean_text(card_raw)))
    return item


def employer_page_company_jobs(
    companies: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect curated server-rendered employer pages without form actions."""
    requested = {value.casefold() for value in companies} if companies is not None else None
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for company, config in EMPLOYER_PAGE_SITES.items():
        if requested is not None and company.casefold() not in requested:
            continue
        try:
            request = urllib.request.Request(config["board_url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                board_raw = response.read(10_000_000).decode("utf-8", "replace")
            request = urllib.request.Request(config["detail_url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                detail_raw = response.read(15_000_000).decode("utf-8", "replace")
            item = employer_page_job_item(company, config, board_raw, detail_raw)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"{company} employer page: {type(exc).__name__}")
    return results, errors


def workday_company_jobs(
    companies: set[str] | None = None,
    max_pages: int = 10,
    request_delay_seconds: float = 0.5,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh Austin-explicit roles from configured public Workday feeds."""
    requested = {value.casefold() for value in companies} if companies is not None else None
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for company, config in WORKDAY_SITES.items():
        if requested is not None and company.casefold() not in requested:
            continue
        host, tenant, site = config["host"], config["tenant"], config["site"]
        search_endpoint = f"{host}/wday/cxs/{tenant}/{site}/jobs"
        listings: dict[str, dict[str, Any]] = {}
        for page in range(max(1, max_pages)):
            body = json.dumps({
                "appliedFacets": config.get("applied_facets", {}),
                "limit": 20,
                "offset": page * 20,
                "searchText": config.get("search_text", ""),
            }).encode("utf-8")
            try:
                request = urllib.request.Request(
                    search_endpoint, data=body, method="POST",
                    headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json", "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read(10_000_000))
            except (urllib.error.URLError, ConnectionError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} Workday page {page + 1}: {type(exc).__name__}")
                break
            page_items = payload.get("jobPostings") or []
            if not isinstance(page_items, list) or not page_items:
                break
            for listing in page_items:
                if not isinstance(listing, dict):
                    continue
                path = str(listing.get("externalPath") or "")
                candidate = {"title": clean_text(listing.get("title"))}
                if path and title_is_candidate(candidate) and _fresh_workday_listing(listing):
                    listings[path] = listing
            if (page + 1) * 20 >= int(payload.get("total") or 0):
                break
            if request_delay_seconds:
                time.sleep(max(0.0, request_delay_seconds))

        for path in listings:
            endpoint = f"{host}/wday/cxs/{tenant}/{site}{path}"
            try:
                request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = json.loads(response.read(12_000_000))
                item = workday_job_item(company, host, site, path, detail)
                if item:
                    results.append(item)
            except (urllib.error.URLError, ConnectionError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} Workday {path.rsplit('/', 1)[-1]}: {type(exc).__name__}")
            if request_delay_seconds:
                time.sleep(max(0.0, request_delay_seconds))
    return results, errors


def _phenom_ddo(raw: str) -> dict[str, Any]:
    """Extract the public structured-data payload embedded in a Phenom page."""
    match = re.search(r"phApp\.ddo = (\{.*?\}); phApp\.experimentData", raw, re.S)
    if not match:
        raise ValueError("Phenom structured job data was not found")
    payload = json.loads(match.group(1))
    if not isinstance(payload, dict):
        raise ValueError("Phenom job data has an unexpected shape")
    return payload


def phenom_search_items(raw: str) -> list[dict[str, Any]]:
    payload = _phenom_ddo(raw).get("eagerLoadRefineSearch") or {}
    jobs = ((payload.get("data") or {}).get("jobs") or []) if isinstance(payload, dict) else []
    return [item for item in jobs if isinstance(item, dict)]


def phenom_job_item(company: str, base_url: str, listing: dict[str, Any], raw: str) -> dict[str, Any]:
    payload = _phenom_ddo(raw).get("jobDetail") or {}
    job = ((payload.get("data") or {}).get("job") or {}) if isinstance(payload, dict) else {}
    if not isinstance(job, dict) or not job:
        raise ValueError("Phenom job detail is missing")
    job_id = clean_text(job.get("jobId") or job.get("reqId") or listing.get("jobId") or listing.get("reqId"))
    title = clean_text(job.get("title") or listing.get("title"))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
    standardized_locations = job.get("standardised_multi_location") or []
    locations = standardized_locations or job.get("multi_location") or listing.get("multi_location") or []
    if not isinstance(locations, list):
        locations = []
    def location_name(value: Any) -> str:
        if isinstance(value, dict):
            explicit = clean_text(value.get("location") or value.get("cityStateCountry") or value.get("cityState"))
            if explicit:
                return explicit
            return ", ".join(
                part for part in (
                    clean_text(value.get("standardisedCity")),
                    clean_text(value.get("standardisedState")),
                    clean_text(value.get("standardisedCountry")),
                ) if part
            )
        return clean_text(value)
    location = " / ".join(location_name(value) for value in locations if location_name(value))
    location = location or clean_text(job.get("location") or job.get("cityStateCountry") or listing.get("location"))
    description = clean_text(job.get("description") or job.get("descriptionTeaser") or listing.get("descriptionTeaser"))
    posted = str(job.get("postedDate") or listing.get("postedDate") or "")[:10] or None
    arrangement = "remote" if "remote" in (location + " " + str(job.get("remote") or "") + " " + str(job.get("RemoteType") or job.get("remoteType") or "")).lower() else "onsite/hybrid"
    item = {
        "company": company, "title": title, "location": location,
        "url": f"{base_url}/job/{job_id}/{slug}", "source": "phenom",
        "description": description, "date_posted": posted, "easy_apply": 0,
        "work_arrangement": arrangement,
    }
    item.update(extract_salary(description))
    return item


def phenom_company_jobs(
    companies: set[str] | None = None,
    max_pages: int = 20,
    request_delay_seconds: float = 0.35,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect full postings from supported public Phenom career sites."""
    requested = {value.casefold() for value in companies} if companies is not None else None
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for company, base_url in PHENOM_SITES.items():
        if requested is not None and company.casefold() not in requested:
            continue
        listings: dict[str, dict[str, Any]] = {}
        for keywords in ("Senior Software Engineer", "Staff Software Engineer"):
            for page in range(max(1, max_pages)):
                params = urllib.parse.urlencode({"keywords": keywords, "from": page * 10, "s": 1})
                endpoint = f"{base_url}/search-results/?{params}"
                try:
                    request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
                    with urllib.request.urlopen(request, timeout=30) as response:
                        raw = response.read(8_000_000).decode("utf-8", "replace")
                    page_items = phenom_search_items(raw)
                except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                    errors.append(f"{company} search page {page + 1}: {type(exc).__name__}")
                    break
                if not page_items:
                    break
                before = len(listings)
                for listing in page_items:
                    job_id = clean_text(listing.get("jobId") or listing.get("reqId"))
                    country = clean_text(listing.get("country") or listing.get("cityStateCountry"))
                    if job_id and title_is_candidate(listing) and "united states" in country.lower():
                        listings[job_id] = listing
                if page > 0 and len(listings) == before and all(
                    clean_text(item.get("jobId") or item.get("reqId")) in listings for item in page_items
                ):
                    break
                if request_delay_seconds:
                    time.sleep(max(0.0, request_delay_seconds))

        for job_id, listing in listings.items():
            title = clean_text(listing.get("title"))
            slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
            endpoint = f"{base_url}/job/{job_id}/{slug}"
            try:
                request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read(8_000_000).decode("utf-8", "replace")
                results.append(phenom_job_item(company, base_url, listing, raw))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} {job_id}: {type(exc).__name__}")
            if request_delay_seconds:
                time.sleep(max(0.0, request_delay_seconds))
    return results, errors


def phenom_listing_has_austin(listing: dict[str, Any]) -> bool:
    """Require an explicit Austin, Texas location in a Phenom result."""
    values = listing.get("multi_location") or [listing.get("location")]
    if not isinstance(values, list):
        values = [values]
    if clean_text(listing.get("city")).casefold() == "austin" and clean_text(listing.get("state")).casefold() == "texas":
        return True
    return any(
        re.search(
            r"(?:\bAustin\s*,\s*(?:Texas|United States of America)\b|\bTX-Austin\b)",
            clean_text(value.get("location") if isinstance(value, dict) else value),
            re.I,
        )
        for value in values
    )


def _phenom_austin_jobs(
    company: str,
    base_url: str,
    board_url: str,
    max_pages: int,
    request_delay_seconds: float,
    max_age_days: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles whose first-party Phenom data explicitly includes Austin."""
    listings: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for page in range(max(1, max_pages)):
        separator = "&" if "?" in board_url else "?"
        endpoint = f"{board_url}{separator}from={page * 10}"
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(8_000_000).decode("utf-8", "replace")
            page_items = phenom_search_items(raw)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company} search page {page + 1}: {type(exc).__name__}")
            break
        if not page_items:
            break
        for listing in page_items:
            job_id = clean_text(listing.get("jobId") or listing.get("reqId"))
            if (
                job_id
                and phenom_listing_has_austin(listing)
                and _fresh_iso_listing(listing.get("postedDate"), max_age_days)
                and title_is_candidate(listing)
            ):
                listings[job_id] = listing
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))

    results: list[dict[str, Any]] = []
    for job_id, listing in listings.items():
        title = clean_text(listing.get("title"))
        slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
        endpoint = f"{base_url}/job/{job_id}/{slug}"
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(8_000_000).decode("utf-8", "replace")
            item = phenom_job_item(company, base_url, listing, raw)
            if phenom_listing_has_austin({"multi_location": item.get("location", "").split(" / ")}) and _fresh_iso_listing(item.get("date_posted"), max_age_days):
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company} {job_id}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def cvs_austin_jobs(
    max_pages: int = 24,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh, explicitly Austin CVS Innovation and Technology roles."""
    return _phenom_austin_jobs(
        "CVS Health", CVS_CAREERS_BASE, CVS_AUSTIN_BOARD,
        max_pages, request_delay_seconds, max_age_days,
    )


def adobe_austin_jobs(
    max_pages: int = 2,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from Adobe's public exact-city Phenom query."""
    return _phenom_austin_jobs(
        "Adobe", PHENOM_SITES["Adobe"], ADOBE_AUSTIN_BOARD,
        max_pages, request_delay_seconds, max_age_days,
    )


def questglobal_austin_jobs(
    max_pages: int = 1,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from Quest Global's public Austin city facet."""
    return _phenom_austin_jobs(
        "Quest Global", QUEST_GLOBAL_CAREERS_BASE, QUEST_GLOBAL_AUSTIN_BOARD,
        max_pages, request_delay_seconds, max_age_days,
    )


def circle_austin_jobs(
    max_pages: int = 7,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from Circle's public Phenom inventory.

    Circle presents many remote US roles as eligible in a fixed set of cities,
    so the employer's complete ``multi_location`` field is the location source
    of truth rather than aggregator labels or the search card's country label.
    """
    return _phenom_austin_jobs(
        "Circle", CIRCLE_CAREERS_BASE, CIRCLE_AUSTIN_BOARD,
        max_pages, request_delay_seconds, max_age_days,
    )


def mastercard_austin_jobs(
    max_pages: int = 3,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh, explicitly Austin Mastercard technology roles from Phenom."""
    return _phenom_austin_jobs(
        "Mastercard", MASTERCARD_CAREERS_BASE, MASTERCARD_AUSTIN_BOARD,
        max_pages, request_delay_seconds, max_age_days,
    )


def lpl_austin_jobs(
    max_pages: int = 6,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from LPL's public Austin Phenom inventory."""
    items, errors = _phenom_austin_jobs(
        "LPL Financial", LPL_CAREERS_BASE, LPL_AUSTIN_BOARD,
        max_pages, request_delay_seconds, max_age_days,
    )
    for item in items:
        match = re.search(r"/job/(R-\d+)(?:/|$)", clean_text(item.get("url")), re.I)
        item["source"] = "lpl"
        item["provider_job_id"] = match.group(1).upper() if match else ""
        item["location"] = "Austin, TX / Multiple US locations" if " / " in clean_text(item.get("location")) else "Austin, TX"
        if "(annualized)" in clean_text(item.get("salary_text")) and item.get("salary_min") is not None:
            item["salary_text"] = f"{format_salary_range(item.get('salary_min'), item.get('salary_max'))} (annualized from employer hourly range)"
    return [item for item in items if item.get("provider_job_id")], errors


def pwc_austin_jobs(
    max_pages: int = 100,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from PwC's complete public Phenom inventory.

    PwC's client-side city facet is not represented in a clean, shareable URL.
    The server-rendered result pages do support stable offset pagination and
    expose each job's complete location list, so scan them slowly and retain
    only records that explicitly contain the portal's ``TX-Austin`` location.
    """
    items, errors = _phenom_austin_jobs(
        "PwC", PWC_CAREERS_BASE, PWC_AUSTIN_BOARD,
        max_pages, request_delay_seconds, max_age_days,
    )
    for item in items:
        match = re.search(r"/job/([^/?#]+)(?:/|$)", clean_text(item.get("url")), re.I)
        item["source"] = "pwc"
        item["provider_job_id"] = match.group(1) if match else ""
        item["location"] = "Austin, TX / Multiple US locations"
    return items, errors


def roku_search_listings(raw: str) -> list[dict[str, str]]:
    """Extract title and canonical URL from Roku's server-rendered Austin results."""
    results: list[dict[str, str]] = []
    for row in re.findall(r'<tr\s+role="link"[^>]*data-job-url="([^"]+)"[^>]*>(.*?)</tr>', raw, re.I | re.S):
        url, body = row
        title_match = re.search(r'aria-label="Title:\s*([^"]+)"', body, re.I)
        title = clean_text(title_match.group(1)) if title_match else ""
        item = {"title": title, "url": canonical_public_url(url), "location": "Austin, TX"}
        if title and item["url"] and title_is_candidate(item):
            results.append(item)
    return results


def roku_job_item(raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a fresh Roku JobPosting whose official address is Austin, Texas."""
    posting: dict[str, Any] | None = None
    for value in re.findall(r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            posting = candidate
            break
    if not posting:
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    locations: list[str] = []
    has_austin = False
    for place in raw_locations:
        address = (place or {}).get("address") if isinstance(place, dict) else {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        state = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        if city.casefold() == "austin" and state.casefold() in {"tx", "texas"} and country.casefold() in {"us", "usa", "united states"}:
            has_austin = True
        label = ", ".join(part for part in (city, state, country) if part)
        if label:
            locations.append(label)
    if not has_austin:
        return None
    description = clean_text(posting.get("description"))
    stated_base = re.search(
        r"\b(?:this|the)\s+(?:role|position)\s+is\s+(?:based|located)\s+in\s+([^.;]{2,100})",
        description,
        re.I,
    )
    if stated_base and is_explicitly_non_us_location(stated_base.group(1)):
        return None
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    title = clean_text(posting.get("title"))
    item = {
        "company": "Roku", "title": title, "location": " / ".join(dict.fromkeys(locations)),
        "url": canonical_public_url(url), "source": "roku", "description": description,
        "date_posted": posted, "provider_job_id": provider_job_id, "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{title} {description}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and description and item["url"] else None


def roku_austin_jobs(
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from Roku's exact-Austin first-party portal."""
    try:
        request = urllib.request.Request(ROKU_AUSTIN_BOARD, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(15_000_000).decode("utf-8", "replace")
            status = int(getattr(response, "status", 200))
        if status != 200:
            challenge = " AWS WAF challenge" if status == 202 and "awsWafCookieDomainList" in raw else ""
            return [], [f"Roku search: HTTP {status}{challenge}"]
        listings = roku_search_listings(raw)
        if not listings and 'data-job-url=' not in raw and not re.search(
            r'\b(?:no jobs found|displaying all 0 entries|0 matching jobs)\b', raw, re.I
        ):
            return [], ["Roku search: listing cards unavailable in public HTTP response; browser verification required"]
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
        return [], [f"Roku search: {type(exc).__name__}"]

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for listing in listings:
        try:
            request = urllib.request.Request(listing["url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(15_000_000).decode("utf-8", "replace")
            item = roku_job_item(raw, listing["url"], max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Roku {listing['title']}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def western_union_job_item(raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a fresh Western Union JobPosting with an explicit Austin address."""
    posting: dict[str, Any] | None = None
    for value in re.findall(r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        candidates = candidate.get("@graph") or [] if isinstance(candidate, dict) else []
        candidates = candidates if isinstance(candidates, list) else []
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            candidates.insert(0, candidate)
        posting = next(
            (item for item in candidates if isinstance(item, dict) and item.get("@type") == "JobPosting"),
            None,
        )
        if posting:
            break
    if not posting:
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    current_job_match = re.search(r"var\s+current_job\s*=\s*(\{.*?\});\s*</script>", raw, re.I | re.S)
    if current_job_match:
        try:
            current_job = json.loads(current_job_match.group(1))
        except (TypeError, ValueError, json.JSONDecodeError):
            current_job = {}
        raw_locations = list(raw_locations)
        if current_job.get("primary_city"):
            raw_locations.append({"address": {
                "addressLocality": current_job.get("primary_city"),
                "addressRegion": current_job.get("primary_state"),
                "addressCountry": current_job.get("primary_country"),
            }})
        for location in current_job.get("addtnl_locations") or []:
            if isinstance(location, dict):
                raw_locations.append({"address": {
                    "addressLocality": location.get("addtnl_city"),
                    "addressRegion": location.get("addtnl_state"),
                    "addressCountry": location.get("addtnl_country"),
                }})
    locations: list[str] = []
    has_austin = False
    for place in raw_locations:
        address = (place or {}).get("address") if isinstance(place, dict) else {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        state = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        if city.casefold() == "austin" and state.casefold() in {"tx", "texas"} and country.casefold() in {"us", "usa", "united states"}:
            has_austin = True
        label = ", ".join(part for part in (city, state, country) if part)
        if label:
            locations.append(label)
    if not has_austin:
        return None
    title = clean_text(posting.get("title"))
    description = clean_text(posting.get("description"))
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    item = {
        "company": "Western Union", "title": title, "location": " / ".join(dict.fromkeys(locations)),
        "url": canonical_public_url(url), "source": "westernunion", "description": description,
        "date_posted": posted, "provider_job_id": provider_job_id, "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{title} {description}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and description and item["url"] else None


def western_union_workday_search_listings(
    payload: dict[str, Any],
    max_age_days: int = 30,
) -> list[dict[str, Any]]:
    """Select fresh candidate paths from Western Union's public Workday search."""
    results: list[dict[str, Any]] = []
    for listing in payload.get("jobPostings") or []:
        if not isinstance(listing, dict):
            continue
        path = clean_text(listing.get("externalPath"))
        if (
            path.startswith("/job/")
            and title_is_candidate({"title": clean_text(listing.get("title"))})
            and _fresh_workday_listing(listing, max_age_days=max_age_days)
        ):
            results.append(listing)
    return results


def western_union_austin_jobs(
    urls: tuple[str, ...] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Discover Western Union Austin roles through its public Workday tenant.

    Explicit ``urls`` retain the older branded-detail refresh path for focused
    checks. Normal collection uses Workday search so new requisitions are not
    limited to a hard-coded URL inventory.
    """
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    if urls is not None:
        for index, url in enumerate(dict.fromkeys(urls)):
            if index:
                time.sleep(delay)
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read(15_000_000).decode("utf-8", "replace")
                item = western_union_job_item(raw, url, max_age_days=max_age_days)
                if item and title_is_candidate(item):
                    results.append(item)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"Western Union {url.rstrip('/').rsplit('/', 2)[-2]}: {type(exc).__name__}")
        return results, errors

    search_endpoint = (
        f"{WESTERN_UNION_WORKDAY_HOST}/wday/cxs/"
        f"{WESTERN_UNION_WORKDAY_TENANT}/{WESTERN_UNION_WORKDAY_SITE}/jobs"
    )
    body = json.dumps({
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": "Austin",
    }).encode("utf-8")
    try:
        request = urllib.request.Request(
            search_endpoint,
            data=body,
            method="POST",
            headers={
                "User-Agent": "EliOpportunityQueue/1.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read(10_000_000))
        listings = western_union_workday_search_listings(payload, max_age_days=max_age_days)
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
        return [], [f"Western Union Workday search: {type(exc).__name__}"]

    for index, listing in enumerate(listings):
        if index:
            time.sleep(delay)
        path = clean_text(listing.get("externalPath"))
        endpoint = (
            f"{WESTERN_UNION_WORKDAY_HOST}/wday/cxs/"
            f"{WESTERN_UNION_WORKDAY_TENANT}/{WESTERN_UNION_WORKDAY_SITE}{path}"
        )
        try:
            request = urllib.request.Request(
                endpoint,
                headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                detail = json.loads(response.read(12_000_000))
            item = workday_job_item(
                "Western Union",
                WESTERN_UNION_WORKDAY_HOST,
                WESTERN_UNION_WORKDAY_SITE,
                path,
                detail,
            )
            if item:
                item["provider_job_id"] = clean_text((detail.get("jobPostingInfo") or {}).get("jobReqId"))
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Western Union {clean_text(listing.get('title'))}: {type(exc).__name__}")
    return results, errors


def resideo_search_listings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Select target titles whose public Resideo feed explicitly includes Austin."""
    results: list[dict[str, Any]] = []
    for job in payload.get("jobs") or []:
        if not isinstance(job, dict) or not title_is_candidate({"title": clean_text(job.get("title"))}):
            continue
        locations = job.get("locations") or []
        has_austin = any(
            isinstance(location, dict)
            and clean_text(location.get("city")).casefold() == "austin"
            and clean_text(location.get("state")).casefold() in {"tx", "texas"}
            and clean_text(location.get("country")).casefold() in {"us", "usa", "united states"}
            for location in locations
        )
        detail_url = urllib.parse.urljoin(RESIDEO_CAREERS_BASE, clean_text(job.get("detailUrl")))
        if has_austin and detail_url:
            results.append({**job, "detailUrl": canonical_public_url(detail_url)})
    return results


def resideo_job_item(raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a fresh Resideo detail page with an official Austin address."""
    posting: dict[str, Any] | None = None
    for value in re.findall(r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            posting = candidate
            break
    if not posting:
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    raw_locations = posting.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    locations: list[str] = []
    has_austin = False
    for place in raw_locations:
        address = (place or {}).get("address") if isinstance(place, dict) else {}
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("addressLocality"))
        state = clean_text(address.get("addressRegion"))
        country = clean_text(address.get("addressCountry"))
        if city.casefold() == "austin" and state.casefold() in {"tx", "texas"} and country.casefold() in {"us", "usa", "united states"}:
            has_austin = True
        label = ", ".join(part for part in (city, state, country) if part)
        if label:
            locations.append(label)
    if not has_austin:
        return None
    segment = re.search(r'class=["\']text-rich-text\s+w-richtext["\'][^>]*>(.*?)<section\s+id=["\']faqs["\']', raw, re.I | re.S)
    description = clean_text(segment.group(1) if segment else posting.get("description"))
    title = clean_text(posting.get("title"))
    identifier = posting.get("identifier") or {}
    provider_job_id = clean_text(identifier.get("value")) if isinstance(identifier, dict) else clean_text(identifier)
    item = {
        "company": "Resideo", "title": title, "location": " / ".join(dict.fromkeys(locations)),
        "url": canonical_public_url(url), "source": "resideo", "description": description,
        "date_posted": posted, "provider_job_id": provider_job_id, "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in f"{title} {description}".casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    if not item.get("salary_max"):
        match = re.search(r"salary\s+for\s+this\s+role,?\s+ranges\s+from\s+USD\s*\$\s*([\d,.]+)\s+to\s+\$\s*([\d,.]+)", description, re.I)
        if match:
            low, high = sorted(float(value.replace(",", "")) for value in match.groups())
            item.update({
                "salary_text": f"${low:,.0f} - ${high:,.0f}",
                "salary_min": low, "salary_max": high, "salary_type": "base",
            })
    return item if title and description and item["url"] else None


def resideo_austin_jobs(
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from Resideo's public jobs API and detail pages."""
    try:
        request = urllib.request.Request(RESIDEO_JOBS_API, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read(20_000_000))
        listings = resideo_search_listings(payload)
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
        return [], [f"Resideo search: {type(exc).__name__}"]
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for listing in listings:
        try:
            request = urllib.request.Request(listing["detailUrl"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(15_000_000).decode("utf-8", "replace")
            item = resideo_job_item(raw, listing["detailUrl"], max_age_days=max_age_days)
            if item:
                results.append(item)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Resideo {clean_text(listing.get('title'))}: {type(exc).__name__}")
        if request_delay_seconds:
            time.sleep(max(2.0, request_delay_seconds))
    return results, errors


def greenhouse_listing_has_austin(job: dict[str, Any]) -> bool:
    """Read Austin from Greenhouse office and posting-location fields."""
    values: list[str] = []
    location = job.get("location") or {}
    if isinstance(location, dict):
        values.append(clean_text(location.get("name")))
    for office in job.get("offices") or []:
        if isinstance(office, dict):
            values.extend((clean_text(office.get("name")), clean_text(office.get("location"))))
    for field in job.get("metadata") or []:
        if not isinstance(field, dict) or clean_text(field.get("name")).casefold() != "job posting location":
            continue
        raw = field.get("value")
        values.extend(clean_text(value) for value in (raw if isinstance(raw, list) else [raw]))
    return any(re.search(r"\bAustin(?:,\s*(?:TX|Texas|US|United States))?\b", value, re.I) for value in values)


def greenhouse_display_location_has_austin(job: dict[str, Any]) -> bool:
    """Require Austin, Texas in Greenhouse's public-facing location label."""
    location = job.get("location") or {}
    value = clean_text(location.get("name")) if isinstance(location, dict) else ""
    return bool(re.search(r"\bAustin\s*,\s*(?:TX|Texas)\b", value, re.I))


def greenhouse_company_jobs(companies: set[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    results, errors = [], []
    for company, board in GREENHOUSE_BOARDS.items():
        if companies is not None and company not in companies: continue
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                # Large employers such as SpaceX publish thousands of complete
                # descriptions in one public board payload.
                payload = json.loads(response.read(35_000_000))
        except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        for job in payload.get("jobs", []):
            published_at = job.get("first_published") or job.get("updated_at")
            if not _fresh_iso_listing(published_at):
                continue
            if company == "Monks":
                # The branded office page identifies this Greenhouse office
                # as Austin, Texas while the board shortens it to "Austin".
                if not greenhouse_listing_has_austin(job):
                    continue
            elif company in {"Affirm", "MongoDB", "Seekr", "ZoomInfo", "Setpoint", "Sagent", "Juul Labs", "Avride", "CharterUP", "Optiver", "Zynga", "Vestwell", "Scorability", "inKind", "Auctane", "Atoms", "Two Chairs", "Telnyx", "Natera", "Duetto", "Navan", "Upshop", "Osano", "Ambiq", "ICON", "Iterable", "Kizen", "Grocery TV", "Lila Sciences"}:
                # These boards associate some postings with company offices
                # even when the displayed work-location field omits Austin.
                # Require the public posting itself to name Austin, Texas.
                if not greenhouse_display_location_has_austin(job):
                    continue
            elif company in {"Cloudflare", "Code and Theory", "Vectra AI", "Speechify", "Take-Two Interactive"} and not greenhouse_listing_has_austin(job):
                continue
            location = clean_text((job.get("location") or {}).get("name", ""))
            if company == "SpaceX" and location.casefold() not in {"austin, tx", "austin, texas"}:
                continue
            if company in {"Affirm", "MongoDB", "Seekr", "ZoomInfo", "Setpoint", "Monks", "Cloudflare", "Code and Theory", "Vectra AI", "Speechify", "Take-Two Interactive", "Sagent", "Juul Labs", "Avride", "CharterUP", "Optiver", "Zynga", "Vestwell", "Scorability", "inKind", "Auctane", "Atoms", "Two Chairs", "Telnyx", "Natera", "Duetto", "Navan", "Upshop", "Osano", "Ambiq", "ICON", "Iterable", "Kizen", "Grocery TV", "Lila Sciences"}:
                location = "Austin, TX"
            description = clean_text(job.get("content", ""))
            metadata = {str(item.get("name", "")).casefold(): item.get("value") for item in (job.get("metadata") or [])}
            location_type = str(metadata.get("location type", ""))
            arrangement = "remote" if "remote" in (location + " " + location_type).lower() else "onsite/hybrid"
            title = clean_text(job.get("title", ""))
            public_url = canonical_public_url(job.get("absolute_url", ""))
            if company == "ZoomInfo" and clean_text(job.get("requisition_id")) and clean_text(job.get("id")):
                slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-") or "job"
                public_url = canonical_public_url(
                    f"https://www.zoominfo.com/careers/{clean_text(job.get('requisition_id')).casefold()}/{slug}"
                    f"?gh_jid={clean_text(job.get('id'))}"
                )
            item = {"company": company, "title": title, "location": location,
                    "url": public_url, "source": "greenhouse", "description": description,
                    "date_posted": str(published_at or "")[:10] or None, "easy_apply": 0,
                    "work_arrangement": arrangement, "provider_job_id": clean_text(job.get("id"))}
            item.update(extract_salary(description))
            if item["url"]: results.append(item)
    return results, errors


def jobvite_search_listings(raw: str, board_url: str) -> list[dict[str, str]]:
    """Extract stable public Jobvite detail links before paced hydration."""
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for path, title in re.findall(
        r'<a[^>]+href=["\']([^"\']+/job/[^"\']+)["\'][^>]*>(.*?)</a>',
        raw,
        re.I | re.S,
    ):
        url = canonical_public_url(urllib.parse.urljoin(f"{board_url.rstrip('/')}/", path))
        if not url or url in seen:
            continue
        seen.add(url)
        results.append({"title": clean_text(title), "url": url})
    return results


def jobvite_job_item(company: str, raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a fresh Jobvite JSON-LD posting with exact Austin evidence."""
    posting: dict[str, Any] | None = None
    for value in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            posting = candidate
            break
    if not posting:
        return None
    raw_locations = posting.get("jobLocation")
    locations = raw_locations if isinstance(raw_locations, list) else [raw_locations]
    austin_address: dict[str, Any] | None = None
    for location in locations:
        address = location.get("address") if isinstance(location, dict) else None
        if not isinstance(address, dict):
            continue
        country = address.get("addressCountry")
        country_name = clean_text(country.get("name")) if isinstance(country, dict) else clean_text(country)
        if (
            clean_text(address.get("addressLocality")).casefold() == "austin"
            and clean_text(address.get("addressRegion")).casefold() in {"tx", "texas"}
            and country_name.casefold() in {"us", "usa", "united states", "united states of america"}
        ):
            austin_address = address
            break
    if not austin_address:
        return None
    posted = clean_text(posting.get("datePosted"))[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    title = clean_text(posting.get("title"))
    description = clean_text(posting.get("description"))
    provider_match = re.search(r"/job/([^/?#]+)", urllib.parse.urlsplit(url).path, re.I)
    item = {
        "company": company,
        "title": title,
        "location": "Austin, TX",
        "url": canonical_public_url(url),
        "source": "jobvite",
        "description": description,
        "date_posted": posted,
        "provider_job_id": provider_match.group(1) if provider_match else "",
        "easy_apply": 0,
        "work_arrangement": "remote" if any(
            "remote" in clean_text(location).casefold() for location in locations
        ) else "onsite/hybrid",
    }
    item.update(extract_salary(f"{description} {clean_text(raw)}", posting))
    return item if title and description and item["url"] else None


def jobvite_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin target roles from configured public Jobvite boards."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    for company, board_url in JOBVITE_SITES.items():
        if companies is not None and company not in companies:
            continue
        try:
            request = urllib.request.Request(board_url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(20_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        listings = [listing for listing in jobvite_search_listings(raw, board_url) if title_is_candidate(listing)]
        for index, listing in enumerate(listings):
            if index:
                time.sleep(delay)
            try:
                request = urllib.request.Request(listing["url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = response.read(20_000_000).decode("utf-8", "replace")
                item = jobvite_job_item(company, detail, listing["url"], max_age_days=max_age_days)
                if item:
                    results.append(item)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} {listing['title']}: {type(exc).__name__}")
    return results, errors


def paylocity_search_listings(raw: str) -> list[dict[str, Any]]:
    """Read the public job summaries embedded in a Paylocity careers page."""
    match = re.search(r"window\.pageData\s*=\s*(\{.*?\})\s*;", raw, re.S)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    results: list[dict[str, Any]] = []
    for job in payload.get("Jobs", []):
        location = job.get("JobLocation") or {}
        job_id = str(job.get("JobId") or "").strip()
        if not job_id:
            continue
        results.append({
            "provider_job_id": job_id,
            "title": clean_text(job.get("JobTitle")),
            "location": ", ".join(
                value for value in (
                    clean_text(location.get("City")),
                    clean_text(location.get("State")),
                    clean_text(location.get("Country")),
                ) if value
            ) or clean_text(job.get("LocationName")),
            "date_posted": str(job.get("PublishedDate") or "")[:10],
            "url": f"https://recruiting.paylocity.com/Recruiting/Jobs/Details/{job_id}",
        })
    return results


def paylocity_job_item(company: str, raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a fresh Paylocity JobPosting with an explicit Austin address."""
    posting: dict[str, Any] | None = None
    for value in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            posting = candidate
            break
    if not posting:
        return None
    address = ((posting.get("jobLocation") or {}).get("address") or {})
    city = clean_text(address.get("addressLocality"))
    region = clean_text(address.get("addressRegion"))
    country = clean_text(address.get("addressCountry"))
    if city.casefold() != "austin" or region.casefold() not in {"tx", "texas"}:
        return None
    posted = str(posting.get("datePosted") or "")[:10]
    if not _fresh_iso_listing(posted, max_age_days):
        return None
    description = clean_text(posting.get("description"))
    title = clean_text(posting.get("title"))
    remote_text = f"{title} {description}".casefold()
    is_remote = bool(re.search(
        r"\b(?:fully remote|remote[- ]first|work remotely|position is remote|role is remote|remote position)\b",
        remote_text,
    ))
    item = {
        "company": company,
        "title": title,
        "location": ", ".join(value for value in (city, region, country) if value),
        "url": canonical_public_url(url),
        "source": "paylocity",
        "description": description,
        "date_posted": posted,
        "provider_job_id": str(url).rstrip("/").rsplit("/", 1)[-1],
        "easy_apply": 0,
        "work_arrangement": "remote" if is_remote else "onsite/hybrid",
    }
    item.update(extract_salary(description, posting))
    return item if title and description else None


def paylocity_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect exact-Austin, on-level roles from public Paylocity pages."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    for company, board_url in PAYLOCITY_SITES.items():
        if companies is not None and company not in companies:
            continue
        try:
            request = urllib.request.Request(board_url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(15_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        candidates = [
            listing for listing in paylocity_search_listings(raw)
            if title_is_candidate(listing)
            and re.search(r"\bAustin,?\s+(?:TX|Texas)\b", listing.get("location", ""), re.I)
        ]
        for index, listing in enumerate(candidates):
            if index:
                time.sleep(delay)
            try:
                request = urllib.request.Request(listing["url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = response.read(15_000_000).decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} {listing['title']}: {type(exc).__name__}")
                continue
            item = paylocity_job_item(company, detail, listing["url"], max_age_days=max_age_days)
            if item:
                results.append(item)
    return results, errors


def _json_after_marker(raw: str, marker: str) -> dict[str, Any] | list[Any] | None:
    """Decode one public JSON value embedded after a stable script marker."""
    start = raw.find(marker)
    if start < 0:
        return None
    tail = raw[start + len(marker):].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(tail)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, (dict, list)) else None


def _ukg_exact_austin_location(opportunity: dict[str, Any]) -> str:
    for location in opportunity.get("Locations") or []:
        address = location.get("Address") if isinstance(location, dict) else None
        if not isinstance(address, dict):
            continue
        city = clean_text(address.get("City"))
        state_value = address.get("State") or {}
        country_value = address.get("Country") or {}
        state = clean_text(state_value.get("Code") or state_value.get("Name")) if isinstance(state_value, dict) else clean_text(state_value)
        country = clean_text(country_value.get("Code") or country_value.get("Name")) if isinstance(country_value, dict) else clean_text(country_value)
        if city.casefold() == "austin" and state.casefold() in {"tx", "texas"} and country.casefold() in {"us", "usa", "united states"}:
            postal = clean_text(address.get("PostalCode"))
            return ", ".join(value for value in (city, "TX" + (f" {postal}" if postal else ""), "USA") if value)
    return ""


def _ukg_opportunities_to_listings(
    payload: list[Any], board_url: str, max_age_days: int = 30,
) -> list[dict[str, Any]]:
    listings: list[dict[str, Any]] = []
    for opportunity in payload:
        if not isinstance(opportunity, dict):
            continue
        location = _ukg_exact_austin_location(opportunity)
        posted = str(opportunity.get("PostedDate") or "")[:10]
        job_id = clean_text(opportunity.get("Id"))
        title = clean_text(opportunity.get("Title"))
        if not location or not job_id or not title or not _fresh_iso_listing(posted, max_age_days):
            continue
        listings.append({
            "title": title,
            "location": location,
            "date_posted": posted,
            "url": f"{board_url.rstrip('/')}/OpportunityDetail?opportunityId={urllib.parse.quote(job_id)}",
            "provider_job_id": job_id,
        })
    return listings


def ukg_legacy_search_listings(raw: str, board_url: str, max_age_days: int = 30) -> list[dict[str, Any]]:
    """Read exact-Austin featured jobs from a public UKG board bootstrap."""
    payload = _json_after_marker(raw, "initialFeaturedOpportunities:")
    return _ukg_opportunities_to_listings(payload, board_url, max_age_days) if isinstance(payload, list) else []


def ukg_legacy_job_item(
    company: str,
    raw: str,
    url: str,
    board_id: str,
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize one public UKG detail, using its external-board publish date."""
    opportunity = _json_after_marker(raw, "new US.Opportunity.CandidateOpportunityDetail(")
    if not isinstance(opportunity, dict):
        return None
    location = _ukg_exact_austin_location(opportunity)
    if not location or opportunity.get("OpportunityIsClosed") is True:
        return None
    published = ""
    for membership in opportunity.get("JobBoardMemberships") or []:
        if not isinstance(membership, dict):
            continue
        if clean_text(membership.get("JobBoardId")).casefold() == board_id.casefold():
            published = str(membership.get("ExternalPostedDate") or "")[:10]
            break
    if not published:
        published = str(opportunity.get("PostedDate") or "")[:10]
    if not _fresh_iso_listing(published, max_age_days):
        return None
    description = clean_text(opportunity.get("Description"))
    title = clean_text(opportunity.get("Title"))
    job_id = clean_text(opportunity.get("Id"))
    if not title or not description or not job_id:
        return None
    item = {
        "company": company,
        "title": title,
        "location": location,
        "url": canonical_public_url(url),
        "source": "ukg",
        "description": description,
        "date_posted": published,
        "provider_job_id": job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if str(opportunity.get("JobLocationType") or "").casefold() == "remote" else "onsite/hybrid",
    }
    salary_data = {
        "baseSalary": {"value": {
            "minValue": opportunity.get("CompensationAnnualMinimum"),
            "maxValue": opportunity.get("CompensationAnnualMaximum"),
            "unitText": "YEAR",
        }}
    }
    item.update(extract_salary(description, salary_data))
    return item


def ukg_legacy_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh exact-Austin roles from curated public UKG boards."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    for company, board_url in UKG_LEGACY_BOARDS.items():
        if companies is not None and company not in companies:
            continue
        try:
            request = urllib.request.Request(board_url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(15_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        board_id = board_url.rstrip("/").rsplit("/", 1)[-1]
        listings = ukg_legacy_search_listings(raw, board_url, max_age_days)
        search_url = f"{board_url.rstrip('/')}/JobBoardView/LoadSearchResults"
        page_size = 50
        offset = 0
        while True:
            body = json.dumps({"OpportunitySearch": "", "Filters": [], "Top": page_size, "Skip": offset}).encode("utf-8")
            try:
                request = urllib.request.Request(
                    search_url,
                    data=body,
                    headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json", "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read(15_000_000).decode("utf-8", "replace"))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{company} search: {type(exc).__name__}")
                break
            opportunities = payload.get("opportunities") if isinstance(payload, dict) else None
            if not isinstance(opportunities, list):
                errors.append(f"{company} search: invalid response")
                break
            listings.extend(_ukg_opportunities_to_listings(opportunities, board_url, max_age_days))
            total = int(payload.get("totalCount") or 0)
            offset += page_size
            if offset >= total:
                break
            time.sleep(delay)
        deduped = {listing["url"]: listing for listing in listings}
        candidates = [listing for listing in deduped.values() if title_is_candidate(listing)]
        for index, listing in enumerate(candidates):
            if index:
                time.sleep(delay)
            try:
                request = urllib.request.Request(listing["url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    detail = response.read(15_000_000).decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} {listing['title']}: {type(exc).__name__}")
                continue
            item = ukg_legacy_job_item(company, detail, listing["url"], board_id, max_age_days)
            if item:
                results.append(item)
    return results, errors


def paycor_search_listings(raw: str, site: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse exact-Austin listings from a public Paycor/Newton career home."""
    listings: list[dict[str, Any]] = []
    pattern = re.compile(r'<a\s+href="(?P<url>[^"]*JobIntroduction\.action\?[^"]+)"[^>]*ns-qa="(?P<label>[^"]+)"', re.I)
    for match in pattern.finditer(raw):
        label = clean_text(match.group("label"))
        location_match = re.fullmatch(r"(?P<title>.+?)\s+-\s+(?P<location>Austin,\s*(?:TX|Texas))", label, re.I)
        if not location_match:
            continue
        detail_url = clean_text(match.group("url"))
        job_id = clean_text(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(detail_url).query)).get("id"))
        if not job_id:
            continue
        canonical = str(site["canonical_detail"]).rstrip("/") + "/?gnk=job&gni=" + urllib.parse.quote(job_id)
        listings.append({
            "title": clean_text(location_match.group("title")),
            "location": "Austin, TX",
            "url": canonical,
            "detail_url": detail_url,
            "provider_job_id": job_id,
        })
    return listings


def paycor_brand_date(raw: str) -> str:
    match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw, re.I)
    return match.group(1)[:10] if match else ""


def paycor_job_item(
    company: str,
    raw: str,
    url: str,
    date_posted: str,
    max_age_days: int = 30,
) -> dict[str, Any] | None:
    """Normalize a public Paycor/Newton detail with explicit Austin evidence."""
    def field(element_id: str) -> str:
        match = re.search(rf'<td[^>]+id="{re.escape(element_id)}"[^>]*>(.*?)</td>', raw, re.I | re.S)
        return clean_text(match.group(1)) if match else ""

    location = re.sub(r"^Location:\s*", "", field("gnewtonJobLocationInfo"), flags=re.I)
    if not re.fullmatch(r"Austin,\s*(?:TX|Texas)(?:,\s*(?:US|USA|United States))?", location, re.I):
        return None
    if not _fresh_iso_listing(date_posted, max_age_days):
        return None
    title = re.sub(r"^Position:\s*", "", field("gnewtonJobPosition"), flags=re.I)
    title = re.sub(r"\s+-\s+Austin,\s*(?:TX|Texas)\s*$", "", title, flags=re.I)
    description = field("gnewtonJobDescriptionText")
    job_id = clean_text(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("gni"))
    if not title or not description or not job_id:
        return None
    item = {
        "company": company,
        "title": title,
        "location": "Austin, TX",
        "url": canonical_public_url(url),
        "source": "paycor",
        "description": description,
        "date_posted": date_posted,
        "provider_job_id": job_id,
        "easy_apply": 0,
        "work_arrangement": "remote" if re.search(r"\b(?:fully remote|role is remote|position is remote)\b", description, re.I) else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    return item


def paycor_company_jobs(
    companies: set[str] | None = None,
    request_delay_seconds: float = 2.0,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh exact-Austin roles from curated public Paycor tenants."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    delay = max(2.0, float(request_delay_seconds))
    for company, site in PAYCOR_SITES.items():
        if companies is not None and company not in companies:
            continue
        home_url = (
            f"{site['career_url'].rstrip('/')}/CareerHome.action?"
            + urllib.parse.urlencode({"clientId": site["client_id"], "parentUrl": site["parent_url"]})
        )
        try:
            request = urllib.request.Request(home_url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(15_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        candidates = [
            listing for listing in paycor_search_listings(raw, site)
            if title_is_candidate(listing)
            or bool(re.fullmatch(r"(?:senior|sr\.?)\s+engineer", listing.get("title", ""), re.I))
        ]
        for index, listing in enumerate(candidates):
            if index:
                time.sleep(delay)
            try:
                brand_request = urllib.request.Request(listing["url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
                with urllib.request.urlopen(brand_request, timeout=30) as response:
                    brand = response.read(15_000_000).decode("utf-8", "replace")
                posted = paycor_brand_date(brand)
                if not _fresh_iso_listing(posted, max_age_days):
                    continue
                time.sleep(delay)
                detail_request = urllib.request.Request(listing["detail_url"], headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/html"})
                with urllib.request.urlopen(detail_request, timeout=30) as response:
                    detail = response.read(15_000_000).decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} {listing['title']}: {type(exc).__name__}")
                continue
            item = paycor_job_item(company, detail, listing["url"], posted, max_age_days)
            if item:
                results.append(item)
    return results, errors


def workable_company_jobs(companies: set[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Read public Workable Markdown feeds; no account or browser session required."""
    results, errors = [], []
    row_pattern = re.compile(
        r"^\|\s*(?P<title>[^|]+?)\s*\|\s*(?P<department>[^|]+?)\s*\|\s*(?P<location>[^|]+?)\s*\|"
        r"\s*(?P<type>[^|]+?)\s*\|\s*(?P<salary>[^|]+?)\s*\|\s*(?P<posted>[^|]+?)\s*\|"
        r"\s*\[View\]\([^)]*/(?P<code>[A-Z0-9]+)\.md\)\s*\|$"
    )
    for company, board in WORKABLE_BOARDS.items():
        if companies is not None and company not in companies: continue
        index_url = f"https://apply.workable.com/{board}/jobs.md"
        try:
            request = urllib.request.Request(index_url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/markdown"})
            with urllib.request.urlopen(request, timeout=25) as response:
                index = response.read(2_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        for line in index.splitlines():
            match = row_pattern.match(line.strip())
            if not match: continue
            fields = {key: clean_text(value) for key, value in match.groupdict().items()}
            code = fields["code"]
            detail_url = f"https://apply.workable.com/{board}/jobs/view/{code}.md"
            try:
                request = urllib.request.Request(detail_url, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "text/markdown"})
                with urllib.request.urlopen(request, timeout=25) as response:
                    description = clean_text(response.read(4_000_000).decode("utf-8", "replace"))
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
                errors.append(f"{company} {fields['title']}: {type(exc).__name__}")
                description = ""
            item = {
                "company": company, "title": fields["title"], "location": fields["location"],
                "url": f"https://apply.workable.com/{board}/j/{code}/", "source": "workable",
                "description": description, "date_posted": fields["posted"], "easy_apply": 0,
                "work_arrangement": "remote" if "remote" in fields["location"].lower() else "onsite/hybrid",
            }
            item.update(extract_salary(f"Salary Range: {fields['salary']} {description}"))
            results.append(item)
    return results, errors


def lever_posting_item(company: str, job: dict[str, Any]) -> dict[str, Any]:
    categories = job.get("categories") or {}
    location = clean_text(categories.get("location", ""))
    list_text = " ".join(clean_text(item.get("content", "")) for item in (job.get("lists") or []))
    description = clean_text(" ".join((str(job.get("descriptionPlain") or ""), list_text, str(job.get("additionalPlain") or ""))))
    created = job.get("createdAt")
    try:
        posted = datetime.fromtimestamp(float(created) / 1000, tz=timezone.utc).date().isoformat() if created else None
    except (TypeError, ValueError, OverflowError):
        posted = None
    salary = job.get("salaryRange") or {}
    item = {
        "company": company, "title": clean_text(job.get("text", "")), "location": location,
        "url": str(job.get("hostedUrl") or job.get("applyUrl") or ""), "source": "lever",
        "description": description, "date_posted": posted, "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in location.lower() else "onsite/hybrid",
    }
    item.update(extract_salary(description))
    if salary.get("min") is not None and salary.get("max") is not None:
        item.update({
            "salary_text": f"${float(salary['min']):,.0f} - ${float(salary['max']):,.0f}",
            "salary_min": float(salary["min"]), "salary_max": float(salary["max"]),
            "salary_type": str(salary.get("interval") or "year"),
        })
    return item


def lever_company_jobs(
    companies: set[str] | None = None,
    max_age_days: int = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read fresh public Lever postings for Austin and remote-first employers."""
    results, errors = [], []
    for company, board in LEVER_BOARDS.items():
        if companies is not None and company not in companies: continue
        api_host = LEVER_API_HOSTS.get(company, "https://api.lever.co")
        endpoint = f"{api_host}/v0/postings/{board}?mode=json"
        request = urllib.request.Request(endpoint, headers={"User-Agent": "EliOpportunityQueue/1.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read(20_000_000))
        except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError, socket.timeout, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{company}: {type(exc).__name__}")
            continue
        for job in payload if isinstance(payload, list) else []:
            item = lever_posting_item(company, job)
            if company in {"Qrypt", "Favor Delivery", "Atom Computing", "Cirrus Logic", "Sonar", "TTEC Digital"} and not re.search(r"\bAustin\s*,\s*(?:TX|Texas)\b", item["location"], re.I):
                continue
            if item["url"] and _fresh_iso_listing(item.get("date_posted"), max_age_days):
                results.append(item)
    return results, errors


def apple_job_item(raw: str, url: str, max_age_days: int = 30) -> dict[str, Any] | None:
    """Normalize a fresh Apple detail whose structured locations explicitly include Austin."""
    match = re.search(r'window\.__staticRouterHydrationData = JSON\.parse\((".*?")\);', raw, re.S)
    if not match:
        return None
    try:
        payload = json.loads(json.loads(match.group(1)))["loaderData"]["jobDetails"]["jobsData"]
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    locations = payload.get("locations") or payload.get("localeLocation") or []
    if not isinstance(locations, list):
        locations = []
    austin_locations = [
        location for location in locations
        if isinstance(location, dict)
        and clean_text(location.get("city") or location.get("name")).casefold() == "austin"
        and clean_text(location.get("stateProvince")).casefold() in {"tx", "texas"}
        and clean_text(location.get("countryName")).casefold() in {"us", "usa", "united states", "united states of america"}
    ]
    if not austin_locations:
        return None
    posted = clean_text(payload.get("postingDateMeta"))[:10]
    if not _fresh_iso_listing(posted, max_age_days=max_age_days):
        return None
    localized = ((payload.get("localizations") or {}).get("en_US") or {}).get("posting") or {}
    if not isinstance(localized, dict):
        localized = {}
    title = clean_text(payload.get("postingTitle") or localized.get("postingTitle"))
    if not title_is_candidate({"title": title}):
        return None
    description = clean_text(" ".join(str(localized.get(key) or payload.get(key) or "") for key in (
        "jobSummary", "description", "responsibilities", "minimumQualifications", "preferredQualifications"
    )))
    canonical_url = canonical_public_url(url)
    parsed = urllib.parse.urlsplit(canonical_url)
    if parsed.netloc.casefold() != "jobs.apple.com" or not re.fullmatch(r"/en-us/details/[^/]+/[^/]+", parsed.path):
        return None
    austin_ids = {clean_text(location.get("id")) for location in austin_locations}
    austin_footer = clean_text(" ".join(
        str((localized_footer or {}).get("content") or "")
        for footer in (payload.get("postingFooters") or [])
        if isinstance(footer, dict) and clean_text(footer.get("postLocationId")) in austin_ids
        for localized_footer in ((footer.get("localizations") or {}).get("en_US") or [])
        if isinstance(localized_footer, dict)
    ))
    item = {
        "company": "Apple",
        "title": title,
        "location": "Austin, TX" if len(locations) == 1 else "Austin, TX / Multiple US locations",
        "url": canonical_url,
        "source": "apple",
        "description": clean_text(f"{description} {austin_footer}"),
        "date_posted": posted,
        "provider_job_id": clean_text(payload.get("jobNumber") or payload.get("reqId") or payload.get("id")),
        "easy_apply": 0,
        "work_arrangement": "remote" if "remote" in description.casefold() else "onsite/hybrid",
    }
    item.update(extract_salary(austin_footer))
    return item if item["description"] else None


def apple_austin_jobs(max_pages: int = 8, max_age_days: int = 30) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect fresh target roles from Apple's official Austin search and details."""
    errors: list[str] = []
    listing_pattern = re.compile(
        r'<a class="link-inline[^"]*"[^>]*href="(?P<url>/en-us/details/[^"]+)"[^>]*>(?P<title>.*?)</a></h3>'
        r'.*?<span class="job-posted-date"[^>]*>(?P<date>.*?)</span>'
        r'.*?<div[^>]*job-title-location[^>]*>.*?<span[^>]*>(?:Location)?</span><span[^>]*>(?P<location>.*?)</span>',
        re.S | re.I,
    )
    listings: dict[str, dict[str, str]] = {}
    for page in range(1, max(1, max_pages) + 1):
        url = APPLE_AUSTIN_BOARD + (f"&page={page}" if page > 1 else "")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(8_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as exc:
            errors.append(f"Apple Austin page {page}: {type(exc).__name__}")
            continue
        for match in listing_pattern.finditer(raw):
            title = clean_text(match.group("title"))
            lowered = title.lower()
            senior = any(term in lowered for term in ("senior", "sr.", "sr ", "staff"))
            engineering = any(term in lowered for term in ("software", "backend", "platform", "infrastructure", "database", "reliability", "site reliability"))
            excluded = any(term in lowered for term in ("principal", "distinguished", "frontend", "front-end", "ios", "hardware", "director"))
            if not senior or not engineering or excluded: continue
            detail_url = "https://jobs.apple.com" + match.group("url").replace("&amp;", "&")
            listings[detail_url] = {"title": title, "date": clean_text(match.group("date")), "location": clean_text(match.group("location"))}

    def detail(entry: tuple[str, dict[str, str]]) -> dict[str, Any] | None:
        url, listing = entry
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 EliOpportunityQueue/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(12_000_000).decode("utf-8", "replace")
            return apple_job_item(raw, url, max_age_days=max_age_days)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append(f"Apple {listing['title']}: {type(exc).__name__}")
            return None

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="apple-job") as pool:
        results = [item for item in pool.map(detail, listings.items()) if item]
    return results, errors
