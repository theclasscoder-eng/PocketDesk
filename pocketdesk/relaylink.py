"""Outbound link from the host to a relay server.

Normally the host listens for inbound HTTP and a phone on the same tunnel/LAN
reaches it directly. With ``--relay`` the host instead dials *out* to a relay
the user runs on a public VPS and keeps one authenticated WebSocket open, so no
inbound ports are opened on the home network and it works behind any NAT.

The relay is a dumb pipe: it forwards each browser request as a JSON envelope
``{"id", "path", "token", "body"}`` and routes our ``{"id", "status", "data"}``
reply back. We run the *same* core handlers the HTTP routes use
(:data:`pocketdesk.server.DISPATCH`) and gate them with the *same* token check
(:func:`pocketdesk.server.verify_token`). The relay never holds the AES key, so
it can neither forge nor open a token. Screen video and input still travel
peer-to-peer over WebRTC (relayed by the TURN server the relay advertises),
never through this socket, and stay DTLS-SRTP encrypted end to end.
"""

import asyncio
import json
import logging

import aiohttp

from .server import CONFIG, DISPATCH, OPEN_PATHS, verify_token

log = logging.getLogger("pocketdesk")

_RECONNECT_MIN = 1.0
_RECONNECT_MAX = 30.0


async def _handle(app, msg, send):
    """Run one relayed request and send its reply, keyed by the envelope id."""
    mid, path = msg.get("id"), msg.get("path")
    core = DISPATCH.get(path)
    if core is None:
        await send({"id": mid, "status": 404, "data": {"error": "Unknown path."}})
        return
    device = None
    if path not in OPEN_PATHS:
        device = verify_token(app, "Bearer " + (msg.get("token") or ""))
        if not device:
            await send({"id": mid, "status": 401, "data": {"error": "Not paired."}})
            return
    try:
        status, data = await core(app, device, msg.get("body") or {})
    except Exception:
        log.exception("Relay request failed: %s", path)
        status, data = 500, {"error": "Server error."}
    await send({"id": mid, "status": status, "data": data})


async def _session(app, url, room, secret):
    """Open one relay link and serve requests until it closes."""
    headers = {"Authorization": "Bearer " + secret} if secret else {}
    endpoint = f"{url.rstrip('/')}/ws/host/{room}"
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15)
    tasks = set()
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.ws_connect(endpoint, headers=headers, heartbeat=30) as ws:
            log.info("Relay link up: %s (room %s)", url, room)
            lock = asyncio.Lock()

            async def send(obj):
                # aiohttp does not promise frame integrity across concurrent
                # sends, and we fan requests out into tasks, so serialise here.
                async with lock:
                    await ws.send_str(json.dumps(obj))

            try:
                async for frame in ws:
                    if frame.type != aiohttp.WSMsgType.TEXT:
                        if frame.type in (aiohttp.WSMsgType.CLOSE,
                                          aiohttp.WSMsgType.CLOSING,
                                          aiohttp.WSMsgType.ERROR):
                            break
                        continue
                    try:
                        msg = json.loads(frame.data)
                    except ValueError:
                        continue
                    if msg.get("type") == "config":
                        # The relay owns the TURN secret; it hands us fresh ICE
                        # servers (STUN + an ephemeral TURN credential) to use
                        # when answering offers, so no TURN secret lives here.
                        app[CONFIG].ice_servers = tuple(msg.get("ice") or ())
                        log.info("Relay sent %d ICE server(s)", len(app[CONFIG].ice_servers))
                        continue
                    if "path" in msg:
                        task = asyncio.ensure_future(_handle(app, msg, send))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
            finally:
                for task in tasks:
                    task.cancel()


async def connect(app, url, room, secret):
    """Keep a relay link open, reconnecting with backoff until cancelled."""
    delay = _RECONNECT_MIN
    while True:
        try:
            await _session(app, url, room, secret)
            delay = _RECONNECT_MIN  # a clean drop: reconnect promptly
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Relay link down (%s); retrying in %.0fs", exc, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, _RECONNECT_MAX)
