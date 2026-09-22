"""Native macOS mouse and pointer dispatch using CoreGraphics via ctypes."""

import sys
import time
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_CG_LOADED = False
_cg = None
_CGPoint = None

if sys.platform == "darwin":
    try:
        import ctypes
        from ctypes import c_void_p, c_uint32, c_int64, c_double, Structure

        class CGPoint(Structure):
            _fields_ = [("x", c_double), ("y", c_double)]

        _CGPoint = CGPoint
        _cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        _cg.CGEventCreateMouseEvent.restype = c_void_p
        _cg.CGEventCreateMouseEvent.argtypes = [c_void_p, c_uint32, CGPoint, c_uint32]
        _cg.CGEventCreateScrollWheelEvent.restype = c_void_p
        _cg.CGEventCreateScrollWheelEvent.argtypes = [c_void_p, c_uint32, c_uint32, c_int64]
        _cg.CGEventPost.argtypes = [c_uint32, c_void_p]
        _cg.CFRelease.argtypes = [c_void_p]
        _CG_LOADED = True
    except Exception as e:
        logger.warning("Failed to initialize CoreGraphics mouse bridge: %s", e)
        _CG_LOADED = False


def is_mouse_available() -> bool:
    """Return True if native macOS mouse dispatch is functional."""
    return _CG_LOADED


def click_screen_coordinates(x: float, y: float, clicks: int = 1, delay_s: float = 0.05) -> bool:
    """Dispatch mouse click(s) at screen coordinates (x, y) using CoreGraphics.

    Args:
        x: Horizontal screen coordinate (points).
        y: Vertical screen coordinate (points).
        clicks: Number of consecutive clicks (1 for single, 2 for double).
        delay_s: Delay between down/up and between clicks.

    Returns:
        bool: True if dispatched successfully.
    """
    if not _CG_LOADED or _cg is None or _CGPoint is None:
        logger.warning("CoreGraphics mouse dispatch is not available on this platform.")
        return False

    try:
        pt = _CGPoint(float(x), float(y))
        # kCGHIDEventTap = 0, kCGMouseButtonLeft = 0
        # kCGEventLeftMouseDown = 1, kCGEventLeftMouseUp = 2
        for _ in range(clicks):
            down = _cg.CGEventCreateMouseEvent(None, 1, pt, 0)
            up = _cg.CGEventCreateMouseEvent(None, 2, pt, 0)
            if not down or not up:
                if down:
                    _cg.CFRelease(down)
                if up:
                    _cg.CFRelease(up)
                return False
            _cg.CGEventPost(0, down)
            time.sleep(delay_s)
            _cg.CGEventPost(0, up)
            _cg.CFRelease(down)
            _cg.CFRelease(up)
            if clicks > 1:
                time.sleep(delay_s)
        return True
    except Exception as e:
        logger.error("Error dispatching mouse click at (%f, %f): %s", x, y, e)
        return False


def scroll_wheel(delta_lines: int) -> bool:
    """Dispatch vertical scroll wheel event. Positive = scroll up, negative = scroll down."""
    if not _CG_LOADED or _cg is None:
        logger.warning("CoreGraphics scroll wheel is not available.")
        return False

    try:
        # kCGScrollEventUnitLine = 1
        evt = _cg.CGEventCreateScrollWheelEvent(None, 1, 1, int(delta_lines))
        if not evt:
            return False
        _cg.CGEventPost(0, evt)
        _cg.CFRelease(evt)
        return True
    except Exception as e:
        logger.error("Error dispatching scroll wheel event (%d): %s", delta_lines, e)
        return False
