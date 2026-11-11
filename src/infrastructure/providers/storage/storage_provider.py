"""Durable UUID-based original-file storage. Original names are never filesystem paths."""
from __future__ import annotations

import asyncio
from pathlib import Path
import os
from uuid import UUID, uuid4

from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


class StorageError(RuntimeError):
    pass


@inject
class StorageProvider:
    def __init__(self, config_reader: ConfigReader) -> None:
        root = config_reader.get("storage.path", "")
        if not isinstance(root, str):
            raise ValueError("Storage path must be a string")
        self._root = Path(root).resolve() if root.strip() else None

    def _locate(self, key: str) -> Path:
        # Stored keys are generated internally; defend against corrupted DB values.
        if self._root is None:
            raise StorageError("STORAGE_UNAVAILABLE")
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise StorageError("INVALID_STORAGE_KEY")
        return path

    async def save_async(self, document_id: str, extension: str, content: bytes) -> str:
        try:
            UUID(document_id)
        except ValueError as exc:
            raise StorageError("INVALID_DOCUMENT_ID") from exc
        if extension not in {"pdf", "txt", "doc", "docx", "json", "csv", "xlsx"}:
            raise StorageError("INVALID_STORAGE_EXTENSION")
        key = f"documents/originals/{document_id}/{uuid4().hex}.{extension}"
        destination = self._locate(key)

        def write() -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_suffix(destination.suffix + ".tmp")
            try:
                with temp.open("xb") as target:
                    target.write(content)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temp, destination)
            finally:
                temp.unlink(missing_ok=True)

        try:
            await asyncio.to_thread(write)
        except OSError as exc:
            raise StorageError("STORAGE_UNAVAILABLE") from exc
        return key

    async def read_async(self, key: str, limit: int) -> bytes:
        path = self._locate(key)

        def read() -> bytes:
            with path.open("rb") as source:
                result = source.read(limit + 1)
            if len(result) > limit:
                raise StorageError("DOCUMENT_TOO_LARGE")
            return result

        try:
            return await asyncio.to_thread(read)
        except OSError as exc:
            raise StorageError("STORAGE_UNAVAILABLE") from exc
