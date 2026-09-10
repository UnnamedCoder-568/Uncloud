from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from pathlib import Path
from typing import Any

SCREENSHOT_DIR = Path.home() / ".uncloud" / "outputs"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# One browser for the whole engine, started on first use and reused across tool
# calls so the agent keeps its session, cookies and scroll position between steps.
_playwright: Any = None
_browser: Any = None
_page: Any = None
_lock = asyncio.Lock()

# Developer-tools surfaces. Bounded, because a chatty page can emit thousands of
# console lines and the agent only ever needs the tail.
_console: deque[str] = deque(maxlen=400)
_network: deque[str] = deque(maxlen=400)

# A pointer drawn into the page itself. The agent moves this, not the machine's
# real cursor, so it can work a page while you keep using your mouse — and the
# pointer shows up in screenshots, so its position is visible to a vision model.
_CURSOR_JS = """
window.__uncloudCursor = (x, y, clicking) => {
  let el = document.getElementById('__uncloud_cursor');
  if (!el) {
    el = document.createElement('div');
    el.id = '__uncloud_cursor';
    el.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;' +
      'width:22px;height:22px;transition:left .12s ease-out,top .12s ease-out;' +
      'filter:drop-shadow(0 1px 2px rgba(0,0,0,.55))';
    el.innerHTML =
      '<svg viewBox="0 0 22 22" width="22" height="22">' +
      '<path d="M3 2 L3 17 L7.2 13 L10 19.5 L12.6 18.4 L9.9 12.2 L15.5 12.2 Z" ' +
      'fill="#f59e0b" stroke="#0a0a0c" stroke-width="1.2" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(el);
  }
  el.style.left = x + 'px';
  el.style.top = y + 'px';
  el.style.transform = clicking ? 'scale(0.8)' : 'scale(1)';
};
"""


async def _ensure_page():
    global _playwright, _browser, _page
    async with _lock:
        if _page is not None and not _page.is_closed():
            return _page
        from playwright.async_api import async_playwright

        if _playwright is None:
            _playwright = await async_playwright().start()
        if _browser is None or not _browser.is_connected():
            _browser = await _playwright.chromium.launch(headless=True)
        _console.clear()
        _network.clear()
        context = await _browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            ),
        )
        await context.add_init_script(_CURSOR_JS)
        _page = await context.new_page()

        _page.on("console", lambda m: _console.append(f"[{m.type}] {m.text}"))
        _page.on("pageerror", lambda e: _console.append(f"[uncaught] {e}"))
        _page.on(
            "response",
            lambda r: _network.append(f"{r.status} {r.request.method} {r.url}"),
        )
        _page.on(
            "requestfailed",
            lambda r: _network.append(
                f"FAILED {r.method} {r.url} — {(r.failure or 'unknown')}"
            ),
        )
        return _page


async def shutdown() -> None:
    global _playwright, _browser, _page
    try:
        if _browser is not None and _browser.is_connected():
            await _browser.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        if _playwright is not None:
            await _playwright.stop()
    except Exception:  # noqa: BLE001
        pass
    _playwright = _browser = _page = None


async def _readable(page) -> str:
    """Page text with the chrome stripped — nav, scripts and styles removed."""
    text = await page.evaluate(
        """() => {
            const drop = ['script','style','noscript','svg','nav','header','footer','aside'];
            const clone = document.body.cloneNode(true);
            drop.forEach(sel => clone.querySelectorAll(sel).forEach(n => n.remove()));
            return clone.innerText;
        }"""
    )
    lines = [ln.strip() for ln in (text or "").splitlines()]
    return "\n".join(ln for ln in lines if ln)[:15000]


async def open_url(url: str) -> str:
    if not url:
        raise ValueError("browser_open requires a 'url' argument")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    page = await _ensure_page()
    await page.goto(url, timeout=45000, wait_until="domcontentloaded")
    with contextlib.suppress(Exception):  # long-polling pages never go idle; carry on
        await page.wait_for_load_state("networkidle", timeout=8000)
    return f"Opened {page.url}\nTitle: {await page.title()}\n\n{await _readable(page)}"


async def read_page() -> str:
    page = await _ensure_page()
    if not page.url or page.url == "about:blank":
        raise RuntimeError("No page open — call browser_open first.")
    return f"URL: {page.url}\nTitle: {await page.title()}\n\n{await _readable(page)}"


async def _resolve(page, target: str):
    """Accept a CSS selector or human-visible text, so the model can say either."""
    if any(c in target for c in "#.[>") or target.startswith(("input", "button", "a[")):
        loc = page.locator(target).first
        if await loc.count():
            return loc
    for factory in (
        lambda: page.get_by_role("button", name=target),
        lambda: page.get_by_role("link", name=target),
        lambda: page.get_by_placeholder(target),
        lambda: page.get_by_label(target),
        lambda: page.get_by_text(target),
    ):
        loc = factory().first
        try:
            if await loc.count():
                return loc
        except Exception:  # noqa: BLE001
            continue
    loc = page.locator(target).first
    if await loc.count():
        return loc
    raise RuntimeError(f"Could not find anything matching '{target}' on {page.url}")


async def click(target: str) -> str:
    if not target:
        raise ValueError("browser_click requires a 'target' argument")
    page = await _ensure_page()
    loc = await _resolve(page, target)
    before = page.url
    await loc.click(timeout=15000)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=8000)
    moved = f" (navigated to {page.url})" if page.url != before else ""
    return f"Clicked '{target}'{moved}\n\n{await _readable(page)}"


async def type_text(target: str, text: str, submit: bool = False) -> str:
    if not target:
        raise ValueError("browser_type requires a 'target' argument")
    page = await _ensure_page()
    loc = await _resolve(page, target)
    await loc.fill(text, timeout=15000)
    if submit:
        await loc.press("Enter")
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=10000)
    return f"Typed into '{target}'{' and submitted' if submit else ''}.\n\n{await _readable(page)}"


async def screenshot(full_page: bool = False) -> str:
    import uuid

    page = await _ensure_page()
    out = SCREENSHOT_DIR / f"screen-{uuid.uuid4().hex[:10]}.png"
    await page.screenshot(path=str(out), full_page=full_page)
    return f"Saved screenshot of {page.url} to {out}"


async def links() -> str:
    """Visible links, so the model can decide where to go without guessing."""
    page = await _ensure_page()
    found = await page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href]'))
            .filter(a => a.offsetParent !== null && a.innerText.trim())
            .slice(0, 80)
            .map(a => a.innerText.trim().replace(/\\s+/g,' ').slice(0,80) + ' -> ' + a.href)"""
    )
    return "\n".join(found) if found else "No visible links found."


# ----------------------------------------------------------------- devtools

async def console_log(level: str = "") -> str:
    """Console output since the page opened. `level` filters to error/warning/log."""
    await _ensure_page()
    lines = list(_console)
    if level:
        want = level.strip().lower()
        lines = [ln for ln in lines if ln.lower().startswith(f"[{want}")]
    if not lines:
        return "Console is empty." if not level else f"No console entries at level '{level}'."
    return "\n".join(lines[-120:])


async def network_log(contains: str = "") -> str:
    """Requests the page made, newest last. `contains` filters by URL substring."""
    await _ensure_page()
    lines = [ln for ln in _network if not contains or contains in ln]
    if not lines:
        return "No matching requests." if contains else "No requests recorded."
    return "\n".join(lines[-120:])


async def evaluate_js(code: str) -> str:
    """Run JavaScript in the page and return the result.

    Accepts either an expression ('document.title') or a function body; the
    former is far more common from a model, so it is tried first.
    """
    if not code or not code.strip():
        raise ValueError("evaluate_js needs some code to run")
    page = await _ensure_page()
    try:
        result = await page.evaluate(f"() => ({code})")
    except Exception:
        result = await page.evaluate(f"() => {{ {code} }}")
    if result is None:
        return "undefined"
    text = result if isinstance(result, str) else repr(result)
    return text[:8000]


# ------------------------------------------------------------ synthetic mouse

async def _draw_cursor(page, x: float, y: float, clicking: bool = False) -> None:
    with contextlib.suppress(Exception):  # the overlay is a nicety, never a blocker
        await page.evaluate(
            "([x, y, c]) => window.__uncloudCursor && window.__uncloudCursor(x, y, c)",
            [x, y, clicking],
        )


async def mouse_move(x: float, y: float) -> str:
    page = await _ensure_page()
    await page.mouse.move(x, y)
    await _draw_cursor(page, x, y)
    return f"Pointer at ({x:.0f}, {y:.0f})."


async def mouse_click(x: float, y: float, button: str = "left", clicks: int = 1) -> str:
    page = await _ensure_page()
    await page.mouse.move(x, y)
    await _draw_cursor(page, x, y, clicking=True)
    await page.mouse.click(x, y, button=button, click_count=max(1, int(clicks)))
    await _draw_cursor(page, x, y)
    await page.wait_for_timeout(400)
    return f"Clicked {button} at ({x:.0f}, {y:.0f}). Now at {page.url}"


async def mouse_drag(x1: float, y1: float, x2: float, y2: float) -> str:
    page = await _ensure_page()
    await page.mouse.move(x1, y1)
    await _draw_cursor(page, x1, y1, clicking=True)
    await page.mouse.down()
    # Interpolated, because a single jump is often ignored by drag handlers.
    for i in range(1, 13):
        ix = x1 + (x2 - x1) * i / 12
        iy = y1 + (y2 - y1) * i / 12
        await page.mouse.move(ix, iy)
        await _draw_cursor(page, ix, iy, clicking=True)
    await page.mouse.up()
    await _draw_cursor(page, x2, y2)
    return f"Dragged ({x1:.0f}, {y1:.0f}) to ({x2:.0f}, {y2:.0f})."


async def scroll_at(x: float, y: float, dy: float = 600) -> str:
    page = await _ensure_page()
    await page.mouse.move(x, y)
    await _draw_cursor(page, x, y)
    await page.mouse.wheel(0, dy)
    await page.wait_for_timeout(250)
    return f"Scrolled {dy:.0f}px at ({x:.0f}, {y:.0f})."
