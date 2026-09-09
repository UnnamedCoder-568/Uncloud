"""Microsoft 365: OneDrive, Outlook, Word, Excel, PowerPoint and Teams.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

One API for all of it — Microsoft Graph — which makes this shorter than Google
despite covering more. As with Google, every call is real and the OAuth client
is not ours to ship: an app registration in Entra ID belongs to whoever
publishes the build, so this reports NOT_CONFIGURED until one is entered.

Three things this API does differently from Google's.

**Excel is edited in place through Graph, not exported.** A workbook has a
`/workbook/worksheets/{name}/range(address='A1:D9')` endpoint that reads and
writes cells directly, which is better than round-tripping a file — but it
works only on files stored in OneDrive or SharePoint.

**Word and PowerPoint have no content API.** Graph will hand over the file and
take one back, and that is all. So `document.read` downloads the .docx and
parses it with the reader this package already has, and creating one builds the
file locally and uploads it. That is not a workaround: it is the only path
Microsoft offers, and it happens to reuse code that already exists.

**`/me` needs a delegated token.** Everything here is user-delegated rather
than application permissions, because an agent acting as you is the whole
point.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ...auth import AuthKind, ProviderConfig, Scope
from .. import documents as documents_reader
from .. import ooxml
from ..capabilities import Capability
from ..contract import Action, Change, Integration, IntegrationError, Sensitivity
from .rest import Rest

GRAPH = "https://graph.microsoft.com/v1.0"

DEFAULTS = ProviderConfig(
    provider="microsoft",
    # `common` lets both work and personal accounts sign in. A tenant-specific
    # authority is the other sensible choice and is what the configuration
    # screen lets somebody enter instead.
    authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
    # Without `offline_access` in the scopes Microsoft issues no refresh token.
    # It is requested below rather than here because Graph takes it as a scope.
    extra_authorize={})

SCOPES = (
    Scope(id="offline_access", summary="Stay signed in"),
    Scope(id="User.Read", summary="Read your name and email"),
    Scope(id="Files.ReadWrite", summary="Read and change your OneDrive files"),
    Scope(id="Mail.Read", summary="Read your mail", required=False),
    Scope(id="Mail.Send", summary="Send mail as you", required=False),
    Scope(id="Calendars.ReadWrite", summary="Read and add calendar events",
          required=False),
    Scope(id="ChannelMessage.Send", summary="Post to Teams channels",
          required=False),
    Scope(id="Team.ReadBasic.All", summary="See which Teams you are in",
          required=False),
)


class Microsoft(Integration):
    def __init__(self, *, client_factory=None) -> None:
        super().__init__(
            id="microsoft",
            name="Microsoft 365",
            summary="OneDrive, Outlook, Word, Excel, PowerPoint and Teams.",
            sensitivity=Sensitivity.PRIVATE,
            available=True,
            auth_kind=AuthKind.OAUTH2_PKCE,
            defaults=DEFAULTS,
            needs="An application registration in Microsoft Entra ID, with "
                  "http://127.0.0.1 as a mobile/desktop redirect and the "
                  "delegated permissions you want. Uncloud cannot supply one: "
                  "an app registration belongs to whoever publishes the build.",
            scopes=SCOPES,
            actions=(
                Action(id="microsoft.files_list",
                       capability=Capability.STORAGE_LIST,
                       summary="List OneDrive files",
                       parameters={"path": "optional folder path"}),
                Action(id="microsoft.files_search",
                       capability=Capability.STORAGE_SEARCH,
                       summary="Search OneDrive",
                       parameters={"query": ""}),
                Action(id="microsoft.file_read",
                       capability=Capability.STORAGE_READ,
                       summary="Read a text file from OneDrive",
                       parameters={"path": "full path, e.g. /Reports/q1.txt"}),
                Action(id="microsoft.file_write",
                       capability=Capability.STORAGE_WRITE,
                       summary="Write a text file to OneDrive",
                       parameters={"path": "", "content": ""}),
                Action(id="microsoft.word_read",
                       capability=Capability.DOCUMENT_READ,
                       summary="Read a Word document",
                       parameters={"path": "full path to the .docx"}),
                Action(id="microsoft.word_create",
                       capability=Capability.DOCUMENT_CREATE,
                       summary="Create a Word document",
                       parameters={"path": "full path ending .docx",
                                   "paragraphs": "list of lines",
                                   "title": "optional"}),
                Action(id="microsoft.excel_read",
                       capability=Capability.SPREADSHEET_READ,
                       summary="Read a range from an Excel workbook",
                       parameters={"path": "full path to the .xlsx",
                                   "sheet": "optional worksheet name",
                                   "range": "optional, e.g. A1:D50"}),
                Action(id="microsoft.excel_write",
                       capability=Capability.SPREADSHEET_WRITE,
                       summary="Write cells into an Excel workbook",
                       parameters={"path": "", "sheet": "", "range": "",
                                   "rows": "list of rows"}),
                Action(id="microsoft.powerpoint_create",
                       capability=Capability.PRESENTATION_CREATE,
                       summary="Create a PowerPoint deck",
                       parameters={"path": "full path ending .pptx",
                                   "slides": "list of {title, bullets}"}),
                Action(id="microsoft.mail_search",
                       capability=Capability.EMAIL_SEARCH,
                       summary="Search Outlook",
                       parameters={"query": "", "limit": "optional"}),
                Action(id="microsoft.mail_read",
                       capability=Capability.EMAIL_READ,
                       summary="Read one message",
                       parameters={"message_id": ""}),
                Action(id="microsoft.mail_draft",
                       capability=Capability.EMAIL_DRAFT,
                       summary="Save a draft",
                       parameters={"to": "", "subject": "", "body": ""}),
                Action(id="microsoft.mail_send",
                       capability=Capability.EMAIL_SEND,
                       summary="Send mail as you",
                       parameters={"to": "", "subject": "", "body": "",
                                   "cc": "optional"}),
                Action(id="microsoft.calendar_list",
                       capability=Capability.CALENDAR_READ,
                       summary="List upcoming events",
                       parameters={"limit": "optional"}),
                Action(id="microsoft.calendar_create",
                       capability=Capability.CALENDAR_CREATE,
                       summary="Create an event",
                       parameters={"subject": "", "start": "ISO 8601",
                                   "end": "ISO 8601", "attendees": "optional",
                                   "location": "optional"}),
                Action(id="microsoft.teams_list",
                       capability=Capability.CHAT_CHANNEL_LIST,
                       summary="List Teams channels you are in",
                       parameters={}),
                Action(id="microsoft.teams_post",
                       capability=Capability.CHAT_MESSAGE_SEND,
                       summary="Post to a Teams channel",
                       parameters={"team_id": "", "channel_id": "",
                                   "text": ""}),
            ))
        self._graph = Rest("microsoft", GRAPH, kind=AuthKind.OAUTH2_PKCE,
                           defaults=DEFAULTS, client_factory=client_factory)
        self._client_factory = client_factory

    def account(self) -> str:
        return ""

    def whoami(self) -> str:
        body = self._graph.get("/me")
        return str(body.get("userPrincipalName") or body.get("mail") or
                   body.get("displayName", ""))

    # ------------------------------------------------------------ path help
    @staticmethod
    def _drive_item(path: str) -> str:
        """Graph's addressing for a file by path.

        `/me/drive/root:/Reports/q1.txt:` — the colons are not a typo; they are
        how Graph separates a path from the action that follows it, and getting
        them wrong produces a 400 that mentions neither.
        """
        clean = str(path or "").strip().lstrip("/")
        if not clean:
            raise IntegrationError("No file path was given.",
                                   remedy="Give a path, e.g. /Reports/q1.xlsx.")
        return f"/me/drive/root:/{clean}:"

    def _download(self, path: str) -> bytes:
        """Fetch a file's bytes.

        Graph answers `/content` with a redirect to storage, so this follows
        one — which `Rest` does not, because everywhere else a redirect would
        be a surprise.
        """
        from ...auth import authorize

        headers = dict(authorize("microsoft", AuthKind.OAUTH2_PKCE, DEFAULTS))
        client = (self._client_factory() if self._client_factory
                  else _default_client())
        response = client.request(
            "GET", f"{GRAPH}{self._drive_item(path)}/content",
            headers=headers, follow_redirects=True)
        if response.status_code >= 400:
            raise self._graph._explain(response)
        return response.content

    def _upload(self, path: str, data: bytes) -> str:
        from ...auth import authorize

        headers = dict(authorize("microsoft", AuthKind.OAUTH2_PKCE, DEFAULTS))
        headers["Content-Type"] = "application/octet-stream"
        client = (self._client_factory() if self._client_factory
                  else _default_client())
        response = client.request(
            "PUT", f"{GRAPH}{self._drive_item(path)}/content",
            headers=headers, content=data)
        if response.status_code >= 400:
            raise self._graph._explain(response)
        try:
            return str(response.json().get("webUrl") or path)
        except ValueError:
            return path

    # --------------------------------------------------------------- preview
    async def preview(self, action_id: str, arguments: dict) -> Change | None:
        if action_id in {"microsoft.mail_send", "microsoft.mail_draft"}:
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
        if action_id == "microsoft.calendar_create":
            attendees = arguments.get("attendees") or []
            return Change(
                summary=f"Create “{arguments.get('subject', '')}”",
                target=f"{arguments.get('start', '')} → {arguments.get('end', '')}",
                detail=(f"invites {', '.join(attendees)}" if attendees
                        else "no attendees"),
                reversible=not attendees)
        if action_id == "microsoft.teams_post":
            return Change(
                summary="Post to a Teams channel",
                target=f"channel {arguments.get('channel_id', '')}",
                reversible=False,
                body=str(arguments.get("text", ""))[:1000])
        if action_id in {"microsoft.file_write", "microsoft.word_create",
                         "microsoft.powerpoint_create"}:
            return Change(
                summary=f"Write {arguments.get('path', '')}",
                target="OneDrive",
                detail="An existing file at that path is replaced.",
                reversible=True,
                body=str(arguments.get("content", ""))[:1000])
        if action_id == "microsoft.excel_write":
            rows = arguments.get("rows") or []
            return Change(
                summary=f"Write {len(rows)} row(s)",
                target=f"{arguments.get('path', '')} "
                       f"{arguments.get('sheet', '')}!{arguments.get('range', '')}",
                detail="Existing values in that range are replaced.",
                reversible=False)
        return None

    # --------------------------------------------------------------- actions
    async def run(self, action_id: str, arguments: dict) -> str:
        handlers = {
            "microsoft.files_list": self._files_list,
            "microsoft.files_search": self._files_search,
            "microsoft.file_read": self._file_read,
            "microsoft.file_write": self._file_write,
            "microsoft.word_read": self._word_read,
            "microsoft.word_create": self._word_create,
            "microsoft.excel_read": self._excel_read,
            "microsoft.excel_write": self._excel_write,
            "microsoft.powerpoint_create": self._powerpoint_create,
            "microsoft.mail_search": self._mail_search,
            "microsoft.mail_read": self._mail_read,
            "microsoft.mail_draft": lambda a: self._mail_out(a, send=False),
            "microsoft.mail_send": lambda a: self._mail_out(a, send=True),
            "microsoft.calendar_list": self._calendar_list,
            "microsoft.calendar_create": self._calendar_create,
            "microsoft.teams_list": self._teams_list,
            "microsoft.teams_post": self._teams_post,
        }
        handler = handlers.get(action_id)
        if handler is None:
            raise IntegrationError(
                f"{action_id} is not something Microsoft 365 can do.",
                remedy="Ask for one of: " + ", ".join(a.id for a in self.actions))
        return handler(arguments)

    # -------------------------------------------------------------- OneDrive
    def _files_list(self, arguments: dict) -> str:
        path = str(arguments.get("path", "")).strip().lstrip("/")
        endpoint = (f"/me/drive/root:/{path}:/children" if path
                    else "/me/drive/root/children")
        body = self._graph.get(endpoint, params={"$top": 100})
        return self._file_rows(body)

    def _files_search(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise IntegrationError("No search text was given.",
                                   remedy="Say what to look for.")
        body = self._graph.get(f"/me/drive/root/search(q='{query}')",
                               params={"$top": 25})
        return self._file_rows(body)

    @staticmethod
    def _file_rows(body: dict) -> str:
        items = body.get("value") or []
        if not items:
            return "Nothing found."
        return "\n".join(
            f"{i['name']}{'/' if 'folder' in i else ''}"
            + (f"  ({i['size'] / 1024:.0f} KB)" if i.get("size") else "")
            + f"  modified {i.get('lastModifiedDateTime', '')}"
            for i in items)

    def _file_read(self, arguments: dict) -> str:
        data = self._download(str(arguments.get("path", "")))
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IntegrationError(
                "That file is not text.",
                remedy="Use word_read for .docx, or excel_read for .xlsx.",
            ) from exc

    def _file_write(self, arguments: dict) -> str:
        path = str(arguments.get("path", ""))
        written = self._upload(path,
                               str(arguments.get("content", "")).encode("utf-8"))
        return f"Wrote {path} ({written})."

    # ------------------------------------------------------------------ Word
    def _word_read(self, arguments: dict) -> str:
        """Download and parse.

        Graph has no content API for Word, so the file comes over and the
        reader already in this package handles it — which is why `documents`
        understanding .docx was worth building before any of this.
        """
        data = self._download(str(arguments.get("path", "")))
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "document.docx"
            local.write_bytes(data)
            return documents_reader.extract(local)

    def _word_create(self, arguments: dict) -> str:
        path = str(arguments.get("path", ""))
        if not path.lower().endswith(".docx"):
            raise IntegrationError(f"{path!r} does not end in .docx.",
                                   remedy="Word will not open it otherwise.")
        paragraphs = [str(p) for p in (arguments.get("paragraphs") or [])]
        if not paragraphs:
            raise IntegrationError("There is nothing to write.",
                                   remedy="Give at least one paragraph.")
        with tempfile.TemporaryDirectory() as directory:
            local = ooxml.write_docx(Path(directory) / "out.docx", paragraphs,
                                     title=str(arguments.get("title", "")))
            written = self._upload(path, local.read_bytes())
        return f"Created {path} ({written})."

    # ----------------------------------------------------------------- Excel
    def _excel_read(self, arguments: dict) -> str:
        """Read cells through Graph's workbook API rather than downloading.

        Only works for files in OneDrive or SharePoint, which is where the ones
        this integration can see live anyway — and it means a 200-row sheet is
        a small JSON response rather than a multi-megabyte download.
        """
        item = self._drive_item(str(arguments.get("path", "")))
        sheet = str(arguments.get("sheet", "")).strip()
        cells = str(arguments.get("range", "")).strip() or "A1:Z200"
        endpoint = (f"{item}/workbook/worksheets('{sheet}')/range(address='{cells}')"
                    if sheet else
                    f"{item}/workbook/worksheets/$/range(address='{cells}')")
        if not sheet:
            sheets = self._graph.get(f"{item}/workbook/worksheets")
            names = [s["name"] for s in sheets.get("value") or []]
            if not names:
                raise IntegrationError("That workbook has no worksheets.",
                                       remedy="Check the file.")
            endpoint = (f"{item}/workbook/worksheets('{names[0]}')"
                        f"/range(address='{cells}')")
        body = self._graph.get(endpoint)
        rows = body.get("values") or []
        if not rows:
            return "That range is empty."
        return "\n".join("\t".join(str(c) for c in row) for row in rows)

    def _excel_write(self, arguments: dict) -> str:
        item = self._drive_item(str(arguments.get("path", "")))
        sheet = str(arguments.get("sheet", "")).strip()
        cells = str(arguments.get("range", "")).strip()
        rows = [list(r) for r in (arguments.get("rows") or [])]
        if not sheet or not cells or not rows:
            raise IntegrationError(
                "Writing needs a sheet, a range and rows.",
                remedy="For example sheet='Sheet1', range='A1:C3'.")
        self._graph.patch(
            f"{item}/workbook/worksheets('{sheet}')/range(address='{cells}')",
            json_body={"values": rows})
        return f"Wrote {len(rows)} row(s) to {sheet}!{cells}."

    # ------------------------------------------------------------ PowerPoint
    def _powerpoint_create(self, arguments: dict) -> str:
        path = str(arguments.get("path", ""))
        if not path.lower().endswith(".pptx"):
            raise IntegrationError(f"{path!r} does not end in .pptx.",
                                   remedy="PowerPoint will not open it otherwise.")
        slides = []
        for entry in arguments.get("slides") or []:
            if isinstance(entry, dict):
                slides.append((str(entry.get("title", "")),
                               [str(b) for b in entry.get("bullets") or []]))
        if not slides:
            raise IntegrationError("There is nothing to write.",
                                   remedy="Give slides as {title, bullets}.")
        with tempfile.TemporaryDirectory() as directory:
            local = ooxml.write_pptx(Path(directory) / "out.pptx", slides)
            written = self._upload(path, local.read_bytes())
        return f"Created {path} with {len(slides)} slide(s) ({written})."

    # --------------------------------------------------------------- Outlook
    def _mail_search(self, arguments: dict) -> str:
        limit = min(int(arguments.get("limit") or 15), 50)
        query = str(arguments.get("query", "")).strip()
        params = {"$top": limit,
                  "$select": "id,subject,from,receivedDateTime,bodyPreview"}
        if query:
            # `$search` and `$orderby` cannot be combined in Graph; asking for
            # both is a 400 that says nothing useful.
            params["$search"] = f'"{query}"'
        else:
            params["$orderby"] = "receivedDateTime desc"
        body = self._graph.get("/me/messages", params=params)
        messages = body.get("value") or []
        if not messages:
            return "No matching mail."
        return "\n".join(
            f"[{m['id']}] {m.get('receivedDateTime', '')} "
            f"{((m.get('from') or {}).get('emailAddress') or {}).get('address', '')}: "
            f"{m.get('subject') or '(no subject)'}"
            for m in messages)

    def _mail_read(self, arguments: dict) -> str:
        message_id = str(arguments.get("message_id", "")).strip()
        if not message_id:
            raise IntegrationError("No message was given.",
                                   remedy="Use the id from a search.")
        message = self._graph.get(f"/me/messages/{message_id}")
        sender = ((message.get("from") or {}).get("emailAddress") or {})
        recipients = ", ".join(
            (r.get("emailAddress") or {}).get("address", "")
            for r in message.get("toRecipients") or [])
        content = (message.get("body") or {}).get("content", "")
        if (message.get("body") or {}).get("contentType") == "html":
            import re

            content = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content)).strip()
        return (f"From: {sender.get('address', '')}\nTo: {recipients}\n"
                f"Date: {message.get('receivedDateTime', '')}\n"
                f"Subject: {message.get('subject', '')}\n\n{content}")

    def _mail_out(self, arguments: dict, *, send: bool) -> str:
        to = str(arguments.get("to", "")).strip()
        if not to:
            raise IntegrationError("No recipient was given.",
                                   remedy="Give an address.")
        message = {
            "subject": str(arguments.get("subject", "")),
            "body": {"contentType": "Text",
                     "content": str(arguments.get("body", ""))},
            "toRecipients": [{"emailAddress": {"address": address.strip()}}
                             for address in to.split(",") if address.strip()],
        }
        if arguments.get("cc"):
            message["ccRecipients"] = [
                {"emailAddress": {"address": address.strip()}}
                for address in str(arguments["cc"]).split(",") if address.strip()]

        if send:
            self._graph.post("/me/sendMail",
                             json_body={"message": message, "saveToSentItems": True},
                             expect_json=False)
            return f"Sent to {to}."
        draft = self._graph.post("/me/messages", json_body=message)
        return f"Draft saved for {to} (id {draft.get('id', '')})."

    # -------------------------------------------------------------- Calendar
    def _calendar_list(self, arguments: dict) -> str:
        from datetime import UTC, datetime

        body = self._graph.get("/me/events", params={
            "$top": min(int(arguments.get("limit") or 20), 100),
            "$orderby": "start/dateTime",
            "$filter": f"start/dateTime ge '{datetime.now(UTC).isoformat()}'",
            "$select": "subject,start,end,location"})
        events = body.get("value") or []
        if not events:
            return "Nothing coming up."
        return "\n".join(
            f"{(e.get('start') or {}).get('dateTime', '')}  "
            f"{e.get('subject', '(no title)')}"
            + (f"  @ {(e.get('location') or {}).get('displayName', '')}"
               if (e.get("location") or {}).get("displayName") else "")
            for e in events)

    def _calendar_create(self, arguments: dict) -> str:
        subject = str(arguments.get("subject", "")).strip()
        start, end = arguments.get("start"), arguments.get("end")
        if not subject or not start or not end:
            raise IntegrationError(
                "An event needs a subject, a start and an end.",
                remedy="Give times in ISO 8601, e.g. 2026-03-04T10:00:00.")
        event = {
            "subject": subject,
            "start": {"dateTime": str(start), "timeZone": "UTC"},
            "end": {"dateTime": str(end), "timeZone": "UTC"},
        }
        if arguments.get("location"):
            event["location"] = {"displayName": str(arguments["location"])}
        if arguments.get("attendees"):
            event["attendees"] = [
                {"emailAddress": {"address": str(a)}, "type": "required"}
                for a in arguments["attendees"]]
        created = self._graph.post("/me/events", json_body=event)
        return f"Created “{subject}”: {created.get('webLink', '')}"

    # ----------------------------------------------------------------- Teams
    def _teams_list(self, arguments: dict) -> str:
        teams = self._graph.get("/me/joinedTeams")
        rows = []
        for team in teams.get("value") or []:
            channels = self._graph.get(f"/teams/{team['id']}/channels")
            for channel in channels.get("value") or []:
                rows.append(f"{team['displayName']} / {channel['displayName']}"
                            f"  team_id={team['id']} channel_id={channel['id']}")
        return "\n".join(rows) or "You are not in any Teams."

    def _teams_post(self, arguments: dict) -> str:
        team_id = str(arguments.get("team_id", "")).strip()
        channel_id = str(arguments.get("channel_id", "")).strip()
        text = str(arguments.get("text", "")).strip()
        if not team_id or not channel_id or not text:
            raise IntegrationError(
                "Posting needs a team, a channel and some text.",
                remedy="Use teams_list to find the ids.")
        self._graph.post(
            f"/teams/{team_id}/channels/{channel_id}/messages",
            json_body={"body": {"contentType": "text", "content": text}})
        return "Posted to the channel."


def _default_client():
    import httpx

    return httpx.Client(timeout=120.0)
