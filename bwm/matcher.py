"""Fuzzy name resolution -> keep/sell decision.

OCR text is fuzzy-matched directly against the keep list. Anything that
doesn't clear the threshold is sold - bronze packs are low value, so a
missed read just costs one common card, not a mistake worth a second
matching stage to guard against.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from rapidfuzz import fuzz, process

from .config_models import OcrConfig


@dataclass
class MatchResult:
    raw_text: str
    resolved_name: Optional[str]
    score: float
    decision: str  # "keep" | "sell"


def _normalize(text: str) -> str:
    return " ".join(text.strip().casefold().split())


class CardMatcher:
    def __init__(self, keep_list: List[str], cfg: OcrConfig):
        self.keep_list = list(dict.fromkeys(keep_list))  # de-duplicated, order preserved
        self.cfg = cfg

    def decide(self, raw_text: str) -> MatchResult:
        text = _normalize(raw_text)
        if text and self.keep_list:
            match = process.extractOne(text, self.keep_list, scorer=fuzz.WRatio, processor=_normalize)
            if match and match[1] >= self.cfg.match_threshold:
                return MatchResult(raw_text, match[0], match[1], "keep")
            return MatchResult(raw_text, None, match[1] if match else 0.0, "sell")
        return MatchResult(raw_text, None, 0.0, "sell")
