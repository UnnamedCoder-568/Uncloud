"""The LAN surface as HTTP: one fence, five routes, and the application itself.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Both products are FastAPI applications with a bearer token, a websocket and a
built single-page frontend, so the wiring is the same wiring and lives here
once. What stays with each product is the three lines that say which
application, which directory and which existing dependency to widen.

Two things here are load-bearing and easy to get wrong if they were left to
each product to remember:

**The fence is pure ASGI, not an HTTP middleware.** Starlette's
`BaseHTTPMiddleware` never sees a websocket, and a websocket is a request like
any other — an attacker who can open one has everything. This runs on both
scopes.

**The pairing token is in a query string, so access logging is off.** `/pair?t=`
is a working credential and uvicorn's access log would write it to a file that
outlives the five minute expiry. The server is started with `access_log=False`
for this reason; it is not a performance choice.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.requests import HTTPConnection

from . import qr
from .pairing import RateLimited
from .service import Lan
from .sessions import Session, describe


def _header(scope: dict[str, Any], name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key == name:
            return value.decode("latin-1")
    return None


class Fence:
    """Refuses any request whose Host this server does not answer to.

    Wrapped around the whole application rather than applied per route: the
    routes that only read are exactly as interesting to an attacker as the ones
    that write, and a list of protected paths is a list somebody forgets to add
    to.
    """

    def __init__(self, app: Any, lan: Lan | None) -> None:
        self.app = app
        self.lan = lan

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if self.lan is None or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        reason = self.lan.guard.refuse(
            _header(scope, b"host"), _header(scope, b"origin"),
            _header(scope, b"referer"))
        if reason is None:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = reason.encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def session_of(request: HTTPConnection, lan: Lan | None) -> Session | None:
    """The paired device behind this request or websocket, if there is one."""
    if lan is None:
        return None
    return lan.sessions.verify(request.cookies.get(lan.cookie))


def _accept(response: Response, lan: Lan, cookie: str) -> Response:
    from .sessions import LIFETIME

    response.set_cookie(
        lan.cookie, cookie,
        max_age=LIFETIME,
        httponly=True,      # script on the page can never read it
        secure=True,        # and it never travels over plain HTTP
        samesite="lax",     # not attached to cross-site POSTs
        path="/",
    )
    return response


class TypedCode(BaseModel):
    code: str
    label: str = ""


class Label(BaseModel):
    label: str


def router(lan: Lan, authorised: Callable[[Request], bool]) -> APIRouter:
    """Pairing, sessions and device management. Mounted by each product.

    `authorised` is the product's own answer to "may this request act?" — its
    bearer token, or a paired session. Pairing itself is the only thing here
    reachable without it, because it is how a device gets it.
    """
    api = APIRouter()

    def refuse(request: Request) -> Response | None:
        if authorised(request):
            return None
        return JSONResponse({"detail": "Not paired."}, status_code=401)

    @api.get("/pair")
    async def pair(request: Request, t: str = "") -> Response:
        """Scanned from the QR. Spends the token and hands back a session."""
        if not t:
            return HTMLResponse(_page(lan.product))
        client = request.client.host if request.client else "unknown"
        try:
            ok = lan.pairing.redeem(t, kind="token", ip=client)
        except RateLimited as limited:
            return HTMLResponse(
                _page(lan.product, error="Too many attempts. Wait a moment."),
                status_code=429,
                headers={"Retry-After": str(int(limited.retry_after))})
        if not ok:
            return HTMLResponse(
                _page(lan.product, error="That link is expired or already used. "
                                         "Show a new code and try again."),
                status_code=403)

        agent = describe(request.headers.get("user-agent"))
        cookie, _ = lan.sessions.issue(label=agent, agent=agent)
        return _accept(RedirectResponse("/", status_code=303), lan, cookie)

    @api.get("/lan/authority.crt")
    async def authority() -> Response:
        """The local certificate authority, for the one-time trust step.

        Unauthenticated on purpose: it is a public certificate, the device that
        needs it is by definition not paired yet, and its fingerprint is shown
        on the computer so the person installing it can check it is this one.
        Served as a download with the CA media type, which is what makes iOS and
        Android offer to install it rather than display it.
        """
        return Response(
            lan.material.authority.read_bytes(),
            media_type="application/x-x509-ca-cert",
            headers={"Content-Disposition":
                     f'attachment; filename="{lan.slug}-local-authority.crt"'},
        )

    @api.post("/api/lan/pair")
    async def pair_with_code(request: Request, body: TypedCode) -> Response:
        """Typed instead of scanned. Same secret budget, different shape."""
        client = request.client.host if request.client else "unknown"
        try:
            ok = lan.pairing.redeem(body.code, kind="code", ip=client)
        except RateLimited as limited:
            return JSONResponse(
                {"detail": "Too many attempts."}, status_code=429,
                headers={"Retry-After": str(int(limited.retry_after))})
        if not ok:
            return JSONResponse(
                {"detail": "That code is wrong, expired, or already used."},
                status_code=403)

        agent = describe(request.headers.get("user-agent"))
        cookie, session = lan.sessions.issue(label=body.label or agent, agent=agent)
        return _accept(JSONResponse({"session": session.public()}), lan, cookie)

    @api.get("/api/lan/session")
    async def whoami(request: Request) -> Response:
        session = session_of(request, lan)
        if session is None:
            return JSONResponse({"paired": False}, status_code=401)
        return JSONResponse({"paired": True, "session": session.public()})

    @api.post("/api/lan/sign-out")
    async def sign_out(request: Request) -> Response:
        session = session_of(request, lan)
        if session is not None:
            lan.sessions.revoke(session.id)
        response = JSONResponse({"ok": True})
        response.delete_cookie(lan.cookie, path="/")
        return response

    @api.get("/api/lan/devices")
    async def devices(request: Request) -> Response:
        """Everything paired. Reachable from the desktop app and from a phone."""
        if (denied := refuse(request)) is not None:
            return denied
        here = session_of(request, lan)
        return JSONResponse({
            "devices": [{**s.public(), "current": here is not None and s.id == here.id}
                        for s in lan.sessions.all()],
            "addresses": [i.label for i in lan.interfaces],
            "authority": str(lan.material.authority),
            "fingerprint": lan.material.fingerprint,
        })

    @api.delete("/api/lan/devices/{device}")
    async def revoke(request: Request, device: str) -> Response:
        if (denied := refuse(request)) is not None:
            return denied
        if device == "all":
            return JSONResponse({"revoked": lan.sessions.revoke_all()})
        if not lan.sessions.revoke(device):
            return JSONResponse({"detail": "No such device."}, status_code=404)
        return JSONResponse({"revoked": 1})

    @api.post("/api/lan/devices/{device}/label")
    async def rename(request: Request, device: str, body: Label) -> Response:
        if (denied := refuse(request)) is not None:
            return denied
        if not lan.sessions.rename(device, body.label.strip()[:60] or "Paired device"):
            return JSONResponse({"detail": "No such device."}, status_code=404)
        return JSONResponse({"ok": True})

    @api.post("/api/lan/offer")
    async def new_offer(request: Request) -> Response:
        """A fresh code, without restarting. What the app's button calls."""
        if (denied := refuse(request)) is not None:
            return denied
        offer = lan.offer()
        return JSONResponse({
            "code": offer.code,
            "expires": offer.expires,
            # The modules, not an image: the interface draws them as SVG in
            # its own colours, and no QR library ships in either frontend.
            "reaches": [{"label": r.interface.label, "url": r.url, "qr": qr.matrix(r.url)}
                        for r in lan.reaches(offer)],
        })

    return api


def serve_frontend(app: Any, dist: Path) -> None:
    """Serve the built single-page app, with everything unknown falling to it.

    Registered last, because the catch-all would otherwise swallow the API. The
    frontend is the SAME build the desktop shell embeds — this is a second way
    in, not a second interface.
    """
    index = dist / "index.html"
    if not index.is_file():
        return

    for child in sorted(dist.iterdir()):
        if child.is_dir():
            app.mount(f"/{child.name}",
                      StaticFiles(directory=child), name=f"dist-{child.name}")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        # An unknown API path is a 404, not the application's front page. A
        # typo'd endpoint answering 200 with HTML is a day of debugging.
        if path.startswith(("api/", "ws/")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist / path).resolve()
        # resolve() then containment check: "../../etc/passwd" is a path the
        # router will happily hand over otherwise.
        if path and dist.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


def _page(product: str, *, error: str = "") -> str:
    """The typed-code page: the one screen that exists before there is a session.

    Deliberately standalone. It has to render before the application bundle is
    allowed to load, so it carries its own handful of colours rather than
    reaching for the design system, and it is the only page in either product
    that does.
    """
    problem = (f'<p class="bad">{html.escape(error)}</p>' if error else "")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Pair with {html.escape(product)}</title>
<style>
  :root {{ color-scheme: dark; --bg:#212121; --raised:#2a2a2a; --line:#343434;
           --text:#ededed; --dim:#a0a0a0; --bad:#f4a6a6; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100dvh; display:grid; place-items:center; padding:24px;
          background:var(--bg); color:var(--text);
          font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }}
  main {{ width:100%; max-width:23rem; }}
  h1 {{ font-size:1.3rem; margin:0 0 .4rem; letter-spacing:-0.02em; }}
  p {{ color:var(--dim); font-size:.85rem; margin:0 0 1.4rem; }}
  .bad {{ color:var(--bad); }}
  input {{ width:100%; padding:14px 16px; font-size:1.25rem; letter-spacing:.14em;
           text-align:center; text-transform:uppercase; border-radius:12px;
           border:1px solid var(--line); background:var(--raised); color:var(--text);
           font-family:ui-monospace, SFMono-Regular, Menlo, monospace; }}
  input:focus {{ outline:2px solid #5a5a5a; outline-offset:1px; }}
  button {{ width:100%; margin-top:12px; min-height:48px; border:0; border-radius:12px;
            background:var(--text); color:var(--bg); font-size:.95rem; font-weight:600;
            cursor:pointer; }}
  button:disabled {{ opacity:.5; cursor:default; }}
  .note {{ margin-top:1.5rem; font-size:.75rem; }}
</style></head><body><main>
  <h1>Pair with {html.escape(product)}</h1>
  <p>Type the code shown on the computer running it.</p>
  {problem}
  <form id="f" autocomplete="off">
    <input id="c" name="code" inputmode="latin" autocapitalize="characters"
           spellcheck="false" placeholder="XXXX-XXXX-XXXX" maxlength="14" required
           aria-label="Pairing code">
    <button id="b" type="submit">Pair this device</button>
  </form>
  <p class="note" id="n"></p>
  <p class="note">Seeing a certificate warning? That is this computer's own certificate,
    which no public authority vouches for. The connection is still encrypted.
    <a href="/lan/authority.crt" style="color:var(--text)">Install it on this device</a>
    once and the warning goes away.</p>
</main><script>
  var f=document.getElementById('f'),c=document.getElementById('c'),
      b=document.getElementById('b'),n=document.getElementById('n');
  c.addEventListener('input',function(){{
    var v=c.value.toUpperCase().replace(/[^0-9A-Z]/g,'').slice(0,12),o=[];
    for(var i=0;i<v.length;i+=4) o.push(v.slice(i,i+4));
    c.value=o.join('-');
  }});
  f.addEventListener('submit',function(e){{
    e.preventDefault(); b.disabled=true; n.textContent=''; n.className='note';
    fetch('/api/lan/pair',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      credentials:'same-origin',body:JSON.stringify({{code:c.value}})}})
      .then(function(r){{ if(r.ok){{ location.href='/'; return null; }} return r.json(); }})
      .then(function(d){{ if(d){{ b.disabled=false;
        n.className='note bad'; n.textContent=d.detail||'That did not work.'; }} }})
      .catch(function(){{ b.disabled=false; n.className='note bad';
        n.textContent='Could not reach the app.'; }});
  }});
  c.focus();
</script></body></html>"""

