<div align="center">

<!-- Logo: save a 256x256 image as docs/logo.png and uncomment the next line. -->
<!-- <img src="docs/logo.png" alt="PocketDesk logo" width="120"> -->

# PocketDesk

**Your computer, on your phone. One window or the whole desktop.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Host: Windows | macOS | Linux](https://img.shields.io/badge/host-Windows%20%7C%20macOS%20%7C%20Linux-555)
![Client: any browser](https://img.shields.io/badge/client-any%20browser-0a84ff)
![Transport: WebRTC over WireGuard](https://img.shields.io/badge/transport-WebRTC%20over%20WireGuard-2ea44f)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-ff69b4.svg)](CONTRIBUTING.md)

<!-- Screenshot: save one as docs/screenshot.png and uncomment the next line. -->
<!-- <img src="docs/screenshot.png" alt="PocketDesk on a phone" width="720"> -->

</div>

PocketDesk streams a single app window, or your entire desktop, from your
computer to a browser on your phone and lets you control it by touch. It is
self-hosted and open source: one Python command on the computer, a web page on
the phone, a WireGuard tunnel in between. No account, no relay server, no open
router ports, no config files.

## Key features

- **Share one window, not your life.** Pick a single app and the phone sees
  only that. Close the app and the session ends.
- **You decide what is reachable.** On first run, choose all apps, a list of
  apps, or the full desktop, and how long a phone stays signed in.
- **Nothing to install on the phone.** It is a web page. iOS, Android, or
  another computer.
- **Two ways to control.** Touch the picture directly, or split the screen
  into picture plus trackpad with a draggable divider.
- **Desktop client too.** Open it from another computer and your mouse, wheel
  and keyboard pass straight through.
- **App View for Claude and Codex (Windows).** See the conversation as a native
  phone chat, read from the real window and wired to its real buttons.
- **Pinch to zoom, draw to point.** Zoom up to 8x and sketch over the picture
  without touching the computer.
- **Private by construction.** WebRTC with no STUN or TURN, bound to your
  Tailscale address, single-use PIN pairing, AES-256-GCM sign-in tokens.
- **CPU only.** Software capture and encoding; no CUDA or GPU compute context.

## Quick start

**You need:** Python 3.11 or newer on the computer (developed on 3.13), and
[Tailscale](https://tailscale.com/download) on both the computer and the phone,
signed in to the same account.

```bash
git clone https://github.com/theclasscoder-eng/PocketDesk.git
cd PocketDesk
python -m venv .venv
```

Install and run on **Windows**:

```bash
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pocketdesk
```

Install and run on **macOS or Linux**:

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pocketdesk
```

Then:

1. **Answer two questions** (first run only): how long a phone stays signed in
   (1 hour, 12 hours, 24 hours, or never), and what it may see (all apps, or a
   list you pick, with or without the full desktop).
2. **Scan the QR code** in the terminal with your phone. It holds only the
   address.
3. **Type the 6-digit PIN** shown in the terminal.
4. **Choose** Mobile or Desktop, then Default or Controlled.
5. **Tap a window or a display.** You are in.

Same Wi-Fi and no Tailscale? `python -m pocketdesk --lan` works, but read
[Hardening](#hardening) first.

## Configuration

There are no environment variables and no config file to write. Choices made
in the first-run questions are saved to `~/.pocketdesk/`; everything else is a
command-line flag.

| Flag | Default | What it does |
| --- | --- | --- |
| `--port` | `8765` | HTTP port |
| `--lan` | off | Also listen on the local network, not only Tailscale |
| `--fps` | `20` | Capture rate, 1 to 60 |
| `--max-width` | `1600` | Downscale wider frames; lower it to save bandwidth |
| `--view-only` | off | Stream, but ignore all input |
| `--no-pairing` | off | Refuse new sign-ins; phones already signed in still work |
| `--revoke-all` | | Forget every signed-in device |
| `--setup` | | Ask the first-run questions again |

| Saved file | Holds |
| --- | --- |
| `~/.pocketdesk/access.json` | Allowed apps, full-desktop permission, sign-in lifetime |
| `~/.pocketdesk/secret.key` | The AES-256 key that seals sign-in tokens |
| `~/.pocketdesk/devices.json` | Signed-in devices |

## Roadmap

- [x] Full-desktop and single-window streaming over WebRTC
- [x] PIN pairing, sign-in expiry, per-app allow list
- [x] Touch gestures, on-screen keyboard, sticky modifier keys
- [x] Controlled style with trackpad and resizable split
- [x] Desktop client with mouse and keyboard passthrough
- [x] Pinch zoom and on-screen drawing
- [x] App View for Claude on Windows
- [ ] Verify App View against the Codex app
- [ ] Run and fix the macOS and Linux backends on real machines
- [ ] Automated tests in CI (today: `python tests/smoke.py` by hand)
- [ ] App View on macOS (Accessibility API) and Linux (AT-SPI)
- [ ] Wayland capture and input through the desktop portal
- [ ] Built-in HTTPS so `--lan` pairing is encrypted
- [ ] Audio streaming
- [ ] Clipboard sync and file drop
- [ ] Multi-monitor switching mid-session
- [ ] Packaged installers (`pipx`, Windows `.exe`)

## Using it

### Device: Mobile or Desktop

The page first asks what you are using. **Mobile** is touch, as described
below. **Desktop** is for opening the page on another computer: its mouse,
wheel and keyboard are passed straight through.

| On Desktop | Result |
| --- | --- |
| Move, click, right-click, drag | the same on the remote computer |
| Wheel | scroll; with Ctrl held, zoom the local picture |
| Typing and shortcuts such as Ctrl+C | sent as typed |

Shortcuts the browser keeps for itself (Ctrl+W, Ctrl+T, Alt+Tab, the Windows
key) never reach the page; use the on-screen modifier keys for those. In the
Controlled style on Desktop the picture sits beside a panel you drag on with
the mouse, and the picture itself only pans.

### Control styles

After the device, the page asks which style to use, and the picker has
**Device** and **Control Style** rows to switch.

**Default** shows the picture full-size and you touch it directly, using the
gestures in the table below.

**Controlled** splits the phone in two: the picture in one half, a trackpad
with left and right buttons in the other (side by side in landscape). Drag
the bar between them to give either half more room; the phone remembers it. The
trackpad moves the pointer from where it is, like a laptop: tap to click,
two-finger tap to right-click, two-finger slide to scroll, and hold the left
button with one thumb while sliding to drag. The phone draws the pointer over
the picture, and when zoomed in the view follows it. On the picture itself,
one finger pans and a pinch zooms.

### App View for Claude and Codex (Windows)

When you tap a Claude or Codex window, the phone asks **App View** or
**Desktop View**. Desktop View is the live picture, as for any window. App
View shows the same conversation laid out as a phone chat app: your messages
in bubbles, replies as text, code blocks, a session drawer and a message box.
A button in the top bar switches to Desktop View at any time.

How it works: the host reads the window through Windows UI Automation, the
interface screen readers use ([pocketdesk/appview.py](pocketdesk/appview.py)).
Chromium-based apps expose their messages, session list, prompt box and
buttons there. The phone gets that as text, not pixels, and polls for changes.
Sending types into the app's real prompt box and presses Enter; chips and
drawer rows press the app's real buttons. Nothing is read from the network or
from the app's files.

Limits:

- Only what the desktop app has loaded is shown. Scrolling the chat on the
  phone scrolls the real app, and reaching the top asks it for earlier
  messages.
- Images, tables and diffs come through as plain text or not at all.
- The layout is styled after each app's mobile look but is not the official
  app, and uses no logos.
- The Codex profile is written against the same structure but has not been
  run against the Codex app.
- An app update that changes its accessibility labels can break the mapping;
  Desktop View always still works.

### Touch and keyboard (Default style)

| Gesture | Result |
| --- | --- |
| Tap | left click |
| Drag one finger | move the pointer |
| Hold, then drag | left-button drag (phone buzzes when the button goes down) |
| Two-finger tap | right click |
| Two-finger drag | scroll wheel, vertical and horizontal |
| Pinch | zoom the picture on the phone only, up to 8x; keep two fingers down to pan |

Zoom never changes anything on the computer. While zoomed, pushing the pointer
against an edge slides the view, and the badge in the corner resets to 1x. The
picture re-fits when you rotate the phone or the keyboard opens.

The pencil button turns on drawing: one finger draws in red over the picture,
with Undo and Clear in the corner. Drawings exist only on the phone, are never
sent to the computer, stay in place when you zoom or pan, and are erased when
you leave the session. While the pencil is on, touches on the picture do not
click; two fingers still zoom.

The keyboard button toggles the phone's own keyboard. Ctrl, Alt, Shift and Cmd
are sticky: tap one, then a key, to send a chord such as Ctrl+C. After each
click the host checks whether a text field took focus and, if so, asks the
phone to open the keyboard. Browsers only open the keyboard in response to a
touch, so when the phone refuses, the keyboard button lights up instead.

## Architecture

```
 Phone (browser)                                   Computer (python -m pocketdesk)
+----------------------+                          +--------------------------------+
| pair / pick source   | -- HTTP: PIN, SDP -----> | aiohttp: /api/pair /api/offer  |
|                      |                          |   auth.py   PIN, AES-GCM token |
| <video>              | <== SRTP video ========= | capture.py  mss / PrintWindow  |
|                      |                          |             -> VP8/H.264 (CPU) |
| touch + keyboard     | == DataChannel JSON ===> | inject.py   pynput mouse/keys  |
+----------------------+                          +--------------------------------+
            \_______________ Tailscale / WireGuard tunnel ______________/
```

**Why WebRTC and not a WebSocket of JPEGs.** A media track gives inter-frame
compression (a mostly static desktop costs almost nothing), congestion control
and jitter handling for free, and every phone browser decodes it in hardware.
Input rides a DataChannel on the same connection, so there is one encrypted
session to authenticate and tear down.

**Why no STUN/TURN.** Both peers pass an empty ICE server list. The only
candidates are the machines' own addresses, so media flows straight over the
tunnel and no third-party server ever sees an address or a packet. NAT
traversal is Tailscale's job.

**Coordinates.** The phone sends positions as fractions (0..1) of the video
picture as it is currently zoomed and panned (`toStream` in
[client/app.js](client/app.js)). The host maps them onto the captured
rectangle: `X = left + x * (width - 1)` (`Session.point` in
[pocketdesk/server.py](pocketdesk/server.py)). The phone never needs to know
the desktop resolution, and in single-window mode a touch cannot land outside
the window.

**Capture modes.**

| | Full desktop | Single window |
| --- | --- | --- |
| Windows | mss (GDI BitBlt) | `PrintWindow` on the `HWND`; works while covered |
| macOS | mss (CoreGraphics) | `CGWindowListCreateImage` on the `CGWindowID` |
| Linux X11 | mss (XGetImage) | window geometry from Xlib, pixels from the root window; the window must be visible |

**CPU only.** Frames come from the OS screen APIs above and are encoded by
libvpx/x264 in software. The process never creates a CUDA context, and sets
`CUDA_VISIBLE_DEVICES` to empty at start so nothing it loads can.

### Files

| Path | Role |
| --- | --- |
| [pocketdesk/__main__.py](pocketdesk/__main__.py) | CLI, picks bind addresses, prints PIN and QR |
| [pocketdesk/server.py](pocketdesk/server.py) | HTTP API, WebRTC session, input dispatch |
| [pocketdesk/auth.py](pocketdesk/auth.py) | PIN pairing, AES-256-GCM device tokens |
| [pocketdesk/capture.py](pocketdesk/capture.py) | screen source and the video track |
| [pocketdesk/inject.py](pocketdesk/inject.py) | mouse and keyboard emulation |
| [pocketdesk/backends/](pocketdesk/backends/) | per-OS window capture and text-focus detection |
| [pocketdesk/access.py](pocketdesk/access.py) | first-run questions: allowed apps, sign-in lifetime |
| [pocketdesk/appview.py](pocketdesk/appview.py) | App View: reads a chat app through UI Automation |
| [client/](client/) | the phone web app |
| [tests/smoke.py](tests/smoke.py) | end-to-end test, no phone needed |

## Hardening

What protects a session:

1. **Tunnel.** WireGuard encrypts everything between phone and computer. By
   default the agent binds to `127.0.0.1` and the Tailscale address only, so
   devices on your Wi-Fi cannot even reach the port.
2. **Pairing.** A random 6-digit PIN, single use, valid 10 minutes. Five wrong
   attempts rotate the PIN and lock pairing for a minute.
   The PIN is never in the QR code, so scanning alone cannot pair.
3. **App limit.** If you chose "only the apps I choose", the full desktop is
   never offered and the host refuses any window that does not belong to one
   of those apps, whatever the phone asks for. The choice is stored by app
   name in `~/.pocketdesk/access.json`.
4. **Token.** Pairing returns an AES-256-GCM sealed token (key in
   `~/.pocketdesk/secret.key`), valid for the sign-in time you chose. Every API call and every WebRTC
   offer needs it; `--revoke-all` kills all of them.
5. **Session.** Video is SRTP and input is DTLS, keyed per connection. One
   controller at a time: a new connection replaces the old one.
6. **Browser.** Cross-origin POSTs are refused and the page ships a strict
   Content-Security-Policy.

How long a phone stays signed in is your choice, asked on first run along with
the app question: **1 hour, 12 hours, 24 hours, or never expires**. The
computer enforces it; once the time is up the phone is sent back to the PIN
screen. "Sign Out" on the phone forgets the sign-in early, and `--revoke-all`
ends every sign-in at once. Pick "never expires" only for a phone you keep
locked: anyone holding it can then open your computer without the PIN.

Once your phone is signed in you can refuse all new sign-ins with
`--no-pairing`.

Checks you can run:

```bash
python tests/smoke.py
```

This confirms that unpaired, wrong-PIN, reused-PIN, forged-token and
cross-origin requests are refused, then pulls real frames for both modes. It
runs view-only and does not touch your mouse.

- Confirm the bind: the first line of output lists the addresses. Without
  `--lan` it must be `127.0.0.1` plus a `100.x.y.z` address, nothing else.
- Confirm no GPU compute: run `nvidia-smi` while streaming; `python` must not
  appear in the process list.
- Lock down the tailnet: in the Tailscale admin console, add an ACL that lets
  only your phone reach this computer on port 8765.

### Know the limits

- **`--lan` is plain HTTP.** Video and input are still encrypted by WebRTC, but
  the PIN, the token and the SDP exchange are not, so someone on the same
  network could intercept them and take over. Use it only on a network you
  trust, or put `tailscale serve` or another HTTPS proxy in front.
- **Single-window mode ends with the window.** When the shared window closes
  (or hides to the tray), the host tells the phone and drops the whole
  session. On Windows, clicks, keys and scrolling are also discarded whenever
  that window, or a dialog it owns, is not in the foreground.
- **It is still not a sandbox.** A shortcut typed into the shared window, such
  as Win+R or Alt+Tab, is handled by the system, and whatever the app itself
  can do (open files, run commands) the phone can do. Anyone you pair has the
  power of someone sitting at that window. On macOS and Linux the foreground
  check is not implemented, so keep the shared window in front yourself.
- **Elevated windows (Windows).** A normal process cannot send input to an
  administrator window or the UAC prompt.
- **Keyboard auto-open** is implemented on Windows only (system caret, with an
  I-beam cursor fallback for browsers and Electron apps).
- **macOS** needs Screen Recording and Accessibility permission for the
  terminal running the agent. **Wayland** without XWayland is not supported.
- **Tested on Windows 11.** The macOS and Linux backends are written to the
  documented APIs but have not been run yet; reports welcome.

## Contributing

Bug reports, fixes and new backends are welcome, and the macOS and Linux
backends especially need people who can run them. Start with
[CONTRIBUTING.md](CONTRIBUTING.md); issues tagged `good first issue` are
scoped to be approachable.

## License

[MIT](LICENSE). Use it, change it, ship it.

PocketDesk is an independent project. It is not affiliated with or endorsed by
Anthropic, OpenAI or Tailscale; their product names are used only to describe
what it works with.
