"""FastAPI app construction and feature-folder controller discovery."""

from __future__ import annotations

from contextlib import asynccontextmanager
import importlib
import inspect
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from uuid import uuid4

from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.di.inject import inject, resolve
from src.infrastructure.utils.config_reader import ConfigReader


class ControllerDiscoveryError(RuntimeError):
    """A convention-based controller could not be loaded."""


@inject
class WebService:
    def __init__(self, config_reader: ConfigReader):
        self._config_reader = config_reader

    def create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            # The engine is created once per process, but sessions are never shared.
            db_context = resolve(PsqlDbContext) if self._config_reader.get("database.url") else None
            try:
                yield
            finally:
                if db_context is not None:
                    await db_context.dispose_async()

        app = FastAPI(
            title=self._config_reader.get("app.name", "Chatbot Service"),
            version=str(self._config_reader.get("app.version", "0.1.0")),
            lifespan=lifespan,
        )
        @app.exception_handler(RequestValidationError)
        async def request_validation_error_async(_request: Request, exc: RequestValidationError):
            request_id = str(uuid4())
            return JSONResponse(
                status_code=422,
                content={"error": {
                    "code": "VALIDATION_ERROR", "message": "Invalid request.",
                    "request_id": request_id,
                    "fields": [
                        {"field": ".".join(str(part) for part in entry["loc"]), "code": entry["type"]}
                        for entry in exc.errors()
                    ],
                }},
                headers={"X-Request-ID": request_id},
            )

        application_root = Path(__file__).resolve().parent
        api_prefix = self._config_reader.get_api_prefix()
        for feature_dir in sorted(application_root.iterdir()):
            if not feature_dir.is_dir() or feature_dir.name.startswith("_"):
                continue
            file = feature_dir / f"{feature_dir.name}_controller.py"
            if not file.is_file():
                continue
            module_name = f"src.application.{feature_dir.name}.{feature_dir.name}_controller"
            try:
                module = importlib.import_module(module_name)
                controllers = [
                    cls for _, cls in inspect.getmembers(module, inspect.isclass)
                    if cls.__module__ == module_name and cls.__name__.endswith("Controller")
                ]
                if len(controllers) != 1:
                    raise ControllerDiscoveryError(f"Expected exactly one Controller in {module_name}")
                controller = controllers[0]()
                router = controller.api()
                if not isinstance(router, APIRouter):
                    raise ControllerDiscoveryError(f"{module_name}.api() must return APIRouter")
                app.include_router(router, prefix=f"{api_prefix}/{feature_dir.name}")
            except Exception as exc:
                raise ControllerDiscoveryError(f"Failed loading {module_name}: {exc}") from exc
        return app
