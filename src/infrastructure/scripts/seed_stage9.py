"""Validate and optionally seed Stage 9 synthetic records into an isolated database only.

Default invocation is read-only. Never touches production DBs or Qdrant.
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from pydantic import ValidationError
from sqlalchemy.engine import make_url

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.scenarios.scenario_contracts import RECORD_TYPES, SCENARIO_INPUTS

FIXTURE = Path(__file__).resolve().parents[3] / "benchmarks" / "stage9_scenarios_fa.json"
SCENARIOS = frozenset({"religious_qa", *SCENARIO_INPUTS})
SEED_SUBJECT = "stage9-synthetic-seeder"


class FixtureError(ValueError):
    """Invalid synthetic data or unsafe seed destination."""


def load_fixture(path: Path = FIXTURE) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise FixtureError("Fixture must contain valid UTF-8 JSON") from exc
    if not isinstance(data, dict) or set(data) != {
        "schema_version", "dataset_id", "tenant_id", "description", "records", "cases"
    }:
        raise FixtureError("Unexpected fixture shape")
    if (data["schema_version"] != 1 or data["dataset_id"] != "stage9-persian-synthetic-v1"
            or data["tenant_id"] != "stage9-synthetic"):
        raise FixtureError("Unexpected fixture version or tenant")
    if not isinstance(data["description"], str) or not data["description"].strip():
        raise FixtureError("Missing fixture description")
    if not isinstance(data["records"], list) or not isinstance(data["cases"], list):
        raise FixtureError("Records and cases must be lists")
    seen: set[tuple[str, str, str]] = set()
    for row in data["records"]:
        if not isinstance(row, dict) or set(row) not in (
            {"kind", "key", "payload"}, {"kind", "key", "audience", "payload"}
        ):
            raise FixtureError("Invalid record shape")
        kind, key = row["kind"], row["key"]
        audience = row.get("audience", "internal")
        if (not isinstance(kind, str) or kind not in RECORD_TYPES
                or not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key) is None
                or audience not in {"internal", "public"}
                or (audience == "public" and kind != "faq")):
            raise FixtureError("Unsafe or invalid record scope")
        unique = (audience, kind, key)
        if unique in seen:
            raise FixtureError("Duplicate record scope/key")
        seen.add(unique)
        try:
            RECORD_TYPES[kind].model_validate(row["payload"])
        except (ValidationError, TypeError) as exc:
            raise FixtureError("Invalid record payload: " + kind + "/" + key) from exc
    case_names: set[str] = set()
    seen_scenarios: set[str] = set()
    for case in data["cases"]:
        if not isinstance(case, dict):
            raise FixtureError("Invalid case entry")
        scenario = case.get("scenario")
        if scenario not in SCENARIOS or not isinstance(case.get("name"), str):
            raise FixtureError("Unknown scenario or case name")
        if case["name"] in case_names or not re.fullmatch(r"[a-z0-9_]{3,64}", case["name"]):
            raise FixtureError("Duplicate or malformed case name")
        case_names.add(case["name"])
        seen_scenarios.add(scenario)
        if not isinstance(case.get("message"), str) or not case["message"].strip():
            raise FixtureError("Missing case message")
        if scenario == "religious_qa":
            if (set(case) not in (
                {"scenario", "name", "message", "expected_response_type"},
                {"scenario", "name", "message", "expected_response_type", "expected_source_reference"},
            ) or case["expected_response_type"] not in {"verified_faq", "insufficient_evidence"}):
                raise FixtureError("Invalid religious case")
        else:
            if (not {"scenario", "name", "message", "scenario_input", "expected_status",
                     "expected_ids"}.issubset(case)
                    or not set(case).issubset({"scenario", "name", "message", "scenario_input",
                                               "expected_status", "expected_ids", "excluded_ids"})
                    or case["expected_status"] not in {"completed", "insufficient_data", "conflict"}
                    or not isinstance(case["expected_ids"], list)
                    or not all(isinstance(x, str) and x for x in case["expected_ids"])
                    or not isinstance(case.get("excluded_ids", []), list)):
                raise FixtureError("Invalid structured case")
            try:
                SCENARIO_INPUTS[scenario].model_validate(case["scenario_input"])
            except (ValidationError, TypeError) as exc:
                raise FixtureError("Invalid scenario input") from exc
    if seen_scenarios != SCENARIOS:
        raise FixtureError("Every scenario requires evaluation cases")
    return data, sha256(raw).hexdigest()


def require_isolated_database(url: str) -> str:
    """The marker and dedicated name are mandatory, even for disposable SQLite."""
    if os.getenv("CHATBOT_STAGE9_ISOLATED") != "1":
        raise FixtureError("Set CHATBOT_STAGE9_ISOLATED=1 explicitly")
    try:
        parsed = make_url(url)
    except Exception as exc:
        raise FixtureError("Invalid test database URL") from exc
    db = parsed.database or ""
    if parsed.get_backend_name() == "sqlite":
        name = Path(db.replace("\\", "/")).name
        if (name.startswith("stage9_") and name.endswith((".sqlite", ".sqlite3", ".db"))
                and db not in ("", ":memory:")):
            return url
    if parsed.get_backend_name() == "postgresql":
        if (re.fullmatch(r"chatbot_stage9_[a-z0-9_]{2,40}", db)
                and parsed.host in {"postgres", "localhost", "127.0.0.1"}):
            return url
    raise FixtureError("Refusing a database outside the dedicated Stage 9 test namespace")


async def seed_async(url: str, fixture: dict) -> dict[str, int]:
    require_isolated_database(url)
    # The seed runner is a standalone composition root; no app or development identity bypass.
    os.environ["CHATBOT_DATABASE_URL"] = url
    os.environ["ENV_TYPE"] = "development"
    from src.infrastructure.di.inject import install_providers, resolve
    from src.infrastructure.di.reflection import discover_providers
    from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
    from src.infrastructure.repositories.scenario.scenario_repository import ScenarioRepository
    from src.core.services.scenarios.scenario_service import ScenarioService

    install_providers(discover_providers())
    repo = resolve(ScenarioRepository)
    service = resolve(ScenarioService)
    context = resolve(PsqlDbContext)
    identity = ChatIdentity(
        SEED_SUBJECT, "internal", frozenset({"scenario:manage", "religious:verify"}),
        fixture["tenant_id"],
    )
    created, unchanged, updated = 0, 0, 0
    try:
        for row in fixture["records"]:
            audience = row.get("audience", "internal")
            tenant = "" if audience == "public" else fixture["tenant_id"]
            expected = RECORD_TYPES[row["kind"]].model_validate(row["payload"]).model_dump(mode="json")
            previous = await repo.get_scoped_async(audience, tenant, row["kind"], row["key"])
            if previous is not None:
                if previous.owner_id != SEED_SUBJECT:
                    raise FixtureError("Refusing to replace a record not owned by the synthetic seed")
                if previous.payload == expected and previous.verified == (row["kind"] == "faq"):
                    unchanged += 1
                    continue
            await service.upsert_record_async(identity, row["kind"], row["key"], expected, audience)
            if previous is None:
                created += 1
            else:
                updated += 1
        return {"created": created, "unchanged": unchanged, "updated": updated}
    finally:
        await context.dispose_async()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--seed", action="store_true", help="Only for a migrated isolated Stage 9 database")
    args = parser.parse_args()
    fixture, digest = load_fixture(args.fixture)
    report = {"sha256": digest, "records": len(fixture["records"]), "cases": len(fixture["cases"])}
    if args.seed:
        url = os.getenv("CHATBOT_STAGE9_TEST_DATABASE_URL", "")
        require_isolated_database(url)
        report["seed"] = asyncio.run(seed_async(url, fixture))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
