# Brighty

**Keyboard shortcuts for an external display and hardware brightness on Apple Silicon Macs.**

Brighty disconnects and restores an external display, restores display positions, and switches brightness between 50% and 100%. Run it from Terminal or the built-in macOS Shortcuts app. No background service, pip dependencies, or paid apps are required.

| Action | Suggested shortcut |
| --- | --- |
| Disconnect / enable the external display | **⌃⌥⌘M** |
| Toggle available displays between 50% and 100% brightness | **⌃⌥⌘B** |

> Tested on a MacBook Pro M1 Pro and an LG 27UL850-W over USB-C. This is an experimental tool that uses private macOS APIs. Compatibility with other displays or future macOS versions is not guaranteed. Disconnecting a display does not cut USB-C power, charging, or the USB hub.

## Features

- Disconnect only the external display while keeping the built-in display active.
- Enable a display that disappeared from discovery using its saved system ID.
- Save display coordinates by UUID before disconnecting and restore them after enabling.
- Choose the brightness target from the **current main macOS display**, rather than a saved flag.
- Adjust MacBook brightness while the external display is disconnected.
- Copy live MacBook brightness to the external display when enabling it through Brighty.
- Verify changes by reading state again and attempt brightness rollback after a partial failure.

## Install on another Mac

Requirements: an Apple Silicon Mac, macOS with a graphical session, Homebrew, Python **3.10+**, and an external monitor supporting DDC/CI over a supported connection. Keep the MacBook lid open when disconnecting the external display.

```sh
brew install python displayplacer m1ddc
git clone git@github.com:username31217/brighty.git
cd brighty
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
python3 brighty.py list
```

Install Homebrew separately using its [official instructions](https://brew.sh/). The m1ddc path in `brightness.py` is currently `/opt/homebrew/bin/m1ddc`, the default Homebrew location on Apple Silicon. Change the `DDC` constant if your installation uses another location.

While the external display is **enabled**, initialize local state:

```sh
python3 brighty.py save-layout
python3 brightness.py status
```

A single external display is selected automatically. If several are connected, specify the UUID reported by `list`:

```sh
python3 brighty.py save-layout --id YOUR_EXTERNAL_DISPLAY_UUID
```

Connection control can select one external display; brightness control currently supports one built-in display and at most one saved external display. The project directory must be writable: local state and a lock file are created next to the scripts. Do not copy `.brighty-state.json` from another machine; create your own.

## Commands

### Connection and layout

```sh
python3 brighty.py list         # displays, UUIDs, system IDs, and coordinates
python3 brighty.py status       # saved external display state
python3 brighty.py off          # save the layout and disconnect the external display
python3 brighty.py on           # enable, restore the layout, and synchronize brightness
python3 brighty.py toggle       # choose off/on using the observed state
python3 brighty.py save-layout  # save the current layout without switching
```

Commands accept `--id UUID` to select a display. First test separate `off` and `on` calls with the lid open and Terminal accessible. Wait for each command to finish. If `on` reports a brightness error, the display may already be enabled: repeat `on` to retry synchronization without reconnecting it.

### Brightness

```sh
python3 brightness.py status  # JSON: main display and brightness in the range 0…1
python3 brightness.py half    # set available displays to 50%
python3 brightness.py max     # set available displays to 100%
python3 brightness.py toggle  # choose the opposite target using the main display
python3 brightness.py sync    # copy current MacBook brightness to the external display
```

| Current main-display brightness | New brightness of available displays |
| --- | --- |
| 0% up to, but not including, 75% | 100% |
| 75% through 100%, inclusive | 50% |

Exactly 75% is equidistant from the two targets; the tie-breaking rule is **75% → 50%**. Examples: 0% → 100%, 50% → 100%, and 90% → 50%.

With only the MacBook available, no DDC request is sent to the external display. When the external display returns through `on` or the connection shortcut, its brightness is copied from the MacBook: 50% stays 50%, 100% stays 100%, and intermediate values are copied too. The MacBook itself is not changed. Post-`on` copying always uses the MacBook as the source; normal `toggle` uses the main macOS display, which may be external.

50% means half of each display's hardware control range, not matching nits or perceived brightness. DDC uses the monitor's actual maximum and rounds to the nearest integer; on the tested LG, half is 50 out of 100.

## Set up keyboard shortcuts

macOS shortcuts live outside Git. Create them on each machine; checking out the repository does not assign keyboard shortcuts automatically.

1. Open Shortcuts → Settings → Advanced → **Allow Running Scripts**.
2. Create **Toggle Monitor** with a **Run Shell Script** action, Shell **/bin/zsh**, and Run as Administrator disabled.
3. Paste the following, replacing the checkout path with your own:

```sh
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
/opt/homebrew/bin/python3 "/absolute/path/to/brighty/brighty.py" toggle
```

4. In **ⓘ → Details → Add Keyboard Shortcut**, assign **Control+Option+Command+M**, then press Tab to leave the shortcut field.
5. Create **Toggle Brightness** with the equivalent action and **Control+Option+Command+B**:

```sh
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
/opt/homebrew/bin/python3 "/absolute/path/to/brighty/brightness.py" toggle
```

macOS enables Quick Action / Services Menu when a keyboard shortcut is assigned. Check for conflicts on your machine and test the first execution using Run. macOS may request access to the script's folder, such as Documents. To change the shortcut, select Run with and enter a new combination; clear it with Delete/Backspace to remove it. Deleting the shortcut does not delete the project. Update absolute paths in the actions after moving your checkout.

The scripts run directly from your checkout. Updating those files updates your local installation immediately; no build or reinstall step is required. Keep the same checkout path to preserve existing shortcut actions.

## Recovery and troubleshooting

If the external display does not return:

```sh
python3 brighty.py on
```

### Notifications

Every display or brightness change raises a macOS notification describing what happened, for example **Brightness 50%** — "LG 50%, MacBook 50%", **External display on** — "Layout restored. LG brightness set to 50.0% to match the MacBook.", or **External display off**. Failures raise a **Brighty error** notification with the error text; when started from Shortcuts, Shortcuts also shows its own script-error notification. Read-only `list` and `status` do not notify. Set `BRIGHTY_NOTIFY=0` to disable notifications, for example in scripts. Notifications use `osascript` and appear only if macOS allows notifications for it.

Every run of `brighty.py`, `brightness.py`, and `recover_display.py` appends one line with its outcome and duration to `.brighty.log` next to the scripts. The file is ignored by Git, trimmed automatically, and omits `list` output. Use it to see why a keyboard shortcut failed:

```sh
tail -n 20 .brighty.log
```

If the saved numeric ID is missing or stale, a separate recovery command can attempt enabling displays:

```sh
python3 recover_display.py                # diagnostics only
python3 recover_display.py --apply       # use the saved ID
python3 recover_display.py --all --apply # try inactive IDs 1…10
```

The last command may enable other disabled displays. It is not intended for ordinary toggling. If recovery fails, save your work and restart the Mac. There is no automatic restart, deletion of system settings, or connection control through displayplacer.

| Symptom | Check |
| --- | --- |
| Empty display list | Run from a regular Terminal in the current graphical session, outside a restricted sandbox |
| Unknown external display | Run `list`, then `save-layout --id UUID` with the intended display enabled |
| DDC error | Cable/adapter, the monitor's DDC/CI setting; `m1ddc display list`, `m1ddc display UUID get luminance` |
| Display enabled but brightness not copied | Retry `brighty.py on` or `brightness.py sync` once DDC is ready |
| Coordinates not restored | The display set must match the saved layout; retry `on` |
| Keyboard shortcut does not work | Check Run, absolute paths, Allow Running Scripts, and shortcut conflicts |
| Shortcuts shows "an error occurred while running the script" | A "Brighty error" notification carries the same text; the last lines of `.brighty.log` keep it. Shortcuts hides the script's error text from the system log |

## Limitations and validation status

- Hardware test setup: Apple Silicon MacBook Pro M1 Pro + LG 27UL850-W over USB-C. Intel, arbitrary HDMI adapters, and other monitors have not been tested.
- Extended-desktop coordinates are restored. Mirroring is rejected; resolution, scaling, rotation, window positions, and calibration are not saved.
- Numeric IDs can change after reconnecting or restarting. A missing display may be disabled or unplugged; private APIs can change.
- There is no background observer. After physically reconnecting without Brighty, run `on` or `sync`. Auto-brightness, HDR, and power-saving settings may change brightness later.
- Overlapping brightness calls are rejected. Device updates are sequential and rollback is best effort. Do not run off/on and brightness changes simultaneously.
- macOS activity does not prove visible output, monitor standby, or power savings.
- Hardware validation covers off/on, coordinate restoration, a two-display 100% → 50% → 100% brightness cycle, brightness invocation from Finder using the keyboard shortcut, and MacBook-only toggling. The new post-return brightness synchronization path has unit coverage; a separate real hardware cycle for that path has not yet been confirmed.

## Development

```sh
python3 -m unittest discover -v
```

**55 tests** use fake devices and do not change real displays. They require neither Homebrew utilities nor macOS frameworks and can run on Linux or macOS. GitHub Actions runs these checks on Python 3.10 and 3.14. Real hardware checks are separate and require explicit authorization.

- [Architecture and invariants](ARCHITECTURE.md)
- [Contributing and adapting to another Mac](CONTRIBUTING.md)
- [Agent instructions](AGENTS.md)
- [Changelog](CHANGELOG.md)
- [Reporting a vulnerability](SECURITY.md)

## License and dependencies

[MIT](LICENSE). External tools are installed separately under their own licenses: [displayplacer](https://github.com/jakehilborn/displayplacer), [m1ddc](https://github.com/waydabber/m1ddc). Their source code is not bundled in this repository.
