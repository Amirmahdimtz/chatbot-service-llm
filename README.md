# chatbot-service-llm

Stage 2: local infrastructure for FastAPI, PostgreSQL, Qdrant, persistent
application storage, and a configurable connection to Windows-hosted llama.cpp.
The HTTP API remains stage 1's `GET /api/v1/health` (process liveness only).
Stage 2 deliberately does **not** add chat, RAG, collections, product tables, or
new migrations.

The project uses constructor `@inject`, feature-folder controller discovery,
SQLAlchemy Async with a single engine and per-operation sessions, and Alembic.

Read [the complete stage 2 runbook](docs/stage-2-infrastructure.md) before
running containers. It documents safe Windows PowerShell setup, environment
variables, Windows Firewall/LLM access, non-destructive persistence checks,
and log collection. Do not commit `.env`, passwords, user data or model files.

Key commands (after reviewing the runbook; the initializer creates missing credentials without replacing existing non-empty values):

```powershell
.\scripts\initialize-development-env.ps1
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
follow the runbook's Package Index network diagnostics before changing
requirements.

Python unit/API tests use `requirements-dev.txt` and `python -m pytest -q`.
GitHub Actions tests Python 3.11/3.12 and runs container infrastructure checks.
Actual Windows host bridge networking, local llama.cpp, and persistence after
restart still require local confirmation.
