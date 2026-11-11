"""Bounded parsing of seven document formats; OCR and legacy Word use local binaries."""
from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from io import BytesIO, StringIO
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import BadZipFile, ZipFile

from src.infrastructure.di.inject import inject
from src.infrastructure.providers.document.text_pipeline import TextChunk
from src.infrastructure.utils.config_reader import ConfigReader


class DocumentProcessingError(RuntimeError):
    pass


@inject
class DocumentProcessor:
    SUPPORTED = frozenset({"pdf", "txt", "doc", "docx", "json", "csv", "xlsx"})

    def __init__(self, config_reader: ConfigReader) -> None:
        self._max_bytes = int(config_reader.get("ingestion.max_upload_bytes", 25 * 1024 * 1024))
        self._max_pages = int(config_reader.get("ingestion.max_pages", 300))
        self._max_rows = int(config_reader.get("ingestion.max_rows", 100000))
        self._ocr = config_reader.get("ingestion.ocr_enabled", True) is True
        self._ocr_language = str(config_reader.get("ingestion.ocr_language", "fas+eng"))
        if not 1024 <= self._max_bytes <= 100 * 1024 * 1024 or not 1 <= self._max_pages <= 1000 or not 1 <= self._max_rows <= 1000000:
            raise ValueError("Invalid ingestion limits")

    @property
    def max_upload_bytes(self) -> int:
        return self._max_bytes

    def validate(self, content: bytes, extension: str) -> None:
        if extension not in self.SUPPORTED or not content:
            raise DocumentProcessingError("UNSUPPORTED_DOCUMENT")
        if len(content) > self._max_bytes:
            raise DocumentProcessingError("DOCUMENT_TOO_LARGE")
        if extension == "pdf" and not content.startswith(b"%PDF-"):
            raise DocumentProcessingError("INVALID_PDF")
        if extension == "doc" and not content.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            raise DocumentProcessingError("INVALID_DOC")
        if extension in {"docx", "xlsx"}:
            self._validate_zip(content, extension)
        if extension in {"txt", "csv", "json"}:
            if b"\x00" in content[:4096]:
                raise DocumentProcessingError("INVALID_ENCODING")
            try:
                content.decode("utf-8-sig", errors="strict")
            except UnicodeDecodeError as exc:
                raise DocumentProcessingError("INVALID_ENCODING") from exc

    @staticmethod
    def _validate_zip(content: bytes, extension: str) -> None:
        if not content.startswith(b"PK"):
            raise DocumentProcessingError("INVALID_OFFICE_FILE")
        try:
            with ZipFile(BytesIO(content)) as archive:
                files = archive.infolist()
                if len(files) > 10000 or sum(x.file_size for x in files) > 150 * 1024 * 1024:
                    raise DocumentProcessingError("ZIP_LIMIT_EXCEEDED")
                if any(x.file_size > max(1024, x.compress_size) * 200 for x in files):
                    raise DocumentProcessingError("ZIP_LIMIT_EXCEEDED")
                required = "word/document.xml" if extension == "docx" else "xl/workbook.xml"
                if required not in archive.namelist():
                    raise DocumentProcessingError("INVALID_OFFICE_FILE")
        except (BadZipFile, OSError, RuntimeError) as exc:
            raise DocumentProcessingError("INVALID_OFFICE_FILE") from exc

    async def extract_async(self, content: bytes, extension: str) -> list[TextChunk]:
        self.validate(content, extension)
        try:
            sections = await asyncio.to_thread(self._extract, content, extension)
        except DocumentProcessingError:
            raise
        except Exception as exc:
            raise DocumentProcessingError("DOCUMENT_EXTRACTION_FAILED") from exc
        if not sections or not any(section.text.strip() for section in sections):
            raise DocumentProcessingError("DOCUMENT_EMPTY")
        return sections

    def _extract(self, content: bytes, extension: str) -> list[TextChunk]:
        if extension == "txt":
            return [TextChunk(content.decode("utf-8-sig"), {"section": "text"})]
        if extension == "json":
            data = json.loads(content.decode("utf-8-sig"))
            if not isinstance(data, (dict, list)):
                raise DocumentProcessingError("INVALID_JSON_STRUCTURE")
            return [TextChunk(json.dumps(data, ensure_ascii=False, indent=2), {"section": "json"})]
        if extension == "csv":
            reader = csv.reader(StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
            sections = []
            for number, row in enumerate(reader, 1):
                if number > self._max_rows:
                    raise DocumentProcessingError("ROW_LIMIT_EXCEEDED")
                if len(row) > 1000:
                    raise DocumentProcessingError("COLUMN_LIMIT_EXCEEDED")
                sections.append(TextChunk(" | ".join(row), {"row": number}))
            return sections
        if extension == "doc":
            if shutil.which("libreoffice") is None:
                raise DocumentProcessingError("DOC_CONVERTER_UNAVAILABLE")
            with tempfile.TemporaryDirectory() as directory:
                original = Path(directory) / "source.doc"
                original.write_bytes(content)
                profile = (Path(directory) / "profile").as_uri()
                outcome = subprocess.run(
                    ["libreoffice", "-env:UserInstallation=" + profile, "--headless",
                     "--convert-to", "docx", "--outdir", directory, str(original)],
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=90, check=False,
                )
                converted = original.with_suffix(".docx")
                if outcome.returncode or not converted.is_file():
                    raise DocumentProcessingError("DOC_CONVERSION_FAILED")
                converted_content = converted.read_bytes()
                self._validate_zip(converted_content, "docx")
                return self._extract(converted_content, "docx")
        if extension == "docx":
            from docx import Document
            document = Document(BytesIO(content))
            sections: list[TextChunk] = []
            for number, paragraph in enumerate(document.paragraphs, 1):
                if paragraph.text.strip():
                    sections.append(TextChunk(paragraph.text, {"paragraph": number}))
            for number, table in enumerate(document.tables, 1):
                for row_index, row in enumerate(table.rows, 1):
                    sections.append(TextChunk(" | ".join(cell.text for cell in row.cells),
                                              {"table": number, "row": row_index}))
                    if len(sections) > self._max_rows:
                        raise DocumentProcessingError("ROW_LIMIT_EXCEEDED")
            return sections
        if extension == "xlsx":
            from openpyxl import load_workbook
            workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
            try:
                sections = []
                for sheet in workbook:
                    for number, row in enumerate(sheet.iter_rows(values_only=True), 1):
                        if number > self._max_rows or len(sections) >= self._max_rows:
                            raise DocumentProcessingError("ROW_LIMIT_EXCEEDED")
                        if len(row) > 1000:
                            raise DocumentProcessingError("COLUMN_LIMIT_EXCEEDED")
                        text = " | ".join("" if value is None else str(value) for value in row)
                        if text.strip(" |"):
                            sections.append(TextChunk(text, {"sheet": sheet.title, "row": number}))
                return sections
            finally:
                workbook.close()
        if extension == "pdf":
            import fitz
            import pytesseract
            from PIL import Image
            sections = []
            with fitz.open(stream=content, filetype="pdf") as document:
                if len(document) > self._max_pages:
                    raise DocumentProcessingError("PAGE_LIMIT_EXCEEDED")
                for number, page in enumerate(document, 1):
                    text = page.get_text("text")
                    if len(text.strip()) < 20 and self._ocr:
                        try:
                            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                            text = pytesseract.image_to_string(image, lang=self._ocr_language,
                                                               config="--psm 3", timeout=45)
                        except (RuntimeError, pytesseract.TesseractError, pytesseract.TesseractNotFoundError) as exc:
                            raise DocumentProcessingError("OCR_UNAVAILABLE") from exc
                    if not text.strip():
                        raise DocumentProcessingError("PDF_PAGE_EMPTY")
                    sections.append(TextChunk(text, {"page": number}))
            return sections
        raise DocumentProcessingError("UNSUPPORTED_DOCUMENT")
