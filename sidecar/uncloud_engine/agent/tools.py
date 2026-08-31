from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

from ..config import settings
from ..library import scan_library

WORKSPACE_DIR = Path.home() / ".uncloud" / "workspace"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

TOOL_SPECS = [
    {"id": "shell", "name": "Shell", "description": "Run a shell command.", "args": ["command"]},
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


async def run_tool(tool_id: str, args: dict[str, Any]) -> str:
    if tool_id == "shell":
        return await _shell(args.get("command", ""))
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
