"""Writing Word, Excel and PowerPoint files without a library.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

An OOXML file is a zip of XML parts plus the relationship files that tie them
together. Producing one Word will actually open needs four things — a content
type map, a package relationship, the document part, and its own relationships
— and that is about sixty lines rather than the multi-megabyte dependency it is
usually assumed to require.

**Why not python-docx and friends.** Three libraries, several megabytes,
frozen into two installers, to write documents whose structure is a paragraph
list. The reading side already parses these formats with `zipfile` and
`ElementTree`; writing them with the same two is consistent and keeps the
Apple Silicon build free of a torch-adjacent dependency chain it does not need.

**What this deliberately does not do.** Styles, themes, images, tables,
comments, revision marks. It writes text — paragraphs, rows, slides — because
that is what an agent summarising a spreadsheet into a deck actually produces,
and a half-implemented style engine would generate files that open with
warnings. Anything richer belongs to a real library, and that is a decision to
take when something needs it rather than in advance.

Every writer here is round-tripped by the reader in the same package, so a file
this produces is one Uncloud can read back.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"

_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _types(*parts: tuple[str, str]) -> str:
    """The content-type map. Word refuses to open a package without one."""
    overrides = "".join(
        f'<Override PartName="{name}" ContentType="{kind}"/>'
        for name, kind in parts)
    rels = "application/vnd.openxmlformats-package.relationships+xml"
    return (_XML + f'<Types xmlns="{CT}">'
            f'<Default Extension="rels" ContentType="{rels}"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'{overrides}</Types>')


def _rels(*entries: tuple[str, str, str]) -> str:
    items = "".join(
        f'<Relationship Id="{rid}" Type="{kind}" Target="{target}"/>'
        for rid, kind, target in entries)
    return _XML + f'<Relationships xmlns="{PR}">{items}</Relationships>'


def _write(path: Path, parts: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


# ------------------------------------------------------------------- Word
def write_docx(path: Path, paragraphs: list[str], *, title: str = "") -> Path:
    """A Word document from a list of paragraphs.

    A leading `# ` marks a heading, which is the one piece of structure worth
    supporting: a summary with no headings is a wall, and Word's built-in
    heading styles need no theme part to render.
    """
    body = []
    for text in ([title, *paragraphs] if title else paragraphs):
        stripped = text.lstrip()
        heading = stripped.startswith("#")
        level = len(stripped) - len(stripped.lstrip("#")) if heading else 0
        content = stripped.lstrip("#").strip() if heading else text
        style = (f'<w:pPr><w:pStyle w:val="Heading{min(level or 1, 3)}"/></w:pPr>'
                 if heading or (title and text is title) else "")
        body.append(
            f"<w:p>{style}<w:r><w:t xml:space=\"preserve\">"
            f"{escape(content)}</w:t></w:r></w:p>")

    return _write(path, {
        "[Content_Types].xml": _types(
            ("/word/document.xml",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")),
        "_rels/.rels": _rels(
            ("rId1", f"{R}/officeDocument", "word/document.xml")),
        "word/_rels/document.xml.rels": _rels(),
        "word/document.xml": (
            _XML + f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}'
            '<w:sectPr/></w:body></w:document>'),
    })


# ------------------------------------------------------------------ Excel
def write_xlsx(path: Path, rows: list[list[object]], *,
               sheet_name: str = "Sheet1") -> Path:
    """A workbook from rows of values.

    Written with inline strings rather than the shared-string table. The table
    is a size optimisation for documents with heavy repetition; inline strings
    are valid, simpler, and remove a whole class of index-mismatch bug from a
    writer nobody will look at again.

    Numbers are written as numbers so the cells are usable — a spreadsheet of
    numeric text is one somebody has to re-type.
    """
    def cell(column: int, row: int, value: object) -> str:
        reference = f"{_column_name(column)}{row}"
        if isinstance(value, bool) or value is None:
            value = "" if value is None else str(value)
        if isinstance(value, (int, float)):
            return f'<c r="{reference}"><v>{value}</v></c>'
        return (f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
                f'{escape(str(value))}</t></is></c>')

    body = "".join(
        f'<row r="{n}">'
        + "".join(cell(i, n, value) for i, value in enumerate(row))
        + "</row>"
        for n, row in enumerate(rows, start=1))

    return _write(path, {
        "[Content_Types].xml": _types(
            ("/xl/workbook.xml",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
            ("/xl/worksheets/sheet1.xml",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")),
        "_rels/.rels": _rels(("rId1", f"{R}/officeDocument", "xl/workbook.xml")),
        "xl/_rels/workbook.xml.rels": _rels(
            ("rId1", f"{R}/worksheet", "worksheets/sheet1.xml")),
        "xl/workbook.xml": (
            _XML + f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets>'
            f'<sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/>'
            "</sheets></workbook>"),
        "xl/worksheets/sheet1.xml": (
            _XML + f'<worksheet xmlns="{S}"><sheetData>{body}</sheetData></worksheet>'),
    })


def _column_name(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA. Excel's own column naming."""
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


# ------------------------------------------------------------- PowerPoint
def write_pptx(path: Path, slides: list[tuple[str, list[str]]]) -> Path:
    """A deck from (title, bullets) pairs.

    The minimum PowerPoint will open: a presentation part, one slide master and
    layout, and a slide per pair. Text boxes are positioned in EMUs — English
    Metric Units, 914400 to the inch — because a slide with no explicit
    geometry renders its content stacked at the origin.
    """
    parts: dict[str, str] = {}
    slide_ids, slide_rels, overrides = [], [], []

    for n, (heading, bullets) in enumerate(slides, start=1):
        body = "".join(
            f'<a:p><a:r><a:t>{escape(str(line))}</a:t></a:r></a:p>'
            for line in bullets) or "<a:p/>"
        parts[f"ppt/slides/slide{n}.xml"] = (
            _XML + f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/>'
            '<p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
            # Title
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/>'
            '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
            '<p:spPr><a:xfrm><a:off x="685800" y="457200"/>'
            '<a:ext cx="7772400" cy="1143000"/></a:xfrm></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>'
            f'<a:t>{escape(str(heading))}</a:t></a:r></a:p></p:txBody></p:sp>'
            # Body
            '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Content"/>'
            '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr>'
            '<p:spPr><a:xfrm><a:off x="685800" y="1828800"/>'
            '<a:ext cx="7772400" cy="3886200"/></a:xfrm></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/>{body}</p:txBody></p:sp>'
            "</p:spTree></p:cSld></p:sld>")
        parts[f"ppt/slides/_rels/slide{n}.xml.rels"] = _rels(
            ("rId1", f"{R}/slideLayout", "../slideLayouts/slideLayout1.xml"))
        slide_ids.append(f'<p:sldId id="{255 + n}" r:id="rId{n + 1}"/>')
        slide_rels.append((f"rId{n + 1}", f"{R}/slide", f"slides/slide{n}.xml"))
        overrides.append((
            f"/ppt/slides/slide{n}.xml",
            "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"))

    parts["ppt/slideMasters/slideMaster1.xml"] = (
        _XML + f'<p:sldMaster xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}">'
        '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
        '<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>'
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
        'accent2="accent2" accent3="accent3" accent4="accent4" '
        'accent5="accent5" accent6="accent6" hlink="hlink" '
        'folHlink="folHlink"/><p:sldLayoutIdLst>'
        '<p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        "</p:sldMaster>")
    parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _rels(
        ("rId1", f"{R}/slideLayout", "../slideLayouts/slideLayout1.xml"))
    parts["ppt/slideLayouts/slideLayout1.xml"] = (
        _XML + f'<p:sldLayout xmlns:p="{P}" xmlns:a="{A}" type="obj">'
        '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
        '<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree>'
        "</p:cSld></p:sldLayout>")
    parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = _rels(
        ("rId1", f"{R}/slideMaster", "../slideMasters/slideMaster1.xml"))

    parts["ppt/presentation.xml"] = (
        _XML + f'<p:presentation xmlns:p="{P}" xmlns:r="{R}">'
        f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/>'
        f'</p:sldMasterIdLst><p:sldIdLst>{"".join(slide_ids)}</p:sldIdLst>'
        '<p:sldSz cx="9144000" cy="6858000"/>'
        '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    parts["ppt/_rels/presentation.xml.rels"] = _rels(
        ("rId1", f"{R}/slideMaster", "slideMasters/slideMaster1.xml"),
        *slide_rels)
    parts["_rels/.rels"] = _rels(
        ("rId1", f"{R}/officeDocument", "ppt/presentation.xml"))
    parts["[Content_Types].xml"] = _types(
        ("/ppt/presentation.xml",
         "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
        ("/ppt/slideMasters/slideMaster1.xml",
         "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"),
        ("/ppt/slideLayouts/slideLayout1.xml",
         "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"),
        *overrides)

    return _write(path, parts)
