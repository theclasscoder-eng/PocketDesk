"""Pairing PIN and AES-256-GCM device tokens.

A phone pairs once with the 6-digit PIN shown on the host. It gets back a
token: an AES-256-GCM sealed blob only this host can open. Every API call
and every WebRTC offer must carry it.
"""

import base64
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PIN_TTL = 600  # seconds a PIN stays valid
MAX_FAILS = 5  # wrong PINs before the PIN rotates and pairing locks
LOCKOUT = 60  # seconds pairing stays locked after MAX_FAILS
TOKEN_TTL = 12 * 3600  # default sign-in lifetime; Auth.ttl overrides, None = no limit
_AAD = b"pocketdesk-token-v1"


class PairingError(Exception):
    pass


class Auth:
    def __init__(self, state_dir: Path, on_pin=None):
        self.state_dir = state_dir
        self.on_pin = on_pin
        state_dir.mkdir(parents=True, exist_ok=True)
        self._key = self._load_key()
        self._devices_path = state_dir / "devices.json"
        self.devices = self._load_devices()
        self.pairing_enabled = True
        self.ttl = TOKEN_TTL
        self._fails = 0
        self._locked_until = 0.0
        self.pin = ""
        self.pin_expires = 0.0
        self.new_pin()

    def _load_key(self) -> bytes:
        path = self.state_dir / "secret.key"
        if path.exists():
            key = path.read_bytes()
            if len(key) == 32:
                return key
        key = AESGCM.generate_key(bit_length=256)
        path.write_bytes(key)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key

    def _load_devices(self) -> dict:
        try:
            return json.loads(self._devices_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_devices(self):
        self._devices_path.write_text(json.dumps(self.devices, indent=2), "utf-8")

    def new_pin(self):
        self.pin = f"{secrets.randbelow(10**6):06d}"
        self.pin_expires = time.time() + PIN_TTL
        self._fails = 0
        if self.on_pin:
            self.on_pin(self.pin)

    def pair(self, pin: str, name: str) -> str:
        now = time.time()
        if not self.pairing_enabled:
            raise PairingError("Pairing is disabled on this host.")
        if now < self._locked_until:
            raise PairingError("Too many wrong PINs. Try again in a minute.")
        if now > self.pin_expires:
            self.new_pin()
            raise PairingError("PIN expired. Use the new PIN shown on the host.")
        if not hmac.compare_digest(str(pin).encode(), self.pin.encode()):
            self._fails += 1
            if self._fails >= MAX_FAILS:
                self._locked_until = now + LOCKOUT
                self.new_pin()
            raise PairingError("Wrong PIN.")
        if self.ttl is not None:  # drop sign-ins whose token has expired
            self.devices = {d: v for d, v in self.devices.items()
                            if now - v.get("paired", 0) <= self.ttl}
        device_id = secrets.token_hex(8)
        self.devices[device_id] = {"name": str(name)[:80], "paired": int(now)}
        self._save_devices()
        self.new_pin()  # a PIN pairs exactly one device
        return self._seal(device_id)

    def _seal(self, device_id: str) -> str:
        nonce = os.urandom(12)
        body = json.dumps({"d": device_id, "iat": int(time.time())}).encode()
        blob = nonce + AESGCM(self._key).encrypt(nonce, body, _AAD)
        return base64.urlsafe_b64encode(blob).decode().rstrip("=")

    def verify(self, token: str):
        """Return the device id for a valid token, else None."""
        try:
            blob = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            body = AESGCM(self._key).decrypt(blob[:12], blob[12:], _AAD)
            claims = json.loads(body)
        except (ValueError, InvalidTag, TypeError):
            return None
        if self.ttl is not None and time.time() - claims.get("iat", 0) > self.ttl:
            return None
        device_id = claims.get("d")
        return device_id if device_id in self.devices else None

    def revoke_all(self):
        self.devices = {}
        self._save_devices()
