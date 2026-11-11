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
server; override `llm.model_name` if a router requires it. The initial
Qwen3-1.7B model has **thinking enabled by default**. With only 256 output
tokens, the model may exhaust its budget on `reasoning_content`, which is
intentionally never exposed as an SSE `delta`, returning
`LLM_EMPTY_RESPONSE` after a long generation. The provider now passes
`chat_template_kwargs: {"enable_thinking": false}` when
`llm.enable_thinking: false` (the Stage 3 default); the parameter is
validated as a strict boolean and is configurable for future models.
Recent llama.cpp builds may ignore or deprecate this per-request kwarg, so
**also start the native Qwen3 server with `--reasoning off`** after checking
your installed executable's help. Qwen documentation identifies non-thinking
as the appropriate setting for short direct answers; see
[Qwen3 model card](https://huggingface.co/Qwen/Qwen3-1.7B)
and [llama.cpp server arguments](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

The local CPU baseline has been measured in Windows logs at roughly
5 generated tokens/second with 256 tokens exhausted and no answer text.
This is not evidence of successful Persian answer quality or time-to-first
visible token; those require a new live test after disabling reasoning.

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

## Troubleshooting llama.cpp readiness from Windows

The backend's infrastructure command reports **sanitized diagnostic codes**,
rather than an opaque `RuntimeError`:

| LLM diagnostic code | Meaning / next action |
| --- | --- |
| `connection_failed` | Verify the native llama-server is running on Windows, then inspect host bridge and firewall |
| `unauthorized` | Check that the existing llama.cpp API key matches `CHATBOT_LLM_API_KEY` in the private .env; never share it |
| `model_loading` | The runtime reports HTTP 503; check its own console for model load progress or failure |
| `no_model_loaded` | The models endpoint answered but returned an empty list |
| `models_endpoint_error`, `health_error` | HTTP endpoint not ready/compatible; check llama.cpp version and actual native-server logs |
| `timeout`, `network_error` | Inspect networking, firewall and runtime responsiveness |
| `invalid_models_response` | Models endpoint returned an unexpected JSON shape |
| `not_configured` | LLM base URL is missing in application configuration |

Do not assume the native runtime is still running after restarting Windows.
First check whether anything listens on port 8080:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Use the **existing, verified** llama-server executable, model GGUF file and
secure settings from [Stage 2](stage-2-infrastructure.md). Start it in a
separate PowerShell window if not running. Avoid changing firewall rules
without checking the Docker bridge address; keep the API key enabled and never
expose this service to the public internet.

Once native llama.cpp is running, check host-side readiness **without printing
the API key**. The model count below must be nonzero; share only the status/count:

```powershell
$LlmKeyLine = Get-Content -LiteralPath ".env" |
    Where-Object { $_ -match '^CHATBOT_LLM_API_KEY=' } | Select-Object -First 1
if (-not $LlmKeyLine) { throw "Missing local LLM API key entry" }
$LlmKey = $LlmKeyLine.Substring("CHATBOT_LLM_API_KEY=".Length)
$Headers = @{ Authorization = "Bearer $LlmKey" }
try {
    $Health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8080/health" -Headers $Headers -TimeoutSec 10 -ErrorAction Stop
    Write-Host ("Host LLM /health: {0}" -f [int]$Health.StatusCode)
    $Models = Invoke-RestMethod -Uri "http://127.0.0.1:8080/v1/models" -Headers $Headers -TimeoutSec 10 -ErrorAction Stop
    $Count = if ($null -ne $Models.data) { @($Models.data).Count } else { 0 }
    Write-Host ("Host LLM model count: {0}" -f $Count)
}
catch {
    if ($null -ne $_.Exception.Response) {
        Write-Host ("Host LLM HTTP status: {0}" -f [int]$_.Exception.Response.StatusCode)
    }
    else {
        Write-Host ("Host LLM probe failed: {0}" -f $_.Exception.GetType().Name)
    }
}
finally {
    Remove-Variable LlmKey, LlmKeyLine, Headers -ErrorAction SilentlyContinue
}
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure --llm
```

If Windows host requests pass but the Docker check reports
`connection_failed`, investigate `host.docker.internal:8080` reachability
and the Windows firewall policy for the Docker Desktop bridge. If the
check reports `unauthorized`, validate the key used by llama-server and the
existing private Compose environment; do not commit or display credentials.

## Qwen3: fix empty text after exhausting the 256-token budget

If the native runtime is healthy but real SSE waits roughly 55–80 seconds and
ends with `LLM_EMPTY_RESPONSE`, inspect the local server timing output:
`n_gen = 256` with no `delta.content` is consistent with Qwen3 consuming the
entire output budget in thinking mode. It is **not** a network failure and
increasing the token budget is not an appropriate default for 16GB CPU-only
development.

After pulling this change, restart the **existing** Windows-hosted
`llama-server.exe` in its own PowerShell console (stop the running instance
with Ctrl+C, not by killing Docker). First confirm native support:

```powershell
$LlamaExecutable = (Get-Command llama-server.exe -ErrorAction Stop).Source
& $LlamaExecutable --help 2>&1 | Select-String -- "--reasoning"
```

For a recent executable supporting `--reasoning off`, start it with the
same GGUF, existing secret and conservative CPU flags. This example assumes
the confirmed file path from the previous local test and reads the key from
the existing private `.env` without printing it:

```powershell
Set-Location "D:\chatbot-service-llm"
$LlamaExecutable = (Get-Command llama-server.exe -ErrorAction Stop).Source
$ModelPath = "D:\models\Qwen3-1.7B-Q4_K_M.gguf"
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw "GGUF file is missing at the configured path."
}
$KeyLine = Get-Content -LiteralPath ".env" |
    Where-Object { $_ -match '^CHATBOT_LLM_API_KEY=' } | Select-Object -First 1
if (-not $KeyLine) { throw "Missing LLM key entry in .env." }
$env:LLAMA_API_KEY = $KeyLine.Substring("CHATBOT_LLM_API_KEY=".Length)
if (-not $env:LLAMA_API_KEY) { throw "Configured LLM key is empty." }

& $LlamaExecutable -m $ModelPath --host 0.0.0.0 --port 8080 `
    --threads 4 --ctx-size 2048 --parallel 1 --n-gpu-layers 0 `
    --reasoning off
```

Only use `--host 0.0.0.0` on a secured, trusted development network with
proper firewall restrictions. If `--reasoning` is unsupported, do not invent
replacement flags or modify the model file: send the redacted
`llama-server.exe --version` and relevant `--help` output so a version-specific
solution can be validated. The application-side per-request kwarg is still
sent, but it is not a guarantee for every llama.cpp version.

In a second PowerShell window:

```powershell
docker compose up -d --build --wait
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure --llm
.\scripts\test-chat-stream.ps1
.\scripts\test-chat-stream.ps1 -CancelAfterFirstDelta
```

A successful stream must contain actual answer `delta` events, **not**
`reasoning_content` or a raw `<think>` block. The cancellation test is
only meaningful after a delta has actually arrived. If the server still
returns no text, provide the sanitized SSE event codes and timing summary,
not raw prompts, thought content or credentials.

## Real, incrementally read Persian SSE on Windows

Windows PowerShell 5.1 does **not always load `System.Net.Http` by default**.
The repository now contains a self-contained, fail-fast PowerShell smoke test
that explicitly loads it with `Add-Type -AssemblyName System.Net.Http`,
reads the development token from your local `.env`, checks HTTP status and
prints each SSE event with elapsed time:

```powershell
.\scripts\test-chat-stream.ps1
```

Use the following to cancel immediately after the first received delta
and close the upstream HTTP stream:

```powershell
.\scripts\test-chat-stream.ps1 -CancelAfterFirstDelta
```

The script only accepts loopback URLs, will not echo the API token, and
disposes HTTP resources even on failure. Expected success sequence:
`message_start`, one or more `delta` events, then `message_end`.
On a stopped/unavailable model, it prints the `error` event (for example
`LLM_UNAVAILABLE`) and exits with a descriptive failure; a Stream error
after response headers retains HTTP 200 as required by SSE.

For a controlled model-unavailable test, stop **only** the native
`llama-server.exe` in its own window using Ctrl+C (do not terminate Docker,
delete data or kill unrelated processes), rerun the smoke test, and
restart the native runtime afterwards. Re-check `--llm` and the success path.

## Why the previous CRLF test failed only on the Windows working tree

The old Python test asserted that the on-disk checkout of
`src/host/entrypoint.sh` had zero carriage returns. On Windows, a file
checked out **before** `.gitattributes` was introduced can still contain
CRLF. The actual Dockerfile already removes CRLF at build time, which
successfully started your app. The test now verifies that LF-normalization
produces a valid POSIX entrypoint. CI still deliberately converts the file
to CRLF and tests the full Docker build, startup and restart. No forced
checkout, destructive reset or volume deletion is necessary for this fix.

## Regression and sanitized evidence to share

```powershell
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure --llm
docker compose ps
docker compose logs --tail 60 app
git log -1 --oneline
```

Share the resulting commit SHA, pytest summary, sanitized output from the
real SSE smoke-test output (including relative timestamps and Event ordering), HTTP
status/content-type, model-unavailable response, cancellation observation,
and infrastructure check summary. Redact prompt content if not synthetic,
credentials, `.env`, Authorization headers, host-specific URLs and any
sensitive model logs. Do not post full `docker compose config` output.
