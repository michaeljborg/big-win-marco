"""Big Win Hockey bronze pack farmer macro.

Package layout:
    adb_controller   - ADB connect/tap/swipe/screenshot for BlueStacks
    capture          - region cropping + frame-diff wait_for_change/wait_for_stable
    ocr              - crop preprocessing + swappable OCR backend
    matcher          - fuzzy name resolution -> keep/sell decision
    calibration_tool - Tkinter screenshot-based calibrator (run standalone)
    hotkeys          - global start/stop hotkeys backing a thread-safe stop flag
    run_logger       - JSONL run log + crop image saving
    macro            - PackFarmerStateMachine, the main loop
    config_models    - dataclass config schema + JSON load/save
"""

__version__ = "0.1.0"
