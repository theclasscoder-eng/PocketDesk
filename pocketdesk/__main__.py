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


async def serve(args):
    ips = local_ipv4()
    tail = [ip for ip in ips if ip in TAILNET]
    if args.lan:
        binds, reach = ["0.0.0.0"], tail + [ip for ip in ips if ip not in TAILNET]
    else:
        binds, reach = ["127.0.0.1"] + [str(ip) for ip in tail], tail

    urls = [f"http://{ip}:{args.port}/" for ip in reach] or [f"http://127.0.0.1:{args.port}/"]

    def show_pin(pin):
        print(f"\n  PIN: {pin}   (valid 10 minutes, single use)")
        print(f"  Open on your phone: {urls[0]}")

    def show_qr():
        # The QR code only carries the address. The PIN is never in it, so
        # the phone always has to type what is on this screen.
        print_qr(urls[0])

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

    print(f"PocketDesk listening on: {', '.join(binds)} port {args.port}")
    print(f"Paired devices: {len(auth.devices)}")
    print(f"Phones can see: {access.describe_all(STATE_DIR, apps)}")
    print(f"Sign-in lasts:  {access.describe_expiry(expiry)}   (change both with --setup)")
    if not tail and not args.lan:
        print("\n  Tailscale was not found, so only this computer can connect.\n"
              "  Install Tailscale on this computer and your phone, sign in to the\n"
              "  same account, then start PocketDesk again. For same-Wi-Fi use\n"
              "  without Tailscale, run with --lan (pairing is then unencrypted).")
    if args.lan:
        print("\n  WARNING: --lan serves plain HTTP to every device on this network.")
    if auth.pairing_enabled:
        auth.on_pin = show_pin
        show_qr()
        show_pin(auth.pin)
    else:
        print("\n  Pairing is off; only already-paired devices can connect.")
        for url in urls:
            print(f"  {url}")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main():
    p = argparse.ArgumentParser(prog="pocketdesk", description=__doc__)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--lan", action="store_true",
                   help="also listen on the local network, not just Tailscale")
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
