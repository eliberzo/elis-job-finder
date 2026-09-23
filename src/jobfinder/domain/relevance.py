"""Profile-independent rules defining the job family the collector may persist."""
import re
from typing import Any
from jobfinder.domain.eligibility import requires_security_clearance, requires_us_citizenship
from jobfinder.domain.locations import is_austin_proper_location, is_explicitly_non_us_location


def title_is_candidate(job: dict[str, Any]) -> bool:
    title = str(job.get("title", "")).lower()
    description = str(job.get("description", "")).lower()
    technical_manager_variant = "manager" in title and any(term in title for term in (
        "ai engineer", "devops", "technical lead", "software lead", "backend lead",
        "platform lead", "infrastructure lead", "data engineering lead", "cloud engineering lead",
        "data engineer", "systems engineer",
    ))
    data_platform_people_manager = (
        "data platform" in title
        and "manager" in title
        and "product" not in title
        and "data engineering" in description
        and bool(re.search(r"\b(?:manage|lead|grow)\b.{0,50}\bdata engineers\b", description))
    )
    engineering_manager = any(term in title for term in (
        "engineering manager", "manager, software engineering", "manager software engineering",
        "manager, engineering", "manager engineering", "manager of software engineering",
        "software development manager", "software development engineering",
        "manager, software development & engineering", "manager software development & engineering",
        "software development & engineering manager",
    )) or bool(re.search(r"\bmanager\b.{0,35}\b(?:software|backend|platform|infrastructure|data|cloud|ai|ml|site reliability) engineering\b", title)) \
        or bool(re.search(r"\bmanager,?\s+engineering\b.{0,35}\b(?:observability|platform|backend|infrastructure|data|cloud|ai|ml|site reliability)\b", title)) \
        or bool(re.search(r"\bmanager,?\s+(?:secrets management|identity|security)\s+platform\b", title)) \
        or bool(re.search(r"\b(?:full[- ]?stack|forward deployed)\s+(?:engineer(?:ing)?\s*[-/]?\s*)?manager\b", title)) \
        or technical_manager_variant or data_platform_people_manager
    seniority = any(term in title for term in (
        "senior", "sr.", "sr ", "staff", "software engineer ii", "software engineer iii",
        "software engineer 2", "software engineer 3", "engineer ii", "engineer iii", "engineer 2", "engineer 3",
        "software developer iii", "software developer 3",
        "mts 1", "mts 2",
        "backend engineer ii", "backend engineer iii",
        "full stack engineer ii", "full stack engineer iii", "technical lead", "technical leader",
        "tech lead", "tech leader", "technology lead", "backend lead", "lead backend", "platform lead",
        "lead software engineer", "lead system integration engineer", "lead systems integration engineer",
        "software technical leader", "software tech leader", "software development & engineering lead",
    )) or bool(re.search(r"\blead\b.{0,30}\b(?:software|backend|platform|infrastructure|data|cloud|ai|ml)\b", title)) \
        or bool(re.search(
            r"\b(?:site reliability|reliability|software|backend|platform|infrastructure|data|cloud|ai|ml)\s+"
            r"(?:engineering\s+)?lead\b",
            title,
        ))
    over_level = any(term in title for term in ("principal", "distinguished", "fellow"))
    security_research_software = "security research engineer" in title and sum(
        signal in description for signal in (
            "internal tooling", "data pipeline", "cloud infrastructure",
            "infrastructure as code", "ci/cd", "etl pipeline", "python", "golang",
        )
    ) >= 3
    engineering = any(term in title for term in (
        "software", "backend", "back-end", "fullstack", "full-stack", "full stack", "platform", "infrastructure", "distributed", "golang",
        "java developer", "java engineer", "java tech lead", ".net developer",
        "database", "data engineer", "cloud engineer", "systems engineer", "reliability", "site reliability", "sre", "devops", "mlops", "ml-ops", "observability", "orchestration",
        "security engineer", "cybersecurity engineer", "iam engineer", "iam automation", "identity engineer", "identity platform",
        "detection engineer",
        "machine learning", "ml engineer", "ml systems engineer", "machine learning systems engineer",
        "ai engineer", "ai/ml", "ai automation", "ai platform", "ai infrastructure", "llm",
        "technology lead",
        "system integration engineer", "systems integration engineer",
        "systems engineer ii", "systems engineer iii", "systems engineer 2", "systems engineer 3",
    )) or security_research_software or bool(re.search(r"\bapi\b", title)) or bool(re.search(
        r"\bengineer\s+(?:ii|iii|2|3)\s*[,/\-]?\s*(?:data|cloud|platform|infrastructure|backend|back-end|ai|ml)\b",
        title,
    ))
    excluded = any(term in title for term in (
        "frontend", "front-end", "front end",
        "mobile", "ios", "android", "ui/uix", "qa ", "quality assurance", "test engineer",
        "embedded", "firmware", "hardware", "chassis", "soft goods", "asic", "vlsi", "chip design", "photonic", "post-silicon",
        "analog engineering",
        "flight software", "graphics", "compiler", "simulation", "wireless", "windows sensor", "linux sensor", "macos sensor", "sensor event", "sensor - mac",
        "zephyr", "open bmc", "openbmc", "graviton software", "cuda driver", "gpu driver", "driver development",
        "wheeled controls", "software engineer - radio", "rf software", "support engineer", "accelerator servers",
        "machine learning accelerators", "virtual platform", "cutlass kernels", "computational engineer",
        "onestream", "epm development", "power platform", "data engineer (bi)", "motorsports",
        "software packager", "network infrastructure engineer",
        "military talent program", "tech architect", "solutions architect", "solutions engineer", "solutions engineering", "customer engineer", "developer advocate", "developer advocacy",
        "consultant", "supplier quality", "quality engineer", "physical security",
        "technical sourcing specialist",
        "research engineer", "research scientist", "applied research", "perception research", "phd early career",
        "product designer", "experience designer", "ux designer", "ui designer", "data scientist", "counsel",
        "product manager", "product owner", "project manager", "program manager", "customer engineering manager", "solutions engineering manager",
        "planner",
        "strategy & operations lead", "software strategy lead", "director", "cashier", "sales", "recruiter",
        "talent acquisition", "talent team", "talent lead",
        "humanoid controls", "robotics manipulation", "robotics systems engineer",
        "ml acceleration system software", "ml acceleration systems software", "soc devops",
        "post-silicon validation", "post silicon validation",
        "water systems engineer", "ai/ml servers", "mainframe",
        "electrical", "product engineering manager",
        "pd methodology engineer",
        "production engineering manager", "applications engineering manager",
        "project engineering manager", "mechanical engineering manager", "manufacturing engineering manager",
        "water department engineering manager",
        "vp,", "vp ", "vpii", "vice president",
    ))
    executive_level = bool(re.match(r"^(?:a|e|s)?vp(?:ii)?(?=$|[\s,/\-()])", title.strip()))
    nonsoftware_reliability = "reliability engineer" in title and "software" not in title and "site reliability" not in title
    unrelated_manager = "manager" in title and not engineering_manager
    # Some first-party employers publish the externally visible title only as
    # "Senior Engineer" while the detail explicitly identifies full-stack
    # software engineering. Require those strong detail signals so hardware or
    # construction roles with the same generic title do not enter the queue.
    generic_software_senior = bool(re.fullmatch(r"(?:senior|sr\.?)\s+engineer", title.strip())) and (
        "full stack senior engineer" in description
        or "internal title: manager, software engineering" in description
        or "internal title ‘manager, software engineering’" in description
    )
    # Some employers expose a deliberately broad "Staff Engineer" title for
    # senior data-infrastructure software roles. Admit it only when the full
    # employer description supplies a dense cluster of software and data-
    # platform evidence, keeping generic hardware and facilities roles out.
    generic_software_staff = bool(re.fullmatch(r"staff\s+engineer", title.strip())) and sum(
        signal in description for signal in (
            "software engineer", "software developer", "data pipeline", "big data",
            "hadoop", "spark", "kafka", "postgres", "cassandra", "python", "java",
            "scala", "sql", "nosql", "scalability",
        )
    ) >= 4
    generic_technical_lead = bool(re.fullmatch(
        r"(?:senior|sr\.?)?\s*(?:technical|tech)\s+(?:team\s+)?lead",
        title.strip(),
    )) and any(signal in description for signal in (
        "software", "full stack", "full-stack", "fullstack", "backend", "back-end",
        "microservice", "api", "java", ".net", "python", "cloud platform", "distributed system",
    ))
    generic_technical_system_senior = bool(re.fullmatch(
        r"(?:senior|sr\.?)\s+system\s+engineer",
        title.strip(),
    )) and sum(signal in description for signal in (
        "software engineering", "platform engineering", "infrastructure engineering",
        "cloud engineering", "distributed systems", "infrastructure as code",
        "site reliability", "devops", "ci/cd", "microservices", "backend", "back-end",
    )) >= 2
    mainframe_software_manager = "mainframe" in title and "software engineering manager" in title
    return (engineering_manager or generic_software_senior or generic_software_staff or generic_technical_lead or generic_technical_system_senior or (seniority and engineering)) and not unrelated_manager and (not excluded or mainframe_software_manager or security_research_software) and not over_level and not executive_level and not nonsoftware_reliability


def posting_is_relevant(job: dict[str, Any]) -> bool:
    if not title_is_candidate(job): return False
    # A multi-location employer posting can legitimately include both Austin
    # and a foreign office. Exact Austin, Texas evidence keeps that posting in
    # scope; foreign-only records remain excluded.
    if is_explicitly_non_us_location(job.get("location")) and not is_austin_proper_location(job.get("location")): return False
    description = str(job.get("description", "")).lower()
    if len(description) < 250: return False
    if re.search(r"\bmanagement level\s+(?:director|vice president)\b|\bas (?:a|the) director\b", description):
        return False
    if re.search(
        r"\b(?:this\s+)?(?:role|position)\s+is\s+(?:for\s+)?(?:a\s+)?principal[- ]level\b|"
        r"\b(?:this\s+)?(?:role|position|(?:senior|staff)?\s*[a-z0-9/&,.()' -]{2,80}(?:engineer|developer|architect|manager))\s+"
        r"(?:is|serves as)\s+(?:a\s+)?principal[- ]level\s+technical\s+leader\b",
        description,
    ):
        return False
    normalized_title = re.sub(r"\s+", " ", str(job.get("title", "")).strip().casefold())
    if normalized_title in {"engineering manager", "manager, engineering", "manager engineering"} and not any(
        signal in description for signal in (
            "software engineering", "software engineer", "software architecture", "backend", "back-end", "site reliability", "data engineering",
            "machine learning", "cloud platform", "infrastructure platform", "distributed systems",
        )
    ):
        return False
    if requires_security_clearance(description) or requires_us_citizenship(description): return False
    frontend_heavy = any(term in normalized_title for term in ("frontend", "front-end", "front end"))
    frontend_architecture_focused = (
        "web frontend architect" in description
        or ("frontend architecture standards" in description and "component library" in description)
    ) and not any(term in description for term in ("backend", "back-end", "server-side", "microservice", "database", "kafka"))
    explicitly_frontend_focused = bool(re.search(
        r"(?:\bthis\s+is\s+|\b(?:role|position)\s+is\s+)(?:an?\s+)?"
        r"front[- ]?end[- ]focused\b|"
        r"\bfront[- ]?end[- ]focused\b[^.]{0,60}\b(?:role|position)\b",
        description,
    ))
    user_interface_focused = "user-facing applications" in description and any(term in description for term in ("ui framework", "ux designer", "user experience"))
    mobile_application_focused = sum(term in description for term in (
        "ios app lifecycle", "objective-c", "uikit", "swiftui", "android sdk",
        "android application", "mobile application", "mobile app development",
    )) >= 2 and not any(term in description for term in (
        "backend", "back-end", "server-side", "microservice", "cloud platform",
        "distributed system",
    ))
    game_engine_focused = "game engine" in description or "rest of the engine is built on" in description
    hardware_focused = any(term in description for term in (
        "datacenter infrastructure equipment", "reliability test plan", "stress based mtbf",
        "embedded software engineer", "cloud hardware products", "server hardware, firmware",
        "board management controller", "hardware/software interface", "hw/sw interface", "low-level driver",
        "autonomous surface vessels", "pre-silicon development", "pre-silicon and post-silicon", "hardware evaluation platforms",
        "ai-assisted silicon design", "performance, power, and area", "satellites, uavs",
        "silicon and platform power-performance architecture", "platform power and performance strategy",
        "microarchitecture and rtl development", "rtl design in systemverilog",
        "pre-silicon validation, silicon bring-up", "device-driver architecture, embedded or real-time software",
        "semiconductor operations", "embedded or distributed software applications", "device drivers and real-time programming",
        "material handling equipment", "industrial control systems", "human machine interfacing",
    )) or (
        "real-time embedded development" in description
        and "hardware devices" in description
    )
    field_systems_hardware_manager = (
        "field systems engineering manager" in normalized_title
        and sum(signal in description for signal in (
            "sensing hardware", "field devices", "signal electronics", "firmware",
            "electrical troubleshooting", "sensors", "power electronics",
        )) >= 2
    )
    embedded_benchmarking = (
        "embedded systems performance" in description
        and sum(signal in description for signal in (
            "semiconductor", "silicon", "soc", "rtos", "oscilloscope",
            "logic analyzer", "hardware emulation", "silicon bring-up",
        )) >= 2
    )
    power_grid_engineering = (
        any(signal in normalized_title for signal in ("power systems engineer", "ercot modeling"))
        and sum(signal in description for signal in (
            "electrical engineering", "power grid", "power system impact",
            "generator interconnection", "dynamic stability", "pss/e", "pscad",
        )) >= 2
    )
    disguised_test_engineering = (
        "software development engineer in test (sdet)" in description
        or "software development engineer in test lead" in description
        or "sdet lead" in description
        or ("test engineer position" in description and "server production" in description and "production floor" in description)
    )
    office_administration_focused = (
        "microsoft 365 platform engineer" in normalized_title
        and sum(signal in description for signal in (
            "administer", "sharepoint online", "power automate", "license administration",
            "microsoft 365 apps", "copilot studio",
        )) >= 3
    )
    device_administration_focused = (
        "systems software engineering" in normalized_title
        and "device-management systems and services" in description
        and "enterprise printing services" in description
    )
    security_operations_focused = (
        "threat detection engineer" in normalized_title
        and "threat hunting" in description
        and "siem platforms" in description
        and "purple team" in description
    )
    design_system_ui_focused = (
        "design system" in normalized_title
        and "reusable components" in description
        and "ios" in description and "android" in description
    )
    operations_consulting_without_software_build = (
        "operations consulting" in description
        and "operational challenges" in description
        and not any(signal in description for signal in (
            "develop software", "build software", "software engineering", "software development",
            "build applications", "build services", "write code",
        ))
    )
    if frontend_heavy or frontend_architecture_focused or explicitly_frontend_focused or user_interface_focused or mobile_application_focused or game_engine_focused or hardware_focused or field_systems_hardware_manager or embedded_benchmarking or power_grid_engineering or disguised_test_engineering or office_administration_focused or device_administration_focused or security_operations_focused or design_system_ui_focused or operations_consulting_without_software_build: return False
    backend_signals = (
        "backend", "back-end", "server-side", "full stack", "full-stack", "fullstack",
        "distributed system", "microservice", "platform", "infrastructure", "cloud", "kafka",
        "database", "data ecosystem", "data architecture", "data pipeline", "etl/elt", "python", "golang", "java",
    )
    applied_ai_engineering = any(term in normalized_title for term in ("ai engineer", "machine learning engineer", "ml engineer")) and sum(
        signal in description for signal in (
            "developing ai/ml systems", "integrating ai into products",
            "deploying llms into production", "designing and optimizing rag pipelines",
            "building production ai systems",
        )
    ) >= 2
    return applied_ai_engineering or any(signal in description for signal in backend_signals) or bool(re.search(r"\bapis?\b", description))
