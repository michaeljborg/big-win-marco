"""Global start/stop hotkeys backing a thread-safe stop flag.

The stop flag is checked frequently throughout the macro loop (every tap,
every swipe, every animation-polling tick) so a stop request lands within
about one poll interval instead of waiting for the current pack to finish.
"""
from __future__ import annotations

import threading

import keyboard


class HotkeyController:
    def __init__(self, start_hotkey: str = "f9", stop_hotkey: str = "f10"):
        self.start_hotkey = start_hotkey
        self.stop_hotkey = stop_hotkey
        self._stop_event = threading.Event()
        self._start_event = threading.Event()
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        keyboard.add_hotkey(self.start_hotkey, self._on_start)
        keyboard.add_hotkey(self.stop_hotkey, self._on_stop)
        self._registered = True

    def _on_start(self) -> None:
        self._stop_event.clear()
        self._start_event.set()

    def _on_stop(self) -> None:
        self._stop_event.set()

    def wait_for_start(self) -> None:
        self._start_event.wait()

    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def reset_stop(self) -> None:
        self._stop_event.clear()
        self._start_event.clear()
