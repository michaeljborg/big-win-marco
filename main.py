"""Big Win Hockey bronze pack farmer - CLI entry point.

Usage:
    python -m bwm.calibration_tool          # calibrate points/regions first
    python main.py --dry-run --max-packs 3  # validate OCR/matching, no real sells
    python main.py --live --once            # sell for real, one pack
    python main.py --live                   # run until F10 or config max_packs
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bwm.adb_controller import AdbConnectionError, AdbController
from bwm.config_models import load_config
from bwm.hotkeys import HotkeyController
from bwm.macro import PackFarmerStateMachine
from bwm.matcher import CardMatcher
from bwm.ocr import build_ocr_backend
from bwm.run_logger import RunLogger

REQUIRED_POINTS = ["open_pack", "card_select", "next_card", "sell_button", "confirm_sell", "continue_close"]
REQUIRED_REGIONS = ["name_crop"]


def _load_json_list(path: Path, key: str) -> list:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get(key, []))


def _check_calibrated(cfg) -> None:
    missing = [k for k in REQUIRED_POINTS if getattr(cfg.points, k) is None]
    missing += [k for k in REQUIRED_REGIONS if getattr(cfg.regions, k) is None]
    if missing:
        raise SystemExit(
            "config.json is missing calibration for: " + ", ".join(missing) +
            "\nRun `python -m bwm.calibration_tool` first."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Big Win Hockey bronze pack farmer")
    parser.add_argument("--config", default="config/config.json")
    parser.add_argument("--keep-list", default="config/keep_list.json")
    parser.add_argument("--dry-run", action="store_true",
                         help="Log decisions without actually tapping select/sell/confirm.")
    parser.add_argument("--live", action="store_true",
                         help="Force live mode even if config.json has dry_run true.")
    parser.add_argument("--max-packs", type=int, default=None)
    parser.add_argument("--once", action="store_true", help="Shorthand for --max-packs 1")
    args = parser.parse_args()

    cfg = load_config(args.config)
    _check_calibrated(cfg)

    if args.dry_run:
        cfg.safety.dry_run = True
    if args.live:
        cfg.safety.dry_run = False
    max_packs = 1 if args.once else args.max_packs

    keep_list = _load_json_list(Path(args.keep_list), "keep")

    adb = AdbController(cfg.adb, cfg.calibration.device_width, cfg.calibration.device_height)
    try:
        adb.connect()
    except AdbConnectionError as e:
        raise SystemExit(str(e))

    ocr_backend = build_ocr_backend(cfg.ocr)
    matcher = CardMatcher(keep_list, cfg.ocr)
    logger = RunLogger(Path("logs"), cfg.logging)
    hotkeys = HotkeyController(cfg.safety.start_hotkey, cfg.safety.stop_hotkey)
    hotkeys.register()

    mode = "DRY RUN" if cfg.safety.dry_run else "LIVE"
    print(f"Mode: {mode}. Press {cfg.safety.start_hotkey.upper()} to start, "
          f"{cfg.safety.stop_hotkey.upper()} to stop at any time.")
    hotkeys.wait_for_start()

    machine = PackFarmerStateMachine(cfg, adb, ocr_backend, matcher, logger, hotkeys)
    try:
        machine.run(max_packs=max_packs)
    finally:
        logger.close()


if __name__ == "__main__":
    main()
