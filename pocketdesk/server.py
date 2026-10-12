"""HTTP signaling, pairing API and the WebRTC session.

Data plane: one RTCPeerConnection per phone. Video goes host -> phone as an
SRTP media track; touch and key events come phone -> host as JSON on a
DTLS-encrypted DataChannel. HTTP is only used to pair and to swap SDP.
"""

import asyncio
import json
import logging
import math
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.codecs import h264, vpx

from . import access, appview, backends
from .auth import Auth, PairingError
from .capture import CaptureTrack, ScreenSource, list_screens

log = logging.getLogger("pocketdesk")
CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"
SCROLL_STEP = 30  # touch pixels per wheel notch

# aiortc's defaults are tuned for webcams; screen text needs more bits.
for _codec in (vpx, h264):
    _codec.DEFAULT_BITRATE = 2_000_000
    _codec.MAX_BITRATE = 6_000_000

AUTH = web.AppKey("auth", Auth)
CONFIG = web.AppKey("config", object)
STATE = web.AppKey("state", dict)


@dataclass
class Config:
    fps: int = 20
    max_width: int = 1600
    view_only: bool = False
    apps: object = "all"  # "all", or a frozenset of allowed app names
    desktop: bool = True  # offer whole displays, which show and control everything


class Session:
    def __init__(self, pc, source, track):
        self.pc = pc
        self.source = source
        self.track = track
        self.channel = None
        self.dead = False
        self.watcher = None
        self.scroll = [0.0, 0.0]

    def send(self, msg):
        if self.channel and self.channel.readyState == "open":
            self.channel.send(json.dumps(msg))

    def inside(self, pt):
        left, top, w, h = self.source.rect
        return left <= pt[0] < left + w and top <= pt[1] < top + h

    def nudge(self, pos, dx, dy):
        """Move a pointer position by a trackpad delta, kept inside the source."""
        left, top, w, h = self.source.rect
        return (int(min(max(pos[0] + dx, left), left + w - 1)),
                int(min(max(pos[1] + dy, top), top + h - 1)))

    def fraction(self, pt):
        left, top, w, h = self.source.rect
        return (pt[0] - left) / max(w - 1, 1), (pt[1] - top) / max(h - 1, 1)

    def point(self, m):
        """Map normalised stream coordinates (0..1) to desktop pixels."""
        x, y = m.get("x"), m.get("y")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)):
            return None
        left, top, w, h = self.source.rect
        x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
        return int(left + x * (w - 1)), int(top + y * (h - 1))


def _json_error(status, message):
    return web.json_response({"error": message}, status=status)


@web.middleware
async def guard(request, handler):
    # Reject cross-site POSTs (CSRF / DNS rebinding).
    origin = request.headers.get("Origin")
    if request.method == "POST" and origin and urlsplit(origin).netloc != request.host:
        return _json_error(403, "Cross-origin request refused.")
    if request.path.startswith("/api/") and request.path != "/api/pair":
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        device = request.app[AUTH].verify(token) if scheme == "Bearer" else None
        if not device:
            return _json_error(401, "Not paired.")
        request["device"] = device
    resp = await handler(request)
    resp.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def index(request):
    return web.FileResponse(CLIENT_DIR / "index.html")


async def pair(request):
    try:
        body = await request.json()
        token = request.app[AUTH].pair(body.get("pin", ""), body.get("name", "phone"))
    except PairingError as exc:
        return _json_error(403, str(exc))
    except (ValueError, AttributeError):
        return _json_error(400, "Bad request.")
    log.info("Paired a new device from %s", request.remote)
    return web.json_response({"token": token})


async def _visible(app):
    """Screens and windows this host is willing to share."""
    backend, apps = app[STATE]["backend"], app[CONFIG].apps
    loop = asyncio.get_running_loop()
    windows = await loop.run_in_executor(None, backend.list_windows) if backend else []
    for w in windows:
        # Chat apps the phone can show in its own app-style layout.
        w["appview"] = appview.profile_for(w.get("app")) if appview.available() else None
    # A full display shows every app, so it needs its own permission.
    screens = await loop.run_in_executor(None, list_screens) if app[CONFIG].desktop else []
    return screens, [w for w in windows if access.allowed(apps, w)]


async def _app_window(request, body=None):
    """The window id an app-view request names, if this host shares it."""
    raw = request.query.get("id") if body is None else body.get("id")
    try:
        hwnd = int(raw)
    except (TypeError, ValueError):
        return None
    _, windows = await _visible(request.app)
    return hwnd if appview.available() and any(w["id"] == hwnd for w in windows) else None


async def app_state(request):
    hwnd = await _app_window(request)
    if hwnd is None:
        return _json_error(403, "This computer does not share that.")
    try:
        model = await appview.snapshot(asyncio.get_running_loop(), hwnd)
    except Exception as exc:
        log.warning("App view failed: %s", exc)
        return _json_error(410, "That window was closed.")
    model["viewOnly"] = request.app[CONFIG].view_only
    return web.json_response(model)


async def app_press(request):
    body = await request.json()
    hwnd = await _app_window(request, body)
    if hwnd is None or request.app[CONFIG].view_only:
        return _json_error(403, "Not allowed.")
    ok = await appview.press(asyncio.get_running_loop(), hwnd, str(body.get("ref")))
    return web.json_response({"ok": ok})


async def app_scroll(request):
    """Scroll the real app's message list to match the phone."""
    body = await request.json()
    hwnd = await _app_window(request, body)
    pos = body.get("pos")
    if hwnd is None or request.app[CONFIG].view_only:
        return _json_error(403, "Not allowed.")
    if not isinstance(pos, (int, float)) or not math.isfinite(pos):
        return _json_error(400, "Bad request.")
    ok = await appview.scroll(asyncio.get_running_loop(), hwnd, float(pos))
    return web.json_response({"ok": ok})


async def app_send(request):
    """Type a message into the app's own prompt box and press Enter."""
    body = await request.json()
    hwnd = await _app_window(request, body)
    state = request.app[STATE]
    inj, text = state["injector"], body.get("text")
    if hwnd is None or inj is None or not isinstance(text, str) or not text.strip():
        return _json_error(403, "Not allowed.")
    loop = asyncio.get_running_loop()
    window = state["backend"].WindowSource(hwnd)
    # Keys go to whatever has focus, so only type once the prompt box has it.
    await loop.run_in_executor(None, window.focus)
    if not window.is_foreground():
        log.warning("App view: Windows would not bring the app to the front")
        return _json_error(409, "Windows would not bring the app to the front. "
                                "Click it once on the computer, then send again.")
    focused, centre = await appview.focus_composer(loop, hwnd)
    if not focused and centre:
        # Some builds ignore a programmatic focus; a real click always works.
        inj.move(*centre)
        inj.click("left")
        await asyncio.sleep(0.15)
        focused = await appview.has_focus(loop, hwnd)
    if not focused:
        log.warning("App view: prompt box did not take focus")
        return _json_error(409, "Could not find the message box in the app. "
                                "Try Desktop View for this message.")
    for i, line in enumerate(text[:4000].replace("\r", "").split("\n")):
        if i:
            inj.key("Enter", ["shift"])  # new line without sending
        inj.text(line)
    inj.key("Enter")
    return web.json_response({"ok": True})


async def sources(request):
    screens, windows = await _visible(request.app)
    return web.json_response({"screens": screens, "windows": windows,
                              "limited": request.app[CONFIG].apps != "all",
                              "desktop": request.app[CONFIG].desktop,
                              "host": platform.node(), "platform": sys.platform,
                              "viewOnly": request.app[CONFIG].view_only})


def _make_source(spec, backend):
    kind, sid = spec.get("kind"), spec.get("id")
    if not isinstance(sid, int):
        raise ValueError("Bad source id.")
    if kind == "screen":
        return ScreenSource(sid)
    if kind == "window" and backend:
        return backend.WindowSource(sid)
    raise ValueError("Unknown source.")


async def offer(request):
    app, cfg = request.app, request.app[CONFIG]
    state = app[STATE]
    try:
        body = await request.json()
        desc = RTCSessionDescription(sdp=body["sdp"], type=body["type"])
        spec = body.get("source") or {}
        screens, windows = await _visible(app)
        offered = screens if spec.get("kind") == "screen" else windows
        if not any(s["id"] == spec.get("id") for s in offered):
            return _json_error(403, "This computer does not share that.")
        source = _make_source(spec, state["backend"])
    except (ValueError, KeyError, TypeError, backends.SourceGone) as exc:
        return _json_error(400, str(exc) or "Bad request.")

    await _close_session(state)  # one controller at a time

    # No ICE servers: candidates are the host's own addresses only, so media
    # flows directly over the tunnel and nothing is sent to a third party.
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    session = Session(pc, source, None)

    async def end():
        if state.get("session") is session:
            await _close_session(state)

    def on_gone(why):
        # The shared window closed: tell the phone, then drop the whole
        # session so no further input can reach this computer.
        session.dead = True
        session.send({"t": "gone", "why": why})
        asyncio.get_running_loop().call_later(0.3, asyncio.ensure_future, end())

    session.track = CaptureTrack(source, cfg.fps, cfg.max_width, on_gone=on_gone)
    state["session"] = session
    pc.addTrack(session.track)

    @pc.on("datachannel")
    def on_channel(channel):
        session.channel = channel

        @channel.on("close")
        def on_close():
            asyncio.ensure_future(end())

        @channel.on("message")
        def on_message(raw):
            try:
                _handle_input(app, session, raw)
            except Exception:
                log.exception("Input event failed")

    @pc.on("connectionstatechange")
    async def on_state():
        log.info("Connection %s", pc.connectionState)
        if pc.connectionState in ("failed", "closed") and state.get("session") is session:
            await _close_session(state)

    if state["injector"]:
        session.watcher = asyncio.ensure_future(_watch_pointer(state["injector"], session))
    await pc.setRemoteDescription(desc)
    await pc.setLocalDescription(await pc.createAnswer())
    if not cfg.view_only:
        source.focus()
    return web.json_response({"sdp": pc.localDescription.sdp,
                              "type": pc.localDescription.type})


def _handle_input(app, session, raw):
    inj = app[STATE]["injector"]
    if inj is None or not isinstance(raw, str) or len(raw) > 4096:
        return
    if session.dead or app[STATE].get("session") is not session:
        return
    m = json.loads(raw)
    if not isinstance(m, dict):
        return
    t = m.get("t")
    source = session.source
    if t == "rel":
        # Trackpad: move relative to where the pointer is, and report the new
        # spot so the phone can draw the pointer without waiting for video.
        dx, dy = m.get("dx"), m.get("dy")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (dx, dy)):
            return
        pt = session.nudge(inj.position(), max(-400, min(400, dx)), max(-400, min(400, dy)))
        inj.move(*pt)
        x, y = session.fraction(pt)
        session.send({"t": "ptr", "x": x, "y": y})
    elif t in ("move", "down", "up", "click"):
        if "x" in m:
            pt = session.point(m)
        else:  # trackpad button: act where the pointer already is
            pt = inj.position()
            if t != "up" and not session.inside(pt):
                return
        if pt is None:
            return
        if t == "up":
            inj.move(*pt)
            inj.button(m.get("b", "left"), False)
        elif t == "move":
            inj.move(*pt)
        else:
            # Bring the shared window forward first. If something else still
            # has the foreground, the click would land on that instead.
            source.focus()
            if not source.is_foreground():
                return
            inj.move(*pt)
            if t == "click":
                inj.click(m.get("b", "left"))
            else:
                inj.button(m.get("b", "left"), True)
        if t in ("click", "up"):
            asyncio.get_running_loop().call_later(0.2, _report_caret, app, session)
    elif not source.is_foreground():
        return  # keys and scrolling only ever go to the shared window
    elif t == "scroll":
        steps = []
        for i, k in enumerate(("dx", "dy")):
            v = m.get(k, 0)
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                return
            session.scroll[i] += max(-2000.0, min(2000.0, v)) / SCROLL_STEP
            whole = int(session.scroll[i])
            session.scroll[i] -= whole
            steps.append(whole)
        if any(steps):
            inj.scroll(-steps[0], steps[1])
    elif t == "key":
        mods = m.get("mods")
        inj.key(m.get("k"), mods if isinstance(mods, list) else ())
    elif t == "text":
        inj.text(m.get("s"))


def _report_caret(app, session):
    backend = app[STATE]["backend"]
    focused = backend.text_focus() if backend else None
    if focused is not None:
        session.send({"t": "caret", "on": bool(focused)})


async def _watch_pointer(inj, session):
    """Tell the phone where the mouse pointer is; the video does not show it."""
    last = None
    while not session.dead:
        await asyncio.sleep(0.04)
        pt = inj.position()
        now = session.fraction(pt) if session.inside(pt) else None
        if now != last and session.channel and session.channel.readyState == "open":
            last = now
            session.send({"t": "ptr", "x": now[0], "y": now[1]} if now
                         else {"t": "ptr", "off": True})


async def _close_session(state):
    session = state.pop("session", None)
    if not session:
        return
    session.dead = True
    if session.watcher:
        session.watcher.cancel()
    if state["injector"]:
        state["injector"].release_all()
    session.track.stop()
    await session.pc.close()


async def _pin_rotator(app):
    auth = app[AUTH]

    async def run():
        while True:
            await asyncio.sleep(15)
            if auth.pairing_enabled and time.time() > auth.pin_expires:
                auth.new_pin()

    task = asyncio.create_task(run())
    yield
    task.cancel()
    await _close_session(app[STATE])


def build_app(auth: Auth, cfg: Config) -> web.Application:
    try:
        backend = backends.load()
    except Exception as exc:
        log.warning("Window capture unavailable: %s", exc)
        backend = None
    injector = None
    if not cfg.view_only:
        try:
            from .inject import Injector
            injector = Injector()
        except Exception as exc:
            log.warning("Input injection unavailable, running view-only: %s", exc)
            cfg.view_only = True

    app = web.Application(middlewares=[guard], client_max_size=256 * 1024)
    app[AUTH] = auth
    app[CONFIG] = cfg
    app[STATE] = {"backend": backend, "injector": injector}
    app.cleanup_ctx.append(_pin_rotator)
    app.router.add_get("/", index)
    app.router.add_post("/api/pair", pair)
    app.router.add_get("/api/sources", sources)
    app.router.add_post("/api/offer", offer)
    app.router.add_get("/api/app", app_state)
    app.router.add_post("/api/app/press", app_press)
    app.router.add_post("/api/app/send", app_send)
    app.router.add_post("/api/app/scroll", app_scroll)
    app.router.add_static("/", CLIENT_DIR)
    return app
