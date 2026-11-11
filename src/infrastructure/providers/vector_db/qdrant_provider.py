"""Restricted Qdrant REST API; never drop or recreate incompatible collections."""
from __future__ import annotations

import httpx

from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


class VectorIndexError(RuntimeError):
    pass


@inject
class QdrantProvider:
    def __init__(self, config_reader: ConfigReader) -> None:
        url = config_reader.get("vector.url")
        if not isinstance(url, str) or (url and not url.startswith(("http://", "https://"))):
            raise ValueError("Qdrant URL is not configured; set CHATBOT_QDRANT_URL")
        self._base_url = url.rstrip("/")
        self._timeout = float(config_reader.get("vector.timeout_seconds", 5))
        if not 0 < self._timeout <= 120:
            raise ValueError("Qdrant timeout must be between 0 and 120 seconds")
        self._public = str(config_reader.get("vector.public_collection", "knowledge_public"))
        self._internal = str(config_reader.get("vector.internal_collection", "knowledge_internal"))
        self._api_key = str(config_reader.get("vector.api_key", ""))

    def collection(self, audience: str) -> str:
        if audience == "public":
            return self._public
        if audience == "internal":
            return self._internal
        raise VectorIndexError("INVALID_AUDIENCE")

    async def _request_async(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not self._base_url:
            raise VectorIndexError("VECTOR_UNAVAILABLE")
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, trust_env=False,
                headers={"api-key": self._api_key} if self._api_key else {},
            ) as client:
                response = await client.request(method, f"{self._base_url}{path}", json=payload)
                if response.status_code == 404:
                    raise VectorIndexError("VECTOR_NOT_FOUND")
                if not 200 <= response.status_code < 300:
                    raise VectorIndexError("VECTOR_UNAVAILABLE")
                result = response.json()
                if not isinstance(result, dict) or result.get("status") == "error":
                    raise VectorIndexError("VECTOR_INVALID_RESPONSE")
                return result
        except (httpx.RequestError, ValueError, TypeError) as exc:
            raise VectorIndexError("VECTOR_UNAVAILABLE") from exc

    async def check_ready_async(self) -> bool:
        if not self._base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                response = await client.get(f"{self._base_url}/readyz")
                return response.status_code == 200
        except httpx.RequestError:
            return False

    async def check_api_async(self) -> bool:
        try:
            payload = await self._request_async("GET", "/collections")
            return isinstance(payload.get("result", {}).get("collections"), list)
        except (VectorIndexError, AttributeError):
            return False

    async def ensure_collection_async(self, audience: str, dimension: int, model_version: str) -> None:
        name = self.collection(audience)
        try:
            info = await self._request_async("GET", f"/collections/{name}")
        except VectorIndexError as exc:
            if str(exc) != "VECTOR_NOT_FOUND":
                raise
            await self._request_async("PUT", f"/collections/{name}", {
                "vectors": {"dense": {"size": dimension, "distance": "Cosine"}},
                "sparse_vectors": {"lexical": {}},
            })
            info = await self._request_async("GET", f"/collections/{name}")
        try:
            params = info["result"]["config"]["params"]
            dense = params["vectors"]["dense"]
            assert dense["size"] == dimension and dense["distance"].lower() == "cosine"
            assert "lexical" in params["sparse_vectors"]
        except (KeyError, TypeError, AttributeError, AssertionError) as exc:
            raise VectorIndexError("VECTOR_SCHEMA_MISMATCH") from exc
        # Server-side scan for ANY different/missing version, not only the first point.
        # This avoids mixing incompatible embeddings when a collection is partially indexed.
        points = await self._request_async("POST", f"/collections/{name}/points/scroll", {
            "limit": 1,
            "filter": {"must_not": [{"key": "embedding_model_version",
                                    "match": {"value": model_version}}]},
            "with_payload": ["embedding_model_version"], "with_vector": False,
        })
        incompatible = points.get("result", {}).get("points", [])
        if incompatible:
            raise VectorIndexError("VECTOR_MODEL_MISMATCH")

    async def upsert_async(self, audience: str, points: list[dict]) -> None:
        if not points:
            raise VectorIndexError("VECTOR_EMPTY_BATCH")
        result = await self._request_async(
            "PUT", f"/collections/{self.collection(audience)}/points?wait=true", {"points": points}
        )
        if result.get("result", {}).get("status") not in ("completed",):
            raise VectorIndexError("VECTOR_NOT_COMMITTED")

    async def query_async(
        self, audience: str, vector: list[float] | dict, using: str, filters: dict, limit: int
    ) -> list[dict]:
        if using not in ("dense", "lexical") or not 1 <= limit <= 100:
            raise VectorIndexError("INVALID_VECTOR_QUERY")
        result = await self._request_async(
            "POST", f"/collections/{self.collection(audience)}/points/query", {
                "query": vector, "using": using, "filter": filters,
                "limit": limit, "with_payload": True, "with_vector": False,
            }
        )
        points = result.get("result", {}).get("points")
        if not isinstance(points, list):
            raise VectorIndexError("VECTOR_INVALID_RESPONSE")
        return points

    async def deactivate_version_async(self, audience: str, document_id: str, version: int) -> None:
        # Non-destructive lifecycle transition. Points remain available for audit/recovery.
        await self._request_async(
            "POST", f"/collections/{self.collection(audience)}/points/payload?wait=true", {
                "payload": {"active": False},
                "filter": {"must": [
                    {"key": "document_id", "match": {"value": document_id}},
                    {"key": "version", "match": {"value": version}},
                ]},
            },
        )

    async def set_publication_async(self, document_id: str, version: int) -> None:
        await self._request_async(
            "POST", f"/collections/{self._public}/points/payload?wait=true", {
                "payload": {"published": True},
                "filter": {"must": [
                    {"key": "document_id", "match": {"value": document_id}},
                    {"key": "version", "match": {"value": version}},
                ]},
            },
        )
