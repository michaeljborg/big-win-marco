"""Dataclass schema for config/config.json, with generic JSON <-> dataclass
conversion so nested points/regions round-trip cleanly between the
calibration tool and the macro runtime.
"""
from __future__ import annotations

import dataclasses
import json
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Point:
    x: int
    y: int


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass
class AdbConfig:
    host: str = "127.0.0.1"
    port: Optional[int] = 5555
    device_serial: Optional[str] = None
    # BlueStacks assigns a different ADB port per instance - sweep these if
    # the configured port doesn't respond.
    candidate_ports: list = field(
        default_factory=lambda: [5555, 5556, 5565, 5575, 5585, 5637]
    )
    # How long a tap holds the touch down before releasing. Short enough to
    # read as a tap rather than a hold/long-press; raise it if taps stop
    # registering at all, lower it if the game still treats them as a hold.
    tap_duration_ms: int = 30


@dataclass
class CalibrationInfo:
    device_width: Optional[int] = None
    device_height: Optional[int] = None
    calibrated_at: Optional[str] = None


@dataclass
class Points:
    open_pack: Optional[Point] = None
    select_pack: Optional[Point] = None
    confirm_purchase: Optional[Point] = None
    card_select: Optional[Point] = None
    next_card: Optional[Point] = None
    sell_button: Optional[Point] = None
    confirm_sell: Optional[Point] = None
    continue_close: Optional[Point] = None


@dataclass
class Regions:
    name_crop: Optional[Rect] = None


@dataclass
class Timings:
    post_tap_min_delay_s: float = 0.15
    # Extra gap after the open_pack tap specifically - the bronze-pack tile
    # tap needs a beat for its menu/screen to open before select_pack can
    # register, longer than the general post_tap_min_delay_s covers.
    post_open_pack_delay_s: float = 0.3
    # Fixed waits (no on-screen change detection): tune these against a
    # dry run if OCR reads come back garbled (transition wasn't done yet)
    # or the macro feels slower than it needs to be.
    pack_open_settle_delay_s: float = 5.0
    card_advance_settle_delay_s: float = 1.0
    post_sell_delay_s: float = 1.0
    post_confirm_delay_s: float = 1.0
    post_continue_delay_s: float = 1.0


@dataclass
class OcrConfig:
    engine: str = "tesseract"  # "tesseract" | "easyocr"
    tesseract_cmd: Optional[str] = None
    psm: int = 7
    whitelist: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' -"
    upscale_factor: float = 3.5
    # HSV bounds (OpenCV H:0-179, S/V:0-255) for isolating the game's
    # gold/yellow card-name text by color instead of by brightness. Tuned
    # against real captures (fill color sampled at BGR ~(74,223,255), i.e.
    # H~25/S~181/V~255); widen if real names start getting clipped, narrow
    # if background art starts bleeding through.
    text_hue_min: int = 15
    text_hue_max: int = 40
    text_sat_min: int = 100
    text_val_min: int = 120
    match_threshold: int = 90


@dataclass
class SafetyConfig:
    start_hotkey: str = "f9"
    stop_hotkey: str = "f10"
    max_packs: Optional[int] = None
    dry_run: bool = True


@dataclass
class LoggingConfig:
    save_all_crops: bool = False
    save_crops_on_uncertain: bool = True


@dataclass
class Config:
    adb: AdbConfig = field(default_factory=AdbConfig)
    calibration: CalibrationInfo = field(default_factory=CalibrationInfo)
    points: Points = field(default_factory=Points)
    regions: Regions = field(default_factory=Regions)
    timings: Timings = field(default_factory=Timings)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# --- generic (de)serialization -------------------------------------------

def _is_optional(tp) -> bool:
    return typing.get_origin(tp) is typing.Union and type(None) in typing.get_args(tp)


def _unwrap_optional(tp):
    args = [a for a in typing.get_args(tp) if a is not type(None)]
    return args[0] if args else tp


def dict_to_dataclass(cls, data: dict):
    if data is None:
        return None
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in dataclasses.fields(cls):
        tp = hints[f.name]
        if _is_optional(tp):
            tp = _unwrap_optional(tp)
        raw = data.get(f.name, dataclasses.MISSING)
        if raw is dataclasses.MISSING:
            continue
        if dataclasses.is_dataclass(tp) and isinstance(raw, dict):
            kwargs[f.name] = dict_to_dataclass(tp, raw)
        else:
            kwargs[f.name] = raw
    return cls(**kwargs)


def dataclass_to_dict(obj):
    if obj is None:
        return None
    if dataclasses.is_dataclass(obj):
        return {f.name: dataclass_to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    return obj


def load_config(path) -> Config:
    path = Path(path)
    if not path.exists():
        return Config()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return dict_to_dataclass(Config, data)


def save_config(cfg: Config, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dataclass_to_dict(cfg), f, indent=2)
        f.write("\n")
