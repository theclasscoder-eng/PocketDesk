"""What paired phones may see: everything, or only chosen apps.

Asked once in the terminal on first run and saved to ~/.pocketdesk/access.json.
Apps are remembered by name (chrome, Code, Terminal...), so the choice still
holds after the app is restarted.
"""

import json
import sys
from pathlib import Path


def _path(state_dir: Path) -> Path:
    return state_dir / "access.json"


def load(state_dir: Path):
    """Return None when never configured, else a frozenset of app names,
    or the string "all"."""
    data = _read(state_dir)
    if data.get("mode") == "limited":
        return frozenset(a.lower() for a in data.get("apps", []))
    return "all" if data.get("mode") == "all" else None


def _read(state_dir: Path) -> dict:
    try:
        return json.loads(_path(state_dir).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _write(state_dir: Path, **changes):
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {**_read(state_dir), **changes}
    _path(state_dir).write_text(json.dumps(data, indent=2), "utf-8")


def _save(state_dir: Path, apps):
    if apps == "all":
        _write(state_dir, mode="all", apps=[], desktop=True)
    else:
        _write(state_dir, mode="limited", apps=sorted(apps), desktop=False)


# How long a phone stays signed in before the PIN is needed again.
EXPIRY_CHOICES = [(1, "1 hour"), (12, "12 hours"), (24, "24 hours"), (0, "Never expires")]
DEFAULT_EXPIRY = 12
UNSET = object()


def load_expiry(state_dir: Path):
    """Hours a sign-in lasts, 0 for no limit, or UNSET when never chosen."""
    hours = _read(state_dir).get("expiry_hours")
    return hours if hours in (h for h, _ in EXPIRY_CHOICES) else UNSET


def describe_expiry(hours) -> str:
    return dict(EXPIRY_CHOICES)[hours].lower()


def ask_expiry(state_dir: Path):
    if sys.stdin and sys.stdin.isatty():
        print("\nHow long should a phone stay signed in before it needs the PIN again?")
        for i, (_, label) in enumerate(EXPIRY_CHOICES, 1):
            print(f"  {i}  {label}")
        try:
            while True:
                choice = input(f"Choose 1-{len(EXPIRY_CHOICES)}: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(EXPIRY_CHOICES):
                    hours = EXPIRY_CHOICES[int(choice) - 1][0]
                    _write(state_dir, expiry_hours=hours)
                    return hours
        except EOFError:
            print()
    return DEFAULT_EXPIRY


def describe(apps) -> str:
    if apps == "all":
        return "all apps and the full desktop"
    if not apps:
        return "nothing (no apps selected)"
    return "only " + ", ".join(sorted(apps))


def allowed(apps, window) -> bool:
    return apps == "all" or window.get("app", "").lower() in apps


def ask(state_dir: Path, backend):
    """Interactive first-run question. Returns the chosen policy."""
    if sys.stdin and sys.stdin.isatty():
        try:
            return _ask(state_dir, backend)
        except EOFError:
            print()
    print("No terminal to ask in, so access is not limited for this run.\n"
          "Run `python -m pocketdesk --setup` in a terminal to choose.")
    return "all"


def _ask(state_dir: Path, backend):
    print("\nWhat can a paired phone see and control?\n"
          "  1  All apps and the full desktop\n"
          "  2  Only the apps I choose")
    while True:
        choice = input("Choose 1 or 2: ").strip()
        if choice in ("1", "2"):
            break
    if choice == "1":
        _save(state_dir, "all")
        return "all"

    running = sorted({w["app"] for w in (backend.list_windows() if backend else [])
                      if w.get("app")}, key=str.lower)
    if not running:
        print("No open apps were found. Open the ones you want, then run --setup.")
        _save(state_dir, frozenset())
        return frozenset()
    print("\nOpen apps:")
    for i, name in enumerate(running, 1):
        print(f"  {i:>2}  {name}")
    while True:
        raw = input("Numbers to allow, separated by commas (e.g. 1,3): ")
        try:
            picks = {int(p) for p in raw.replace(" ", "").split(",") if p}
        except ValueError:
            continue
        if picks and all(1 <= p <= len(running) for p in picks):
            break
    apps = frozenset(running[p - 1].lower() for p in picks)
    _save(state_dir, apps)
    print("\nAlso offer the full desktop? It shows and controls the entire computer,\n"
          "not just the apps above.")
    while True:
        answer = input("Allow full desktop? y/n: ").strip().lower()
        if answer in ("y", "yes", "n", "no"):
            break
    _write(state_dir, desktop=answer.startswith("y"))
    return apps


def desktop_allowed(state_dir: Path, apps) -> bool:
    """Whole displays are offered with "all", or when chosen alongside a list."""
    return apps == "all" or bool(_read(state_dir).get("desktop"))


def describe_all(state_dir: Path, apps) -> str:
    if apps != "all" and desktop_allowed(state_dir, apps):
        return describe(apps).replace("only ", "") + ", plus the full desktop"
    return describe(apps)
