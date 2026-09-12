# Big Win Hockey — Bronze Pack Farmer

Automates the shop grind in Big Win Hockey (played via BlueStacks): open a
bronze pack, read each of the 6 cards' names by OCR, sell the ones you don't
want, keep the ones you do, repeat.

Everything talks to the emulator over **ADB** (not simulated mouse clicks),
so it works in the emulator's true device-pixel coordinate space and doesn't
care whether the BlueStacks window is focused, moved, or covered.

## 1. One-time setup

### 1a. Enable ADB in BlueStacks
1. Open BlueStacks → **Settings** (gear icon) → **Advanced**.
2. Turn on **Android Debug Bridge (ADB)**.
3. Note the `127.0.0.1:<port>` address shown — BlueStacks assigns a port per
   instance and it isn't always 5555. You'll put this in `config/config.json`
   (`adb.port`), or just leave the defaults — the tool will sweep a list of
   common candidate ports automatically if the configured one doesn't answer.
4. In BlueStacks display settings, lock the resolution to a fixed value
   (not "Auto") so calibrated coordinates don't drift between sessions.

### 1b. Install dependencies
```
pip install -r requirements.txt
```
You also need, separately:
- **Tesseract OCR** (the engine itself — `pytesseract` is just a Python
  wrapper around it). On Windows, install the
  [UB-Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki),
  then either add its install folder to `PATH` or set `ocr.tesseract_cmd` in
  `config/config.json` to the full path of `tesseract.exe`.
- **Android platform-tools** (`adb.exe`) — add its folder to `PATH` so the
  `adbutils` library can find/start the adb server.

### 1c. Calibrate click points and the OCR region
```
python -m bwm.calibration_tool
```
This opens a small window that pulls a real screenshot from BlueStacks (via
ADB, so it's already in the exact pixel space taps use) and lets you click
to place points, or drag to draw regions/gestures, directly on that image.

Because different targets live on different game screens, calibrate in
passes — navigate the actual game to the right screen, click **Recapture**,
then place the targets that live there:

| Screen | Targets to place |
|---|---|
| Shop screen | `open_pack` (1st tap: select Bronze Pack), `select_pack` (2nd tap: choose a pack, if that step exists), `confirm_purchase` (3rd tap: confirm dialog, if it exists) |
| Mid-pack (after opening, one card showing) | `card_select` (point), `name_crop` (drag a tight rectangle around just the name text), `next_card` (point — a tap that advances from card N to N+1) |
| After selecting cards to sell | `sell_button` |
| Sell confirmation dialog | `confirm_sell` |
| After confirming the sale | `continue_close` (whatever gets you back to the shop) |

Use **Test Tap** on any placed point to fire a real tap and confirm it lands
correctly on the live emulator before moving on. Click **Save config.json**
when done — this also records the detected device resolution, which is
checked on every future run so a resolution change (e.g. BlueStacks got
reset to "Auto") is caught with a clear error instead of silently mis-tapping.

### 1d. Build your keep list
Edit `config/keep_list.json` — a flat list of exact card names you want to
keep. Anything read that isn't on this list gets sold.

```json
{ "keep": ["Wayne Gretzky", "Connor McDavid"] }
```

OCR text is fuzzy-matched directly against this list (`ocr.match_threshold`
in `config.json`, default 90) — anything that doesn't clear the threshold
is sold.

## 2. Dry run first — important

Card names that can't be confidently read/matched are **sold by default**
(your choice, since bronze packs are low value). That makes it worth
validating OCR accuracy before trusting it with real sells:

```
python main.py --dry-run --max-packs 3
```

This runs the full read/decide pipeline and logs exactly what it *would*
tap, without actually tapping select/sell/confirm (it still performs the
navigational next-card taps, since otherwise cards 2–6 are never reached).
Check `logs/run_<timestamp>.jsonl` — each card gets a record with the raw
OCR text, the matched name (if any), and the decision. Crop images for
uncertain reads are saved under `logs/crops/<run_id>/` so you can see
exactly what the OCR engine was looking at.

Press **F9** to start, **F10** to stop at any time — the stop flag is
checked before every tap/swipe and sliced into every fixed wait, so it
halts within roughly 0.1s rather than finishing the current pack.

## 3. Go live

Once dry-run output looks right:
```
python main.py --live --once      # one pack, watch it actually sell
python main.py --live             # run continuously until F10 or --max-packs
```

## Troubleshooting

- **"Could not connect to BlueStacks over ADB on any candidate port"** —
  double check ADB is enabled in BlueStacks (1a) and that the port shown
  there is reachable; add it to `adb.candidate_ports` in `config.json` if
  it's unusual.
- **"Connected device resolution ... does not match the calibrated
  resolution"** — BlueStacks' display resolution changed since calibration.
  Either fix it back, or re-run `python -m bwm.calibration_tool`.
- **F9/F10 don't do anything** — the `keyboard` library installs a low-level
  global hook; try running from a plain (non-elevated) terminal first, and
  make sure no other app is already bound to those keys.
- **A tap registers as a press-and-hold instead of a quick tap** (e.g. the
  game opens a preview/tooltip instead of advancing) — raise or lower
  `adb.tap_duration_ms` in `config.json` (default 30ms). Taps are sent as a
  same-point swipe with this exact duration rather than a plain `input tap`,
  since some Android/BlueStacks builds give `input tap` a longer built-in
  press than the game's tap-vs-hold threshold expects.
- **OCR reads garbage consistently** — OCR isolates the name text by color
  (the game renders it in one consistent gold/yellow, regardless of the
  background art behind it) rather than by grayscale brightness, so it's
  usually robust to busy card-art backgrounds. If reads are still bad,
  first tighten the `name_crop` rectangle in the calibration tool so it's
  just the glyphs, no surrounding art/border/icons. If the name text isn't
  actually gold/yellow (e.g. a different pack tier), retune `ocr.text_hue_min`
  /`text_hue_max`/`text_sat_min`/`text_val_min` in `config.json` to match -
  sample a real crop's pixel colors (`cv2.imread` + inspect BGR/HSV values)
  to find the right range. If it's still unreliable, set
  `"engine": "easyocr"` under `ocr` in `config.json` (after
  `pip install easyocr`) — the rest of the pipeline is unchanged.
- **A real card name comes back with junk prefixed/suffixed to it** (e.g.
  `"' Reaction"`) — a same-colored UI element (an icon, rarity ribbon, etc.)
  is bleeding into a corner of `name_crop`. Fuzzy matching tolerates this
  fine in practice, but for cleaner reads, tighten `name_crop` in the
  calibration tool to exclude that corner.
- **OCR reads a blurry/mid-transition frame, or the previous card's name** —
  the fixed waits under `timings` (`pack_open_settle_delay_s`,
  `card_advance_settle_delay_s`) are too short for how long the transition
  actually takes on your machine. Bump them up in `config.json` and re-run a
  dry run.
  Conversely, if reads are consistently clean well before the wait ends,
  you can shorten them to speed up the grind.

For a walkthrough of how the current OCR preprocessing (color-based text
masking) was diagnosed and why a couple of tempting alternatives were
rejected along the way, see [docs/OCR_DEBUGGING.md](docs/OCR_DEBUGGING.md).

## Project layout

```
main.py                    CLI entry point
bwm/
  adb_controller.py        ADB connect/tap/swipe/screenshot
  capture.py                region crop utility
  ocr.py                    crop preprocessing + Tesseract/EasyOCR backend
  matcher.py                 fuzzy name resolution -> keep/sell decision
  calibration_tool.py        screenshot-based calibrator (run standalone)
  hotkeys.py                  F9/F10 global start/stop
  run_logger.py                JSONL run log + crop image saving
  macro.py                     the main open/read/decide/sell loop
  config_models.py              config schema + JSON load/save
config/
  config.json                calibrated points/regions/timings (fill in via calibration_tool)
  keep_list.json              card names to keep
logs/                          created on first run
docs/
  OCR_DEBUGGING.md               case study: OCR preprocessing debugging session
```
