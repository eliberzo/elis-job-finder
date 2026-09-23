"""HTTP presentation adapter. Business rules live in application/domain/infrastructure."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import sys
import threading
import urllib.parse
import webbrowser

from jobfinder.application.read_models import filter_jobs_by_location_scope, jobs_view, resume_analysis_view
from jobfinder.application.workflows import enrich_compensation, import_jobs, rescore_and_enrich, run_company_board_collection, run_linkedin_collection, toggle_actual, toggle_practice, update_job_status
from jobfinder.application.workspaces import generate_resume_workspace, goals_workspace, local_events_workspace, original_resume_path, practice_workspace, resume_workspace, save_practice_workspace, save_resume_workspace, todo_workspace, toggle_todo_item, toggle_todo_item_blocker, update_local_event_status, upload_resume_source
from jobfinder.application.voice_interviews import finish_interview, interview_audio, interview_workspace, start_interview, submit_answer
from jobfinder.config import ACTUAL_RESUME_PATH, HOST, PORT, STATIC_DIR, TEMPLATE_PATH


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): sys.stdout.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))
    def send(self, status, body, content_type="application/json", headers=None):
        if isinstance(body, str): body = body.encode()
        self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body)))
        response_headers = {
            "Cache-Control": "no-store, max-age=0, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
        response_headers.update(headers or {})
        for key, value in response_headers.items(): self.send_header(key, value)
        self.end_headers(); self.wfile.write(body)
    def json(self, status, data): self.send(status, json.dumps(data))
    def body(self): return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/": return self.send(200, TEMPLATE_PATH.read_bytes(), "text/html; charset=utf-8")
        if path == "/resume/download":
            resume_path = original_resume_path()
            if not resume_path:
                return self.json(404, {"error": "Resume file not found"})
            return self.send(200, resume_path.read_bytes(), "application/pdf", {"Content-Disposition": f'attachment; filename="{resume_path.name}"'})
        if path in ("/resume/actual", "/resume/actual/download"):
            if not ACTUAL_RESUME_PATH.exists():
                return self.json(404, {"error": "Rebuilt resume has not been generated yet"})
            disposition = "attachment" if path.endswith("/download") else "inline"
            return self.send(200, ACTUAL_RESUME_PATH.read_bytes(), "application/pdf", {
                "Content-Disposition": f'{disposition}; filename="{ACTUAL_RESUME_PATH.name}"',
                "Cache-Control": "no-store",
            })
        if path in (
            "/static/styles.css", "/static/tabs.css", "/static/tooltips.css",
            "/static/resume.css", "/static/todo.css", "/static/practice.css", "/static/interview.css",
            "/static/app.js", "/static/resume.js", "/static/practice.js", "/static/interview.js", "/static/todo.js", "/static/goals.js",
        ):
            target = STATIC_DIR / path.rsplit("/", 1)[-1]
            return self.send(200, target.read_bytes(), "text/css; charset=utf-8" if target.suffix == ".css" else "application/javascript; charset=utf-8")
        if path == "/api/jobs": return self._jobs(query)
        if path == "/api/resume-analysis": return self._resume_analysis(query)
        if path == "/api/resume-builder": return self.json(200, resume_workspace())
        if path == "/api/practice-builder": return self.json(200, practice_workspace())
        if path == "/api/voice-interviews": return self.json(200, interview_workspace())
        audio_match = re.fullmatch(r"/api/voice-interviews/([^/]+)/audio/([^/]+)", path)
        if audio_match:
            audio, content_type = interview_audio(audio_match.group(1), audio_match.group(2))
            return self.send(200, audio, content_type)
        if path == "/api/local-events": return self.json(200, local_events_workspace())
        if path == "/api/todos": return self.json(200, todo_workspace())
        if path == "/api/goals": return self.json(200, goals_workspace())
        return self.json(404, {"error": "Not found"})

    def _resume_analysis(self, query=""):
        version = urllib.parse.parse_qs(query).get("version", ["current"])[0]
        return self.json(200, resume_analysis_view(version))

    def _jobs(self, query):
        raw = urllib.parse.parse_qs(query)
        params = {key: values[0] for key, values in raw.items() if values}
        return self.json(200, jobs_view(params))

    def do_POST(self):
        path = self.path.partition("?")[0]
        try:
            if path == "/api/resume-builder":
                payload = json.loads(self.body() or b"{}")
                return self.json(200, save_resume_workspace(payload))
            if path == "/api/resume-builder/source":
                return self.json(200, upload_resume_source(json.loads(self.body() or b"{}")))
            if path == "/api/resume-builder/generate":
                return self.json(200, generate_resume_workspace(json.loads(self.body() or b"{}")))
            if path == "/api/practice-builder":
                payload = json.loads(self.body() or b"{}")
                return self.json(200, save_practice_workspace(payload))
            if path == "/api/voice-interviews/start":
                return self.json(200, start_interview(json.loads(self.body() or b"{}")))
            answer_match = re.fullmatch(r"/api/voice-interviews/([^/]+)/answer", path)
            if answer_match:
                return self.json(200, submit_answer(answer_match.group(1), json.loads(self.body() or b"{}")))
            finish_match = re.fullmatch(r"/api/voice-interviews/([^/]+)/finish", path)
            if finish_match:
                return self.json(200, finish_interview(finish_match.group(1)))
            event_match = re.fullmatch(r"/api/local-events/([^/]+)/status", path)
            if event_match:
                return self.json(200, update_local_event_status(event_match.group(1), json.loads(self.body() or b"{}")))
            if path == "/api/discover/linkedin":
                return self.json(200, run_linkedin_collection(json.loads(self.body() or b"{}")))
            if path == "/api/discover/company-boards":
                return self.json(200, run_company_board_collection(json.loads(self.body() or b"{}")))
            if path == "/api/import":
                return self.json(200, import_jobs(self.body().decode("utf-8-sig"), self.headers.get("Content-Type", "")))
            if path == "/api/rescore": return self.json(200, rescore_and_enrich())
            if path == "/api/enrich/compensation": return self.json(200, enrich_compensation())
            todo_match = re.fullmatch(r"/api/todos/([^/]+)/toggle", path)
            if todo_match: return self.json(200, toggle_todo_item(todo_match.group(1)))
            blocker_match = re.fullmatch(r"/api/todos/([^/]+)/block", path)
            if blocker_match: return self.json(200, toggle_todo_item_blocker(blocker_match.group(1)))
            if path == "/api/companies/toggle":
                company = json.loads(self.body() or b"{}").get("company", "")
                return self.json(200, toggle_actual(company))
            if path == "/api/companies/toggle-practice":
                company = json.loads(self.body() or b"{}").get("company", "")
                return self.json(200, toggle_practice(company))
            match = re.fullmatch(r"/api/jobs/(\d+)/status", path)
            if match:
                status = json.loads(self.body() or b"{}").get("status")
                return self.json(200, update_job_status(match.group(1), status))
        except LookupError as exc: return self.json(404, {"error": str(exc)})
        except Exception as exc: return self.json(400, {"error": str(exc)})
        return self.json(404, {"error": "Not found"})

def serve(open_browser=True):
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Eli's Opportunity Queue running at http://{HOST}:{PORT}\nPress Ctrl+C to stop. SQLite and jobs.jsonl persist every change.")
    if open_browser: threading.Timer(.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nStopped.")
    finally: server.server_close()
