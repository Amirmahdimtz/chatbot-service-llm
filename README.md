# chatbot-service-llm

Stage 1: baseline FastAPI architecture with convention-based DI, controller discovery,
async SQLAlchemy repository contracts and Alembic configuration.

## Local setup (PowerShell, Python 3.11+)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:ENV_TYPE = 'development'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn src.host.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/api/v1/health` for a process-liveness check.
This route does not test the database, model runtime, or vector database.

`CHATBOT_DATABASE_URL` is read from the process environment when the database
is used, for example `postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB_NAME`.
Do **not** commit credentials or set a production URL in appsettings files.

Alembic configuration is at `src/infrastructure/alembic/alembic.ini`.
After creating a real model and configuring a PostgreSQL connection, run
`python -m alembic -c src/infrastructure/alembic/alembic.ini revision --autogenerate -m "describe change"`
and review the generated migration before applying `upgrade head`.
No application tables or migrations exist yet.

The technical requirements and stage order are defined in
`Chatbot_Service_Implementation_Guide_FA.md`. Stage 2 is not implemented.
