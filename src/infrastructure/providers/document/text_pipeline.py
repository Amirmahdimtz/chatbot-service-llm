"""Persian-safe normalization, location-aware chunking, and lexical sparse vectors."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import math
import re
import unicodedata

WORD = re.compile(r"[\w\u200c]+", re.UNICODE)
TOKEN = re.compile(r"[\w\u200c]+|[^\w\s]", re.UNICODE)
TRANSLATION = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی", "\u00a0": " ", "\u200f": "", "\u200e": "", "\ufeff": ""})


@dataclass(frozen=True)
class TextChunk:
    text: str
    location: dict[str, object]


def normalize_persian(text: str) -> str:
    text = unicodedata.normalize("NFC", text.translate(TRANSLATION))
    text = "".join(char for char in text if char in "\n\t\u200c" or unicodedata.category(char)[0] != "C")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<!\w)\u200c|\u200c(?!\w)", "", text)
    return text.strip()


def token_count(text: str) -> int:
    """Approximate lexical-token count (not model BPE tokens); config is a budget estimate."""
    return len(TOKEN.findall(text))


def chunk_sections(sections: list[TextChunk], size: int = 512, overlap: int = 64) -> list[TextChunk]:
    if size < 16 or overlap < 0 or overlap >= size:
        raise ValueError("Invalid chunk length or overlap")
    chunks: list[TextChunk] = []
    for section in sections:
        text = normalize_persian(section.text)
        if not text:
            continue
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        current: list[str] = []
        count = 0

        def flush() -> None:
            nonlocal current, count
            if current:
                value = "\n\n".join(current).strip()
                if value:
                    chunks.append(TextChunk(value, dict(section.location)))
            current, count = [], 0

        for paragraph in paragraphs:
            parts = TOKEN.findall(paragraph)
            if len(parts) > size:
                flush()
                step = size - overlap
                for start in range(0, len(parts), step):
                    piece = parts[start:start + size]
                    if piece:
                        chunks.append(TextChunk(" ".join(piece), dict(section.location)))
                    if start + size >= len(parts):
                        break
                continue
            if count + len(parts) > size:
                flush()
            current.append(paragraph)
            count += len(parts)
        flush()
    return chunks


def sparse_keywords(text: str) -> dict[str, list[int] | list[float]]:
    """Stable hashed lexical term-frequency vector; identical for index and search."""
    words = WORD.findall(normalize_persian(text).lower())
    counts = Counter(int.from_bytes(sha256(word.encode("utf-8")).digest()[:4], "big") for word in words if len(word) > 1)
    indices = sorted(counts)
    weights = [1.0 + math.log(counts[index]) for index in indices]
    norm = math.sqrt(sum(x * x for x in weights)) or 1.0
    return {"indices": indices, "values": [x / norm for x in weights]}
