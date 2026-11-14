# PLAN: AULA F75 Max on Linux

Goal: a Linux app that controls the AULA F75 Max (Epomaker x AULA) RGB lighting and its
128x128 screen, built from the protocol that AULA's Windows software uses. The user will
review it and test it on real hardware in the morning. Tonight I have no write access
to the keyboard (`/dev/hidraw*` is root-only and sudo needs a password).

## Constraints

- The official software is untrusted. I only analyse it statically and never run it.
- Never implement or send firmware-update, bootloader, flash or factory-reset commands.
- Python with stdlib hidraw ioctls. Pillow (already installed) handles images and Tk handles the GUI. No new dependencies.
- Dry-run mode must print the exact bytes. Tests must check packets byte-for-byte against
  what the official software sends.
- Commit to a branch as I go and never push.
- Write every judgment call to DECISIONS.md.

## Phases

### 1. Research (done before this plan was finalised)
- Web and GitHub search turned up about 20 community projects for the F75 Max. Several
  include captures of the official software (`Ghost-CR/F75_Initializer` ships pcapng files).
- The official driver is "AULA F75 Max Gasket Mechanical Keyboard Driver 1.0.0.5". It is an
  Inno Setup installer containing a native 32-bit MFC `DeviceDriver.exe`, not Electron or
  .NET. AULA has no web driver for this model.

### 2. Static analysis of the official software
- Unpack the installer with innoextract into `/tmp/aula-official`. Read `config.xml` and
  `layouts/rgb-keyboard.xml`, which hold the VID/PIDs, interfaces, menu flags per link,
  screen geometry and per-key LED indices.
- Run Ghidra headless (on disk under `~/aula-re`) with a Java script that decompiles
  every function to one C file. Then find the packet builders by their constants:
  `0x72` (screen metadata), `0xAA 0x55` trailers, `0x5A` (time), and calls through the
  `HidD_SetFeature`/`HidD_GetFeature`/`WriteFile` pointers.
- Write down function addresses for PROTOCOL.md citations. List the dangerous commands
  (firmware, reset) by their bytes so the code can refuse them.

### 3. Cross-check with the real device
- Parse the report descriptors in `/sys/class/hidraw/*/device/report_descriptor` and record
  which interface carries which usage page and report sizes, for both dongle and wired mode.
- Compare against the captures in community projects and the decompiled code.

### 4. PROTOCOL.md
- Cover links and interfaces, transport (feature reports versus output reports, acks),
  each command (lighting, per-key colours, clock, screen upload, battery), image format
  and timing.
- Cite a source for each fact: an official-binary function address or file, a capture, or
  a community repo file:line.

### 5. Application (`aula_f75/`)
- `protocol.py` holds pure packet builders with no I/O, plus the image-to-RGB565 stream
  encoder. It is the only place that knows bytes.
- `hid.py` handles hidraw discovery from sysfs, the feature and output report ioctls, and a
  `DryRun` transport that prints bytes instead of sending them.
- `cli.py` provides `list`, `color`, `effect`, `keys` (per-key), `time`, `image`, `battery`,
  and `--dry-run` on everything.
- `gui.py` is a Tk window: effect, colour picker, brightness, speed and direction, image or
  GIF picker with preview, clock sync, and a dry-run checkbox.
- `tests/test_protocol.py` checks the stdlib `unittest` packets byte-for-byte against
  vectors taken from the official app's captures and the decompiled code.
- Refuse to build anything on the dangerous-command list (an explicit guard plus a test).

### 6. Packaging and docs
- `udev/70-aula-f75.rules`: `TAG+="uaccess"` for 0c45:800a and 05ac:024f hidraw nodes.
- README.md: install, the exact sudo commands, and a "first test in the morning" checklist.
  It starts with `list` and a dry run, then one static colour over the dongle, and works up
  to clock and image over the cable.
- CLAUDE.md from the template, under 40 lines.

## Done when

- `python3 -m unittest` passes.
- Every CLI command runs in `--dry-run` without the device and prints the packets.
- The GUI starts and sends nothing in dry-run mode.
- PROTOCOL.md cites every fact, DECISIONS.md explains every judgment call, README.md has
  the morning checklist, and all of it is committed on `feat/initial`.

## Out of scope tonight (and why)

- Firmware update, reset, flash erase and bootloader are forbidden by the user.
- Key remapping and macros: the user asked for lighting and the screen. They can come later
  on the same transport.
- Live hardware testing: there is no device access tonight.
