from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

from ..config import settings
from ..core import Gate, Request, Risk
from ..library import scan_library

WORKSPACE_DIR = Path.home() / ".uncloud" / "workspace"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------- risk
#
# What each tool could do to a person, as a category. Kept as a table beside
# the specs rather than as a field inside them, for one reason: this table has
# to be COMPLETE, and a missing entry has to be a failure rather than a default.
# A tool with no risk recorded raises, and a test asserts every spec appears
# here — which means adding a tool without deciding what it can do is a broken
# build, not an ungoverned hole discovered later.
#
# Two calls worth explaining, because neither is obvious:
#
# `screen_capture` is DEVICE rather than READ. It photographs whatever the user
# happens to have open — mail, a password manager, someone else's message — and
# treating that as "reading a file" would file the most invasive tool here
# under the one category that does not ask.
#
# The browser splits. Opening and reading a page is NETWORK; clicking, typing,
# running script and moving the pointer are WRITE, because they change state on
# somebody's server. Neither is a local file operation, but "this pressed a
# button on a website" is a different question from "this fetched a page", and
# collapsing them would let a policy that permits research also permit acting.
#: Tools with no fixed category, because they resolve to something that has
#: one. `capability` becomes an integration action and is governed by THAT
#: action's risk — giving it a category here would mean picking one, and any
#: choice would be wrong for most of what it can resolve to.
#:
#: Dispatched before the risk lookup in `run_tool`, exactly as a dotted action
#: id is. Nothing here escapes the gate; it is asked one level down, with
#: better information.
RESOLVED_AT_CALL_TIME: frozenset[str] = frozenset({"capability"})

TOOL_RISK: dict[str, Risk] = {
    "shell": Risk.SHELL,
    "app_open": Risk.DEVICE,
    "screen_capture": Risk.DEVICE,

    "integrations": Risk.READ,

    "fs_read": Risk.READ,
    "fs_list": Risk.READ,
    "fs_glob": Risk.READ,
    "fs_grep": Risk.READ,
    "fs_write": Risk.WRITE,
    "fs_edit": Risk.WRITE,

    "http_fetch": Risk.NETWORK,
    "web_read": Risk.NETWORK,
    "web_search": Risk.NETWORK,
    "browser_open": Risk.NETWORK,
    "browser_read": Risk.NETWORK,
    "browser_links": Risk.NETWORK,
    "browser_console": Risk.NETWORK,
    "browser_network": Risk.NETWORK,
    "browser_screenshot": Risk.NETWORK,
    "browser_click": Risk.WRITE,
    "browser_type": Risk.WRITE,
    "browser_eval": Risk.WRITE,
    "browser_move": Risk.WRITE,
    "browser_click_at": Risk.WRITE,
    "browser_drag": Risk.WRITE,
    "browser_scroll_at": Risk.WRITE,

    "video_info": Risk.READ,
    "video_frames": Risk.WRITE,
    "see_image": Risk.READ,

    "skill_list": Risk.READ,
    "skill_read": Risk.READ,
    "skill_save": Risk.WRITE,

    "plan_set": Risk.READ,
    "plan_show": Risk.READ,
    "plan_update": Risk.READ,
    "note_save": Risk.READ,
    "note_recall": Risk.READ,

    "generate_image": Risk.GENERATE,
}


class Ungoverned(RuntimeError):
    """A tool ran, or tried to, with nothing deciding whether it may.

    Raised rather than defaulted in either direction. Defaulting to allow is
    the hole this whole layer exists to close; defaulting to deny would make a
    forgotten wire-up look like a broken tool. This looks like what it is.
    """


_gate: Gate | None = None


def install_gate(gate: Gate | None) -> None:
    """Give the tool layer its approval gate. Called once, at startup."""
    global _gate
    _gate = gate


def current_gate() -> Gate:
    if _gate is None:
        raise Ungoverned(
            "No approval gate is installed. Every tool call has to be decided "
            "by one; a tool layer without it is not a smaller feature, it is an "
            "ungoverned one.")
    return _gate


def _summarise(tool_id: str, args: dict[str, Any]) -> tuple[str, dict]:
    """The sentence a person reads, and whatever the interface can show.

    Specific on purpose. "The agent wants to run a command" is not a decision
    anybody can make; "run `rm -rf build`" is. The most dangerous tool gets the
    most literal summary.
    """
    def first(*names: str) -> str:
        for name in names:
            value = args.get(name)
            if value not in (None, ""):
                return str(value)
        return ""

    if tool_id == "shell":
        command = first("command")
        return f"Run this command: {command}", {"command": command}
    if tool_id in ("fs_write", "fs_edit"):
        path = first("path")
        body = str(args.get("content") or args.get("new") or "")
        return (f"{'Write' if tool_id == 'fs_write' else 'Edit'} {path}",
                {"path": path, "bytes": len(body), "preview": body[:600]})
    if tool_id == "app_open":
        target = first("target", "app")
        return f"Open {target} on this Mac", {"target": target}
    if tool_id == "screen_capture":
        return ("Take a screenshot of the whole screen, including anything "
                "else that is open", {})
    if tool_id in ("browser_type",):
        return (f"Type into {first('target')} on the current page",
                {"target": first("target"), "text": first("text")[:200]})
    if tool_id in ("browser_click", "browser_click_at"):
        return f"Click {first('target') or 'in the page'}", dict(args)
    if tool_id == "browser_eval":
        return "Run JavaScript in the current page", {"code": first("code")[:400]}
    if tool_id == "generate_image":
        return f"Generate an image: {first('prompt')[:160]}", {}
    if tool_id in ("web_search", "web_read", "http_fetch", "browser_open"):
        return f"Go online: {first('query', 'url')}", {"target": first("query", "url")}
    if tool_id == "skill_save":
        return f"Save a skill called {first('name')}", {"name": first("name")}
    if tool_id == "video_frames":
        return f"Extract frames from {first('path')}", {"path": first("path")}
    return f"{tool_id} {first('path', 'target', 'query', 'url', 'name')}".strip(), {}

TOOL_SPECS = [
    {"id": "shell", "name": "Shell", "description": "Run a shell command.", "args": ["command"]},
    {
        "id": "capability", "name": "Use a Capability",
        "description": "Do something through whichever connected integration "
                       "can. Give a capability such as email.send, "
                       "spreadsheet.read or code.issue.create, and the "
                       "arguments that capability takes. Name a provider only "
                       "if the user asked for a specific one.",
        "args": ["capability", "arguments", "provider"],
    },
    {"id": "integrations", "name": "Integrations",
     "description": "List what this computer is connected to — document folders, "
                    "accounts — and which actions each one offers. Use the action "
                    "ids it returns to actually do something.",
     "args": []},
    {"id": "fs_read", "name": "Read File", "description": "Read a text file.", "args": ["path"]},
    {"id": "fs_write", "name": "Write File", "description": "Write a text file.", "args": ["path", "content"]},
    {"id": "fs_list", "name": "List Directory", "description": "List a directory's contents.", "args": ["path"]},
    {"id": "http_fetch", "name": "Fetch URL", "description": "GET a URL and return the raw body. Prefer web_read for web pages.", "args": ["url"]},
    {
        "id": "web_read", "name": "Read Web Page",
        "description": "Fetch a web page and return its main content as clean readable text, without navigation or markup.",
        "args": ["url"],
    },
    {
        "id": "web_search", "name": "Web Search",
        "description": "Search the web and return the top results with titles, URLs and snippets.",
        "args": ["query"],
    },
    {
        "id": "video_info", "name": "Video Info",
        "description": "Duration, resolution and frame rate of a video file. Check this before pulling frames so you know where to look.",
        "args": ["path"],
    },
    {
        "id": "video_frames", "name": "Extract Video Frames",
        "description": "Pull still frames from a video and save them as images, then use see_image to look at them. This is how to watch a video: sample frames across it, or densely around one moment. 'start' and 'duration' are seconds; 'count' is how many frames to take.",
        "args": ["path", "start", "duration", "count"],
    },
    {
        "id": "skill_list", "name": "List Skills",
        "description": "List the skills available — saved procedures for tasks this user does often. Check this first when a goal sounds like something that might already have a written method.",
        "args": [],
    },
    {
        "id": "skill_read", "name": "Read Skill",
        "description": "Read a skill's full instructions by name, then follow them. Skills are guidance, not commands — carry them out with the normal tools.",
        "args": ["name"],
    },
    {
        "id": "skill_save", "name": "Save Skill",
        "description": "Write down a procedure as a reusable skill, when the user asks you to remember how something is done. Save instructions a person could follow, never code to run. 'tools' optionally lists the tool ids it expects to use, so it can be offered only where they are available.",
        "args": ["name", "description", "instructions", "tools (optional)"],
    },
    {
        "id": "browser_console", "name": "Read Browser Console",
        "description": "Read the browser console: JavaScript errors, warnings and logs from the current page. Use to debug a page that misbehaves. 'level' optionally filters to error, warning or log.",
        "args": ["level"],
    },
    {
        "id": "browser_network", "name": "Read Network Requests",
        "description": "List the network requests the page made, with status codes and failures. 'contains' optionally filters by URL substring.",
        "args": ["contains"],
    },
    {
        "id": "browser_eval", "name": "Run JavaScript",
        "description": "Run JavaScript in the current page and return the result, e.g. 'document.title' or 'document.querySelectorAll(\'a\').length'. Use for things the page does not show as text.",
        "args": ["code"],
    },
    {
        "id": "browser_move", "name": "Move Pointer",
        "description": "Move the browser's pointer to pixel coordinates. This is the agent's own pointer inside the page, not the machine's mouse, so it never fights the user for control. Pair with screenshot_page and see_image to work visually.",
        "args": ["x", "y"],
    },
    {
        "id": "browser_click_at", "name": "Click At Coordinates",
        "description": "Click at pixel coordinates in the page. Use when an element has no usable text or selector — read a screenshot first to find the position. Prefer browser_click when the target has a visible label.",
        "args": ["x", "y", "button", "clicks"],
    },
    {
        "id": "browser_drag", "name": "Drag Pointer",
        "description": "Press at one point, drag to another and release. For sliders, canvases and drag-and-drop.",
        "args": ["x1", "y1", "x2", "y2"],
    },
    {
        "id": "browser_scroll_at", "name": "Scroll At",
        "description": "Scroll the page by a pixel amount at a position. Positive dy scrolls down. Use for panes that scroll independently.",
        "args": ["x", "y", "dy"],
    },
    {
        "id": "fs_edit", "name": "Edit File",
        "description": "Replace an exact string in a file. Use to change part of a file without rewriting all of it.",
        "args": ["path", "old", "new"],
    },
    {
        "id": "fs_glob", "name": "Find Files",
        "description": "Find files matching a glob pattern, e.g. '**/*.tsx'.",
        "args": ["pattern", "path (optional)"],
    },
    {
        "id": "fs_grep", "name": "Search In Files",
        "description": "Search file contents for a regular expression and return matching lines with their file and line number.",
        "args": ["pattern", "path (optional)", "glob (optional)"],
    },
    {
        "id": "app_open", "name": "Open On This Mac",
        "description": (
            "Open a URL or a file in the user's own default browser or app, or launch "
            "an application by name. Use this when asked to open something on their "
            "machine — Safari, Finder, a document. Different from browser_open, which "
            "drives a separate automated browser the user cannot see."
        ),
        "args": ["target", "app"],
    },
    {
        "id": "browser_open", "name": "Open In Browser",
        "description": "Open a URL in a real browser session and return the page's visible text. Use instead of web_read when the page needs JavaScript, or when you intend to click or type next.",
        "args": ["url"],
    },
    {
        "id": "browser_read", "name": "Read Current Page",
        "description": "Return the visible text of the page currently open in the browser.",
        "args": [],
    },
    {
        "id": "browser_links", "name": "List Page Links",
        "description": "List the visible links on the current page with their URLs, to choose where to go next.",
        "args": [],
    },
    {
        "id": "browser_click", "name": "Click In Browser",
        "description": "Click something on the current page. 'target' can be visible text (e.g. 'Sign in') or a CSS selector.",
        "args": ["target"],
    },
    {
        "id": "browser_type", "name": "Type In Browser",
        "description": "Type into a field on the current page. 'target' can be the field's label, placeholder or a CSS selector. Set submit to true to press Enter afterwards.",
        "args": ["target", "text", "submit (optional)"],
    },
    {
        "id": "browser_screenshot", "name": "Screenshot Page",
        "description": "Save a PNG screenshot of the current page and return its path.",
        "args": ["full_page (optional)"],
    },
    {
        "id": "plan_set", "name": "Write Plan",
        "description": "Write down the plan before starting work: the overall goal and an ordered list of steps. Do this first on any task with more than two steps.",
        "args": ["goal", "steps (list of strings)"],
    },
    {
        "id": "plan_show", "name": "Check Plan",
        "description": "Re-read the saved plan and see which steps are done, in progress, or still outstanding. Use this whenever you lose track of where you are.",
        "args": [],
    },
    {
        "id": "plan_update", "name": "Update Plan",
        "description": "Mark a step's status: todo, doing, done or blocked. Add a note explaining what happened. Do this after finishing each step.",
        "args": ["n", "status", "note (optional)"],
    },
    {
        "id": "note_save", "name": "Remember Fact",
        "description": "Save a fact worth not re-deriving later — a file path, an ID, a finding. Give it a short key.",
        "args": ["key", "value"],
    },
    {
        "id": "note_recall", "name": "Recall Facts",
        "description": "Read back saved facts. Omit the key to list everything remembered.",
        "args": ["key (optional)"],
    },
    {
        "id": "see_image", "name": "Look At Image",
        "description": "Look at an image file and answer a question about it. Works on screenshots, photos and generated images. Requires a vision-capable model to be loaded.",
        "args": ["path", "question (optional)"],
    },
    {
        "id": "screen_capture", "name": "Capture Screen",
        "description": "Take a screenshot of the whole screen and return its path. Pair with see_image to look at it.",
        "args": [],
    },
    {
        "id": "generate_image", "name": "Generate Image",
        "description": (
            "Invoke a locally installed image diffusion model to generate a picture. "
            "'model' is optional — a name or catalog id (e.g. 'krea', 'pony'); omit to use "
            "whichever image model is installed. Saves a PNG and returns its path."
        ),
        "args": ["prompt", "model (optional)", "negative_prompt (optional)", "steps (optional)",
                  "guidance (optional)", "width (optional)", "height (optional)", "seed (optional)"],
    },
]


def _resolve_image_model(name: str | None):
    models = [m for m in scan_library(settings.models_dir) if m.category == "image" and m.ready]
    if not models:
        raise RuntimeError("No image model is installed. Download one from the Models tab first.")
    if not name:
        return models[0]
    needle = name.strip().lower()
    for m in models:
        if needle == m.id.lower() or needle == (m.catalog_id or "").lower() or needle in m.name.lower():
            return m
    raise RuntimeError(f"No installed image model matches '{name}'. Installed: {', '.join(m.name for m in models)}")


def _resolve_path(raw: str) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = WORKSPACE_DIR / p
    p = p.resolve()
    if not settings.agent_device_access:
        if WORKSPACE_DIR.resolve() not in p.parents and p != WORKSPACE_DIR.resolve():
            raise PermissionError(
                f"'{raw}' is outside the agent workspace. Enable full device access in "
                "Settings to let Agent Mode touch the rest of the filesystem."
            )
    return p


async def run_tool(tool_id: str, args: dict[str, Any], *, origin: str = "") -> str:
    """Run one tool, after asking whether it may.

    The gate is here rather than in each tool for the reason the whole layer
    exists: thirty-eight tools each remembering to check is thirty-eight
    chances to forget, and the one that forgets is the one that matters. A tool
    added tomorrow is governed by having an entry in TOOL_RISK, which it cannot
    run without.
    """
    # Integration actions are namespaced (`documents.read`) and carry their own
    # risk category, declared by the integration rather than listed here. They
    # go to `registry.perform`, which asks the gate exactly as this function
    # does — one level down, and with a better question, because for a write it
    # can show what would change rather than only what was called.
    if "." in tool_id:
        from ..core.integrations import find_action, perform

        if find_action(tool_id) is not None:
            return await perform(tool_id, args, origin=origin or "agent")

    # Planning in capabilities rather than in provider names. The model asks to
    # `email.send` and the registry decides whether that is Gmail or Outlook,
    # which is what stops "if gmail" appearing in planning code the first time
    # somebody adds a second mail provider.
    if tool_id == "capability":
        from ..core.integrations import Capability, perform_capability

        wanted = str(args.get("capability", "")).strip()
        try:
            capability = Capability(wanted)
        except ValueError:
            known = ", ".join(sorted(c.value for c in Capability))
            raise ValueError(
                f"{wanted!r} is not a capability. Known: {known}") from None
        return await perform_capability(
            capability, args.get("arguments") or {},
            provider=str(args.get("provider", "")),
            origin=origin or "agent")

    risk = TOOL_RISK.get(tool_id)
    if risk is None:
        raise ValueError(
            f"Unknown tool: {tool_id}" if tool_id not in {t["id"] for t in TOOL_SPECS}
            else f"{tool_id} has no risk category. Add one to TOOL_RISK — a tool "
                 f"nobody has classified cannot be governed.")

    summary, preview = _summarise(tool_id, args)
    from .approval import decide

    await decide(Request(action=tool_id, category=risk, summary=summary,
                         preview=preview, origin=origin or "agent"))

    if tool_id == "shell":
        return await _shell(args.get("command", ""))
    if tool_id == "integrations":
        return _integrations()
    if tool_id == "fs_read":
        return _fs_read(args.get("path", ""))
    if tool_id == "fs_write":
        return _fs_write(args.get("path", ""), args.get("content", ""))
    if tool_id == "fs_list":
        return _fs_list(args.get("path", "."))
    if tool_id == "http_fetch":
        return await _http_fetch(args.get("url", ""))
    if tool_id == "web_read":
        return await _web_read(args.get("url", ""))
    if tool_id == "web_search":
        return await _web_search(args.get("query", ""))
    if tool_id == "fs_edit":
        return _fs_edit(args.get("path", ""), args.get("old", ""), args.get("new", ""))
    if tool_id == "fs_glob":
        return _fs_glob(args.get("pattern", "*"), args.get("path", "."))
    if tool_id == "fs_grep":
        return _fs_grep(args.get("pattern", ""), args.get("path", "."), args.get("glob", "*"))
    if tool_id == "video_info":
        return await _video_info(args.get("path", ""))
    if tool_id == "video_frames":
        return await _video_frames(args)
    if tool_id.startswith("skill_"):
        from . import skills

        if tool_id == "skill_list":
            return skills.skill_list()
        if tool_id == "skill_read":
            return skills.skill_read(str(args.get("name", "")))
        if tool_id == "skill_save":
            return skills.skill_save(
                str(args.get("name", "")),
                str(args.get("description", "")),
                str(args.get("instructions", "")),
                tools=str(args.get("tools", "")),
                capabilities=str(args.get("capabilities", "")),
                memory_gb=str(args.get("memory_gb", "")),
            )
    if tool_id == "app_open":
        return _app_open(args.get("target", ""), args.get("app", ""))
    if tool_id.startswith("browser_"):
        from . import browser

        if tool_id == "browser_open":
            return await browser.open_url(args.get("url", ""))
        if tool_id == "browser_read":
            return await browser.read_page()
        if tool_id == "browser_links":
            return await browser.links()
        if tool_id == "browser_console":
            return await browser.console_log(str(args.get("level", "")))
        if tool_id == "browser_network":
            return await browser.network_log(str(args.get("contains", "")))
        if tool_id == "browser_eval":
            return await browser.evaluate_js(str(args.get("code", "")))
        if tool_id == "browser_move":
            return await browser.mouse_move(_num_arg(args, "x"), _num_arg(args, "y"))
        if tool_id == "browser_click_at":
            return await browser.mouse_click(
                _num_arg(args, "x"), _num_arg(args, "y"),
                str(args.get("button", "left") or "left"),
                int(_num_arg(args, "clicks", 1)),
            )
        if tool_id == "browser_drag":
            return await browser.mouse_drag(
                _num_arg(args, "x1"), _num_arg(args, "y1"),
                _num_arg(args, "x2"), _num_arg(args, "y2"),
            )
        if tool_id == "browser_scroll_at":
            return await browser.scroll_at(
                _num_arg(args, "x"), _num_arg(args, "y"), _num_arg(args, "dy", 600),
            )
        if tool_id == "browser_click":
            return await browser.click(args.get("target", ""))
        if tool_id == "browser_type":
            return await browser.type_text(
                args.get("target", ""), args.get("text", ""), _truthy(args.get("submit")),
            )
        if tool_id == "browser_screenshot":
            return await browser.screenshot(_truthy(args.get("full_page")))
    if tool_id.startswith(("plan_", "note_")):
        from . import memory

        if tool_id == "plan_set":
            steps = args.get("steps", [])
            if isinstance(steps, str):  # small models often send a newline/comma list
                steps = [s.strip("-• ").strip() for s in re.split(r"[\n;]|(?<=[a-z])\s*,\s*(?=[A-Z])", steps) if s.strip()]
            return memory.plan_set(args.get("goal", ""), list(steps))
        if tool_id == "plan_show":
            return memory.plan_show()
        if tool_id == "plan_update":
            return memory.plan_update(
                int(args.get("n", 0)), str(args.get("status", "")).strip().lower(), args.get("note", ""),
            )
        if tool_id == "note_save":
            return memory.note_save(args.get("key", ""), args.get("value", ""))
        if tool_id == "note_recall":
            return memory.note_recall(args.get("key", ""))
    if tool_id == "see_image":
        return await _see_image(args.get("path", ""), args.get("question", ""))
    if tool_id == "screen_capture":
        return await _screen_capture()
    if tool_id == "generate_image":
        return await _generate_image(args)
    raise ValueError(f"Unknown tool: {tool_id}")


async def _screen_capture() -> str:
    import uuid

    out = Path.home() / ".uncloud" / "outputs" / f"screen-{uuid.uuid4().hex[:10]}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "screencapture", "-x", str(out),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(
            "Screen capture failed — grant Screen Recording permission in "
            f"System Settings > Privacy & Security. {stdout.decode(errors='ignore')[:200]}"
        )
    return str(out)


async def _see_image(path: str, question: str) -> str:
    """Send an image to the loaded model. Only works when that model has an
    image encoder — a text-only model has no way to receive the pixels."""
    import base64

    from ..engines import engine_manager

    if not engine_manager.active:
        raise RuntimeError("No model is loaded. Start one from the Chat tab first.")
    if not engine_manager.supports_vision:
        raise RuntimeError(
            "The loaded model is text-only and cannot see images. Load a vision-capable "
            "model (e.g. Gemma 4 26B-A4B or Gemma 4 12B) from the Models tab."
        )

    p = _resolve_path(path)
    if not p.exists():
        raise FileNotFoundError(f"No such image: {p}")

    suffix = p.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    b64 = base64.b64encode(p.read_bytes()).decode()

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{engine_manager.active.base_url}/v1/chat/completions",
            json={
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question or "Describe this image in detail."},
                        {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
                    ],
                }],
                "max_tokens": 1024,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _num_arg(args: dict, key: str, default: float = 0.0) -> float:
    """Models hand back coordinates as ints, floats or strings; take any of them."""
    raw = args.get(key, default)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return float(default)


def _truthy(value: Any) -> bool:
    """Small models emit booleans as strings often enough to be worth handling."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1")


async def _shell(command: str) -> str:
    if not command:
        raise ValueError("shell tool requires a 'command' argument")
    cwd = str(Path.home()) if settings.agent_device_access else str(WORKSPACE_DIR)
    proc = await asyncio.create_subprocess_shell(
        command, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("Command timed out after 120s")
    out = stdout.decode(errors="ignore")[-8000:]
    if proc.returncode != 0:
        raise RuntimeError(f"Exit {proc.returncode}: {out}")
    return out or "(no output)"


def _fs_read(path: str) -> str:
    p = _resolve_path(path)
    return p.read_text(errors="ignore")[:20000]


def _fs_write(path: str, content: str) -> str:
    p = _resolve_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content)} bytes to {p}"


def _fs_list(path: str) -> str:
    p = _resolve_path(path)
    if not p.is_dir():
        raise NotADirectoryError(str(p))
    return "\n".join(sorted(child.name + ("/" if child.is_dir() else "") for child in p.iterdir()))


async def _http_fetch(url: str) -> str:
    if not url:
        raise ValueError("http_fetch tool requires a 'url' argument")
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text[:20000]


async def _web_read(url: str) -> str:
    """Fetch a page and hand back readable prose. Raw HTML burns a local model's
    context on markup it can't use."""
    if not url:
        raise ValueError("web_read tool requires a 'url' argument")
    import trafilatura

    async with httpx.AsyncClient(follow_redirects=True, timeout=25) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Uncloud/0.1)"})
        resp.raise_for_status()
        html = resp.text

    text = trafilatura.extract(html, include_links=True, include_tables=True, favor_recall=True)
    if not text:
        # Not an article (an app shell, a listing page). Fall back to stripped text.
        text = trafilatura.html2txt(html) or ""
    if not text.strip():
        raise RuntimeError(f"Could not extract readable content from {url}")
    return text[:20000]


async def _web_search(query: str) -> str:
    if not query:
        raise ValueError("web_search tool requires a 'query' argument")
    from html import unescape

    # DuckDuckGo's no-JS endpoint: no API key, no account.
    async with httpx.AsyncClient(follow_redirects=True, timeout=25) as client:
        resp = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; Uncloud/0.1)"},
        )
        resp.raise_for_status()
        html = resp.text

    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
        r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.DOTALL,
    )
    tag = re.compile(r"<[^>]+>")

    results = []
    for m in pattern.finditer(html):
        title = unescape(tag.sub("", m.group("title"))).strip()
        snippet = unescape(tag.sub("", m.group("snippet"))).strip()
        link = unescape(m.group("url"))
        # DDG wraps hits in a redirect; recover the real target.
        real = re.search(r"uddg=([^&]+)", link)
        if real:
            link = unquote(real.group(1))
        if title and link:
            results.append(f"{len(results) + 1}. {title}\n   {link}\n   {snippet}")
        if len(results) >= 8:
            break

    if not results:
        return "No results found."
    return "\n\n".join(results)


def _fs_edit(path: str, old: str, new: str) -> str:
    if not old:
        raise ValueError("fs_edit requires a non-empty 'old' string")
    p = _resolve_path(path)
    content = p.read_text(errors="ignore")
    count = content.count(old)
    if count == 0:
        raise ValueError(f"'old' string not found in {p}")
    if count > 1:
        raise ValueError(
            f"'old' string appears {count} times in {p}; include more surrounding "
            "context so it matches exactly once."
        )
    p.write_text(content.replace(old, new))
    return f"Edited {p}"


def _fs_glob(pattern: str, path: str) -> str:
    root = _resolve_path(path)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    hits = [str(m) for m in sorted(root.glob(pattern)) if m.is_file()][:200]
    return "\n".join(hits) if hits else f"No files matching '{pattern}' under {root}"


def _fs_grep(pattern: str, path: str, glob: str) -> str:
    if not pattern:
        raise ValueError("fs_grep requires a 'pattern' argument")
    root = _resolve_path(path)
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression: {exc}")

    targets = [root] if root.is_file() else sorted(root.rglob(glob))
    out: list[str] = []
    for f in targets:
        if not f.is_file():
            continue
        try:
            for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                if rx.search(line):
                    out.append(f"{f}:{i}: {line.strip()[:200]}")
                    if len(out) >= 200:
                        return "\n".join(out) + "\n… (truncated at 200 matches)"
        except OSError:
            continue
    return "\n".join(out) if out else f"No matches for '{pattern}'"


async def _generate_image(args: dict[str, Any]) -> str:
    from ..catalog import get_entry
    from ..image_engine import image_engine

    prompt = args.get("prompt", "")
    if not prompt:
        raise ValueError("generate_image tool requires a 'prompt' argument")
    model = _resolve_image_model(args.get("model"))
    entry = get_entry(model.catalog_id) if model.catalog_id else None

    def _num(key: str, cast):
        val = args.get(key)
        return cast(val) if val is not None and val != "" else None

    job = image_engine.start(
        model.path, model.engine, prompt,
        negative_prompt=args.get("negative_prompt", ""),
        steps=_num("steps", int), guidance=_num("guidance", float),
        width=_num("width", int) or 1024, height=_num("height", int) or 1024,
        seed=_num("seed", int),
        mflux_cli=entry.mflux_cli if entry else "mflux-generate",
    )
    for _ in range(1800):  # up to 15 min for a cold ~22GB model load + generation
        await asyncio.sleep(0.5)
        if job.status in ("done", "error"):
            break
    if job.status == "error":
        raise RuntimeError(job.error or "Image generation failed")
    if job.status != "done":
        raise RuntimeError("Image generation timed out")
    return f"Generated image with {model.name}, saved to: {job.output_path}"


# ---------------------------------------------------------------- tool sets

# Every tool description goes into the planner's prompt on every call, so the
# full set is a real cost, not just a capability. A 27B copes with 31 options;
# a small model on a laptop plans measurably worse with 31 than with 10. Groups
# let the surface match the model actually doing the planning.
def _app_open(target: str, app: str = "") -> str:
    """Open a URL, file or application the way the user's desktop would.

    Asked to "open Safari and go to YouTube", a model without this reaches for
    the shell and writes AppleScript from memory — and a small model does not
    reliably know an application's scripting dictionary. One observed attempt
    used `currentURL of window 1`, which Safari has no such property for.

    The platform launcher already does this correctly and needs no dictionary.
    """
    import subprocess
    import sys

    target = (target or "").strip()
    app = (app or "").strip()
    if not target and not app:
        return "Nothing to open: give a target (URL or path) or an app name."

    if sys.platform == "darwin":
        cmd = ["open"]
        if app:
            cmd += ["-a", app]
        if target:
            cmd.append(target)
    elif sys.platform.startswith("linux"):
        if not target:
            return f"Cannot launch an application by name on this platform: {app}"
        cmd = ["xdg-open", target]
    elif sys.platform == "win32":
        cmd = ["cmd", "/c", "start", "", target or app]
    else:
        return f"Opening things is not supported on {sys.platform}."

    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Could not open {target or app}: {exc}"
    if done.returncode != 0:
        return f"Could not open {target or app}: {done.stderr.strip() or done.returncode}"
    what = target or app
    where = f" in {app}" if app and target else ""
    return f"Opened {what}{where}."


TOOL_GROUPS: dict[str, dict] = {
    "files": {
        "label": "Files",
        "note": "Read, write, edit, list, glob and grep.",
        "ids": {"fs_read", "fs_write", "fs_list", "fs_edit", "fs_glob", "fs_grep"},
    },
    "shell": {
        "label": "Shell",
        "note": "Run commands, and open things in the user's own apps.",
        "ids": {"shell", "app_open"},
    },
    "web": {
        "label": "Web",
        "note": "Search and read pages as text.",
        "ids": {"web_search", "web_read", "http_fetch"},
    },
    "memory": {
        "label": "Plan and memory",
        "note": "Write a plan, track step status, remember facts across a run.",
        "ids": {"plan_set", "plan_show", "plan_update", "note_save", "note_recall"},
    },
    "browser": {
        "label": "Browser",
        "note": "Drive a real browser by visible text: open, click, type, screenshot.",
        "ids": {"browser_open", "browser_read", "browser_links",
                "browser_click", "browser_type", "browser_screenshot"},
    },
    "devtools": {
        "label": "Developer tools",
        "note": "Console, network requests and JavaScript evaluation.",
        "ids": {"browser_console", "browser_network", "browser_eval"},
    },
    "pointer": {
        "label": "Pointer control",
        "note": "Move, click, drag and scroll at pixel coordinates.",
        "ids": {"browser_move", "browser_click_at", "browser_drag", "browser_scroll_at"},
    },
    "video": {
        "label": "Video",
        "note": "Probe a video and pull frames out of it. Pair with Vision to watch one.",
        "ids": {"video_info", "video_frames"},
    },
    "vision": {
        "label": "Vision",
        "note": "Look at images and capture the screen. Needs a vision model.",
        "ids": {"see_image", "screen_capture"},
    },
    "skills": {
        "label": "Skills",
        "note": "Look up and save reusable procedures. Instructions only, never code.",
        "ids": {"skill_list", "skill_read", "skill_save"},
    },
    "media": {
        "label": "Image generation",
        "note": "Generate pictures with a local diffusion model.",
        "ids": {"generate_image"},
    },
}

_AUTO_FULL = list(TOOL_GROUPS)


def auto_groups(model_path: str | None) -> list[str]:
    """Every tool, for every model.

    This used to withhold tool groups below a size threshold — under 8 GB got
    four groups, under 20 GB got eight, and only above that did a model see
    everything. The reasoning was that a small model plans badly with a long
    tool list.

    It was the wrong call, and wrong in both directions. Size is not ability:
    it handed Vision to a 12 GB text-only model that cannot see, and withheld
    the browser from a sharp 7B one that could have driven it. It also froze
    the product against the future — every model released from now on is
    better at its size than the one that set the threshold, and a capability
    withheld by a number written today is a capability no new model can ever
    reach.

    So: if a model has the ability to use something, let it. A model that
    plans badly with a long tool list produces a bad plan, which is visible,
    recoverable, and the user's to judge. A capability silently unavailable is
    none of those things.

    The user can still narrow this by hand in Settings — that is a choice they
    make, not one made for them. `model_path` is kept in the signature because
    the caller has it and a future version may report what a model declares it
    can do; it is deliberately not consulted to guess.
    """
    return list(_AUTO_FULL)


def tools_for(groups: list[str] | None) -> list[dict]:
    """The specs a planner should see. None means every tool."""
    if not groups:
        return list(TOOL_SPECS)
    allowed: set[str] = set()
    for g in groups:
        spec = TOOL_GROUPS.get(g)
        if spec:
            allowed |= spec["ids"]
    return [t for t in TOOL_SPECS if t["id"] in allowed]


def group_summary() -> list[dict]:
    return [
        {"id": g, "label": v["label"], "note": v["note"], "count": len(v["ids"])}
        for g, v in TOOL_GROUPS.items()
    ]


async def _ffprobe(path: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=width,height,r_frame_rate,codec_type",
        "-of", "json", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError((err or b"").decode()[-500:] or "ffprobe failed")
    import json as _json

    return _json.loads(out or b"{}")


async def _video_info(path: str) -> str:
    p = _resolve_path(path)
    if not p.exists():
        raise FileNotFoundError(f"No such file: {p}")
    data = await _ffprobe(str(p))
    dur = float(data.get("format", {}).get("duration", 0) or 0)
    lines = [f"{p.name} — {dur:.1f}s"]
    for st in data.get("streams", []):
        if st.get("codec_type") == "video":
            rate = st.get("r_frame_rate", "0/1")
            try:
                num, den = rate.split("/"); fps = float(num) / float(den or 1)
            except (ValueError, ZeroDivisionError):
                fps = 0.0
            lines.append(f"video: {st.get('width')}x{st.get('height')} @ {fps:.0f} fps")
    return "\n".join(lines)


async def _video_frames(args: dict[str, Any]) -> str:
    """Sample frames to disk so a vision model can look at them.

    Extracting stills is the only way to read a video here — there is no model
    that consumes video directly, and a handful of well-chosen frames answers
    most questions about one anyway.
    """
    import uuid

    p = _resolve_path(str(args.get("path", "")))
    if not p.exists():
        raise FileNotFoundError(f"No such file: {p}")

    count = max(1, min(24, int(_num_arg(args, "count", 8))))
    start = max(0.0, _num_arg(args, "start", 0.0))
    data = await _ffprobe(str(p))
    total = float(data.get("format", {}).get("duration", 0) or 0)
    duration = _num_arg(args, "duration", 0.0) or max(0.1, total - start)

    out_dir = Path.home() / ".uncloud" / "outputs" / f"frames-{uuid.uuid4().hex[:8]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = count / duration if duration > 0 else 1.0

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(p),
        "-vf", f"fps={fps:.4f},scale=768:-1", "-frames:v", str(count),
        str(out_dir / "f%03d.png"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError((out or b"").decode()[-600:] or "ffmpeg failed")

    files = sorted(out_dir.glob("f*.png"))
    if not files:
        raise RuntimeError("No frames were produced — check the start time and duration.")
    lines = [f"{len(files)} frame(s) from {start:.1f}s over {duration:.1f}s:"]
    for i, f in enumerate(files):
        lines.append(f"  {start + i * duration / len(files):6.2f}s  {f}")
    lines.append("\nUse see_image on any of these to look at it.")
    return "\n".join(lines)


def _integrations() -> str:
    """What is connected, what it can do, and what is missing.

    Written capability-first, because that is how the model should plan: the
    list of capabilities is the vocabulary for the `capability` tool, and the
    provider names below it are context rather than instructions.

    Integrations that cannot work are listed with what they need rather than
    hidden. A model that knows Google Workspace exists but is not connected can
    say so; one that has never heard of it invents a reason instead.
    """
    from ..core.integrations import all_integrations, capability_map

    lines = []
    routable = capability_map()
    if routable:
        lines.append("Capabilities available right now — use the `capability` "
                     "tool with any of these:")
        for capability, providers in sorted(routable.items()):
            lines.append(f"    {capability}  (via {', '.join(providers)})")
        lines.append("")
    lines.append("Integrations:")
    for integration in all_integrations(refresh=True):
        connection = integration.connection()
        if connection.state.usable:
            where = f" ({connection.account})" if connection.account else ""
            lines.append(f"{integration.name}{where} — connected.")
            for action in integration.actions:
                arguments = ", ".join(f"{k}: {v}"
                                      for k, v in action.parameters.items())
                lines.append(f"    {action.id}({arguments})"
                             f"  [{action.capability.value}] — {action.summary}")
            continue

        # The state matters to the model, because the remedies differ and it
        # will otherwise tell somebody to sign in to a provider that has no
        # OAuth client registered yet.
        if connection.state.value == "not_configured":
            lines.append(f"{integration.name} — needs configuring before it can "
                         f"be connected. {integration.needs}")
        elif connection.state.value == "authentication_required":
            lines.append(f"{integration.name} — was connected; the sign-in has "
                         f"expired and needs doing again in Settings.")
        elif not integration.available:
            lines.append(f"{integration.name} — not available in this build. "
                         f"{integration.needs}")
        else:
            lines.append(f"{integration.name} — not connected. The user can "
                         + ("choose a folder for it in Settings."
                            if not integration.needs_credential
                            else "connect it in Settings."))
    return "\n".join(lines)
