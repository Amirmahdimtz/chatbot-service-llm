# Stage 4 — PostgreSQL history, feedback and knowledge metadata

This stage creates real persistent data, not an in-memory prototype. It extends
Stage 3 but **does not** upload/parse documents, create Qdrant vectors, run RAG
or provide an external identity provider.

## API contract

All endpoints except health require `Authorization: Bearer <CHATBOT_DEV_API_TOKEN>`
in development. The credential is a locally generated synthetic **public** user
only; never use it with real data. Production remains HTTP 401 without a
trusted identity provider. `X-User-ID`, `X-Audience` and `X-Tenant-ID` are
rejected; untrusted request-body owner claims are rejected by Pydantic DTOs.

- `POST /api/v1/conversation/` with JSON `{"title":"Synthetic"}` (or
  `{"title":null}`) creates a conversation; status 201.
- `GET /api/v1/conversation/?limit=20&offset=0` returns `items` and
  `next_cursor` (a decimal offset string when more results exist). Order is
  last activity descending, then ID descending.
- `GET /api/v1/conversation/{conversation_id}?limit=50&offset=0`
  returns its metadata plus ordered messages and `message_next_cursor`.
  Role is `user` or `assistant` for stage-4-generated turns. Message status
  can be `streaming`, `completed`, `failed`, `cancelled`.
- `POST /api/v1/chat/stream` accepts `{"message":"hello"}` for a new
  conversation or `{"message":"continue","conversation_id":"<uuid>"}` to
  continue an owned conversation. The `message_start` event includes real
  persisted conversation/message UUIDs; `delta` remains UTF-8, and
  `message_end` is emitted only after a terminal DB update. The LLM context
  contains a bounded number of previous **completed** user/assistant turns.
  A failed/aborted answer may retain partial text but is never marked complete.
- `POST /api/v1/feedback/` with
  `{"message_id":"<assistant-uuid>","kind":"incorrect","comment":"Synthetic"}`
  registers one feedback per actor and **completed assistant** message (201).
  Kinds: `positive`, `negative`, `incorrect`. Duplicate: 409.
- `POST /api/v1/knowledge/` with
  `{"title":"Test","source_type":"pdf","audience":"public"}`
  creates metadata only (201, `status=registered`, `version=1`).
  Accepted types: pdf, txt, doc, docx, json, csv, xlsx. The API does not
  receive bytes and does not claim to index anything. `GET /api/v1/knowledge/`
  and `GET /api/v1/knowledge/{document_id}` are owner/audience scoped.

All list endpoints accept `limit` 1..100 and `offset` 0..1000000. Invalid
input: 422. Missing or not owned resources: 404 without IDOR disclosure.
Malformed/spoofed identity: 401/403. Storage errors: 503 with a sanitized
`error` object. Stream failures after headers use SSE `error` and
`message_end(status=failed)`.

Persistent schema: `conversations` allocates `next_sequence` under a
PostgreSQL row lock. `chat_messages` has unique `(conversation_id, sequence)`
and FK to conversations. `feedback` has unique `(message_id, actor_id)` and
FK to messages. `knowledge_documents` stores owner, audience, classification,
source type, version, processing status and future storage/Qdrant references,
which remain unset until a future ingestion workflow. Metadata indexing is
not evidence of an ingested document.

No conversation DELETE endpoint is enabled. Retention and multi-system deletion
require explicit organization policy. Alembic downgrade drops tables and
**must only be tested on an isolated disposable database**. The production
runtime never calls create_all; schema changes use committed migrations.

## Safe PowerShell setup (Windows 11)

Use the actual project path; the example assumes `D:\chatbot-service-llm`.

```powershell
if (-not (Test-Path "D:\chatbot-service-llm\.git")) {
    git clone https://github.com/Amirmahdimtz/chatbot-service-llm.git D:\chatbot-service-llm
    if ($LASTEXITCODE -ne 0) { throw "Clone failed" }
}
Set-Location "D:\chatbot-service-llm"
git status --short
if (git status --porcelain) { throw "Review local changes before pulling" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "Pull failed" }
git log -1 --oneline

.\scripts\initialize-development-env.ps1
$env:CHATBOT_PIP_INDEX_URL = "https://mirror-pypi.runflare.com/simple/"
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose config failed" }
docker compose up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw "Containers not ready" }
docker compose ps
docker compose exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed; inspect logs before retrying" }
docker compose exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini current
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure
```

Do not run `alembic downgrade` against your local persistent Docker database.
Never delete volumes, overwrite `.env` or hard-reset the local checkout.
Check published host port conflicts (configured CHATBOT_APP_PORT,
POSTGRES_HOST_PORT and QDRANT_HOST_PORT) before launching; adjust existing
private Compose settings instead of stopping unrelated services.
A container mapping such as `127.0.0.1:18000->8000/tcp` requires
`http://127.0.0.1:18000` from Windows; `8000` is the internal container
port. An HTTP 404 from port 8000 may be an unrelated local HTTP service,
not a problem in the Chat controller. `docker compose port app 8000`
reports the effective published port without printing credentials.

## Automated tests

```powershell
$env:ENV_TYPE = "development"
if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3.12 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt --index-url https://mirror-pypi.runflare.com/simple/
if ($LASTEXITCODE -ne 0) { throw "pip failed" }
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic -c src/infrastructure/alembic/alembic.ini history
```

The default tests cover SQLite-backed repository workflows and a
**disposable SQLite database** for Alembic upgrade/downgrade. Real PostgreSQL
integration requires the explicitly designated `CHATBOT_TEST_DATABASE_URL`
and `CHATBOT_TEST_DATABASE_ISOLATED=1`; CI runs this against an ephemeral
PostgreSQL instance. Do not point either at a database holding valuable data.

## API and real streaming validation

```powershell
# Resolve the published HOST port rather than the container's port 8000.
# This also works when CHATBOT_APP_PORT is changed in the private .env file.
$PublishedPort = docker compose port app 8000
if ($LASTEXITCODE -ne 0 -or -not $PublishedPort) {
    throw "Could not determine the published app port; check docker compose ps."
}
$PortText = (($PublishedPort | Select-Object -First 1) -split ':')[-1]
$HostPort = 0
if (-not [int]::TryParse($PortText, [ref]$HostPort) -or
    $HostPort -lt 1 -or $HostPort -gt 65535) {
    throw "Invalid host port returned by Docker Compose."
}
$Api = "http://127.0.0.1:$HostPort"
Write-Host ("Testing app at {0}" -f $Api)
Invoke-RestMethod -Uri "$Api/api/v1/health"
$TokenLine = Get-Content -LiteralPath ".env" |
    Where-Object { $_ -match '^CHATBOT_DEV_API_TOKEN=' } | Select-Object -First 1
if (-not $TokenLine) { throw "Missing synthetic token" }
$Token = $TokenLine.Substring("CHATBOT_DEV_API_TOKEN=".Length)
$Headers = @{ Authorization = "Bearer $Token" }
$Created = Invoke-RestMethod -Method Post -Uri "$Api/api/v1/conversation/" `
    -Headers $Headers -ContentType "application/json; charset=utf-8" -Body '{"title":"Synthetic stage 4"}'
$ConversationId = $Created.id
$Listed = Invoke-RestMethod -Uri "$Api/api/v1/conversation/?limit=5" -Headers $Headers
$Metadata = Invoke-RestMethod -Method Post -Uri "$Api/api/v1/knowledge/" `
    -Headers $Headers -ContentType "application/json" `
    -Body '{"title":"Synthetic metadata","source_type":"pdf","audience":"public"}'
$MetadataState = Invoke-RestMethod -Uri "$Api/api/v1/knowledge/$($Metadata.id)" -Headers $Headers
Write-Host ("Created conversation ID: {0}" -f $ConversationId)
Write-Host ("Knowledge status: {0}" -f $MetadataState.status)
# Always use the effective Compose host port; the container listens on 8000.
.\scripts\test-chat-stream.ps1 -ApiUrl "$Api/api/v1/chat/stream" -ConversationId $ConversationId
$History = Invoke-RestMethod -Uri "$Api/api/v1/conversation/$ConversationId" -Headers $Headers
$Reply = @($History.messages | Where-Object { $_.role -eq "assistant" -and $_.status -eq "completed" } | Select-Object -Last 1)
if ($Reply.Count -gt 0) {
    $FeedbackBody = @{ message_id = $Reply[0].id; kind = "incorrect"; comment = "Synthetic test" } | ConvertTo-Json -Compress
    $Feedback = Invoke-RestMethod -Method Post -Uri "$Api/api/v1/feedback/" `
        -Headers $Headers -ContentType "application/json" -Body $FeedbackBody
    Write-Host ("Feedback ID: {0}" -f $Feedback.id)
}
.\scripts\test-chat-stream.ps1 -ApiUrl "$Api/api/v1/chat/stream" -ConversationId $ConversationId -CancelAfterFirstDelta
$AfterCancel = Invoke-RestMethod -Uri "$Api/api/v1/conversation/$ConversationId" -Headers $Headers
$AfterCancel.messages | Select-Object role, status, sequence
Remove-Variable Token, TokenLine, Headers -ErrorAction SilentlyContinue
```

Ensure Windows-hosted `llama.cpp` is healthy before SSE tests:
`docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure --llm`.
After cancellation, observe `cancelled` (possibly delayed briefly because
disconnect detection depends on ASGI/network behavior). A client may not
receive `message_end` when it disconnects.

## Evidence to send back

Share (with tokens and private data redacted): `git log -1 --oneline`,
`docker compose ps`, Alembic `current` / `history`, pytest summary,
Conversation JSON with **synthetic** messages and statuses, API HTTP statuses,
SSE event order and cancellation behavior, sanitized LLM readiness result,
and `docker compose logs --tail 60 app` only if an error occurs.
