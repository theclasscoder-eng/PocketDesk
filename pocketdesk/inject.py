"""Virtual mouse and keyboard, via pynput (SendInput / Quartz / XTest)."""

_KEY_NAMES = {
    "Enter": "enter", "Backspace": "backspace", "Tab": "tab", "Escape": "esc",
    "Delete": "delete", "ArrowUp": "up", "ArrowDown": "down",
    "ArrowLeft": "left", "ArrowRight": "right", "Home": "home", "End": "end",
    "PageUp": "page_up", "PageDown": "page_down", " ": "space",
    **{f"F{i}": f"f{i}" for i in range(1, 13)},
}
_MOD_NAMES = {"ctrl": "ctrl", "alt": "alt", "shift": "shift", "meta": "cmd"}
MAX_TEXT = 512


class Injector:
    def __init__(self):
        # Imported here so a host with no display can still run view-only.
        from pynput import keyboard, mouse

        self._mouse = mouse.Controller()
        self._kb = keyboard.Controller()
        self._buttons = {"left": mouse.Button.left, "right": mouse.Button.right,
                         "middle": mouse.Button.middle}
        self._keys = {k: getattr(keyboard.Key, v) for k, v in _KEY_NAMES.items()}
        self._mods = {k: getattr(keyboard.Key, v) for k, v in _MOD_NAMES.items()}
        self._enter = keyboard.Key.enter
        self._held = set()

    def position(self):
        x, y = self._mouse.position
        return int(x), int(y)

    def move(self, x: int, y: int):
        self._mouse.position = (x, y)

    def button(self, name: str, down: bool):
        btn = self._buttons.get(name)
        if btn is None:
            return
        if down:
            self._mouse.press(btn)
            self._held.add(btn)
        else:
            self._mouse.release(btn)
            self._held.discard(btn)

    def click(self, name: str):
        btn = self._buttons.get(name)
        if btn is not None:
            self._mouse.click(btn)

    def scroll(self, dx: int, dy: int):
        self._mouse.scroll(dx, dy)

    def key(self, name, mods=()):
        if not isinstance(name, str):
            return
        key = self._keys.get(name)
        if key is None:
            if len(name) != 1 or not name.isprintable():
                return
            key = name.lower() if mods else name
        held = [self._mods[m] for m in mods if isinstance(m, str) and m in self._mods]
        for m in held:
            self._kb.press(m)
        try:
            self._kb.press(key)
            self._kb.release(key)
        finally:
            for m in reversed(held):
                self._kb.release(m)

    def text(self, s):
        if not isinstance(s, str):
            return
        parts = s[:MAX_TEXT].replace("\r", "").split("\n")
        for i, part in enumerate(parts):
            if i:
                self._kb.press(self._enter)
                self._kb.release(self._enter)
            clean = "".join(c for c in part if c.isprintable() or c == "\t")
            if clean:
                self._kb.type(clean)

    def release_all(self):
        for btn in list(self._held):
            self._mouse.release(btn)
        self._held.clear()
