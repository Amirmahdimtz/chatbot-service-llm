"""Run connectivity checks inside the app container, without public diagnostic endpoints."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import tempfile

from sqlalchemy import text

from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.di.bootstrap import bootstrap_di
from src.infrastructure.di.inject import resolve
from src.infrastructure.providers.llm.llama_cpp_provider import LlamaCppProvider
from src.infrastructure.providers.vector_db.qdrant_provider import QdrantProvider
from src.infrastructure.utils.config_reader import ConfigReader


async def check_async(include_llm: bool = False) -> int:
    bootstrap_di()
    failed = False
    context = None

    try:
        context = resolve(PsqlDbContext)
        async with context.session() as first:
            result = await first.execute(text("SELECT 1"))
            if result.scalar_one() != 1:
                raise RuntimeError("Database returned an unexpected result")
        async with context.session() as second:
            result = await second.execute(text("SELECT 1"))
            if result.scalar_one() != 1 or first is second:
                raise RuntimeError("Session isolation check failed")
        print("POSTGRES: passed (async connections and distinct sessions)")
    except Exception as exc:
        failed = True
        print(f"POSTGRES: failed ({type(exc).__name__})")
    finally:
        if context is not None:
            await context.dispose_async()

    try:
        provider = resolve(QdrantProvider)
        if not await provider.check_ready_async() or not await provider.check_api_async():
            raise RuntimeError("Qdrant readiness/API unavailable")
        print("QDRANT: passed (readiness and collections API)")
    except Exception as exc:
        failed = True
        print(f"QDRANT: failed ({type(exc).__name__})")

    try:
        root = Path(resolve(ConfigReader).get("storage.path"))
        required = ("documents/originals", "documents/extracted", "generated", "temporary", "exports")
        if not all((root / subdir).is_dir() for subdir in required):
            raise RuntimeError("Storage directories missing")
        with tempfile.TemporaryFile(dir=root / "temporary") as probe:
            probe.write(b"storage probe")
            probe.flush()
        print("STORAGE: passed (required directories and write permission)")
    except Exception as exc:
        failed = True
        print(f"STORAGE: failed ({type(exc).__name__})")

    if include_llm:
        try:
            readiness = await resolve(LlamaCppProvider).readiness_status_async()
            if readiness == "ready":
                print("LLM: passed (health and model API)")
            else:
                failed = True
                print(f"LLM: failed ({readiness})")
        except Exception as exc:
            failed = True
            print(f"LLM: failed ({type(exc).__name__})")
    else:
        print("LLM: not run (pass --llm to check host runtime)")

    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Check stage 2 dependencies from the app network.")
    parser.add_argument("--llm", action="store_true", help="Also verify the local llama.cpp model is loaded.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check_async(args.llm)))


if __name__ == "__main__":
    main()
