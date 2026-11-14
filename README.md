# aula-f75: AULA F75 Max on Linux

Control the AULA F75 Max (Epomaker x AULA) RGB lighting and its 128×128 screen on Linux,
from a command line or a small window.

AULA's protocol was recovered from their own Windows driver (decompiled, never run) and
checked byte-for-byte against USB captures of that driver. See [PROTOCOL.md](PROTOCOL.md)
for the protocol and [DECISIONS.md](DECISIONS.md) for why things are the way they are.

| Feature | 2.4 GHz dongle | USB-C cable |
|---|---|---|
| Lighting effects (19 + off), colour, brightness, speed, direction | yes | yes |
| Per-key colours | yes | yes |
| Screen clock (set to the PC's time) | yes | yes |
| Screen image / animated GIF / text | no (the official app doesn't either) | yes |
| Battery level | yes | no |

**Requires:** Python 3.10 or newer, Tk for the window, and Pillow for screen images. On Arch
that means `python`, `tk` and `python-pillow`, which are already installed on this machine.
Nothing else is needed.

## One-time setup: permission to talk to the keyboard

`/dev/hidraw*` is root-only by default. This udev rule gives the logged-in user access to
the keyboard's vendor interfaces only: commands on the cable and dongle, plus the screen
data interface. The typing interfaces stay root-only, so programs can't read keystrokes
through it.

```sh
cd ~/github-repos/aula-f75-linux
sudo install -m 0644 udev/70-aula-f75.rules /etc/udev/rules.d/70-aula-f75.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
```

Then unplug and replug the dongle (and the cable, if you use it).

Optionally, install the commands on your PATH:
`pipx install --system-site-packages .`, which gives you `aula-f75` and `aula-f75-gui`.
Without that, run everything as `python3 -m aula_f75 …` from this directory, as below.

## First test in the morning

Start with the most harmless step and stop at the first surprise. Every command accepts
`-n`/`--dry-run`, which prints the exact bytes without sending anything, and `-v`, which
logs every report and reply.

1. **Tests and dry run (sends nothing):**
   ```sh
   python3 -m unittest discover -s tests          # expect: OK (skipped=1)
   python3 -m aula_f75 -n color ff0000            # prints the one 32-byte report it would send
   ```
2. **Check permissions after the udev step:**
   ```sh
   python3 -m aula_f75 list
   ```
   The `dongle if3 page 0xff60 commands` line should say `ok`. If it says `no access`,
   replug the dongle or log out and back in.
3. **One static colour over the dongle** (the safest real command: a single report, the
   same one the official app sends when you pick "Static"):
   ```sh
   python3 -m aula_f75 -v color ff0000
   ```
   The keys should turn red. If you see `warning: no reply …`, press a key to wake the
   keyboard and make sure its switch is on 2.4 GHz.
4. **More lighting:**
   ```sh
   python3 -m aula_f75 color 00ffff -b 3
   python3 -m aula_f75 effect breath -c ff8800 -s 2
   python3 -m aula_f75 effect ripples --colorful
   python3 -m aula_f75 keys --base 000000 w,a,s,d=ff0000 esc=00ff00 space=0000ff
   python3 -m aula_f75 off
   python3 -m aula_f75 effect rolling -c ff0000 --colorful   # the factory default look
   ```
5. **Clock and battery over the dongle:**
   ```sh
   python3 -m aula_f75 clock      # the screen clock jumps to this PC's local time
   python3 -m aula_f75 battery
   ```
6. **USB-C cable:** plug it in, then run `python3 -m aula_f75 list`. You should see
   `usb-c if2 … screen data ok` and `usb-c if3 … commands ok`.
   ```sh
   python3 -m aula_f75 --link wired color 00ff00
   python3 -m aula_f75 text "hello"            # small upload, 9 chunks, about 2 s
   python3 -m aula_f75 image ~/Pictures/some.gif
   ```
   - A large GIF takes a while: 255 frames is about 2040 chunks, roughly 5 minutes, the
     same as the official app.
   - Don't unplug the cable during an upload. If one is interrupted, replug the cable
     before retrying.
7. **The window:**
   ```sh
   python3 -m aula_f75.gui
   ```
   It has a "Dry run" checkbox at the top right.

## Commands

```
aula-f75 list                                    interfaces and permission status
aula-f75 color RRGGBB [-b 0-5]                   static colour
aula-f75 effect NAME [-c RRGGBB] [--colorful] [-b 0-5] [-s 0-5] [-d right|down|left|up]
aula-f75 off
aula-f75 keys [--base RRGGBB] KEY[,KEY…]=COLOUR …   per-key; names in aula_f75/layout.py, or LED numbers
aula-f75 keys --pattern NAME|C1,C2,… [--axis x|y|diagonal|radial] [KEY=COLOUR …]   gradient over the keys
aula-f75 react ripple|glow|heatmap|speed [-c rainbow|RRGGBB] [--base PATTERN] [--base-level 0-100]   USB-C only, Ctrl+C stops
aula-f75 clock [--at 2026-11-15T07:30:00]
aula-f75 image FILE [--fit fit|fill|stretch] [--frame-ms 30-500]      USB-C only
aula-f75 text "line one\nline two" [--fg white] [--bg black]          USB-C only
aula-f75 battery                                  dongle only
global options, before or after the command: --link wired|dongle, -n/--dry-run, -v
```

- **Effects:** off, static, single-on, single-off, glittering, falling, colourful, breath,
  spectrum, outward, scrolling, rolling, rotating, explode, launch, ripples, flowing,
  pulsating, tilt, shuttle.
- **Key patterns:** rainbow, rainbow-rows, synthwave, sunset, ocean, fire, aurora, forest,
  ice, candy, neon, or your own gradient (`--pattern ff0000,ffffff,0000ff --axis radial`).
  Keys you list after it override it: `keys --pattern ocean w,a,s,d=red`. The GUI's Per-key
  tab has the same presets ("Use pattern"), and you can paint over them before applying.
- **Reactive (USB-C):** `react ripple` (rings roll out from each key), `glow` (keys light and
  fade), `heatmap` (keys warm up with use), `speed` (board colour follows typing speed). Runs
  until Ctrl+C; the keys keep the last frame afterwards until you set another look.
- **Colours:** hex `ff8800` or a basic name (`red`, `orange`, …).
- **Link choice:** the link is picked automatically, the cable first when both are
  present. Use `--link` to force one.

## Troubleshooting

- **`no permission on /dev/hidrawN`:** the udev rule isn't active. Repeat the setup and
  replug. `aula-f75 list` shows which node is blocked.
- **The rule doesn't match your cable's screen interface:** for example, `list` shows
  `screen data no access` on an interface other than 2. Temporarily run once with `sudo`
  to confirm everything else works, then report the `list` output.
- **`warning: no reply … through the dongle`:** the keyboard is asleep, out of range, or
  switched to Bluetooth or cable mode.
- **Image looks glitchy over USB-C:** other users report this is the keyboard firmware.
  Unplugging the cable after the upload, or using pure black backgrounds, helps.

## What this tool will never do

It never sends firmware-update, bootloader, flash or factory-reset commands. That
includes the official app's dongle "Factory Reset" (`0x0F`) and "Reset Keyboard" (`0x1F`)
reports. Some community tools send `0x0F` before every colour change by mistake; see
PROTOCOL.md §9. Every packet passes an allowlist (`aula_f75/protocol.py: check_step`)
before it reaches the device.

## Layout

```
aula_f75/protocol.py   packet builders (pure, no I/O) + safety allowlist
aula_f75/device.py     runs packets over hidraw with the official timing
aula_f75/hid.py        sysfs discovery, hidraw ioctls, dry-run transport
aula_f75/screen.py     image/GIF/text -> 128x128 RGB565 frames (Pillow)
aula_f75/layout.py     per-key LED map, generated from the official layout XML
aula_f75/patterns.py   gradient presets laid over the key positions
aula_f75/react.py      reactive effects: key presses in, live frames out
aula_f75/cli.py, gui.py
tests/test_protocol.py byte-exact vectors from official captures and the decompiled app
tools/pcap_usb.py      USBPcap reader used to pull those vectors
```
