"""macOS backend: CGWindowID capture via Quartz.

Needs Screen Recording permission for capture and Accessibility permission
for input (System Settings > Privacy & Security).
"""

import numpy as np
import Quartz

from . import SourceGone


def _info(window_id=None):
    if window_id is None:
        opts = (Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements)
        return Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []
    return Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionIncludingWindow, window_id) or []


def list_windows():
    out = []
    for w in _info():
        if w.get(Quartz.kCGWindowLayer, 0) != 0:
            continue
        owner = w.get(Quartz.kCGWindowOwnerName, "")
        name = w.get(Quartz.kCGWindowName, "")
        title = f"{owner} - {name}" if name else owner
        if title:
            out.append({"id": int(w[Quartz.kCGWindowNumber]), "title": title,
                        "app": owner})
    return out


class WindowSource:
    def __init__(self, window_id: int):
        self.window_id = window_id
        self.rect = (0, 0, 2, 2)
        self._last = np.zeros((2, 2, 4), np.uint8)
        if not _info(window_id):
            raise SourceGone("No such window")

    def grab(self):
        info = _info(self.window_id)
        if not info:
            raise SourceGone("Window closed")
        b = info[0][Quartz.kCGWindowBounds]
        # Bounds are in points, the same unit pynput injects in.
        self.rect = (int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"]))
        img = Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow,
            self.window_id,
            Quartz.kCGWindowImageBoundsIgnoreFraming
            | Quartz.kCGWindowImageNominalResolution)
        if img is None:
            return self._last
        w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
        if w < 2 or h < 2:
            return self._last
        stride = Quartz.CGImageGetBytesPerRow(img)
        data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
        arr = np.frombuffer(data, np.uint8).reshape(h, stride // 4, 4)[:, :w]
        self._last = arr
        return arr

    def focus(self):
        pass  # raising another app's window needs the Accessibility API

    def is_foreground(self):
        return True  # not detectable without the Accessibility API

    def close(self):
        pass


def text_focus():
    return None
