# راهنمای مرجع معماری و کدنویسی سرویس‌های python

سند مستقل برای تولید پروژه‌ها و Featureهای جدید با FastAPI، Constructor Dependency Injection، Repository Pattern و ساختار لایه‌ای


هدف: این فایل به‌تنهایی برای انتقال استاندارد معماری به ChatGPT یا هر توسعه‌دهنده کافی باشد.

## ۰. قرارداد اصلی این سند با ChatGPT / AI

- این سند «استاندارد الزام‌آور پروژه» است. هنگام تولید یا تغییر کد، قواعد این سند بر الگوهای عمومی و ترجیحات پیش‌فرض مدل مقدم است.

- هدف تجاری پروژه را از معماری استنتاج نکن. فقط Feature یا Serviceای را که کاربر درخواست می‌کند با همین ساختار پیاده‌سازی کن.

- معماری را به Clean Architecture کامل، DDD، Hexagonal، CQRS یا ساختار دیگری تبدیل نکن مگر اینکه کاربر صریحاً درخواست کند.

- برای هر Service/Repository ساده Interface نساز. Concrete class پیش‌فرض است؛ Interface فقط زمانی اضافه شود که واقعاً چند implementation، مرز قابل‌تعویض، تست‌پذیری خاص یا قرارداد abstraction لازم باشد.

- Dependencyها را داخل کلاس با constructor injection دریافت کن. کلاس وابسته نباید dependency خود را با new/constructor مستقیم بسازد.

- Services، Repositories، Infrastructure providers و Controllerهای دارای dependency باید با @inject کار کنند و registration دستی برای آن‌ها نوشته نشود.

- ساختار پوشه، نام فایل‌ها و نام کلاس‌ها بخشی از runtime convention پروژه است؛ تغییر نام دلخواه ممکن است discovery را بشکند.

- در خروجی کدنویسی، فایل‌ها را کامل و قابل‌اجرا تولید کن؛ placeholderهایی مثل TODO، pseudo-code یا «بقیه مشابه است» نگذار مگر کاربر صریحاً نمونه‌ی کوتاه بخواهد.

- اگر Feature جدید Model دیتابیس دارد، تغییر Alembic metadata/import و نیاز به migration را فراموش نکن.

- اگر درخواست کاربر با این استاندارد تعارض دارد، درخواست صریح کاربر مقدم است؛ در غیر این صورت این سند مبناست.



```text
این سند استاندارد معماری پروژه است. هر کدی که از این به بعد برای این پروژه می‌نویسی باید مطابق آن باشد.
Feature یا Service درخواستی من را با همان لایه‌بندی، نام‌گذاری، Constructor DI، @inject، Repository Pattern، DTO و Controller convention پیاده‌سازی کن.
ساختار جایگزین یا abstraction اضافی ایجاد نکن مگر اینکه صریحاً درخواست کنم.
```

## ۱. فلسفه و سبک معماری

این پروژه یک معماری لایه‌ای سبک، convention-based و pragmatic است. هدف آن ایجاد ساختار مشخص بدون ceremony اضافی است. این معماری از بعضی اصول Clean Architecture الهام می‌گیرد، اما Clean Architecture خالص نیست و نباید به زور به آن تبدیل شود.

- لایه‌ها: Host → Application → Core → Infrastructure.

- Convention over configuration: ثبت DI و Controllerها تا حد ممکن خودکار است.

- Constructor Dependency Injection: وابستگی‌ها از type hint سازنده resolve می‌شوند.

- Thin Controllers: Controller فقط HTTP، validation، mapping و فراخوانی Service را مدیریت می‌کند.

- Service Layer: منطق workflow/business در Core/services قرار می‌گیرد.

- Repository Pattern: persistence و query دیتابیس در Repository است.

- Generic BaseRepository: CRUD عمومی تکرار نمی‌شود.

- Async-first database access با SQLAlchemy AsyncSession.

- Minimal abstractions: Interface و Domain layer فقط در صورت نیاز واقعی.

- Feature-oriented organization داخل Application، Core/services و Infrastructure/repositories.



## ۲. ساختار استاندارد پروژه

```text
project/
├── ci/
├── docs/
├── src/
│   ├── host/
│   │   ├── app.py
│   │   ├── entrypoint.sh
│   │   └── res/
│   │       ├── appsettings.yaml
│   │       └── appsettings.development.yaml
│   ├── application/
│   │   ├── web.py
│   │   └── {feature}/
│   │       ├── {feature}_controller.py
│   │       └── dtos/
│   │           └── {feature}_dto.py
│   ├── core/
│   │   └── services/
│   │       └── {feature}/
│   │           └── {feature}_service.py
│   └── infrastructure/
│       ├── di/
│       │   ├── inject.py
│       │   ├── reflection.py
│       │   └── bootstrap.py
│       ├── context/
│       │   ├── sql_db/psql_dbcontext.py
│       │   └── vault/vault_service.py
│       ├── models/
│       │   └── {feature}.py
│       ├── repositories/
│       │   ├── base/base_repository.py
│       │   └── {feature}/{feature}_repository.py
│       ├── utils/config_reader.py
│       ├── alembic/
│       └── scripts/run_migrations.py
├── Dockerfile
├── requirements.txt
└── .gitlab-ci.yml
```

| لایه | مسیر | مسئولیت |

| --- | --- | --- |

| Host | src/host/ | Entry point، appsettings، startup و Docker entrypoint |

| Application | src/application/ | HTTP layer: Controller، DTO، FastAPI wiring و route discovery |

| Core | src/core/services/ | Serviceها و منطق workflow/business |

| Infrastructure | src/infrastructure/ | DB context، SQLAlchemy models، Repository، Vault، Config، DI و migrations |



## ۳. جریان استاندارد درخواست و وابستگی‌ها

```text
HTTP Request
    ↓
{Feature}Controller
    ↓
{Feature}Service
    ↓
{Feature}Repository
    ↓
PsqlDbContext
    ↓
PostgreSQL
```

Dependency graph باید از طریق constructor injection ساخته شود؛ Controller نباید Service را بسازد، Service نباید Repository را بسازد و Repository نباید DbContext را بسازد.

## ۴. استاندارد Dependency Injection

### ۴.۱ Constructor Injection

```python
from src.infrastructure.di.inject import inject

@inject
class ProductService:
    def __init__(self, product_repository: ProductRepository):
        self._product_repository = product_repository
```

DI براساس type annotation پارامتر سازنده عمل می‌کند. نام متغیر secondary است؛ type hint باید دقیق و resolveشدنی باشد.

### ۴.۲ قواعد @inject

| نوع Component | @inject | قاعده |

| --- | --- | --- |

| Service | بله | پیش‌فرض الزامی |

| Repository | بله | پیش‌فرض الزامی |

| Config/DB/Vault و providerهای Infrastructure | بله | برای resolve شدن توسط container |

| Controller دارای dependency | بله | تا سازنده هنگام discovery dependency بگیرد |

| Controller بدون dependency | اختیاری | مانند Health Check ساده |

| DTO / Pydantic Model | خیر | Data object است، provider نیست |

| SQLAlchemy Model | خیر | Entity دیتابیس است، provider نیست |



### ۴.۳ Singleton policy

```python
@inject
class PsqlDbContext:
    __di_singleton__ = True

    def __init__(self, config_reader: ConfigReader, vault_service: VaultService):
        ...
```

در معماری مرجع، ConfigReader، VaultService و PsqlDbContext Singleton هستند. Service، Repository و Controller به‌صورت پیش‌فرض Singleton نیستند مگر نیاز معماری مشخصی وجود داشته باشد.

### ۴.۴ Bootstrap و discovery

```python
def bootstrap_di() -> None:
    bootstrap_packages()

# scan order:
# infrastructure → core → application
```

فقط کلاس‌هایی که با @inject علامت‌گذاری شده‌اند provider محسوب می‌شوند. ثبت providerها دستی نیست. پوشه‌های di، dtos، models، scripts، alembic، versions، res و sso از اسکن providerها کنار گذاشته می‌شوند.

### ۴.۵ رفتار constructor injection که باید حفظ شود

- پارامتری که caller هنگام ساخت object صریحاً داده است دوباره inject نمی‌شود.

- پارامتری که default value دارد اجباری inject نمی‌شود.

- پارامتر dependency بدون type annotation معتبر نباید نوشته شود؛ resolver نمی‌تواند آن را تشخیص دهد.

- برای dependencyهای DI از typeهای concrete یا interface ثبت‌شده استفاده شود، نه string lookup و global service locator.

- استفاده از resolve() خارج از composition/startup یا helperهای خاص باید حداقلی باشد؛ الگوی اصلی constructor injection است.



## ۵. استاندارد Controller و Auto Discovery

Controller discovery با DI discovery متفاوت است. WebService پوشه‌های مستقیم زیر src/application را بررسی می‌کند و قرارداد نام‌گذاری زیر را انتظار دارد:

```text
src/application/{feature}/{feature}_controller.py

class {FeaturePascalCase}Controller:
    def api(self):
        return APIRouter(...)
```

- نام پوشه feature با نام فایل controller هماهنگ باشد؛ مثال: product/product_controller.py.

- نام کلاس با Controller تمام شود؛ مثال: ProductController.

- کلاس متد api() داشته باشد و APIRouter برگرداند.

- Controller prefix اصلی feature را خودش تکرار نکند؛ WebService آن را mount می‌کند.

- route نهایی برابر {api.prefix}/{feature} است؛ در config مرجع api.prefix برابر /api/v1 است.

- Controller باید thin بماند: DTO validation، HTTP status، HTTPException، mapping response و call به Service.

- Query مستقیم SQLAlchemy یا ساخت Session داخل Controller ممنوع است.



### ۵.۱ نمونه Controller استاندارد

```python
from typing import List
from fastapi import APIRouter, HTTPException, status

from src.application.product.dtos.product_dto import (
    CreateProductDto,
    ProductResponseDto,
    UpdateProductDto,
)
from src.core.services.product.product_service import ProductService
from src.infrastructure.di.inject import inject


@inject
class ProductController:
    def __init__(self, product_service: ProductService):
        self._product_service = product_service

    def api(self):
        router = APIRouter(
            prefix="",
            tags=["Product"],
            responses={404: {"description": "Not found"}},
        )

        @router.post(
            "/",
            response_model=ProductResponseDto,
            status_code=status.HTTP_201_CREATED,
            summary="Create product",
        )
        async def create_product(payload: CreateProductDto) -> ProductResponseDto:
            product = await self._product_service.create_async(
                name=payload.name,
                price=payload.price,
            )
            return ProductResponseDto.model_validate(product)

        @router.get("/", response_model=List[ProductResponseDto])
        async def list_products() -> List[ProductResponseDto]:
            products = await self._product_service.get_all_async()
            return [ProductResponseDto.model_validate(x) for x in products]

        @router.get("/{product_id}", response_model=ProductResponseDto)
        async def get_product(product_id: str) -> ProductResponseDto:
            product = await self._product_service.get_by_id_async(product_id)
            if product is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Product '{product_id}' not found",
                )
            return ProductResponseDto.model_validate(product)

        return router
```

## ۶. استاندارد DTO و Validation

- DTOها داخل src/application/{feature}/dtos/ قرار می‌گیرند.

- برای request و response مدل‌های Pydantic مجزا تعریف شوند وقتی شکل داده‌ها متفاوت است.

- نام‌گذاری پیشنهادی: Create{Feature}Dto، Update{Feature}Dto، {Feature}ResponseDto.

- Validation ورودی HTTP (min/max length، range، pattern و موارد مشابه) در DTO انجام شود.

- Response DTO برای SQLAlchemy object از from_attributes استفاده کند.

- SQLAlchemy Model را مستقیم به‌عنوان request body تعریف نکن.



```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class CreateProductDto(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    price: float = Field(..., ge=0)


class UpdateProductDto(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    price: float = Field(..., ge=0)


class ProductResponseDto(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    price: float
    creation_datetime: datetime
    modification_datetime: datetime | None = None
```

## ۷. استاندارد Service Layer

- مسیر: src/core/services/{feature}/{feature}_service.py.

- Service با @inject تعریف شود و Repository را در constructor دریافت کند.

- Business rule، normalization، orchestration و تصمیم‌های use-case در Service انجام شوند.

- Service نباید FastAPI APIRouter، HTTPException یا status code را بشناسد مگر نیاز خاصی صریحاً تعریف شده باشد.

- متدهای async با suffix _async نام‌گذاری شوند تا سبک پروژه حفظ شود.

- برای CRUD ساده return type می‌تواند SQLAlchemy model باشد و Controller آن را به DTO map کند.

- اگر چند Repository لازم است، همه باید از constructor تزریق شوند.



```python
from typing import List, Optional

from src.infrastructure.di.inject import inject
from src.infrastructure.models.product import Product
from src.infrastructure.repositories.product.product_repository import ProductRepository


@inject
class ProductService:
    def __init__(self, product_repository: ProductRepository):
        self._product_repository = product_repository

    async def create_async(self, name: str, price: float) -> Product:
        product = Product(name=name.strip(), price=price)
        return await self._product_repository.insert_async(product)

    async def get_by_id_async(self, product_id: str) -> Optional[Product]:
        return await self._product_repository.get_by_id_async(product_id)

    async def get_all_async(self) -> List[Product]:
        return await self._product_repository.get_all_async()

    async def update_async(
        self, product_id: str, name: str, price: float
    ) -> Optional[Product]:
        product = await self._product_repository.get_by_id_async(product_id)
        if product is None:
            return None

        product.name = name.strip()
        product.price = price
        return await self._product_repository.update_async(product)

    async def delete_async(self, product_id: str) -> bool:
        return await self._product_repository.delete_async(product_id)
```

## ۸. استاندارد Repository، Model و Database

### ۸.۱ SQLAlchemy Model

- Modelهای persistence داخل src/infrastructure/models/ قرار می‌گیرند؛ Domain layer جدا به‌صورت پیش‌فرض ایجاد نشود.

- تمام Modelها از Base تعریف‌شده در psql_dbcontext.py ارث‌بری کنند.

- برای شناسه، timestamp و naming الگوی Modelهای موجود پروژه حفظ شود مگر schema نیاز متفاوتی داشته باشد.

- اضافه شدن Model جدید باید در Alembic env.py یا مکان central registration وارد شود تا Base.metadata آن را ببیند.



```python
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, String
from sqlalchemy.sql import func

from src.infrastructure.context.sql_db.psql_dbcontext import Base


class Product(Base):
    __tablename__ = "product"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid4()))
    name = Column(String(200), nullable=False)
    price = Column(Float, nullable=False)
    creation_datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        default=datetime.now(UTC),
    )
    modification_datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=True,
        onupdate=datetime.now(UTC),
    )
```

### ۸.۲ Repository

Repository ساده باید BaseRepository را reuse کند و فقط model و DbContext را wire کند:

```python
from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.di.inject import inject
from src.infrastructure.models.product import Product
from src.infrastructure.repositories.base.base_repository import BaseRepository


@inject
class ProductRepository(BaseRepository[Product]):
    def __init__(self, db_context: PsqlDbContext):
        super().__init__(db_context=db_context, model=Product)
```

Queryهای اختصاصی feature در همین Repository اضافه می‌شوند. SQL/query persistence نباید به Service یا Controller منتقل شود.

### ۸.۳ BaseRepository contract

| متد | رفتار |

| --- | --- |

| insert_async(entity) | ذخیره entity و refresh، سپس برگرداندن entity |

| insert_and_get_id_async(entity) | ذخیره و برگرداندن id |

| get_by_id_async(id) | برگرداندن entity یا None |

| get_all_async() | برگرداندن List از entityها |

| update_async(entity) | merge + commit + refresh |

| delete_async(id) | حذف و برگرداندن bool |



### ۸.۴ DbContext و Session lifetime

```text
PsqlDbContext (Singleton)
    ├── AsyncEngine (shared)
    └── async_sessionmaker (shared)

Each repository operation
    └── async with db_context.session() as session:
            ...
```

Engine و session factory یک بار ساخته می‌شوند، اما هر عملیات Repository Session خودش را باز می‌کند. engine-per-request یا global AsyncSession ایجاد نکن.

## ۹. Configuration، Vault و Environment

- Configuration داخل src/host/res/appsettings.development.yaml و appsettings.yaml نگهداری می‌شود.

- env_type=development فایل development را انتخاب می‌کند؛ سایر environmentها فایل appsettings.yaml را می‌خوانند.

- ConfigReader Singleton است و dotted key مثل database.url یا api.prefix را resolve می‌کند.

- برای local development معمولاً Vault غیرفعال و database.url مستقیم در config تنظیم می‌شود.

- با Vault فعال، secretهای حساس از VaultService خوانده می‌شوند.

- ConfigReader یا VaultService را داخل Service جدید نساز؛ در صورت نیاز آن‌ها را inject کن.



```yaml
app:
  name: "My Service"
  version: "1.0.0.0"
server:
  host: "0.0.0.0"
  port: 5000
database:
  url: "postgresql://postgres:postgres@localhost:5432/postgres"
api:
  prefix: "/api/v1"
vaulthc:
  enabled: false
```

## ۱۰. سیاست Interface و Abstraction

پیش‌فرض این معماری concrete injection است. برای CRUD ساده این ساختار صحیح است:

```text
ProductController → ProductService → ProductRepository → PsqlDbContext
```

ساخت IProductService، IProductRepository یا IBaseRepository فقط برای «شکل معماری» ممنوع است. Interface فقط وقتی ایجاد شود که حداقل یکی از شرایط زیر برقرار باشد:

- بیش از یک implementation واقعی وجود دارد یا قرار است وجود داشته باشد.

- یک dependency خارجی باید قابل تعویض باشد (مثلاً providerهای مختلف payment/storage).

- مرز abstraction مشخصی برای تست یا plugin architecture لازم است.

- کاربر صریحاً Interface می‌خواهد.



DI engine interface را پشتیبانی می‌کند: اگر implementation از ABC یا base classای که نامش با I شروع می‌شود ارث ببرد، reflection می‌تواند آن base را interface registration در نظر بگیرد.

## ۱۱. فرایند استاندارد ساخت Feature جدید

1. نیاز Feature را به entity/data، persistence، business workflow و HTTP endpointها تقسیم کن.

2. اگر داده پایدار است، SQLAlchemy Model را در infrastructure/models بساز.

3. Repository را در infrastructure/repositories/{feature} بساز و در حالت CRUD از BaseRepository ارث بده.

4. Service را در core/services/{feature} بساز و Repository را با constructor injection بگیر.

5. DTOهای request/response را در application/{feature}/dtos بساز.

6. Controller را در application/{feature}/{feature}_controller.py بساز، با نام کلاس ending in Controller و متد api().

7. Model جدید را برای Alembic metadata register/import کن.

8. Migration را generate و apply کن.

9. Importها و naming convention را بررسی کن تا auto discovery کار کند.

10. Syntax/compile و تست‌های موجود را اجرا کن.



```text
src/
├── application/product/
│   ├── product_controller.py
│   └── dtos/product_dto.py
├── core/services/product/
│   └── product_service.py
└── infrastructure/
    ├── models/product.py
    └── repositories/product/
        └── product_repository.py
```

## ۱۲. Alembic و Migration

- تغییر schema فقط با تغییر Model تمام نمی‌شود؛ migration باید ایجاد و commit شود.

- Model جدید باید در Alembic metadata قابل مشاهده باشد. در ساختار مرجع env.py modelها را import می‌کند.

- برای local development می‌توان از --sync استفاده کرد؛ در pipeline production migrationهای commitشده با --upgrade اجرا می‌شوند.

- هر migration یک logical change مشخص داشته باشد و پیام قابل‌فهم بگیرد.



```bash
python src/infrastructure/scripts/run_migrations.py --upgrade
python src/infrastructure/scripts/run_migrations.py --autogenerate -m "add product table"
python src/infrastructure/scripts/run_migrations.py --sync -m "add product table"
```

## ۱۳. Naming و Coding Conventions

| مورد | قاعده | مثال |

| --- | --- | --- |

| Feature folder | snake_case | health_check، product_order |

| Controller file | {feature}_controller.py | product_controller.py |

| Controller class | PascalCase + Controller | ProductController |

| Service file | {feature}_service.py | product_service.py |

| Service class | PascalCase + Service | ProductService |

| Repository file | {feature}_repository.py | product_repository.py |

| Repository class | PascalCase + Repository | ProductRepository |

| DTO file | {feature}_dto.py | product_dto.py |

| Async method | verb_async | create_async، get_by_id_async |

| Private dependency field | _name | self._product_repository |



## ۱۴. مرزبندی مسئولیت‌ها و Error Handling

| Component | مسئولیت |

| --- | --- |

| Controller | HTTP status، HTTPException، request/response DTO، route metadata |

| Service | قواعد business/workflow، orchestration، normalization، تصمیم‌های domain-like |

| Repository | SQLAlchemy query، persistence، session usage |

| DbContext | engine/session factory و اتصال دیتابیس |

| Config/Vault | configuration و secret resolution |



مثال: اگر entity پیدا نشود، Service می‌تواند None برگرداند و Controller آن را به HTTP 404 تبدیل کند. این الگوی Profile مرجع است و HTTP concern را از Core دور نگه می‌دارد.

## ۱۵. موارد ممنوع یا خارج از استاندارد پیش‌فرض

- ساخت Repository داخل Service: self._repo = ProductRepository(...).

- ساخت Service داخل Controller به‌صورت مستقیم.

- استفاده از Session/SQLAlchemy query داخل Controller.

- ساخت یک Domain layer، UseCases layer، Ports/Adapters یا CQRS فقط برای زیبایی معماری.

- ساخت I{Feature}Service و I{Feature}Repository برای هر Feature بدون نیاز واقعی.

- ثبت دستی تک‌تک providerها در container در حالی که @inject discovery وجود دارد.

- نام‌گذاری controller خارج از {feature}/{feature}_controller.py که باعث شکستن discovery شود.

- تعریف Controller بدون api() یا کلاسی که نامش به Controller ختم نمی‌شود.

- قرار دادن SQLAlchemy models در Application یا DTOها در Infrastructure.

- ایجاد engine یا async_sessionmaker برای هر request/repository call.

- اضافه کردن dependency یا framework جدید برای DI بدون درخواست صریح.

- تغییر مسیر importهای src.* یا افزودن __init__.pyهای غیرضروری فقط برای پیروی از templateهای دیگر.



## ۱۶. قرارداد خروجی ChatGPT هنگام درخواست ساخت سرویس/Feature

وقتی کاربر بعد از آپلود این سند می‌گوید «سرویس Product را بساز»، مدل باید قبل از تولید کد این قواعد را اعمال کند:

- ابتدا اجزای موردنیاز را از روی درخواست تشخیص بده: Model، Repository، Service، DTO، Controller، config و migration.

- اگر درخواست فقط Service است و نیازی به HTTP/DB ندارد، فایل‌های غیرلازم ایجاد نکن؛ اما DI و محل Service را همچنان مطابق سند نگه دار.

- اگر CRUD/API کامل خواسته شد، stack کامل feature را بساز.

- فایل‌ها را با مسیر دقیق معرفی کن و محتوای کامل هر فایل را ارائه بده.

- Importهای واقعی و consistent با src.* بنویس.

- تمام dependencyها از constructor دریافت شوند و providerها با @inject مشخص شوند.

- از BaseRepository برای CRUD عمومی استفاده کن؛ custom queryها را در Repository feature اضافه کن.

- HTTPException و status code را در Controller نگه دار.

- Validation را در Pydantic DTO قرار بده.

- اگر Model جدید است، Alembic registration و دستور migration را همراه تغییرات اعلام کن.

- در پایان یک checklist کوتاه از فایل‌های ایجاد/تغییرکرده و routeهای نهایی بده.

- اگر بخشی از نیاز نامشخص است ولی می‌توان safe default گرفت، با همین conventions بهترین default را پیاده‌سازی کن؛ معماری را عوض نکن.



### ۱۶.۱ ترتیب پیشنهادی ارائه فایل‌ها

1. SQLAlchemy Model

2. Repository

3. Service

4. DTOs

5. Controller

6. Alembic metadata/import change

7. Migration command / config changes

8. Summary of routes and dependency graph



## ۱۷. Promptهای آماده برای استفاده با ChatGPT

### ۱۷.۱ ساخت Feature CRUD کامل

```text
این سند استاندارد معماری پروژه من است و باید دقیقاً رعایت شود.
یک Feature به نام Product بساز.
فیلدها:
- name: string, required, max 200
- price: float, required, >= 0

CRUD کامل HTTP می‌خواهم.
کد تمام فایل‌های لازم را با مسیر دقیق، Dependency Injection، Repository، Service، DTO، Controller و تغییر Alembic تولید کن.
هیچ Interface یا Layer اضافی نساز مگر طبق خود سند لازم باشد.
```

### ۱۷.۲ ساخت Service بدون API

```text
طبق سند معماری پیوست، یک EmailNotificationService بساز که به I/Provider خارجی ایمیل متصل شود.
این سرویس endpoint HTTP و SQLAlchemy model نمی‌خواهد.
Dependency provider را با Constructor Injection دریافت کن و فقط فایل‌های واقعاً لازم را ایجاد کن.
اگر برای provider خارجی abstraction لازم است، دلیل آن را کوتاه بگو و مطابق DI پروژه پیاده‌سازی کن.
```

### ۱۷.۳ توسعه Feature موجود

```text
طبق این سند و بدون تغییر معماری، به Feature Product قابلیت جست‌وجو بر اساس name اضافه کن.
Query دیتابیس باید در ProductRepository باشد، orchestration در ProductService و endpoint در ProductController.
فقط فایل‌های لازم را تغییر بده و کد کامل بخش‌های تغییرکرده را ارائه کن.
```

## ۱۸. چک‌لیست پذیرش Feature جدید

- [ ] پوشه و فایل Controller دقیقاً با convention نام‌گذاری شده‌اند.

- [ ] Controller class با Controller تمام می‌شود و api() دارد.

- [ ] Controller دارای dependency با @inject علامت‌گذاری شده است.

- [ ] Service در src/core/services/{feature} قرار دارد و @inject دارد.

- [ ] Repository در src/infrastructure/repositories/{feature} قرار دارد و @inject دارد.

- [ ] Dependencyها با constructor injection هستند؛ ساخت مستقیم dependency وجود ندارد.

- [ ] Repository برای CRUD از BaseRepository استفاده می‌کند.

- [ ] SQLAlchemy Model در src/infrastructure/models قرار دارد.

- [ ] DTOها در application feature قرار دارند و Pydantic validation دارند.

- [ ] async methodها با _async نام‌گذاری شده‌اند.

- [ ] HTTP concern در Controller و DB concern در Repository باقی مانده است.

- [ ] Interface غیرضروری ساخته نشده است.

- [ ] Domain/CQRS/UseCase layer غیرضروری اضافه نشده است.

- [ ] Model جدید برای Alembic metadata register شده است.

- [ ] Migration ایجاد/اعلام شده است.

- [ ] route نهایی با /api/v1/{feature} سازگار است.

- [ ] کد compile می‌شود و import pathها معتبرند.



## ۱۹. ماتریس تصمیم برای اجزای لازم

| نوع نیاز | اجزای استاندارد |

| --- | --- |

| Endpoint HTTP جدید | Controller + DTO + معمولاً Service |

| Business workflow بدون HTTP | Service و dependencyهای لازم |

| Persistence جدید | Model + Repository + Service + migration |

| CRUD ساده entity | Model + thin Repository(BaseRepository) + Service + DTO + Controller + migration |

| Custom DB query | متد جدید در Repository + wrapper/orchestration در Service |

| Config value جدید | appsettings + ConfigReader.get(...) یا helper در صورت تکرار |

| Secret خارجی | Vault/environment resolution؛ در صورت نیاز provider Infrastructure |

| Implementation قابل‌تعویض | Interface/ABC فقط در این حالت قابل توجیه است |



## ۲۰. نکات دقیق مربوط به DI و Discovery مرجع

- bootstrap_di() باید قبل از resolve(WebService) اجرا شود.

- Injector provider را براساس type ثبت و resolve می‌کند.

- اگر provider با __di_singleton__ = True ثبت شده باشد، instance پس از اولین resolve cache می‌شود.

- اگر interface inferred شود، implementation هم جداگانه قابل register/resolve می‌ماند.

- bootstrap یک guard دارد و فقط یک بار packageها را scan می‌کند.

- در reflection مرجع، import error یک module باعث skip شدن آن module می‌شود؛ بنابراین naming/import صحیح برای discovery حیاتی است.

- WebService Controller را با controller_class() instantiate می‌کند؛ @inject wrapper constructor در همان لحظه dependencyها را resolve می‌کند.

- route prefix از ConfigReader.get_api_prefix() و نام feature folder ساخته می‌شود.

- namespace package style استفاده شده و __init__.pyهای متعدد جزو requirement معماری نیستند.



## ۲۱. بهبودهای مجاز بدون شکستن معماری

- افزودن تست unit/integration برای Service، Repository و Controller.

- افزودن logging استاندارد و centralized error handling در صورت نیاز پروژه.

- افزودن pagination/filtering با حفظ query در Repository و HTTP params در Controller.

- افزودن transaction orchestration در سطح مناسب در صورتی که use-case چند عملیات atomic داشته باشد.

- افزودن Interface فقط برای dependency واقعاً قابل‌تعویض.

- تقویت reflection error reporting یا bootstrap validation بدون تغییر convention اصلی.

- ایجاد registration مرکزی برای Alembic models اگر تعداد Modelها زیاد شد، به شرط حفظ visibility در Base.metadata.



## ۲۲. نسخه فشرده استاندارد برای قرار دادن در ابتدای هر پروژه

```text
ARCHITECTURE RULES

1) Layers: Host → Application → Core → Infrastructure.
2) Use constructor Dependency Injection. Mark providers with @inject.
3) Do not manually instantiate Service/Repository/DbContext dependencies.
4) Default dependency chain: Controller → Service → Repository → PsqlDbContext.
5) Controllers: src/application/{feature}/{feature}_controller.py, class ends with Controller, exposes api() -> APIRouter.
6) Routes are auto-mounted under {api.prefix}/{feature} (normally /api/v1/{feature}).
7) Controllers stay thin; HTTP concerns belong there.
8) Services live in src/core/services/{feature}; business/workflow belongs there; async methods end in _async.
9) Repositories live in src/infrastructure/repositories/{feature}; DB queries and persistence belong there.
10) Use BaseRepository for common CRUD. Add custom repository methods only for feature-specific queries.
11) SQLAlchemy models live in src/infrastructure/models, not a separate Domain layer by default.
12) DTOs live under application/{feature}/dtos and use Pydantic validation.
13) ConfigReader, VaultService and PsqlDbContext are singleton infrastructure providers. Services/Repositories/Controllers are not singleton by default.
14) Do not create per-feature interfaces unless there is a real abstraction/multiple implementation need.
15) Do not introduce DDD/CQRS/Hexagonal/Clean-Architecture layers unless explicitly requested.
16) New DB models must be visible to Alembic metadata and require a migration.
17) Preserve src.* imports, naming conventions and discovery-compatible folder structure.
18) Produce complete executable files, not pseudo-code, when asked to implement a feature.
```

