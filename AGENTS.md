# Instructions for coding agents

## Start here

Read README.md, ARCHITECTURE.md, CONTRIBUTING.md, and CHANGELOG.md. This is a small Python 3.10+ macOS CLI project. All tracked documentation, user-facing CLI output, source comments, and tests must be in English. Preserve behavior when translating text.

Run safe verification with `python3 -m unittest discover -v` and `git diff --check`. Tests mock hardware and need no Homebrew tools, macOS frameworks, or display session. Do not add dependencies just to run existing tests. Do not run display-changing commands as part of automated tests or CI.

## Non-negotiable implementation invariants

- Never disconnect the built-in display. Off requires an active built-in screen.
- Use displayplacer for discovery only. Do not restore displayplacer off/on: it previously left the external display unable to return.
- Preserve the tested direct CGSConfigureDisplayEnabled connection workaround. Its transaction uses option 0; layout uses CGConfigureDisplayOrigin with forSession=1. Do not unify these options without evidence.
- Persist UUID, numeric ID, and complete layout before disconnect. Do not overwrite a pending layout with a partial active-display set. Reject stale IDs that now belong to another active display.
- Confirm outcomes with fresh reads; a successful API return alone is insufficient.
- Keep the toggle threshold at 0.75: below it targets 1.0, at/above it targets 0.5. Read the current main screen, not a stored brightness flag.
- Brightness must work for the MacBook alone without opening a DDC adapter. Unknown external displays must fail before changes.
- After on and layout restoration, copy the MacBook's live brightness to the external display without toggling or changing the MacBook. Keep on idempotent for connection state and retryable for brightness sync failures.
- Read the DDC maximum; do not hardcode a 100-point scale. Keep verification, best-effort rollback, bounded retries/timeouts, and the shared brightness lock.
- Do not add a daemon, software dimming, or change auto-brightness/HDR settings implicitly.

## Hardware and privacy

Do not run off/on/toggle/half/max/sync or recovery --apply without authorization to affect the user's displays. Never leave a display disconnected after a hardware test that disconnected it. Preserve the starting layout and record exactly what was verified. Read-only list/status are diagnostics, but their output contains machine identifiers: do not publish raw output.

Never stage .brighty-state.json, .brighty-state.tmp, .brightness.lock, .local-notes/, caches, credentials, or personal system settings. Do not commit real display UUIDs, serials, or absolute home-directory paths in docs or fixtures. Do not remove ignored local state while preparing a release.

## Scope and handoff

Keep changes focused. Update docs alongside behavior. State whether validation used mocks or physical hardware. The post-on brightness sync still needs an independently recorded real hardware cycle. Do not silently claim support for Intel, arbitrary HDMI adapters, multiple external brightness targets, or cable hotplug monitoring.

See CONTRIBUTING.md for another-machine setup and ARCHITECTURE.md for module boundaries and known limitations.
