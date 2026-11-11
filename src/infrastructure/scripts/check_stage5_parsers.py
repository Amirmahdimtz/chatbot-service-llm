"""Container smoke test: real local .doc conversion and scanned-PDF OCR, synthetic only."""
from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
import subprocess
import tempfile

import fitz
from docx import Document
from PIL import Image, ImageDraw, ImageFont

from src.infrastructure.providers.document.document_processor import DocumentProcessor
from src.infrastructure.utils.config_reader import ConfigReader


async def main_async() -> None:
    processor = DocumentProcessor(ConfigReader())
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        document = Document()
        document.add_paragraph("Synthetic legacy Word document content.")
        docx_file = folder / "sample.docx"
        document.save(str(docx_file))
        result = subprocess.run(
            ["libreoffice", "-env:UserInstallation=" + (folder / "profile1").as_uri(),
             "--headless", "--convert-to", "doc", "--outdir", directory, str(docx_file)],
            capture_output=True, timeout=120, check=False,
        )
        doc_file = folder / "sample.doc"
        if result.returncode != 0 or not doc_file.exists():
            raise RuntimeError("Could not create synthetic .doc fixture using LibreOffice")
        old_word = await processor.extract_async(doc_file.read_bytes(), "doc")
        if not any("Synthetic legacy Word" in x.text for x in old_word):
            raise RuntimeError("Legacy Word extraction did not preserve test text")

        image = Image.new("RGB", (1100, 250), "white")
        painter = ImageDraw.Draw(image)
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        font = ImageFont.truetype(font_path, 70)
        painter.text((45, 70), "TEST DOCUMENT 123", fill="black", font=font)
        target = BytesIO()
        image.save(target, format="PNG")
        pdf = fitz.open()
        page = pdf.new_page(width=550, height=125)
        page.insert_image(page.rect, stream=target.getvalue())
        scanned = pdf.tobytes()
        pdf.close()
        result = await processor.extract_async(scanned, "pdf")
        if "TEST" not in result[0].text.upper():
            raise RuntimeError("Scanned PDF OCR did not recognize synthetic text")
    print("stage5-local-doc-and-ocr: passed")


if __name__ == "__main__":
    asyncio.run(main_async())
