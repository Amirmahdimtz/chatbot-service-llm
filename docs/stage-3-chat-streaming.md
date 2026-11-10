# Stage 3: Local chat streaming contract and Windows validation

This stage extends the existing FastAPI service. It does **not** add database tables,
migrations, conversation CRUD endpoints, RAG citations, or tool execution. Use only
synthetic text. Stage 2 volumes, ports, credentials and working llama.cpp setup remain intact.

## API and security contract

`POST /api/v1/chat/stream` accepts JSON:

```json
{"message":"سلام، خودت را معرفی کن.","conversation_id":null}
```

`message` is required, whitespace-trimmed, 1–1000 characters. A provided
`conversation_id` must be UUID-shaped; non-null valid IDs receive HTTP 409
because no persistence/ownership contract exists until stage 4. No message history
is kept in a global dictionary. Retries are independent; no replay/idempotency
guarantee or resumable stream is provided. An `audience`, `user_id`, role, or
unknown body field is invalid (HTTP 422).

All Chat calls need `Authorization: Bearer <CHATBOT_DEV_API_TOKEN>`. The demo
credential is generated locally in `.env`, passed only to the app container
through Compose, compared with `hmac.compare_digest`, and grants a **synthetic
public principal only** when `ENV_TYPE=development` and
`auth.dev_enabled=true`. Client `X-Audience`/`X-User-ID` headers are
rejected, not treated as authorization. Production always rejects with HTTP 401
until trusted Identity Provider integration exists. Do not expose port 18000
beyond loopback. Do not share `.env` or token-bearing requests.

On authentication failure HTTP 401, unsupported continuation HTTP 409, or
validation HTTP 422, the server responds with JSON:
`{"error":{"code":"...","message":"...","request_id":"..."}}`.
For successful authorized requests, HTTP 200 uses `text/event-stream` UTF-8.
Every event is separated by a blank line and includes `event:` and JSON `data:`.
A typical complete stream is:

```text
event: message_start
data: {"request_id":"...","message_id":"...","conversation_id":null,"role":"assistant"}

event: delta
data: {"text":"سلام"}

event: message_end
data: {"request_id":"...","message_id":"...","status":"completed"}

```

An upstream error after headers results in `error` (safe code and message)
and exactly one `message_end(status=failed)`. No fake `sources` or tool events
are emitted. `request_id` also appears in `X-Request-ID`.
Disconnect/cancellation closes the upstream HTTP stream; the client is not
promised an end event after disconnect. Maximum output is limited to 8192
characters / 256 model tokens, request concurrency is 1 per app process,
and the model total timeout is 120 seconds by default. A busy request is
signaled as `LLM_BUSY` **inside the SSE stream** (HTTP status remains 200).

The provider sends an async streaming request to the installed llama.cpp
`POST /v1/chat/completions`. Model name is omitted for the single-model
server; override `llm.model_name` if a router requires it. Chat templates and
the Qwen3 reasoning mode require verification against the actual local build;
this stage does not assert a measured Persian quality/TTFT or model speed.

## Get the committed code without overwriting local changes

Run from a PowerShell window, or clone if the directory does not yet exist:

```powershell
if (-not (Test-Path "D:\chatbot-service-llm\.git")) {
    git clone https://github.com/Amirmahdimtz/chatbot-service-llm.git D:\chatbot-service-llm
    if ($LASTEXITCODE -ne 0) { throw "Clone failed" }
}
Set-Location D:\chatbot-service-llm
git status --short
# If git status shows any changes, stop and review them before pulling.
if (git status --porcelain) { throw "Working tree not clean; review local changes before pull" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "Pull failed" }
git log -1 --oneline
```

## Safe development start

The initializer preserves all existing non-empty credentials and appends a new
development Chat token to older Stage 2 `.env` files. Never delete volumes or
reset the PostgreSQL password as part of Stage 3.

```powershell
.\scripts\initialize-development-env.ps1
$env:CHATBOT_PIP_INDEX_URL = "https://mirror-pypi.runflare.com/simple/"
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Invalid Compose configuration" }
docker compose up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw "Docker services not ready" }
docker compose ps
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure --llm
Invoke-RestMethod http://127.0.0.1:18000/api/v1/health
```

The existing Windows-host `llama-server.exe` must be running and reachable
from Docker at `host.docker.internal:8080`, using the model and credential
already documented in Stage 2. Keep CPU defaults `--threads 4 --ctx-size 2048
--parallel 1 --n-gpu-layers 0`, narrow firewall exposure and avoid binding
the native model server to a public interface without controls.

## Unit, API and mock HTTP integration tests (Windows PowerShell)

```powershell
$env:ENV_TYPE = "development"
if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3.12 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt --index-url https://mirror-pypi.runflare.com/simple/
if ($LASTEXITCODE -ne 0) { throw "pip failed" }
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic -c src/infrastructure/alembic/alembic.ini history
```

Tests use synthetic mock responses. Passing them does not prove llama.cpp
generation in Windows.

## Real, incrementally read Persian SSE on Windows

This uses `.NET HttpClient` and `ResponseHeadersRead`; unlike
`Invoke-RestMethod`, it reads lines as they arrive. No token is placed in
the shell command-line arguments or printed.

```powershell
$KeyLine = Get-Content ".env" | Where-Object { $_ -match '^CHATBOT_DEV_API_TOKEN=' } | Select-Object -First 1
if (-not $KeyLine) { throw "Missing dev token; rerun env initializer" }
$Token = $KeyLine.Substring("CHATBOT_DEV_API_TOKEN=".Length)
if ($Token.Length -lt 32) { throw "Invalid development Chat token" }
$Http = [System.Net.Http.HttpClient]::new()
$Http.Timeout = [TimeSpan]::FromMinutes(3)
$Req = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, "http://127.0.0.1:18000/api/v1/chat/stream")
$Req.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
$Body = '{"message":"سلام، لطفاً در دو جمله به فارسی پاسخ بده."}'
$Req.Content = [System.Net.Http.StringContent]::new($Body, [System.Text.Encoding]::UTF8, "application/json")
$Resp = $Http.SendAsync($Req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
Write-Host ("HTTP status: " + [int]$Resp.StatusCode)
Write-Host ("Content-Type: " + $Resp.Content.Headers.ContentType)
$Reader = [System.IO.StreamReader]::new($Resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult(), [System.Text.Encoding]::UTF8)
$Clock = [System.Diagnostics.Stopwatch]::StartNew()
try {
    while (($Line = $Reader.ReadLine()) -ne $null) {
        if ($Line.StartsWith("event: ") -or $Line.StartsWith("data: ")) {
            Write-Host ("{0:N2}s {1}" -f $Clock.Elapsed.TotalSeconds, $Line)
        }
    }
}
finally {
    $Reader.Dispose(); $Resp.Dispose(); $Req.Dispose(); $Http.Dispose()
    Remove-Variable Token, KeyLine -ErrorAction SilentlyContinue
}
```

Ensure you receive actual `delta` chunks before `message_end`. For
cancellation, repeat the request but exit the read loop immediately after the
first `delta` and dispose `$Resp` in `finally`; then check app/model
logs for absence of a continuing generation. For model-unavailable behavior,
stop the native `llama-server.exe` with Ctrl+C in **its own** PowerShell
window (do not stop Docker, delete data or kill unrelated processes), rerun
the streaming check and confirm `LLM_UNAVAILABLE`. Restart llama.cpp and
rerun the success path. There is no automated network outage simulation in
production; tests already cover mock timeouts, parser and cancellation.

## Regression and sanitized evidence to share

```powershell
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure --llm
docker compose ps
docker compose logs --tail 60 app
git log -1 --oneline
```

Share the resulting commit SHA, pytest summary, sanitized output from the
real SSE read (including relative timestamps and Event ordering), HTTP
status/content-type, model-unavailable response, cancellation observation,
and infrastructure check summary. Redact prompt content if not synthetic,
credentials, `.env`, Authorization headers, host-specific URLs and any
sensitive model logs. Do not post full `docker compose config` output.
