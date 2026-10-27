"""The PocketDesk relay: an authenticated bridge the user runs on a VPS.

The relay lets a host behind NAT and a browser on another network reach each
other without Tailscale and without opening any port at home. The host dials
*out* and registers a room; the browser opens ``/r/<room>`` and the relay pipes
their control messages (pair / sources / offer / app-view) between them.

It is deliberately dumb: it forwards opaque JSON envelopes and never holds the
host's AES key, so it cannot open or forge a device token. The actual screen
video and input travel peer-to-peer over WebRTC — relayed, when NAT requires
it, by a TURN server (coturn) running alongside this process — and stay
DTLS-SRTP encrypted end to end, so neither the relay nor TURN ever sees them.
"""

import asyncio
import base64
import hmac
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from aiohttp import WSMsgType, web

from .rooms import Rooms, ice_servers

log = logging.getLogger("pocketdesk.relay")
CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"
ROOM_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")


@dataclass
class Config:
    host_secret: str
    stun_url: str = ""
    turn_url: str = ""
    turn_secret: str = ""
    turn_ttl: int = 43200          # TURN credential lifetime (12h)
    conn_per_min: int = 30         # viewer connections per IP per minute
    pair_per_min: int = 10         # pairing attempts per IP per minute


CFG = web.AppKey("cfg", Config)
ROOMS = web.AppKey("rooms", Rooms)
LIMITER = web.AppKey("limiter", object)
PAGE = web.AppKey("page", str)


class Limiter:
    """A plain per-IP sliding-window rate limiter (one process, in memory)."""

    def __init__(self, conn_per_min, pair_per_min):
        self.conn_per_min, self.pair_per_min = conn_per_min, pair_per_min
        self._conn, self._pair = {}, {}

    def _allow(self, store, ip, limit):
        now = time.time()
        hits = [t for t in store.get(ip, ()) if now - t < 60]
        if len(hits) >= limit:
            store[ip] = hits
            return False
        hits.append(now)
        store[ip] = hits
        return True

    def allow_connect(self, ip):
        return self._allow(self._conn, ip, self.conn_per_min)

    def allow_pair(self, ip):
        return self._allow(self._pair, ip, self.pair_per_min)


def _valid_room(room_id):
    return bool(room_id and ROOM_RE.fullmatch(room_id))


def _ice(cfg):
    return ice_servers(cfg.stun_url, cfg.turn_url, cfg.turn_secret, cfg.turn_ttl)


async def index_root(request):
    return web.Response(
        text="PocketDesk relay. Open the room link your computer printed: "
             "https://<this-host>/r/<room>\n",
        content_type="text/plain")


async def healthz(request):
    return web.Response(text="ok")


async def index_room(request):
    room_id = request.match_info["room"]
    if not _valid_room(room_id):
        return web.Response(status=404, text="No such room.")
    cfg = request.app[CFG]
    # A nonce lets exactly our injected config script run under a strict CSP.
    nonce = base64.b64encode(os.urandom(16)).decode()
    boot = (f'<base href="/"><script nonce="{nonce}">window.POCKETDESK={{'
            f"relay:location.origin.replace(/^http/,'ws'),"
            f"room:{json.dumps(room_id)},ice:{json.dumps(_ice(cfg))}"
            f"}};</script>")
    page = request.app[PAGE].replace("<head>", "<head>" + boot, 1)
    csp = ("default-src 'self'; "
           f"script-src 'self' 'nonce-{nonce}'; "
           "connect-src 'self'; img-src 'self' data:; "
           "style-src 'self'; frame-ancestors 'none'")
    return web.Response(text=page, content_type="text/html", headers={
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    })


def _reply(mid, status, error):
    return json.dumps({"id": mid, "status": status, "data": {"error": error}})


async def ws_host(request):
    """The host's outbound socket: authenticated, then replies get routed back."""
    room_id = request.match_info["room"]
    cfg = request.app[CFG]
    scheme, _, secret = request.headers.get("Authorization", "").partition(" ")
    if scheme != "Bearer" or not hmac.compare_digest(secret, cfg.host_secret):
        return web.Response(status=401, text="Bad host secret.")
    if not _valid_room(room_id):
        return web.Response(status=404, text="Bad room id.")

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    rooms = request.app[ROOMS]
    room = rooms.ensure(room_id)
    if room.host is not None and not room.host.closed:
        await room.host.close()  # a reconnect replaces the old link
    room.host = ws
    log.info("Host online for room %s", room_id)

    async def push_config():
        await ws.send_str(json.dumps({"type": "config", "ice": _ice(cfg)}))

    async def refresh():
        # TURN credentials expire, so re-send ICE config well before they do.
        while not ws.closed:
            await asyncio.sleep(max(60, cfg.turn_ttl // 2))
            if ws.closed:
                break
            try:
                await push_config()
            except Exception:
                break

    await push_config()
    refresher = asyncio.create_task(refresh())
    try:
        async for frame in ws:
            if frame.type != WSMsgType.TEXT:
                continue
            try:
                msg = json.loads(frame.data)
            except ValueError:
                continue
            tag, _, orig = str(msg.get("id", "")).partition(".")
            viewer = room.viewers.get(tag)
            if viewer is None or viewer.closed:
                continue
            msg["id"] = orig
            try:
                await viewer.send_str(json.dumps(msg))
            except Exception:
                pass
    finally:
        refresher.cancel()
        if room.host is ws:
            room.host = None
            log.info("Host offline for room %s", room_id)
        rooms.drop_if_empty(room)
    return ws


async def ws_view(request):
    """A browser's socket: each request is forwarded to the room's host."""
    room_id = request.match_info["room"]
    if not _valid_room(room_id):
        return web.Response(status=404, text="No such room.")
    limiter, ip = request.app[LIMITER], request.remote
    if not limiter.allow_connect(ip):
        return web.Response(status=429, text="Too many connections; wait a minute.")

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    rooms = request.app[ROOMS]
    room = rooms.ensure(room_id)
    tag = room.add_viewer(ws)
    try:
        async for frame in ws:
            if frame.type != WSMsgType.TEXT:
                continue
            try:
                msg = json.loads(frame.data)
            except ValueError:
                continue
            orig = msg.get("id")
            host = room.host
            if host is None or host.closed:
                await ws.send_str(_reply(orig, 503, "The computer is offline."))
                continue
            if msg.get("path") == "/api/pair" and not limiter.allow_pair(ip):
                await ws.send_str(_reply(orig, 429, "Too many pairing attempts; wait a minute."))
                continue
            msg["id"] = f"{tag}.{orig}"
            try:
                await host.send_str(json.dumps(msg))
            except Exception:
                await ws.send_str(_reply(orig, 503, "The computer is offline."))
    finally:
        room.remove_viewer(tag)
        rooms.drop_if_empty(room)
    return ws


def build_app(cfg: Config) -> web.Application:
    app = web.Application(client_max_size=256 * 1024)
    app[CFG] = cfg
    app[ROOMS] = Rooms()
    app[LIMITER] = Limiter(cfg.conn_per_min, cfg.pair_per_min)
    app[PAGE] = (CLIENT_DIR / "index.html").read_text(encoding="utf-8")
    app.router.add_get("/", index_root)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/r/{room}", index_room)
    app.router.add_get("/ws/host/{room}", ws_host)
    app.router.add_get("/ws/view/{room}", ws_view)
    # Static assets (app.js, style.css, manifest, icons) resolve to root because
    # the room page injects <base href="/">. Registered last as the fallback.
    app.router.add_static("/", CLIENT_DIR)
    return app
