"""Linux X11 backend: window geometry from Xlib, pixels from the root window.

The window is captured from the screen, so it has to be visible (not
covered or minimised) while it is being streamed.
"""

import mss
import numpy as np
from Xlib import X, display, error

from . import SourceGone


def _title(dpy, win):
    for atom in ("_NET_WM_NAME", "WM_NAME"):
        try:
            prop = win.get_full_property(dpy.intern_atom(atom), X.AnyPropertyType)
        except error.XError:
            return ""
        if prop and prop.value:
            v = prop.value
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
    return ""


def list_windows():
    dpy = display.Display()
    try:
        root = dpy.screen().root
        prop = root.get_full_property(dpy.intern_atom("_NET_CLIENT_LIST"),
                                      X.AnyPropertyType)
        out = []
        for wid in (prop.value if prop else []):
            win = dpy.create_resource_object("window", int(wid))
            title = _title(dpy, win)
            if title:
                try:
                    cls = win.get_wm_class()
                except error.XError:
                    cls = None
                out.append({"id": int(wid), "title": title,
                            "app": cls[1] if cls else ""})
        return out
    finally:
        dpy.close()


class WindowSource:
    def __init__(self, window_id: int):
        self.window_id = window_id
        self.rect = (0, 0, 2, 2)
        self._dpy = None
        self._sct = None
        self._last = np.zeros((2, 2, 4), np.uint8)

    def grab(self):
        # Created lazily: both handles must live on the capture thread.
        if self._dpy is None:
            self._dpy = display.Display()
            self._sct = mss.mss()
        root = self._dpy.screen().root
        try:
            win = self._dpy.create_resource_object("window", self.window_id)
            geo = win.get_geometry()
            pos = root.translate_coords(win, 0, 0)
        except error.XError:
            raise SourceGone("Window closed")
        screen = self._dpy.screen()
        left, top = max(pos.x, 0), max(pos.y, 0)
        right = min(pos.x + geo.width, screen.width_in_pixels)
        bottom = min(pos.y + geo.height, screen.height_in_pixels)
        if right - left < 2 or bottom - top < 2:
            return self._last
        self.rect = (left, top, right - left, bottom - top)
        shot = self._sct.grab({"left": left, "top": top,
                               "width": right - left, "height": bottom - top})
        arr = np.frombuffer(shot.raw, np.uint8).reshape(shot.height, shot.width, 4)
        self._last = arr
        return arr

    def focus(self):
        pass

    def is_foreground(self):
        return True

    def close(self):
        if self._sct:
            self._sct.close()
        if self._dpy:
            self._dpy.close()


def text_focus():
    return None
