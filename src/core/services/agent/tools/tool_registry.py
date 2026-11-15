"""Server-owned, permissioned read-only agent tools with strict Pydantic contracts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.knowledge.knowledge_service import KnowledgeService
from src.core.services.rag.rag_service import RagService
from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


class AgentToolError(RuntimeError):
    """Sanitized, non-sensitive tool error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SearchKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=3, max_length=500)


class ListOwnedDocumentsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    limit: int = Field(default=5, ge=1, le=10)


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    chunk_id: UUID
    title: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    source_location: dict[str, str | int] = Field(default_factory=dict)


class SearchKnowledgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence: str = Field(max_length=8192)
    sources: list[SourceRecord] = Field(max_length=10)


class OwnedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    title: str = Field(min_length=1, max_length=200)
    status: str = Field(pattern="^(registered|processing|failed|approved)$")
    version: int = Field(ge=1)


class ListOwnedDocumentsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[OwnedDocument] = Field(max_length=10)
    has_more: bool


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    output_schema: type[BaseModel]
    scenario: str = "agent_qa"


@inject
class AgentToolRegistry:
    """Only hardcoded operations are callable; model output never becomes code or scope."""

    _TOOLS = (
        ToolSpec("search_knowledge", "Search authorized knowledge and return excerpts with citations.",
                 SearchKnowledgeArgs, SearchKnowledgeOutput),
        ToolSpec("list_owned_documents", "List metadata for documents owned by the authenticated user.",
                 ListOwnedDocumentsArgs, ListOwnedDocumentsOutput),
    )

    def __init__(self, rag_service: RagService, knowledge_service: KnowledgeService,
                 config_reader: ConfigReader) -> None:
        self._rag = rag_service
        self._knowledge = knowledge_service
        self._max_bytes = int(config_reader.get("agent.max_tool_output_size", 3072))
        if not 256 <= self._max_bytes <= 16384:
            raise ValueError("agent.max_tool_output_size must be between 256 and 16384")

    @staticmethod
    def _allowed(identity: ChatIdentity, scenario: str) -> bool:
        if not isinstance(identity, ChatIdentity) or not identity.subject.strip():
            return False
        if scenario != "agent_qa" or identity.audience not in {"public", "internal"}:
            return False
        if identity.audience == "internal":
            return bool(identity.tenant_id and identity.tenant_id.strip()
                        and "knowledge:read_internal" in identity.permissions)
        return identity.tenant_id is None

    def available(self, identity: ChatIdentity, scenario: str) -> list[dict[str, Any]]:
        if not self._allowed(identity, scenario):
            return []
        return [{"name": tool.name, "description": tool.description,
                 "parameters": tool.args_schema.model_json_schema()}
                for tool in self._TOOLS if tool.scenario == scenario]

    async def run_async(self, name: str, arguments: dict[str, Any],
                        identity: ChatIdentity, scenario: str) -> dict[str, Any]:
        if not self._allowed(identity, scenario):
            raise AgentToolError("AGENT_TOOL_DENIED")
        tool = next((tool for tool in self._TOOLS if tool.name == name and tool.scenario == scenario), None)
        if tool is None:
            raise AgentToolError("AGENT_INVALID_TOOL")
        try:
            validated = tool.args_schema.model_validate(arguments)
        except (ValidationError, ValueError, TypeError) as exc:
            raise AgentToolError("AGENT_INVALID_ARGUMENTS") from exc
        try:
            if name == "search_knowledge":
                context = await self._rag.prepare_async(identity, validated.query)
                output = {"evidence": context.evidence, "sources": list(context.sources)}
            elif name == "list_owned_documents":
                documents, more = await self._knowledge.list_async(identity, validated.limit, 0)
                output = {"items": [{"document_id": doc.id, "title": doc.title,
                                     "status": doc.status, "version": doc.version}
                                    for doc in documents], "has_more": more}
            else:
                raise AgentToolError("AGENT_INVALID_TOOL")
            result = tool.output_schema.model_validate(output).model_dump(mode="json")
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > self._max_bytes:
                raise AgentToolError("AGENT_TOOL_OUTPUT_LIMIT")
            return result
        except AgentToolError:
            raise
        except Exception as exc:
            raise AgentToolError("AGENT_TOOL_FAILED") from exc
