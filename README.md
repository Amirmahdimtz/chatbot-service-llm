# chatbot-service-llm

Stage 1: baseline FastAPI architecture with convention-based DI, controller discovery,
async SQLAlchemy repository contracts and Alembic configuration.

## Local setup (PowerShell, Python 3.11 or 3.12)

Python 3.11 and 3.12 are tested in CI. Check installed versions with `py -0p`
before creating the virtual environment.

Clone into the preferred directory only when it is absent or empty. If it already
contains unrelated files, leave them untouched and use a separate directory.
Never delete or overwrite existing files just to clone the repository.

```powershell
$Repo = "https://github.com/Amirmahdimtz/chatbot-service-llm.git"
$Project = "D:\chatbot-service-llm"

if (Test-Path -LiteralPath $Project) {
    if (Test-Path -LiteralPath (Join-Path $Project ".git")) {
        Set-Location $Project
        if ((git branch --show-current) -ne "main") {
            throw "Review the current branch before pulling."
        }
        if ((git status --porcelain | Out-String).Trim()) {
            throw "Local changes exist. Review them before pulling."
        }
        git pull --ff-only origin main
    }
    elseif (@(Get-ChildItem -LiteralPath $Project -Force).Count -eq 0) {
        git clone $Repo $Project
    }
    else {
        $Project = "D:\chatbot-service-llm-git"
        if (Test-Path -LiteralPath $Project) {
            throw "Alternate clone directory already exists. Choose a new location."
        }
        git clone $Repo $Project
    }
}
else {
    git clone $Repo $Project
}
if ($LASTEXITCODE -ne 0) { throw "Git operation failed." }

Set-Location $Project
git rev-parse HEAD

# Choose the version that 'py -0p' reports; Python 3.12 is shown here.
py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }

$Python = Join-Path $Project ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment Python executable is missing."
}

$env:PIP_CACHE_DIR = "D:\pip-cache"
$env:ENV_TYPE = "development"
& $Python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

& $Python -m compileall -q src tests
& $Python -m pytest -q
& $Python -m uvicorn src.host.app:app --host 127.0.0.1 --port 8000
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
