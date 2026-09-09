"""Provider adapters: one module per service, all speaking capabilities.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Each adapter's job is narrow — turn a capability into that provider's HTTP call
and turn its failures into something a person can act on. Everything else,
including authentication, permission and approval, happens above them and is
the same for all seven.

Two groups, and the difference is not about how finished they are:

* **GitHub, Slack, Notion** take a token the user issues to themselves. Nothing
  has to be registered with anybody, so they work as soon as somebody pastes
  one.
* **Google, Microsoft, Dropbox** require an OAuth client, which is issued to a
  named party under the provider's terms. Uncloud has none and will never
  fabricate one, so these report NOT_CONFIGURED until the user registers an
  application and enters its client ID.

That second state is a real, displayable answer with a real remedy — not an
excuse and not an unfinished feature.
"""

from .dropbox import Dropbox
from .github import GitHub
from .google import Google
from .microsoft import Microsoft
from .notion import Notion
from .rest import Rest
from .slack import Slack

__all__ = ["Dropbox", "GitHub", "Google", "Microsoft", "Notion", "Rest", "Slack"]
