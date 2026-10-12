# Contributing to PocketDesk

Thanks for looking. PocketDesk is small enough to read in an afternoon, and
there is real work a newcomer can pick up. This page covers reporting bugs,
suggesting features and sending pull requests.

## Where help is needed most

- **macOS and Linux.** Both backends are written to the documented APIs but
  have never been run. If you have either machine, running
  `python tests/smoke.py` and reporting what happens is a genuine contribution.
- **Codex App View.** The profile exists but has not been run against the
  Codex app.
- **Anything tagged [`good first issue`](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).**
  These are scoped to one file or one behaviour and say where to start.
  Comment on the issue before you begin so two people do not do the same work.

## Reporting a bug

Open an issue with the **Bug report** template. It asks for steps to
reproduce, what you expected, what happened, and your environment. The two
details that most often decide whether a bug can be fixed:

- the **host OS** and the **phone or browser**, with versions
- whether it happens in **Desktop View, App View, or both**

Include the terminal output from the agent if there is any. Remove the PIN and
any `100.x.y.z` address before posting.

**Security problems:** do not open a public issue. Use GitHub's "Report a
vulnerability" button on the Security tab so it can be fixed before it is
disclosed.

## Suggesting a feature

Open an issue and describe the problem first, then the idea: what were you
trying to do, and what got in the way? Check the
[roadmap](README.md#roadmap) in case it is already planned. Features that
widen what a paired phone can reach will be asked how they stay safe by
default.

## Setting up

```bash
git clone https://github.com/theclasscoder-eng/PocketDesk.git
cd PocketDesk
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
```

Run the agent without letting it touch your mouse or keyboard:

```bash
.venv/Scripts/python -m pocketdesk --view-only
```

Run the end-to-end test. It pairs, streams real frames from a display and a
window, closes a window to check the session ends, and checks the app allow
list. It is view-only and takes about 20 seconds:

```bash
.venv/Scripts/python tests/smoke.py
```

## Where things live

| Path | What it does |
| --- | --- |
| `pocketdesk/__main__.py` | Command line, bind addresses, PIN and QR output |
| `pocketdesk/server.py` | HTTP API, WebRTC session, input dispatch |
| `pocketdesk/auth.py` | PIN pairing and sign-in tokens |
| `pocketdesk/access.py` | First-run questions and the saved answers |
| `pocketdesk/capture.py` | Screen capture and the video track |
| `pocketdesk/inject.py` | Mouse and keyboard emulation |
| `pocketdesk/backends/` | One file per OS: window list, window capture, focus |
| `pocketdesk/appview.py` | App View: reads a chat app through UI Automation |
| `client/` | The web client: one HTML file, one stylesheet, one script |

Adding an OS means adding one file in `pocketdesk/backends/` with
`list_windows()`, a `WindowSource` class and `text_focus()`. The docstring in
`pocketdesk/backends/__init__.py` lists the exact interface.

## Sending a pull request

1. Fork the repository and branch from `main`: `git checkout -b fix-scroll-jump`.
2. Keep the change to one thing. A bug fix and a refactor are two pull requests.
3. Match the code around you: the same naming, comment density and style. The
   client is plain JavaScript with no build step and no framework; please keep
   it that way.
4. Run `python tests/smoke.py` and say in the pull request that it passed, and
   on which OS.
5. Say what you tested by hand, and what you could not test. "Untested on
   macOS" is useful; silence is not.
6. If the change alters what a user sees or types, update `README.md` in the
   same pull request.

### Changes that touch security

Pairing, tokens, the app allow list, the bind address and input injection
decide who can control someone's computer. For changes there:

- explain what an attacker on the same network, and a paired phone, could do
  before and after
- never widen the default: new reach must be something the host owner turns on
- add a check to `tests/smoke.py` that fails without your change

## Conduct

Be kind and be specific. Critique code, not people. Assume the other person
has less context than you, and explain accordingly.

## License

By contributing you agree that your work is released under the
[MIT License](LICENSE).
