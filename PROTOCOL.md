# AULA F75 Max protocol

This is the protocol that AULA's Windows app ("AULA F75 Max Gasket Mechanical Keyboard
Driver", Beta 1.0.0.5) uses to talk to the keyboard. Every fact cites one of the sources
below. `FUN_xxxxxxxx` names refer to the Ghidra 12.2 decompilation of `DeviceDriver.exe`;
the addresses are the image addresses in that file.

## Sources

| Tag | What | Trust |
|---|---|---|
| **[BIN]** | `DeviceDriver.exe` from `AULA_F75_Max_Gasket_Mechanical_Keyboard_Driver_1.0.0.5.zip` (zip sha256 `98dd00c6…1144581`, Epomaker download page), decompiled with Ghidra headless. Analysed statically only, never run. | Ground truth for what the app sends |
| **[MUI]** | `mui.dll` from the same installer (`MUI::LCDViewList::GetImageRGB565Data` @ `1003c8f0`) | Ground truth for pixel format |
| **[CFG]** | `config.xml`, `layouts/rgb-keyboard.xml`, `language/1033.lan` from the same installer | Ground truth for device table, limits and names |
| **[CAP]** | USBPcap captures of the official app driving a real F75 Max over USB-C, published in [Ghost-CR/F75_Initializer](https://github.com/Ghost-CR/F75_Initializer): `docs/captures/rgb_*.pcapng`, `official_guts_upload.pcapng`. Decoded with `tools/pcap_usb.py`. | Ground truth for real wire bytes and timing (cable only) |
| **[DEV]** | Report descriptors of this machine's dongle, `/sys/class/hidraw/hidraw{2..6}/device/report_descriptor` | Ground truth for the dongle's interfaces |
| **[HW]** | This app on the owner's F75 Max (2026-11-14): dongle and cable, every command in README, the GUI | Ground truth for how this keyboard reacts |
| **[COM]** | Community projects, mainly [VitalyArt/Aula-F75-Max-Driver](https://github.com/VitalyArt/Aula-F75-Max-Driver) (MIT) and [rexdotsh/aula-f75-max-screen](https://github.com/rexdotsh/aula-f75-max-screen) | Hardware-tested by others; used only where [BIN]/[CAP] are silent |

## 1. Links and interfaces

| Link | VID:PID | Interface | Usage page / usage | Reports | Used for | Source |
|---|---|---|---|---|---|---|
| USB-C cable | `0c45:800a` | 3 | `0xFF13` / `0x01` | Feature 64 B, no report ID | Commands | [CFG] `config.xml` mode 0; [CAP] all feature requests have `wIndex=3`; [COM] Ghost-CR `PROTOCOL_REFERENCE.md` (Windows path `MI_03`) |
| USB-C cable | `0c45:800a` | 2 | `0xFF68` / `0x61` | Output 4096 B, input 64 B, no report ID | Screen data | [CAP] interrupt OUT ep `0x03` 4096 B, IN ep `0x84` 64 B; [BIN] `FUN_0044f2b0` writes `0x1001` bytes (ID + 4096); [COM] Ghost-CR (`MI_02`) |
| 2.4 GHz dongle | `05ac:024f` | 3 | `0xFF60` / `0x61` | Output 32 B, input 32 B, no report ID | Commands | [CFG] `config.xml` mode 2 `hid_interface="…MI_03"`; [DEV] hidraw5 descriptor `06 60 ff 09 61 … 95 20 … 91 02` |
| 2.4 GHz dongle | `05ac:024f` | 4 | `0xFF59` / `0x61` | Output 64 B, input 64 B | Not used by the official app | [DEV] hidraw6 descriptor; [CFG] only MI_03 is configured |
| Bluetooth | — | — | — | — | No settings channel | [CFG] has no Bluetooth mode entry |

The dongle reports Apple's VID and is bound to `hid_apple` ([DEV] uevent `DRIVER=apple`). That
does not matter for hidraw access.

Which features each link supports in the official app comes from [CFG] `rgb-keyboard.xml`:
`<menu … light_mode="1" user_light="1" custom_light="1" music="1" screen="1"/>` for the cable
and `<menu_wireless … light_mode="1" user_light="1" music="1" screen="0"/>` for the dongle.
**The screen is cable-only in the official app**, although the shared code base contains a
dongle uploader (§6.6).

## 2. Transport

### 2.1 Cable, command interface (0xFF13)
- Every command is a 64-byte payload sent as a 65-byte SET_FEATURE with report ID 0
  ([BIN] `FUN_00451430` calls `HidD_SetFeature(h, buf, 0x41)`).
- Commands are `04 <op> 00 … [8]=arg …`.
- "Read-back" means: sleep `cmd_delaytime`, SET_FEATURE, sleep again, then GET_FEATURE
  (IOCTL `0xB0192`) ([BIN] `FUN_0044eeb0` with `param_3=1`; `FUN_004514d0`). With
  `param_3=0` the app only does the SET.
- `cmd_delaytime` is **35 ms** ([CFG] `<cmd_delaytime value="35"/>`). [CAP] shows 35–50 ms
  between steps.
- The reply echoes bytes 0–1 with byte 3 = `01` when the command is accepted, e.g.
  `04 18 00 01` ([CAP] every reply). The official app does not check the reply. This app
  does check it and stops if byte 3 is not `01`.
- **Payloads longer than 64 bytes** are sent as consecutive 64-byte SET_FEATUREs with
  `cmd_delaytime` after each, no GET, and up to 10 retries per page ([BIN] `FUN_0044eeb0`,
  `param_2 >= 0x42` branch).

### 2.2 Cable, data interface (0xFF68)
- A screen chunk is one 4096-byte output report: `write()` of `00` + 4096 bytes. The app
  then waits up to **300 ms** for an input report and continues either way ([BIN]
  `FUN_0044f2b0`: `FUN_00451210(…,0x1001)` then `FUN_004512f0(…,0x1001,300)`).
- The keyboard answers each chunk with `01 5a 02 00 …` (64 bytes). [CAP] has 841 acks for
  841 chunks, about 139 ms apart.

### 2.3 Dongle (0xFF60)
- Every command is one 32-byte output report written as 33 bytes with report ID 0.
- **Checksum:** byte 31 = 8-bit sum of bytes 0–30 ([BIN] `FUN_0044f5d0`: sums the 65-byte
  buffer, whose ID byte and tail are 0, into `buf[32]`).
- After writing, the app sleeps 5 ms, then polls the input report (5 ms timeout, 10 ms
  sleep, up to 20 tries) for a reply whose first 3 bytes equal the command's first 3
  bytes. It retries the write once after 10 ms if the write fails ([BIN] `FUN_0044f5d0`).
- Most dongle reports are the cable's data page shifted right by 3 bytes behind a
  `<cmd> 10 00` prefix, with the `aa 55` trailer at bytes 17–18 (§3–§5).

## 3. Lighting effect

Task 9 in the app's worker ([BIN] `FUN_004342f0`): cable `FUN_0042b0d0`, dongle
`FUN_0042b270`.

### 3.1 Effects
Effect numbers 1–19 are the official names, strings 521–539 in [CFG] `1033.lan`. [CAP]
`rgb_mode_off_static_breathing_wave_rainbow.pcapng` sends all of them, 0x00–0x13. The
factory default is 11 ([CFG] `default_mode="11"`, and the first transaction in [CAP]).

| # | Name | # | Name | # | Name | # | Name |
|---|---|---|---|---|---|---|---|
| 0 | off | 5 | falling | 10 | scrolling | 15 | ripples |
| 1 | static | 6 | colourful | 11 | rolling | 16 | flowing |
| 2 | single-on | 7 | breath | 12 | rotating | 17 | pulsating |
| 3 | single-off | 8 | spectrum | 13 | explode | 18 | tilt |
| 4 | glittering | 9 | outward | 14 | launch | 19 | shuttle |

- `0x80` is the per-key "user light" mode (§4).
- Brightness and speed are 0–5 ([CFG] `brightness_max="5" speed_max="5"`; defaults 5 and 3).
- Direction is 0 right, 1 down, 2 left, 3 up (order of `img_direction_*` in the UI; [COM]
  VitalyArt `WirelessAulaDevice.swift`).
- "Colorful" (rainbow instead of the chosen colour) is a flag ([CFG] string 80).

### 3.2 Cable sequence ([BIN] `FUN_0042b0d0`, byte-identical in [CAP])
```
04 18 00…              read-back
04 13 00 00 00 00 00 00 01 00…   read-back
MM RR GG BB 00 00 00 00 CF BR SP DI 00 00 aa 55 00…   SET only
04 02 00…              read-back   (reply 04 02 00 01 xx 02)
04 f0 00…              SET only
```
For effect 0 the app sends an all-zero page with only `aa 55` at 14–15 ([BIN] the colour
fields are filled only `if mode != 0`; [CAP]). Colour bytes are R, G, B from the low byte
of a Windows `COLORREF` ([CAP]: red = `ff 00 00`, green = `00 ff 00`, blue = `00 00 ff`).

### 3.3 Dongle report ([BIN] `FUN_0042b270`)
```
05 10 00 MM RR GG BB 00 00 00 00 CF BR SP DI 00 00 aa 55 00 … 00 CK
```
This is a single report. **No `0x0F` report is sent before it** (see §9).

## 4. Per-key colours ("User Lighting")

Task 0xb, [BIN] `FUN_00434a40`. The table is 576 bytes (`0x240`) because the layout has
`rgb_keyboard="1"` ([BIN] `param_1+0x7ac != 0`). Entry `i` sits at offset `4*i` and holds
`i R G B`. Unassigned entries stay `00 00 00 00`. `aa 55` goes at offset 574.

LED indices are the `light_index` attributes in [CFG] `layouts/rgb-keyboard.xml` (Esc=1,
F1–F12=2–13, \`=19, …), copied into `aula_f75/layout.py`.

**Cable:**
1. Switch to mode 0x80 ([BIN] `FUN_0044b8f0`): `04 18`(rb), `04 13 [8]=01`(rb),
   page `80 00 00 00 00 00 00 00 00 BR 00 00 00 00 aa 55`, `04 02`(rb), `04 f0`.
2. Write the table: `04 18`(rb), `04 23 [8]=09`(rb), the table as 9 pages, `04 02`(rb),
   `04 f0`(rb).

**Dongle:**
1. Mode report `05 10 00 80 00 00 00 00 00 00 00 00 BR 00 … aa 55@17 … CK`.
2. 21 reports `14 LL NN <28 table bytes> CK`, where NN is the packet number 0–20 and
   LL = `0x1c`, or `0x10` on the last packet. The app sleeps 2 ms after each.

## 5. Clock (screen clock face)

Cable [BIN] `FUN_004238f0`, dongle [BIN] `FUN_00423a20`. The values come from Windows
`GetLocalTime`, so they are local time.
```
cable:  04 18(rb)  04 28 [8]=01 (rb)
        00 SL 5a YY MM DD hh mm ss 00 WD 00 … aa 55@62   (read-back; reply is an echo, no status)
        04 02(rb)
dongle: 0c 10 00 00 SL 5a YY MM DD hh mm ss 00 WD 00 00 00 aa 55 … CK
```
- `YY` = year % 2000. `WD` = day of week with Sunday = 0 (`SYSTEMTIME.wDayOfWeek`).
- `SL` = the selected screen-list entry + 1, which is 1 in the default UI.
- [COM] VitalyArt sends the same bytes with `SL=1` and reports that it works on hardware.

## 6. Screen (128×128 TFT)

Task 0x10: cable [BIN] `FUN_00422930`, dongle `FUN_004231d0`. Limits come from [CFG]:
`<screen gif_headlength="256" gif_maxframes="255" gif_count="1" width="128" height="128"/>`.
The UI allows 30–500 ms per frame (string 807) and at most 255 frames (string 802).

### 6.1 Stream
```
offset 0          frame count N (1..255)
offset 1..N       one delay byte per frame = max(1, delay_ms / 2)  (integer division)
offset N+1..255   0xFF
offset 256        frame 0, then frame 1, …  each 128*128 RGB565 little-endian (32768 B)
end               0xFF up to the next multiple of 4096
```
- [BIN] `FUN_00422930` allocates `total + 0x1000` bytes, fills them with `0xFF`, writes
  byte 0 and the delays, then copies each frame from `GetImageRGB565Data`.
- [CAP] matches exactly: N=105, delays 15/20 for the GIF's 30/40 ms, `0xFF` fill, and 3840
  bytes of `0xFF` tail.
- **Chunk count** = ceil((256 + N·32768) / 4096).

### 6.2 Pixels ([MUI] `GetImageRGB565Data` @ `1003c8f0`)
1. The frame is drawn with GDI+ (`GdipDrawImageRectI`) onto a 128×128 ARGB bitmap cleared
   to black.
2. Each pixel is packed by truncation: `lo = (G&0xFC)<<3 | B>>3`, `hi = (R&0xF8) | G>>5`.
   This is standard RGB565, little-endian.

[CAP] confirms this: frame 0 of a 640×360 GIF is letterboxed to rows 28–99 on black, and
all non-black pixels decode as exact greys only when read little-endian.

### 6.3 Cable sequence ([BIN] `FUN_00422930`, byte-identical in [CAP])
```
04 18(rb)
04 72 SL 00 00 00 00 00 CL CH 00…  (rb)    SL = list entry + 1, CH:CL = chunk count
chunk × count   (0xFF68, wait ≤300 ms for 01 5a 02 each)
04 02(rb)
```
[CAP] contains `04 72 02 … 49 03`: slot 2, 841 chunks. There is no `04 f0` in this
sequence. This app uses slot 1, the default selection. [COM] c0deJedi and VitalyArt use 1
on hardware. [HW] An upload to slot 2 is accepted but simply replaces the picture on the
same screen page; it does not add a second page. The firmware's other pages (clock
face, status) cannot be themed from the stock protocol.

### 6.4 Timing
The official app sends the next chunk as soon as the ack arrives. One 105-frame GIF took
117 s ([CAP]).

### 6.5 Warnings from community testing
- Do not send `04 02` after an incomplete chunk stream ([COM] Ghost-CR, rexdotsh).
- Never let two programs upload at once ([COM] rexdotsh).

### 6.6 Dongle upload, present in the code but not used here
[BIN] `FUN_004231d0` sends a header `7f 03 00 SL N0 N1 N2 …` (N = 24-bit packet count),
then N reports `(0x80|i>>16) i_lo i_mid <28 stream bytes> CK`. The F75 Max layout
disables the screen menu over 2.4 GHz (`menu_wireless screen="0"`), so the official app
never runs this for this keyboard. This app does not implement it (DECISIONS.md).

## 7. Battery (dongle only)

[BIN] `FUN_00435890`, polled every 15 s in 2.4 GHz mode: `20 01 00 … CK`. The reply
echoes `20 01 00`, and byte 3 is the charge in percent, clamped to 100. Over the cable
the app shows no battery.

## 8. Other features in the official app, not implemented here

| Feature | Bytes | Source |
|---|---|---|
| Key response, sleep time, Win/Alt-Tab/Alt-F4 lock, Fn layer | cable `04 18`, `04 17 …`, page, `04 02`; dongle `07 10 00 …` | [BIN] `FUN_00414020`, `FUN_00414290` |
| Key remap (base and Fn layer) | cable `04 18`, `04 11`/`04 27 [8]=09`, 576 B, `04 02`, `04 f0`; dongle `FUN_00418c70` | [BIN] `FUN_004183d0` |
| Macros | `04 19`, `04 15 [8]=…`, pages, `04 02`; dongle `09 1c …` | [BIN] `FUN_0042d6d0`, `FUN_0042dc50` |
| Music / ambilight (host streams per-key colours) | `04 20 …` fast path (5 ms gaps); dongle `0b 1c …` | [BIN] `FUN_00427dc0`, `FUN_004329c0`, `FUN_0044f0a0`, `FUN_00432c20` |
| Live LED read-back for the preview | `04 f5 [8]=09`, then 9 GET_FEATUREs | [BIN] `FUN_0042aeb0`; [CAP] polled about every 150 ms |
| Side light | `05 01 00 (mode+0x1f)` | [BIN] `FUN_004349c0`. The F75 Max has `sidelight="0"`. |

## 9. Commands this app never sends

These are listed so that nobody adds them by accident. `aula_f75/protocol.py` refuses
anything outside an allowlist (`check_step`), and a test enforces it.

| Bytes | What it does | Source |
|---|---|---|
| dongle `0f 00 … CK` | **Factory Reset** ("Factory reset will clear all data") | [BIN] string 167 → task `0xe` → `FUN_00434fa0`: in 2.4 GHz mode it sends report `0x0F`, then re-applies lighting. [COM] VitalyArt's `rgbCommitReport`, and c0deJedi's port of it, send this before every colour change. Do not copy that. |
| dongle `1f 00 … CK` | **Reset Keyboard** ("Resetting the keyboard will clear all keyboard data") | [BIN] string 165 → task `0xd` → `FUN_004342f0` |
| cable factory reset | Rewrites macros, both key layers, per-key table, lighting and settings with defaults | [BIN] `FUN_00434fa0` cable branch. The `04 19`, `04 15 [8]=08`, zero-pages sequence that [COM] c0deJedi calls "clear display" is its macro step. |
| cable `aa 42 89 5a ff 71 62 cc 00…` | Jumps to the bootloader; the keyboard re-enumerates as `0c45:7140` | [COM] elibosley `scripts/keyboard_bootcheck.py` |
| firmware update | Done by a separate `FirmwareUpdateTool.exe` that the app downloads and starts | [BIN] strings `%s\temp\FirmwareUpdateTool.exe` |
| `04 02` after a partial screen stream | Leaves the screen state broken until replug | [COM] Ghost-CR, rexdotsh |
