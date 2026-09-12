"""PackFarmerStateMachine - the main open/read/decide/sell loop.

Flow per pack: tap open-pack (+ select-pack and confirm-purchase if
configured) -> wait a fixed delay for the reveal animation to settle -> for
each of the 6 cards: screenshot, crop the name region, OCR, decide, tap to
select if selling, tap next-card and wait a fixed delay for the transition
to settle -> tap Sell -> tap Confirm -> tap Continue -> log the pack outcome
-> repeat.
"""
from __future__ import annotations

import time
from typing import Optional

from .adb_controller import AdbController
from .capture import StopRequested, crop_region
from .config_models import Config
from .hotkeys import HotkeyController
from .matcher import CardMatcher
from .ocr import OcrBackend
from .run_logger import RunLogger


class PackFarmerStateMachine:
    def __init__(self, cfg: Config, adb: AdbController, ocr: OcrBackend,
                 matcher: CardMatcher, logger: RunLogger, hotkeys: HotkeyController):
        self.cfg = cfg
        self.adb = adb
        self.ocr = ocr
        self.matcher = matcher
        self.logger = logger
        self.hotkeys = hotkeys

    def run(self, max_packs: Optional[int] = None) -> None:
        pack_count = 0
        limit = max_packs if max_packs is not None else self.cfg.safety.max_packs
        try:
            while not self.hotkeys.stop_requested():
                if limit is not None and pack_count >= limit:
                    break
                self._run_one_pack(pack_count)
                pack_count += 1
        except StopRequested:
            print("Stop hotkey pressed - halting.")

    def _check_stop(self) -> None:
        if self.hotkeys.stop_requested():
            raise StopRequested()

    def _tap(self, point) -> None:
        self._check_stop()
        self.adb.tap(point.x, point.y)
        time.sleep(self.cfg.timings.post_tap_min_delay_s)

    def _wait(self, seconds: float, poll: float = 0.1) -> None:
        """Fixed delay, but sliced so the stop hotkey still lands promptly
        instead of only being checked once every several seconds."""
        remaining = seconds
        while remaining > 0:
            self._check_stop()
            chunk = min(poll, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _run_one_pack(self, pack_n: int) -> None:
        t = self.cfg.timings
        p = self.cfg.points
        warnings = []

        self._tap(p.open_pack)
        if p.select_pack:
            self._wait(t.post_open_pack_delay_s)
            self._tap(p.select_pack)
        if p.confirm_purchase:
            self._tap(p.confirm_purchase)

        self._wait(t.pack_open_settle_delay_s)

        sold = 0
        kept = 0
        for card_i in range(6):
            self._check_stop()
            frame = self.adb.screenshot()
            crop = crop_region(frame, self.cfg.regions.name_crop)
            raw_text, ocr_conf = self.ocr.read(crop)
            result = self.matcher.decide(raw_text)

            print(f"  Card {card_i + 1}: read={raw_text!r} (ocr_conf={ocr_conf:.0f}) "
                  f"-> matched={result.resolved_name!r} (score={result.score:.0f}) "
                  f"decision={result.decision}")

            will_tap = result.decision == "sell" and not self.cfg.safety.dry_run
            self.logger.log_card(pack_n, card_i, raw_text, ocr_conf,
                                  result.resolved_name, result.score, result.decision, will_tap)

            if result.decision == "keep":
                kept += 1
            else:
                sold += 1

            if self.cfg.logging.save_all_crops or (
                result.decision == "sell" and self.cfg.logging.save_crops_on_uncertain
            ):
                self.logger.save_crop(pack_n, card_i, crop, result.decision)

            if will_tap:
                self._tap(p.card_select)

            if card_i < 5:
                self._tap(p.next_card)
                self._wait(t.card_advance_settle_delay_s)

        if not self.cfg.safety.dry_run:
            self._tap(p.sell_button)
            time.sleep(t.post_sell_delay_s)
            self._tap(p.confirm_sell)
            time.sleep(t.post_confirm_delay_s)
            self._tap(p.continue_close)
            time.sleep(t.post_continue_delay_s)

        for w in warnings:
            self.logger.log_warning(f"pack {pack_n}: {w}")
        self.logger.log_pack_end(pack_n, sold, kept, warnings)

        mode = " [DRY RUN]" if self.cfg.safety.dry_run else ""
        print(f"Pack {pack_n}: kept {kept}, sold {sold}{mode}" +
              (f" - warnings: {warnings}" if warnings else ""))
