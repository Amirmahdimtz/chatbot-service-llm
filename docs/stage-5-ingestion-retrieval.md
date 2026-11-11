# Stage 5 — Document ingestion and hybrid retrieval

## Scope and boundaries

Stage 5 introduces real upload, persistent original storage, extraction, Persian text
normalization, location-aware chunks, local-model embeddings, Qdrant dense + sparse
lexical search, RRF and local cross-encoder reranking. It does **not** connect the
retrieved context to Chat SSE; that is Stage 6. No external identity provider is
implemented. Production continues to fail closed until a trusted identity
integration is supplied.

Stage 4 registration/history/feedback contracts remain unchanged. Existing
knowledge registration creates a record in `registered` status, not an indexed
document.

## Processing and recovery

1. `POST /api/v1/knowledge/`: register document with trusted actor, owner and audience.
2. `POST /api/v1/knowledge/{id}/upload`: multipart field `file` with extension
   matching the registered `source_type`; 25 MiB default maximum.
3. Authorization, actual content validation, SHA-256, owner/audience deduplication
   and an atomic PostgreSQL processing claim.
4. Write UUID-based filename under `storage/documents/originals/<uuid>/` using an
   fsync + rename, record the pending key and checksum for retry.
5. Parse to sections with source provenance; reject malformed/empty content.
   OCR is required when native PDF page extraction is insufficient.
6. Normalize Arabic/Persian forms and safe Unicode; lexical-token chunk budget
   512 with 64 overlap (approximate words/punctuation, **not** the Qwen tokenizer).
   Chunking respects document section/page/row and paragraph boundaries.
7. Call the local llama.cpp `/v1/embeddings` endpoint. Validate actual vector
   dimension, finite values and response order; default expected size 1024.
8. Validate/create the appropriate Qdrant collection without replacing existing
   collections; upsert deterministic per-version UUIDv5 chunk IDs and
   separately indexed dense and hashed lexical sparse vectors.
9. Commit PostgreSQL status `approved`, active version, checksum, storage key,
   embedding model version and chunk IDs **only after** confirmed Qdrant writes.

`POST /api/v1/knowledge/{id}/reindex` reuses the checksum-verified stored original
to create a fresh version with the currently configured model, without
requiring a new upload. It is rejected if there is no successful indexed
original. A model-version mismatch in an existing collection still requires
a separately approved safe index cutover; reindex never overwrites an
incompatible vector space.

Retry uses the persisted pending file and checksum. A crashed process may leave
an unfinished claim; configured stale processing claims (180 minutes) may be
recovered, but users should confirm that the previous worker is no longer
running before retrying. A failed replacement leaves the old approved version
available. After successful replacement the previous version is marked inactive
non-destructively; PostgreSQL checks the current version on every result.
No deletion endpoint or destructive collection migration is implemented.

There is no cross-system distributed transaction. Orphan files or vectors from
crashes can remain on disk; access is blocked by active PostgreSQL metadata and
version checks. Physical garbage collection requires an approved retention plan.

## Formats, local tooling, and threats

- `txt`, `json`, `csv`: strict UTF-8, explicit malformed/empty errors.
- `docx`: python-docx reading text and tables from bounded OOXML ZIP.
- `xlsx`: openpyxl read-only, sheet/row provenance, row/column ceilings.
- `pdf`: PyMuPDF page text or local Tesseract OCR (`fas+eng`) when needed.
- `doc`: legacy OLE signature, local LibreOffice headless conversion to
  temporary DOCX, then the same DOCX parser.

ZIP expansion is bounded. Filenames are never used as storage paths. A file
whose type/size/content is invalid does not become indexed. OCR/LibreOffice
failures are explicit. Converter/OCR processes operate on untrusted content,
so deploy with the container's read-only filesystem, no new privileges,
non-root user, tmpfs, network isolation and resource limits. For stricter
production threat models a separate sandbox is recommended; no document
content is interpreted as backend instructions or executable commands.

## Qdrant index contract

Logical collections are `knowledge_public` and `knowledge_internal`.
They must have named dense vector `dense` using Cosine and a named
sparse vector `lexical`. The lexical vector is a deterministic SHA-256
hash of lowercase Persian-normalized terms into unsigned 32-bit indices,
with log term-frequency weights and L2 normalization. This is independent
from dense retrieval; it is not BM25 and has no corpus IDF. Persian quality
must be compared against stronger alternatives on a benchmark before tuning.

Each point payload contains `document_id`, `chunk_id`, `version`,
`text`, `location`, `source_uri`, `title`, `audience`, `owner_id`,
`tenant_id`, `classification`, `published`, `active`, and
`embedding_model_version`. First-stage dense and sparse results (20 per
query by default) are combined via RRF (k=60), deduplicated, checked against
approved and current PostgreSQL metadata, then reranked to top five.

Collection schema and an indexed point's model-version metadata are checked
before ingest; a model change must never silently reuse the same vector
space. No collection is dropped, recreated or overwritten on mismatch.

## Authorization

The test Development token grants **synthetic public** access only.
`knowledge:write` can register/upload/retry owned documents. Publication is
distinct: `knowledge:publish` on the trusted backend actor and a public,
unclassified, approved document are required to mark it visible to other
public users. Publication is not granted by self-declared HTTP fields.
Internal indexing is possible only through a trusted internal identity
in integration tests / future organization identity integration.
`knowledge:read_internal` permits internal tenant-scope retrieval;
otherwise only owned tenant-matching internal documents may be retrieved.
`knowledge:read_public` allows internal users to retrieve public documents.
Public users never query `knowledge_internal`.

The vector store has restrictive audience/tenant/owner/publication filters,
and every candidate is revalidated using PostgreSQL ownership, tenant,
document status, active version, model version and chunk ID.
Document IDOR and cross-tenant/cross-collection access are denied.
The public metadata GET/list remain owner-only (Stage 4 API compatibility).
Untrusted document text may appear as retrieval evidence but does not
acquire privileged tool/command execution rights.

## HTTP contracts

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/v1/knowledge/` | Existing JSON metadata registration, 201 |
| GET | `/api/v1/knowledge/` | Existing owner-scoped listing |
| GET | `/api/v1/knowledge/{id}` | Owner-only status, error, checksum, version and extraction metadata |
| POST | `/api/v1/knowledge/{id}/upload` | Multipart `file`, process first version, 200 |
| POST | `/api/v1/knowledge/{id}/replace` | Multipart `file`, new version only on success |
| POST | `/api/v1/knowledge/{id}/retry` | Recover pending original without reupload |
| POST | `/api/v1/knowledge/{id}/reindex` | Refresh version from stored original |
| POST | `/api/v1/knowledge/{id}/publish` | Explicit permission required |
| POST | `/api/v1/knowledge/search` | JSON `{"query":"..."}`; top hits with citation metadata |

Expected errors: 401 unauthenticated, 403 authorization/spoofing, 404 IDOR,
409 duplicate/processing/conflict, 413 oversize, 422 validation/extraction,
503 infrastructure/model unavailable. Exception bodies and secrets are never
returned. Unlike Chat SSE, Stage 5 operations are synchronous HTTP requests;
large CPU-only ingestions can be slow, so tune gateway timeouts conservatively.

## Windows 11 — safe bootstrap

Run in PowerShell from a writable directory on D:. Do not delete Docker
volumes, collections or local model files.

```powershell
$Repo = "D:\chatbot-service-llm"  # Edit to the real checkout
if (-not (Test-Path (Join-Path $Repo ".git"))) {
    git clone https://github.com/Amirmahdimtz/chatbot-service-llm.git $Repo
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}
Set-Location $Repo
git status --short
if (git status --porcelain) { throw "Review local modifications before pulling" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "Pull failed" }
git log -1 --oneline
.\scripts\initialize-development-env.ps1
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Invalid compose configuration" }
docker compose up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw "Containers unavailable" }
docker compose exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw "Migration failed" }
docker compose exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini current
docker compose exec -T app python -m src.infrastructure.scripts.check_infrastructure
docker compose exec -T app python -m src.infrastructure.scripts.check_stage5_parsers
docker compose ps
```

The development .env must include the new values below (add manually to an
**existing** .env; initialization is idempotent and will not overwrite it).
Do not post actual tokens/passwords:

```dotenv
CHATBOT_EMBEDDING_BASE_URL=http://host.docker.internal:8081
CHATBOT_EMBEDDING_API_KEY=
CHATBOT_RERANKING_BASE_URL=http://host.docker.internal:8082
CHATBOT_RERANKING_API_KEY=
CHATBOT_QDRANT_API_KEY=
```

The model binaries and exact GGUF file paths are local user inputs, **not**
downloaded or bundled by Docker. Verify licenses and file integrity before
use. In separate PowerShell windows, start the actual installed llama-server
binary (edit paths) for **one model at a time** when RAM is tight:

```powershell
$Server = "D:\models\llama.cpp\llama-server.exe" # Change to actual executable
$EmbeddingGGUF = "D:\models\embedding\model.gguf" # Change to actual checkpoint
if (-not (Test-Path $Server) -or -not (Test-Path $EmbeddingGGUF)) { throw "Set real model paths" }
& $Server -m $EmbeddingGGUF --embedding --pooling last --threads 4 --ctx-size 2048 --parallel 1 --n-gpu-layers 0 --host 127.0.0.1 --port 8081
```

A separate reranker server (if enough RAM) can be started with:

```powershell
$RerankerGGUF = "D:\models\reranker\model.gguf" # Change to actual compatible checkpoint
if (-not (Test-Path $Server) -or -not (Test-Path $RerankerGGUF)) { throw "Set real model paths" }
& $Server -m $RerankerGGUF --reranking --threads 4 --ctx-size 2048 --parallel 1 --n-gpu-layers 0 --host 127.0.0.1 --port 8082
```

Confirm both runtime endpoints from inside the container; host-local
127.0.0.1 is not container-local 127.0.0.1. Check
`host.docker.internal` reachability and Windows Firewall restrictions.
Never expose model endpoints to an untrusted network simply to fix
connectivity. Model quantization, `--pooling last` compatibility for Qwen3
Embedding and `--reranking` support for the chosen BGE checkpoint require
real validation on the installed llama.cpp version; no benchmark claim is made.

```powershell
docker compose exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8081/health', timeout=5).status)"
docker compose exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8082/health', timeout=5).status)"
$env:ENV_TYPE = "development"
if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3.12 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest -q
```

For manual API verification, register a synthetic `txt` metadata record,
then upload a small synthetic `sample.txt` file and query it. Obtain
the published app host port via `docker compose port app 8000`.
On Windows PowerShell 5.1, use `curl.exe` (not the `curl` alias) for
multipart file uploads. Keep the Bearer token in a local variable and
exclude it from pasted logs. Inspect the GET status and the
`knowledge_public` collection through Qdrant. Do **not** manually
write to `knowledge_internal` using the synthetic public token.

## Troubleshooting stalled Debian APT downloads on Windows

The Stage 5 Docker image installs LibreOffice and Tesseract from Debian.
If `docker compose up -d --build --wait` pauses at
`RUN apt-get update && apt-get install ...` with repeated `Ign:`
messages from `deb.debian.org`, the immediate failure is external
repository connectivity during **image build**, not Python, Alembic or
Qdrant. Docker Desktop might use a proxy even when Windows host
connectivity succeeds. Do not remove volumes or bypass APT signature
verification.

First interrupt only the active build with Ctrl+C (existing persisted
data is unaffected), then check HTTPS reachability from Windows and
from a disposable container. This diagnostic does not modify the app
or database and does not depend on a running Compose stack.

```powershell
Test-NetConnection deb.debian.org -Port 443
$AptProbe = @'
from pathlib import Path
import subprocess
source = Path("/etc/apt/sources.list.d/debian.sources")
source.write_text(source.read_text().replace("http://deb.debian.org/", "https://deb.debian.org/"))
raise SystemExit(subprocess.run([
    "apt-get", "-o", "APT::Update::Error-Mode=any",
    "-o", "Acquire::Retries=0", "-o", "Acquire::https::Timeout=15",
    "update"
], check=False).returncode)
'@
$AptProbe | docker run --rm -i --entrypoint python python:3.12.16-slim-bookworm -
"Strict APT exit code: $LASTEXITCODE"
```

The Dockerfile now defaults to HTTPS for official Debian repositories,
limits each APT transfer timeout and retry count, and supports optional
build-time mirror URLs. APT index refresh runs with
`APT::Update::Error-Mode=any`, ensuring that failed or partial repository
updates stop the image build before installing packages. If container connectivity fails, inspect Docker
Desktop's **Settings > Resources > Proxies** (actual UI may vary), VPN,
proxy and DNS settings. A browser or host-side network check alone does
not prove the Docker build network is healthy. Do not disable TLS
verification or set `trusted=yes` in APT sources.

If the official endpoints are genuinely unavailable but an authorized
trusted Debian mirror is reachable, pass both appropriate repository
URLs by setting `CHATBOT_APT_DEBIAN_MIRROR_URL` and
`CHATBOT_APT_SECURITY_MIRROR_URL` in a PowerShell session (or in your
uncommitted private `.env`). Do not substitute a PyPI mirror for Debian
APT repositories. Use the actual mirror URLs, not illustrative values.

```powershell
# Optional: only after verifying each trusted replacement URL.
# $env:CHATBOT_APT_DEBIAN_MIRROR_URL = "https://YOUR-DEBIAN-MIRROR/debian"
# $env:CHATBOT_APT_SECURITY_MIRROR_URL = "https://YOUR-DEBIAN-SECURITY-MIRROR/debian-security"
docker compose build --progress plain app
if ($LASTEXITCODE -ne 0) { throw "Image build failed; examine the first APT error" }
docker compose up -d --wait
```

If a proposed mirror returns `Certificate verification failed` or
`The name in the certificate does not match the expected`, reject that
mirror. A mirror present on Debian's public list is not necessarily
configured for HTTPS under every alias. Probe candidate mirror URLs with
normal TLS validation before setting build arguments. Do not use
`Verify-Peer=false`, `trusted=yes`, or `--allow-unauthenticated`.
A healthy pre-existing Compose app container may still run an older image
after a failed build: check that the Stage 5 service module is actually
present after a successful build.

If the HTTPS probe succeeds but the build still stalls, capture the
first `Err:` / `Temporary failure resolving` / `Certificate` /
`Connection timed out` line with `--progress plain`. Share
redacted errors, `docker compose ps` and Docker Desktop proxy status;
never share credentials or complete private proxy URLs.

---

## Testing and remaining acceptance evidence

- Unit tests exercise six Python-native formats, invalid files, legacy
  conversion unavailability, normalization, lexical RRF, model endpoints
  and Qdrant REST contracts.
- SQLite workflow tests exercise actual filesystem writes, recovery,
  version promotion, deduplication, permission boundaries and citation
  retrieval with mocked model/vector systems.
- API tests exercise file upload/replace, registration, retrieval,
  spoofing and IDOR.
- Opt-in real Qdrant test runs with `CHATBOT_TEST_QDRANT_ISOLATED=1`
  and `CHATBOT_TEST_QDRANT_URL` on a disposable service. It creates
  uniquely named test collections and never deletes existing data.
- Container smoke script exercises actual DOC conversion and OCR.
- Real local Qwen3 Embedding and BGE Reranker performance/quality, RAM use,
  dimension and scorer compatibility remain to be measured on Windows.
  Until this evidence exists, Stage 5 must be reported **partial**.
