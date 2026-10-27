# PocketDesk relay

Connect two computers over the internet **without Tailscale** by running your own
small relay on a VPS. The host desktop dials *out* to the relay and the laptop
opens an `https://` link on the relay — no port forwarding, no open ports at
home, works behind any NAT.

```
 Laptop browser  --wss/https-->  [ VPS: Caddy(TLS) -> relay ]  <--wss(out)--  Host agent
        |                                                                          |
        +---------------- WebRTC media/input (DTLS-SRTP) via coturn TURN ----------+
```

The relay is a **dumb authenticated pipe**. It forwards pairing, the source list,
the WebRTC SDP and App View messages between the two sides. It never holds the
host's encryption key, so it cannot read or forge your device token. Screen video
and input travel peer-to-peer over WebRTC and stay DTLS-SRTP encrypted end to
end — coturn only ever relays those encrypted packets.

## What you need

- A VPS with a public IP.
- A DNS **A record** `relay.example.com` → your VPS IP.
- Firewall open on the VPS: **443/tcp** (Caddy), **3478/tcp+udp** and
  **49160–49200/udp** (coturn). Add **5349/tcp** only if you enable TURN-over-TLS.
- Docker + Docker Compose on the VPS.

## Deploy (VPS)

```bash
cd relay
cp .env.example .env            # edit: DOMAIN + three random secrets
cp turnserver.conf.example turnserver.conf   # set static-auth-secret = TURN_SECRET
docker compose up -d --build
```

Generate secrets with `openssl rand -base64 32`. `TURN_SECRET` must be identical
in `.env` and in `turnserver.conf`. Check it is up: `https://relay.example.com/healthz`
should return `ok` with a valid padlock.

## Connect (host desktop)

Install the host requirements (`pip install -r ../requirements.txt`) and run:

```bash
python -m pocketdesk --relay wss://relay.example.com --relay-secret <HOST_SECRET>
```

`--relay-secret` is the `HOST_SECRET` from the VPS `.env`. The host prints a room
link like `https://relay.example.com/r/XXXXXXXX` and a PIN. It remembers the room
id, so the link stays the same next time (pin your own with `--relay-room`).

Open that link on the laptop, type the PIN once, and pick a screen or window.

## Notes

- **TLS**: Caddy auto-provisions a Let's Encrypt certificate for `DOMAIN`. The
  browser and the host both connect over TLS to the relay.
- **Plain TURN is fine**: media is already encrypted (DTLS-SRTP), so `turn:` on
  3478 is secure. `turns:` on 5349 only helps punch through networks that block
  UDP; enable it (certs required) by uncommenting the TLS lines in
  `turnserver.conf` and adding the `turns:` URL to `TURN_URL`.
- **Who can connect**: the room id is a long, unguessable capability and the host
  secret stops strangers from registering rooms; anyone who gets the link still
  has to pass the PIN. The relay rate-limits connections and pairing attempts.
- **Local mode still works**: without `--relay`, the host behaves exactly as
  before (Tailscale/loopback by default, `--lan` for same-Wi-Fi).
