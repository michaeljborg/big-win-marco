"""Screenshot-based calibration tool.

Run standalone:
    python -m bwm.calibration_tool [--config config/config.json]

Grabs a real ADB screenshot - already in true device-pixel space, the same
space taps need to land in - and lets you click/place tap points and drag
out the OCR name-crop rectangle directly on that image. Different targets
live on different game screens (shop screen, mid-pack screen,
sell-confirmation dialog): navigate the game to the right screen and hit
"Recapture" before placing each group of targets. "Test Tap" fires a real
tap at a placed point so you can confirm alignment live on the emulator
before saving.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk

from .adb_controller import AdbController, AdbConnectionError
from .config_models import Config, Point, Rect, load_config, save_config

POINT_TARGETS = [
    ("open_pack", "Open Pack: 1st tap (select Bronze Pack)"),
    ("select_pack", "Open Pack: 2nd tap (select a pack, optional)"),
    ("confirm_purchase", "Open Pack: 3rd tap (confirm purchase, optional)"),
    ("card_select", "Card select/tap point"),
    ("next_card", "Next card (tap to advance N -> N+1)"),
    ("sell_button", "Sell button"),
    ("confirm_sell", "Confirm Sell button"),
    ("continue_close", "Continue / Close button"),
]
RECT_TARGETS = [
    ("name_crop", "Card name-text crop region"),
]

MAX_CANVAS_W = 480
MAX_CANVAS_H = 854


class CalibrationTool(tk.Tk):
    def __init__(self, config_path: Path):
        super().__init__()
        self.title("Big Win Hockey - Calibration")
        self.config_path = config_path
        self.cfg: Config = load_config(config_path)

        self.adb: AdbController | None = None
        self.frame_bgr = None
        self.scale = 1.0
        self.tk_image = None
        self.selected_target: tuple[str, str] | None = None  # (key, kind)
        self._drag_start = None

        self._build_ui()
        self._connect_adb()

    # -- ADB ----------------------------------------------------------
    def _connect_adb(self) -> None:
        try:
            self.adb = AdbController(
                self.cfg.adb,
                self.cfg.calibration.device_width,
                self.cfg.calibration.device_height,
            )
            self.adb.connect()
            self.status_var.set("Connected to BlueStacks over ADB.")
        except AdbConnectionError as e:
            self.adb = None
            self.status_var.set(f"ADB connection failed: {e}")
            messagebox.showwarning("ADB connection failed", str(e))

    # -- UI -------------------------------------------------------------
    def _build_ui(self) -> None:
        toolbar = tk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(toolbar, text="Reconnect ADB", command=self._connect_adb).pack(side=tk.LEFT, padx=4, pady=4)
        tk.Button(toolbar, text="Recapture", command=self.recapture).pack(side=tk.LEFT, padx=4, pady=4)
        tk.Button(toolbar, text="Test Tap", command=self.test_tap_selected).pack(side=tk.LEFT, padx=4, pady=4)
        tk.Button(toolbar, text="Save config.json", command=self.save).pack(side=tk.LEFT, padx=4, pady=4)

        self.status_var = tk.StringVar(value="Not connected.")
        tk.Label(self, textvariable=self.status_var, anchor="w").pack(side=tk.TOP, fill=tk.X, padx=4)

        body = tk.Frame(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(body, width=MAX_CANVAS_W, height=MAX_CANVAS_H, bg="black")
        self.canvas.pack(side=tk.LEFT)
        self.canvas.bind("<Button-1>", self._on_canvas_press)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

        sidebar = tk.Frame(body)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=8)

        tk.Label(sidebar, text="Points (click to place)", font=("", 9, "bold")).pack(anchor="w")
        for key, label in POINT_TARGETS:
            self._add_target_button(sidebar, key, label, "point")

        tk.Label(sidebar, text="Regions (drag to draw)", font=("", 9, "bold")).pack(anchor="w", pady=(10, 0))
        for key, label in RECT_TARGETS:
            self._add_target_button(sidebar, key, label, "rect")

        self.selected_var = tk.StringVar(value="Selected: (none)")
        tk.Label(sidebar, textvariable=self.selected_var, wraplength=220, justify="left").pack(
            anchor="w", pady=(14, 0))

    def _add_target_button(self, parent, key, label, kind) -> None:
        tk.Button(parent, text=label, anchor="w",
                  command=lambda k=key, kd=kind: self._select_target(k, kd)).pack(fill=tk.X)

    def _select_target(self, key: str, kind: str) -> None:
        self.selected_target = (key, kind)
        self.selected_var.set(f"Selected: {key} ({kind}).\nClick (or drag) on the image to place it.")

    # -- Screenshot handling --------------------------------------------
    def recapture(self) -> None:
        if self.adb is None:
            self._connect_adb()
            if self.adb is None:
                return
        try:
            self.frame_bgr = self.adb.screenshot()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Screenshot failed", str(e))
            return

        h, w = self.frame_bgr.shape[:2]
        self.scale = min(MAX_CANVAS_W / w, MAX_CANVAS_H / h, 1.0)
        disp_w, disp_h = max(1, int(w * self.scale)), max(1, int(h * self.scale))
        rgb = cv2.cvtColor(self.frame_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb).resize((disp_w, disp_h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(pil_img)
        self.canvas.config(width=disp_w, height=disp_h)
        self._redraw()
        self.status_var.set(f"Captured {w}x{h} screenshot (display scale {self.scale:.2f}).")

    def _redraw(self) -> None:
        self.canvas.delete("all")
        if self.tk_image is not None:
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        self._draw_existing_markers()

    def _to_device(self, cx: int, cy: int) -> tuple[int, int]:
        return int(cx / self.scale), int(cy / self.scale)

    def _to_canvas(self, dx: int, dy: int) -> tuple[int, int]:
        return int(dx * self.scale), int(dy * self.scale)

    def _draw_existing_markers(self) -> None:
        for key, _ in POINT_TARGETS:
            pt = getattr(self.cfg.points, key)
            if pt:
                cx, cy = self._to_canvas(pt.x, pt.y)
                self.canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, outline="lime", width=2)
                self.canvas.create_text(cx + 8, cy, text=key, anchor="w", fill="lime")
        for key, _ in RECT_TARGETS:
            rect = getattr(self.cfg.regions, key)
            if rect:
                x1, y1 = self._to_canvas(rect.x, rect.y)
                x2, y2 = self._to_canvas(rect.x + rect.w, rect.y + rect.h)
                self.canvas.create_rectangle(x1, y1, x2, y2, outline="cyan", width=2)
                self.canvas.create_text(x1 + 4, y1 - 8, text=key, anchor="w", fill="cyan")

    # -- Mouse handling ----------------------------------------------------
    def _on_canvas_press(self, event) -> None:
        self._drag_start = (event.x, event.y)

    def _on_canvas_release(self, event) -> None:
        if self.selected_target is None:
            messagebox.showinfo("Select a target first", "Click a target in the sidebar before placing it.")
            return
        if self.frame_bgr is None:
            messagebox.showinfo("No screenshot", "Click Recapture first.")
            return

        key, kind = self.selected_target
        start = self._drag_start or (event.x, event.y)
        end = (event.x, event.y)

        if kind == "point":
            dx, dy = self._to_device(*end)
            setattr(self.cfg.points, key, Point(x=dx, y=dy))
        elif kind == "rect":
            (sx, sy), (ex, ey) = start, end
            x0, y0 = min(sx, ex), min(sy, ey)
            x1, y1 = max(sx, ex), max(sy, ey)
            dx0, dy0 = self._to_device(x0, y0)
            dx1, dy1 = self._to_device(x1, y1)
            setattr(self.cfg.regions, key, Rect(x=dx0, y=dy0, w=max(1, dx1 - dx0), h=max(1, dy1 - dy0)))

        self.status_var.set(f"Set {key}.")
        self._redraw()

    # -- Actions ------------------------------------------------------------
    def test_tap_selected(self) -> None:
        if self.selected_target is None:
            messagebox.showinfo("Select a target first", "Select a point target to test-tap.")
            return
        key, kind = self.selected_target
        if kind != "point":
            messagebox.showinfo("Not a point", "Test Tap only applies to point targets.")
            return
        pt = getattr(self.cfg.points, key)
        if pt is None:
            messagebox.showinfo("Not set", f"{key} has not been placed yet.")
            return
        if self.adb is None:
            messagebox.showwarning("Not connected", "ADB is not connected.")
            return
        self.adb.tap(pt.x, pt.y)
        self.status_var.set(f"Test-tapped {key} at ({pt.x}, {pt.y}). Check the emulator.")

    def save(self) -> None:
        if self.adb is not None:
            try:
                w, h = self.adb.get_resolution()
                self.cfg.calibration.device_width = w
                self.cfg.calibration.device_height = h
                self.cfg.calibration.calibrated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:  # noqa: BLE001 - non-fatal, save whatever we have
                pass
        save_config(self.cfg, self.config_path)
        self.status_var.set(f"Saved to {self.config_path}")
        messagebox.showinfo("Saved", f"Configuration saved to {self.config_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Big Win Hockey calibration tool")
    parser.add_argument("--config", default="config/config.json")
    args = parser.parse_args()
    app = CalibrationTool(Path(args.config))
    app.mainloop()


if __name__ == "__main__":
    main()
