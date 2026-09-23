# Opportunity Queue architecture

The SQLite/JSONL job corpus is shared infrastructure. Features access it through the storage module or through application read models and workflows; the browser-facing HTTP server does not own query, scoring, or mutation rules.

## Dependency direction

```text
web UI / HTTP presentation
          ↓
application read models + workflows
          ↓
domain rules          infrastructure adapters
                           ↓
                  jobs.db + JSONL mirrors
```

## Modules

- `domain/` contains pure decisions: relevance, eligibility, locations, résumé matching, and résumé review. `ranking.py` first derives an immutable `JobSignals` snapshot, then evaluates fit, practice, strategic-cost, application, salary, and explanation rules. Each scoring stage emits structured `RuleResult` contributions for an explainable ranking breakdown; `matching.score()` remains a compatibility entry point. The domain layer does not fetch pages or serve HTTP.
- `infrastructure/storage.py` owns the one denormalized jobs table and text mirrors. `providers.py`, `aggregator.py`, and `levels.py` adapt external job and compensation sources.
- `application/collection.py` is the mining pipeline. It fetches relevant candidates, rate-limits detail collection, deduplicates, and persists raw records without résumé scoring.
- `application/service.py` is the scoring service. It normalizes records, calculates company signals, scores jobs, and rebuilds derived caches after persistence.
- `application/compensation.py` enriches missing compensation separately from both collection and presentation.
- `application/read_models.py` builds read-only job-table and résumé-analysis payloads for any presentation client.
- `application/workflows.py` coordinates state-changing operations: mining followed by scoring/enrichment, imports, saved-company changes, and job status transitions.
- `application/workspaces.py` exposes resume, interview-practice, and todo use cases without leaking their persistence adapters into HTTP code.
- `application/interview_prep.py` cross-references sourced interview research with the companies currently selected in the shared jobs database.
- `presentation/webapp.py` is a thin HTTP adapter: parse requests, call an application use case, and serialize the response.
- `web/static/app.js` owns shared navigation, filters, the company/job tree, and job actions.
- `web/static/resume.js`, `practice.js`, and `todo.js` own their feature-specific presentation and interactions. They share the core browser helpers but do not query the database or calculate ranks.
- `web/templates/` and the CSS files define markup and styling independently from mining, matching, and persistence.

## Mining lifecycle

```text
public source → provider adapter → normalization → relevance/eligibility
→ deduplication → raw persistence → scoring → compensation enrichment
→ Top 40 cache + JSONL mirror → read model → UI
```

Raw collection completes before scoring. This keeps network concurrency and the persistence queue independent from résumé matching and makes future collectors or presentation clients replaceable.

Interview research follows a similar boundary: public reports are summarized into `data/leetcode_research.json`; the progressive whiteboard curriculum lives independently in `data/whiteboard_question_bank.json`; the application layer filters both against companies selected in `jobs.db`; the Practice Builder only renders the resulting study view.
