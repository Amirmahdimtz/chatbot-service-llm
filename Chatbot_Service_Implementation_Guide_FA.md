# سند مرجع نیازمندی‌ها و پیاده‌سازی سرویس چت‌بات هوشمند

> **نام فایل:** `Chatbot_Service_Implementation_Guide_FA.md`  
> **پروژه:** `chatbot-service-llm`  
> **نسخه سند:** `1.2.0`  
> **تاریخ تدوین:** `2026-11-10`  
> **وضعیت:** قرارداد محصول و تصمیم‌های معماری مورد توافق؛ برخی تنظیمات مدل و استقرار محلی تا زمان Benchmark قابل اصلاح هستند.  
> **سند همراه و الزامی:** `Service_Architecture_Guide_FA.md`

---

## ۰. نحوه استفاده از این سند همراه با سند معماری

این سند **شرح پروژه، دامنه تعهدات، فناوری‌های منتخب، رفتار مورد انتظار و معیارهای پذیرش** را مشخص می‌کند؛ `Service_Architecture_Guide_FA.md` مرجع الزام‌آور **ساختار کد، لایه‌بندی، naming، dependency injection، repository، DTO، controller discovery و migration** است. این دو سند باید هم‌زمان خوانده شوند.

**قرارداد با ChatGPT / توسعه‌دهنده:**

1. همه قابلیت‌های تعریف‌شده در این سند، بخشی از دامنه نهایی پروژه‌اند. هیچ سناریویی را بدون درخواست صریح کاربر حذف نکن یا به نسخه/فاز نامعلوم موکول نکن.
2. معماری را مطابق `Service_Architecture_Guide_FA.md` اجرا کن: `Host → Application → Core → Infrastructure`، `@inject`، constructor injection، thin controller، `BaseRepository`، auto discovery و importهای `src.*`.
3. این سرویس **یک کدبیس و یک FastAPI deployment مشترک** برای `public` و `internal` دارد؛ جداسازی دسترسی و داده در سطح backend، PostgreSQL و Qdrant اعمال می‌شود.
4. «AI Agent» در این پروژه **یک Agentic LLM Workflow داخلی در همین برنامه** است؛ به معنای یک microservice یا API خارجی مستقل نیست.
5. LLM و مدل‌های Embedding/Reranking **محلی** هستند. برای اجرای LLM از `llama.cpp` استفاده کن؛ از API مدل ابری به‌عنوان پیش‌فرض استفاده نکن.
6. Vector database پروژه **Qdrant** است؛ از `pgvector` برای ذخیره بردارها استفاده نکن.
7. جریان پاسخ Chat API **Streaming با SSE** است.
8. طراحی را برای داده واقعی سازمان آماده کن، اما آزمایش و توسعه با داده‌های **مصنوعی/ساختگی** انجام می‌شوند.
9. وضعیت اجرای سیستم و مدل‌ها بر اساس محدودیت سخت‌افزار محلی تنظیم شود؛ تنظیمات و مدل‌های اولیه قابل تعویض باشند، بدون بازنویسی Serviceها.
10. به‌جای تولید ساختار اضافی، فقط Componentهایی را بساز که نیاز واقعی دارند. فایل‌ها و importهای پروژه موجود را قبل از اعمال تغییر بررسی کن؛ مسیرهای این سند، **طرح پیشنهادی** هستند نه ادعای وجود فایل‌ها.
11. قبل از تولید کد درباره موارد نامشخص، ابتدا از قراردادهای موجود و پیش‌فرض‌های امن این سند استفاده کن؛ تصمیم جدید را شفاف ثبت کن. اگر تصمیم مستقیماً بر امنیت یا صحت اثر دارد و پیش‌فرض امن وجود ندارد، آن را مشخص کن.
12. **تقدم تصمیم‌ها:** درخواست صریح جدید کاربر بر هر دو سند مقدم است؛ در غیر این صورت برای ساختار و conventions سند معماری، و برای نیازمندی‌های سرویس این سند مرجع است. تعارض‌های باقی‌مانده باید آشکار شوند، نه اینکه بی‌صدا معماری تغییر کند.
13. با هر تصمیم تأییدشده جدید، بخش مرتبط، جدول تصمیم‌ها و تاریخچه تغییرات این فایل را به‌روزرسانی کن.

### محدوده سند

- **مورد توافق:** دامنه کامل، یک deployment، Agent داخلی، Qdrant، مدل محلی و `llama.cpp`، SSE، فرمت‌های دانش، توسعه لوکال، تست داده مصنوعی.
- **پیشنهاد اولیه قابل بازنگری:** انتخاب دقیق checkpoint/quantization مدل‌ها، پارامترهای Chunking، Retrieval، Reranking، نگهداری فایل‌ها و tuning.
- **وابسته به سازمان در زمان استقرار:** ارائه هویت معتبر کاربران، سیاست دسترسی واقعی، اتصال به داده عملیاتی، سیاست تصویب/اجرای تصمیم‌ها، ظرفیت و SLA نهایی.

---

## ۱. هدف و دامنه محصول

سرویس یک رابط مکالمه‌ای فارسی‌محور برای پرسش و پاسخ، تحلیل مسئله، بازیابی دانش، تولید پیشنهاد و اجرای **فرآیندهای تحلیلی Agentic** در بستر سازمان ارائه می‌کند. هسته مشترک از LLM محلی، RAG، حافظه مکالمه و ابزارهای کنترل‌شده Agent استفاده می‌کند.

**دامنه محصول:**

- نسخه عمومی برای کاربران مجاز عمومی، ازجمله خانواده کارکنان و سربازان.
- نسخه داخلی برای کارکنان و کاربران سازمان.
- **یک برنامه مشترک** برای هر دو گروه، با تفکیک منطقی داده و مجوز دسترسی.
- پشتیبانی از همه سناریوهای بخش ۳؛ تحویل ناقص صرفاً به‌خاطر محدودیت سخت‌افزار توسعه پذیرفته نیست. محدودیت سرعت و مقیاس محیط توسعه از دامنه قابلیت‌های محصول مستقل است.
- در زمان توسعه، ورودی‌ها و خروجی‌های واقعی با مجموعه داده آزمایشی جایگزین می‌شوند؛ قرارداد ورود داده سازمان باید مشخص، مستند و قابل اعتبارسنجی باشد.

**خارج از دامنه پیش‌فرض:** ساخت سامانه ثبت‌نام/ورود هویت سازمان، اتصال به سامانه‌های نامشخص خارجی بدون قرارداد، و اجرای مستقیم تغییرات حساس سازمانی بدون مجوز/Integration مشخص. این موارد مانع پیاده‌سازی کامل قابلیت‌های تحلیل و پیشنهاد نیستند.

---

## ۲. هسته مشترک چت‌بات — قابلیت‌های الزامی

| مؤلفه | مسئولیت اصلی | انتظار رفتاری |
|---|---|---|
| `Chat Management` | دریافت پیام، هماهنگی پاسخ | API مکالمه، تشخیص پیام جدید، پاسخ Streaming |
| `Conversation History` | Session و History | ایجاد/ادامه مکالمه، بازیابی تاریخچه، جداسازی مالکیت |
| `LLM Integration` | اجرای مدل محلی | `llama.cpp`، timeout، streaming، تعویض تنظیماتی مدل |
| `RAG` | بازیابی دانش قبل از پاسخ | جست‌وجوی مجاز، Reranking، استناد، مدیریت نبود شواهد |
| `Knowledge Management` | مدیریت چرخه دانش | Upload، Extraction، Chunking، Indexing، Versioning، وضعیت اسناد |
| `Scenario Routing` | انتخاب سناریو و مسیر پردازش | مسیر RAG/LLM/Agent، بدون اتکا به پیام برای تعیین مجوز |
| `Access Control` | تفکیک عمومی/داخلی | جلوگیری از دسترسی به داده و ابزار خارج از مجوز |
| `Feedback` | ثبت کیفیت پاسخ | امتیاز، گزارش پاسخ نادرست، اتصال Feedback به پیام/منبع |
| `External Integration` | آمادگی اتصال به داده/سرویس‌های سازمان | Adapterهای کنترل‌شده هنگام وجود قرارداد؛ **نه AI Agent خارجی** |

برای هر مؤلفه تست Unit و Integration متناسب با مسئولیتش باید وجود داشته باشد. مرز HTTP، Business، DB و Provider مطابق سند معماری رعایت می‌شود.

---

## ۳. سناریوهای کامل محصول

### ۳.۱. پاسخگویی به شبهات دینی (`religious_qa`)

**ورودی:** سؤال متنی فارسی و Context گفتگو.  
**منابع:** FAQ تأییدشده، پاسخ‌های کارشناسی، اسناد مرجع دارای منشأ.  
**رفتار:**

1. یافتن سؤال/پاسخ مرجع با تطبیق معتبر؛ شباهت Semantic به‌تنهایی برای هم‌ارزی قطعی کافی نیست.
2. در صورت وجود پاسخ تأییدشده و واقعاً منطبق، ارائه آن با مشخصات منبع.
3. در نبود تطبیق دقیق، اجرای RAG روی اسناد مجاز و تولید پاسخ مبتنی بر شواهد.
4. در نبود شواهد کافی، اعلام محدودیت پاسخ و ثبت وضعیت قابل پیگیری برای ارجاع احتمالی به کارشناس در استقرار سازمانی.
5. امکان ثبت پاسخ کارشناسی جدید و Reindex کردن دانش، بدون ادعای اینکه پاسخ تولیدی خودکار همان پاسخ تأییدشده است.

**خروجی:** پاسخ، منبع/استناد، نوع پاسخ (`verified_faq` / `rag_generated` / `insufficient_evidence`) و شناسه مکالمه.

### ۳.۲. معاونت نیروی انسانی (`human_resources`)

سه قابلیت مستقل و قابل آزمون:

**الف) تطبیق موقعیت شغلی با افراد (`personnel_matching`):** دریافت نیازمندی و معیارهای شغل، جست‌وجوی کارکنان مجاز، ارزیابی تناسب با شروط سخت/نرم، ارائه افراد پیشنهادی به‌همراه دلایل و محدودیت‌ها.

**ب) استعدادیابی:** دریافت مشخصات یک فرد، مهارت‌ها، تجربه و علایق/اهداف موجود؛ ارائه موقعیت‌های متناسب و توضیح تناسب.

**ج) نقل‌وانتقال درون‌سازمانی:** دریافت وضعیت فرد، نیاز واحدها، ظرفیت‌ها و محدودیت‌های قابل تنظیم؛ تولید پیشنهاد جابه‌جایی همراه با توجیه، تعارض‌ها و داده ناقص.

**نکات اجرایی:**

- LLM/Agent برای فهم درخواست، انتخاب Toolها و توضیح نتیجه استفاده می‌شود؛ محاسبه و اعمال معیارهای صریح باید در Service/Toolهای قابل تست صورت گیرد، نه به‌صورت حدس بدون داده.
- اطلاعات پرسنلی ساختاریافته و توضیحات متنی می‌توانند با هم استفاده شوند؛ بخش ساختاریافته از Repository و بخش دانشی از RAG بازیابی می‌شود.
- خروجی شامل `candidate_id`، عوامل تناسب و شواهد/قواعد به‌کاررفته است. امتیازدهی عددی تنها در صورت تعریف معیار و روش امتیازدهی معتبر شود.
- برای پیشگیری از توصیه‌های ناموجه، صفات حساس و داده‌های خارج از نیاز شغلی نباید در رتبه‌بندی وارد شوند.
- محصول **پیشنهاد** تولید می‌کند؛ تصمیم نهایی و سیاست اقدام سازمان در زمان استقرار تعریف می‌شود.

### ۳.۳. دفتر تحقیق و پژوهش (`research_advice`)

**ورودی:** مسئله یا چالش سازمانی.  
**منابع:** تجربیات ثبت‌شده، گزارش‌ها، مشکلات مشابه و نتایج قبلی.  
**رفتار:** بازیابی تجربیات مرتبط، مقایسه زمینه‌ها، استخراج راهکارهای ممکن، بیان مزایا/ریسک‌ها/پیش‌فرض‌ها و استناد به تجربیات.  
**خروجی:** راهکارهای قابل بررسی با استناد، عدم قطعیت و معیارهای ارزیابی اثرگذاری.

### ۳.۴. دستیار توسعه فردی کارکنان (`personal_development`)

**ورودی:** وضعیت شغلی، اهداف، مهارت‌ها، نیازهای آموزشی و اطلاعات مجاز فرد.  
**رفتار:** تحلیل شکاف مهارتی، پیشنهاد آموزش/مسیر رشد، ساخت برنامه قابل پیگیری و ارزیابی پیشرفت بر اساس داده جدید.  
**خروجی:** برنامه با اهداف، اقدامات پیشنهادی، زمان‌بندی قابل تنظیم و شاخص ارزیابی.

### ۳.۵. تفکیک و تخصیص وظایف سازمانی (`task_allocation`)

**ورودی:** برنامه جدید، اهداف، ساختار واحدها، ظرفیت‌ها، محدودیت‌ها و دستورالعمل‌ها.  
**رفتار:** استخراج فعالیت‌ها و وابستگی‌ها، تطبیق مسئولیت‌ها با واحدها، پیشنهاد تخصیص و مشخص‌کردن تعارض یا کمبود داده.  
**خروجی:** پیشنهاد تقسیم وظایف ساختاریافته، دلایل انتخاب و موارد نیازمند بررسی.

**قاعده مشترک سناریوها:** هیچ‌یک صرفاً یک Prompt ثابت با خروجی متن آزاد نیست؛ هر سناریو باید Validation، Service Logic، دسترسی به داده/ابزار موردنیاز، خروجی ساختاریافته قابل تست و پاسخ قابل فهم کاربر داشته باشد.

---

## ۴. تعریف دقیق Agent و مرزبندی آن با RAG

**تعریف مصوب:** AI Agent یک مؤلفه داخلی همین Python/FastAPI Application است که با LLM محلی، Tool Calling و Workflow چندمرحله‌ای مسائل پیچیده را پردازش می‌کند. این Agent به یک microservice مستقل تبدیل نمی‌شود.

```text
User
  ↓
ChatController  [HTTP + DTO + SSE]
  ↓
ChatService    [conversation orchestration]
  ↓
ScenarioRouterService
  ├── Direct LLM path (وقتی بازیابی/ابزار لازم نیست)
  ├── RagService (پاسخ مستند)
  └── AgentService (تحلیل چندمرحله‌ای + tool calling)
        ├── Personnel / Position lookup tools
        ├── Matching / Talent / Transfer analysis tools
        ├── Research / Document retrieval tools
        ├── Development planning tools
        └── Task allocation tools
  ↓
Local LLM provider (llama.cpp) / Authorized repositories / Qdrant
  ↓
Streaming answer + sources + structured results
```

**قواعد اجرای Agent:**

- Tool Registry با نام، توضیح، ورودی Pydantic و خروجی مشخص؛ فقط ابزارهای مجاز برای سناریو و هویت معتبر در دسترس باشند.
- اجرای Tool از مسیر Serviceهای موجود و constructor-injected dependencies باشد؛ Agent حق SQL خام، shell، فایل‌سیستم نامحدود یا فراخوانی HTTP دلخواه ندارد.
- سقف قابل تنظیم برای تعداد مراحل، تعداد Tool Call، timeout و اندازه Context اعمال شود؛ از حلقه بی‌نهایت جلوگیری شود.
- ورودی/خروجی Tool اعتبارسنجی و خطاها به‌شکل کنترل‌شده در Stream گزارش شوند.
- داده بازگشتی از اسناد یا Toolها **دستور سیستمی معتبر نیست**؛ باید در برابر Prompt Injection و دستورهای موجود در محتوای بازیابی‌شده مقاوم‌سازی انجام شود.
- رفتار Agent قابل مشاهده و قابل تست باشد: انتخاب ابزار، نتیجه ابزار، خطا، زمان اجرا و دلیل انتخاب مسیر، بدون ثبت محتوای محرمانه غیرضروری.
- در سناریوهای حساس، Agent خروجی مشورتی/تحلیلی می‌سازد؛ اجرای تغییر عملیاتی در سامانه سازمان صرفاً با مجوز و قرارداد مشخص فعال می‌شود. **وجود سیاست تأیید نهایی نباید توسعه قابلیت‌های پیشنهاددهی را متوقف کند.**

---

## ۵. معماری و ساختار کدنویسی

### ۵.۱. قواعد غیرقابل مذاکره از سند معماری

- مسیر لایه‌ها: `src/host/`، `src/application/`، `src/core/services/`، `src/infrastructure/`.
- Controller: `src/application/{feature}/{feature}_controller.py`، کلاس `{Feature}Controller` و متد `api() -> APIRouter`.
- WebService با توجه به `api.prefix` و نام پوشه Feature، Route را mount می‌کند؛ برای prefix مرجع `/api/v1`، مسیر `chat` با `/api/v1/chat` آغاز می‌شود.
- Serviceهای Async با پسوند `_async`، و بدون `HTTPException`، APIRouter یا status code.
- Repository برای Persistence و Query؛ برای CRUD معمول از `BaseRepository` استفاده شود.
- DTOهای Pydantic در `application/{feature}/dtos/` و SQLAlchemy Modelها در `infrastructure/models/`.
- Components دارای dependency با `@inject` و constructor injection؛ registration دستی برای Providerهای discoverable ممنوع.
- `PsqlDbContext`، `ConfigReader` و `VaultService` به‌صورت Singleton و Session برای هر عملیات Repository مستقل است.
- به‌هنگام Model جدید: Alembic import/metadata، migration و تست migration.
- از Interfaceهای غیرضروری، Domain/UseCases/CQRS/Hexagonal layer و DI framework جایگزین خودداری کن.
- Naming و `src.*` importها باید با Auto Discovery واقعی Repository سازگار باشند.

### ۵.۲. ساختار پیشنهادی؛ قابل تکمیل بر اساس کد موجود

> این Tree **تعهد ساخت یک فایل برای هر نام به‌صورت مکانیکی نیست**. قبل از ایجاد هر فایل، وجود، قرارداد و جایگزین واقعی آن در Repository بررسی شود. با اضافه‌شدن قابلیت، Tree و سند به‌روزرسانی گردد.

```text
src/
├── host/
│   ├── app.py
│   └── res/
│       ├── appsettings.yaml
│       └── appsettings.development.yaml
├── application/
│   ├── web.py
│   ├── chat/
│   │   ├── chat_controller.py
│   │   └── dtos/chat_dto.py
│   ├── conversation/
│   │   ├── conversation_controller.py
│   │   └── dtos/conversation_dto.py
│   ├── knowledge/
│   │   ├── knowledge_controller.py
│   │   └── dtos/knowledge_dto.py
│   └── feedback/
│       ├── feedback_controller.py
│       └── dtos/feedback_dto.py
├── core/
│   └── services/
│       ├── chat/chat_service.py
│       ├── conversation/conversation_service.py
│       ├── scenario_router/scenario_router_service.py
│       ├── llm/llm_service.py
│       ├── rag/rag_service.py
│       ├── knowledge/knowledge_service.py
│       ├── feedback/feedback_service.py
│       ├── agent/
│       │   ├── agent_service.py
│       │   └── tools/                   # ابزارهای دارای قرارداد مشخص
│       ├── religious_qa/religious_qa_service.py
│       ├── human_resources/human_resources_service.py
│       ├── personnel_matching/personnel_matching_service.py
│       ├── research_advice/research_advice_service.py
│       ├── personal_development/personal_development_service.py
│       └── task_allocation/task_allocation_service.py
└── infrastructure/
    ├── di/
    │   ├── inject.py
    │   ├── reflection.py
    │   └── bootstrap.py
    ├── context/sql_db/psql_dbcontext.py
    ├── models/
    │   ├── conversation.py
    │   ├── chat_message.py
    │   ├── knowledge_document.py
    │   ├── feedback.py
    │   ├── personnel.py
    │   ├── position.py
    │   ├── development_plan.py
    │   └── task_proposal.py
    ├── repositories/
    │   ├── base/base_repository.py
    │   ├── conversation/conversation_repository.py
    │   ├── chat_message/chat_message_repository.py
    │   ├── knowledge/knowledge_repository.py
    │   ├── feedback/feedback_repository.py
    │   ├── personnel/personnel_repository.py
    │   ├── position/position_repository.py
    │   ├── development_plan/development_plan_repository.py
    │   └── task_proposal/task_proposal_repository.py
    ├── providers/
    │   ├── llm/llama_cpp_provider.py
    │   ├── embedding/embedding_provider.py
    │   ├── reranking/reranking_provider.py
    │   ├── vector_db/qdrant_provider.py
    │   └── document/document_processor.py
    ├── alembic/
    └── scripts/run_migrations.py
```

**قاعده مهم:** پیاده‌سازی `AgentService` در Core است؛ `llama_cpp_provider.py` و Qdrant provider در Infrastructure قرار می‌گیرند. منطق سناریو داخل Service مربوط به خود و عملیات دیتابیس در Repository همان Feature باقی می‌ماند.

---

## ۶. تصمیم‌های فناوری

| موضوع | تصمیم | وضعیت |
|---|---|---|
| زبان/HTTP | `Python` + `FastAPI` | قطعی |
| ORM/DB عملیاتی | `SQLAlchemy Async` + `PostgreSQL` | قطعی |
| Vector database | `Qdrant`، **نه pgvector** | قطعی |
| Collectionهای اصلی | `knowledge_public` و `knowledge_internal` | قطعی |
| مدل‌های مولد | **محلی**، سروینگ با `llama.cpp` | قطعی |
| مدل اصلی کیفیت | `Qwen3-4B-Instruct-2507`، ترجیحاً GGUF Q4_K_M | انتخاب اولیه قابل جایگزینی |
| مدل سبک توسعه | `Qwen3-1.7B`، ترجیحاً GGUF Q4_K_M | انتخاب اولیه قابل جایگزینی |
| Embedding | `Qwen3-Embedding-0.6B` | انتخاب اولیه قابل جایگزینی |
| Reranking | `BGE-reranker-v2-m3` | انتخاب اولیه قابل جایگزینی |
| Retrieval | Hybrid Dense + Sparse / Keyword، سپس Reranking | استراتژی منتخب؛ Encoder دقیق آزمایش شود |
| Fusion | `RRF` به‌عنوان پیش‌فرض | قابل tuning |
| Memory | PostgreSQL History + پیام‌های اخیر + Summary | منتخب |
| Document Processing | `Docling` + ابزارهای لازم برای OCR/Word قدیمی | پیشنهاد اولیه |
| Document Storage | Local Filesystem با Volume پایدار | منتخب برای لوکال |
| API پاسخ | Streaming با `SSE` | قطعی |
| Local orchestration | `Docker Compose` | قطعی |
| Agent | Agentic Workflow **داخلی** با Tool Calling | قطعی |
| ورود/خروج داده | JSON، CSV، XLSX، PDF، TXT، DOC، DOCX | محدوده منتخب |
| Authentication | اتصال به Identity Provider سازمان در استقرار؛ پیاده‌سازی سامانه ورود خارج از دامنه | قطعی در سطح مسئولیت |

**توجه اجرایی درباره مدل‌ها:** انتخاب دقیق فایل GGUF، Template گفتگو، پشتیبانی Tool Calling، روش Serve کردن Embedding و Reranker، و کیفیت متن فارسی باید روی نسخه واقعی Runtime تست شود. نام مدل یا حجم فایل به‌تنهایی اثبات سازگاری و کارایی نیست. تعویض checkpoint/quantization/Provider endpoint نباید باعث تغییر Controller/Service اصلی شود.

### ۶.۱. اجرای LLM

- `llama.cpp` میزبان HTTP مدل مولد است؛ Integration در Infrastructure با Adapter دارای `@inject` و `httpx`/client مناسب انجام شود، اگر dependency واقعاً لازم است.
- Model endpoint، مسیر فایل، Context، Threads، timeout، Temperature و concurrency از Configuration خوانده شوند، نه Hardcode.
- اصل اول در محیط توسعه: CPU-only و حداقل مصرف منابع؛ در زمان ارتقای سخت‌افزار می‌توان تنظیمات را تغییر داد.
- برای Tool Calling، سازگاری Chat Template و خروجی ساختاریافته مدل باید در تست مستقل سنجیده شود. در صورت ضعف مدل سبک، مدل قوی‌تر/الگوی محدودتر استفاده شود.

### ۶.۲. Embedding / Reranking

- مدل Embedding باید روی فارسی (سؤال‌وجواب، متن اداری، متن تخصصی) با مجموعه ارزیابی آزمایش شود.
- ابعاد مرجع برای `Qwen3-Embedding-0.6B` در پیکربندی پیش‌فرض **۱۰۲۴** است؛ Dimension واقعی از خروجی Runtime تأیید و در Collection ثبت شود.
- تغییر مدل/ابعاد Embedding مستلزم ساخت Collection یا Index نسخه‌دار و Reindex کردن داده‌هاست؛ Vectorهای ناسازگار را در یک فضای هم‌نام مخلوط نکن.
- Reranker به‌شکل محدود و برای Top-K اسناد اجرا می‌شود؛ Backend سروینگ آن پس از بررسی سازگاری واقعی با Runtime انتخاب شود.
- روی سیستم ۱۶ GB بهتر است زمان اجرای Embedding/Indexing و LLM با کنترل concurrency مدیریت شود؛ همه مدل‌ها هم‌زمان بارگذاری نشوند مگر مصرف حافظه اندازه‌گیری شده باشد.

---

## ۷. ذخیره‌سازی، تفکیک داده و مجوزها

### ۷.۱. یک Deployment، دو Audience

- `public`: فقط به مکالمات متعلق به خود و دانش عمومی مجاز دسترسی دارد.
- `internal`: به داده‌های داخلی مرتبط با مجوزها و در صورت مجاز بودن دانش عمومی دسترسی دارد.
- مقدار `audience` در DTO یا Header درخواست به‌خودی‌خود هویت یا مجوز نیست؛ Scope معتبر باید از Authentication/Authorization Context سمت Server بیاید.
- در PostgreSQL همه رکوردهای وابسته به کاربر باید با شناسه مالک/tenant/audience مناسب محافظت شوند. Query بدون Scope معتبر در مسیر عملیاتی مجاز نیست.
- جداسازی منطقی Collection کافی نیست: اعتبارسنجی هویت و مجوز، Query Filtering و جلوگیری از Cross-collection Retrieval ضروری است.
- نسخه Local Demo تنها با **داده مصنوعی** و یک روش مشخص تست هویت اجرا می‌شود؛ این روش نباید به‌صورت پیش‌فرض در استقرار واقعی فعال بماند.
- در استقرار واقعی، سرویس تا دریافت Identity Context **قابل اعتبارسنجی** نباید اجازه دسترسی به منابع محرمانه بدهد (fail closed).

### ۷.۲. Collectionهای ثابت Qdrant

```text
knowledge_public
knowledge_internal
```

- دو Collection فوق تصمیم تأییدشده پروژه هستند.
- سند عمومی فقط در `knowledge_public`؛ سند داخلی فقط در `knowledge_internal` ایندکس شود.
- اسناد داخلی دارای سطح‌بندی ریزتر باید علاوه بر Collection، Metadata و فیلتر مجوز سمت Server داشته باشند.
- در جست‌وجوی داخلی، بازیابی ترکیبی از دو Collection **فقط در صورت مجوز** قابل انجام است؛ عمومی هرگز Internal را جست‌وجو نمی‌کند.
- هر Vector Payload باید به Document/Chunk در Metadata Store قابل ردیابی باشد.
- در صورت تغییر مدل Embedding، مهاجرت Index با Versioning و Cutover کنترل‌شده طراحی شود؛ نام‌های منطقی عمومی/داخلی برای مصرف‌کنندگان سرویس حفظ شوند.

### ۷.۳. ذخیره‌سازی عملیاتی

**PostgreSQL** برای مکالمات، پیام‌ها، اطلاعات سند، وضعیت Ingestion، Feedback، برنامه‌ها و داده‌های ساختاریافته سناریوها.  
**Qdrant** برای Vector Indexها و Payload بازیابی، نه جایگزین دیتابیس تراکنشی.  
**Filesystem/Volume** برای فایل خام، متن استخراج‌شده، فایل موقت و Export.

طرح اولیه Storage:

```text
storage/
├── documents/
│   ├── originals/
│   └── extracted/
├── generated/
├── temporary/
└── exports/
```

- از UUID/شناسه داخلی برای ذخیره فایل استفاده شود، نه نام فایل خام کاربر به‌عنوان مسیر.
- حجم و نوع فایل اعتبارسنجی شود؛ hash برای شناسایی تکرار، versioning و جلوگیری از overwrite ناخواسته ثبت گردد.
- حذف/ویرایش سند باید اثر آن روی Metadata و Vector Index را همگام و قابل ترمیم کند؛ عملیات چندسیستمی idempotent طراحی شوند.
- نسخه سازمانی می‌تواند بعداً از Object Storage استفاده کند، اما محل ذخیره نباید در Business Service هاردکد شود.

---

## ۸. استاندارد ورود دانش و RAG

### ۸.۱. فرمت‌های ورودی/خروجی

| نوع | فرمت | روش اولیه |
|---|---|---|
| سند و دستورالعمل | `.pdf` | `Docling` + OCR در صورت اسکن بودن |
| متن ساده | `.txt` | پردازش UTF-8 و تشخیص/گزارش Encoding نامعتبر |
| Word جدید | `.docx` | `Docling` یا Parser سازگار |
| Word قدیمی | `.doc` | تبدیل محلی کنترل‌شده، سپس استخراج |
| داده ساختاریافته | `.json` | Pydantic validation |
| داده جدولی | `.csv` | CSV parser با Encoding و Column validation |
| اکسل | `.xlsx` | `openpyxl` / import validation |
| خروجی گزارش | PDF، DOCX، TXT، JSON/CSV/XLSX در صورت نیاز | Export جداگانه با اعتبارسنجی دسترسی |

**نکته:** پشتیبانی از PDF اسکن‌شده شامل ارزیابی OCR فارسی و گزارش خطا یا کیفیت پایین استخراج است؛ متن نامعتبر نباید بی‌صدا Index شود.

### ۸.۲. Pipeline ورود سند

```text
Upload
  → Authentication / Audience authorization
  → File type / size / content validation
  → Safe persistent storage + SHA-256
  → Text / table extraction (+ OCR if needed)
  → Persian normalization
  → Structure-aware chunking + document/source location
  → Embedding
  → Qdrant upsert to authorized collection
  → Ingestion status + source/version metadata in PostgreSQL
```

**Metadata حداقلی:**

```json
{
  "document_id": "uuid",
  "title": "Document title",
  "source_type": "pdf",
  "category": "religious_qa",
  "audience": "public",
  "language": "fa",
  "version": 1,
  "status": "approved",
  "created_at": "2026-11-10T00:00:00Z"
}
```

فیلدهای ضروری دیگر در پیاده‌سازی: `source_uri` یا شناسه منبع، `checksum`، `uploaded_by`، `classification`، `page/section`, `chunk_id`, `embedding_model_version` و وضعیت پردازش. این JSON **نمونه قرارداد مفهومی** است، نه Schema نهایی SQLAlchemy یا Payload کامل Qdrant.

### ۸.۳. مقادیر شروع Retrieval (قابل تنظیم)

| پارامتر | مقدار شروع | توضیح |
|---|---|---|
| Max upload | `25 MB` | قابل تغییر؛ محدودیت برای Batch جداگانه |
| Chunk length | حدود `512 tokens` | رعایت مرز ساختار و پاراگراف |
| Overlap | حدود `64 tokens` | کاهش بریدگی مفهومی |
| Dense vector size | `1024` | باید با خروجی مدل سازگار باشد |
| First-stage retrieval | `20` | نتایج اولیه ترکیبی |
| After reranking | `5` | متن منتخب برای پاسخ |
| Fusion | `RRF` | ترکیب Dense/Sparse |
| Persian normalization | فعال | یکسان‌سازی حروف، فاصله/نیم‌فاصله، ارقام مطابق نیاز |
| Deduplication | `SHA-256` | در سطح فایل؛ Chunk dedup اختیاری و مستند |
| Citations | فعال | شناسه سند + موقعیت + نسخه در صورت امکان |

**مهم:** Dense Embedding به‌تنهایی Hybrid Search نیست. برای مسیر Sparse/Keyword باید Encoder/Index جداگانه مشخص و آزمایش شود؛ از سازگاری زبان فارسی، Query Fusion و نبود نشت دسترسی مطمئن شو. نوع دقیق Sparse Encoder را بعد از Evaluation تثبیت کن، نه از روی فرض.

### ۸.۴. مسیر پاسخ RAG

1. تعیین Scenario و Scope مجاز توسط Backend.
2. بازیابی FAQ معتبر/پرسش مشابه در صورت تناسب سناریو.
3. اجرای Dense + Sparse/Keyword Retrieval فقط روی منابع مجاز.
4. ادغام نتایج، Deduplication و Reranking.
5. انتخاب Context در محدوده Token Budget، با اطلاعات منشأ.
6. ساخت Prompt با تفکیک واضح متن کاربر، دستور سیستم و داده بازیابی‌شده.
7. تولید پاسخ Streaming و Citationها.
8. در صورت نبود شواهد کافی، اعلام محدودیت؛ از جعل منبع و پاسخ قطعی بی‌پشتوانه جلوگیری شود.
9. ثبت Trace/Metadata فنی با حداقل داده حساس.

**تمایز پاسخ‌ها:** `verified_faq`، `rag_generated`، `agent_generated` و `insufficient_evidence` باید قابل تشخیص باشند؛ پاسخ ساخته‌شده توسط LLM به‌صورت خودکار «تأیید کارشناسی» محسوب نمی‌شود.

---

### ۸.۵. قرارداد اجرایی مرحله ۵ (۲۰۲۶-۱۱-۱۱)

- مسیر مستقل مرحله ۵: ثبت Metadata، Upload محدود و مالک‌محور، ذخیره فایل با کلید داخلی، SHA-256، استخراج، نرمال‌سازی فارسی، Chunking ساختارمحور، Embedding محلی، Upsert در Qdrant و ثبت نسخه فعال در PostgreSQL. اتصال به SSE و Scenario Router در مرحله ۶ باقی می‌ماند.
- ورودی‌ها: PDF با استخراج صفحه و OCR محلی Tesseract، TXT/JSON/CSV با UTF-8 معتبر، DOC قدیمی با تبدیل LibreOffice در محیط محدود، DOCX و XLSX با Parser محلی. حجم اولیه ۲۵ مگابایت و محدودیت‌های صفحات، ردیف‌ها و بازکردن ZIP قابل تنظیم هستند.
- Embedding: Endpoint محلی سازگار با `/v1/embeddings`، مدل ابتدایی `Qwen3-Embedding-0.6B`، اعتبارسنجی Dimension و نسخه واقعی هنگام Indexing؛ بدون Embedding تصادفی در محیط عملیاتی.
- Vector Index: دو Collection منطقی `knowledge_public` و `knowledge_internal` با Dense Cosine نام‌دار `dense` و Sparse Lexical نام‌دار `lexical`. Sparse اولیه از هش پایدار اصطلاحات نرمال‌شده فارسی و وزن Term Frequency استفاده می‌کند؛ این روش BM25 نیست و نیاز به Benchmark فارسی دارد. ادغام با RRF و Reranking محلی مدل پیشنهادی `BGE-reranker-v2-m3` انجام می‌شود.
- امنیت: متادیتای مالکیت و Tenant از Identity مورداعتماد Backend استخراج می‌شود. Public هیچ‌گاه Collection داخلی را Query نمی‌کند. انتشار بین‌کاربری دانش عمومی نیازمند Permission مستقل `knowledge:publish` و تأیید وضعیت سند است. نتیجه Retrieval مجدداً با سند، نسخه فعال و Chunk ID در PostgreSQL تطبیق داده می‌شود.
- چرخه عمر: Claim اتمیک پردازش، فایل Pending برای Retry، خطای کنترل‌شده، Dedup در Scope مالک/Audience، Version Replacement، Reindex از نسخه ذخیره‌شده و غیرفعال‌سازی غیرمخرب نسخه قبلی. حذف دائمی و پاک‌سازی Collection بدون اجازه انجام نمی‌شود.
- مدل‌های محلی، OCR، حافظه و کیفیت Retrieval تا اجرای تست واقعی و Benchmark روی Windows تأییدشده محسوب نمی‌شوند؛ Stage 5 فقط با شواهد تمام معیارهای پذیرش `completed` می‌شود.
- جزئیات API، Migration، تست‌ها، راهنمای Windows و بازیابی در `docs/stage-5-ingestion-retrieval.md` ثبت می‌شوند.

---

## ۹. حافظه مکالمه و مدیریت Context

### وضعیت پیاده‌سازی مرحله ۴ (2026-11-11)

- Conversation و ChatMessage در PostgreSQL همراه با شناسه UUID متنی، مالک، Audience، ترتیب یکتای پیام‌ها و Timestamp نگهداری می‌شوند.
- ایجاد دو پیام هر Turn (User completed و Assistant streaming) در یک Transaction با قفل ردیف Conversation انجام می‌شود؛ پایان موفق، خطا و Cancellation وضعیت مستقل دارند.
- API تاریخچه و فهرست مکالمات تنها بر مبنای هویت معتبر سمت سرور، با Pagination و ترتیب قطعی Query می‌شوند.
- Summary خودکار مکالمه و سیاست حذف/Retention نهایی هنوز تصمیم قطعی ندارند؛ هیچ DELETE مخربی در مرحله ۴ ارائه نشده است.
- پاسخ‌های فعلی LLM تنها تعداد محدود پیام‌های completed قبلی را دریافت می‌کنند؛ پاسخ ناموفق یا نیمه‌کاره وارد Context پاسخ بعدی نمی‌شود.

## ۹. حافظه مکالمه و مدیریت Context

طرح منتخب: **PostgreSQL Persistent History + Short-term Context + Conversation Summary**.

- هر Conversation شناسه مستقل، شناسه صاحب/Scope، زمان ایجاد و آخرین فعالیت دارد.
- پیام‌ها با role و ordering صحیح ذخیره شوند؛ نتیجه ناقص Streaming باید وضعیت شفاف داشته باشد.
- برای هر درخواست فقط پیام‌های مرتبط اخیر در Context قرار گیرند؛ تاریخچه کامل در دیتابیس حفظ شود.
- برای مکالمات طولانی از Summary کنترل‌شده و نسخه‌دار استفاده شود؛ Summary جایگزین History اصلی نیست.
- Token Budget به‌صورت تفکیک‌شده برای دستورها، حافظه، RAG Context، Tool Result و خروجی محاسبه شود.
- درج/ویرایش/مشاهده مکالمه فقط با بررسی ownership و identity scope معتبر مجاز است.
- سیاست نگهداری/حذف داده و وضعیت پاک‌سازی در زمان استقرار باید قابل تنظیم و مستند باشد؛ زمان نگهداری ثابت و ساختگی تعیین نکن.

---

## ۱۰. API Contracts و Streaming

### ۱۰.۱. قرارداد Controller

تمام APIها با controller discovery سند معماری mount می‌شوند؛ نام Folder و فایل Controller نباید آزادانه تغییر کند. مثال‌ها **قرارداد پیشنهادی** هستند و پیش از کدنویسی در DTO/OpenAPI تثبیت می‌شوند.

| Feature | Endpoint نمونه | هدف |
|---|---|---|
| Chat | `POST /api/v1/chat/stream` | پاسخ SSE با Scenario Routing |
| Conversation | `POST /api/v1/conversation/` | ایجاد مکالمه |
| Conversation | `GET /api/v1/conversation/` | مکالمات مجاز کاربر |
| Conversation | `GET /api/v1/conversation/{id}` | تاریخچه یک مکالمه |
| Conversation | `DELETE /api/v1/conversation/{id}` | حذف با سیاست نگهداری/مجوز |
| Knowledge | `POST /api/v1/knowledge/` | ثبت/ورود سند |
| Knowledge | `GET /api/v1/knowledge/{id}` | وضعیت/Metadata سند |
| Feedback | `POST /api/v1/feedback/` | ثبت بازخورد پاسخ |

سناریوهای تخصصی می‌توانند از `ChatService` با Scenario مشخص استفاده کنند؛ Endpoint اختصاصی صرفاً زمانی ساخته شود که قرارداد ساختاریافته مستقلی لازم باشد. تعداد زیاد Controller به‌تنهایی هدف نیست.

### قرارداد تثبیت‌شده Stage 3 (2026-11-10)

- `POST /api/v1/chat/stream`: درخواست JSON دارای `message` (متن Trim‌شده، ۱ تا ۱۰۰۰ کاراکتر) و `conversation_id` اختیاری از نوع UUID؛ فیلد اضافی/هویت یا Audience ادعایی در Body پذیرفته نمی‌شود.
- در Stage 3 فقط درخواست مستقل یک‌پیامی پشتیبانی می‌شود. `conversation_id` غیرتهی پاسخ `409 CONVERSATION_UNAVAILABLE` دارد؛ `message_start.conversation_id=null` به‌معنای عدم وجود Conversation پایدار است. Replay/Idempotency، History، Ownership و Endpointهای CRUD مکالمه در Stage 4 به Persistence واقعی متصل می‌شوند؛ هیچ ID قابل ادامه یا State ساختگی ایجاد نمی‌شود.
- رویدادهای واقعی: `message_start`، `delta`های تدریجی از `llama.cpp`، `message_end` با `status=completed`؛ در خطای میانه Stream، `error` و سپس یک `message_end` با `status=failed`. روی Disconnect، Stream/HTTP upstream بسته و پایان ساختگی ارسال نمی‌شود. `request_id` و `message_id` UUIDهای سمت Server هستند.
- قرارداد DTO برای `sources` و Conversation تعریف شده ولی `sources`/Tool Events و Endpointهای Conversation تا اجرای واقعی RAG/History منتشر نمی‌شوند.
- خطای Validation دارای `error.code=VALIDATION_ERROR`، `request_id` و Field/Code بدون انعکاس Input است؛ خطای Authentication/Contract پیش از Stream با JSON و خطای LLM پس از Stream با SSE و پیام عمومی اعلام می‌شود. در نبود Model، پاسخ SSE خطا دارد و HTTP status دیگر قابل تغییر نیست.
- کنترل بار CPU با Semaphore اشتراکی در Provider (پیش‌فرض ۱ درخواست در هر Process)، پاسخ `LLM_BUSY` در Stream بدون صف نامحدود، محدودیت کاراکتر خروجی، حداکثر توکن و Timeout اعمال می‌شود.
- تنها هویت Local معتبر، Token محرمانه `CHATBOT_DEV_API_TOKEN` در `ENV_TYPE=development` با `auth.dev_enabled=true` است؛ Principal آزمایشی همیشه `public` و Synthetic است. Headerهای `X-Audience`/`X-User-ID` رد می‌شوند. Production تا افزودن Identity Provider معتبر، برای Chat همواره `401` (fail closed) می‌دهد؛ این مسیر Local جایگزین SSO نیست.
- `llama.cpp` از `POST /v1/chat/completions` با `stream=true` استفاده می‌کند؛ `model_name` اختیاری و برای single-model server خالی است. سازگاری Chat Template، کیفیت فارسی، TTFT و Cancel باید روی Build/Model واقعی Windows اندازه‌گیری شوند؛ بدون شواهد محلی تأییدشده نیستند.

### قرارداد اجرایی مرحله ۴

- `POST /api/v1/conversation/`، `GET /api/v1/conversation/`، `GET /api/v1/conversation/{conversation_id}` ایجاد و مشاهده‌ی دامنه مالک و تاریخچه Page‌بندی‌شده را فراهم می‌کنند.
- `POST /api/v1/chat/stream` اکنون Conversation جدید می‌سازد یا شناسه موجود را با Ownership بررسی می‌کند؛ شناسه‌ها در `message_start` واقعی هستند.
- `POST /api/v1/feedback/` روی پیام کامل دستیار، با `kind=positive|negative|incorrect`، یک رکورد به‌ازای هر کاربر/پیام ذخیره می‌کند؛ تکرار 409 است.
- `POST /api/v1/knowledge/` صرفاً Metadata را با وضعیت `registered` و `version=1` ثبت می‌کند. **هیچ فایل، Chunk، Vector یا وضعیت Index موفق ساخته نمی‌شود.**
- `GET /api/v1/knowledge/` و `GET /api/v1/knowledge/{document_id}` فقط اسناد متعلق به مالک و Audience معتبر او را باز می‌گردانند.
- `DELETE` مکالمه تا روشن شدن سیاست Retention سازمان ایجاد نشده است؛ اطلاعات موجود حذف نمی‌شود.
- مجوز توسعه صرفاً برای Principal مصنوعی `public` و Token محلی است؛ Production فاقد Provider احراز هویت سازمانی همواره fail closed باقی می‌ماند.
- Revision: `20261111_01`. راهنمای آزمون و اجرای امن: `docs/stage-4-persistence.md`.

### ۱۰.۲. SSE

- `Content-Type: text/event-stream`، Encoding UTF-8 و رعایت قواعد framing پیام‌های SSE.
- رویدادهای پیشنهادی: `message_start`، `delta`، `sources`، `tool_start`، `tool_result`، `message_end`، `error`.
- Eventهای `tool_result` باید به اطلاعات مورد نیاز نمایش محدود باشند؛ Prompt داخلی، داده خام حساس، tokenها و secretها افشا نشوند.
- پس از آغاز Stream، خطا دیگر الزاماً با HTTP status جدید قابل ارسال نیست؛ باید با رویداد `error` کنترل‌شده و وضعیت نهایی پیام گزارش شود.
- Cancellation/Disconnect باید تولید LLM، Toolها و مصرف منابع را تا حد امکان متوقف و وضعیت ذخیره پیام را سازگار کند. در Starlette/AnyIO، cleanup ذخیره وضعیت نهایی و بستن Generator باید در `CancelScope(shield=True)` انجام شود تا لغو Task جلوی commit وضعیت `cancelled` را نگیرد.
- Rate limit و concurrency limit برای مدل CPU-bound ضروری است؛ صف/Busy response مشخص و قابل تست باشد.
- استفاده از `async` نباید عملیات CPU-bound سنگین را روی Event Loop اصلی مسدود کند؛ پردازش اسناد و Inference با سرویس/worker یا Runtime مناسب انجام شود.

**نمونه مفهومی (صرفاً شکل پیام، نه قرارداد نهایی):**

```text
event: message_start
data: {"conversation_id":"...","message_id":"..."}

event: delta
data: {"text":"سلام"}

event: sources
data: {"documents":[{"document_id":"...","page":2}]}

event: message_end
data: {"status":"completed"}

```

- در Responseهای JSON و SSE، یک خطای ساختاریافته با شناسه پیگیری و بدون نشت Stack Trace تولید شود.
- قابلیت Replay/Resume Stream تنها در صورت نیاز صریح به قرارداد اضافه شود؛ از ابتدا وعده آن داده نشود.

---

## ۱۱. احراز هویت، محرمانگی و سیاست کنترل انسانی

### ۱۱.۱. مسئولیت این سرویس در هویت

سامانه ورود/SSO سازمان **خارج از دامنه توسعه** است. اما API نباید بدون احراز هویت معتبر فرض کند کاربر داخلی است. قرارداد Integration باید قابلیت دریافت/اعتبارسنجی Claims معتبر (هویت، Audience، Permission، Tenant در صورت وجود) را فراهم کند. برای Local Test، هویت نمایشی فقط در تنظیمات Development و با داده مصنوعی قابل فعال‌سازی است.

### ۱۱.۲. الزامات امنیتی

- جداسازی داده عمومی/داخلی در Collection، Query، Context و پاسخ.
- جلوگیری از IDOR در Conversation، Document و Feedback.
- جلوگیری از Prompt Injection و دستورهای مخربِ داخل PDF، متن و Tool Result.
- محدودکردن Tool Calling به allowlist و schema مشخص.
- محافظت در برابر Upload مخرب، Path Traversal، فایل بسیار بزرگ، Zip Bomb یا محتوای ناسازگار.
- عدم ذخیره/نمایش Secret و اطلاعات حساس در Log، Prompt Trace یا خطا.
- محدودکردن دسترسی Network/Volume به Qdrant، PostgreSQL و LLM Server؛ برای استقرار واقعی تنظیمات TLS/Authentication و Secret Management باید مطابق سیاست سازمان اعمال شوند.
- در صورت فعال نبودن Provider هویت مورد اعتماد در Production، دسترسی به دانش داخلی باید fail closed باشد.

### ۱۱.۳. کنترل انسانی؛ تصمیم کاربر

- **توسعه پروژه نباید برای تعیین سیاست تصویب نهایی سازمان متوقف شود.** تمام قابلیت‌های تحلیل، پیشنهاد، گزارش و سناریوها پیاده‌سازی و با داده آزمایشی تست می‌شوند.
- درباره تأیید انسانی، نقش تصمیم‌گیر، گردش تصویب و اختیار اعمال تغییر، سازمان هنگام تحویل سیاست‌گذاری می‌کند.
- برای سازگاری آینده، نقطه اتصال Policy/Approval قابل تنظیم باقی می‌ماند؛ در حالت توسعه قابلیت پیشنهاد دادن کامل فعال است.
- عملیات تغییر واقعی وضعیت کارکنان، انتقال افراد یا تغییر مسئولیت در سیستم عملیاتی تا دریافت قرارداد و مجوز معتبر اجرا نمی‌شوند؛ این محدودیت مانع تولید پیشنهاد قابل ارزیابی نیست.
- هیچ Workflow Approval اجباری و ثابت برای هر پیام یا تحلیل بدون درخواست صریح کاربر پیاده‌سازی نشود.

---

## ۱۲. پیکربندی خاص سیستم توسعه محلی

### ۱۲.۱. مشخصات گزارش‌شده سیستم کاربر

| منبع | مقدار |
|---|---|
| OS | `Windows 11 Pro`, 64-bit |
| CPU | `Intel Core i7-6700 @ 3.40 GHz` |
| CPU cores/threads | `4 cores / 8 logical processors` |
| RAM | `15.88 GB` |
| GPU شناسایی‌شده | `Intel HD Graphics 530` |
| NVIDIA CUDA | `nvidia-smi` در PATH وجود ندارد؛ GPU NVIDIA شناسایی نشده |
| Docker CLI | `29.7.2` |
| Docker Compose CLI | `v5.5.1` |
| Disk `C:` | حدود `9.06 GB` فضای آزاد |
| Disk `D:` | حدود `451.70 GB` فضای آزاد |
| Disk `E:` | حدود `213.74 GB` فضای آزاد |
| Disk `F:` | حدود `151.49 GB` فضای آزاد |

**محدودیت‌های فعلاً بررسی‌نشده:** سلامت Docker Engine، وضعیت WSL2، SSD/HDD بودن دیسک‌های مقصد، سرعت واقعی مدل، وضعیت CPU virtualization، اندازه فضای فعلی Docker disk image. نتیجه این موارد حدس زده نشود.

### ۱۲.۲. روش اجرای پیشنهادی در توسعه

```text
Windows Host
├── llama.cpp (CPU-only; native Windows)
│   └── local LLM HTTP endpoint
├── local Embedding / Reranking runtime (محدود و قابل زمان‌بندی)
└── Docker Compose
    ├── FastAPI service
    ├── PostgreSQL
    └── Qdrant
```

- `llama.cpp` روی Windows به‌صورت CPU-only اجرا شود تا ابتدا سربار و پیچیدگی GPU/Container کاهش یابد.
- FastAPI داخل Docker برای ارتباط با LLM روی Host از آدرس/Network قابل حل برای Container استفاده کند؛ از `localhost` داخل Container برای Host استفاده نکند. در Docker Desktop ویندوز غالباً `host.docker.internal` قابل استفاده است؛ در محیط واقعی صحت آن تست شود.
- Model فایل‌ها، Storage و Volumeهای Docker ترجیحاً روی `D:` قرار گیرند. به‌دلیل فضای بسیار کم `C:`، مسیر Docker disk image باید در تنظیمات رسمی Docker Desktop بررسی و در صورت نیاز از روش پشتیبانی‌شده جابه‌جا شود؛ **فایل‌های WSL/Docker را دستی و بدون Backup منتقل نکن**.
- محل پیشنهادی کد `D:\\chatbot-service-llm` و Storage/Model نیز زیر `D:` است؛ این فقط پیشنهاد و نه مسیر موجود یا الزام پروژه است.
- Compose برای نسخه سازمانی می‌تواند Containerهای دیگری داشته باشد؛ طرح فعلی محدودیت سخت‌افزار توسعه را در نظر دارد.

### ۱۲.۳. تنظیمات اولیه llama.cpp برای Benchmark

| گزینه | مقدار شروع | وضعیت |
|---|---|---|
| Runtime | `llama.cpp` | قطعی |
| Device | CPU-only | مبتنی بر سخت‌افزار کنونی |
| Initial model | `Qwen3-1.7B GGUF Q4_K_M` | سبک برای Iteration |
| Quality candidate | `Qwen3-4B-Instruct-2507 GGUF Q4_K_M` | مقایسه کیفیت |
| `--threads` | `4` | قابل tuning |
| `--ctx-size` | `2048` | قابل tuning؛ محدودیت برای Agent/RAG |
| `--parallel` | `1` | جلوگیری از فشار هم‌زمان |
| `--n-gpu-layers` | `0` | بدون Offload |
| SSE | فعال در API خودمان | قطعی |

- Context Size در این سیستم صرفاً نقطه شروع است؛ Agentهای چندمرحله‌ای و RAG ممکن است Context بیشتر بخواهند. باید با Memory Budget، truncation و benchmark تنظیم شوند؛ `2048` به‌عنوان استاندارد دائمی محصول تلقی نشود.
- سرعت تولید Token، زمان اولین Token، RAM Peak، زمان Retrieval/Reranking و پاسخ صحیح فارسی اندازه‌گیری شوند.
- در توسعه ممکن است پردازش Ingestion، Reranker و LLM به‌صورت نوبتی اجرا شود تا فشار RAM کنترل شود.
- همه قابلیت‌ها باید قابل توسعه/تست باشند؛ کندبودن تست محلی با «کامل بودن قابلیت نرم‌افزاری» متفاوت است.

---

### ۱۲.۴. تصمیم‌های اجرایی مرحله ۲ (توسعه محلی)

- Compose شامل FastAPI، PostgreSQL 16.15 و Qdrant 1.20.0 با healthcheck و شبکه Bridge است.
- `llama.cpp` روی Windows Host و مستقل از چرخه راه‌اندازی API باقی می‌ماند؛ آدرس Container قابل تنظیم است و اتصال زنده باید در Windows آزمون شود.
- PostgreSQL و Qdrant از Named Volume مستقل استفاده می‌کنند؛ Storage فایل‌های برنامه از Bind Mount قابل تنظیم استفاده می‌کند. محل Docker Disk Image در Docker Desktop باید پیش از دانلود کنترل شود.
- Portهای منتشرشده فقط روی `127.0.0.1` Host قرار می‌گیرند؛ این استقرار صرفاً Development با داده ساختگی است، نه الگوی امن Production.
- رمز عبور دیتابیس از Environment خوانده می‌شود؛ پیکربندی Production بدون تنظیم معتبر Database/LLM/Vector به‌طور پیش‌فرض فاقد URL است.
- Readiness سرویس‌های پایگاه داده و Qdrant در Healthcheck و ابزار تست درون Container بررسی می‌شود؛ مسیر `/api/v1/health` فقط Liveness API است.
- ساخت Collection در Qdrant تا تأیید خروجی و ابعاد واقعی Embedding به تعویق می‌افتد؛ نام منطقی `knowledge_public` و `knowledge_internal` ثابت است.
- برای رفع مشکلات Timeout دانلود Python Package در Docker محلی، `CHATBOT_PIP_INDEX_URL` امکان انتخاب اختیاری Mirror ران‌فلر در زمان Build را می‌دهد؛ PyPI رسمی پیش‌فرض Dockerfile و CI است و TLS Verification غیرفعال نمی‌شود.
- Shell Script راه‌اندازی Container با `LF` اجرا می‌شود؛ `.gitattributes` از تبدیل خط در Git Checkout پیشگیری می‌کند و Dockerfile در زمان Build فایل را در صورت وجود `CRLF` نرمال می‌کند.
- جزئیات اجرای مرحله ۲، تست‌های Windows و هشدارهای امنیتی در `docs/stage-2-infrastructure.md` نگهداری می‌شود.

---

## ۱۳. پیکربندی و نگهداری Secretها

- مطابق راهنمای معماری، تنظیمات داخل `src/host/res/appsettings.yaml` و `appsettings.development.yaml` نگهداری و از `ConfigReader` خوانده شوند.
- مسیر مدل، نام Collection، timeoutها، Context/Threads، پارامترهای RAG، سطح Log و مسیر Storage در Config قابل تغییر باشند.
- رمز عبور، توکن، connection secret یا اطلاعات واقعی پرسنل در فایل commit‌شده Hardcode نشود.
- تنظیمات Local Demo و Production به‌وضوح جدا شوند؛ Demo Identity یا Policy تست در Production مجاز نیست.
- نام متغیرها و Config Keyهای نهایی را با قرارداد واقعی `ConfigReader` موجود هماهنگ کن. از معرفی متدهای ناموجود به‌عنوان API واقعی بپرهیز.

**نمونه *مفهومی* (نه Config نهایی):**

```yaml
api:
  prefix: "/api/v1"
llm:
  provider: "llama_cpp"
  model_profile: "development_light"
  context_size: 2048
  parallel: 1
rag:
  retrieval_limit: 20
  rerank_limit: 5
vector:
  provider: "qdrant"
  public_collection: "knowledge_public"
  internal_collection: "knowledge_internal"
storage:
  provider: "filesystem"
```

---

## ۱۴. داده آزمایشی و قرارداد ورود داده سازمان

در طول توسعه از **Fixtureهای کاملاً ساختگی** استفاده می‌شود؛ هیچ فرد واقعی یا داده محرمانه لازم نیست.

| سناریو | Fixture لازم | سنجه کلیدی پذیرش |
|---|---|---|
| Religious QA | FAQ و متن مرجع نمونه | پاسخ مستند؛ رفتار درست در نبود منبع |
| Job matching | افراد مصنوعی + نیاز شغل | رعایت شروط سخت، رتبه‌بندی قابل توضیح |
| Talent discovery | پروفایل مصنوعی + مشاغل | پیشنهاد سمت مناسب با دلیل |
| Transfers | افراد + واحدها + ظرفیت‌ها | شناسایی محدودیت ظرفیت/ناسازگاری |
| Research advice | مسئله + تجربه و گزارش گذشته | استناد به تجربه مشابه و تحلیل تفاوت |
| Personal development | فرد + مهارت‌ها + آموزش‌ها | برنامه توسعه با شاخص ارزیابی |
| Task allocation | ساختار سازمان + برنامه + وظایف | پیشنهاد تخصیص با محدودیت‌های روشن |

قرارداد Import واقعی باید برای هر جدول/مدل مشخص کند: نوع داده، نام و الزام فیلدها، کلید پایدار، Encoding، مقدار مجاز، سطح دسترسی، سازوکار به‌روزرسانی/حذف، مرجع صحت و پیام خطای Validation.

- داده ساختگی باید Caseهای مثبت، منفی، ناقص، متناقض، تکراری و Cross-audience را پوشش دهد.
- برای تست RAG، یک مجموعه سؤال با پاسخ/منبع مرجع و اسناد عمداً نامرتبط ساخته شود.
- ابزار Import داده واقعی در تحویل سازمان قابل استفاده باشد، نه اینکه منطق تحلیل به Fixtureها وابسته شود.
- Fixtureها reproducible باشند؛ Migration و Seed داده‌های تست از Production Data جدا بمانند.

---

## ۱۵. کیفیت، تست، مانیتورینگ و خطا

### ۱۵.۱. تست‌های الزامی

1. Unit Test: Serviceها، Matching/Rules، Agent Tool Schema، Policy و Scenario Router.
2. Integration Test: PostgreSQL Repositories، Alembic، Qdrant، Ingestion، Retrieval و Provider LLM (با mock مناسب + حداقل تست واقعی محلی).
3. API Test: Controller Discovery، validation، status code، SSE framing، error event و cancellation.
4. Security Test: public→internal document retrieval، IDOR، دسترسی Tool غیرمجاز، جعل audience و Prompt Injection.
5. RAG Evaluation: پاسخ مستند، Citation Precision، وجود منبع، رفتار نبود شواهد، Retrieval hit و فارسی.
6. Agent Evaluation: انتخاب ابزار، محدودیت مراحل، جلوگیری از تکرار بی‌پایان، پاسخ ساختاریافته و handling خطا.
7. Scenario Acceptance: همه ۷ زیرفرآیند جدول داده آزمایشی باید End-to-End قابل اجرا باشند.
8. Performance/Resource: TTFT، token/s، Latency بازیابی، حافظه Peak، Load در concurrency=1 و رفتار در فشار منابع.

### ۱۵.۲. مشاهده‌پذیری

- Correlation/Request ID برای پیام‌ها، رویدادها و خطاها.
- Logging ساختاریافته با حذف Secret و حداقل‌سازی داده شخصی.
- ثبت زمان پاسخ LLM، Retrieval، Reranking و Agent Toolها.
- Health Check برای API، دیتابیس، Qdrant و وضعیت وابستگی LLM؛ عدم دسترس‌بودن مدل باید خطای کنترل‌شده داشته باشد.
- Migrationها و پیکربندی مدل/Index با Version ثبت شوند تا قابل عیب‌یابی باشند.

### ۱۵.۳. اصول پیاده‌سازی

- قبل از تغییر Repository موجود، کد و وابستگی واقعی را بخوان؛ API/Function/Schema ساختگی نساز.
- از Transaction مناسب، Idempotency و سازگاری بین PostgreSQL و Qdrant برای ورود سند استفاده شود؛ تراکنش سراسری فرض نشود.
- در Failover ساده، عملیات ناتمام قابل Retry یا Recovery باشند.
- برای Streaming، timeout و Backpressure مدیریت شود؛ Close/Disconnect منابع را رها کند.
- برای Queryهای پرحجم Pagination/Filter و Index مناسب در نظر گرفته شود.
- بدون نیاز واقعی Framework Agent/DI جدید وارد نکن؛ اجرای Agent می‌تواند داخل Serviceهای خودمان باشد.

---

## ۱۶. ترتیب اجرایی کار؛ بدون فازبندی محصول

**توافق قطعی:** کل پروژه باید پیاده‌سازی شود؛ بخش‌های زیر فقط **ترتیب وابستگی فنی کارها** هستند، نه تفکیک تحویل یا حذف سناریوها.

1. بررسی فایل‌های واقعی پروژه و اعتبارسنجی DI، Controller Discovery، DB Context، BaseRepository، Alembic.
2. آماده‌سازی Compose، PostgreSQL، Qdrant، Storage و اتصال `llama.cpp` محلی.
3. تعریف و اجرای Contractهای DTO، Conversation و SSE؛ تست پاسخ مدل سبک.
4. ایجاد Model/Repository/Serviceهای History، Feedback و Knowledge همراه Migration.
5. تکمیل Pipeline اسناد (PDF/TXT/DOC/DOCX/JSON/CSV/XLSX)، Qdrant و Hybrid Retrieval + Reranking.
6. اتصال Chat به Scenario Router و RAG؛ تست مستند بودن پاسخ‌ها و Isolation.
7. پیاده‌سازی AgentService و Toolهای محدود، قابل تست و schema-based.
8. تکمیل تمام سناریوها: Religious QA، سه کاربرد HR، Research، Personal Development و Task Allocation.
9. تکمیل Seed آزمایشی، API/Integration/Security/E2E Tests، Benchmark و مستندات نصب/تحویل.
10. آماده‌سازی Configuration/Adapterهای لازم برای ورود داده واقعی سازمان و Policyهای استقرار، بدون وابستگی به داده محرمانه واقعی در توسعه.

اگر در حین اجرای این ترتیب، ماژول جدیدی لازم شد، فقط مطابق سند معماری اضافه شود و **این سند** با تصمیم‌های تأییدشده کاربر همگام گردد.

---

## ۱۷. معیارهای پذیرش نهایی پروژه

- [ ] تمام مؤلفه‌های ۹گانه هسته مشترک بخش ۲ اجرا و تست شده‌اند.
- [ ] تمام پنج حوزه کاربردی و هر سه کاربرد منابع انسانی End-to-End با داده مصنوعی کار می‌کنند.
- [ ] مدل مولد کاملاً محلی و از طریق `llama.cpp` قابل استفاده است؛ حداقل یک مدل سبک عملیاتی تست شده است.
- [ ] Embedding و Reranking محلی هستند و نسخه‌های قابل تعویض/تنظیم دارند.
- [ ] RAG با Qdrant و دو Collection `knowledge_public` / `knowledge_internal` کار می‌کند.
- [ ] کاربر عمومی هیچ دسترسی API/RAG/Agent به اطلاعات داخلی ندارد.
- [ ] مستندات/اسناد PDF، TXT، DOC و DOCX و داده‌های JSON، CSV و XLSX وارد و اعتبارسنجی می‌شوند.
- [ ] Ingestion، Metadata، Versioning، Citation و حذف/به‌روزرسانی Index رفتار قابل تست دارند.
- [ ] Hybrid Retrieval و Reranking روی مجموعه فارسی ارزیابی شده‌اند.
- [ ] پاسخ Chat با SSE Stream می‌شود و Eventهای success/error/cancellation پوشش دارند.
- [ ] Agent ابزارها را در همان برنامه به‌صورت مجاز، محدود و قابل مشاهده فراخوانی می‌کند.
- [ ] History/Memory در PostgreSQL ذخیره می‌شود و Ownership Enforcement دارد.
- [ ] Docker Compose سرویس‌های زیرساخت را در محیط محلی اجرا می‌کند و به Runtime مدل محلی وصل می‌شود.
- [ ] مسیر نصب/Run روی Windows توسعه و تنظیمات جایگزین استقرار مستند شده‌اند.
- [ ] Unit/Integration/API/Security/Scenario Tests و Alembic migrationهای لازم وجود دارند.
- [ ] هیچ Interface، لایه اضافی یا Provider Registration مغایر سند معماری ایجاد نشده است.
- [ ] همه کلاس‌ها و مسیرهای Controller/Service/Repository با Auto Discovery موجود سازگارند.
- [ ] قابلیت تحلیل و پیشنهاد، بدون الزام سیاست تصویب نهایی سازمان، قابل تحویل و آزمون است؛ اقدام واقعی حساس بدون Permission/Integration معتبر فعال نیست.
- [ ] فایل‌ها و تنظیمات توسعه به Credential، داده واقعی یا سرویس ابری پیش‌فرض وابسته نیستند.

**معیار مهم تحویل:** وجود Endpoint یا خروجی Dummy به‌تنهایی پیاده‌سازی کامل نیست. رفتارهای واقعی هر سناریو باید با Fixtureها قابل تکرار و تست باشند. اگر کیفیت مدل سبک کافی نبود، نتیجه Evaluation و جایگزین پیشنهادی ثبت شود؛ این وضعیت نباید با ادعای دقت تأییدنشده پوشانده شود.

---

## ۱۸. موضوعات باز و روش تصمیم‌گیری

این موارد **عمداً نهایی نشده‌اند** و نباید در کدنویسی بدون آزمون قطعی فرض شوند:

| موضوع باز | روش تعیین |
|---|---|
| سلامت Docker Engine و وضعیت WSL2 | اجرای `docker info` و `wsl --status` روی سیستم کاربر |
| SSD/HDD بودن محل Storage | بررسی `Get-PhysicalDisk` و تست I/O در صورت لزوم |
| مدل GGUF دقیق و Chat Template | اجرای نمونه، بررسی توکن‌سازی فارسی و Tool Calling |
| سرعت واقعی LLM | Benchmark روی i7-6700 / 16GB |
| روش Serve کردن Embedding/Reranker | تست سازگاری Runtime/مدل و مصرف حافظه |
| Sparse Encoder برای Hybrid | Evaluation فارسی و مقایسه نتایج Dense-only / Hybrid |
| محدودیت عملی تعداد سند/کاربر | تست بار با داده آزمایشی و منابع موجود |
| Schema واقعی HR/ساختار سازمانی | تعیین قرارداد Import با داده مصنوعی؛ تطبیق نهایی با سازمان |
| Claims و سیاست Access سازمان | قرارداد Identity Provider سازمان هنگام تحویل |
| Approval/Workflow واقعی | سیاست سازمان در زمان استقرار؛ **مانع توسعه پیشنهادها نیست** |
| مجوز استفاده/بازتوزیع مدل و ابزار | بررسی License نسخه دقیق پیش از بسته‌بندی و تحویل |
| معیار SLA/Latency تولید | Benchmark و الزامات واقعی محیط سازمان |

---

## ۱۹. قالب ثبت تصمیم‌های جدید (Decision Log)

برای جلوگیری از فراموش‌شدن توافق‌ها، هر تصمیم بعدی باید به این جدول اضافه و در بخش مرتبط اعمال شود.

| تاریخ | موضوع | تصمیم | وضعیت |
|---|---|---|---|
| 2026-11-10 | مرجع معماری | `Service_Architecture_Guide_FA.md` | قطعی |
| 2026-11-10 | دامنه پروژه | پیاده‌سازی تمام سناریوها، بدون تقسیم تحویل به فازهای مستقل | قطعی |
| 2026-11-10 | Deployment | یک FastAPI مشترک برای Public + Internal | قطعی |
| 2026-11-10 | Agent | Agentic LLM داخلی، نه سرویس خارجی مجزا | قطعی |
| 2026-11-10 | Vector DB | Qdrant، دو Collection عمومی/داخلی | قطعی |
| 2026-11-10 | LLM | محلی با `llama.cpp`؛ شروع با Qwen3-1.7B و مقایسه 4B | انتخاب مدل اولیه |
| 2026-11-10 | Embedding/Reranking | Qwen3-Embedding-0.6B / BGE-reranker-v2-m3 | انتخاب اولیه |
| 2026-11-10 | Retrieval | Hybrid + RRF + Reranking + Source Citation | منتخب |
| 2026-11-10 | Streaming | SSE | قطعی |
| 2026-11-10 | Storage/DB | PostgreSQL + Qdrant + Local Filesystem | منتخب |
| 2026-11-10 | Dev Environment | Windows 11، CPU-only، 16GB، Docker Compose | قطعی بر اساس سخت‌افزار گزارش‌شده |
| 2026-11-10 | تست داده‌ها | Fixtureهای ساختگی و قرارداد Import برای داده واقعی سازمان | قطعی |
| 2026-11-10 | Authentication/Approval | SSO و سیاست تصویب نهایی متعلق به سازمان؛ اتصال امن و تحلیل قابل تحویل | قطعی در حد مسئولیت |
| 2026-11-11 | Stage 4 Persistence | UUID متنی، ترتیب اتمیک Turn، Streaming status و History با Ownership و Audience در PostgreSQL | پیاده‌سازی مرحله ۴ |
| 2026-11-11 | Stage 4 SSE disconnect cleanup | محافظت از commit وضعیت `cancelled` و بستن LLM generator با AnyIO shield در لغو ASGI Task؛ تست واقعی disconnect در ASGI | اصلاح رگرسیون مرحله ۴؛ نیازمند تأیید Windows |
| 2026-11-11 | Feedback | تنها پیام completed متعلق به مالک؛ یک بازخورد برای هر actor/message؛ تکرار HTTP 409 | پیاده‌سازی مرحله ۴ |
| 2026-11-11 | Knowledge Metadata | ثبت Metadata بدون Upload/Indexing؛ وضعیت registered، نسخه ۱، دسترسی محدود به مالک و Audience | مرز مرحله ۴/۵ |
| 2026-11-11 | Conversation Deletion | تا تعیین سیاست Retention، Endpoint حذف فعال نمی‌شود | تصمیم ایمن موقت |
| 2026-11-10 | Stage 2 local infrastructure | Compose سه‌سرویسی، PostgreSQL 16.15، Qdrant 1.20.0، Storage جدا، Local llama.cpp و Health Check مستقل از Liveness | تصمیم اجرایی Development؛ اعتبارسنجی Windows باز |
| 2026-11-10 | Stage 2 development credentials | آماده‌سازی idempotent و CRLF-safe فایل `.env`، حفظ Secret موجود و عدم نمایش Credential در خروجی | اصلاح راه‌اندازی Development |
| 2026-11-10 | Stage 2 PyPI mirror | انتخاب اختیاری Mirror ران‌فلر برای Docker Build محلی از طریق Build ARG، پیش‌فرض PyPI رسمی در CI و حفظ TLS | تصمیم اجرایی Development؛ آزمون Windows باز |
| 2026-11-10 | Stage 2 shell line endings | پیشگیری از CRLF در `entrypoint.sh` هنگام Windows Checkout و نرمال‌سازی دفاعی در Docker Build، با CI شبیه‌ساز CRLF | رفع Crash مرحله ۲؛ اعتبارسنجی محلی باز |
| 2026-11-10 | Stage 3 Chat/SSE/Identity | One-shot bounded SSE over local llama.cpp; no fake conversation persistence; synthetic public Bearer token only in Development; Production fail-closed; concurrency=1 | تصمیم اجرایی Stage 3؛ تست واقعی Windows باز |
| 2026-11-11 | Stage 3 Windows validation and LLM readiness | Tolerate pre-existing CRLF in Windows worktrees while verifying Docker normalization; use PS 5.1-compatible fail-fast SSE smoke script; report allowlisted LLM readiness causes without secrets | اصلاح خطاهای تأیید محلی Stage 3؛ اتصال واقعی Windows باز |
| 2026-11-11 | Stage 3 Qwen3 non-thinking output | Start local Qwen3 with `--reasoning off` (if supported) and request per-call `chat_template_kwargs.enable_thinking=false` by validated YAML config; keep reasoning out of SSE; do not raise CPU token budget to mask empty output | رفع ریشه‌ای پیشنهادی؛ تست موفق واقعی Windows باز |
| 2026-11-11 | Stage 3 Windows PowerShell Unicode source | Ensure ANSI-codepage-safe `.ps1` source by using ASCII-only JSON Unicode escapes for Persian prompt; add exact prompt regression and CI check; do not alter production SSE decoding without evidence | رفع مشکل درخواست فارسی در PowerShell 5.1؛ آزمون دوباره خروجی مدل روی Windows باز |

| 2026-11-11 | Stage 5 ingestion | Parser محلی هفت فرمت، OCR/LibreOffice، Storage پایدار با UUID، SHA-256، نسخه و Retry؛ عدم انتشار تا Index موفق | پیاده‌سازی اولیه؛ تأیید Windows باز |
| 2026-11-11 | Stage 5 retrieval | Dense + Lexical sparse با Qdrant named vectors، Fusion از نوع RRF، Reranking محلی، بررسی Visibility/Version مجدد در PostgreSQL | پیاده‌سازی اولیه؛ Benchmark فارسی باز |
| 2026-11-11 | Stage 5 knowledge access | Metadata مالک‌محور مرحله ۴ حفظ شد؛ انتشار دانش Public نیازمند Permission مستقل و Internal بر اساس Tenant/Permission تفکیک می‌شود | قرارداد امنیتی Stage 5 |

---

## ۲۰. دستور آماده برای استفاده در گفتگوهای آینده

```text
دو فایل مرجع این پروژه را مبنا قرار بده:
1) Service_Architecture_Guide_FA.md: استاندارد الزام‌آور معماری و کدنویسی.
2) Chatbot_Service_Implementation_Guide_FA.md: نیازمندی‌ها، فناوری‌های منتخب و معیارهای پذیرش چت‌بات.

تمام Featureها را در یک FastAPI مشترک برای Public/Internal با Constructor DI و @inject توسعه بده.
AI Agent باید Workflow داخلی مبتنی بر LLM/Tool Calling باشد، نه سرویس مستقل.
LLM، Embedding و Reranking محلی، Runtime اصلی llama.cpp، Vector DB برابر Qdrant
با Collectionهای knowledge_public و knowledge_internal و پاسخ Chat به شکل SSE باشد.
کل پنج سناریوی پروژه و سه زیرسناریوی HR در دامنه نهایی هستند.
پیش از هر تغییر کد موجود را بررسی کن، فایل‌های لازم را کامل تولید کن، Alembic و تست‌ها را فراموش نکن.
تصمیم جدید تأییدشده را در سند Implementation و Decision Log به‌روزرسانی کن.
```

---

## ۲۱. تاریخچه سند

| نسخه | تاریخ | تغییر |
|---|---|---|
| `1.0.0` | `2026-11-10` | تدوین سند جامع از تصمیم‌های توافق‌شده درباره هسته چت‌بات، پنج سناریو، Agent داخلی، یک Deployment، LLM محلی، Qdrant، RAG، SSE، Storage، تست و سخت‌افزار محلی. |
| `1.2.0` | `2026-11-11` | ثبت قرارداد اجرایی مرحله ۵ درباره Parser/OCR، Storage، Embedding، Qdrant Hybrid+RRF، Reranking، Retrieval Access، Version/Retry و محدودیت Benchmark محلی. |
| `1.1.1` | `2026-11-11` | رفع مشکل ماندن پیام SSE در وضعیت `streaming` هنگام client disconnect با shield در cleanup و تست لغو ASGI؛ ثبت تفاوت نمایش JSON فارسی در PowerShell 5.1. |
| `1.1.0` | `2026-11-11` | ثبت قراردادهای واقعی Stage 4 برای Conversation History، وضعیت SSE، Feedback، Knowledge Metadata، Scope، Migration و Retention. |
| `1.0.1` | `2026-11-10` | ثبت تصمیم‌های اجرایی Stage 2 برای Compose، Security، Persistent Storage، Runtime محلی و وضعیت آزمون Windows. |
| `1.0.2` | `2026-11-10` | اصلاح مشکل سازگاری CRLF در آماده‌سازی Environment مرحله ۲، افزودن راه‌اندازی idempotent و اصلاح دستور اجرای llama.cpp در نشست مستقل PowerShell. |
| `1.0.3` | `2026-11-10` | امکان انتخاب Runflare PyPI Mirror برای نصب وابستگی‌ها در Docker Build مرحله ۲ و ثبت ملاحظات امنیتی. |
| `1.0.4` | `2026-11-10` | اصلاح CRLF در Shell EntryPoint برای Docker روی Windows و افزودن تست Integration شبیه‌ساز Checkout ویندوز. |
| `1.0.5` | `2026-11-10` | ثبت قراردادهای Chat/Conversation/SSE، Error/Concurrency و سیاست Identity آزمایشی Stage 3 بدون Persistence جعلی. |
| `1.0.6` | `2026-11-11` | اصلاح Test مربوط به CRLF در Windows، بهبود کدهای امن تشخیص آمادگی llama.cpp و افزودن PowerShell 5.1 SSE smoke test. |
| `1.0.7` | `2026-11-11` | ثبت علت محتمل `LLM_EMPTY_RESPONSE` در Qwen3، خاموش‌کردن Thinking برای مدل اولیه و مستندکردن تنظیمات سازگار `llama.cpp` و تست Windows. |
| `1.0.8` | `2026-11-11` | اصلاح مشکل Encoding متن فارسی در فایل UTF-8 بدون BOM اسکریپت Windows PowerShell 5.1 با JSON Unicode escape و افزودن آزمون رگرسیون. |

**پایان سند — این فایل باید در کنار `Service_Architecture_Guide_FA.md` نگهداری و با تصمیم‌های تأییدشده جدید نسخه‌بندی شود.**