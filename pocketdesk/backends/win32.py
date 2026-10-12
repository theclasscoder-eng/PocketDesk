"""Windows backend: HWND capture with PrintWindow, caret and I-beam inspection."""

import ctypes
import os
import time
from ctypes import wintypes

import numpy as np

from . import SourceGone

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Capture, window rects and injected coordinates must all be physical pixels.
try:
    ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
except OSError:
    user32.SetProcessDPIAware()

PW_RENDERFULLCONTENT = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80
SW_RESTORE = 9
SW_MINIMIZE = 6
GUI_CARETBLINKING = 0x1
IDC_IBEAM = 32513
GA_ROOTOWNER = 3
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x2
H = ctypes.c_void_p


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", H), ("hwndFocus", H), ("hwndCapture", H),
                ("hwndMenuOwner", H), ("hwndMoveSize", H), ("hwndCaret", H),
                ("rcCaret", wintypes.RECT)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hCursor", H), ("ptScreenPos", wintypes.POINT)]


def _sig(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = argtypes


_ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, H, wintypes.LPARAM)
_sig(user32.EnumWindows, wintypes.BOOL, _ENUM, wintypes.LPARAM)
_sig(user32.IsWindow, wintypes.BOOL, H)
_sig(user32.IsWindowVisible, wintypes.BOOL, H)
_sig(user32.IsIconic, wintypes.BOOL, H)
_sig(user32.GetWindowTextLengthW, ctypes.c_int, H)
_sig(user32.GetWindowTextW, ctypes.c_int, H, wintypes.LPWSTR, ctypes.c_int)
_sig(user32.GetWindowLongW, wintypes.LONG, H, ctypes.c_int)
_sig(user32.GetWindowRect, wintypes.BOOL, H, ctypes.POINTER(wintypes.RECT))
_sig(user32.GetWindowDC, H, H)
_sig(user32.ReleaseDC, ctypes.c_int, H, H)
_sig(user32.PrintWindow, wintypes.BOOL, H, H, wintypes.UINT)
_sig(user32.GetForegroundWindow, H)
_sig(user32.SetForegroundWindow, wintypes.BOOL, H)
_sig(user32.ShowWindow, wintypes.BOOL, H, ctypes.c_int)
_sig(user32.GetAncestor, H, H, wintypes.UINT)
_sig(user32.GetWindowThreadProcessId, wintypes.DWORD, H, ctypes.POINTER(wintypes.DWORD))
_sig(kernel32.OpenProcess, H, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_sig(kernel32.QueryFullProcessImageNameW, wintypes.BOOL, H, wintypes.DWORD,
     wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
_sig(kernel32.CloseHandle, wintypes.BOOL, H)
_sig(kernel32.GetCurrentThreadId, wintypes.DWORD)
_sig(user32.AttachThreadInput, wintypes.BOOL, wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
_sig(user32.BringWindowToTop, wintypes.BOOL, H)
_sig(user32.keybd_event, None, wintypes.BYTE, wintypes.BYTE, wintypes.DWORD,
     ctypes.c_size_t)
_sig(user32.GetGUIThreadInfo, wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(GUITHREADINFO))
_sig(user32.GetCursorInfo, wintypes.BOOL, ctypes.POINTER(CURSORINFO))
_sig(user32.LoadCursorW, H, H, H)
_sig(gdi32.CreateCompatibleDC, H, H)
_sig(gdi32.CreateCompatibleBitmap, H, H, ctypes.c_int, ctypes.c_int)
_sig(gdi32.SelectObject, H, H, H)
_sig(gdi32.DeleteObject, wintypes.BOOL, H)
_sig(gdi32.DeleteDC, wintypes.BOOL, H)
_sig(gdi32.GetDIBits, ctypes.c_int, H, H, wintypes.UINT, wintypes.UINT,
     ctypes.c_void_p, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT)
_sig(dwmapi.DwmGetWindowAttribute, ctypes.c_long, H, wintypes.DWORD,
     ctypes.c_void_p, wintypes.DWORD)


def _app_name(hwnd):
    """Executable name without extension, e.g. 'chrome'."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.splitext(os.path.basename(buf.value))[0]
    finally:
        kernel32.CloseHandle(handle)


def list_windows():
    out = []

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        cloaked = wintypes.DWORD()
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), 4)
        if cloaked.value:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        out.append({"id": hwnd, "title": buf.value, "app": _app_name(hwnd)})
        return True

    user32.EnumWindows(_ENUM(visit), 0)
    return out


class WindowSource:
    def __init__(self, hwnd: int):
        if not user32.IsWindow(hwnd):
            raise SourceGone("No such window")
        self.hwnd = hwnd
        self.rect = (0, 0, 2, 2)
        self._last = np.zeros((2, 2, 4), np.uint8)

    def grab(self):
        hwnd = self.hwnd
        # Apps that close to the tray hide the window instead of destroying it.
        if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
            raise SourceGone("Window closed")
        if user32.IsIconic(hwnd):
            return self._last
        outer = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(outer))
        w, h = outer.right - outer.left, outer.bottom - outer.top
        if w <= 0 or h <= 0:
            return self._last

        wdc = user32.GetWindowDC(hwnd)
        mdc = gdi32.CreateCompatibleDC(wdc)
        bmp = gdi32.CreateCompatibleBitmap(wdc, w, h)
        old = gdi32.SelectObject(mdc, bmp)
        try:
            # Renders the window itself, so it works while covered by others.
            user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)
            gdi32.SelectObject(mdc, old)
            bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w,
                                   biHeight=-h, biPlanes=1, biBitCount=32)
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        finally:
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mdc)
            user32.ReleaseDC(hwnd, wdc)
        arr = np.frombuffer(buf, np.uint8).reshape(h, w, 4)

        # Trim the invisible resize border so the image matches what is on screen.
        vis = wintypes.RECT()
        hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                          ctypes.byref(vis), ctypes.sizeof(vis))
        if hr == 0 and vis.right > vis.left and vis.bottom > vis.top:
            x0, y0 = max(vis.left - outer.left, 0), max(vis.top - outer.top, 0)
            x1, y1 = min(vis.right - outer.left, w), min(vis.bottom - outer.top, h)
            arr = arr[y0:y1, x0:x1]
            self.rect = (outer.left + x0, outer.top + y0, x1 - x0, y1 - y0)
        else:
            self.rect = (outer.left, outer.top, w, h)
        self._last = arr
        return arr

    def is_foreground(self):
        """True when this window, or a dialog it owns, has keyboard focus."""
        fg = user32.GetForegroundWindow()
        return bool(fg) and (fg == self.hwnd
                             or user32.GetAncestor(fg, GA_ROOTOWNER) == self.hwnd)

    def focus(self):
        if not user32.IsWindow(self.hwnd):
            return
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_RESTORE)
        if self.is_foreground():
            return
        # Windows refuses to let a background process take the foreground, so
        # try progressively more insistent ways until one sticks.
        for attempt in (self._raise_plain, self._raise_attached,
                        self._raise_with_alt, self._raise_by_restore):
            attempt()
            for _ in range(10):
                if self.is_foreground():
                    return
                time.sleep(0.02)

    def _raise_plain(self):
        user32.SetForegroundWindow(self.hwnd)

    def _raise_with_alt(self):
        # A process that is mid-keystroke counts as the one receiving input.
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.SetForegroundWindow(self.hwnd)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

    def _raise_attached(self):
        # Borrow the input queue of whichever window has the foreground now.
        ours = kernel32.GetCurrentThreadId()
        theirs = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        if not theirs or theirs == ours:
            return
        user32.AttachThreadInput(ours, theirs, True)
        try:
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
        finally:
            user32.AttachThreadInput(ours, theirs, False)

    def _raise_by_restore(self):
        # Last resort: restoring a minimised window always activates it.
        user32.ShowWindow(self.hwnd, SW_MINIMIZE)
        user32.ShowWindow(self.hwnd, SW_RESTORE)

    def close(self):
        pass


def text_focus():
    """True when the foreground app shows a text caret or an I-beam cursor."""
    gti = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if user32.GetGUIThreadInfo(0, ctypes.byref(gti)):
        if gti.hwndCaret or gti.flags & GUI_CARETBLINKING:
            return True
    # Browsers and Electron apps draw their own caret; fall back to the cursor.
    ci = CURSORINFO(cbSize=ctypes.sizeof(CURSORINFO))
    if user32.GetCursorInfo(ctypes.byref(ci)):
        return ci.hCursor == user32.LoadCursorW(None, IDC_IBEAM)
    return False
