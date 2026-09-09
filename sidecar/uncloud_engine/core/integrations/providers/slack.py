"""Slack: channels, messages, threads, search and posting.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Connected with a bot or user token from an app installed into the workspace.
That still needs somebody to create the app — Slack has no equivalent of a
personal access token — but it needs no OAuth redirect, so the connection is a
paste rather than a browser round trip.

**Slack answers 200 for its own failures.** `{"ok": false, "error":
"channel_not_found"}` arrives with a perfectly good HTTP status, so an adapter
that only checked the status code would treat every refusal as success and hand
the model an empty result. `_call` unwraps that, which is most of why this file
exists rather than using `Rest` directly.

**Search needs a USER token, posting works with a bot token.** Different tokens
grant different things, and "search is not available with a bot token" is a
sentence somebody can act on where `not_allowed_token_type` is not.
"""

from __future__ import annotations

from ...auth import AuthKind, Scope
from ..capabilities import Capability
from ..contract import Action, Change, Integration, IntegrationError, Sensitivity
from .rest import Rest

API = "https://slack.com/api"


class Slack(Integration):
    def __init__(self, *, client_factory=None) -> None:
        super().__init__(
            id="slack",
            name="Slack",
            summary="Channels, messages and threads.",
            sensitivity=Sensitivity.PRIVATE,
            available=True,
            auth_kind=AuthKind.TOKEN,
            needs="A token from a Slack app installed into your workspace "
                  "(api.slack.com/apps). A bot token can read and post; "
                  "searching needs a user token.",
            scopes=(
                Scope(id="channels:read", summary="See which channels exist"),
                Scope(id="channels:history", summary="Read messages in "
                                                     "channels it is in"),
                Scope(id="chat:write", summary="Post messages as the app"),
                Scope(id="search:read", summary="Search messages "
                                                "(user token only)",
                      required=False),
            ),
            actions=(
                Action(id="slack.channels",
                       capability=Capability.CHAT_CHANNEL_LIST,
                       summary="List channels",
                       parameters={"query": "optional name filter"}),
                Action(id="slack.history",
                       capability=Capability.CHAT_MESSAGE_READ,
                       summary="Read recent messages in a channel",
                       parameters={"channel": "name or ID",
                                   "limit": "optional, default 30",
                                   "thread_ts": "optional, to read a thread"}),
                Action(id="slack.search",
                       capability=Capability.CHAT_MESSAGE_SEARCH,
                       summary="Search messages",
                       parameters={"query": "Slack search syntax"}),
                Action(id="slack.post",
                       capability=Capability.CHAT_MESSAGE_SEND,
                       summary="Post a message",
                       parameters={"channel": "name or ID", "text": "",
                                   "thread_ts": "optional, to reply in "
                                                "a thread"}),
            ))
        self._rest = Rest("slack", API, kind=AuthKind.TOKEN,
                          client_factory=client_factory)

    # ----------------------------------------------------------------- calls
    def _call(self, method: str, *, params: dict | None = None,
              body: dict | None = None) -> dict:
        """One Slack call, with Slack's own idea of failure unwrapped.

        `{"ok": false}` arrives with HTTP 200. An adapter that trusted the
        status would hand the model an empty result and no reason.
        """
        if body is None:
            payload = self._rest.get(f"/{method}", params=params)
        else:
            payload = self._rest.post(f"/{method}", json_body=body)
        if not isinstance(payload, dict):
            raise IntegrationError(
                f"Slack returned something unexpected from {method}.",
                remedy="Try again; if it persists the token may be wrong.")
        if payload.get("ok"):
            return payload
        raise self._explain(str(payload.get("error") or "unknown_error"), method)

    def _explain(self, error: str, method: str) -> IntegrationError:
        known = {
            "channel_not_found": (
                "No such channel, or the app has not been added to it.",
                "Invite the app to the channel: /invite @your-app"),
            "not_in_channel": (
                "The app is not in that channel.",
                "Invite it: /invite @your-app"),
            "missing_scope": (
                "The token does not have the permission this needs.",
                "Add the scope to the Slack app and reinstall it."),
            "not_allowed_token_type": (
                "Searching needs a user token; this is a bot token.",
                "Connect with a user token (xoxp-) to search."),
            "invalid_auth": ("Slack rejected the token.",
                             "Reconnect with a current token."),
            "token_revoked": ("The token has been revoked.",
                              "Reconnect with a new token."),
            "ratelimited": ("Slack is rate limiting.", "Wait and try again."),
        }
        message, remedy = known.get(
            error, (f"Slack refused {method}: {error}", "Check the arguments."))
        return IntegrationError(
            message, remedy=remedy,
            needs_reconnect=error in {"invalid_auth", "token_revoked"},
            retryable=error == "ratelimited")

    def account(self) -> str:
        return ""

    def whoami(self) -> str:
        payload = self._call("auth.test")
        team, user = payload.get("team", ""), payload.get("user", "")
        return f"{user} at {team}" if team else user

    # ---------------------------------------------------------------- lookup
    def _channel_id(self, given: str) -> str:
        """Accept a name or an ID.

        A model that has read a channel list will say `#general`; a person will
        too. Requiring `C01234567` would make every call a two-step dance.
        """
        name = given.strip().lstrip("#")
        if not name:
            raise IntegrationError("No channel was given.",
                                   remedy="Name a channel.")
        if name.startswith(("C", "G", "D")) and name.isalnum() and name.isupper():
            return name
        payload = self._call("conversations.list", params={
            "limit": 1000, "types": "public_channel,private_channel"})
        for channel in payload.get("channels", []):
            if channel.get("name") == name:
                return channel["id"]
        raise IntegrationError(
            f"There is no channel called #{name} that this token can see.",
            remedy="Check the name, or add the app to the channel.")

    # --------------------------------------------------------------- preview
    async def preview(self, action_id: str, arguments: dict) -> Change | None:
        if action_id != "slack.post":
            return None
        channel = str(arguments.get("channel", ""))
        return Change(
            summary=f"Post to #{channel.lstrip('#')}",
            target=f"#{channel.lstrip('#')}",
            detail="as a thread reply" if arguments.get("thread_ts") else "",
            # A Slack message can be deleted, but everybody in the channel has
            # already seen it.
            reversible=False,
            body=str(arguments.get("text", ""))[:1000])

    # --------------------------------------------------------------- actions
    async def run(self, action_id: str, arguments: dict) -> str:
        if action_id == "slack.channels":
            return self._channels(arguments)
        if action_id == "slack.history":
            return self._history(arguments)
        if action_id == "slack.search":
            return self._search(arguments)
        if action_id == "slack.post":
            return self._post(arguments)
        raise IntegrationError(f"{action_id} is not something Slack can do.",
                               remedy="Ask for one of: "
                                      + ", ".join(a.id for a in self.actions))

    def _channels(self, arguments: dict) -> str:
        payload = self._call("conversations.list", params={
            "limit": 1000, "types": "public_channel,private_channel",
            "exclude_archived": "true"})
        needle = str(arguments.get("query", "")).lower().lstrip("#")
        rows = [c for c in payload.get("channels", [])
                if not needle or needle in c.get("name", "").lower()]
        if not rows:
            return "No channels matched."
        return "\n".join(
            f"#{c['name']}{' (private)' if c.get('is_private') else ''}"
            f" — {(c.get('purpose') or {}).get('value') or 'no purpose set'}"
            for c in sorted(rows, key=lambda c: c.get("name", "")))

    def _history(self, arguments: dict) -> str:
        channel = self._channel_id(str(arguments.get("channel", "")))
        limit = min(int(arguments.get("limit") or 30), 200)
        if arguments.get("thread_ts"):
            payload = self._call("conversations.replies", params={
                "channel": channel, "ts": arguments["thread_ts"], "limit": limit})
        else:
            payload = self._call("conversations.history", params={
                "channel": channel, "limit": limit})
        messages = payload.get("messages", [])
        if not messages:
            return "No messages."
        # Oldest first: Slack returns newest first, and a conversation read
        # backwards is one the model summarises backwards.
        return "\n".join(
            f"[{m.get('ts', '')}] {m.get('user') or m.get('bot_id') or '?'}: "
            f"{m.get('text', '')}"
            for m in reversed(messages))

    def _search(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise IntegrationError("No search text was given.",
                                   remedy="Say what to look for.")
        payload = self._call("search.messages",
                             params={"query": query, "count": 20})
        matches = (payload.get("messages") or {}).get("matches") or []
        if not matches:
            return f"Nothing found for {query!r}."
        return "\n".join(
            f"#{m.get('channel', {}).get('name', '?')} "
            f"{m.get('username', '?')}: {m.get('text', '')}"
            for m in matches)

    def _post(self, arguments: dict) -> str:
        text = str(arguments.get("text", "")).strip()
        if not text:
            raise IntegrationError("There is no message to post.",
                                   remedy="Give some text.")
        channel = self._channel_id(str(arguments.get("channel", "")))
        body = {"channel": channel, "text": text}
        if arguments.get("thread_ts"):
            body["thread_ts"] = arguments["thread_ts"]
        payload = self._call("chat.postMessage", body=body)
        return f"Posted to {arguments.get('channel')} at {payload.get('ts', '')}."
