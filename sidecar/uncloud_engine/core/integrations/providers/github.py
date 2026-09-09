"""GitHub: repositories, files, issues, pull requests and search.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

The provider that works out of the box, and worth understanding why: GitHub
issues personal access tokens that a user creates for themselves, with scopes
they choose, revocable from their own settings page. No application
registration, no OAuth client, nothing Uncloud has to be issued by anybody.
Google and Microsoft cannot work that way, which is the whole difference
between IMPLEMENTED and REQUIRES EXTERNAL CONFIGURATION in the report.

Everything here calls api.github.com for real. The tests drive it against a
stub, because a test suite that needs somebody's repository is one that fails
on every other machine — but nothing is simulated in the adapter itself.
"""

from __future__ import annotations

import base64

from ...auth import AuthKind, Scope
from ..capabilities import Capability
from ..contract import Action, Change, Integration, IntegrationError, Sensitivity
from .rest import Rest

API = "https://api.github.com"


class GitHub(Integration):
    """One GitHub account, through a token the user issued themselves."""

    def __init__(self, *, client_factory=None) -> None:
        super().__init__(
            id="github",
            name="GitHub",
            summary="Repositories, files, issues and pull requests.",
            sensitivity=Sensitivity.PRIVATE,
            available=True,
            auth_kind=AuthKind.TOKEN,
            needs="A personal access token from github.com/settings/tokens. "
                  "Give it `repo` for private repositories, or `public_repo` "
                  "if you only need public ones.",
            scopes=(
                Scope(id="repo", summary="Read and write your repositories",
                      required=False),
                Scope(id="public_repo", summary="Read and write public "
                                                "repositories", required=False),
            ),
            actions=(
                Action(id="github.repos", capability=Capability.CODE_REPO_LIST,
                       summary="List repositories you can see",
                       parameters={"affiliation": "optional: owner, "
                                                  "collaborator, "
                                                  "organization_member"}),
                Action(id="github.read_file", capability=Capability.CODE_FILE_READ,
                       summary="Read a file from a repository",
                       parameters={"repo": "owner/name", "path": "path in the repo",
                                   "ref": "optional branch, tag or commit"}),
                Action(id="github.search", capability=Capability.CODE_SEARCH,
                       summary="Search code across repositories",
                       parameters={"query": "GitHub code search syntax",
                                   "repo": "optional owner/name to narrow to"}),
                Action(id="github.issues", capability=Capability.CODE_ISSUE_READ,
                       summary="List or read issues",
                       parameters={"repo": "owner/name",
                                   "number": "optional, for one issue",
                                   "state": "open, closed or all"}),
                Action(id="github.create_issue",
                       capability=Capability.CODE_ISSUE_CREATE,
                       summary="Open an issue",
                       parameters={"repo": "owner/name", "title": "",
                                   "body": "", "labels": "optional list"}),
                Action(id="github.pulls", capability=Capability.CODE_PR_READ,
                       summary="List or read pull requests",
                       parameters={"repo": "owner/name",
                                   "number": "optional, for one",
                                   "state": "open, closed or all"}),
                Action(id="github.create_pull",
                       capability=Capability.CODE_PR_CREATE,
                       summary="Open a pull request",
                       parameters={"repo": "owner/name", "title": "",
                                   "head": "branch with the changes",
                                   "base": "branch to merge into", "body": ""}),
                Action(id="github.write_file",
                       capability=Capability.CODE_FILE_WRITE,
                       summary="Commit a file to a branch",
                       parameters={"repo": "owner/name", "path": "",
                                   "content": "", "message": "commit message",
                                   "branch": "optional; the default branch "
                                             "otherwise"}),
            ))
        self._rest = Rest(
            "github", API, kind=AuthKind.TOKEN, client_factory=client_factory,
            # GitHub versions its API through this header; without it, response
            # shapes drift under you over months rather than failing loudly.
            extra_headers={"Accept": "application/vnd.github+json",
                           "X-GitHub-Api-Version": "2022-11-28"})

    # ------------------------------------------------------------- previews
    async def preview(self, action_id: str, arguments: dict) -> Change | None:
        repo = str(arguments.get("repo", ""))
        if action_id == "github.create_issue":
            return Change(
                summary=f"Open an issue on {repo}",
                target=repo,
                detail=str(arguments.get("title", "")),
                # An issue can be closed but not unsent: it notifies watchers
                # the moment it exists.
                reversible=False,
                body=str(arguments.get("body", ""))[:1000])
        if action_id == "github.create_pull":
            return Change(
                summary=f"Open a pull request on {repo}",
                target=f"{repo}: {arguments.get('head', '')} → "
                       f"{arguments.get('base', '')}",
                detail=str(arguments.get("title", "")),
                reversible=False,
                body=str(arguments.get("body", ""))[:1000])
        if action_id == "github.write_file":
            branch = arguments.get("branch") or "the default branch"
            return Change(
                summary=f"Commit {arguments.get('path', '')} to {repo}",
                target=f"{repo} ({branch})",
                detail=str(arguments.get("message", "")),
                reversible=False,
                body=str(arguments.get("content", ""))[:1000])
        return None

    # -------------------------------------------------------------- account
    def account(self) -> str:
        return ""

    def whoami(self) -> str:
        """The signed-in login, for the connection label.

        Called when connecting rather than on every render: a settings page
        that made an API call per row would be slow and would burn rate limit.
        """
        return str(self._rest.get("/user").get("login", ""))

    # --------------------------------------------------------------- actions
    async def run(self, action_id: str, arguments: dict) -> str:
        if action_id == "github.repos":
            return self._repos(arguments)
        if action_id == "github.read_file":
            return self._read_file(arguments)
        if action_id == "github.search":
            return self._search(arguments)
        if action_id == "github.issues":
            return self._issues(arguments)
        if action_id == "github.create_issue":
            return self._create_issue(arguments)
        if action_id == "github.pulls":
            return self._pulls(arguments)
        if action_id == "github.create_pull":
            return self._create_pull(arguments)
        if action_id == "github.write_file":
            return self._write_file(arguments)
        raise IntegrationError(f"{action_id} is not something GitHub can do.",
                               remedy="Ask for one of: "
                                      + ", ".join(a.id for a in self.actions))

    def _repo(self, arguments: dict) -> str:
        repo = str(arguments.get("repo", "")).strip().strip("/")
        if "/" not in repo:
            raise IntegrationError(
                f"{repo!r} is not a repository name.",
                remedy="Give it as owner/name, for example octocat/Hello-World.")
        return repo

    def _repos(self, arguments: dict) -> str:
        rows = self._rest.get("/user/repos", params={
            "per_page": 100, "sort": "updated",
            "affiliation": arguments.get("affiliation")
            or "owner,collaborator,organization_member"})
        if not rows:
            return "No repositories."
        return "\n".join(
            f"{r['full_name']}{' (private)' if r.get('private') else ''}"
            f" — {r.get('description') or 'no description'}"
            for r in rows)

    def _read_file(self, arguments: dict) -> str:
        repo = self._repo(arguments)
        path = str(arguments.get("path", "")).lstrip("/")
        params = {"ref": arguments["ref"]} if arguments.get("ref") else None
        body = self._rest.get(f"/repos/{repo}/contents/{path}", params=params)

        if isinstance(body, list):
            return "\n".join(f"{e['name']}{'/' if e['type'] == 'dir' else ''}"
                             for e in body)
        if body.get("encoding") != "base64":
            raise IntegrationError(
                f"{path} is not a text file GitHub will hand over directly.",
                remedy="Large or binary files have to be fetched from "
                       "download_url instead.")
        try:
            return base64.b64decode(body["content"]).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IntegrationError(
                f"{path} is not text.",
                remedy="Only text files can be read this way.") from exc

    def _search(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise IntegrationError("No search text was given.",
                                   remedy="Say what to look for.")
        if arguments.get("repo"):
            query = f"{query} repo:{arguments['repo']}"
        body = self._rest.get("/search/code", params={"q": query, "per_page": 20})
        items = body.get("items") or []
        if not items:
            return f"Nothing found for {query!r}."
        return "\n".join(
            f"{i['repository']['full_name']}: {i['path']}" for i in items)

    def _issues(self, arguments: dict) -> str:
        repo = self._repo(arguments)
        if arguments.get("number"):
            issue = self._rest.get(f"/repos/{repo}/issues/{arguments['number']}")
            return (f"#{issue['number']} {issue['title']} "
                    f"[{issue['state']}]\n\n{issue.get('body') or ''}")
        rows = self._rest.get(f"/repos/{repo}/issues", params={
            "state": arguments.get("state") or "open", "per_page": 50})
        # GitHub returns pull requests from the issues endpoint. Leaving them in
        # makes "list the issues" quietly wrong.
        issues = [r for r in rows if "pull_request" not in r]
        if not issues:
            return f"No {arguments.get('state') or 'open'} issues on {repo}."
        return "\n".join(f"#{i['number']} {i['title']} [{i['state']}]"
                         for i in issues)

    def _create_issue(self, arguments: dict) -> str:
        repo = self._repo(arguments)
        title = str(arguments.get("title", "")).strip()
        if not title:
            raise IntegrationError("An issue needs a title.",
                                   remedy="Give one.")
        payload = {"title": title, "body": str(arguments.get("body", ""))}
        if arguments.get("labels"):
            payload["labels"] = list(arguments["labels"])
        issue = self._rest.post(f"/repos/{repo}/issues", json_body=payload)
        return f"Opened {repo}#{issue['number']}: {issue['html_url']}"

    def _pulls(self, arguments: dict) -> str:
        repo = self._repo(arguments)
        if arguments.get("number"):
            pull = self._rest.get(f"/repos/{repo}/pulls/{arguments['number']}")
            return (f"#{pull['number']} {pull['title']} [{pull['state']}]\n"
                    f"{pull['head']['ref']} → {pull['base']['ref']}\n\n"
                    f"{pull.get('body') or ''}")
        rows = self._rest.get(f"/repos/{repo}/pulls", params={
            "state": arguments.get("state") or "open", "per_page": 50})
        if not rows:
            return f"No open pull requests on {repo}."
        return "\n".join(
            f"#{p['number']} {p['title']} "
            f"({p['head']['ref']} → {p['base']['ref']})" for p in rows)

    def _create_pull(self, arguments: dict) -> str:
        repo = self._repo(arguments)
        for required in ("title", "head", "base"):
            if not str(arguments.get(required, "")).strip():
                raise IntegrationError(
                    f"A pull request needs {required}.",
                    remedy="head is the branch with the changes; base is the "
                           "branch to merge into.")
        pull = self._rest.post(f"/repos/{repo}/pulls", json_body={
            "title": arguments["title"], "head": arguments["head"],
            "base": arguments["base"], "body": str(arguments.get("body", ""))})
        return f"Opened {repo}#{pull['number']}: {pull['html_url']}"

    def _write_file(self, arguments: dict) -> str:
        repo = self._repo(arguments)
        path = str(arguments.get("path", "")).lstrip("/")
        message = str(arguments.get("message", "")).strip()
        if not path or not message:
            raise IntegrationError(
                "A commit needs a path and a message.", remedy="Give both.")

        payload = {
            "message": message,
            "content": base64.b64encode(
                str(arguments.get("content", "")).encode("utf-8")).decode("ascii"),
        }
        if arguments.get("branch"):
            payload["branch"] = arguments["branch"]

        # Updating an existing file needs its blob SHA. Without it GitHub
        # refuses rather than clobbering, which is the right behaviour and the
        # reason this looks first.
        try:
            existing = self._rest.get(
                f"/repos/{repo}/contents/{path}",
                params={"ref": arguments["branch"]} if arguments.get("branch")
                else None)
            if isinstance(existing, dict) and existing.get("sha"):
                payload["sha"] = existing["sha"]
        except IntegrationError:
            # Not there yet, so this is a create rather than an update and
            # GitHub does not want a SHA.
            pass

        result = self._rest.put(f"/repos/{repo}/contents/{path}",
                                json_body=payload)
        commit = result.get("commit", {})
        return (f"Committed {path} to {repo}: "
                f"{commit.get('html_url') or commit.get('sha', '')}")
