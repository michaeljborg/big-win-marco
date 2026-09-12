"""Region cropping helper, plus the stop-signal exception used to unwind the
macro loop promptly when the stop hotkey fires.
"""
from __future__ import annotations

import numpy as np

from .config_models import Rect


class StopRequested(Exception):
    """Raised to unwind the macro loop promptly when the stop hotkey fires."""


def crop_region(frame_bgr: np.ndarray, rect: Rect) -> np.ndarray:
    return frame_bgr[rect.y: rect.y + rect.h, rect.x: rect.x + rect.w]
