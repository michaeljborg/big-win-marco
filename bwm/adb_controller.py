"""ADB connection + tap/screenshot wrapper for BlueStacks.

Uses `adbutils` (talks to the adb server over its socket API in-process)
rather than shelling out to adb.exe per call.
"""
from __future__ import annotations

import re
from typing import Optional

import adbutils
import cv2
import numpy as np

from .config_models import AdbConfig


class AdbConnectionError(RuntimeError):
    pass


class AdbController:
    def __init__(self, cfg: AdbConfig, expected_width: Optional[int] = None,
                 expected_height: Optional[int] = None):
        self.cfg = cfg
        self.expected_width = expected_width
        self.expected_height = expected_height
        self._device = None

    def connect(self):
        """Connects to BlueStacks, trying the configured port first and then
        sweeping candidate ports. Verifies the device actually responds and
        (if an expected resolution was given) matches it, so a stale/wrong
        instance doesn't silently receive taps meant for another one.
        """
        client = adbutils.AdbClient(host="127.0.0.1", port=5037)

        ports_to_try = []
        if self.cfg.port:
            ports_to_try.append(self.cfg.port)
        for p in self.cfg.candidate_ports:
            if p not in ports_to_try:
                ports_to_try.append(p)

        last_err: Optional[Exception] = None
        for port in ports_to_try:
            serial = self.cfg.device_serial or f"{self.cfg.host}:{port}"
            try:
                client.connect(serial, timeout=2.0)
            except Exception as e:  # noqa: BLE001 - try the next candidate port
                last_err = e
                continue
            try:
                device = client.device(serial=serial)
                device.shell("echo ok")  # confirm it actually responds
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue

            self._device = device
            self._verify_resolution(device)
            return device

        raise AdbConnectionError(
            "Could not connect to BlueStacks over ADB on any candidate port "
            f"{ports_to_try}. In BlueStacks: Settings > Advanced > enable "
            "'Android Debug Bridge (ADB)' and note the port shown there, "
            f"then set it as adb.port in config.json. Last error: {last_err}"
        )

    def _verify_resolution(self, device) -> None:
        if not self.expected_width or not self.expected_height:
            return  # not calibrated yet - nothing to check against
        w, h = self._parse_wm_size(device.shell("wm size"))
        if w is None:
            return
        if (w, h) != (self.expected_width, self.expected_height):
            raise AdbConnectionError(
                f"Connected device resolution {w}x{h} does not match the "
                f"calibrated resolution {self.expected_width}x{self.expected_height}. "
                "Re-run the calibration tool, or fix BlueStacks' display "
                "resolution back to what it was during calibration."
            )

    @staticmethod
    def _parse_wm_size(output: str):
        m = re.search(r"(\d+)x(\d+)", output)
        if not m:
            return None, None
        return int(m.group(1)), int(m.group(2))

    @property
    def device(self):
        if self._device is None:
            raise AdbConnectionError("Not connected yet - call connect() first.")
        return self._device

    def get_resolution(self) -> tuple:
        w, h = self._parse_wm_size(self.device.shell("wm size"))
        if w is None:
            raise RuntimeError("Could not parse 'wm size' output from device.")
        return w, h

    def tap(self, x: int, y: int) -> None:
        # A same-point swipe with an explicit short duration, rather than
        # adbutils' click() (which shells out to `input tap` - on some
        # Android/BlueStacks builds that has enough built-in press duration
        # for the game to read it as a hold instead of a quick tap).
        duration_s = self.cfg.tap_duration_ms / 1000.0
        self.device.swipe(x, y, x, y, duration_s)

    def screenshot(self) -> np.ndarray:
        """Returns a BGR numpy array (OpenCV convention)."""
        pil_img = self.device.screenshot()
        rgb = np.array(pil_img)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
