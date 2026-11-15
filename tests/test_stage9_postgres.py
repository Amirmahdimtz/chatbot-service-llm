"""Opt-in real PostgreSQL integration for repeatable synthetic Stage 9 seed.

Never connects to production databases: dedicated DB name and explicit marker required.
"""
from __future__ import annotations

import os

import pytest

from src.infrastructure.scripts.seed_stage9 import (
    load_fixture, require_isolated_database, seed_async,
)


@pytest.mark.asyncio
async def test_real_postgres_isolated_seed_idempotency_and_tenant_boundary():
    url = os.getenv("CHATBOT_STAGE9_TEST_DATABASE_URL")
    if not url or os.getenv("CHATBOT_STAGE9_ISOLATED") != "1":
        pytest.skip("Requires an explicitly isolated migrated Stage 9 PostgreSQL test database")
    require_isolated_database(url)
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("Real PostgreSQL integration requires asyncpg")
    fixture, _ = load_fixture()
    first = await seed_async(url, fixture)
    assert first["created"] + first["unchanged"] + first["updated"] == len(fixture["records"])
    second = await seed_async(url, fixture)
    assert second == {"created": 0, "updated": 0, "unchanged": len(fixture["records"])}

    from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
    from src.infrastructure.repositories.scenario.scenario_repository import ScenarioRepository

    class Config:
        def get(self, key, default=None):
            return url if key == "database.url" else default

    context = PsqlDbContext(Config())
    repository = ScenarioRepository(context)
    try:
        own = await repository.get_scoped_async("internal", fixture["tenant_id"], "personnel", "alice")
        foreign = await repository.get_scoped_async("internal", "stage9-other-tenant", "personnel", "alice")
        public = await repository.get_scoped_async("public", "", "faq", "faq_prayer_training")
        assert own is not None and own.owner_id == "stage9-synthetic-seeder"
        assert own.version == 1
        assert foreign is None
        assert public is not None and public.verified is True
    finally:
        await context.dispose_async()
