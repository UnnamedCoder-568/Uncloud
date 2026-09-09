"""Notion: pages, databases, search, and writing content.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Connected with an internal integration token, which the user creates in their
own workspace settings. No OAuth, no application registration.

**The step people get wrong is sharing.** A Notion integration sees nothing
until each page or database is explicitly shared with it, and the symptom is a
search that returns an empty list rather than an error. `_search` says so when
it finds nothing, because "no results" and "you have not shared anything with
this integration yet" look identical and mean completely different things.

**Notion's content model is blocks, not text.** A page is a tree of typed
blocks; reading one means walking it and flattening, and writing one means
constructing paragraph blocks. That conversion is the bulk of this file.
"""

from __future__ import annotations

from ...auth import AuthKind, Scope
from ..capabilities import Capability
from ..contract import Action, Change, Integration, IntegrationError, Sensitivity
from .rest import Rest

API = "https://api.notion.com/v1"

#: Notion pins behaviour to a dated version. Without it the API picks one, and
#: response shapes change under you between deploys.
VERSION = "2022-06-28"


class Notion(Integration):
    def __init__(self, *, client_factory=None) -> None:
        super().__init__(
            id="notion",
            name="Notion",
            summary="Pages and databases in your workspace.",
            sensitivity=Sensitivity.PRIVATE,
            available=True,
            auth_kind=AuthKind.TOKEN,
            needs="An internal integration token from "
                  "notion.so/my-integrations. Each page or database also has "
                  "to be shared with the integration — it sees nothing by "
                  "default.",
            scopes=(
                Scope(id="read", summary="Read pages shared with it"),
                Scope(id="insert", summary="Add content to shared pages",
                      required=False),
                Scope(id="update", summary="Change shared pages",
                      required=False),
            ),
            actions=(
                Action(id="notion.search", capability=Capability.NOTES_SEARCH,
                       summary="Search pages and databases",
                       parameters={"query": "text to look for",
                                   "type": "optional: page or database"}),
                Action(id="notion.read_page",
                       capability=Capability.NOTES_PAGE_READ,
                       summary="Read a page as text",
                       parameters={"page_id": "the page's ID or URL"}),
                Action(id="notion.query_database",
                       capability=Capability.NOTES_DATABASE_QUERY,
                       summary="List rows in a database",
                       parameters={"database_id": "", "limit": "optional"}),
                Action(id="notion.create_page",
                       capability=Capability.NOTES_PAGE_CREATE,
                       summary="Create a page",
                       parameters={"parent_id": "page or database to create in",
                                   "title": "", "content": "paragraphs, "
                                                           "one per line"}),
                Action(id="notion.append",
                       capability=Capability.NOTES_PAGE_WRITE,
                       summary="Add paragraphs to an existing page",
                       parameters={"page_id": "", "content": "paragraphs, "
                                                             "one per line"}),
            ))
        self._rest = Rest("notion", API, kind=AuthKind.TOKEN,
                          client_factory=client_factory,
                          extra_headers={"Notion-Version": VERSION})

    def account(self) -> str:
        return ""

    def whoami(self) -> str:
        body = self._rest.get("/users/me")
        bot = body.get("bot") or {}
        owner = (bot.get("owner") or {}).get("workspace")
        name = body.get("name") or "integration"
        return f"{name} ({'workspace' if owner else 'user'})"

    # ---------------------------------------------------------------- ids
    @staticmethod
    def _identifier(given: str) -> str:
        """A Notion ID out of whatever the user pasted.

        People paste URLs. The ID is the last 32 hex characters, with or
        without dashes, and requiring the bare form would make this fail on the
        thing everybody actually has to hand.
        """
        raw = str(given or "").strip()
        if not raw:
            raise IntegrationError("No page or database was given.",
                                   remedy="Paste its ID or URL.")
        tail = raw.rstrip("/").split("/")[-1].split("?")[0]
        candidate = tail.split("-")[-1] if "-" in tail else tail
        compact = candidate.replace("-", "")
        if len(compact) == 32 and all(c in "0123456789abcdefABCDEF" for c in compact):
            return compact
        compact = raw.replace("-", "")
        if len(compact) == 32:
            return compact
        raise IntegrationError(
            f"{raw!r} does not look like a Notion ID.",
            remedy="Copy the page link, or use the 32-character ID.")

    # ------------------------------------------------------------- content
    @staticmethod
    def _plain(rich: list) -> str:
        return "".join(part.get("plain_text", "") for part in rich or [])

    def _flatten(self, blocks: list) -> str:
        """A block tree as readable text.

        Only the block types that carry prose. A page of unsupported embeds
        returning nothing is better than one returning `[unsupported]` forty
        times, which is what a model would then try to summarise.
        """
        lines = []
        for block in blocks:
            kind = block.get("type", "")
            payload = block.get(kind) or {}
            text = self._plain(payload.get("rich_text") or [])
            if not text:
                continue
            if kind.startswith("heading_"):
                lines.append(f"{'#' * int(kind[-1])} {text}")
            elif kind == "bulleted_list_item":
                lines.append(f"- {text}")
            elif kind == "numbered_list_item":
                lines.append(f"1. {text}")
            elif kind == "to_do":
                done = "x" if payload.get("checked") else " "
                lines.append(f"- [{done}] {text}")
            elif kind == "code":
                lines.append(f"```\n{text}\n```")
            else:
                lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _paragraphs(content: str) -> list[dict]:
        return [
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": [{"type": "text",
                                          "text": {"content": line[:2000]}}]}}
            for line in str(content or "").splitlines() if line.strip()
        ]

    # --------------------------------------------------------------- preview
    async def preview(self, action_id: str, arguments: dict) -> Change | None:
        if action_id == "notion.create_page":
            return Change(
                summary=f"Create the page “{arguments.get('title', '')}”",
                target=f"in {arguments.get('parent_id', '')}",
                detail=f"{len(self._paragraphs(arguments.get('content', '')))} "
                       f"paragraph(s)",
                reversible=True,
                body=str(arguments.get("content", ""))[:1000])
        if action_id == "notion.append":
            return Change(
                summary="Add content to a Notion page",
                target=str(arguments.get("page_id", "")),
                detail=f"{len(self._paragraphs(arguments.get('content', '')))} "
                       f"paragraph(s)",
                reversible=True,
                body=str(arguments.get("content", ""))[:1000])
        return None

    # --------------------------------------------------------------- actions
    async def run(self, action_id: str, arguments: dict) -> str:
        if action_id == "notion.search":
            return self._search(arguments)
        if action_id == "notion.read_page":
            return self._read_page(arguments)
        if action_id == "notion.query_database":
            return self._query_database(arguments)
        if action_id == "notion.create_page":
            return self._create_page(arguments)
        if action_id == "notion.append":
            return self._append(arguments)
        raise IntegrationError(f"{action_id} is not something Notion can do.",
                               remedy="Ask for one of: "
                                      + ", ".join(a.id for a in self.actions))

    def _title_of(self, item: dict) -> str:
        properties = item.get("properties") or {}
        for value in properties.values():
            if value.get("type") == "title":
                return self._plain(value.get("title") or []) or "Untitled"
        return self._plain(item.get("title") or []) or "Untitled"

    def _search(self, arguments: dict) -> str:
        body: dict = {"query": str(arguments.get("query", "")), "page_size": 25}
        if arguments.get("type") in {"page", "database"}:
            body["filter"] = {"property": "object", "value": arguments["type"]}
        payload = self._rest.post("/search", json_body=body)
        results = payload.get("results") or []
        if not results:
            # The failure everybody hits first, and it looks like success.
            return ("Nothing found. Note that a Notion integration sees only "
                    "pages and databases that have been shared with it — open "
                    "the page, and use ••• → Connections to add this "
                    "integration.")
        return "\n".join(
            f"[{r.get('object')}] {self._title_of(r)} — {r.get('id')}"
            for r in results)

    def _read_page(self, arguments: dict) -> str:
        page_id = self._identifier(arguments.get("page_id", ""))
        page = self._rest.get(f"/pages/{page_id}")
        blocks = self._rest.get(f"/blocks/{page_id}/children",
                                params={"page_size": 100})
        text = self._flatten(blocks.get("results") or [])
        return f"# {self._title_of(page)}\n\n{text}".strip()

    def _query_database(self, arguments: dict) -> str:
        database_id = self._identifier(arguments.get("database_id", ""))
        payload = self._rest.post(
            f"/databases/{database_id}/query",
            json_body={"page_size": min(int(arguments.get("limit") or 50), 100)})
        rows = payload.get("results") or []
        if not rows:
            return "The database has no rows the integration can see."
        return "\n".join(f"{self._title_of(r)} — {r.get('id')}" for r in rows)

    def _create_page(self, arguments: dict) -> str:
        parent_id = self._identifier(arguments.get("parent_id", ""))
        title = str(arguments.get("title", "")).strip()
        if not title:
            raise IntegrationError("A page needs a title.", remedy="Give one.")

        # A database parent needs the title under its own title property; a
        # page parent uses `title`. Getting this wrong is a 400 with a message
        # nobody can act on, so both shapes are tried in the order that is
        # cheapest to be wrong about.
        body = {
            "parent": {"page_id": parent_id},
            "properties": {"title": {"title": [
                {"type": "text", "text": {"content": title}}]}},
            "children": self._paragraphs(arguments.get("content", "")),
        }
        try:
            page = self._rest.post("/pages", json_body=body)
        except IntegrationError:
            body["parent"] = {"database_id": parent_id}
            page = self._rest.post("/pages", json_body=body)
        return f"Created “{title}”: {page.get('url') or page.get('id')}"

    def _append(self, arguments: dict) -> str:
        page_id = self._identifier(arguments.get("page_id", ""))
        blocks = self._paragraphs(arguments.get("content", ""))
        if not blocks:
            raise IntegrationError("There is nothing to add.",
                                   remedy="Give some text.")
        self._rest.patch(f"/blocks/{page_id}/children",
                         json_body={"children": blocks})
        return f"Added {len(blocks)} paragraph(s)."
