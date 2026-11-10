"""Process liveness only; does not claim database or model readiness."""

from fastapi import APIRouter

from src.infrastructure.di.inject import inject


@inject
class HealthController:
    def api(self) -> APIRouter:
        router = APIRouter(tags=["Health"])

        @router.get("", summary="API liveness")
        async def health_async() -> dict[str, str]:
            return {"status": "ok"}

        return router
