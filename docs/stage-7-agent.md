# Stage 7 — Internal bounded Agent with schema-validated tools

This stage extends the existing `POST /api/v1/chat/stream`; it does not create a new service, schema or database migration. Route `agent_qa → agent` is explicitly chosen by the validated request, never by an audience/tenant/permission claim in the message. `general → direct_llm` and `knowledge_qa → rag` remain separate.

## Workflow and trust boundaries

```
ChatController (authentication, SSE) → ChatService (ownership, history, persistence)
  → ScenarioRouterService (agent_qa)
  → AgentService (bounded choices and tool execution)
    → AgentToolRegistry (server allowlist, schema + trusted scope)
      → RagService → KnowledgeIndexService → Qdrant + PostgreSQL authorization
      → KnowledgeService → KnowledgeRepository → scoped PostgreSQL
    → LlamaCppProvider (local JSON decision and streamed Persian final answer)
```

Agent's planner asks the local `/v1/chat/completions` endpoint for a **non-streaming JSON object** using a schema-constrained `response_format: {"type":"json_schema","json_schema":{"name":"agent_decision","strict":true,"schema":...}}`, `temperature:0`, configured max_tokens and disabled thinking when configured. The response is parsed as JSON and validated using `ToolDecision` and the selected tool's **strict Pydantic input schema**; the backend, not the model, chooses the callable from a fixed server allowlist. This is **structured JSON tool selection**, not native OpenAI `tools/tool_calls`. Native tool calls require compatible `llama.cpp` `--jinja` and model chat templates; they have NOT been verified on the user's specific Qwen3 GGUF/build. A Windows test with Qwen3-1.7B and build 12242 produced HTTP 200 and JSON, but the planner response did not match the expected fields (`AGENT_INVALID_DECISION` after about 55 seconds). The actual JSON was not logged, so the exact invalid field remains unknown. In this update, JSON schema-constrained decoding replaces free-form `json_object` for Agent decisions; it constrains `action`, `tool` (to permitted names or null), required `arguments`, and top-level keys. Allowed argument property names are derived from the trusted Pydantic tool definitions; unknown keys are excluded by the JSON schema, and each tool's Pydantic model remains authoritative. The backend still independently validates semantics and tool arguments; a second Windows run with the Qwen3-1.7B build confirmed valid structured tool selection and successful `list_owned_documents` execution (zero results), but the same tool was then selected again and caused `AGENT_REPEATED_CALL` after about 35 seconds. The repeated-call policy was changed to reuse the existing validated result and continue to final generation; acceptance of the final response on Windows is pending. Do not interpret HTTP 200 or valid JSON as proof the schema was enforced. When rejected, logs contain only safe validation-field categories and error types, not the model response.

The `agent_qa` planner **must execute at least one server-authorized read-only tool before it can finish**. Its first-turn JSON schema restricts `action` to `tool` and `tool` to server-allowed names; Core independently rejects a premature `finish` even if the model ignores the schema. A successful final response therefore always has at least one `tool_start` and `tool_result`. For owned-document questions, the prompt prioritizes `list_owned_documents`. If all executed tools return no authorized documents/evidence, the Backend emits a short static Persian answer derived from the validated empty results; it does **not** ask the model to invent reasons involving security, approval, identity or nonexistent documents. This avoids slow ungrounded generation. If any authorized evidence exists, the standard streamed final LLM response continues. These rules address a later Windows run that previously completed in about 104 seconds with **no tool events** and unsupported claims about approval status.

The planner may choose `{"action":"tool","tool":"search_knowledge","arguments":{"query":"..."}}`, `{"action":"tool","tool":"list_owned_documents","arguments":{"limit":5}}`, or `{"action":"finish","tool":null,"arguments":{}}`. Another turn sees the actual validated result as **lower-trust user-role data**, never as a system message. A finish decision starts a separate streaming model completion with the accumulated authorized results; a result is never fabricated. Prompt injection may still affect the model's prose, so allowlists, identity enforcement, citation provenance and zero write operations are security boundaries independent of model obedience.

## Tools

| Tool | Contract | Backend | Authorization |
|---|---|---|---|
| `search_knowledge` | `query`: string 3..500; output `evidence` + validated `sources[]` | `RagService.prepare_async` (actual permitted hybrid retrieval, RRF, reranking, SQL-visible citations) | trusted public scope or trusted internal tenant + `knowledge:read_internal` |
| `list_owned_documents` | `limit`: integer 1..10; output `items[{document_id,title,status,version}]`, `has_more` | `KnowledgeService.list_async` → tenant- and owner-scoped repository | same trusted identity conditions |

Only `agent_qa` can invoke these tools. Public cannot query internal collection or list another person's documents. Internal scope must have a nonempty tenant and explicit knowledge permission. Unsupported scenarios, arbitrary tool names, extra fields, raw SQL, shell, HTTP and filesystem requests cannot be executed. Model output, inputs and tool outputs are independently validated. A future Stage 8 tool must define a server-owned spec, Pydantic input/output and DI-injected implementation with explicit permission/scenario checks, then be added to the registry's hardcoded dispatch. Do not expose dynamic Python import, eval or a generic API invoker.

## SSE and persistence

For a successful grounded multi-tool exchange: `message_start` → `tool_start` → `tool_result` → `sources` (if valid) → optional further tool events → `delta*` → `message_end(status=completed,response_type=agent_generated)`. `tool_start` has only `tool`, opaque `call_id`; `tool_result` contains `tool`, `call_id`, `status=completed`, `item_count`, not raw result, internal prompt or secrets. `sources` carries only authorized citation identifiers/title/version/location (no `source_uri`).

An all-empty tool result produces a single server-authored `delta` and a normal completed `message_end` with the response persisted. A model refusal to use the first required tool fails closed with `AGENT_INVALID_DECISION`; it does not produce a tool-free generated answer. A tool/model error produces a sanitized `error` and one failed `message_end`; premature disconnect cancels the provider/tool when possible and persists `cancelled` using the existing shielded finalizer. The model's final text is stored as the assistant message under the same scoped conversation ownership/IDOR rules. No separate tool result persistence or replay contract is introduced. A duplicate planned call emits no second `tool_start`/`tool_result`; SSE still ends as completed when the final response is streamed and persisted.

## Bounded configuration

Values in both appsettings YAMLs:

| Key | Default | Validation |
|---|---:|---|
| agent.max_steps | 4 | 1..8 |
| agent.max_tool_calls | 2 | 1..4 |
| agent.tool_timeout | 45 seconds | 1..180 |
| agent.workflow_timeout | 240 seconds | greater than tool timeout and <= 600 |
| agent.context_budget | 3072 UTF-8 bytes | 256..8192 |
| agent.max_tool_output_size | 3072 UTF-8 bytes | 256..16384 |
| agent.max_concurrent_workflows | 1 | 1..2 |

Requests also share the existing `llm.max_concurrent_requests=1`, LLM output max and history budget. A repeated identical tool call is **not re-executed**: planning stops and the final answer streams using only previously validated authorized observations, even when the allowed tool-call budget is exhausted. An unexecuted new call beyond the budget, missing finish decision within step limit, excessive output/context, request/step timeout and model failure remain terminal sanitized errors. For an empty `list_owned_documents` result, final generation must state the lack of visible owned documents without inventing documents or implying that all tenant documents are absent. Note that UTF-8-byte budgeting is conservative, not an exact tokenizer.

## Windows PowerShell — isolated development validation

Keep the Stage 6 Compose project and all volumes intact. Use a *new* Compose project and ports to avoid collisions. This script assumes local `llama.cpp` services 8080/8081/8082 are already configured; do not reinstall or restart them without checking first.

```powershell
$Repo = "D:\chatbot-service-llm"
if (-not (Test-Path $Repo)) {
    git clone https://github.com/Amirmahdimtz/chatbot-service-llm.git $Repo
    if ($LASTEXITCODE -ne 0) { throw "Clone failed" }
}
Set-Location $Repo
git status --short
if (git status --porcelain) { throw "Review existing local changes; do not overwrite them" }
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "Pull failed" }
$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    py -3.11 -m venv .venv
    $Python = ".\.venv\Scripts\python.exe"
}
& $Python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency check failed" }
& $Python -m compileall -q src tests
if ($LASTEXITCODE -ne 0) { throw "Compile failed" }
& $Python -m pytest -q tests/test_stage7_agent.py tests/test_stage7_provider.py tests/test_stage7_api.py
if ($LASTEXITCODE -ne 0) { throw "Stage 7 tests failed" }
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Regression tests failed" }
if (-not (Test-Path .env)) { & .\scripts\initialize-development-env.ps1 }
$env:CHATBOT_APP_PORT = "18030"
$env:POSTGRES_HOST_PORT = "15453"
$env:QDRANT_HOST_PORT = "16354"
$env:CHATBOT_STORAGE_HOST_PATH = "D:\chatbot-stage7-validation-storage"
New-Item -ItemType Directory -Force -Path $env:CHATBOT_STORAGE_HOST_PATH | Out-Null
docker compose --project-name stage7-validation config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose config failed" }
docker compose --project-name stage7-validation up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw "Compose failed" }
docker compose --project-name stage7-validation exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw "Existing migrations failed" }
docker compose --project-name stage7-validation ps
curl.exe --fail --silent --show-error http://127.0.0.1:8080/health
curl.exe --fail --silent --show-error http://127.0.0.1:8081/health
curl.exe --fail --silent --show-error http://127.0.0.1:8082/health
curl.exe --fail --silent --show-error http://127.0.0.1:18030/api/v1/health
.\scripts\test-chat-stream.ps1 -ApiUrl "http://127.0.0.1:18030/api/v1/chat/stream" -Scenario agent_qa -Question "اسناد متعلق به من را فهرست کن و اگر اطلاعات کافی نیست توضیح بده."
```

Inspect `message_start.route=agent`, whether `tool_start/tool_result` really occurred (a model may select `finish` early), `message_end.response_type=agent_generated`, and history through `GET /api/v1/conversation/{conversation_id}` with the same synthetic Bearer identity. No `sources` event is expected for `list_owned_documents` alone or empty search; for citations, first index **synthetic** public documents using the Stage 5/6 fixtures and rerun a `search_knowledge` question.

For troubleshooting (redact tokens, content, prompts, file paths, personal data), share:
```powershell
git rev-parse HEAD
docker compose --project-name stage7-validation ps
docker compose --project-name stage7-validation logs --tail 80 app
```
Report test pass/fail output, only sanitized SSE event names/tool names/error codes, model build/flags and whether `response_format` selection succeeded. Check `LLM_BAD_RESPONSE` for malformed JSON or model-template mismatch, `LLM_BUSY` for occupied CPU model slot, `AGENT_LIMIT` for small-model failure to finish, and `AGENT_TOOL_DENIED` for missing trusted permission. Do not expose `.env` contents. CI mocks do not prove real Qwen3 JSON selection, semantic Persian quality, production SSO or sustained i7-6700 latency; Stage 7 remains **partial** until the Windows runtime evidence is received.

No destructive commands, volume deletion, database resets, force push or new production credentials are required.
