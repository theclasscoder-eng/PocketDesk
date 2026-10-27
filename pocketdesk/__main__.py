"""Run the host agent:  python -m pocketdesk"""

import os

# Belt and braces: nothing here uses CUDA, and nothing it loads may start to.
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import argparse
import asyncio
import ipaddress
import logging
import sys
from pathlib import Path

import ifaddr
from aiohttp import web

from . import access
from .auth import Auth
from .server import STATE, Config, build_app

TAILNET = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's CGNAT range
STATE_DIR = Path.home() / ".pocketdesk"


def local_ipv4():
    ips = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if isinstance(ip.ip, str):
                addr = ipaddress.ip_address(ip.ip)
                if not addr.is_loopback and not addr.is_link_local:
                    ips.append(addr)
    return ips


def print_qr(url):
    if not url:
        return
    try:
        import qrcode
    except ImportError:
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    try:
        qr.print_ascii(invert=True)
    except UnicodeEncodeError:
        pass  # console cannot draw block characters; the URL is printed anyway


def relay_room(explicit):
    """The room id to register on the relay with.

    A stable, unguessable id is remembered in the state dir so the phone's URL
    stays the same across runs, unless the user pins one with --relay-room.
    """
    if explicit:
        return explicit
    path = STATE_DIR / "relay_room"
    try:
        saved = path.read_text().strip()
        if saved:
            return saved
    except OSError:
        pass
    import secrets
    room = secrets.token_urlsafe(12)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(room)
    return room


def relay_web_url(relay, room):
    """The https:// address the phone opens, derived from the wss:// relay."""
    base = relay.rstrip("/")
    if base.startswith("wss://"):
        base = "https://" + base[len("wss://"):]
    elif base.startswith("ws://"):
        base = "http://" + base[len("ws://"):]
    return f"{base}/r/{room}"


async def serve(args):
    relay_secret = args.relay_secret or os.environ.get("POCKETDESK_RELAY_SECRET", "")
    if args.relay and not relay_secret:
        print("ERROR: --relay needs --relay-secret (or POCKETDESK_RELAY_SECRET).")
        return
    room = relay_room(args.relay_room) if args.relay else None
    relay_url = relay_web_url(args.relay, room) if args.relay else None

    ips = local_ipv4()
    tail = [ip for ip in ips if ip in TAILNET]
    if args.relay and not args.lan:
        # Relay mode reaches out; no local listener is needed unless --lan is
        # also set to allow same-Wi-Fi connections at the same time.
        binds, reach = [], []
    elif args.lan:
        binds, reach = ["0.0.0.0"], tail + [ip for ip in ips if ip not in TAILNET]
    else:
        binds, reach = ["127.0.0.1"] + [str(ip) for ip in tail], tail

    urls = [f"http://{ip}:{args.port}/" for ip in reach]
    if not urls and not args.relay:
        urls = [f"http://127.0.0.1:{args.port}/"]
    primary = relay_url or (urls[0] if urls else f"http://127.0.0.1:{args.port}/")

    def show_pin(pin):
        print(f"\n  PIN: {pin}   (valid 10 minutes, single use)")
        print(f"  Open on your phone: {primary}")

    def show_qr():
        # The QR code only carries the address. The PIN is never in it, so
        # the phone always has to type what is on this screen.
        print_qr(primary)

    auth = Auth(STATE_DIR)
    if args.revoke_all:
        auth.revoke_all()
        print("All paired devices revoked.")
    auth.pairing_enabled = not args.no_pairing

    cfg = Config(fps=args.fps, max_width=args.max_width, view_only=args.view_only)
    app = build_app(auth, cfg)
    apps, expiry = access.load(STATE_DIR), access.load_expiry(STATE_DIR)
    if args.setup or apps is None or expiry is access.UNSET:
        # First run, --setup, or an answer is missing: ask both, expiry first.
        expiry = access.ask_expiry(STATE_DIR)
        apps = access.ask(STATE_DIR, app[STATE]["backend"])
    cfg.apps = apps
    cfg.desktop = access.desktop_allowed(STATE_DIR, apps)
    auth.ttl = expiry * 3600 if expiry else None
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    for host in binds:
        await web.TCPSite(runner, host, args.port).start()

    relay_task = None
    if args.relay:
        from . import relaylink
        relay_task = asyncio.create_task(
            relaylink.connect(app, args.relay, room, relay_secret))

    if binds:
        print(f"PocketDesk listening on: {', '.join(binds)} port {args.port}")
    if args.relay:
        print(f"Relay: {args.relay}   (room {room})")
    print(f"Paired devices: {len(auth.devices)}")
    print(f"Phones can see: {access.describe_all(STATE_DIR, apps)}")
    print(f"Sign-in lasts:  {access.describe_expiry(expiry)}   (change both with --setup)")
    if not tail and not args.lan and not args.relay:
        print("\n  Tailscale was not found, so only this computer can connect.\n"
              "  Install Tailscale on this computer and your phone, sign in to the\n"
              "  same account, then start PocketDesk again. For same-Wi-Fi use\n"
              "  without Tailscale, run with --lan (pairing is then unencrypted).\n"
              "  To connect over the internet through your own server, use --relay.")
    if args.lan:
        print("\n  WARNING: --lan serves plain HTTP to every device on this network.")
    if auth.pairing_enabled:
        auth.on_pin = show_pin
        show_qr()
        show_pin(auth.pin)
    else:
        print("\n  Pairing is off; only already-paired devices can connect.")
        print(f"  {primary}")
    try:
        await asyncio.Event().wait()
    finally:
        if relay_task:
            relay_task.cancel()
        await runner.cleanup()


def main():
    p = argparse.ArgumentParser(prog="pocketdesk", description=__doc__)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--lan", action="store_true",
                   help="also listen on the local network, not just Tailscale")
    p.add_argument("--relay", metavar="URL",
                   help="connect out to your relay server, e.g. "
                        "wss://relay.example.com (no open ports / NAT needed)")
    p.add_argument("--relay-room", metavar="CODE",
                   help="room id on the relay (generated and remembered if omitted)")
    p.add_argument("--relay-secret", metavar="SECRET",
                   help="shared secret authorising this host to the relay "
                        "(or set POCKETDESK_RELAY_SECRET)")
    p.add_argument("--fps", type=int, default=20, choices=range(1, 61), metavar="1-60")
    p.add_argument("--max-width", type=int, default=1600,
                   help="downscale frames wider than this (pixels)")
    p.add_argument("--view-only", action="store_true", help="stream but accept no input")
    p.add_argument("--no-pairing", action="store_true", help="refuse new devices")
    p.add_argument("--revoke-all", action="store_true", help="forget every paired device")
    p.add_argument("--setup", action="store_true",
                   help="choose again which apps phones may see")
    args = p.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # show the PIN at once, even when piped
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("aioice").setLevel(logging.WARNING)
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
