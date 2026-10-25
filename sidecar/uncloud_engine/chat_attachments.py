"""Local document extraction for Chat, independent of model vision support."""
from __future__ import annotations

import codecs
import zipfile
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARACTERS = 120_000
MAX_EXPANDED_BYTES = 25 * 1024 * 1024


def _pdf(path: Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('This PDF is password-protected. Attach an unlocked copy.')
        parts = []
        length = 0
        for page in reader.pages:
            text = (page.extract_text() or '').strip()
            if not text:
                continue
            part = (('\n\n' if parts else '') + text)[:MAX_CHARACTERS + 1 - length]
            parts.append(part)
            length += len(part)
            if length > MAX_CHARACTERS:
                break
        text = ''.join(parts)
        if not text:
            raise ValueError('This PDF has no readable text. It may contain scanned pages. '
                             'Use OCR to save a searchable PDF, or attach page images '
                             'to a compatible vision model.')
        return text
    except PdfReadError as exc:
        raise ValueError('This PDF is damaged or cannot be read. '
                         'Open it in a PDF reader and save a new copy.') from exc


def extract_chat_document(path: Path) -> str:
    """Extract bounded text; never treat a binary document as UTF-8 content."""
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        return _pdf(path)
    if suffix in {'.docx', '.xlsx', '.pptx'}:
        from .core.integrations.documents import extract

        with zipfile.ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise ValueError('This document expands beyond the 25 MB reading limit.')
        return extract(path).strip()[:MAX_CHARACTERS + 1]
    if suffix in {'.doc', '.xls', '.ppt', '.rtf', '.odt', '.ods', '.odp',
                  '.pages', '.numbers', '.key'}:
        raise ValueError('Save this document as PDF, DOCX, XLSX, PPTX or plain text, '
                         'then attach that copy.')
    raw = path.read_bytes()
    # BOM detection must test UTF-32 first: its LE marker starts with UTF-16's.
    encoding = 'utf-8-sig'
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = 'utf-32'
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = 'utf-16'
    try:
        text = raw.decode(encoding)
    except UnicodeError as exc:
        raise ValueError('This file is not a readable text document. '
                         'Use PDF, DOCX, XLSX, PPTX or a UTF-8 text/source file.') from exc
    if any(ord(char) < 32 and char not in '\t\n\r\f' for char in text):
        raise ValueError('This file contains binary data. '
                         'Use PDF, DOCX, XLSX, PPTX or a text/source file.')
    return text.strip()[:MAX_CHARACTERS + 1]
