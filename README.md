# chatbot-service-llm

Stage 5 implements real ingestion of seven document formats, scoped Qdrant hybrid retrieval and local reranking. See the [Stage 5 ingestion runbook](docs/stage-5-ingestion-retrieval.md) and the [reproducible Persian retrieval benchmark](docs/stage-5-benchmark-fa.md). Actual Persian quality and CPU performance must be measured on Windows before final Stage 5 acceptance.

Stage 4 introduces persistent PostgreSQL conversations and message history, with
ownership/audience filtering, authenticated Feedback, and document metadata
registration. Stage 3 SSE streaming is now persisted; a partial response is
never marked completed. Document metadata is **registered**, not uploaded,
extracted, or indexed; the ingestion pipeline is Stage 5.

See [Stage 4 persistence runbook](docs/stage-4-persistence.md) for the
API contracts, Alembic revision, CI/integration verification, and Windows
PowerShell commands. Production remains fail-closed without trusted identity.

The local SSE PowerShell smoke test stores its synthetic Persian prompt as
ASCII JSON Unicode escapes for compatibility with Windows PowerShell 5.1.

The initial Qwen3-1.7B model uses non-thinking chat settings; recent native
llama.cpp builds should be launched with `--reasoning off` to avoid consuming
the small 256-token budget before any final answer. Windows live confirmation
remains outstanding.

See [Stage 3 Chat SSE runbook](docs/stage-3-chat-streaming.md) for the API contract,
PowerShell 5.1 streaming smoke script, sanitized llama.cpp readiness diagnostics,
credential setup and remaining Windows acceptance checks.
See [Stage 2 infrastructure runbook](docs/stage-2-infrastructure.md) for Compose,
PostgreSQL, Qdrant, storage and native llama.cpp prerequisites.

The project uses constructor `@inject`, feature-folder controller discovery,
SQLAlchemy Async with a single engine and per-operation sessions, and Alembic.

Read [the complete stage 2 runbook](docs/stage-2-infrastructure.md) before
running containers. It documents safe Windows PowerShell setup, environment
variables, Windows Firewall/LLM access, non-destructive persistence checks,
and log collection. Do not commit `.env`, passwords, user data or model files.

Key commands (after reviewing the runbook; the initializer creates missing credentials without replacing existing non-empty values):

```powershell
.\scripts\initialize-development-env.ps1
# Use Runflare for the Docker build in this PowerShell session (existing .env is kept):
$env:CHATBOT_PIP_INDEX_URL = "https://mirror-pypi.runflare.com/simple/"
docker compose config --quiet
docker compose up -d --build --wait
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure
# Run llama.cpp on Windows host, then explicitly verify the optional model:
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure --llm
docker compose down
```

The `postgres_data` and `qdrant_data` named volumes persist across ordinary
restarts/down operations; document storage is a configurable bind mount. On
Windows, check Docker Desktop's disk image location before downloading images
because named-volume data may consume C: space.

On Windows, inspect host port ownership before `docker compose up`. If another
project already uses ports 8000, 6333, or 5432, set separate
`CHATBOT_APP_PORT`, `QDRANT_HOST_PORT`, and `POSTGRES_HOST_PORT`
values in your private `.env`; do not stop unrelated containers.
If pip inside Docker Build reports `(from versions: none)` for FastAPI,
select Runflare via `CHATBOT_PIP_INDEX_URL` and test package resolution from a
container before changing requirements. Official PyPI remains the default
when no override is supplied, including CI; TLS verification remains enabled.

Python unit/API tests use `requirements-dev.txt` and `python -m pytest -q`.
GitHub Actions tests Python 3.11/3.12 and runs container infrastructure checks.
Actual Windows host bridge networking, local llama.cpp, and persistence after
restart still require local confirmation.
