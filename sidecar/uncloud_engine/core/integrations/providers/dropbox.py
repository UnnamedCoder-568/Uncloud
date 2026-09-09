"""Dropbox: files and folders, listed, searched, read and written.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Connected with an access token generated in the Dropbox App Console, or through
OAuth once a client ID is configured. Both paths are supported because the
token path lets somebody try this in a minute while the OAuth path is what a
real deployment wants.

**Dropbox splits its API across two hosts.** Metadata goes to `api` as JSON;
content goes to `content` with the arguments in a header and the bytes in the
body. That is not a wrapper detail — it is why this file does not simply use
`Rest` for everything.

**Paths are Dropbox-shaped.** The root is `""`, not `"/"`, and a leading slash
is required everywhere else. Passing `/` where Dropbox wants `""` produces an
error message that mentions neither.
"""

from __future__ import annotations

import json

from ...auth import AuthKind, ProviderConfig, Scope, authorize
from ..capabilities import Capability
from ..contract import Action, Change, Integration, IntegrationError, Sensitivity
from .rest import Rest

API = "https://api.dropboxapi.com/2"
CONTENT = "https://content.dropboxapi.com/2"

DEFAULTS = ProviderConfig(
    provider="dropbox",
    authorize_url="https://www.dropbox.com/oauth2/authorize",
    token_url="https://api.dropboxapi.com/oauth2/token",
    # Without this Dropbox issues a short-lived token and no refresh token, and
    # the connection dies after four hours with no way to renew it.
    extra_authorize={"token_access_type": "offline"})

#: Beyond this a file is not something to hand a model. Dropbox will serve it;
#: the context window will not take it.
MAX_DOWNLOAD = 10_000_000


class Dropbox(Integration):
    def __init__(self, *, client_factory=None) -> None:
        super().__init__(
            id="dropbox",
            name="Dropbox",
            summary="Files and folders in your Dropbox.",
            sensitivity=Sensitivity.PRIVATE,
            available=True,
            auth_kind=AuthKind.OAUTH2_PKCE,
            defaults=DEFAULTS,
            needs="An app in the Dropbox App Console. For a quick trial, "
                  "generate an access token there and paste it; for a lasting "
                  "connection, enter the app key and sign in.",
            scopes=(
                Scope(id="files.metadata.read", summary="See your file names "
                                                        "and folders"),
                Scope(id="files.content.read", summary="Read file contents"),
                Scope(id="files.content.write", summary="Add and change files",
                      required=False),
            ),
            actions=(
                Action(id="dropbox.list", capability=Capability.STORAGE_LIST,
                       summary="List a folder",
                       parameters={"path": "folder path; empty for the root"}),
                Action(id="dropbox.search", capability=Capability.STORAGE_SEARCH,
                       summary="Search for files by name",
                       parameters={"query": "", "path": "optional folder to "
                                                        "search within"}),
                Action(id="dropbox.read", capability=Capability.STORAGE_READ,
                       summary="Read a text file",
                       parameters={"path": "full path to the file"}),
                Action(id="dropbox.write", capability=Capability.STORAGE_WRITE,
                       summary="Write a text file",
                       parameters={"path": "full path", "content": "",
                                   "overwrite": "optional, default false"}),
            ))
        self._client_factory = client_factory
        self._rest = Rest("dropbox", API, kind=AuthKind.OAUTH2_PKCE,
                          defaults=DEFAULTS, client_factory=client_factory)

    def account(self) -> str:
        return ""

    def whoami(self) -> str:
        body = self._rest.post("/users/get_current_account", json_body=None)
        name = (body.get("name") or {}).get("display_name") or ""
        return f"{name} ({body.get('email', '')})".strip()

    @staticmethod
    def _path(given: str, *, allow_root: bool = False) -> str:
        """A Dropbox path.

        The root is the empty string rather than `/`, which is the one piece of
        this API that catches everybody.
        """
        raw = str(given or "").strip()
        if raw in {"", "/"}:
            if allow_root:
                return ""
            raise IntegrationError("No file path was given.",
                                   remedy="Give a full path, e.g. /Reports/q1.txt.")
        return raw if raw.startswith("/") else f"/{raw}"

    def _content_call(self, path: str, arguments: dict, *,
                      body: bytes | None = None) -> object:
        """A call to the content host, where arguments travel in a header.

        Written out rather than folded into `Rest` because the shape is genuinely
        different: JSON in a header, bytes in the body, and a non-JSON response.
        """
        headers = dict(authorize("dropbox", AuthKind.OAUTH2_PKCE, DEFAULTS))
        headers["Dropbox-API-Arg"] = json.dumps(arguments)
        headers["Content-Type"] = "application/octet-stream"

        client = (self._client_factory() if self._client_factory
                  else _default_client())
        response = client.request("POST", f"{CONTENT}{path}",
                                  headers=headers, content=body or b"")
        if response.status_code >= 400:
            raise self._rest._explain(response)
        return response

    # --------------------------------------------------------------- preview
    async def preview(self, action_id: str, arguments: dict) -> Change | None:
        if action_id != "dropbox.write":
            return None
        path = self._path(arguments.get("path", ""))
        overwrite = bool(arguments.get("overwrite"))
        return Change(
            summary=("Overwrite" if overwrite else "Write") + f" {path}",
            target=path,
            detail=f"{len(str(arguments.get('content', '')))} characters",
            # Dropbox keeps versions, so even an overwrite is recoverable —
            # stated accurately rather than pessimistically, because a prompt
            # that cries wolf gets clicked through.
            reversible=True,
            body=str(arguments.get("content", ""))[:1000])

    # --------------------------------------------------------------- actions
    async def run(self, action_id: str, arguments: dict) -> str:
        if action_id == "dropbox.list":
            return self._list(arguments)
        if action_id == "dropbox.search":
            return self._search(arguments)
        if action_id == "dropbox.read":
            return self._read(arguments)
        if action_id == "dropbox.write":
            return self._write(arguments)
        raise IntegrationError(f"{action_id} is not something Dropbox can do.",
                               remedy="Ask for one of: "
                                      + ", ".join(a.id for a in self.actions))

    def _list(self, arguments: dict) -> str:
        body = self._rest.post("/files/list_folder", json_body={
            "path": self._path(arguments.get("path", ""), allow_root=True),
            "limit": 200})
        entries = body.get("entries") or []
        if not entries:
            return "The folder is empty."
        return "\n".join(
            f"{e['name']}{'/' if e['.tag'] == 'folder' else ''}"
            + (f"  ({e['size'] / 1024:.0f} KB)" if e.get("size") else "")
            for e in entries)

    def _search(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise IntegrationError("No search text was given.",
                                   remedy="Say what to look for.")
        options = {"max_results": 25}
        if arguments.get("path"):
            options["path"] = self._path(arguments["path"], allow_root=True)
        body = self._rest.post("/files/search_v2",
                               json_body={"query": query, "options": options})
        matches = body.get("matches") or []
        if not matches:
            return f"Nothing found for {query!r}."
        rows = []
        for match in matches:
            item = (match.get("metadata") or {}).get("metadata") or {}
            if item.get("path_display"):
                rows.append(item["path_display"])
        return "\n".join(rows) or f"Nothing found for {query!r}."

    def _read(self, arguments: dict) -> str:
        path = self._path(arguments.get("path", ""))
        response = self._content_call("/files/download", {"path": path})
        content = response.content
        if len(content) > MAX_DOWNLOAD:
            raise IntegrationError(
                f"{path} is {len(content) / 1e6:.0f} MB, which is too large to "
                f"read in one piece.",
                remedy="Open it directly, or point at a smaller file.")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IntegrationError(
                f"{path} is not a text file.",
                remedy="Only text can be read this way.") from exc

    def _write(self, arguments: dict) -> str:
        path = self._path(arguments.get("path", ""))
        content = str(arguments.get("content", ""))
        mode = "overwrite" if arguments.get("overwrite") else "add"
        response = self._content_call(
            "/files/upload",
            {"path": path, "mode": mode, "autorename": mode == "add",
             "mute": True},
            body=content.encode("utf-8"))
        try:
            written = response.json().get("path_display", path)
        except ValueError:
            written = path
        return f"Wrote {written} ({len(content)} characters)."


def _default_client():
    import httpx

    return httpx.Client(timeout=120.0)
