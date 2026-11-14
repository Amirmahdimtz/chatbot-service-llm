# Stage 6 — Authorized Chat → Scenario Router → RAG → Local LLM → SSE

Stage 6 preserves the existing Chat endpoint and database schema. The default general scenario is backward-compatible direct LLM. The explicit knowledge_qa scenario invokes the Stage 5 authorized hybrid retrieval, RRF, reranking, SQL metadata/version validation, then bounded evidence selection before calling local llama.cpp. Specialized Agent/scenario logic belongs to Stages 7–8, not Stage 6.

## Runtime contract

POST /api/v1/chat/stream accepts {"message":"...","scenario":"knowledge_qa","conversation_id":"optional-uuid"}. Unknown scenario and client-provided audience/tenant/permission claims do not grant access. The backend authorizes the route before creating a conversation exchange. Production has no development identity.

Event sequence for a grounded answer:
- message_start: request_id, message_id, conversation_id, scenario and route
- sources: authorized document_id, chunk_id, title, version, source_location (never unreviewed source_uri)
- delta: zero or more chunks of model text
- message_end: completed, response_type=rag_generated

Missing authorized evidence gives a deterministic Persian explanation, delta followed by message_end(response_type=insufficient_evidence), without invented citations or a model call. Retrieval or LLM failure produces error then message_end(status=failed). Pre-existing cancelled/disconnect cleanup and conversation ownership remain active. Direct LLM remains the default path and emits response_type=direct_generated.

IMPORTANT: rag_generated indicates the answer used authorized sources; it is NOT a certification that every sentence was semantically entailed or reviewed by an expert. Citations identify retrieved chunks, not proven sentence-level attribution. Prompt injection is constrained by evidence being a lower-trust user-role message, explicit delimiters and immutable server-side identity controls; the LLM cannot guarantee perfect semantic obedience.

Config defaults: rag.context_token_budget=512; rag.max_sources=3; llm.history_token_budget=256. Token budgeting is conservative based on UTF-8 bytes. Large chunks use a query-aware excerpt anchored near query terms; the original retrieved chunk and its metadata remain unmodified. This is NOT the unsafe fixed 120-character prefix used in the rejected Stage 5 experiment. The default retrieval reranking candidate count remains unchanged.

No new database models, migrations, external dependencies, cloud LLM or HTTP endpoints were added.

## Test coverage

The CI workflow runs Python compileall, the complete pytest suite, Alembic history and disposable PostgreSQL/Qdrant checks. New tests/test_stage6_unit.py and tests/test_stage6_api.py exercise route decisions, evidence, tail text, provenance, SSE order, real SQLite conversation persistence, error/cancellation regressions, spoofed audience, permissions, and direct LLM backward compatibility. Previous Stage 4/5 tests cover actual SQL ownership, Qdrant hybrid retrieval and version/tenant visibility.

Passing mock-based tests does NOT verify production SSO, Persian answer faithfulness, CPU performance or simultaneous loading of all three local models. These require separate Windows/local hardware acceptance.

## Windows PowerShell: isolated synthetic E2E

Do not delete or reset any Docker volumes, modify the existing Stage 5 benchmark project, publish internal documents or overwrite existing benchmark reports. Adapt the root path to your machine. This new Compose project creates its own new PostgreSQL/Qdrant volumes and separate storage.

~~~powershell
$Repo = "D:\chatbot-service-llm"
if (-not (Test-Path $Repo)) {
    git clone https://github.com/Amirmahdimtz/chatbot-service-llm.git $Repo
    if ($LASTEXITCODE -ne 0) { throw "Clone failed" }
}
Set-Location $Repo
git status --short
if (git status --porcelain) { throw "Review existing local modifications before pulling" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "Pull failed" }
$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    py -3.11 -m venv .venv
    $Python = ".\.venv\Scripts\python.exe"
    & $Python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependencies failed" }
}
& $Python -m compileall -q src tests
if ($LASTEXITCODE -ne 0) { throw "Compile failed" }
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

if (-not (Test-Path ".env")) { & .\scripts\initialize-development-env.ps1 }
if (-not (Test-Path ".env")) { throw "Missing .env" }
$env:CHATBOT_APP_PORT = "18020"
$env:POSTGRES_HOST_PORT = "15443"
$env:QDRANT_HOST_PORT = "16344"
$env:CHATBOT_STORAGE_HOST_PATH = "D:\chatbot-stage6-validation-storage"
New-Item -ItemType Directory -Force -Path $env:CHATBOT_STORAGE_HOST_PATH | Out-Null
docker compose --project-name stage6-validation config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose config failed" }
docker compose --project-name stage6-validation up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw "Compose start failed" }
docker compose --project-name stage6-validation exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw "Existing migrations failed" }
docker compose --project-name stage6-validation ps
curl.exe --fail --silent --show-error http://127.0.0.1:8080/health
curl.exe --fail --silent --show-error http://127.0.0.1:8081/health
curl.exe --fail --silent --show-error http://127.0.0.1:8082/health
~~~

Local Windows CPU-only llama.cpp servers must already be running on ports 8080 (generation), 8081 (embedding), 8082 (reranking), using commands/models verified in Stages 3/5. Generation starting settings remain threads=4, ctx-size=2048, parallel=1, n-gpu-layers=0. On 16GB RAM, running all three models simultaneously may fail: record memory/health, do not claim E2E passed if a service is unavailable. No production auth or fake internal SSO is created.

In the same PowerShell session, load the private development token without printing it, seed three public synthetic documents using the existing Stage 5 fixture, then stream both paths:

~~~powershell
$TokenLine = @(Get-Content ".env" | Where-Object { $_ -match '^CHATBOT_DEV_API_TOKEN=' })
if ($TokenLine.Count -ne 1) { throw "Development token missing" }
$env:CHATBOT_DEV_API_TOKEN = $TokenLine[0].Substring("CHATBOT_DEV_API_TOKEN=".Length)
$ReportPath = "benchmarks/results/stage6-$(Get-Date -Format yyyyMMddHHmmss).json"
& $Python -m src.infrastructure.scripts.benchmark_stage5_fa --base-url http://127.0.0.1:18020 --mode smoke --output $ReportPath --confirm-write
if ($LASTEXITCODE -ne 0) { throw "Synthetic ingestion/retrieval failed" }
& .\scripts\test-chat-stream.ps1 -ApiUrl http://127.0.0.1:18020/api/v1/chat/stream -Scenario general
$Fixture = Get-Content "benchmarks/stage5_fa_fixture.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$Question = [string]$Fixture.documents[2].questions[0]
& .\scripts\test-chat-stream.ps1 -ApiUrl http://127.0.0.1:18020/api/v1/chat/stream -Scenario knowledge_qa -Question $Question
docker compose --project-name stage6-validation logs --tail 60 app
~~~

Review real SSE metadata for sources: IDs and version must correspond to authorized Stage 5 public synthetic documents. The documented chat script requests a generic Persian question; retrieval may return an unrelated candidate. For answer-faithfulness evaluation, use each reference question in the benchmark fixture and manually compare generated text to the correct stored source. Do not infer semantic insufficiency from an arbitrary unknown query: embedding retrieval can return unrelated hits. For deterministic insufficient_evidence, use the unit/API test fixture.

Run the negative authorization tests in pytest. Production internal authentication is deliberately fail-closed until the organization's trusted identity provider is integrated.

Send back: sanitized compile/pytest summary, Compose ps and app logs, three health statuses, SSE event names and response_type, citation document/chunk/version metadata, plus synthetic benchmark metrics. Do not share .env, passwords, tokens, or raw real-world documents.
