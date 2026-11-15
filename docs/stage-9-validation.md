# مرحله ۹ — Gap Analysis، داده‌های مصنوعی، CI و Benchmark محلی

**وضعیت:** partial — pending local benchmark and final acceptance. این سند نتیجه Mock/CI را با کیفیت واقعی مدل محلی یکی نمی‌داند.

## وضعیت واقعی قبل از تغییر (HEAD مرحله ۸: f5573691)

- معماری موجود: FastAPI، `@inject`، Controller discovery، SQLAlchemy Async و Alembic؛ Migration فعلی `20261115_04`.
- سناریوهای `religious_qa`، `personnel_matching`، `talent_discovery`، `internal_transfers`، `research_advice`، `personal_development` و `task_allocation` با Service/Repository/DTO/SSE وجود داشتند.
- ۲۲۰ تست موفق و ۲ مورد skip در Windows پایان مرحله ۸ توسط کاربر گزارش شده‌اند؛ نتایج Stage 9 باید جداگانه سنجیده شوند.
- Benchmark موجود مرحله ۵ دارای ۱۰ سند فارسی و ۲۰ سؤال و Recall@5، MRR@5، صحت ساختار Citation و Latency بوده است؛ این نتیجه **معادل ارزیابی کیفیت پاسخ تولیدی LLM نیست**.
- Identity داخلی Production بدون Trusted Provider معتبر fail-closed است. جایگزین تستی فقط در نقطه مرزی و فقط داخل Test Runner انجام می‌شود.
- PostgreSQL integration و Qdrant integration موجود بودند؛ اما Seed یکپارچه و ارزیابی گسترده مرحله ۹ وجود نداشت.

## Gap Analysis و معیار پذیرش

| قابلیت | وضعیت قبل | تست‌های موجود | Gap / ریسک | اقدام Stage 9 / فایل‌ها | معیار قابل اندازه‌گیری |
|---|---|---|---|---|---|
| سناریوهای هفت‌گانه | Implemented | test_stage8_unit/api | Oracle پراکنده و موارد منفی کم | `benchmarks/stage9_scenarios_fa.json`، `tests/test_stage9_scenarios.py` | خروجی ساختاریافته، SSE، SQL History، status و محدودیت برای تمام ۷ سناریو |
| Seed | Partial | Seed داخل تست مرحله ۸ | نبود Dataset نسخه‌دار/اجرای ایمن مستقل | `seed_stage9.py`، fixture JSON | Validation، SHA-256، deterministic، اجرای مجدد بدون تغییر Version |
| Identity و tenant | Implemented | Stage 3/4/7/8 API | امکان Regression IDOR و Forged Claims | تست Stage 9 public/internal، tenant، malicious attrs | 401/403/404/422 برای درخواست نامعتبر و عدم نشت |
| Conversation، Feedback، SSE | Implemented | Stage 3/4/6/8 | تست بار و قطع واقعی Client نیازمند محیط اجرایی | Regression سراسری؛ SSE/History Stage 9 | framing، ordering، completed/cancelled/failed و ownership |
| Ingestion و Qdrant | Implemented | Stage 5 API/Workflow/Qdrant | Recovery و OCR فارسی واقعی وابسته به محیط | CI موجود و Runbook Stage 5، بدون بازنویسی | ارزیابی هفت فرمت، hybrid dense+lexical و lifecycle |
| RAG | Partial acceptance | Stage 5 Persian benchmark | Citation precision معنایی، nonempty-evidence E2E و مقایسه کنترل‌شده Dense/Hybrid هنوز باز | ابزارهای Stage 5 حفظ؛ آزمایش Local/Optional | Recall@5، MRR@5، Citation Issues، p50/p95 latency |
| Agent | Partial acceptance | Stage 7 Tool tests، Stage 8 Domain tests | شواهد واقعی ابزار و کیفیت فارسی مدل سبک | Oracle سناریوها + تست محدودیت و مجوز موجود | Correct Tool، no unauthorized calls، step/tool/time limits |
| Benchmark LLM | Missing | readiness/stream tests | TTFT واقعی، token/s و Resource Metrics نامعلوم | `benchmark_stage9_llm.py`، prompts JSON و تست MockTransport | warm-up، p50/p95، بدون جعل token/s |
| CI / PostgreSQL | Partial | Python 3.11/3.12، PostgreSQL مرحله ۴، Qdrant مرحله ۵ | نبود PostgreSQL seed-stage9 قابل تکرار | `tests/test_stage9_postgres.py`، workflow | Migration روی DB جدید CI؛ idempotency و scope تست واقعی |
| Windows delivery | Partial | stage2-8 runbooks و اسکریپت‌ها | Benchmark مدل محلی و منابع هنوز اندازه‌گیری نشده | این Runbook | دستورهای PowerShell و خروجی قابل بازبینی |

**تغییر Schema، Endpoint و Migration در این مرحله:** ندارد. Stage 9 از قرارداد و Migration مرحله ۸ استفاده می‌کند. بدون اجازه، Database، Qdrant Collection و Volume عملیاتی حذف یا reset نمی‌شوند.

## Dataset و معیارهای ارزیابی

`benchmarks/stage9_scenarios_fa.json` فقط داده جعلی است: FAQ تأییدشده و سؤال فاقد منبع، افراد دارای Skills/Experience/Availability مختلف، Positionهای دارای Hard/Soft Constraints، Capacity، Mobility، Research دارای Source، برنامه رشد و DAG با Cycle/Shortage. هر Case دارای پاسخ مرجع ساختاریافته و انتظار status است. آزمون SQL/SSE این Oracle را با خروجی واقعی الگوریتم سناریو مقایسه می‌کند.

`benchmarks/stage9_llm_prompts_fa.json` دارای چهار Prompt فارسی نسخه‌دار برای ارزیابی انسانی رعایت دستور، عدم جعل استناد، استدلال درباره ریسک و مقاومت در برابر Prompt Injection است. هیچ‌کدام مبنای ادعای کیفیت قطعی مدل بدون بررسی خروجی واقعی نیستند.

- **Scenario exact-oracle accuracy:** تعداد Caseهای مطابق status و IDهای مرجع / کل Caseهای اجراشده؛ داده سناریو مصنوعی است و مدل مولد را اندازه نمی‌گیرد.
- **Recall@5:** نسبت پرسش‌هایی که سند مرجع در پنج نتیجه نخست بازیابی شده است؛ **MRR@5:** میانگین `1/rank` سند مرجع برای rank≤5، و صفر برای بقیه.
- **Citation Issues@5:** تعداد استنادهای دارای شناسه/نسخه/Metadata نامعتبر در Top 5؛ *Citation Precision معنایی* نیازمند قضاوت درباره پشتیبانی واقعی ادعا توسط متن است و از این شمارش استنتاج نمی‌شود.
- **Source Coverage:** تعداد پاسخ‌های دارای دست‌کم یک منبع مرتبط / پاسخ‌هایی که باید مستند باشند؛ در آزمایش پاسخ‌های تولیدی نیازمند بازبینی مرجع است.
- **Unsupported Answer Rate:** تعداد پاسخ‌های دارای ادعای بدون شاهد / تعداد پاسخ‌های داوری‌شده؛ فعلاً بدون Label دستی و Benchmark واقعی **not measured**.
- **Dense-only versus Hybrid و اثر Reranker:** باید روی همان Dataset، همان Embedding/Index و شرایط یکسان A/B اجرا شود؛ در این مرحله نتیجه جدید قطعی گزارش نشده است.
- **Agent:** تصمیم Tool در تست Schema/Allowlist و محدودیت تعداد Tool Call و Workflow سنجیده می‌شود؛ نتیجه Unit/Mock را از Tool Calling واقعی `llama.cpp` جدا ثبت کنید.

## اجرای امن در Windows 11 (PowerShell)

همه دستورهای زیر با مسیر قابل اصلاح هستند. از اجرای Pull روی Working Tree دارای تغییر جلوگیری کنید:

```powershell
$Project = 'D:\chatbot-service-llm'
if (-not (Test-Path $Project)) {
    git clone https://github.com/Amirmahdimtz/chatbot-service-llm.git $Project
}
Set-Location $Project
git status --short
# Only if no uncommitted changes:
git pull --ff-only origin main
git rev-parse HEAD
python -m pip install -r requirements-dev.txt
python -m compileall -q src tests
python -m pytest -q tests/test_stage9_scenarios.py tests/test_stage9_benchmark.py
python -m pytest -q
python -m alembic -c src/infrastructure/alembic/alembic.ini history
python -m src.infrastructure.scripts.seed_stage9
```

آخرین دستور فقط Dataset را **اعتبارسنجی** می‌کند، هیچ نوشتنی ندارد. اجرای HTTP/SSE/SQLite آزمایشی در `test_stage9_scenarios.py` نیز به DB فعلی شما متصل نیست.

برای API و Migration زیرساخت موجود، نخست فایل `.env` خودتان را بدون چاپ Secret بررسی کنید. مقادیر پورت فعلی روی سیستم شما 18031، 15454 و 16355 گزارش شده‌اند؛ به‌صورت ثابت وارد Production نکنید.

```powershell
docker compose config --quiet
docker compose up -d --build --wait
docker compose exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini upgrade head
docker compose exec -T app python -m alembic -c src/infrastructure/alembic/alembic.ini current
docker compose ps
Invoke-WebRequest 'http://127.0.0.1:18031/api/v1/health' -UseBasicParsing
```

**اختیاری — Seed روی PostgreSQL مستقل و صریحاً آزمایشی:** فقط اگر یک Database *جدید* با نام `chatbot_stage9_local` در همان PostgreSQL ساخته و Migrationهای اصلی را روی **همان Database مجزا** اعمال کرده‌اید. از Database اصلی `chatbot` استفاده نکنید؛ Script آن را رد می‌کند. نمونه ایجاد DB جدید در صورت عدم وجود (یک بار):

```powershell
docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE chatbot_stage9_local;"'
```

برای اجرای Migration و Seed، `CHATBOT_DATABASE_URL` و `CHATBOT_STAGE9_TEST_DATABASE_URL` را صرفاً برای همان **process** به نشانی PostgreSQL مجزا تنظیم کنید. رمز را از محیط خصوصی محلی خود تأمین و URL-encode کنید و آن را در Log یا Chat چاپ نکنید. گزینه `CHATBOT_STAGE9_ISOLATED=1` و نام Database با پیشوند `chatbot_stage9_` و Host فقط `postgres` / `localhost` / `127.0.0.1` اجباری است. نمونه اجرا پس از آماده‌شدن متغیر `$TestDatabaseUrl`:

```powershell
docker compose exec -T -e "CHATBOT_DATABASE_URL=$TestDatabaseUrl" app python -m alembic -c src/infrastructure/alembic/alembic.ini upgrade head
docker compose exec -T -e "CHATBOT_STAGE9_ISOLATED=1" -e "CHATBOT_STAGE9_TEST_DATABASE_URL=$TestDatabaseUrl" app python -m src.infrastructure.scripts.seed_stage9 --seed
# PostgreSQL integration tests run in host Python, not inside the production app image:
$HostTestDatabaseUrl = $TestDatabaseUrl.Replace('@postgres:5432/', '@127.0.0.1:15454/')
$env:CHATBOT_STAGE9_ISOLATED = '1'
$env:CHATBOT_STAGE9_TEST_DATABASE_URL = $HostTestDatabaseUrl
python -m pytest -q tests/test_stage9_postgres.py
```

**دقت:** این آزمون به جدول‌های Migrated نیاز دارد؛ بدون Migration و جداسازی DB اجرا نشود. Production Identity هیچ‌جا برای آسان‌کردن Seed تغییر نکرده است. اسکریپت داده‌های موجود متعلق به Owner دیگر را overwrite نمی‌کند و هیچ delete ندارد.

## Benchmark واقعی llama.cpp (اجرای اختیاری روی Windows Host)

پیش‌نیازها را بررسی کنید؛ وجود Runtime یا مدل را از پیش تأییدشده ندانید:

```powershell
$LlamaServerExe = 'D:\PATH-TO-LLAMA-CPP\llama-server.exe' # Replace with actual executable
$ModelFile = 'D:\PATH-TO-MODELS\Qwen3-1.7B-Q4_K_M.gguf' # Replace with actual GGUF
Test-Path $LlamaServerExe
Test-Path $ModelFile
if ((Test-Path $LlamaServerExe) -and (Test-Path $ModelFile)) {
    & $LlamaServerExe --help | Select-String 'threads|ctx-size|parallel|n-gpu-layers|reasoning'
}
```

فقط پس از تأیید Help و وجود مدل، در **PowerShell جداگانه** مدل سبک را CPU-only سرو کنید. برای 4B ابتدا مصرف RAM مدل 1.7B را بررسی و دو Runtime را هم‌زمان اجرا نکنید:

```powershell
& $LlamaServerExe --model $ModelFile --host 127.0.0.1 --port 8080 --threads 4 --ctx-size 2048 --parallel 1 --n-gpu-layers 0 --reasoning off
```

در پنجره اصلی و **فقط بعد از Ready شدن سرور**، هر بار نام خروجی تازه انتخاب کنید؛ اسکریپت از overwrite جلوگیری می‌کند. اگر API Key برای مدل تنظیم شده است، `CHATBOT_LLM_API_KEY` باید به‌شکل Secret در Environment همین Process موجود باشد.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8080/health'
Invoke-RestMethod 'http://127.0.0.1:8080/v1/models'
python -m src.infrastructure.scripts.benchmark_stage9_llm --base-url http://127.0.0.1:8080 --model-label Qwen3-1.7B --quantization Q4_K_M --runs 3 --warmup 1 --output .\stage9-llm-1p7b-local.json
Get-Process -Name llama-server -ErrorAction SilentlyContinue | Select-Object Id, CPU, WorkingSet64, PeakWorkingSet64
```

همان مراحل را جداگانه برای `Qwen3-4B-Instruct-2507` تکرار کنید **فقط اگر واقعاً مدل GGUF و حافظه کافی وجود دارد**. اسکریپت خروجی JSON با شناسه مدل سرو‌شده، SHA256 Dataset، Warmup، تعداد خطا، TTFT/Latency و p50/p95 می‌سازد. `generated_tokens_per_second` فقط در صورت وجود `completion_tokens` واقعی در Streaming Usage محاسبه می‌شود؛ `characters_per_second_proxy` هرگز token/s نیست. `Get-Process` تنها Snapshot و PeakWorkingSet از زمان آغاز Process است؛ Peak RAM/CPU دقیق در بازه Benchmark نیازمند پروفایلینگ جداگانه است.

Benchmark Retrieval/Reranking مرحله ۵ همان مسیر قبلی را دارد: `docs/stage-5-benchmark-fa.md`، `docs/stage-5-ingestion-retrieval.md` و اسکریپت‌های `benchmark_stage5_fa.py` و `benchmark_stage5_rerank_ab_fa.py`. آنها ممکن است اسناد عمومی مصنوعی را در DB مورد تست ثبت کنند؛ فقط در محیط ایزوله و با رضایت صریح خودتان اجرا شوند. Endpoint داخلی Stage 9 به Production اضافه نشده است.

## CI و ارسال شواهد

GitHub Actions: `.github/workflows/tests.yml`، Python 3.11/3.12 + تمام تست‌ها، Compile، Alembic history، Compose، PostgreSQL واقعی در DB اختصاصی `chatbot_stage9_ci`، Qdrant حقیقی در Collectionهای آزمایشی و Windows PowerShell syntax. Benchmark مدل حجیم، OCR فارسی دقیق و فشار سخت‌افزاری در CI اجباری نیستند.

خروجی‌های موردنیاز برای بررسی بعدی:

1. `git status --short`، `git rev-parse HEAD`؛ متن خلاصه `pytest -q` و نام هر تست ناموفق.
2. `docker compose ps` و `alembic current`، بدون Secret.
3. فایل JSON خام Benchmark 1.7B (و 4B در صورت امکان) و Command/Version واقعی `llama-server`، بدون API Key.
4. خلاصه `Get-Process` برای RAM/CPU، با ذکر اینکه Snapshot است.
5. در صورت نیاز، فقط خطاهای sanitised از `docker compose logs --tail 80 app`؛ هرگز `.env`، Authorization Header یا داده واقعی پرسنل را نفرستید.

**Definition of Done:** تا اجرای Benchmark سخت‌افزار Windows، تأیید کیفیت فارسی/استناد واقعی، اعتبارسنجی کامل Security/E2E روی محیط محلی و موفقیت CI آخرین Commit، مرحله ۹ `completed` نیست. عملیات مستقل مرحله ۱۰ اجرا نشده است.
