# OCR Debugging Case Study: Grayscale Threshold → Color Masking

**Date:** 2026-09-12
**Symptom:** A `--dry-run` pack showed `kept 1, sold 5`, and the newly-added
per-card console output revealed why: half the reads were badly garbled or
completely empty.

```
Card 1: read='atakeaways'          -> matched 'Takeaways' (score=95)  OK (fuzzy match survived it)
Card 2: read='NS riury Free'       -> no match
Card 3: read='Defensive Draws'     -> no match (correct - real card, not in keep list)
Card 4: read='Al e ER Sactions'    -> no match
Card 5: read=''                    -> no match
Card 6: read=''                    -> no match
```

This doc walks through how we diagnosed it, a dead end we hit along the way,
and the fix we shipped - mainly so the same mistake (trusting a "smarter"
heuristic without checking its failure mode) doesn't get repeated next time
OCR needs work.

## Step 1: Don't guess, look at what OCR actually saw

`config.json`'s `logging.save_crops_on_uncertain` already saves the exact
crop image behind every `sell_uncertain` decision, under
`logs/crops/<run_id>/`. Before touching any code, we pulled up the crops for
cards 2-6 (card 1 wasn't saved since it matched successfully).

Two things jumped out immediately:

- **"Defensive Draws" and "Injury Free"** sat on a plain blue gradient
  banner - one read at 96% confidence, the other garbled, so the *font*
  wasn't the problem.
- **"Reaction" and "Shot" (×2)** sat on a dark, high-contrast diagonal
  striped background - and all three of those were the badly garbled or
  empty ones.

That correlation (texture-heavy background → bad read, plain background →
good read) pointed straight at the preprocessing, not the crop calibration
or the font.

## Step 2: Find out why texture breaks it

The existing `preprocess()` in `bwm/ocr.py` did:
`grayscale → upscale → CLAHE contrast → single global Otsu threshold`.

Otsu picks *one* brightness cutoff for the entire image based on its overall
histogram. That's fine against a smooth gradient, but a background with its
own strong light/dark texture (the diagonal stripes) pulls the histogram
around enough that the cutoff no longer cleanly separates "text" from
"background" - some stripe pixels end up on the text side of the line and
vice versa, and Tesseract sees noise instead of glyphs.

## Step 3: Find a signal that doesn't care about the background

We sampled raw BGR/HSV pixel values across several crops (`cv2.imread` +
manual pixel indexing) instead of guessing. Every single crop showed the
card name text in almost exactly the same color:

```
BGR ≈ (74, 223, 255)   →   HSV ≈ (25, 181, 255)
```

...regardless of whether it sat on the blue banner, the orange stripes, or
right next to the black outline the font uses. That consistency is the
whole fix: instead of thresholding on *brightness* (which the background
can imitate), threshold on *this exact color* (which only the text uses).

We validated this against the real saved crops (via the actual
`pytesseract.image_to_data` call path, not just a quick `image_to_string`
sanity check - see Step 4 for why that distinction mattered) before touching
`ocr.py` at all:

| Card | Old (grayscale + Otsu) | New (HSV color mask) |
|---|---|---|
| Injury Free | `'NS riury Free'` | `'Injury Free'` ✅ |
| Defensive Draws | (96 conf, borderline) | `'Defensive Draws'` ✅ |
| Reaction | `'Al e ER Sactions'` | `"' Reaction"` (real word intact) |
| Shot ×2 | `''` (empty) | `'el Shot'` / `'el -Shot'` (real word intact) |

Two of five went perfect immediately. The other three improved from
unusable to "real word plus a little junk" - which was enough for the
fuzzy matcher, but not fully clean. That led to a second, smaller
investigation.

## Step 4: The dead end - auto-detecting "the real text row"

The three still-imperfect crops all had a second, separately-colored blob
of gold/yellow pixels sitting in their own distinct row, above the actual
card name - a sliver of a same-colored icon/ribbon bleeding into the top of
the crop rectangle. The natural next idea: after building the color mask,
find the row-band with the most ink (a histogram of foreground pixels per
row) and keep only that band, discarding everything else as noise.

First attempt: pick the single row-range with the *highest total ink*, using
a small gap tolerance to decide where one "band" ends and another begins.

**This made things worse**, not better - "Defensive Draws" (previously
perfect with the plain color mask) came back as `'UVetensive Uraws'`. We
dumped the row-by-row ink histogram to see why, and found the real letters
have an internal dip in ink between the tops of tall capitals (like "D")
and the denser main body of the word - a real, if small, gap. Our
gap-tolerance was too tight, so it treated that dip as a hard boundary and
kept only the denser sub-segment, silently chopping the tops off capital
letters (which is exactly what turns a "D" into something that reads as
"U").

We widened the gap tolerance so it merged across small intra-word dips
while still separating from the noise band - and "Defensive Draws" came
back clean. But testing against the "Shot" crops exposed a deeper problem
we hadn't guarded against at all: **the noise blob there had *more total
ink* than the real word "Shot" itself.** `max(segments, key=total_ink)`
picked the noise band outright, not just partially.

At that point we stopped: this heuristic has a genuine failure mode that no
amount of threshold-tuning fixes, because it's fundamentally guessing which
of two colored blobs is "the real text" using a signal (ink quantity) that
isn't reliably correlated with being the real text. A short word next to a
large icon will always be at risk.

**Decision: don't ship it.** A fragile heuristic that can *actively pick the
wrong answer* is worse than the plain color mask, which never does worse
than "real word plus harmless junk" that the fuzzy matcher already tolerates
fine.

## The fix we actually shipped

1. **`bwm/ocr.py`** - `preprocess()` now upscales the crop, converts to HSV,
   and masks by color (`cv2.inRange` against the sampled gold/yellow range)
   instead of grayscale + Otsu. Small morphological open+close cleans up
   speckle noise and fills tiny gaps, same as before.
2. **`bwm/config_models.py` / `config.json`** - the HSV bounds are exposed
   as `ocr.text_hue_min` / `text_hue_max` / `text_sat_min` / `text_val_min`
   rather than hardcoded, in case a different pack tier ever renders name
   text in a different color.
3. **No row-band auto-cropping.** The residual "junk prefix from a
   same-colored icon" issue is left as a manual calibration knob: tighten
   `name_crop` in the calibration tool to exclude the corner the icon
   bleeds in from. This is a one-time, low-risk fix (you're narrowing a
   rectangle you already calibrated by eye) versus an algorithm that can
   confidently pick the wrong answer.

## Why this is worth remembering

- **Sample the actual data before designing a threshold.** We didn't guess
  an HSV range - we read real pixel values out of real crops first. Every
  bound in the fix traces back to a measurement.
- **A "smarter" heuristic needs its failure mode checked, not just its
  success cases.** The row-band idea looked reasonable and even fixed one
  case (Defensive Draws) on the second attempt - but it took a specifically
  adversarial case (short word, large same-colored noise blob) to reveal
  that "pick the band with more ink" is not a safe assumption in general.
  We only found that by testing against *all* the failing crops, not just
  the one we were actively iterating on.
- **Test through the real code path, not a shortcut.** An early check used
  `pytesseract.image_to_string()` and got confusing results that didn't
  match what the actual pipeline (`image_to_data()`, word-level, used by
  `TesseractBackend.read()`) produced on the same image. Always validate
  against the exact method production code calls.
- **Saved failure artifacts are a free regression suite.** Because
  `save_crops_on_uncertain` was already on, every fix in this session was
  validated offline against the exact images that failed - zero emulator
  interaction needed to confirm the improvement, and a clean way to compare
  old vs. new preprocessing side by side.

## If OCR breaks again

1. Turn on `logging.save_all_crops` (or rely on `save_crops_on_uncertain`)
   and grab the failing crop(s) from `logs/crops/<run_id>/`.
2. Sample pixel colors directly (`cv2.imread` + index into the array) rather
   than eyeballing the image - confirm whether the text color assumption in
   `ocr.py`'s `preprocess()` still holds.
3. Test any preprocessing change against the saved crops through
   `bwm.ocr.TesseractBackend.read()` (or at least `image_to_data`, matching
   what `read()` actually calls) before touching the live pipeline.
4. If a fix seems to work on the crop you're looking at, deliberately test
   it against every other saved crop too, especially ones with a very short
   or very cluttered name - that's where heuristics tend to break.
