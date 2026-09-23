import json
import os
import unittest
from unittest.mock import patch

from jobfinder.application.resume_builder import _openai_resume, _response_output_text
from jobfinder.application.resume_targets import focus_selected_resume_targets


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return None
    def read(self): return json.dumps(self.payload).encode()


class ResumeBuilderAiTests(unittest.TestCase):
    def test_response_output_text_finds_assistant_json(self):
        payload = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"summary\":\"ok\"}"}]}]}
        self.assertEqual(_response_output_text(payload), '{"summary":"ok"}')

    def test_ai_generation_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                _openai_resume({}, [], "Staff Engineer")

    def test_ai_request_disables_storage_and_parses_structured_resume(self):
        resume = {"contact": {key: "" for key in ("name", "headline", "location", "phone", "email", "linkedin", "linkedin_url")}, "summary": "Grounded", "skills": {key: "" for key in ("Languages", "Platforms & Systems", "Leadership")}, "experience": [], "education": []}
        api_payload = {"id": "resp_123", "model": "gpt-test", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(resume)}]}]}
        captured = {}
        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data))
            return FakeResponse(api_payload)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch("jobfinder.application.resume_builder.urllib.request.urlopen", side_effect=fake_urlopen):
            result, metadata = _openai_resume(
                {},
                [{"id": "source-1", "kind": "review", "name": "review.txt", "text": "Improved latency by 20%."}],
                "Staff Engineer",
                [{
                    "company": "Target Co", "title": "Staff Backend Engineer", "location": "Austin, TX",
                    "actual_score": 8.7, "detected_skills": ["Python", "Distributed systems"],
                    "description": "Build a distributed backend platform.",
                }],
            )
        self.assertEqual(result["summary"], "Grounded")
        self.assertFalse(captured["store"])
        self.assertEqual(captured["text"]["format"]["type"], "json_schema")
        self.assertEqual(metadata["response_id"], "resp_123")
        self.assertIn("Staff Backend Engineer", captured["input"])
        self.assertIn("demand signals", captured["instructions"])
        self.assertIn("not evidence about the candidate", captured["instructions"])

    def test_selected_resume_targets_are_relevant_deduplicated_and_company_balanced(self):
        description = "Build Python backend platform services, distributed systems, APIs, and cloud infrastructure. " * 8
        rows = [
            {"company":"Alpha", "title":"Staff Backend Engineer", "location":"Austin, TX", "description":description, "actual_score":9.2, "age_days":2},
            {"company":"Alpha", "title":"Staff Backend Engineer", "location":"Remote, US", "description":description, "actual_score":9.0, "age_days":1},
            {"company":"Alpha", "title":"Senior Platform Engineer", "location":"Austin, TX", "description":description, "actual_score":8.8, "age_days":3},
            {"company":"Alpha", "title":"Senior Site Reliability Engineer", "location":"Austin, TX", "description":description, "actual_score":8.7, "age_days":3},
            {"company":"Beta", "title":"Staff Machine Learning Engineer", "location":"Austin, TX", "description":description, "actual_score":9.4, "age_days":1},
            {"company":"Gamma", "title":"Senior Backend Engineer", "location":"London, UK", "description":description, "actual_score":9.1, "age_days":1},
            {"company":"Delta", "title":"Senior Backend Engineer", "location":"Austin, TX", "description":description, "actual_score":6.9, "age_days":1},
        ]
        targets = focus_selected_resume_targets(rows, limit=10, per_company=2)
        self.assertEqual([(item["company"], item["title"]) for item in targets], [
            ("Alpha", "Staff Backend Engineer"),
            ("Alpha", "Senior Platform Engineer"),
        ])


if __name__ == "__main__": unittest.main()
