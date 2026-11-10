# Stage 2 infrastructure runbook

This runbook describes **local development with synthetic data only**, not a hardened
production deployment. The architecture and implementation guides are tracked at the repository root.

## Decision log (2026-11-10)

| Decision | Reason | Scope |
| --- | --- | --- |
| App, PostgreSQL 16.15, Qdrant 1.20.0 under Docker Compose | Reproducible local services with health-gated startup | Development only |
| llama.cpp on Windows host, not Compose | CPU-only hardware and independent model lifecycle | Development only |
| Named volumes for PostgreSQL and Qdrant | Avoid unsafe Qdrant/DB bind mounts on Windows filesystems | Development only |
| Configurable bind mount for document storage | Visible application files on D: without mixing DB/vector data | Development only |
| Loopback-only published ports and no public diagnostics endpoint | Reduce exposure of unauthenticated local services | Development only |
| Qdrant collection creation deferred | Embedding runtime output/dimension unverified | Stage 5 |
| API liveness remains separate from dependency checks | Avoid reporting LLM/DB readiness when only HTTP works | Stage 2 |
| Explicit environment-only passwords/API key | Avoid committing secrets and failing open in non-development config | Stage 2 |

The implementation guide's Decision Log and Version History are synchronized in version 1.0.1. No approved product-level decision is changed by this development runbook.

## Prerequisites

Windows 11, Docker Desktop with working Linux engine and Compose, Python 3.12,
Git and enough free disk space. Run `docker version`, `docker info`,
`docker compose version`, `wsl --status`, and inspect Docker Desktop's
**Settings > Resources > Advanced > Disk image location**. Move the disk image
only via Docker Desktop's supported UI workflow after backing up important data;
do not copy/delete WSL/Docker data manually. Named volumes use the Docker engine's
disk image, which may otherwise reside on C:.

The project path can be `D:\\chatbot-service-llm`. Persistent document storage
defaults to `./storage` relative to Compose; customize
`CHATBOT_STORAGE_HOST_PATH` in `.env` if needed.

## Safe initial setup (PowerShell)

From the repository root, review `git status --short` before pulling.
Run `git pull --ff-only origin main` only if the tree is clean.
Copy `.env.example` to `.env` without overwriting an existing one, then
generate a URL-safe password, for example:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$Bytes = New-Object byte[] 32
$Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try { $Rng.GetBytes($Bytes) } finally { $Rng.Dispose() }
$Password = [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
# Review .env before replacing the empty POSTGRES_PASSWORD field.
(Get-Content .env) -replace '^POSTGRES_PASSWORD=$', "POSTGRES_PASSWORD=$Password" |
    Set-Content -Encoding ascii .env
```

Do not share the resulting password or .env file. Passwords must be URL-safe
because the development Compose configuration constructs an SQLAlchemy URL.

```powershell
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-WebRequest http://127.0.0.1:6333/readyz
docker compose exec -T postgres pg_isready -U chatbot -d chatbot
docker compose logs --tail 80 app postgres qdrant
```

A real database connection is verified by the infrastructure script, which runs
two independent SQLAlchemy async sessions and `SELECT 1`. It deliberately
does not create product tables, Qdrant collections, or migrations.

## llama.cpp on Windows host

Use an official Windows CPU build from
https://github.com/ggml-org/llama.cpp/releases and a compatible GGUF Q4_K_M
model from https://huggingface.co/ggml-org/Qwen3-1.7B-GGUF. Check the selected
binary/model version, license, and actual file path. Run `llama-server.exe --help`
and `llama-server.exe --version` before selecting flags.

Example, replacing both paths with actual ones:

```powershell
& 'D:\\llama.cpp\\llama-server.exe' -m 'D:\\models\\Qwen3-1.7B-Q4_K_M.gguf' --host 0.0.0.0 --port 8080 --threads 4 --ctx-size 2048 --parallel 1 --n-gpu-layers 0
```

**Security:** `0.0.0.0` is needed for host-to-container reachability on some
Docker Desktop configurations; it can also expose an unauthenticated LLM server
to the LAN. Use only with synthetic data on a trusted/offline development network.
Restrict the Windows Firewall to the Docker Desktop host bridge and/or set a
strong llama.cpp `--api-key` with the matching `CHATBOT_LLM_API_KEY` in `.env`.
Never use this setup as production exposure. Check the actual firewall state
before running; prefer a narrower host interface if supported.

```powershell
Invoke-WebRequest http://127.0.0.1:8080/health
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure --llm
```

The app starts normally if llama.cpp is off. The `--llm` check explicitly
returns a failure, not a fabricated model result. Qdrant uses the logical
collection names `knowledge_public` and `knowledge_internal`; collections
are not provisioned in stage 2, pending embedding validation.

## Test, persistence and shutdown

```powershell
$env:ENV_TYPE = 'development'
.\\.venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt
.\\.venv\\Scripts\\python.exe -m compileall -q src tests
.\\.venv\\Scripts\\python.exe -m pytest -q
.\\.venv\\Scripts\\python.exe -m alembic -c src/infrastructure/alembic/alembic.ini history
docker compose restart
docker compose ps
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure
docker compose down
```

`docker compose down` without `-v` retains named volumes and local document
storage. No app schema exists yet; do not autogenerate or apply empty migrations.
For incidents, collect *sanitized* `docker compose ps`, `docker compose config --services`,
`docker compose logs --tail 80`, and infrastructure check output.
Never paste `docker compose config` in full: it expands secret values.
