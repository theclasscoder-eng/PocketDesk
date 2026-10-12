"""Capture sources and the WebRTC video track that streams them.

Capture and encoding are CPU-only: frames come from OS screen APIs and are
encoded by aiortc's software VP8/H.264 encoders. No CUDA or other GPU compute
context is ever created by this process.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import mss
import numpy as np
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame

from .backends import SourceGone

CLOCK = 90000


def list_screens():
    with mss.mss() as sct:
        return [{"id": i, "title": f"Display {i}",
                 "detail": f"{m['width']} × {m['height']}"}
                for i, m in enumerate(sct.monitors) if i > 0]


class ScreenSource:
    def __init__(self, index: int = 1):
        self.index = index
        self.rect = (0, 0, 2, 2)
        self._sct = None

    def grab(self):
        if self._sct is None:  # mss handles are bound to the thread that made them
            self._sct = mss.mss()
        mons = self._sct.monitors
        if not 1 <= self.index < len(mons):
            raise SourceGone("No such display")
        mon = mons[self.index]
        self.rect = (mon["left"], mon["top"], mon["width"], mon["height"])
        shot = self._sct.grab(mon)
        return np.frombuffer(shot.raw, np.uint8).reshape(shot.height, shot.width, 4)

    def focus(self):
        pass

    def is_foreground(self):
        return True

    def close(self):
        if self._sct:
            self._sct.close()


class CaptureTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, source, fps: int, max_width: int, on_gone=None):
        super().__init__()
        self.source = source
        self.fps = fps
        self.max_width = max_width
        self.on_gone = on_gone
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture")
        self._start = None
        self._count = 0

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        if self._start is None:
            self._start = time.monotonic()
        else:
            self._count += 1
            wait = self._start + self._count / self.fps - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            else:  # fell behind; do not try to catch up with a burst
                self._start, self._count = time.monotonic() - 1 / self.fps, 1
        loop = asyncio.get_running_loop()
        try:
            frame = await loop.run_in_executor(self._pool, self._frame)
        except Exception as exc:
            if self.on_gone:
                self.on_gone(str(exc))
            self.stop()
            raise MediaStreamError from exc
        frame.pts = int(time.monotonic() * CLOCK)
        frame.time_base = Fraction(1, CLOCK)
        return frame

    def _frame(self):
        arr = self.source.grab()
        h, w = arr.shape[:2]
        h, w = h - h % 2, w - w % 2  # encoders need even dimensions
        frame = VideoFrame.from_ndarray(np.ascontiguousarray(arr[:h, :w]), format="bgra")
        if w > self.max_width:
            nh = int(h * self.max_width / w)
            frame = frame.reformat(width=self.max_width - self.max_width % 2,
                                   height=nh - nh % 2)
        return frame

    def stop(self):
        if self.readyState == "live":
            super().stop()
            self._pool.submit(self.source.close)
            self._pool.shutdown(wait=False)
