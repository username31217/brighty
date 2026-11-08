# Contributing and adapting Brighty

Thanks for contributing. Brighty consists of small Python CLIs and requires no build or pip packages. Read the [README](README.md), [architecture](ARCHITECTURE.md), and [AGENTS.md](AGENTS.md) before making changes.

## Checkout and checks

```sh
git clone git@github.com:username31217/brighty.git
cd brighty
python3 -m unittest discover -v
```

Python 3.10+ is required. Linux is suitable for developing pure logic and running mock tests. Real display commands require Apple Silicon macOS and the dependencies listed in the README. Never invoke display-changing CLI commands in CI.

## Adapt to your machine

1. Install the Homebrew dependencies and check `brighty.py list`.
2. With the monitor enabled, create your own state using `save-layout`, with `--id` if necessary.
3. Check m1ddc using the UUID and get/max luminance. Do not assume the maximum is always 100.
4. For nonstandard Homebrew locations, update `DDC` in brightness.py and the paths in Shortcuts.
5. Create your own keyboard shortcuts; the system Shortcuts library is not transferred through Git.
6. Test hardware with the lid open, Terminal accessible, and a way to run `on`.

Do not commit personal UUIDs, system IDs, serial numbers, local paths, display state, or system-settings exports. Use synthetic values such as `internal` and `lg` in tests. Never copy another Mac's runtime state.

## Code changes

- Preserve the separation between the controller, macOS API, and DDC adapter.
- Test new behavior and failure outcomes instead of mirroring implementation details.
- Changes to transactions, CoreGraphics scope, and private APIs need a separate rationale and hardware validation. An API success code does not replace a fresh state read.
- Introduce multiple-external-display and Intel support explicitly; neither is currently claimed for brightness control.
- Update README for CLI changes, ARCHITECTURE for implementation changes, and CHANGELOG for behavior changes.
- Prefer the Python standard library unless a dependency solves a concrete problem. Document runtime and development dependencies.

## Before a commit or pull request

```sh
python3 -m unittest discover -v
git diff --check
git status --short
```

Describe the problem, resulting behavior, tests, and limits of hardware validation. Distinguish mock tests, OS state reads, and the user's visual confirmation. For hardware runs, record the Mac/monitor models, connection, macOS version, and utility versions without unique identifiers.

Known gap: automatic brightness synchronization after LG returns has unit coverage, but a separate physical cycle of the new path has not yet been confirmed. Do not claim hardware validation without new evidence.

All tracked documentation, source comments, CLI output, and tests must be in English.
