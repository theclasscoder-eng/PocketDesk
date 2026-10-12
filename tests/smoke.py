"""End-to-end check without a phone:  python tests/smoke.py

Starts the agent view-only on a loopback port, pairs with the PIN, then
receives real video frames over WebRTC from the full screen and from one
window. View-only, so it never moves your mouse or types.
"""

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiohttp import ClientSession, web
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from pocketdesk.auth import Auth
from pocketdesk.server import CONFIG, STATE, Config, build_app


async def stream(http, base, headers, source):
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    pc.addTransceiver("video", direction="recvonly")
    pc.createDataChannel("input")
    got = asyncio.get_running_loop().create_future()

    @pc.on("track")
    def on_track(track):
        async def read():
            for _ in range(3):
                frame = await track.recv()
            got.set_result((frame.width, frame.height))
        asyncio.ensure_future(read())

    await pc.setLocalDescription(await pc.createOffer())
    body = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "source": source}
    async with http.post(base + "/api/offer", json=body, headers=headers) as r:
        assert r.status == 200, await r.text()
        await pc.setRemoteDescription(RTCSessionDescription(**await r.json()))
    size = await asyncio.wait_for(got, 30)
    await pc.close()
    return size


async def main():
    auth = Auth(Path(tempfile.mkdtemp(prefix="pocketdesk-test-")))
    app = build_app(auth, Config(view_only=True))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = "http://127.0.0.1:%d" % runner.addresses[0][1]

    async with ClientSession() as http:
        async with http.get(base + "/api/sources") as r:
            assert r.status == 401, "API must refuse unpaired clients"
        async with http.post(base + "/api/pair", json={"pin": "x", "name": "t"}) as r:
            assert r.status == 403, "wrong PIN must be refused"
        async with http.post(base + "/api/pair", json={"pin": auth.pin, "name": "t"},
                             headers={"Origin": "http://evil.example"}) as r:
            assert r.status == 403, "cross-origin POST must be refused"
        used = auth.pin
        async with http.post(base + "/api/pair", json={"pin": used, "name": "t"}) as r:
            assert r.status == 200
            headers = {"Authorization": "Bearer " + (await r.json())["token"]}
        async with http.post(base + "/api/pair", json={"pin": used, "name": "t"}) as r:
            assert r.status == 403, "a PIN must be single use"
        async with http.get(base + "/api/sources", headers={"Authorization": "Bearer junk"}) as r:
            assert r.status == 401, "forged token must be refused"
        print("auth: ok")

        async with http.get(base + "/api/sources", headers=headers) as r:
            src = await r.json()
        print(f"sources: {len(src['screens'])} screen(s), {len(src['windows'])} window(s)")

        size = await stream(http, base, headers, {"kind": "screen", "id": src["screens"][0]["id"]})
        print("full desktop frame:", size)
        if src["windows"]:
            win = src["windows"][0]
            size = await stream(http, base, headers, {"kind": "window", "id": win["id"]})
            print("single window frame:", size)

        await closing_window_ends_session(http, base, headers, app)

        # Limited access: only the chosen app is listed, nothing else connects.
        chosen = src["windows"][0]["app"].lower() if src["windows"] else "none"
        app[CONFIG].apps = frozenset({chosen})
        app[CONFIG].desktop = False
        async with http.get(base + "/api/sources", headers=headers) as r:
            lim = await r.json()
        assert lim["screens"] == [], "full desktop must not be offered when limited"
        assert all(w["app"].lower() == chosen for w in lim["windows"])
        body = {"sdp": "x", "type": "offer", "source": {"kind": "screen", "id": 1}}
        async with http.post(base + "/api/offer", json=body, headers=headers) as r:
            assert r.status == 403, "limited host must refuse the full desktop"
        other = [w for w in src["windows"] if w["app"].lower() != chosen]
        if other:
            body["source"] = {"kind": "window", "id": other[0]["id"]}
            async with http.post(base + "/api/offer", json=body, headers=headers) as r:
                assert r.status == 403, "limited host must refuse unlisted apps"
        print(f"limited access: only '{chosen}' offered ({len(lim['windows'])} window(s))")

    await runner.cleanup()
    print("PASS")


async def closing_window_ends_session(http, base, headers, app):
    """Share a throwaway window, close it, and check the host hangs up."""
    title = "pocketdesk-smoke-window"
    proc = subprocess.Popen([sys.executable, "-c",
                             f"import tkinter as t; r=t.Tk(); r.title('{title}'); r.mainloop()"])
    try:
        for _ in range(40):
            await asyncio.sleep(0.25)
            async with http.get(base + "/api/sources", headers=headers) as r:
                wins = [w for w in (await r.json())["windows"] if w["title"] == title]
            if wins:
                break
        else:
            print("window close: skipped (could not open a test window)")
            return

        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        pc.addTransceiver("video", direction="recvonly")
        channel = pc.createDataChannel("input")
        messages, closed = [], asyncio.Event()
        channel.on("message", lambda m: messages.append(json.loads(m)["t"]))
        channel.on("close", closed.set)
        await pc.setLocalDescription(await pc.createOffer())
        body = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type,
                "source": {"kind": "window", "id": wins[0]["id"]}}
        async with http.post(base + "/api/offer", json=body, headers=headers) as r:
            await pc.setRemoteDescription(RTCSessionDescription(**await r.json()))
        for _ in range(40):
            if channel.readyState == "open":
                break
            await asyncio.sleep(0.25)
        assert "session" in app[STATE], "session should be live before the window closes"

        proc.kill()
        await asyncio.wait_for(closed.wait(), 10)
        assert "gone" in messages, "phone must be told the window closed"
        assert "session" not in app[STATE], "host must drop the session"
        await pc.close()
        print("window close: session ended")
    finally:
        proc.kill()


asyncio.run(main())
