"""Room registry and ephemeral TURN credentials for the relay.

A *room* is a rendezvous point named by a long, unguessable id the host picks.
One host registers a room (authenticated by the shared host secret) and any
number of browsers join it; the relay bridges their control messages. The relay
holds no PocketDesk secrets — it cannot open or forge the host's device tokens —
so a stranger who learns a room id still faces the host's PIN.
"""

import base64
import hashlib
import hmac
import time


class Room:
    def __init__(self, room_id):
        self.id = room_id
        self.host = None          # the host's WebSocketResponse, or None
        self.viewers = {}         # tag -> browser WebSocketResponse
        self._next = 0

    def add_viewer(self, ws):
        self._next += 1
        tag = str(self._next)
        self.viewers[tag] = ws
        return tag

    def remove_viewer(self, tag):
        self.viewers.pop(tag, None)


class Rooms:
    def __init__(self):
        self._rooms = {}

    def get(self, room_id):
        return self._rooms.get(room_id)

    def ensure(self, room_id):
        room = self._rooms.get(room_id)
        if room is None:
            room = self._rooms[room_id] = Room(room_id)
        return room

    def drop_if_empty(self, room):
        if room.host is None and not room.viewers:
            self._rooms.pop(room.id, None)


def mint_turn(secret, ttl=43200, name="pd"):
    """A short-lived TURN credential (coturn ``use-auth-secret`` scheme).

    The username is an expiry timestamp; the password is HMAC-SHA1 of that
    username under the TURN static-auth-secret. coturn validates it without any
    per-user state, and it stops working after ``ttl`` seconds, so it is safe to
    hand to every browser.
    """
    expiry = int(time.time()) + ttl
    username = f"{expiry}:{name}"
    digest = hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
    return username, base64.b64encode(digest).decode()


def ice_servers(stun_url, turn_url, turn_secret, ttl=43200):
    """Build the ICE server list handed to a browser and to the host.

    ``turn_url`` may be a comma-separated list (e.g. UDP plus TURN-over-TLS on
    443) which is sent as a single entry with one credential, as WebRTC expects.
    """
    servers = []
    if stun_url:
        servers.append({"urls": [u.strip() for u in stun_url.split(",") if u.strip()]})
    if turn_url and turn_secret:
        user, cred = mint_turn(turn_secret, ttl)
        servers.append({"urls": [u.strip() for u in turn_url.split(",") if u.strip()],
                        "username": user, "credential": cred})
    return servers
