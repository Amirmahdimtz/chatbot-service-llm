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
| Optional Runflare PyPI mirror | Resolve local Docker image Python dependencies despite incomplete/time-limited reads from pypi.org | Stage 2 development only |
| LF-safe Shell entrypoint | Windows Git checkout may introduce CRLF; force LF via Git attributes and normalize before container startup | Stage 2 |

The implementation guide's Decision Log and Version History are synchronized in version 1.0.4. No approved product-level decision is changed by this development runbook.

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

## Runflare mirror for local Docker builds

Runflare documents its HTTPS Simple API at
`https://mirror-pypi.runflare.com/simple/`:
https://runflare.com/mirrors/pypi-mirror/ . This is an external, third-party
package source; choose it only for trusted development dependency installs.
Do not disable TLS certificate verification or use `--trusted-host`.

The Dockerfile defaults to official PyPI. `compose.yaml` passes the optional
`CHATBOT_PIP_INDEX_URL` to its `PIP_INDEX_URL` build argument. GitHub Actions
and systems without an override continue using official PyPI. New `.env` files
copied from `.env.example` select Runflare; existing `.env` files are not
overwritten and require an explicit opt-in.

Use the following in PowerShell to select Runflare for **this session only**,
without exposing or changing credentials:

```powershell
Set-Location "D:\chatbot-service-llm"
$env:CHATBOT_PIP_INDEX_URL = "https://mirror-pypi.runflare.com/simple/"
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Invalid Compose configuration" }

docker run --rm --entrypoint python python:3.12.16-slim-bookworm `
    -m pip --isolated --disable-pip-version-check index versions fastapi `
    --index-url https://mirror-pypi.runflare.com/simple/
if ($LASTEXITCODE -ne 0) { throw "Runflare cannot resolve FastAPI from Docker" }

docker compose up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw "Docker build/startup failed" }
docker compose ps
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure
```

To make the choice persistent, add exactly one
`CHATBOT_PIP_INDEX_URL=https://mirror-pypi.runflare.com/simple/` line to
your existing private `.env`. Do not commit `.env`, overwrite existing
credentials, or modify global pip settings. The mirror affects Docker image
dependency installation, not model execution or network access by the app.
Host-port overrides (`CHATBOT_APP_PORT`, `QDRANT_HOST_PORT`,
`POSTGRES_HOST_PORT`) remain independent; use `docker compose ps` to determine
the correct host health URL.

---
## Safe initial setup (PowerShell)

From the repository root, review `git status --short` before pulling.
Run `git pull --ff-only origin main` only if the tree is clean.
Initialize the development file with the repository script. It generates random
URL-safe values for **empty** `POSTGRES_PASSWORD` and `CHATBOT_LLM_API_KEY`
entries, handles Windows CRLF line endings, and leaves existing non-empty
values unchanged. It never prints the credentials.

```powershell
.\\scripts\\initialize-development-env.ps1
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose configuration failed; do not start services." }
```

If an existing PostgreSQL named volume already contains data, do not rotate its
previous password without checking that database's initialization history.
Never delete the volume to solve an authentication failure.

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

Use a **new PowerShell window** for the Windows-hosted server. All command
variables are initialized in that same window; do not depend on variables set
by previous sessions. The command reads the local secret without displaying it
or putting it in the command-line arguments.

```powershell
Set-Location "D:\\chatbot-service-llm"
$LlamaExecutable = (Get-Command llama-server.exe -ErrorAction Stop).Source
$ModelPath = "D:\\models\\Qwen3-1.7B-Q4_K_M.gguf"
if (-not (Test-Path -LiteralPath $LlamaExecutable -PathType Leaf)) { throw "llama-server.exe is missing" }
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) { throw "GGUF model is missing" }

$KeyLine = Get-Content -LiteralPath ".env" |
    Where-Object { $_ -match '^CHATBOT_LLM_API_KEY=' } |
    Select-Object -First 1
if (-not $KeyLine) { throw "Missing CHATBOT_LLM_API_KEY in .env" }
$env:LLAMA_API_KEY = $KeyLine.Substring("CHATBOT_LLM_API_KEY=".Length)
if (-not $env:LLAMA_API_KEY) { throw "The LLM API key is empty" }

& $LlamaExecutable -m $ModelPath --host 0.0.0.0 --port 8080 --threads 4 --ctx-size 2048 --parallel 1 --n-gpu-layers 0
```

**Security:** `0.0.0.0` is needed for host-to-container reachability on some
Docker Desktop configurations; it can also expose an unauthenticated LLM server
to the LAN. Use only with synthetic data on a trusted/offline development network.
Restrict the Windows Firewall to the Docker Desktop host bridge and/or set a
strong llama.cpp `--api-key` with the matching `CHATBOT_LLM_API_KEY` in `.env`.
Never use this setup as production exposure. Check the actual firewall state
before running; prefer a narrower host interface if supported.

```powershell
$Headers = @{ Authorization = "Bearer $env:LLAMA_API_KEY" }
Invoke-RestMethod -Uri http://127.0.0.1:8080/health -Headers $Headers
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure --llm
```

For the Qwen3-1.7B **Stage 3 chat** workflow, use the documented
[non-thinking launch override](stage-3-chat-streaming.md#qwen3-fix-empty-text-after-exhausting-the-256-token-budget)
in addition to these baseline flags. Default Qwen3 thinking may consume the
entire short response budget without emitting any final answer text.

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


## Troubleshooting: Compose variable interpolation

If Compose reports that `POSTGRES_PASSWORD` is missing, it has not
started the project services. This often happens when a CRLF `.env` file
was edited with a raw-text regex ending in `=$`; the carriage-return
prevents matching the empty value. Re-run `scripts/initialize-development-env.ps1`
and check `docker compose config --quiet` before `up`. Do not print
`docker compose config` without `--quiet`, as its output includes secrets.

A 200 response from localhost port 6333 or a 404 from 8000 **before Compose
startup** does not establish that these endpoints belong to this project.
Inspect `docker ps` and `docker compose ps`. If host ports are occupied by
unrelated applications, choose alternative `QDRANT_HOST_PORT` or
`CHATBOT_APP_PORT` values in `.env`; keep internal container ports unchanged.

## Troubleshooting: occupied local ports on Windows

Before starting this Compose project, check ownership of its default host ports:

```powershell
docker ps --format "table {{.Names}}\t{{.Ports}}"
Get-NetTCPConnection -State Listen -LocalPort 8000,6333,5432,8080 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress,LocalPort,OwningProcess
```

Do not stop, remove, or change another project's containers to make these ports
available. When defaults are occupied, edit **only the host port fields** in
the existing, untracked `.env` file, for example:

```dotenv
CHATBOT_APP_PORT=18000
QDRANT_HOST_PORT=16333
POSTGRES_HOST_PORT=15432
```

Check the alternatives are free on your host before using them. These values
change only the published host ports; container-to-container access still uses
`postgres:5432`, `qdrant:6333`, and `app:8000`. Validate with
`docker compose config --quiet`, then run the Compose startup command and
inspect `docker compose ps`. After changing ports, the host health URL becomes
`http://127.0.0.1:18000/api/v1/health`. A response from an older URL
does **not** prove that this project's service is healthy.

## Troubleshooting: pip sees no FastAPI distributions in Docker Build

If the application build fails at `pip install -r requirements.txt` with
`Could not find a version that satisfies the requirement fastapi ... (from
versions: none)`, first check Package Index reachability. The specified
FastAPI range supports Python 3.12 and was validated by CI; do not change
version constraints to work around an unverified networking failure.

Run a pip lookup in a disposable container based on the **same image** used by
the Dockerfile; it does not change this project's services or volumes:

```powershell
docker run --rm --entrypoint python python:3.12.16-slim-bookworm -m pip --disable-pip-version-check index versions fastapi
```

For further diagnostics, check DNS and HTTPS from the same image:

```powershell
docker run --rm --entrypoint python python:3.12.16-slim-bookworm -c "import socket; print(socket.getaddrinfo('pypi.org', 443)[0][4])"
docker run --rm --entrypoint python python:3.12.16-slim-bookworm -c "import urllib.request; print(urllib.request.urlopen('https://pypi.org/simple/fastapi/', timeout=20).status)"
```

These checks distinguish resolver problems, HTTPS connectivity, and pip's
configured Package Index. A successful `docker pull` alone does not prove
that `pip` within a BuildKit container can access PyPI: registry image
pulls and container/build network traffic can have different proxy paths.

If the lookup fails, inspect **Docker Desktop > Settings > Resources >
Proxies** and the Windows system proxy/VPN configuration, using the official
Docker Desktop documentation. Do not disable security controls, add
`--trusted-host`, bypass TLS verification, or use an unknown package mirror.
If the lookup succeeds but the build still fails, capture a sanitized verbose
build log:

```powershell
docker compose --progress plain build app
```

Before sharing logs, redact credentials and any private proxy or package-index
URLs. `docker compose config` without `--quiet` prints environment secrets,
so do not share it. Do not retry `docker compose exec app` until
`docker compose up -d --build --wait` actually succeeds.

## Troubleshooting: `/bin/sh` reports `set: Illegal option -`

On Windows, Git may check out `src/host/entrypoint.sh` with CRLF line endings.
The Debian `/bin/sh` used in the app container treats the trailing carriage
return after `set -eu` as an invalid option and exits with code 2.
This can cause a restart loop before the Python API process starts.

The project now includes `.gitattributes` (`*.sh text eol=lf`) and also
normalizes the entrypoint with `sed` during Docker image creation, before
switching to its unprivileged runtime user. CI exercises a deliberately
CRLF-converted entrypoint during its full Compose startup check.

After pulling the fix, rebuild the app image (do not delete volumes):

```powershell
Set-Location "D:\chatbot-service-llm"
git status --short
# If the working tree is clean:
git pull --ff-only origin main
$env:CHATBOT_PIP_INDEX_URL = "https://mirror-pypi.runflare.com/simple/"
docker compose up -d --build --wait
docker compose ps
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure
```

Check the actual host port in `docker compose ps`, especially if it was
overridden to 18000. The next stage 2 validation is the optional Windows
llama.cpp health/model check, followed by persistence testing.
