import unittest
from datetime import date

from jobfinder.application.corpus_report import analyze_jobs


DESCRIPTION = (
    "Build Python distributed systems, cloud APIs, data platforms, Kafka, "
    "Kubernetes, SQL, and reliable backend services. " * 7
)


class CorpusReportTests(unittest.TestCase):
    def test_recent_official_austin_roles_are_deduplicated_and_ranked(self):
        rows = [
            {"company": "Example Inc.", "title": "Senior Backend Software Engineer", "location": "Austin, TX",
             "url": "https://example.com/jobs/1", "source": "greenhouse",
             "description": DESCRIPTION, "date_posted": "2026-09-20"},
            {"company": "Example", "title": "Senior Backend Software Engineer", "location": "Austin, TX",
             "url": "https://linkedin.com/jobs/view/1", "source": "linkedin",
             "description": DESCRIPTION, "date_posted": "2026-09-21"},
            {"company": "Other", "title": "Staff Backend Software Engineer", "location": "Austin, Texas",
             "url": "https://other.example/jobs/2", "source": "ashby",
             "description": DESCRIPTION, "date_posted": "2026-09-19"},
            {"company": "Old", "title": "Senior Backend Software Engineer", "location": "Austin, TX",
             "url": "https://old.example/jobs/3", "source": "greenhouse",
             "description": DESCRIPTION, "date_posted": "2026-07-01"},
            {"company": "Nearby", "title": "Senior Backend Software Engineer", "location": "Round Rock, TX",
             "url": "https://nearby.example/jobs/4", "source": "greenhouse",
             "description": DESCRIPTION, "date_posted": "2026-09-20"},
        ]
        report = analyze_jobs(rows, today=date(2026, 9, 23), include_linkedin=True)
        self.assertEqual(report["unique_jobs"], 2)
        self.assertEqual(report["unique_companies"], 2)
        self.assertEqual(report["jobs_with_common_skills"][0]["url"], "https://example.com/jobs/1")
        self.assertEqual(report["common_skills"][0]["jobs"], 2)
        self.assertEqual(report["common_skills"][0]["percent"], 100.0)

    def test_no_recent_jobs_produces_empty_report(self):
        report = analyze_jobs([], today=date(2026, 9, 23))
        self.assertEqual(report["unique_jobs"], 0)
        self.assertEqual(report["common_skills"], [])
        self.assertEqual(report["jobs_with_common_skills"], [])


if __name__ == "__main__":
    unittest.main()
