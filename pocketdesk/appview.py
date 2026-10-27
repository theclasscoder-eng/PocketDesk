"""App view: read a chat app's window as structured data instead of pixels.

Electron apps such as Claude and Codex expose their whole interface through
Windows UI Automation (the screen-reader API): the session list, every
message, the prompt box and each button. This module turns that tree into a
small JSON model the phone renders natively, and maps taps back to the real
controls. Nothing is scraped from the network; it is the same information a
screen reader gets from the window on this computer.

Windows only for now.
"""

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

MAX_NODES = 6000
MAX_MESSAGES = 60
MAX_TEXT = 6000
ARIA_ROLE = 30101  # UIA_AriaRolePropertyId
SAID = re.compile(r"^(.{1,40}?) said:\s*", re.S)
HINTS = re.compile(r"^(Use the up and down arrow keys|[\w .]{1,30} responded:)")

# Apps that get an app-style view, matched against the executable name.
PROFILES = (("claude", "claude"), ("codex", "codex"), ("chatgpt", "codex"))

# UI Automation is COM: every call has to come from one initialised thread.
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="appview")
_auto = None
_refs = {}  # hwnd -> {ref: control} from the latest snapshot


def available() -> bool:
    return sys.platform == "win32"


def profile_for(app_name: str):
    name = (app_name or "").lower()
    for needle, profile in PROFILES:
        if needle in name:
            return profile
    return None


def _uia():
    global _auto
    if _auto is None:
        import uiautomation
        uiautomation.SetGlobalSearchTimeout(1)
        _uia.keep = uiautomation.UIAutomationInitializerInThread()
        _auto = uiautomation
    return _auto


class Node:
    __slots__ = ("ctrl", "type", "role", "name", "kids", "has_text", "has_copy")

    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.type = ctrl.ControlTypeName.replace("Control", "")
        self.name = ctrl.Name or ""
        try:
            self.role = ctrl.GetPropertyValue(ARIA_ROLE) or ""
        except Exception:
            self.role = ""
        self.kids = []
        self.has_text = self.type == "Text" and bool(self.name.strip())
        self.has_copy = self.type == "Button" and self.name.lower().startswith("copy code")


def _build(ctrl, budget):
    node = Node(ctrl)
    if node.type == "Text":
        return node  # a text node's name already holds everything under it
    try:
        children = ctrl.GetChildren()
    except Exception:
        children = []
    for child in children:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        try:
            kid = _build(child, budget)
        except Exception:
            continue
        node.kids.append(kid)
        node.has_text |= kid.has_text
        node.has_copy |= kid.has_copy
    return node


def _find(node, pred):
    if pred(node):
        return node
    for kid in node.kids:
        hit = _find(kid, pred)
        if hit:
            return hit
    return None


def _all(node, pred, out=None, skip=None):
    out = [] if out is None else out
    if skip and skip(node):
        return out
    if pred(node):
        out.append(node)
    for kid in node.kids:
        _all(kid, pred, out, skip)
    return out


def _text(node):
    """All readable text under a node, in reading order, without buttons."""
    if node.type == "Text":
        return node.name
    if node.type in ("Button", "ToolBar"):
        return ""
    return "".join(_text(k) for k in node.kids)


def _clean(text):
    return re.sub(r"[ \t ]+", " ", text).strip()[:MAX_TEXT]


def _remember(refs, ctrl):
    """Give a control an id that stays the same from one snapshot to the next.

    The phone taps things it drew from an earlier snapshot, so ids must not
    depend on how many other controls happen to exist right now.
    """
    try:
        key = "r" + ".".join(str(part) for part in ctrl.GetRuntimeId())
    except Exception:
        key = ""
    if len(key) < 2 or key in refs:
        key = f"n{len(refs)}"
    refs[key] = ctrl
    return key


class _Feed:
    """Turns the message area into [{role, blocks}]."""

    def __init__(self, refs):
        self.refs = refs
        self.messages = []
        self.role = "assistant"

    def _message(self, role):
        if not self.messages or self.messages[-1]["role"] != role:
            self.messages.append({"role": role, "blocks": []})
        return self.messages[-1]

    def _add(self, kind, text, **extra):
        text = _clean(text) if kind != "code" else text.strip()[:MAX_TEXT]
        if not text or text == "running" or HINTS.match(text):
            return  # empty, or a line meant only for screen-reader users
        blocks = self._message(self.role)["blocks"]
        if text not in [b["t"] for b in blocks[-3:]]:  # live regions repeat themselves
            blocks.append({"k": kind, "t": text, **extra})

    def walk(self, node):
        if node.type == "ToolBar":
            return  # per-message copy/retry icons
        if node.role == "article":
            heading = _find(node, lambda n: n.role == "heading")
            said = SAID.match(heading.name) if heading else None
            if said:
                # Screen-reader heading: "You said: ..." or "<App> said: ...".
                self.role = "user" if said.group(1).lower() == "you" else "assistant"
                if self.role == "user":
                    # The heading can be cut short, so read the body and keep
                    # the heading only as a fallback.
                    message = {"role": "user", "blocks": []}
                    self.messages.append(message)
                    for kid in node.kids:
                        if kid is not heading:
                            self.walk(kid)
                    if not message["blocks"]:
                        message["blocks"].append(
                            {"k": "p", "t": _clean(heading.name[said.end():])})
                    self.messages.append({"role": "assistant", "blocks": []})
                    self.role = "assistant"
                    return
        if node.type == "Button":
            return
        if node.role == "heading":
            if not SAID.match(node.name):
                self._add("h", node.name)
            return
        if node.type == "List":
            for item in node.kids:
                if item.type == "ListItem":
                    button = _find(item, lambda n: n.type == "Button" and n.name)
                    label = re.sub(r"^\s*(•|\d+\.)\s*", "", item.name or _text(item))
                    extra = {"ref": self._ref(button)} if button else {}
                    self._add("li", label, **extra)
                else:
                    self.walk(item)
            return
        if node.has_copy and not any(k.has_copy and k.has_text for k in node.kids):
            self._add("code", _text(node))
            return
        if node.type == "Text":
            self._add("p", node.name)
            return
        if any(k.type == "Text" and k.name.strip() for k in node.kids):
            self._add("p", _text(node))  # a paragraph and its inline spans
            return
        for kid in node.kids:
            self.walk(kid)

    def _ref(self, node):
        return _remember(self.refs, node.ctrl)


def _snapshot(hwnd):
    auto = _uia()
    root = _build(auto.ControlFromHandle(hwnd), [MAX_NODES])
    refs = {}

    def ref(node):
        return _remember(refs, node.ctrl)

    def wide(node, least=90):
        # Icon-only buttons are narrow; the ones worth showing carry a label.
        try:
            return node.ctrl.BoundingRectangle.width() >= least
        except Exception:
            return False

    doc = _find(root, lambda n: n.type == "Document" and n.name)
    main = _find(root, lambda n: n.role == "main") or root
    feed_node = _find(main, lambda n: n.role in ("feed", "log")) or main
    side = _find(root, lambda n: n.role in ("complementary", "navigation"))

    feed = _Feed(refs)
    for kid in feed_node.kids:
        feed.walk(kid)
    messages = [m for m in feed.messages if m["blocks"]][-MAX_MESSAGES:]

    # Everything in the main area that is a button but not part of a message:
    # Stop, model picker, permission mode, Allow / Deny prompts...
    in_feed = lambda n: n is feed_node or n.type == "ToolBar"
    buttons = _all(main, lambda n: n.type == "Button" and n.name.strip(), skip=in_feed)
    stop = next((b for b in buttons if b.name.strip().lower() in ("stop", "stop generating",
                                                                   "stop streaming")), None)
    controls = [{"ref": ref(b), "label": _clean(b.name)[:34]}
                for b in buttons if b is not stop and wide(b, 34)][:14]

    nav = []
    if side:
        for b in _all(side, lambda n: n.type == "Button" and n.name.strip()):
            if not wide(b):
                continue
            item = {"ref": ref(b), "label": _clean(b.name)[:60]}
            # Folders expand in place instead of opening anything.
            try:
                fold = b.ctrl.GetPattern(auto.PatternId.ExpandCollapsePattern)
                if fold:
                    item["group"] = True
                    item["open"] = fold.ExpandCollapseState != 0
            except Exception:
                pass
            nav.append(item)
    box = None
    for n in _all(main, lambda n: n.type == "Edit" or n.role == "textbox"):
        box = n
    if box:
        refs["composer"] = box.ctrl
    # The element that actually scrolls the message list, and the app's own
    # "load earlier" button, so the phone can drive both.
    earlier = _find(feed_node, lambda n: n.type == "Button"
                    and n.name.lower().startswith(("load earlier", "load more", "show earlier")))
    ctrl = feed_node.ctrl
    for _ in range(8):
        try:
            pattern = ctrl.GetPattern(auto.PatternId.ScrollPattern)
            if pattern and pattern.VerticallyScrollable:
                refs["scroller"] = pattern
                break
            ctrl = ctrl.GetParentControl()
        except Exception:
            break
        if ctrl is None:
            break
    busy = bool(stop) or bool(_find(main, lambda n: n.type == "Text"
                                    and n.name.strip().lower().endswith("is responding")))
    model = {
        "title": re.sub(r"\s+[-–—]\s+\w+\s*$", "", _clean(doc.name))[:80] if doc else "",
        "messages": messages,
        "controls": controls,
        "nav": nav[:60],
        "busy": busy,
        "stop": ref(stop) if stop else None,
        "earlier": ref(earlier) if earlier else None,
        "placeholder": _clean(box.name)[:40] if box else "",
        "canType": box is not None,
        # Chromium only fills its accessibility tree after the first request.
        "ready": doc is not None and (bool(messages) or box is not None),
    }
    stable = {k: v for k, v in model.items()}
    model["v"] = hashlib.sha1(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:12]
    _refs[hwnd] = refs
    return model


def _press(hwnd, ref):
    auto = _uia()
    ctrl = _refs.get(hwnd, {}).get(ref)
    if ctrl is None or ref in ("composer", "scroller"):
        return False
    try:
        fold = ctrl.GetPattern(auto.PatternId.ExpandCollapsePattern)
        if fold:
            fold.Expand() if fold.ExpandCollapseState == 0 else fold.Collapse()
            return True
    except Exception:
        pass
    for pattern_id, method in ((auto.PatternId.InvokePattern, "Invoke"),
                               (auto.PatternId.SelectionItemPattern, "Select"),
                               (auto.PatternId.TogglePattern, "Toggle")):
        try:
            pattern = ctrl.GetPattern(pattern_id)
            if pattern:
                getattr(pattern, method)()
                return True
        except Exception:
            continue
    return False


def _focus_composer(hwnd):
    """Returns (has focus, centre of the box on screen or None)."""
    ctrl = _refs.get(hwnd, {}).get("composer")
    if ctrl is None:
        _snapshot(hwnd)  # the page may have re-rendered since the last poll
        ctrl = _refs.get(hwnd, {}).get("composer")
        if ctrl is None:
            return False, None
    centre = None
    try:
        r = ctrl.BoundingRectangle
        if r.width() > 0 and r.height() > 0:
            centre = (r.left + r.width() // 2, r.top + r.height() // 2)
        ctrl.SetFocus()
        for _ in range(8):  # focus lands a moment after the call returns
            if ctrl.HasKeyboardFocus:
                return True, centre
            time.sleep(0.05)
    except Exception:
        pass
    return False, centre


def _scroll(hwnd, position):
    """Scroll the app's own message list: 0 is the top, 1 the newest message."""
    pattern = _refs.get(hwnd, {}).get("scroller")
    if pattern is None:
        return False
    try:
        pattern.SetScrollPercent(-1, min(max(position, 0.0), 1.0) * 100)  # -1: leave horizontal
        return True
    except Exception:
        return False


def _has_focus(hwnd):
    ctrl = _refs.get(hwnd, {}).get("composer")
    try:
        return bool(ctrl is not None and ctrl.HasKeyboardFocus)
    except Exception:
        return False


async def _run(loop, fn, *args):
    return await loop.run_in_executor(_pool, fn, *args)


async def snapshot(loop, hwnd):
    return await _run(loop, _snapshot, hwnd)


async def press(loop, hwnd, ref):
    return await _run(loop, _press, hwnd, ref)


async def focus_composer(loop, hwnd):
    return await _run(loop, _focus_composer, hwnd)


async def scroll(loop, hwnd, position):
    return await _run(loop, _scroll, hwnd, position)


async def has_focus(loop, hwnd):
    return await _run(loop, _has_focus, hwnd)
