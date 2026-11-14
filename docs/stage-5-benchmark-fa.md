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

## Stage 5 CPU reranking A/B: same corpus, no new documents

The isolated 10-document/20-question Windows run on 2026-11-14 achieved document-level Recall@5=1.0, MRR@5=1.0, 0 citation structure issues and 0 external hits; mean search latency was **68,769.11 ms** and p95 **82,689.83 ms**. These are **user-measured baseline values** on an i7-6700 CPU, not a performance acceptance target. No separate stage timings were captured for this full run. Earlier profiling of a one-document run identified CPU reranking as the dominant cost. With 10 short documents, the default second stage can rerank 10 candidates even though only 5 final hits are returned.

A reversible **opt-in** setting, `CHATBOT_RERANK_CANDIDATES`, caps the number of **RRF-ordered, authorization-validated** candidates sent to the local reranker. Default is `20` (unchanged behavior); valid range is from `retrieval.final=5` through `retrieval.first_stage=20`. This setting does **not** change dense/sparse retrieval, RRF, access filters, Qdrant schema, chunk storage or citation text. Restricting the set **can hurt Recall@5 or MRR@5** if a relevant document was outside the RRF top 5, so it is **not** a recommended production change without measurement.

The following uses the **already created** `stage5-fa-benchmark` Compose project and **reuses** the exact run ID `fa20261114125025` (ten already approved fixture documents). It only recreates the isolated **app** container; existing PostgreSQL/Qdrant containers and named volumes are preserved. On a new PowerShell session, reapply all the same port/storage overrides. Do **not** execute `docker compose down -v`, `git reset --hard`, or any deletion command.

```powershell
Set-Location "D:\chatbot-service-llm"
if (git status --porcelain) { throw "Review local changes before pull" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "Pull failed" }
$env:CHATBOT_APP_PORT = "18010"
$env:POSTGRES_HOST_PORT = "15442"
$env:QDRANT_HOST_PORT = "16343"
$env:CHATBOT_STORAGE_HOST_PATH = "D:\chatbot-stage5-fa-storage"
$env:CHATBOT_PIP_INDEX_URL = "https://mirror-pypi.runflare.com/simple/"
$env:CHATBOT_RERANK_CANDIDATES = "5"
docker compose --project-name stage5-fa-benchmark config --quiet
if ($LASTEXITCODE -ne 0) { throw "Invalid isolated Compose configuration" }
docker compose --project-name stage5-fa-benchmark up -d --build --no-deps --force-recreate --wait app
if ($LASTEXITCODE -ne 0) { throw "Isolated app rebuild failed" }
docker compose --project-name stage5-fa-benchmark ps
```

Re-run the real benchmark with **exactly the existing run ID**, but a new report path. The script lists and **reuses** already approved documents; it does not duplicate them. It still requires the explicit synthetic-write authorization flag because this is the same safe ingestion-capable CLI:

```powershell
$Python = ".\.venv\Scripts\python.exe"
$Line = Get-Content ".env" | Where-Object { $_ -match '^CHATBOT_DEV_API_TOKEN=' } | Select-Object -Last 1
if (-not $Line) { throw "Missing development token" }
$env:CHATBOT_DEV_API_TOKEN = ($Line -split '=', 2)[1].Trim().Trim('"', "'")
try {
  & $Python -m src.infrastructure.scripts.benchmark_stage5_fa `
      --base-url http://127.0.0.1:18010 `
      --mode full --run-id fa20261114125025 `
      --output benchmarks/results/fa20261114125025-cap5.json `
      --timeout-seconds 600 --confirm-write
  if ($LASTEXITCODE -ne 0) { throw "Candidate-budget benchmark failed" }
} finally {
  Remove-Item Env:CHATBOT_DEV_API_TOKEN -ErrorAction SilentlyContinue
}
$Baseline = Get-Content benchmarks/results/fa20261114125025-full.json -Raw -Encoding UTF8 | ConvertFrom-Json
$Candidate5 = Get-Content benchmarks/results/fa20261114125025-cap5.json -Raw -Encoding UTF8 | ConvertFrom-Json
$Baseline.metrics | Format-List
$Candidate5.metrics | Format-List
```

Compare both results on the **same run and corpus**, including `recall_at_5`, `mrr_at_5`, `citation_issues_at_5`, `mean_latency_ms`, `p95_latency_ms` and `shared_corpus_warning`. If quality regresses, restore `$env:CHATBOT_RERANK_CANDIDATES = "20"` and recreate **only** the isolated app with the same `up -d --no-deps --force-recreate --wait app` command. Do not deploy the candidate cap on the main app until results are reviewed. The 10-document sample remains small and cannot justify a general production SLA.

## Stage 5 read-only candidate length probe (CPU)

The `src/infrastructure/scripts/probe_stage5_reranking.py` diagnostic runs **inside the isolated development app container**, resolves the existing authorized `KnowledgeIndexService`, and observes **the real texts after RRF and PostgreSQL access validation**, immediately before reranking. It emits only candidate character lengths, an **approximate lexical-token count** (not llama.cpp tokenizer tokens), number of candidates, HTTP-provider reranking time and the known relevant fixture document rank. It never prints source texts or queries, writes documents, changes production configuration, or deletes data. The provider method is restored in a `finally` block in the short-lived diagnostic process.

The baseline run below executes **one real retrieval** against the already indexed 10-document/20-question fixture. It does not call the shortened-input variation. First verify that local embedding (8081) and reranking (8082) are healthy and `threads-batch=4` is still active. This new script is shipped in the Docker `app` image, so rebuild **only that app** in the existing benchmark project with the original port/storage overrides and candidate cap of 5.

```powershell
Set-Location "D:\chatbot-service-llm"
if (git status --porcelain) { throw "Review local changes before pull" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "Pull failed" }
$Python = ".\.venv\Scripts\python.exe"
& $Python -m pytest -q tests/test_stage5_reranker_probe.py
if ($LASTEXITCODE -ne 0) { throw "Probe unit tests failed" }

$env:CHATBOT_APP_PORT = "18010"
$env:POSTGRES_HOST_PORT = "15442"
$env:QDRANT_HOST_PORT = "16343"
$env:CHATBOT_STORAGE_HOST_PATH = "D:\chatbot-stage5-fa-storage"
$env:CHATBOT_PIP_INDEX_URL = "https://mirror-pypi.runflare.com/simple/"
$env:CHATBOT_RERANK_CANDIDATES = "5"
docker compose --project-name stage5-fa-benchmark config --quiet
if ($LASTEXITCODE -ne 0) { throw "Invalid Compose config" }
docker compose --project-name stage5-fa-benchmark up -d --build --no-deps --force-recreate --wait app
if ($LASTEXITCODE -ne 0) { throw "Isolated app failed" }

$Report = Get-Content "benchmarks/results/fa20261114125025-cap5.json" -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Report.run_id -ne "fa20261114125025" -or $Report.query_count -ne 20 -or $Report.shared_corpus_warning) {
    throw "Unexpected fixture report; do not probe a different corpus"
}
$Case = $Report.questions[0]
$QueryB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$Case.question))
docker compose --project-name stage5-fa-benchmark exec -T app python -m src.infrastructure.scripts.probe_stage5_reranking --query-base64 $QueryB64 --expected-document-id ([string]$Case.expected_document_id)
if ($LASTEXITCODE -ne 0) { throw "Stage 5 probe failed" }
```

The `lengths` array reports each candidate independently; `total_characters` counts all five, and `baseline_rerank_ms` is the actual local model call time. No speedup is claimed from character counts alone. A later **opt-in** test with `--max-characters 120` executes baseline and prefix-only reranking against the **same authorized candidate set in one retrieval**. It does not alter the service's returned baseline results or original citation text. The `comparison` includes both time measurements and document order only when the full original candidate-to-document mapping is unambiguous (all candidates returned, distinct full texts). A short prefix may omit relevant evidence; do **not** deploy truncation based on one question or these ten synthetic documents. Compare all 20 questions and repeated runs before considering a service change. Never execute this probe with real organizational text or credentials.

## Stage 5 A/B order and tail-evidence challenge (read-only)

**Purpose:** verify (1) that the measured reranker speedup is not solely an artifact of running the original text first, and (2) that a fixed 120-character prefix can hide relevant evidence in longer fictional documents. Neither experiment changes `KnowledgeIndexService`, source text, Qdrant collections, PostgreSQL rows, citation payloads or runtime settings. This evaluation is **not** a production readiness gate or a benchmark of answer generation.

The CLI `src/infrastructure/scripts/benchmark_stage5_rerank_ab_fa.py` runs **inside the existing isolated development app container**. It supports:

- `--mode tail`: five fully synthetic documents (each longer than 500 characters) with an identical introductory prefix and distinct relevant facts **only after** the first 120 characters. Five queries target each distinct suffix. Sends the documents directly to the real local `RerankingProvider`. No SQL, Qdrant or embedding retrieval is performed in this mode. Scores are **reranker-only Top-1 and MRR@5**, not full-retrieval Recall. HitRate@5 is reported but is trivially 1.0 whenever the known target is among these five candidates, so do not interpret it as a sensitive quality metric.
- `--mode corpus`: twenty previously recorded synthetic queries with expected UUIDs; runs the **real authorized public retrieval**, captures the same five authorized candidates after RRF/SQL validation, and reranks the originals and prefixes for each query. This evaluates the effect of reranking input length on the **already retrieved** candidate set. No new ingestion, no query text or document body printed to output. Fails closed when fewer/more than five candidates are available or candidate/document mapping is ambiguous.
- `--order prefix-first` reverses the earlier `baseline-first` A/B sequence; `--order alternating` uses ten `prefix-first` and ten `baseline-first` pairs across the 20-question corpus (3/2 for five tail cases). Both modes always label the timing based on the text sent, regardless of order. The existing one-query Probe keeps `baseline-first` by default.
- JSON stdout contains `metrics` (timing, document ranks, Top-1 and MRR) and case metadata without raw text. Diagnostic progress is sent to stderr. The harness requires a valid **development-only synthetic public identity** and does not call any write endpoint.

### Exact Windows PowerShell execution (reuse existing isolated corpus)

Do **not** remove or reset existing volumes, document storage or model checkpoints. Verify reranker `--threads 4 --threads-batch 4` is active, and no other benchmark is running. Commands assume `D:\chatbot-service-llm`, the previous `fa20261114125025-cap5.json` and the existing `stage5-fa-benchmark` Compose project.

```powershell
Set-Location "D:\chatbot-service-llm"
if (git status --porcelain) { throw "Review local changes before pull" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "Git pull failed" }
$Python = ".\.venv\Scripts\python.exe"
& $Python -m pytest -q tests/test_stage5_reranker_probe.py tests/test_stage5_rerank_ab.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5 A/B tests failed" }

$env:CHATBOT_APP_PORT = "18010"
$env:POSTGRES_HOST_PORT = "15442"
$env:QDRANT_HOST_PORT = "16343"
$env:CHATBOT_STORAGE_HOST_PATH = "D:\chatbot-stage5-fa-storage"
$env:CHATBOT_PIP_INDEX_URL = "https://mirror-pypi.runflare.com/simple/"
$env:CHATBOT_RERANK_CANDIDATES = "5"
docker compose --project-name stage5-fa-benchmark config --quiet
if ($LASTEXITCODE -ne 0) { throw "Invalid isolated Compose configuration" }
docker compose --project-name stage5-fa-benchmark up -d --build --no-deps --force-recreate --wait app
if ($LASTEXITCODE -ne 0) { throw "Isolated app build failed" }
curl.exe --fail --silent --show-error http://127.0.0.1:8081/health
if ($LASTEXITCODE -ne 0) { throw "Embedding model not ready" }
curl.exe --fail --silent --show-error http://127.0.0.1:8082/health
if ($LASTEXITCODE -ne 0) { throw "Reranker not ready" }
```

Tail-only negative control (five fictional documents, *no persistent writes*):

```powershell
$TailRaw = & docker compose --project-name stage5-fa-benchmark exec -T app `
    python -m src.infrastructure.scripts.benchmark_stage5_rerank_ab_fa `
    --mode tail --order alternating --max-characters 120
if ($LASTEXITCODE -ne 0) { throw "Tail benchmark failed" }
$Tail = ($TailRaw -join "`n") | ConvertFrom-Json
$Tail | ConvertTo-Json -Depth 10 | Out-File -Encoding UTF8 -NoClobber "benchmarks/results/fa20261114125025-tail-ab.json"
$Tail.metrics | Format-List
```

Reverse-order evaluation of the **same** existing 20 questions. The payload contains **base64 encoded synthetic questions**, UUIDs and report metadata only; not API keys, source documents or credentials. PowerShell 5.1's default native-command pipeline encoding is safe because this compact JSON is ASCII-only.

```powershell
$Original = Get-Content "benchmarks/results/fa20261114125025-cap5.json" -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Original.run_id -ne "fa20261114125025" -or $Original.document_count -ne 10 -or
    $Original.query_count -ne 20 -or $Original.shared_corpus_warning) {
    throw "Unexpected isolated fixture report"
}
$Cases = @($Original.questions | ForEach-Object {
    @{
        query_base64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$_.question))
        expected_document_id = [string]$_.expected_document_id
    }
})
$Payload = @{
    run_id = [string]$Original.run_id
    document_count = [int]$Original.document_count
    query_count = [int]$Original.query_count
    shared_corpus_warning = [bool]$Original.shared_corpus_warning
    cases = $Cases
} | ConvertTo-Json -Depth 6 -Compress
$CorpusRaw = $Payload | & docker compose --project-name stage5-fa-benchmark exec -T app `
    python -m src.infrastructure.scripts.benchmark_stage5_rerank_ab_fa `
    --mode corpus --order prefix-first --max-characters 120
if ($LASTEXITCODE -ne 0) { throw "Reverse-order corpus benchmark failed" }
$Corpus = ($CorpusRaw -join "`n") | ConvertFrom-Json
$Corpus | ConvertTo-Json -Depth 10 | Out-File -Encoding UTF8 -NoClobber "benchmarks/results/fa20261114125025-reverse-ab.json"
$Corpus.metrics | Format-List
```

Prior **baseline-first** reranker-only 20-question mean timings (from Windows 2026-11-14): originals 32,344.17 ms and prefix 24,439.09 ms, MRR@5 1.0 for both and zero Top-1 changes. Compare these with the new **prefix-first** summary and the tail negative control. Since the model and CPU workload fluctuate, a speedup in one order is not definitive. A tail-case MRR drop means fixed prefix truncation is unsafe even if the short corpus quality remains perfect.

`benchmarks/results/` is git-ignored; output paths above are new. Do not overwrite existing reports. The commands print progression to stderr; avoid concurrent model requests and do not run with actual organizational data. Send both **metrics** objects and per-case baseline/prefix ranks (not secrets or paths). No additional migrations/endpoints are required.

## Checks and interpretation

```powershell
& $Python -m compileall -q src tests
& $Python -m pytest -q
# For the stage 5 manual smoke only; this is NOT a benchmark:
docker compose exec -T app python -m src.infrastructure.scripts.check_stage5_parsers
```

Inspect the JSON report's `metrics`, per-question `relevant_rank` and `latency_ms`, and `shared_corpus_warning`. The scripted unit tests pass without real models; actual 10-document Persian retrieval, resource usage and quality **must be verified locally**. A successful CLI exit means the measurements finished and a JSON report was written; it does not mean recall or latency met a production SLA.

**Evidence to share:** sanitized console output (run ID, `metrics` and any error), and optionally the JSON report. Never share `.env`, API tokens, passwords or private documents. No schema changes or Alembic revision are needed for this benchmark.
