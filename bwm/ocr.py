"""Card name-crop preprocessing + a swappable OCR backend.

Tesseract is the default (light, fast, no torch dependency) - it's usually
enough for a tightly-calibrated, name-only crop even with a stylized game
font, provided the crop is upscaled and cleaned up first. If dry-run logs
show it isn't cutting it against the real font, switch `ocr.engine` to
"easyocr" in config.json - no other code changes needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, Tuple

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from .config_models import OcrConfig


def preprocess(crop_bgr: np.ndarray, cfg: OcrConfig) -> np.ndarray:
    h, w = crop_bgr.shape[:2]
    factor = cfg.upscale_factor
    upscaled = cv2.resize(crop_bgr, (max(1, int(w * factor)), max(1, int(h * factor))),
                           interpolation=cv2.INTER_CUBIC)

    # The game renders card names in one very consistent gold/yellow
    # (confirmed by sampling real captures: BGR ~(74,223,255) regardless of
    # what's behind them - a blue gradient panel, dark diagonal-striped
    # card art, a black outline, all of it). A color mask targeting that
    # hue isolates the glyphs far more reliably than a grayscale brightness
    # threshold: a global Otsu threshold gets fooled the moment the
    # background itself has strong local contrast, e.g. real captures
    # where it misread "Reaction" as "Al e ER Sactions" against
    # dark-striped art, while the color mask reads it cleanly since it
    # never looks at background brightness at all.
    hsv = cv2.cvtColor(upscaled, cv2.COLOR_BGR2HSV)
    lower = (cfg.text_hue_min, cfg.text_sat_min, cfg.text_val_min)
    upper = (cfg.text_hue_max, 255, 255)
    mask = cv2.inRange(hsv, lower, upper)  # 255 = matched text pixel

    kernel = np.ones((2, 2), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    binary = cv2.bitwise_not(mask)  # tesseract wants black text on white

    # Tesseract clips glyphs that touch the image edge.
    padded = cv2.copyMakeBorder(binary, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    return padded


class OcrBackend(Protocol):
    def read(self, crop_bgr: np.ndarray) -> Tuple[str, float]:
        """Returns (raw_text, confidence_0_100)."""
        ...


class TesseractBackend:
    def __init__(self, cfg: OcrConfig):
        self.cfg = cfg
        if cfg.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd
        config_path = self._write_whitelist_config(cfg.whitelist)
        self._tess_config = f'--psm {cfg.psm} --oem 1 {config_path}'

    @staticmethod
    def _write_whitelist_config(whitelist: str) -> str:
        """Writes tessedit_char_whitelist to a real Tesseract config file
        and returns its path, instead of inlining `-c var="value"` in the
        config string handed to pytesseract.

        pytesseract's Windows code path runs
        `shlex.split(config, posix=False)`, and non-POSIX shlex only groups
        a quoted span into one token when the quote starts *right at* a
        token boundary - `var="a b"` embedded mid-token still splits on the
        inner space regardless of the quotes. Our whitelist has to contain a
        space (multi-word card names) and an apostrophe, so the inline form
        always broke on Windows. A config file sidesteps shell quoting
        entirely: Tesseract reads the rest of the line as the value, space
        and all. The file must still live under a path with no spaces of
        its own, since a quoted *path* hits the exact same shlex problem -
        hence writing it next to config.json rather than to a temp dir.
        """
        path = Path(__file__).resolve().parent.parent / "config" / "_tesseract_whitelist.cfg"
        path.write_text(f"tessedit_char_whitelist {whitelist}\n", encoding="utf-8")
        return str(path)

    def read(self, crop_bgr: np.ndarray) -> Tuple[str, float]:
        img = preprocess(crop_bgr, self.cfg)
        data = pytesseract.image_to_data(img, config=self._tess_config, output_type=Output.DICT)
        words, confs = [], []
        for text, conf in zip(data["text"], data["conf"]):
            text = text.strip()
            if not text:
                continue
            try:
                conf_f = float(conf)
            except (TypeError, ValueError):
                continue
            if conf_f < 0:
                continue
            words.append(text)
            confs.append(conf_f)
        if not words:
            return "", 0.0
        return " ".join(words), sum(confs) / len(confs)


class EasyOcrBackend:
    """Optional fallback if Tesseract proves unreliable against the game's
    actual font. Requires `pip install easyocr` (not in default
    requirements.txt since it pulls in torch)."""

    def __init__(self, cfg: OcrConfig):
        import easyocr  # local import: heavy optional dependency
        self.cfg = cfg
        self._reader = easyocr.Reader(["en"], gpu=False)

    def read(self, crop_bgr: np.ndarray) -> Tuple[str, float]:
        results = self._reader.readtext(crop_bgr, detail=1)
        if not results:
            return "", 0.0
        text = " ".join(r[1] for r in results)
        conf = 100.0 * sum(r[2] for r in results) / len(results)
        return text.strip(), conf


def build_ocr_backend(cfg: OcrConfig) -> OcrBackend:
    if cfg.engine == "easyocr":
        return EasyOcrBackend(cfg)
    return TesseractBackend(cfg)
