from __future__ import annotations

import asyncio
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
        context = await _browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            ),
        )
        _page = await context.new_page()
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
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001 - long-polling pages never go idle; carry on
        pass
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
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001
        pass
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
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:  # noqa: BLE001
            pass
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
