"""Google Workspace: Drive, Docs, Sheets, Slides, Gmail and Calendar.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Every call here is real. What is not — and cannot be — is the OAuth client:
Google issues those to a named party under their terms, so this reports
NOT_CONFIGURED until the user registers an application and enters its client
ID. That is the honest state, and the report distinguishes it from "not
implemented".

Three things worth knowing about this API surface.

**Gmail bodies are base64url, nested, and sometimes only in the parts.** A
message's text can be at the top level or buried in a multipart tree, so
reading one means walking it. A reader that only checked `payload.body` returns
empty strings for most real mail.

**Sending mail is RFC 2822 in a base64url string.** There is no "to/subject/
body" endpoint; the message is assembled and encoded.

**Docs and Sheets are separate APIs from Drive.** Drive lists and searches;
Docs and Sheets read and write content. Finding a file is one API, opening it
is another, and conflating them produces a Drive export that loses structure.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage

from ...auth import AuthKind, ProviderConfig, Scope
from ..capabilities import Capability
from ..contract import Action, Change, Integration, IntegrationError, Sensitivity
from .rest import Rest

DEFAULTS = ProviderConfig(
    provider="google",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    revoke_url="https://oauth2.googleapis.com/revoke",
    # Without `access_type=offline` Google issues no refresh token, and the
    # connection dies in an hour with nothing to renew it. `prompt=consent`
    # forces one to be re-issued when somebody reconnects.
    extra_authorize={"access_type": "offline", "prompt": "consent"})

SCOPES = (
    Scope(id="https://www.googleapis.com/auth/drive.readonly",
          summary="See and download your Drive files"),
    Scope(id="https://www.googleapis.com/auth/documents",
          summary="Read and write Google Docs", required=False),
    Scope(id="https://www.googleapis.com/auth/spreadsheets",
          summary="Read and write Google Sheets", required=False),
    Scope(id="https://www.googleapis.com/auth/presentations",
          summary="Read and write Google Slides", required=False),
    Scope(id="https://www.googleapis.com/auth/gmail.readonly",
          summary="Read your mail", required=False),
    Scope(id="https://www.googleapis.com/auth/gmail.compose",
          summary="Draft and send mail as you", required=False),
    Scope(id="https://www.googleapis.com/auth/calendar",
          summary="Read and add calendar events", required=False),
)


class Google(Integration):
    def __init__(self, *, client_factory=None) -> None:
        super().__init__(
            id="google",
            name="Google Workspace",
            summary="Drive, Docs, Sheets, Slides, Gmail and Calendar.",
            sensitivity=Sensitivity.PRIVATE,
            available=True,
            auth_kind=AuthKind.OAUTH2_PKCE,
            defaults=DEFAULTS,
            needs="An OAuth client ID from a Google Cloud project, with the "
                  "APIs you want enabled and http://127.0.0.1 registered as a "
                  "redirect. Uncloud cannot supply one: Google issues OAuth "
                  "clients to a named party under their terms.",
            scopes=SCOPES,
            actions=(
                Action(id="google.drive_search",
                       capability=Capability.STORAGE_SEARCH,
                       summary="Search Drive",
                       parameters={"query": "name or full-text",
                                   "mime_type": "optional filter"},
                       scopes=("drive.readonly",)),
                Action(id="google.drive_list",
                       capability=Capability.STORAGE_LIST,
                       summary="List Drive files, newest first",
                       parameters={"folder_id": "optional"}),
                Action(id="google.doc_read", capability=Capability.DOCUMENT_READ,
                       summary="Read a Google Doc as text",
                       parameters={"document_id": ""}),
                Action(id="google.doc_create",
                       capability=Capability.DOCUMENT_CREATE,
                       summary="Create a Google Doc",
                       parameters={"title": "", "content": "paragraphs, one "
                                                           "per line"}),
                Action(id="google.sheet_read",
                       capability=Capability.SPREADSHEET_READ,
                       summary="Read a range from a Sheet",
                       parameters={"spreadsheet_id": "",
                                   "range": "e.g. Sheet1!A1:D50"}),
                Action(id="google.sheet_write",
                       capability=Capability.SPREADSHEET_WRITE,
                       summary="Write rows into a Sheet",
                       parameters={"spreadsheet_id": "", "range": "",
                                   "rows": "list of rows"}),
                Action(id="google.slides_create",
                       capability=Capability.PRESENTATION_CREATE,
                       summary="Create a Slides deck",
                       parameters={"title": "", "slides": "list of "
                                                          "{title, bullets}"}),
                Action(id="google.mail_search",
                       capability=Capability.EMAIL_SEARCH,
                       summary="Search Gmail",
                       parameters={"query": "Gmail search syntax",
                                   "limit": "optional"}),
                Action(id="google.mail_read", capability=Capability.EMAIL_READ,
                       summary="Read one message",
                       parameters={"message_id": ""}),
                Action(id="google.mail_draft", capability=Capability.EMAIL_DRAFT,
                       summary="Save a draft",
                       parameters={"to": "", "subject": "", "body": ""}),
                Action(id="google.mail_send", capability=Capability.EMAIL_SEND,
                       summary="Send mail as you",
                       parameters={"to": "", "subject": "", "body": "",
                                   "cc": "optional"}),
                Action(id="google.calendar_list",
                       capability=Capability.CALENDAR_READ,
                       summary="List upcoming events",
                       parameters={"limit": "optional",
                                   "calendar_id": "optional"}),
                Action(id="google.calendar_create",
                       capability=Capability.CALENDAR_CREATE,
                       summary="Create an event",
                       parameters={"summary": "", "start": "ISO 8601",
                                   "end": "ISO 8601", "attendees": "optional",
                                   "location": "optional"}),
            ))
        self._api = lambda base: Rest(
            "google", base, kind=AuthKind.OAUTH2_PKCE, defaults=DEFAULTS,
            client_factory=client_factory)
        self.drive = self._api("https://www.googleapis.com/drive/v3")
        self.docs = self._api("https://docs.googleapis.com/v1")
        self.sheets = self._api("https://sheets.googleapis.com/v4")
        self.slides = self._api("https://slides.googleapis.com/v1")
        self.gmail = self._api("https://gmail.googleapis.com/gmail/v1")
        self.calendar = self._api("https://www.googleapis.com/calendar/v3")

    def account(self) -> str:
        return ""

    def whoami(self) -> str:
        return str(self.gmail.get("/users/me/profile").get("emailAddress", ""))

    # --------------------------------------------------------------- preview
    async def preview(self, action_id: str, arguments: dict) -> Change | None:
        if action_id in {"google.mail_send", "google.mail_draft"}:
            sending = action_id.endswith("send")
            recipients = str(arguments.get("to", ""))
            if arguments.get("cc"):
                recipients += f"  cc: {arguments['cc']}"
            return Change(
                summary=("Send" if sending else "Draft")
                        + f" “{arguments.get('subject', '')}”",
                target=recipients,
                detail="" if sending else "Saved as a draft; not sent.",
                reversible=not sending,
                body=str(arguments.get("body", ""))[:1000])
        if action_id == "google.calendar_create":
            attendees = arguments.get("attendees") or []
            return Change(
                summary=f"Create “{arguments.get('summary', '')}”",
                target=f"{arguments.get('start', '')} → "
                       f"{arguments.get('end', '')}",
                detail=(f"invites {', '.join(attendees)}" if attendees
                        else "no attendees")
                       + (f" at {arguments['location']}"
                          if arguments.get("location") else ""),
                # Cancellable, but everybody invited has already been emailed.
                reversible=not attendees)
        if action_id == "google.doc_create":
            return Change(summary=f"Create the doc “{arguments.get('title', '')}”",
                          target="Google Drive", reversible=True,
                          body=str(arguments.get("content", ""))[:1000])
        if action_id == "google.slides_create":
            slides = arguments.get("slides") or []
            return Change(summary=f"Create the deck “{arguments.get('title', '')}”",
                          target="Google Drive",
                          detail=f"{len(slides)} slide(s)", reversible=True)
        if action_id == "google.sheet_write":
            rows = arguments.get("rows") or []
            return Change(
                summary=f"Write {len(rows)} row(s)",
                target=f"{arguments.get('spreadsheet_id', '')} "
                       f"{arguments.get('range', '')}",
                detail="Existing values in that range are replaced.",
                reversible=False)
        return None

    # --------------------------------------------------------------- actions
    async def run(self, action_id: str, arguments: dict) -> str:
        handlers = {
            "google.drive_search": self._drive_search,
            "google.drive_list": self._drive_list,
            "google.doc_read": self._doc_read,
            "google.doc_create": self._doc_create,
            "google.sheet_read": self._sheet_read,
            "google.sheet_write": self._sheet_write,
            "google.slides_create": self._slides_create,
            "google.mail_search": self._mail_search,
            "google.mail_read": self._mail_read,
            "google.mail_draft": lambda a: self._mail_out(a, send=False),
            "google.mail_send": lambda a: self._mail_out(a, send=True),
            "google.calendar_list": self._calendar_list,
            "google.calendar_create": self._calendar_create,
        }
        handler = handlers.get(action_id)
        if handler is None:
            raise IntegrationError(
                f"{action_id} is not something Google Workspace can do.",
                remedy="Ask for one of: " + ", ".join(a.id for a in self.actions))
        return handler(arguments)

    # ----------------------------------------------------------------- Drive
    def _drive_search(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).replace("'", "\\'")
        clauses = [f"(name contains '{query}' or fullText contains '{query}')"]
        if arguments.get("mime_type"):
            clauses.append(f"mimeType = '{arguments['mime_type']}'")
        clauses.append("trashed = false")
        body = self.drive.get("/files", params={
            "q": " and ".join(clauses), "pageSize": 25,
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"})
        return self._drive_rows(body)

    def _drive_list(self, arguments: dict) -> str:
        clauses = ["trashed = false"]
        if arguments.get("folder_id"):
            clauses.append(f"'{arguments['folder_id']}' in parents")
        body = self.drive.get("/files", params={
            "q": " and ".join(clauses), "pageSize": 50,
            "orderBy": "modifiedTime desc",
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"})
        return self._drive_rows(body)

    @staticmethod
    def _drive_rows(body: dict) -> str:
        files = body.get("files") or []
        if not files:
            return "Nothing found."
        return "\n".join(
            f"{f['name']}  [{f['mimeType'].rsplit('.', 1)[-1]}]  "
            f"id={f['id']}  modified {f.get('modifiedTime', '')}"
            for f in files)

    # ------------------------------------------------------------------ Docs
    def _doc_read(self, arguments: dict) -> str:
        document_id = self._required(arguments, "document_id")
        body = self.docs.get(f"/documents/{document_id}")
        lines = []
        for element in (body.get("body") or {}).get("content") or []:
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            text = "".join(
                (run.get("textRun") or {}).get("content", "")
                for run in paragraph.get("elements") or [])
            if text.strip():
                lines.append(text.rstrip("\n"))
        return f"# {body.get('title', '')}\n\n" + "\n".join(lines)

    def _doc_create(self, arguments: dict) -> str:
        title = self._required(arguments, "title")
        document = self.docs.post("/documents", json_body={"title": title})
        document_id = document["documentId"]
        content = str(arguments.get("content", ""))
        if content:
            self.docs.post(f"/documents/{document_id}:batchUpdate", json_body={
                "requests": [{"insertText": {"location": {"index": 1},
                                             "text": content}}]})
        return (f"Created “{title}”: "
                f"https://docs.google.com/document/d/{document_id}/edit")

    # ---------------------------------------------------------------- Sheets
    def _sheet_read(self, arguments: dict) -> str:
        spreadsheet_id = self._required(arguments, "spreadsheet_id")
        cells = arguments.get("range") or "A1:Z200"
        body = self.sheets.get(
            f"/spreadsheets/{spreadsheet_id}/values/{cells}")
        rows = body.get("values") or []
        if not rows:
            return "That range is empty."
        return "\n".join("\t".join(str(c) for c in row) for row in rows)

    def _sheet_write(self, arguments: dict) -> str:
        spreadsheet_id = self._required(arguments, "spreadsheet_id")
        cells = self._required(arguments, "range")
        rows = arguments.get("rows") or []
        if not rows:
            raise IntegrationError("There is nothing to write.",
                                   remedy="Give at least one row.")
        body = self.sheets.put(
            f"/spreadsheets/{spreadsheet_id}/values/{cells}",
            params={"valueInputOption": "USER_ENTERED"},
            json_body={"values": [list(r) for r in rows]})
        return f"Updated {body.get('updatedCells', 0)} cell(s)."

    # ---------------------------------------------------------------- Slides
    def _slides_create(self, arguments: dict) -> str:
        title = self._required(arguments, "title")
        deck = self.slides.post("/presentations", json_body={"title": title})
        presentation_id = deck["presentationId"]

        requests: list[dict] = []
        for n, slide in enumerate(arguments.get("slides") or []):
            heading = str(slide.get("title", "")) if isinstance(slide, dict) else str(slide)
            bullets = slide.get("bullets") or [] if isinstance(slide, dict) else []
            page_id = f"slide_{n}"
            requests.append({"createSlide": {
                "objectId": page_id,
                "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                "placeholderIdMappings": [
                    {"layoutPlaceholder": {"type": "TITLE"},
                     "objectId": f"{page_id}_title"},
                    {"layoutPlaceholder": {"type": "BODY", "index": 0},
                     "objectId": f"{page_id}_body"}]}})
            requests.append({"insertText": {"objectId": f"{page_id}_title",
                                            "text": heading}})
            if bullets:
                requests.append({"insertText": {
                    "objectId": f"{page_id}_body",
                    "text": "\n".join(str(b) for b in bullets)}})
        if requests:
            self.slides.post(f"/presentations/{presentation_id}:batchUpdate",
                             json_body={"requests": requests})
        return (f"Created “{title}”: "
                f"https://docs.google.com/presentation/d/{presentation_id}/edit")

    # ----------------------------------------------------------------- Gmail
    def _mail_search(self, arguments: dict) -> str:
        limit = min(int(arguments.get("limit") or 15), 50)
        body = self.gmail.get("/users/me/messages", params={
            "q": str(arguments.get("query", "")), "maxResults": limit})
        messages = body.get("messages") or []
        if not messages:
            return "No matching mail."
        rows = []
        for message in messages:
            # `metadata` rather than `full`: a search listing needs headers, and
            # pulling whole bodies for fifteen messages is slow and mostly waste.
            detail = self.gmail.get(
                f"/users/me/messages/{message['id']}",
                params={"format": "metadata",
                        "metadataHeaders": ["From", "Subject", "Date"]})
            headers = {h["name"]: h["value"]
                       for h in (detail.get("payload") or {}).get("headers") or []}
            rows.append(f"[{message['id']}] {headers.get('Date', '')} "
                        f"{headers.get('From', '')}: "
                        f"{headers.get('Subject', '(no subject)')}")
        return "\n".join(rows)

    def _mail_read(self, arguments: dict) -> str:
        message_id = self._required(arguments, "message_id")
        detail = self.gmail.get(f"/users/me/messages/{message_id}",
                                params={"format": "full"})
        payload = detail.get("payload") or {}
        headers = {h["name"]: h["value"] for h in payload.get("headers") or []}
        return (f"From: {headers.get('From', '')}\n"
                f"To: {headers.get('To', '')}\n"
                f"Date: {headers.get('Date', '')}\n"
                f"Subject: {headers.get('Subject', '')}\n\n"
                f"{self._body_of(payload)}")

    @staticmethod
    def _body_of(payload: dict) -> str:
        """The readable text out of a MIME tree.

        Walked rather than read from `payload.body`, which is empty for most
        real mail — the text lives in a part, sometimes nested two deep, and
        plain text is preferred over HTML where both exist.
        """
        def decode(data: str) -> str:
            try:
                return base64.urlsafe_b64decode(data + "===").decode(
                    "utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - a malformed part is not fatal
                return ""

        plain, html = [], []

        def walk(part: dict) -> None:
            mime = part.get("mimeType", "")
            data = (part.get("body") or {}).get("data")
            if data:
                (plain if mime == "text/plain" else html).append(decode(data))
            for child in part.get("parts") or []:
                walk(child)

        walk(payload)
        if plain:
            return "\n".join(t for t in plain if t.strip())
        if html:
            import re

            stripped = re.sub(r"<[^>]+>", " ", "\n".join(html))
            return re.sub(r"\s+", " ", stripped).strip()
        return "(no readable body)"

    def _mail_out(self, arguments: dict, *, send: bool) -> str:
        to = self._required(arguments, "to")
        message = EmailMessage()
        message["To"] = to
        if arguments.get("cc"):
            message["Cc"] = str(arguments["cc"])
        message["Subject"] = str(arguments.get("subject", ""))
        message.set_content(str(arguments.get("body", "")))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

        if send:
            result = self.gmail.post("/users/me/messages/send",
                                     json_body={"raw": raw})
            return f"Sent to {to} (id {result.get('id', '')})."
        result = self.gmail.post("/users/me/drafts",
                                 json_body={"message": {"raw": raw}})
        return f"Draft saved for {to} (id {result.get('id', '')})."

    # -------------------------------------------------------------- Calendar
    def _calendar_list(self, arguments: dict) -> str:
        from datetime import UTC, datetime

        calendar_id = arguments.get("calendar_id") or "primary"
        body = self.calendar.get(f"/calendars/{calendar_id}/events", params={
            "maxResults": min(int(arguments.get("limit") or 20), 100),
            "orderBy": "startTime", "singleEvents": "true",
            "timeMin": datetime.now(UTC).isoformat()})
        events = body.get("items") or []
        if not events:
            return "Nothing coming up."
        return "\n".join(
            f"{(e.get('start') or {}).get('dateTime') or (e.get('start') or {}).get('date', '')}"
            f"  {e.get('summary', '(no title)')}"
            + (f"  @ {e['location']}" if e.get("location") else "")
            for e in events)

    def _calendar_create(self, arguments: dict) -> str:
        event = {
            "summary": self._required(arguments, "summary"),
            "start": {"dateTime": self._required(arguments, "start")},
            "end": {"dateTime": self._required(arguments, "end")},
        }
        if arguments.get("location"):
            event["location"] = str(arguments["location"])
        if arguments.get("attendees"):
            event["attendees"] = [{"email": str(a)}
                                  for a in arguments["attendees"]]
        created = self.calendar.post(
            "/calendars/primary/events", json_body=event,
            params={"sendUpdates": "all" if arguments.get("attendees") else "none"})
        return f"Created “{event['summary']}”: {created.get('htmlLink', '')}"

    @staticmethod
    def _required(arguments: dict, name: str) -> str:
        value = str(arguments.get(name, "")).strip()
        if not value:
            raise IntegrationError(f"{name} is required.",
                                   remedy=f"Give a value for {name}.")
        return value
