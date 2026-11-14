# Stage 5 — Reproducible Persian retrieval benchmark

This is **Stage 5 only**: real public synthetic-document ingestion, dense + sparse Qdrant retrieval, RRF, local reranking and document-level retrieval/citation measurements. It does not evaluate answer generation or implement Stage 6.

## What is measured

`benchmarks/stage5_fa_fixture.json` contains **10 fictional UTF-8 Persian TXT documents and 20 unique questions** (two per document), spanning religious QA, three HR topics, research, personal development and task assignment. Every question has exactly one known relevant document. The CLI uses the **existing** `/api/v1/knowledge/` registration, `/{id}/upload`, and `/search` endpoints. No fakes are involved in a local benchmark; the automated Python tests use an in-process HTTP mock to verify the harness itself.

- **Recall@5 / HitRate@5:** fraction of questions whose expected document ID appears among the five returned hits. With exactly one relevant document per question, these are equal; this is *not* a multi-relevant-document Recall measurement.
- **MRR@5:** mean reciprocal **unique document** rank, deduplicating repeated chunks in the returned order; a missing target contributes zero.
- **Latency:** end-to-end search HTTP wall-clock time, in milliseconds. Reported as mean, median, p95 (nearest-rank), max and per-query samples. Ingestion time and model-startup time are excluded. It does not distinguish embedding, Qdrant and reranking latencies.
- **Citation structure:** validates UUID-shaped document/chunk IDs, version, text, source-location map and finite scores. For documents inserted by this benchmark it additionally compares version, title and TXT location. `citation_issues_at_5` counts failures per hit. **This does not prove that a generated answer is correctly cited**, nor verify every chunk against a separate index transaction; non-benchmark hits are identified as external.
- **Corpus contamination:** `preexisting_non_run_documents`, `shared_corpus_warning`, and `external_hits_at_5` expose other owned documents and non-benchmark hits. They can distort retrieval scores. A fresh isolated stack is recommended for comparative quality claims.

Reported scores are **measurements, not acceptance thresholds**. There is deliberately no fabricated pass threshold. Persian semantic quality needs manual error analysis of low-ranked/missed questions and repeated runs before setting a target. The benchmark does not evaluate production organizational identity or authorization; those remain covered by separate security tests.

## Safety and repeatability

The CLI only accepts `http://localhost:<port>` or `http://127.0.0.1:<port>` and requires `--confirm-write` and a development Bearer token read from `CHATBOT_DEV_API_TOKEN` (never from command-line arguments). No external network service is contacted by the harness. It creates **public, unpublished, synthetic** metadata and documents, never any internal document. It never deletes, publishes, replaces or deactivates existing content. Existing development data is not modified.

Each run uses a unique ASCII `--run-id`; the ID is appended to fixture text to avoid checksum collisions. Use the **same run ID and unchanged fixture** to resume: existing approved documents are reused, incomplete registration is uploaded, and a failed ingestion with a pending original is retried. If the API is in an unsafe state (such as `processing`), the benchmark aborts instead of changing it. Writes are persistent and are **not** automatically cleaned up; do not use production data or an organizational credential. For an apples-to-apples evaluation, use a new isolated Docker Compose project rather than deleting or resetting existing data. Output files are written exclusively as new files; rerun with another output filename.

`smoke` (the default) uses 3 documents and 6 questions. `full` uses all 10 documents and 20 questions. On an i7-6700 CPU, real full reranking across many candidates may be expensive. The CLI reports progress after each upload and query and has a configurable per-request timeout; no SLA is claimed. Never run multiple benchmark invocations concurrently against the same run ID.

## Windows PowerShell — existing environment, exploratory run

These commands assume the current checkout is `D:\chatbot-service-llm`, the application is healthy on loopback port `18000`, the local embedding llama-server listens on `8081`, and the reranker llama-server listens on `8082`. Adapt the path and app port to your actual `.env`. Leave model terminals open. No need to start the generative `8080` server for this benchmark.

```powershell
$Repo = "D:\chatbot-service-llm"
Set-Location $Repo
if (git status --porcelain) { throw "Review local modifications before pull" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "Pull failed" }
$Python = ".\.venv\Scripts\python.exe"
$Mirror = "https://mirror-pypi.runflare.com/simple/"
& $Python -m pip install --index-url $Mirror -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed" }
& $Python -m pytest -q tests/test_stage5_benchmark.py
if ($LASTEXITCODE -ne 0) { throw "Benchmark unit tests failed" }
docker compose ps
curl.exe --fail --silent --show-error http://127.0.0.1:8081/health
curl.exe --fail --silent --show-error http://127.0.0.1:8082/health
```

The following reads a token from the **local** private `.env` without printing it or passing it as a CLI argument. Do not paste the token or the raw `.env` into chat.

```powershell
$TokenLine = Get-Content ".env" | Where-Object { $_ -match '^CHATBOT_DEV_API_TOKEN=' } | Select-Object -Last 1
if (-not $TokenLine) { throw "Missing development token" }
$env:CHATBOT_DEV_API_TOKEN = ($TokenLine -split '=', 2)[1].Trim().Trim('"', "'")
if ($env:CHATBOT_DEV_API_TOKEN.Length -lt 32) { throw "Invalid development token" }
$RunId = "fa$(Get-Date -Format yyyyMMddHHmmss)"
try {
    & $Python -m src.infrastructure.scripts.benchmark_stage5_fa `
        --base-url http://127.0.0.1:18000 `
        --mode smoke --run-id $RunId `
        --output "benchmarks/results/$RunId-smoke.json" --confirm-write
    if ($LASTEXITCODE -ne 0) { throw "Smoke benchmark failed; note run ID for resume" }
} finally {
    Remove-Item Env:CHATBOT_DEV_API_TOKEN -ErrorAction SilentlyContinue
}
```

After successful smoke, optionally run full using a **new** run ID and output name with `--mode full`. If both runs are performed in the same shared database, results are explicitly marked contaminated. To resume an interrupted run, use the original `--run-id` with a **new** `--output` filename. The generated JSON report is under `benchmarks/results/`, excluded from git. It contains only synthetic questions and document IDs; inspect before sharing anyway.

## Recommended isolated full run (non-destructive)

Create a distinct Compose project with fresh *new* PostgreSQL/Qdrant named volumes and a dedicated storage directory; do not delete or reuse existing volumes. The same local llama.cpp model servers on `8081`/`8082` can serve both, but avoid running simultaneous benchmarks.

```powershell
Set-Location "D:\chatbot-service-llm"
$env:CHATBOT_APP_PORT = "18010"
$env:POSTGRES_HOST_PORT = "15442"
$env:QDRANT_HOST_PORT = "16343"
$env:CHATBOT_STORAGE_HOST_PATH = "D:\chatbot-stage5-fa-storage"
$env:CHATBOT_PIP_INDEX_URL = "https://mirror-pypi.runflare.com/simple/"
New-Item -ItemType Directory -Force -Path $env:CHATBOT_STORAGE_HOST_PATH | Out-Null
docker compose --project-name stage5-fa-benchmark config --quiet
if ($LASTEXITCODE -ne 0) { throw "Invalid isolated Compose config" }
docker compose --project-name stage5-fa-benchmark up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw "Isolated stack unavailable" }
docker compose --project-name stage5-fa-benchmark exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw "Migration failed" }
docker compose --project-name stage5-fa-benchmark ps
```

Once health and migrations are verified, run the CLI above with `--base-url http://127.0.0.1:18010 --mode full` and a new run ID/output filename. `preexisting_owned_documents` should be zero on a fresh stack. If you need to stop only this stack, use `docker compose --project-name stage5-fa-benchmark stop` **without** `-v`. Do not remove named volumes. PowerShell environment overrides only affect the current terminal session; review them before using the regular stack again.

## Checks and interpretation

```powershell
& $Python -m compileall -q src tests
& $Python -m pytest -q
# For the stage 5 manual smoke only; this is NOT a benchmark:
docker compose exec -T app python -m src.infrastructure.scripts.check_stage5_parsers
```

Inspect the JSON report's `metrics`, per-question `relevant_rank` and `latency_ms`, and `shared_corpus_warning`. The scripted unit tests pass without real models; actual 10-document Persian retrieval, resource usage and quality **must be verified locally**. A successful CLI exit means the measurements finished and a JSON report was written; it does not mean recall or latency met a production SLA.

**Evidence to share:** sanitized console output (run ID, `metrics` and any error), and optionally the JSON report. Never share `.env`, API tokens, passwords or private documents. No schema changes or Alembic revision are needed for this benchmark.
