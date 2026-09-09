"""A folder of documents, including the Office formats, with no dependencies.

The worked reference for everything else in this package. It is deliberately
the boring one: a folder on disk needs no OAuth, no token and no network, so
what it demonstrates is the part that is easy to get wrong — scope, previews,
structured failure, and reading formats the filesystem tools cannot.

**Why it exists when `fs_read` already does.** `fs_read` returns bytes. A .docx
is a zip of XML, and reading it as text produces a screenful of markup that
looks enough like content for a model to try to answer from it. The three Office
formats are read properly here: paragraphs from Word, cells from Excel, slide
text from PowerPoint.

**It writes the three formats too, in `ooxml`.** Text only — paragraphs, rows,
slides — because that is what an agent summarising a spreadsheet into a deck
actually produces. What it will not do is styles, images and tables: a
half-implemented style engine produces files that open with warnings, which is
worse than a plain document that opens cleanly.

**Scope is enforced on the resolved path.** Connecting a folder grants that
folder. `../` out of it, and a symlink pointing out of it, both resolve first
and are refused after — checking the string the model supplied would catch the
first and miss the second.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from . import credentials, ooxml
from .capabilities import Capability
from .contract import Action, Change, Integration, IntegrationError, Sensitivity

HANDLE = "documents"

#: Namespaces the three formats put their text in. Matched by local name rather
#: than by prefix — the prefix is arbitrary and varies between producers.
_TEXT_TAGS = {"t"}

#: Read whole into memory, so a bounded size matters. A 200 MB spreadsheet is
#: not something to hand a model in any case.
MAX_BYTES = 25_000_000

#: What a model can usefully be given. Beyond this it is being handed a haystack
#: and asked to be a search engine.
MAX_CHARACTERS = 120_000


class Documents(Integration):
    """One folder, read-only, with the Office formats understood."""

    def __init__(self) -> None:
        super().__init__(
            id=HANDLE,
            name="Documents folder",
            summary="A folder on this computer. Word, Excel and PowerPoint "
                    "files are read as text rather than as markup.",
            # A person's documents folder is correspondence, contracts and
            # drafts. It does not go to a remote model on a hunch.
            sensitivity=Sensitivity.PRIVATE,
            available=True,
            needs_credential=False,
            actions=(
                Action(id="documents.list",
                       capability=Capability.STORAGE_LIST,
                       summary="List the files in the connected folder",
                       parameters={"subfolder": "optional, relative to the folder"}),
                Action(id="documents.read",
                       capability=Capability.STORAGE_READ,
                       summary="Read one document as text",
                       parameters={"path": "relative to the connected folder"}),
                Action(id="documents.search",
                       capability=Capability.STORAGE_SEARCH,
                       summary="Find documents containing a phrase",
                       parameters={"query": "the text to look for"}),
                Action(id="documents.write_document",
                       capability=Capability.DOCUMENT_CREATE,
                       summary="Write a Word document",
                       parameters={"path": "relative, ending .docx",
                                   "paragraphs": "list of lines; '# ' makes a heading",
                                   "title": "optional"}),
                Action(id="documents.write_spreadsheet",
                       capability=Capability.SPREADSHEET_WRITE,
                       summary="Write an Excel workbook",
                       parameters={"path": "relative, ending .xlsx",
                                   "rows": "list of rows, each a list of values",
                                   "sheet_name": "optional"}),
                Action(id="documents.write_presentation",
                       capability=Capability.PRESENTATION_CREATE,
                       summary="Write a PowerPoint deck",
                       parameters={"path": "relative, ending .pptx",
                                   "slides": "list of {title, bullets}"}),
            ))

    # ------------------------------------------------------------ connection
    def ready(self) -> bool:
        root = credentials.path_of(HANDLE)
        return bool(root and root.is_dir())

    def account(self) -> str:
        root = credentials.path_of(HANDLE)
        return str(root) if root else ""

    def _root(self) -> Path:
        root = credentials.path_of(HANDLE)
        if root is None:
            raise IntegrationError(
                "No documents folder is connected.",
                remedy="Choose a folder in Settings → Integrations.",
                needs_reconnect=True)
        if not root.is_dir():
            raise IntegrationError(
                f"The connected folder is not there any more: {root}",
                remedy="Reconnect it, or choose a different folder.",
                needs_reconnect=True)
        return root

    def _resolve(self, relative: str) -> Path:
        """A path inside the connected folder, or a refusal.

        Resolved BEFORE the check, so a symlink pointing outside is caught.
        Validating the string the caller supplied would stop `../` and miss the
        symlink, which is the one an attacker would use.
        """
        root = self._root().resolve()
        target = (root / (relative or "")).resolve()
        if target != root and root not in target.parents:
            raise IntegrationError(
                f"{relative!r} is outside the connected folder.",
                remedy="Connecting a folder grants that folder and nothing "
                       "above it. Connect a different folder to reach this.")
        return target

    # ---------------------------------------------------------------- actions
    async def preview(self, action_id: str, arguments: dict) -> Change | None:
        """What a write would do, before it does it.

        Reads return None. For a write the file path matters most — overwriting
        somebody's report is the thing they would want to catch — so whether
        the target already exists is stated rather than left to be discovered.
        """
        if action_id not in {"documents.write_document",
                             "documents.write_spreadsheet",
                             "documents.write_presentation"}:
            return None

        relative = str(arguments.get("path", ""))
        target = self._resolve(relative)
        exists = target.is_file()
        if action_id == "documents.write_spreadsheet":
            rows = arguments.get("rows") or []
            detail = f"{len(rows)} row(s)"
            body = "\n".join(
                "\t".join(str(c) for c in row) for row in rows[:8])
        elif action_id == "documents.write_presentation":
            slides = arguments.get("slides") or []
            detail = f"{len(slides)} slide(s)"
            body = "\n".join(
                str(s.get("title", "")) for s in slides[:8]
                if isinstance(s, dict))
        else:
            paragraphs = arguments.get("paragraphs") or []
            detail = f"{len(paragraphs)} paragraph(s)"
            body = "\n".join(str(p) for p in paragraphs[:8])

        return Change(
            summary=("Replace" if exists else "Create") + f" {target.name}",
            target=str(target), detail=detail,
            # Overwriting is the case worth flagging: the previous contents are
            # gone, and nothing here keeps a copy.
            reversible=not exists, body=body)

    async def run(self, action_id: str, arguments: dict) -> str:
        if action_id == "documents.list":
            return self._list(str(arguments.get("subfolder", "")))
        if action_id == "documents.read":
            return self._read(str(arguments.get("path", "")))
        if action_id == "documents.search":
            return self._search(str(arguments.get("query", "")))
        if action_id == "documents.write_document":
            return self._write_document(arguments)
        if action_id == "documents.write_spreadsheet":
            return self._write_spreadsheet(arguments)
        if action_id == "documents.write_presentation":
            return self._write_presentation(arguments)
        raise IntegrationError(f"{action_id} is not something this can do.",
                               remedy="Ask for one of: "
                                      + ", ".join(a.id for a in self.actions))

    # ----------------------------------------------------------------- writes
    def _target(self, arguments: dict, suffix: str) -> Path:
        """A checked path with the right extension.

        The extension is enforced rather than corrected: a caller asking to
        write a deck to `notes.txt` has misunderstood something, and quietly
        renaming the file would hide that.
        """
        relative = str(arguments.get("path", "")).strip()
        if not relative:
            raise IntegrationError("No file name was given.",
                                   remedy=f"Give a path ending in {suffix}.")
        if not relative.lower().endswith(suffix):
            raise IntegrationError(
                f"{relative!r} does not end in {suffix}.",
                remedy=f"Office will not open it otherwise. Use a {suffix} name.")
        return self._resolve(relative)

    def _write_document(self, arguments: dict) -> str:
        target = self._target(arguments, ".docx")
        paragraphs = [str(p) for p in (arguments.get("paragraphs") or [])]
        if not paragraphs:
            raise IntegrationError("There is nothing to write.",
                                   remedy="Give at least one paragraph.")
        ooxml.write_docx(target, paragraphs,
                         title=str(arguments.get("title", "")))
        return f"Wrote {target.name} ({len(paragraphs)} paragraphs)."

    def _write_spreadsheet(self, arguments: dict) -> str:
        target = self._target(arguments, ".xlsx")
        raw = arguments.get("rows") or []
        if not raw:
            raise IntegrationError("There is nothing to write.",
                                   remedy="Give at least one row.")
        rows = [list(row) if isinstance(row, (list, tuple)) else [row]
                for row in raw]
        ooxml.write_xlsx(target, rows,
                         sheet_name=str(arguments.get("sheet_name") or "Sheet1"))
        return f"Wrote {target.name} ({len(rows)} rows)."

    def _write_presentation(self, arguments: dict) -> str:
        target = self._target(arguments, ".pptx")
        raw = arguments.get("slides") or []
        slides = []
        for entry in raw:
            if isinstance(entry, dict):
                bullets = entry.get("bullets") or entry.get("points") or []
                slides.append((str(entry.get("title", "")),
                               [str(b) for b in bullets]))
            elif isinstance(entry, (list, tuple)) and entry:
                slides.append((str(entry[0]),
                               [str(b) for b in (entry[1] if len(entry) > 1 else [])]))
        if not slides:
            raise IntegrationError(
                "There is nothing to write.",
                remedy="Give slides as {title, bullets} objects.")
        ooxml.write_pptx(target, slides)
        return f"Wrote {target.name} ({len(slides)} slides)."

    def _list(self, subfolder: str) -> str:
        target = self._resolve(subfolder)
        if not target.is_dir():
            raise IntegrationError(f"{subfolder or '.'} is not a folder.",
                                   remedy="Give a folder, or omit it for the top.")
        rows = []
        for child in sorted(target.iterdir()):
            if child.name.startswith("."):
                continue
            rows.append(f"{child.name}/" if child.is_dir()
                        else f"{child.name}  ({child.stat().st_size / 1024:.0f} KB)")
        return "\n".join(rows) if rows else "The folder is empty."

    def _read(self, relative: str) -> str:
        target = self._resolve(relative)
        if not target.is_file():
            raise IntegrationError(
                f"There is no file at {relative!r}.",
                remedy="Use documents.list to see what is there.")
        if target.stat().st_size > MAX_BYTES:
            raise IntegrationError(
                f"{relative} is {target.stat().st_size / 1e6:.0f} MB, which is "
                f"too large to read in one piece.",
                remedy="Open it directly, or point at a smaller file.")
        text = extract(target)
        if len(text) > MAX_CHARACTERS:
            return (text[:MAX_CHARACTERS]
                    + f"\n\n[… truncated at {MAX_CHARACTERS} characters. "
                      f"The document continues.]")
        return text

    def _search(self, query: str) -> str:
        if not query.strip():
            raise IntegrationError("No search text was given.",
                                   remedy="Say what to look for.")
        root = self._root().resolve()
        needle = query.lower()
        hits = []
        for child in sorted(root.rglob("*")):
            if not child.is_file() or child.name.startswith("."):
                continue
            # Checked per candidate rather than trusting the walk. `rglob` does
            # not currently follow directory symlinks, but that is a property
            # of the traversal implementation and it has changed between Python
            # versions — the boundary must not depend on it.
            resolved = child.resolve()
            if resolved != root and root not in resolved.parents:
                continue
            if child.stat().st_size > MAX_BYTES:
                continue
            try:
                text = extract(child)
            except IntegrationError:
                continue
            if needle in text.lower():
                where = text.lower().index(needle)
                excerpt = text[max(0, where - 60):where + 120].replace("\n", " ")
                hits.append(f"{child.relative_to(root)}\n    …{excerpt.strip()}…")
            if len(hits) >= 20:
                break
        return "\n".join(hits) if hits else f"Nothing contains {query!r}."


# ------------------------------------------------------------------ formats
def _xml_text(data: bytes, tags: set[str], separator: str = "") -> str:
    """Every text node under the named tags, in document order.

    Matched by LOCAL name. Producers disagree about namespace prefixes, and a
    prefix-matching reader works on files from Word and returns nothing for the
    same format written by LibreOffice.
    """
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return ""
    out = []
    for element in root.iter():
        local = element.tag.rsplit("}", 1)[-1]
        if local in tags and element.text:
            out.append(element.text)
        elif local in {"p", "br", "tab"} and out and out[-1] != "\n":
            out.append("\n")
    return separator.join(out)


def _docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        if "word/document.xml" not in archive.namelist():
            raise IntegrationError(f"{path.name} is not a Word document.",
                                   remedy="Check the file.")
        return _xml_text(archive.read("word/document.xml"), _TEXT_TAGS)


def _pptx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        slides = sorted(n for n in archive.namelist()
                        if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
        out = []
        for number, name in enumerate(slides, start=1):
            body = _xml_text(archive.read(name), _TEXT_TAGS)
            out.append(f"--- Slide {number} ---\n{body.strip()}")
        return "\n\n".join(out)


def _xlsx(path: Path) -> str:
    """Cells as tab-separated rows, with shared strings resolved.

    Excel stores most text once in a shared table and refers to it by index, so
    a reader that ignores `sharedStrings.xml` returns a spreadsheet of numbers
    and blanks — which looks like a successfully read empty file.
    """
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            try:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            except ElementTree.ParseError:
                root = None
            if root is not None:
                for item in root:
                    parts = [node.text or "" for node in item.iter()
                             if node.tag.rsplit("}", 1)[-1] == "t"]
                    shared.append("".join(parts))

        sheets = sorted(n for n in names
                        if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        out = []
        for name in sheets:
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError:
                continue
            for row in root.iter():
                if row.tag.rsplit("}", 1)[-1] != "row":
                    continue
                cells = []
                for cell in row:
                    kind = cell.get("t", "")
                    value = ""
                    for node in cell:
                        if node.tag.rsplit("}", 1)[-1] == "v":
                            value = node.text or ""
                        elif node.tag.rsplit("}", 1)[-1] == "is":
                            value = "".join(n.text or "" for n in node.iter()
                                            if n.tag.rsplit("}", 1)[-1] == "t")
                    if kind == "s" and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                    cells.append(value)
                if any(cells):
                    out.append("\t".join(cells))
        return "\n".join(out)


#: Extension to reader. Anything not here is read as text, which is right for
#: .txt, .md, .csv and source files and wrong only for binaries — which fail
#: with a message rather than returning mojibake.
_READERS = {".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}


def extract(path: Path) -> str:
    """One document as text, whatever it is."""
    reader = _READERS.get(path.suffix.lower())
    if reader is not None:
        try:
            return reader(path)
        except zipfile.BadZipFile as exc:
            raise IntegrationError(
                f"{path.name} is damaged, or is not really a "
                f"{path.suffix} file.",
                remedy="Open it in its own application to check.") from exc
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrationError(
            f"{path.name} is not a text document and there is no reader for "
            f"{path.suffix or 'files with no extension'}.",
            remedy="Word, Excel, PowerPoint and plain text are understood.",
        ) from exc
