"""Prevent Windows PowerShell 5.1 from corrupting UTF-8 Persian in .ps1 source."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_sse_smoke_script_prompt_is_codepage_independent():
    source = (ROOT / "scripts" / "test-chat-stream.ps1").read_bytes()
    # Windows PowerShell 5.1 treats BOM-less .ps1 source as legacy ANSI.
    # ASCII-only source with JSON Unicode escapes is consistent in PS 5.1 and 7.
    assert source.isascii()
    match = re.search(r"(?m)^\s*\$Body = '(\{.+\})'\s*$", source.decode("ascii"))
    assert match, "Expected one literal JSON body with Unicode escape sequences"
    body = match.group(1)
    assert r"\u0633" in body
    assert json.loads(body) == {"message": "سلام، لطفاً در دو جمله به فارسی پاسخ بده."}


def test_sse_client_explicitly_decodes_utf8_network_response():
    source = (ROOT / "scripts" / "test-chat-stream.ps1").read_text(encoding="ascii")
    assert "[System.Text.Encoding]::UTF8" in source
    assert "ReadAsStreamAsync()" in source
