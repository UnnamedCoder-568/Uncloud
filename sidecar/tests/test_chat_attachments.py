"""Exercise real uploads and parsers without a loaded model or external service."""
from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from uncloud_engine import chat_attachments


@pytest.fixture
def upload(tmp_path, monkeypatch):
    from uncloud_engine import main

    monkeypatch.setattr(main, 'UPLOAD_DIR', tmp_path)
    client = TestClient(main.app)
    headers = {'Authorization': f'Bearer {main.settings.token}'}

    def send(name, data, content_type='application/octet-stream'):
        result = client.post('/api/chat/attachments', headers=headers,
                             files={'file': (name, data, content_type)})
        assert not list(tmp_path.iterdir()), 'upload scratch file must be removed'
        return result

    return send


def pdf(*pages):
    from reportlab.pdfgen.canvas import Canvas

    data = io.BytesIO()
    canvas = Canvas(data)
    for text in pages:
        canvas.drawString(40, 700, text)
        canvas.showPage()
    canvas.save()
    return data.getvalue()


def test_pdf_upload_extracts_real_pages_without_a_vision_model(upload):
    result = upload('Quarterly Report.PDF', pdf('Revenue: 12345', 'Margin: 17%'),
                    'application/pdf')
    assert result.status_code == 200
    assert result.json() == {'name': 'Quarterly Report.PDF', 'type': 'application/pdf',
                             'text': 'Revenue: 12345\n\nMargin: 17%', 'clipped': False}


@pytest.mark.parametrize('suffix', ['.docx', '.xlsx', '.pptx'])
def test_modern_office_uploads_still_extract_contents(upload, tmp_path, suffix):
    from uncloud_engine.core.integrations import ooxml

    source = tmp_path.parent / f'report{suffix}'
    if suffix == '.docx':
        ooxml.write_docx(source, ['Revenue: 12345'])
    elif suffix == '.xlsx':
        ooxml.write_xlsx(source, [['Revenue', 12345]])
    else:
        ooxml.write_pptx(source, [('Revenue', ['12345'])])
    result = upload(source.name, source.read_bytes())
    assert result.status_code == 200
    assert 'Revenue' in result.json()['text']
    assert '12345' in result.json()['text']
    assert result.json()['clipped'] is False


@pytest.mark.parametrize('name,encoding', [
    ('notes.txt', 'utf-8-sig'), ('report.csv', 'utf-8'), ('config.custom', 'utf-8'),
    ('README', 'utf-8'), ('main.swift', 'utf-8'), ('notes.txt', 'utf-16'),
    ('notes.txt', 'utf-32'),
])
def test_readable_text_is_not_limited_by_filename_or_missing_mime(upload, name, encoding):
    result = upload(name, 'Revenue\t12345\nCafé'.encode(encoding))
    assert result.status_code == 200
    assert result.json()['text'] == 'Revenue\t12345\nCafé'


def test_corrupt_pdf_is_explained_and_scratch_file_is_removed(upload):
    result = upload('broken.pdf', b'not a PDF')
    assert result.status_code == 400
    assert 'damaged' in result.json()['detail']


def test_password_protected_pdf_requests_an_unlocked_copy(upload):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf('Private report'))))
    writer.encrypt('secret')
    data = io.BytesIO()
    writer.write(data)
    result = upload('locked.pdf', data.getvalue())
    assert result.status_code == 400
    assert 'password-protected' in result.json()['detail']


def test_pdf_without_a_text_layer_explains_ocr_requirement(upload):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    data = io.BytesIO()
    writer.write(data)
    result = upload('scanned.pdf', data.getvalue())
    assert result.status_code == 400
    assert 'OCR' in result.json()['detail']


@pytest.mark.parametrize('name,data', [
    ('program.bin', b'MZ\x00\x01'), ('image.png', b'\x89PNG\r\n\x1a\n'),
    ('corrupt.docx', b'not a zip'), ('notes.txt', b'\xff\xff\xff'),
    ('empty.txt', b'  \n '),
])
def test_unreadable_files_are_rejected_instead_of_becoming_model_context(upload, name, data):
    assert upload(name, data).status_code == 400


def test_large_upload_is_rejected_before_extraction(upload):
    result = upload('large.txt', b'x' * (chat_attachments.MAX_BYTES + 1))
    assert result.status_code == 413


def test_long_text_is_marked_as_an_excerpt(upload):
    result = upload('long.txt', b'x' * (chat_attachments.MAX_CHARACTERS + 20))
    assert result.status_code == 200
    assert len(result.json()['text']) == chat_attachments.MAX_CHARACTERS
    assert result.json()['clipped'] is True


def test_pdf_excerpt_accounts_for_page_separators(upload, monkeypatch):
    monkeypatch.setattr(chat_attachments, 'MAX_CHARACTERS', 5)
    result = upload('long.pdf', pdf('12345', '67890'))
    assert result.status_code == 200
    assert result.json()['text'] == '12345'
    assert result.json()['clipped'] is True


def test_office_archive_expansion_is_bounded(upload, monkeypatch):
    monkeypatch.setattr(chat_attachments, 'MAX_EXPANDED_BYTES', 32)
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', b'x' * 33)
    result = upload('oversized.docx', data.getvalue())
    assert result.status_code == 400
    assert 'reading limit' in result.json()['detail']


def test_upload_requires_authentication():
    from uncloud_engine import main

    client = TestClient(main.app)
    result = client.post('/api/chat/attachments', files={'file': ('x.txt', b'Hello')})
    assert result.status_code == 401
