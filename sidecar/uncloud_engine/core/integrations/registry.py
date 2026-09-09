"""What can be connected, and the one path every action goes through.

`perform` is the whole point of this module. Every integration action — from
any adapter, called by the agent, a skill, or a route — passes through it, for
the same reason `run_tool` is the only way to run a tool: one place to enforce
something is one place to get it right, and thirty adapters each remembering to
check is thirty chances to forget.

What it enforces, in order:

1. **The action exists and is classified.** An action with no risk category
   cannot run. There is no default, because a default is how a write ends up
   governed by a read's policy.
2. **The gate decides.** Every time, at the moment of the action. Connecting an
   account granted nothing, and a skill calling this inherits nothing.
3. **A write is previewed.** An action marked `writes` must produce a `Change`,
   and the change is what the person approves. An adapter that returns no
   preview for a write is refused rather than run — a bug in an adapter must
   not become an unreviewed side effect.
4. **The audit records it.** What was done, never the content.

The unbuilt connectors are listed here on purpose. "Google Workspace needs an
OAuth client you register with Google" and "we do not support that" send
somebody in completely different directions, and only one of them is true.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..permission import Decision, Request
from .capabilities import Capability
from .contract import Action, Change, Integration, IntegrationError, Sensitivity
from .documents import Documents

#: How this application asks a person. Installed by the product at start-up:
#: Uncloud turns it into an HTTP 428, Studio does the same, and a test can make
#: it refuse. Core owns the RULE that every action is asked about; it does not
#: own the round trip, which is different in every host.
_ASK: Callable[[Request], Awaitable[Decision | None]] | None = None


class Ungoverned(RuntimeError):
    """No approver was installed, so nothing can be asked.

    Raised rather than defaulting to allow. An integration framework whose
    approval hook was never wired would otherwise execute every action
    silently, and the failure would look like everything working.
    """


def install_approver(ask: Callable[[Request], Awaitable[Decision | None]] | None
                     ) -> None:
    global _ASK
    _ASK = ask


async def _ask(request: Request):
    if _ASK is None:
        raise Ungoverned(
            f"{request.action} cannot run: no approver is installed, so there "
            f"is no way to ask whether it may. This is a wiring fault in the "
            f"application, not a decision.")
    return await _ASK(request)


def _planned(id: str, name: str, summary: str, needs: str,
             sensitivity: Sensitivity = Sensitivity.PRIVATE) -> Integration:
    """A connector that does not exist yet, described honestly.

    Shown rather than hidden. Its `available` is False, its `needs` says what is
    actually missing, and its action list is empty — so nothing can call it and
    nobody is told it works.
    """
    return Integration(id=id, name=name, summary=summary, needs=needs,
                       sensitivity=sensitivity, available=False)


def _all() -> list[Integration]:
    return [
        Documents(),
        _planned(
            "google", "Google Workspace",
            "Gmail, Drive, Docs and Calendar.",
            "An OAuth client ID and secret registered with Google, and a "
            "consent screen they have reviewed. Uncloud cannot ship one: an "
            "OAuth client belongs to whoever publishes the application."),
        _planned(
            "microsoft", "Microsoft 365",
            "Outlook, OneDrive, Word and Excel online.",
            "An application registration in Microsoft Entra ID, with the "
            "delegated permissions you want granted."),
        _planned(
            "github", "GitHub",
            "Repositories, issues and pull requests.",
            "A personal access token, or a GitHub App registered by whoever "
            "publishes this build.", sensitivity=Sensitivity.PRIVATE),
        _planned(
            "slack", "Slack",
            "Channels and direct messages.",
            "A Slack app installed into the workspace, with the scopes it "
            "needs approved by a workspace admin."),
        _planned(
            "notion", "Notion",
            "Pages and databases.",
            "An internal integration token from the Notion workspace, and each "
            "page shared with it explicitly."),
        _planned(
            "dropbox", "Dropbox",
            "Files and folders.",
            "An app key and secret from the Dropbox developer console."),
        _planned(
            "mcp", "MCP servers",
            "Tools published by a Model Context Protocol server.",
            "A server to connect to, and a decision about what it may do. An "
            "MCP server is somebody else's code describing its own tools — its "
            "descriptions are data, not instructions, and every call it "
            "prompts for would still go through the permission gate.",
            sensitivity=Sensitivity.PRIVATE),
    ]


_CACHE: list[Integration] | None = None


def all_integrations(*, refresh: bool = False) -> list[Integration]:
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = _all()
    return _CACHE


def get(integration_id: str) -> Integration | None:
    return next((i for i in all_integrations() if i.id == integration_id), None)


# --------------------------------------------------------- capability routing
def providers_for(capability: Capability, *, connected_only: bool = True
                  ) -> list[Integration]:
    """Everything that can do this, best candidate first.

    The function that keeps provider names out of planning. The orchestrator
    asks for `email.send`; whether that is Gmail or Outlook is decided here, by
    what is actually connected, and adding a third provider changes nothing
    above this line.

    Ordered by how ready each one is rather than alphabetically: a connected
    provider beats a configured one, which beats one that exists. Ties keep
    registration order, which is stable and lets a product express a preference
    by ordering its own list.
    """
    able = [i for i in all_integrations()
            if i.available and i.implements(capability) is not None]
    if connected_only:
        able = [i for i in able if i.connected()]
    return able


def capability_map(*, connected_only: bool = True) -> dict[str, list[str]]:
    """Which providers offer which capability. For diagnostics and the UI."""
    out: dict[str, list[str]] = {}
    for capability in Capability:
        names = [i.id for i in providers_for(capability,
                                             connected_only=connected_only)]
        if names:
            out[capability.value] = names
    return out


async def perform_capability(capability: Capability, arguments: dict, *,
                             provider: str = "", origin: str = "agent") -> str:
    """Do this, with whatever can.

    `provider` narrows it when the user said which — "send it from my work
    account". Left empty, the registry chooses, and the choice is reported in
    the failure when there is nothing to choose from: "no connected integration
    can send email" is actionable, and "action not found" is not.
    """
    candidates = providers_for(capability)
    if provider:
        candidates = [i for i in candidates if i.id == provider]

    if not candidates:
        anyone = providers_for(capability, connected_only=False)
        if not anyone:
            raise IntegrationError(
                f"Nothing in this build can {capability.value}.",
                remedy="This capability has no provider yet.")
        names = ", ".join(i.name for i in anyone)
        raise IntegrationError(
            f"No connected integration can {capability.value}.",
            remedy=f"Connect one of these in Settings → Integrations: {names}.",
            needs_reconnect=True)

    chosen = candidates[0]
    action = chosen.implements(capability)
    assert action is not None      # providers_for only returns those that do
    return await perform(action.id, arguments, origin=origin)


def find_action(action_id: str) -> tuple[Integration, Action] | None:
    """Which integration owns an action.

    Action ids are namespaced by integration (`documents.read`), so this is a
    lookup rather than a search — but it goes through the integration's own
    list, so an adapter cannot answer for an action it does not declare.
    """
    for integration in all_integrations():
        found = integration.action(action_id)
        if found is not None:
            return integration, found
    return None


def describe() -> list[dict]:
    return [i.to_dict() for i in all_integrations(refresh=True)]


def may_send_to_remote_model(integration_id: str, *, allowed: set[str] | None = None
                             ) -> tuple[bool, str]:
    """Whether this integration's content may go to a remote model.

    Three conditions, and all of them are the user's rather than ours: a remote
    model is actually being used, the data is needed for the task, and the user
    has allowed it for THIS integration. Only the third is knowable here, so
    only the third is decided here — the caller answers the other two by virtue
    of asking.

    Private is the default for anything that is somebody's correspondence,
    private repository, or workspace. Classifying by source rather than by
    reading the content is deliberate: nothing can classify a document by
    reading it, and being wrong in the permissive direction is unrecoverable.
    """
    integration = get(integration_id)
    if integration is None:
        return False, f"{integration_id} is not an integration"
    if integration.sensitivity is Sensitivity.NORMAL:
        return True, ""
    if allowed and integration_id in allowed:
        return True, ""
    return False, (
        f"{integration.name} is marked private, so its content stays on this "
        f"machine. Allow it for this integration in Settings if you want a "
        f"remote model to see it.")


async def preview(action_id: str, arguments: dict) -> Change | None:
    found = find_action(action_id)
    if found is None:
        raise IntegrationError(f"{action_id} is not an action any integration "
                               f"offers.", remedy="Check the name.")
    integration, _ = found
    return await integration.preview(action_id, arguments)


async def perform(action_id: str, arguments: dict, *, origin: str = "agent") -> str:
    """Run one integration action, after asking whether it may."""
    found = find_action(action_id)
    if found is None:
        raise IntegrationError(
            f"{action_id} is not an action any integration offers.",
            remedy="Ask for a list of integrations to see what is available.")
    integration, action = found

    if not integration.available:
        raise IntegrationError(
            f"{integration.name} is not built into this version.",
            remedy=integration.needs)
    if not integration.connected():
        # Not gated on `needs_credential`: a folder integration has nothing
        # secret and can still be unconnected, and skipping the check for it
        # meant reporting a missing folder as connected.
        raise IntegrationError(
            f"{integration.name} is not connected.",
            remedy=("Choose a folder in Settings → Integrations."
                    if not integration.needs_credential
                    else "Connect it in Settings → Integrations."),
            needs_reconnect=True)

    # A write must be able to say what it would do, before it does it. An
    # adapter that cannot is refused rather than run: a missing preview is a
    # bug in the adapter, and letting it through would turn that bug into an
    # unreviewed side effect on somebody else's account.
    change = await integration.preview(action_id, arguments)
    if action.writes and change is None:
        raise IntegrationError(
            f"{action_id} changes something but could not say what.",
            remedy="This is a fault in the integration. It has been stopped "
                   "rather than run.")

    await _ask(Request(
        action=action_id,
        category=action.risk,
        summary=(f"{integration.name}: {change.summary}" if change
                 else f"{integration.name}: {action.summary}"),
        preview=_preview_text(change, arguments),
        origin=origin))

    return await integration.run(action_id, arguments)


def _preview_text(change: Change | None, arguments: dict) -> str:
    """What the approval shows.

    The change when there is one, because "send this, to these people" is a
    decision somebody can make and "send the email" is not. Otherwise the
    arguments, which for a read is the whole of what is being asked.
    """
    if change is not None:
        lines = [change.summary, f"→ {change.target}"]
        if change.detail:
            lines.append(change.detail)
        if not change.reversible:
            lines.append("This cannot be undone.")
        if change.body:
            lines.append("")
            lines.append(change.body[:1000])
        return "\n".join(lines)
    return "\n".join(f"{key}: {value}" for key, value in arguments.items()
                     if value not in ("", None))
