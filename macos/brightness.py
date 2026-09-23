"""macOS native display brightness integration using DisplayServices / CoreDisplay."""

from __future__ import annotations
import ctypes
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_ds_lib: Optional[ctypes.CDLL] = None
_cg_lib: Optional[ctypes.CDLL] = None
_init_attempted: bool = False
_is_available: bool = False


def _init_display_services() -> bool:
    """Initialize DisplayServices and CoreGraphics CDLL bindings."""
    global _ds_lib, _cg_lib, _init_attempted, _is_available
    if _init_attempted:
        return _is_available

    _init_attempted = True
    try:
        ds_path = "/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices"
        cg_path = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"

        _ds_lib = ctypes.CDLL(ds_path)
        _cg_lib = ctypes.CDLL(cg_path)

        # Function signatures
        _ds_lib.DisplayServicesGetLinearBrightness.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_float)]
        _ds_lib.DisplayServicesGetLinearBrightness.restype = ctypes.c_int

        _ds_lib.DisplayServicesSetLinearBrightness.argtypes = [ctypes.c_uint32, ctypes.c_float]
        _ds_lib.DisplayServicesSetLinearBrightness.restype = ctypes.c_int

        _cg_lib.CGMainDisplayID.argtypes = []
        _cg_lib.CGMainDisplayID.restype = ctypes.c_uint32

        # Test query on main display
        main_id = _cg_lib.CGMainDisplayID()
        test_val = ctypes.c_float(0.0)
        ret = _ds_lib.DisplayServicesGetLinearBrightness(main_id, ctypes.byref(test_val))
        if ret == 0:
            _is_available = True
            return True
        else:
            logger.warning(f"DisplayServicesGetLinearBrightness returned non-zero error: {ret}")
            _is_available = False
            return False
    except Exception as e:
        logger.warning(f"Failed to bind macOS DisplayServices: {e}")
        _is_available = False
        return False


def is_brightness_supported() -> bool:
    """Check if native macOS display brightness control is functional."""
    return _init_display_services()


def get_display_brightness(display_id: Optional[int] = None) -> tuple[bool, float, Optional[str]]:
    """Query current display brightness in range [0.0, 1.0].

    Returns (success, brightness_value, error_message).
    """
    if not _init_display_services():
        return False, 0.0, "DisplayServices is not supported or accessible on this display."

    try:
        did = display_id if display_id is not None else _cg_lib.CGMainDisplayID()
        val = ctypes.c_float(0.0)
        ret = _ds_lib.DisplayServicesGetLinearBrightness(ctypes.c_uint32(did), ctypes.byref(val))
        if ret != 0:
            return False, 0.0, f"DisplayServices error code: {ret}"
        return True, float(val.value), None
    except Exception as e:
        return False, 0.0, f"Failed to get brightness: {e}"


def set_display_brightness(level: float, display_id: Optional[int] = None) -> tuple[bool, float, Optional[str]]:
    """Set display brightness to level in range [0.0, 1.0].

    Returns (success, actual_brightness_value, error_message).
    """
    if not _init_display_services():
        return False, 0.0, "DisplayServices is not supported or accessible on this display."

    clamped = max(0.0, min(1.0, float(level)))
    try:
        did = display_id if display_id is not None else _cg_lib.CGMainDisplayID()
        ret = _ds_lib.DisplayServicesSetLinearBrightness(ctypes.c_uint32(did), ctypes.c_float(clamped))
        if ret != 0:
            return False, 0.0, f"DisplayServices error code: {ret}"

        # Read back actual state
        val = ctypes.c_float(0.0)
        _ds_lib.DisplayServicesGetLinearBrightness(ctypes.c_uint32(did), ctypes.byref(val))
        return True, float(val.value), None
    except Exception as e:
        return False, 0.0, f"Failed to set brightness: {e}"
