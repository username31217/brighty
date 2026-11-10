# Changelog

## Unreleased

### Fewer intermittent Shortcuts errors — 2026-11-10

- Repeated a failed or malformed m1ddc request up to 3 times with 0.3-second pauses before failing a brightness command; timeouts are not repeated.
- Extended post-on brightness synchronization from 3 attempts with 0.5-second pauses to 8 attempts with 1-second pauses. Shortcuts logs showed on and an immediate brightness toggle failing while DDC was not yet ready, then succeeding a few seconds later.
- Added a local `.brighty.log` (ignored by Git) recording each CLI run's outcome and duration, because Shortcuts only shows a generic error and the system log redacts the script's message. `list` output is not recorded.
- 42 unit tests. Validated with mocks and read-only commands only; the retries have not yet been observed on hardware.

### English-only interface and documentation — 2026-11-09

- Translated CLI output, errors, help, test expectations, documentation, and the pull request template into English without changing display-control behavior.
- Documented that scripts run directly from the checkout: updating files updates the local installation without a separate build or reinstall.
- Updated contributor and agent instructions to require English for all tracked text.

### Repository preparation — 2026-11-09

- Added a README for a fresh checkout on another Mac: installation, initialization, CLI, keyboard shortcuts, troubleshooting, and limitations.
- Added contributor and agent instructions, architecture documentation, and hardware-test safety rules.
- Added the MIT License, security-reporting information, a pull request template, and hardware-free CI.
- Excluded local display state, locks, personal diagnostic notes, and Python caches from Git. Documentation contains no real hardware identifiers or personal paths.

### Single-display support and post-on synchronization — 2026-11-08

- status/half/max/toggle work with only the MacBook, without sending DDC requests to an absent external display.
- After on and coordinate restoration, the external display receives current MacBook brightness without toggling or changing the MacBook. Repeated on retries synchronization without reconnecting an active display.
- Synchronization is wired into normal on/toggle and emergency recovery. Added brightness.py sync, a shared lock, and up to three DDC-readiness attempts.
- Brightness discovery uses CGDisplayIsOnline to distinguish an available sleeping display from a software-disconnected one: displayplacer Enabled may become false during sleep.
- 34 unit tests: 12 brightness tests and 22 connection/layout tests.
- Hardware validation covered the MacBook alone changing to 100% and back to 50%. A separate real cycle of post-return external brightness synchronization has not been confirmed; mock checks pass.

### Initial implementation — 2026-11-08

- Added an external-display CLI with UUID-based selection and layout restoration.
- Kept displayplacer for discovery only: its original disconnection path did not reliably enable the monitor again. Connection changes now use a direct macOS API.
- State and coordinates are saved before off; on is verified using fresh reads. A separate recovery tool only enables displays.
- Added hardware brightness through DisplayServices for MacBook and m1ddc/DDC for the external display: 50%/100%, a 75% toggle threshold, normalization using the DDC maximum, result verification, and rollback.
- Added Shortcuts integration with suggested ⌃⌥⌘M and ⌃⌥⌘B combinations.
- On a MacBook Pro M1 Pro + LG 27UL850-W over USB-C, validated off/on, coordinate restoration, a two-display 100% → 50% → 100% brightness cycle, and brightness invocation from Finder using the keyboard shortcut.
