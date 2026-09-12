"""JSONL run log + crop image saving, so the sell-on-uncertain policy stays
auditable: every card read is recorded, and uncertain reads keep their crop
image for manual review.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from .config_models import LoggingConfig


class RunLogger:
    def __init__(self, run_dir, cfg: LoggingConfig):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = cfg
        self.run_id = time.strftime("%Y%m%d_%H%M%S")
        self.jsonl_path = self.run_dir / f"run_{self.run_id}.jsonl"
        self.crops_dir = self.run_dir / "crops" / self.run_id
        self._fh = open(self.jsonl_path, "a", encoding="utf-8")

    def _write(self, record: dict) -> None:
        record["ts"] = time.time()
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()

    def log_card(self, pack_n: int, card_i: int, raw_text: str, ocr_conf: float,
                 resolved_name: Optional[str], score: float, decision: str, tapped: bool) -> None:
        self._write({
            "event": "card",
            "pack": pack_n,
            "card_i": card_i,
            "raw_text": raw_text,
            "ocr_confidence": ocr_conf,
            "matched_name": resolved_name,
            "match_score": score,
            "decision": decision,
            "tapped": tapped,
        })

    def log_pack_end(self, pack_n: int, sold: int, kept: int, warnings: List[str]) -> None:
        self._write({
            "event": "pack_end",
            "pack": pack_n,
            "sold": sold,
            "kept": kept,
            "warnings": warnings,
        })

    def log_warning(self, message: str) -> None:
        self._write({"event": "warning", "message": message})

    def save_crop(self, pack_n: int, card_i: int, crop_bgr: np.ndarray, decision: str) -> None:
        self.crops_dir.mkdir(parents=True, exist_ok=True)
        path = self.crops_dir / f"{pack_n:04d}_{card_i}_{decision}.png"
        cv2.imwrite(str(path), crop_bgr)

    def close(self) -> None:
        self._fh.close()
