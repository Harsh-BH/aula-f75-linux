# aula-f75-linux

Linux CLI + Tk GUI that drives the AULA F75 Max keyboard's RGB lighting and 128x128 screen over hidraw.

## Stack

Python ≥3.10 stdlib (hidraw ioctls, argparse, tkinter). Pillow only for screen images. No other deps.

## Commands

| | |
|---|---|
| install | none; optional `pipx install --system-site-packages .` |
| dev | `python3 -m aula_f75 -n <command>` (dry run) · `python3 -m aula_f75.gui` |
| test | `python3 -m unittest discover -s tests` (+ `AULA_CAPTURES=<F75_Initializer checkout>` for the full replay) |
| lint / typecheck | none |
| build | none |

Run test before claiming anything works.

## Layout

```
aula_f75/protocol.py  the only place that knows bytes; pure builders returning Steps + check_step allowlist
aula_f75/device.py    the only place that does I/O; every Step goes through check_step first
aula_f75/layout.py    generated from the official rgb-keyboard.xml; regenerate, don't hand-edit
```

## Conventions

- Every protocol fact needs a source in PROTOCOL.md: [BIN] decompiled function, [CAP] official capture, or [COM] repo.
- New packets get a byte-exact test vector in tests/test_protocol.py with the same source tag.
- Judgment calls go in DECISIONS.md.

## Gotchas

- Dongle 0x0F = official Factory Reset, 0x1F = Reset Keyboard. Community repos send 0x0F as a "commit"; never copy that.
- argparse `parents=` shares action objects: a shared default once silently dropped `--dry-run` (see `_global_options`).
- The screen is cable-only (official layout `menu_wireless screen="0"`). Never send `04 02` after a partial chunk stream.

## Don't

- Don't add firmware-update, bootloader, flash, macro-wipe or reset commands, or widen `WIRED_OPS`/`DONGLE_OPS` without a [BIN] source.
- Don't run or execute the official Windows software; static analysis only.
