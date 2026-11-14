"""Document ingestion, version-safe index lifecycle and permissioned hybrid retrieval."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import logging
from uuid import NAMESPACE_URL, uuid5

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.errors import PermissionDenied, ResourceConflict, ResourceNotFound
from src.infrastructure.di.inject import inject
from src.infrastructure.providers.document.document_processor import DocumentProcessor, DocumentProcessingError
from src.infrastructure.providers.document.text_pipeline import chunk_sections, sparse_keywords
from src.infrastructure.providers.embedding.embedding_provider import EmbeddingProvider
from src.infrastructure.providers.reranking.reranking_provider import RerankingProvider
from src.infrastructure.providers.storage.storage_provider import StorageProvider
from src.infrastructure.providers.vector_db.qdrant_provider import QdrantProvider
from src.infrastructure.repositories.knowledge.knowledge_repository import KnowledgeRepository
from src.infrastructure.utils.config_reader import ConfigReader

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(rankings: list[list[dict]], k: int = 60) -> list[dict]:
    if k < 1:
        raise ValueError("Invalid RRF constant")
    scores: dict[str, float] = defaultdict(float)
    objects: dict[str, dict] = {}
    for result in rankings:
        seen: set[str] = set()
        for rank, candidate in enumerate(result, 1):
            point_id = str(candidate.get("id", ""))
            if not point_id or point_id in seen:
                continue
            seen.add(point_id)
            objects[point_id] = candidate
            scores[point_id] += 1 / (k + rank)
    return [dict(objects[key], rrf_score=score) for key, score in
            sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


@inject
class KnowledgeIndexService:
    def __init__(
        self, knowledge_repository: KnowledgeRepository, document_processor: DocumentProcessor,
        storage_provider: StorageProvider, embedding_provider: EmbeddingProvider,
        reranking_provider: RerankingProvider, qdrant_provider: QdrantProvider,
        config_reader: ConfigReader,
    ) -> None:
        self._documents = knowledge_repository
        self._processor = document_processor
        self._storage = storage_provider
        self._embedding = embedding_provider
        self._reranking = reranking_provider
        self._vectors = qdrant_provider
        self._chunk_size = int(config_reader.get("ingestion.chunk_length", 512))
        self._overlap = int(config_reader.get("ingestion.chunk_overlap", 64))
        self._max_chunks = int(config_reader.get("ingestion.max_chunks", 1024))
        self._stale_minutes = int(config_reader.get("ingestion.stale_processing_minutes", 180))
        self._first_stage = int(config_reader.get("retrieval.first_stage", 20))
        self._final = int(config_reader.get("retrieval.final", 5))
        # Optional second-stage budget: default retains existing full reranking.
        self._rerank_candidates = int(config_reader.get("retrieval.rerank_candidates", self._first_stage))
        self._rrf_k = int(config_reader.get("retrieval.rrf_k", 60))
        if not (16 <= self._chunk_size <= 4096 and 0 <= self._overlap < self._chunk_size
                and 1 <= self._max_chunks <= 10000 and 10 <= self._stale_minutes <= 1440
                and 1 <= self._final <= self._rerank_candidates <= self._first_stage <= 100
                and 1 <= self._rrf_k <= 1000):
            raise ValueError("Invalid ingestion/retrieval configuration")

    async def _owned_async(self, identity: ChatIdentity, document_id: str):
        document = await self._documents.get_scoped_async(document_id, identity.subject, identity.audience)
        if document is None or document.tenant_id != identity.tenant_id:
            raise ResourceNotFound("Document not found")
        return document

    async def ingest_async(
        self, identity: ChatIdentity, document_id: str, filename: str | None,
        content: bytes | None, replace: bool = False, retry: bool = False, reindex: bool = False,
    ):
        if "knowledge:write" not in identity.permissions:
            raise PermissionDenied("Knowledge write permission required")
        document = await self._owned_async(identity, document_id)
        if retry and reindex:
            raise ResourceConflict("Retry and reindex cannot be combined")
        if reindex:
            if document.status != "approved" or not document.storage_key or not document.checksum:
                raise ResourceConflict("No indexed original available for reindex")
            content = await self._storage.read_async(document.storage_key,
                                                     self._processor.max_upload_bytes)
            checksum = sha256(content).hexdigest()
            if checksum != document.checksum:
                raise ResourceConflict("Indexed file checksum mismatch")
            storage_key = document.storage_key
            replace = True
        elif retry:
            if not document.pending_storage_key or not document.pending_checksum:
                raise ResourceConflict("No pending file available")
            content = await self._storage.read_async(document.pending_storage_key,
                                                     self._processor.max_upload_bytes)
            checksum = sha256(content).hexdigest()
            if checksum != document.pending_checksum:
                raise ResourceConflict("Pending file changed")
            storage_key = document.pending_storage_key
            replace = document.status == "approved"
        else:
            if content is None or not filename or "/" in filename or "\\" in filename or any(ord(x) < 32 for x in filename):
                raise DocumentProcessingError("INVALID_FILENAME")
            if not filename.lower().endswith("." + document.source_type):
                raise DocumentProcessingError("FILE_TYPE_MISMATCH")
            checksum = sha256(content).hexdigest()
            storage_key = None
        self._processor.validate(content, document.source_type)
        if document.status == "approved" and not replace:
            raise ResourceConflict("Replacement requires explicit request")
        if document.status != "approved" and replace:
            raise ResourceConflict("Document has no current indexed version")
        if document.status == "approved" and document.checksum == checksum and not (reindex or retry):
            raise ResourceConflict("Content already indexed")
        if await self._documents.find_duplicate_async(identity.subject, identity.audience, checksum, document.id):
            raise ResourceConflict("Duplicate document")
        if not await self._documents.claim_processing_async(
            document.id, identity.subject, identity.audience, document.version, self._stale_minutes
        ):
            raise ResourceConflict("Document processing already active")
        previous_version = document.version
        new_version = previous_version + 1 if replace else previous_version
        try:
            if storage_key is None:
                storage_key = await self._storage.save_async(document.id, document.source_type, content)
            await self._documents.mark_pending_async(document.id, storage_key, checksum)
            sections = await self._processor.extract_async(content, document.source_type)
            chunks = chunk_sections(sections, size=self._chunk_size, overlap=self._overlap)
            if not chunks or len(chunks) > self._max_chunks:
                raise DocumentProcessingError("INVALID_CHUNK_COUNT")
            vectors = await self._embedding.embed_async([chunk.text for chunk in chunks])
            await self._vectors.ensure_collection_async(document.audience, self._embedding.dimension,
                                                        self._embedding.model_version)
            point_ids: list[str] = []
            for start in range(0, len(chunks), 16):
                points = []
                for offset in range(start, min(start + 16, len(chunks))):
                    chunk = chunks[offset]
                    point_id = str(uuid5(NAMESPACE_URL, f"{document.id}:{new_version}:{offset}"))
                    point_ids.append(point_id)
                    points.append({
                        "id": point_id,
                        "vector": {"dense": vectors[offset], "lexical": sparse_keywords(chunk.text)},
                        "payload": {
                            "document_id": document.id, "chunk_id": point_id,
                            "version": new_version, "text": chunk.text,
                            "location": chunk.location, "source_uri": document.source_uri,
                            "title": document.title, "audience": document.audience,
                            "owner_id": document.owner_id, "tenant_id": document.tenant_id or "",
                            "classification": document.classification or "",
                            "published": document.published, "active": True,
                            "embedding_model_version": self._embedding.model_version,
                        },
                    })
                await self._vectors.upsert_async(document.audience, points)
            success = await self._documents.complete_index_async(
                document.id, previous_version, new_version, storage_key, checksum,
                self._embedding.model_version, point_ids,
                {"sections": len(sections), "chunks": len(chunks)},
            )
            if not success:
                raise ResourceConflict("Document changed during indexing")
            if replace:
                try:
                    await self._vectors.deactivate_version_async(document.audience, document.id, previous_version)
                except Exception:
                    # SQL version validation is authoritative; stale vectors cannot be served.
                    logger.warning("Non-destructive old index deactivation deferred for document %s", document.id)
            return await self._owned_async(identity, document.id)
        except Exception as exc:
            await self._documents.mark_failed_async(
                document.id, getattr(exc, "code", type(exc).__name__.upper())[:64]
            )
            raise

    async def publish_async(self, identity: ChatIdentity, document_id: str):
        if "knowledge:publish" not in identity.permissions:
            raise PermissionDenied("Publishing requires explicit permission")
        doc = await self._owned_async(identity, document_id)
        if doc.audience != "public" or doc.status != "approved" or doc.classification is not None:
            raise PermissionDenied("Document cannot be published")
        # Set Qdrant before PostgreSQL; PostgreSQL remains the authorization source of truth.
        await self._vectors.set_publication_async(doc.id, doc.version)
        if not await self._documents.publish_async(doc.id, identity.subject):
            raise ResourceConflict("Publication state changed")
        return await self._owned_async(identity, document_id)

    async def retrieve_async(self, identity: ChatIdentity, query: str) -> list[dict]:
        if identity.audience not in {"public", "internal"}:
            raise PermissionDenied("Invalid identity audience")
        if identity.audience == "internal" and (not identity.tenant_id or "knowledge:read_internal" not in identity.permissions):
            raise PermissionDenied("Internal retrieval requires tenant and explicit permission")
        if not isinstance(query, str) or not query.strip() or len(query) > 2048:
            raise ValueError("Invalid query")
        embedding = (await self._embedding.embed_async([query]))[0]
        sparse = sparse_keywords(query)
        scopes = ["public"] if identity.audience == "public" else ["internal"]
        if identity.audience == "internal" and "knowledge:read_public" in identity.permissions:
            scopes.append("public")
        rankings = []
        for scope in scopes:
            must = [
                {"key": "audience", "match": {"value": scope}},
                {"key": "active", "match": {"value": True}},
                {"key": "embedding_model_version", "match": {"value": self._embedding.model_version}},
            ]
            if scope == "internal":
                must.append({"key": "tenant_id", "match": {"value": identity.tenant_id or ""}})
                if "knowledge:read_internal" not in identity.permissions:
                    must.append({"key": "owner_id", "match": {"value": identity.subject}})
                filters = {"must": must}
            else:
                filters = {"must": must, "should": [
                    {"key": "published", "match": {"value": True}},
                    {"key": "owner_id", "match": {"value": identity.subject}},
                ]}
            rankings.append(await self._vectors.query_async(
                scope, embedding, "dense", filters, self._first_stage
            ))
            if sparse["indices"]:
                rankings.append(await self._vectors.query_async(
                    scope, sparse, "lexical", filters, self._first_stage
                ))
        candidates = reciprocal_rank_fusion(rankings, self._rrf_k)
        visible = await self._documents.visible_async(
            list({str(item.get("payload", {}).get("document_id", "")) for item in candidates}), identity
        )
        valid = []
        for candidate in candidates:
            payload = candidate.get("payload", {})
            doc = visible.get(str(payload.get("document_id")))
            if (doc is not None and doc.version == payload.get("version")
                    and doc.embedding_model_version == payload.get("embedding_model_version")
                    and doc.audience == payload.get("audience")
                    and str(candidate.get("id")) in (doc.chunk_ids or [])
                    and isinstance(payload.get("text"), str)):
                valid.append(candidate)
            if len(valid) >= self._first_stage:
                break
        if not valid:
            return []
        # Only the highest fused, authorized candidates enter the CPU-heavy cross-encoder.
        # Keep the original RRF ordering and full text/citations; never bypass reranking.
        valid = valid[:self._rerank_candidates]
        reranked = await self._reranking.rerank_async(query, [item["payload"]["text"] for item in valid])
        results = []
        for position, score in reranked[:self._final]:
            item = valid[position]
            payload = item["payload"]
            results.append({
                "chunk_id": str(item["id"]), "document_id": payload["document_id"],
                "version": payload["version"], "text": payload["text"],
                "source_location": payload.get("location", {}),
                "source_uri": payload.get("source_uri"), "title": payload.get("title"),
                "score": score, "rrf_score": item["rrf_score"],
            })
        return results
