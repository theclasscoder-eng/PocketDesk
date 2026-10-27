"""Run the relay:  python -m relay

Runs plain HTTP; put a TLS terminator (Caddy) in front of it in production so
browsers and the host connect over https/wss. See relay/README.md.
"""

import argparse
import logging
import os

from aiohttp import web

from .server import Config, build_app


def main():
    p = argparse.ArgumentParser(prog="relay", description=__doc__)
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (keep 127.0.0.1 behind a TLS proxy)")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--host-secret", default=os.environ.get("POCKETDESK_RELAY_HOST_SECRET", ""),
                   help="shared secret a host must present to register a room "
                        "(or set POCKETDESK_RELAY_HOST_SECRET)")
    p.add_argument("--stun-url", default=os.environ.get("POCKETDESK_STUN_URL", ""),
                   help="e.g. stun:relay.example.com:3478")
    p.add_argument("--turn-url", default=os.environ.get("POCKETDESK_TURN_URL", ""),
                   help="comma-separated, e.g. "
                        "turn:relay.example.com:3478,turns:relay.example.com:5349?transport=tcp")
    p.add_argument("--turn-secret", default=os.environ.get("POCKETDESK_TURN_SECRET", ""),
                   help="coturn static-auth-secret for minting ephemeral credentials")
    p.add_argument("--turn-ttl", type=int, default=43200,
                   help="TURN credential lifetime in seconds (default 12h)")
    args = p.parse_args()

    if not args.host_secret:
        p.error("--host-secret (or POCKETDESK_RELAY_HOST_SECRET) is required")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = Config(host_secret=args.host_secret, stun_url=args.stun_url,
                 turn_url=args.turn_url, turn_secret=args.turn_secret,
                 turn_ttl=args.turn_ttl)
    web.run_app(build_app(cfg), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
