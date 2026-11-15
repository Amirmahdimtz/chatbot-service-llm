# Stage 8 — Specialized scenario implementation

## Shared API contract

`POST /api/v1/chat/stream` accepts `message`, `conversation_id` (optional), `scenario`, and for all scenarios except `religious_qa`, an object `scenario_input`. Legacy `general`, `knowledge_qa` and `agent_qa` remain unchanged.

| Scenario | Server permission | Valid scenario_input |
| --- | --- | --- |
| `religious_qa` | public; internal requires `knowledge:read_internal` | omit |
| `personnel_matching` | internal `chat:use_internal` + `hr:analyze` | `{"position_id":"senior"}` |
| `talent_discovery` | internal `chat:use_internal` + `hr:analyze` | `{"employee_id":"alice"}` |
| `internal_transfers` | internal `chat:use_internal` + `hr:analyze` | `{"employee_id":"alice"}` |
| `research_advice` | internal `chat:use_internal` + `research:analyze` | `{"context_tags":["python"],"include_knowledge":false}` |
| `personal_development` | internal `chat:use_internal` + `development:analyze`, plus `hr:analyze` or `development:self` for own ID | `{"employee_id":"alice","target_position_id":"senior","weeks":8}` |
| `task_allocation` | internal `chat:use_internal` + `tasks:analyze` | `{"plan_id":"plan1"}` |

Internal identity, tenant and permissions must be server-trusted; the Development Bearer token creates only a synthetic **public** identity. Production without trusted identity remains fail-closed. The application ignores user claims of audience/tenant and rejects identity headers. Tests simulate a trusted synthetic internal principal by monkeypatching only the identity boundary.

## Data ingestion and lifecycle

`PUT /api/v1/scenario/records/{kind}/{key}` takes `{"audience":"internal","payload":{...}}`, restricted to internal `scenario:manage`. Kinds are `personnel`, `position`, `unit`, `research`, `task_plan`, `faq` and `development_progress`; schemas are in `src/core/services/scenarios/scenario_contracts.py`. Unknown fields and sensitive/non-job-relevant attributes are rejected. Records are tenant-scoped and versioned, with uniqueness per audience/tenant/kind/key. Data are not seeded in production.

`faq` records require `religious:verify` and include a source reference, source title and expert reference. Only this permission can approve/publicly expose one. Exact normalized question/alias equality returns an approved FAQ; semantic equivalence is never presumed. Otherwise authorized RAG provides document citations, or an owner-scoped durable pending marker records insufficient evidence. SQL FAQ updates are immediately active without a Qdrant reindex; other approved documents continue using existing Knowledge ingestion/reindex. `GET /api/v1/scenario/pending/{pending_id}` is restricted to the original requester.

`GET /api/v1/scenario/records/{kind}/{key}` is manager/expert-only. `POST /api/v1/scenario/progress` accepts `employee_id`, `position_id` and `completed_skills`, restricted to `scenario:manage` or `development:self` for the authenticated employee. Progress is keyed by a deterministic hash and read for reassessment.

PostgreSQL stores scenario records and history; Qdrant retains exactly `knowledge_public` and `knowledge_internal` and is used only for document retrieval. Schema migrations `20261115_03` (additive scenario records) and `20261115_04` (additive nullable `chat_messages.scenario_payload`) preserve existing rows. Never run downgrade against preserved data.

## Deterministic evidence and constraints

- Matching: mandatory skills, minimum experience, vacancy and availability are hard filters. Preference rank uses the **count** of satisfied preferred skill requirements, with stable ID tie-break. No invented psychometric or normalized suitability score.
- Talent: evaluate open positions; return eligibility, explicit missing skills, experience gaps and available goal-word overlap.
- Transfers: require mobility allowance, destination capacity, open vacancy and mandatory job criteria; never change the employee's actual position.
- Research: match actual sourced experience tags/problem text, disclose contextual differences, benefits, risks, assumptions and measurable evaluation criteria. Optional `include_knowledge=true` fetches authorized RAG document citations when `knowledge:read_internal` is present; no invented document conclusion.
- Development: compute target skill levels vs existing and recorded progress, create week milestones and evaluation indicators; suggested timelines are not promises.
- Tasks: Kahn topological ordering rejects cycles and unknown dependencies; proposals consume available unit hours in memory, check skills and report unassigned tasks. No actual task assignment is executed.

Agent workflows use a single server-selected, schema-validated read-only tool per explicit structured scenario, sharing the existing Agent concurrency/timeout limits. The LLM is *not* trusted with hard constraints. Tool results are untrusted data, not system instructions.

## SSE and persistence

Existing events are preserved. New `scenario_result` contains `result: {scenario, status, items, limitations, sources}` for the six structured workflows, or `result: {scenario, response_type, sources, pending_id}` for Religious QA. Other relevant events are `tool_start`, `tool_result`, `sources`, `delta` and `message_end`. Religious response types distinguish `verified_faq`, `rag_generated` and `insufficient_evidence`. Completed structured outputs are also stored in `chat_messages.scenario_payload` and visible in Conversation history.

Current bounded catalogue reads cover up to 200 records per kind and must be paginated before use with larger organizations. Source consistency, production permissions and real LLM/RAG performance require local/organizational evaluation.

## Windows PowerShell validation

First inspect changes; **do not pull over uncommitted work**.

```powershell
Set-Location D:\chatbot-service-llm
git status --short
git pull --ff-only origin main
docker compose config --quiet
docker compose up -d --build --wait
docker compose exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini upgrade head
docker compose exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini current
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/test_stage8_unit.py tests/test_stage8_api.py tests/test_stage8_migration.py
python -m pytest -q
docker compose ps
docker compose logs --tail 100 app
```

For a missing checkout use `git clone https://github.com/Amirmahdimtz/chatbot-service-llm.git D:\chatbot-service-llm`. The Stage 8 API integration tests simulate all seven paths and trusted internal identities with synthetic records; default Development identity cannot call internal endpoints by design.

For feedback send redacted output of `pytest`, `alembic current`, `docker compose ps` and only error lines from app logs. Never share secrets, `.env`, private personnel data or token-bearing headers.
