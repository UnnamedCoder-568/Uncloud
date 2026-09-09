"""What an integration can do, named so that two providers can both do it.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

This is the vocabulary the orchestrator plans in. It asks for `email.send`, not
for Gmail — and the registry answers with whatever is connected and able. The
alternative is provider names spreading through planning code until adding
Fastmail means editing the orchestrator, which is exactly the shape this avoids.

**Two names from the brief were generalised, deliberately.** It listed
`github.issue.create` and `slack.message.send`. Both describe a category rather
than a product: GitLab and Gitea create issues, Teams and Discord send channel
messages, and naming the capability after the first provider to implement it
would put the second one in a branch. They are `code.issue.create` and
`chat.message.send` here. Where a concept genuinely is provider-shaped, the
capability stays specific rather than being forced into a false general.

**Granularity follows RISK, not the provider's API surface.** Reading mail and
sending it are separate capabilities because one is a read and the other is
irreversible and goes to other people. Listing a folder and reading a file are
one capability, because nothing turns on the difference.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..permission import Risk


class Capability(StrEnum):
    """Something an integration can do, independent of who does it."""

    # ------------------------------------------------------------- mail
    EMAIL_SEARCH = "email.search"
    EMAIL_READ = "email.read"
    #: Composing without sending. Separate because a draft is reversible and a
    #: sent message is not, and that difference is the whole approval story.
    EMAIL_DRAFT = "email.draft"
    EMAIL_SEND = "email.send"

    # --------------------------------------------------------- calendar
    CALENDAR_READ = "calendar.read"
    CALENDAR_CREATE = "calendar.create"

    # ---------------------------------------------------------- storage
    STORAGE_LIST = "storage.file.list"
    STORAGE_SEARCH = "storage.file.search"
    STORAGE_READ = "storage.file.read"
    STORAGE_WRITE = "storage.file.write"

    # -------------------------------------------------------- documents
    DOCUMENT_READ = "document.read"
    DOCUMENT_CREATE = "document.create"
    DOCUMENT_WRITE = "document.write"

    SPREADSHEET_READ = "spreadsheet.read"
    SPREADSHEET_WRITE = "spreadsheet.write"

    PRESENTATION_READ = "presentation.read"
    PRESENTATION_CREATE = "presentation.create"

    # ------------------------------------------------------------- chat
    CHAT_CHANNEL_LIST = "chat.channel.list"
    CHAT_MESSAGE_SEARCH = "chat.message.search"
    CHAT_MESSAGE_READ = "chat.message.read"
    CHAT_MESSAGE_SEND = "chat.message.send"

    # ------------------------------------------------------------- code
    CODE_REPO_LIST = "code.repo.list"
    CODE_FILE_READ = "code.file.read"
    CODE_FILE_WRITE = "code.file.write"
    CODE_SEARCH = "code.search"
    CODE_ISSUE_READ = "code.issue.read"
    CODE_ISSUE_CREATE = "code.issue.create"
    CODE_PR_READ = "code.pr.read"
    CODE_PR_CREATE = "code.pr.create"

    # ------------------------------------------------------------ notes
    NOTES_SEARCH = "notes.search"
    NOTES_PAGE_READ = "notes.page.read"
    NOTES_PAGE_CREATE = "notes.page.create"
    NOTES_PAGE_WRITE = "notes.page.write"
    NOTES_DATABASE_QUERY = "notes.database.query"


#: Which risk category each capability falls under, and therefore which policy
#: governs it. Central rather than per-adapter for the reason the tool layer
#: already learned: thirty adapters each classifying their own actions is
#: thirty chances to classify a send as a read.
#:
#: MESSAGE is used for anything that reaches another person. That is a stricter
#: default than WRITE and it is the right one — an email cannot be unsent, and
#: the recipient is not the user.
RISK: dict[Capability, Risk] = {
    Capability.EMAIL_SEARCH: Risk.READ,
    Capability.EMAIL_READ: Risk.READ,
    Capability.EMAIL_DRAFT: Risk.WRITE,
    Capability.EMAIL_SEND: Risk.MESSAGE,

    Capability.CALENDAR_READ: Risk.READ,
    #: Reaches other people the moment it has attendees, and the adapter cannot
    #: know in advance that it will not.
    Capability.CALENDAR_CREATE: Risk.MESSAGE,

    Capability.STORAGE_LIST: Risk.READ,
    Capability.STORAGE_SEARCH: Risk.READ,
    Capability.STORAGE_READ: Risk.READ,
    Capability.STORAGE_WRITE: Risk.WRITE,

    Capability.DOCUMENT_READ: Risk.READ,
    Capability.DOCUMENT_CREATE: Risk.WRITE,
    Capability.DOCUMENT_WRITE: Risk.WRITE,
    Capability.SPREADSHEET_READ: Risk.READ,
    Capability.SPREADSHEET_WRITE: Risk.WRITE,
    Capability.PRESENTATION_READ: Risk.READ,
    Capability.PRESENTATION_CREATE: Risk.WRITE,

    Capability.CHAT_CHANNEL_LIST: Risk.READ,
    Capability.CHAT_MESSAGE_SEARCH: Risk.READ,
    Capability.CHAT_MESSAGE_READ: Risk.READ,
    Capability.CHAT_MESSAGE_SEND: Risk.MESSAGE,

    Capability.CODE_REPO_LIST: Risk.READ,
    Capability.CODE_FILE_READ: Risk.READ,
    Capability.CODE_FILE_WRITE: Risk.WRITE,
    Capability.CODE_SEARCH: Risk.READ,
    Capability.CODE_ISSUE_READ: Risk.READ,
    #: Visible to everyone with access to the repository, and notifies people.
    Capability.CODE_ISSUE_CREATE: Risk.MESSAGE,
    Capability.CODE_PR_READ: Risk.READ,
    Capability.CODE_PR_CREATE: Risk.MESSAGE,

    Capability.NOTES_SEARCH: Risk.READ,
    Capability.NOTES_PAGE_READ: Risk.READ,
    Capability.NOTES_PAGE_CREATE: Risk.WRITE,
    Capability.NOTES_PAGE_WRITE: Risk.WRITE,
    Capability.NOTES_DATABASE_QUERY: Risk.READ,
}

#: Capabilities that change something outside Uncloud and therefore must be
#: able to describe what they would change before doing it. Derived from the
#: risk table rather than declared twice: anything that is not a READ writes.
WRITES: frozenset[Capability] = frozenset(
    capability for capability, risk in RISK.items() if risk is not Risk.READ)


@dataclass(frozen=True)
class Requirement:
    """What a plan needs, before anything has been chosen to do it.

    The orchestrator builds these. Nothing about a provider appears until the
    registry answers, which is what keeps provider knowledge out of planning.
    """

    capability: Capability
    #: Ask this provider specifically. Set when the user said which — "send it
    #: from my work account" — and empty when they did not care.
    provider: str = ""

    def to_dict(self) -> dict:
        return {"capability": self.capability.value, "provider": self.provider}


def risk_of(capability: Capability) -> Risk:
    """Which policy governs this capability.

    Raises for anything unclassified rather than defaulting. A capability
    nobody has categorised cannot be governed, and defaulting it to READ is how
    a send ends up running under a read's policy.
    """
    try:
        return RISK[capability]
    except KeyError as exc:
        raise KeyError(
            f"{capability} has no risk category. Add one to "
            f"integrations.capabilities.RISK — a capability nobody has "
            f"classified cannot be governed.") from exc


def writes(capability: Capability) -> bool:
    return capability in WRITES


def describe_capability(capability: Capability) -> str:
    """A capability in a person's terms, for a permission prompt."""
    return _SUMMARY.get(capability, capability.value)


_SUMMARY: dict[Capability, str] = {
    Capability.EMAIL_SEARCH: "Search your mail",
    Capability.EMAIL_READ: "Read a message",
    Capability.EMAIL_DRAFT: "Save a draft",
    Capability.EMAIL_SEND: "Send mail as you",
    Capability.CALENDAR_READ: "Read your calendar",
    Capability.CALENDAR_CREATE: "Create a calendar event",
    Capability.STORAGE_LIST: "List files",
    Capability.STORAGE_SEARCH: "Search files",
    Capability.STORAGE_READ: "Read a file",
    Capability.STORAGE_WRITE: "Write a file",
    Capability.DOCUMENT_READ: "Read a document",
    Capability.DOCUMENT_CREATE: "Create a document",
    Capability.DOCUMENT_WRITE: "Change a document",
    Capability.SPREADSHEET_READ: "Read a spreadsheet",
    Capability.SPREADSHEET_WRITE: "Change a spreadsheet",
    Capability.PRESENTATION_READ: "Read a presentation",
    Capability.PRESENTATION_CREATE: "Create a presentation",
    Capability.CHAT_CHANNEL_LIST: "List channels",
    Capability.CHAT_MESSAGE_SEARCH: "Search messages",
    Capability.CHAT_MESSAGE_READ: "Read messages",
    Capability.CHAT_MESSAGE_SEND: "Post a message",
    Capability.CODE_REPO_LIST: "List repositories",
    Capability.CODE_FILE_READ: "Read a file from a repository",
    Capability.CODE_FILE_WRITE: "Commit a file to a repository",
    Capability.CODE_SEARCH: "Search code",
    Capability.CODE_ISSUE_READ: "Read issues",
    Capability.CODE_ISSUE_CREATE: "Open an issue",
    Capability.CODE_PR_READ: "Read pull requests",
    Capability.CODE_PR_CREATE: "Open a pull request",
    Capability.NOTES_SEARCH: "Search your notes",
    Capability.NOTES_PAGE_READ: "Read a page",
    Capability.NOTES_PAGE_CREATE: "Create a page",
    Capability.NOTES_PAGE_WRITE: "Change a page",
    Capability.NOTES_DATABASE_QUERY: "Query a database",
}
