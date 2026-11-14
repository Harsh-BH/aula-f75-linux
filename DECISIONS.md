# Decisions

One entry per judgment call made while working unattended (2026-11-14 night). The entries
run in roughly chronological order.

## Research and sources

1. **Build on community work, but treat it as a lead, not as truth.** About 20
   open-source F75 Max projects exist. Most are ports of one Swift project (VitalyArt), so
   their agreement is not independent evidence. Every byte this app sends was instead
   checked against two sources: the decompiled official `DeviceDriver.exe` [BIN], and USB
   captures of the official app [CAP] published in Ghost-CR/F75_Initializer. PROTOCOL.md
   tags each fact with its source.

2. **Official software:** Epomaker's download page links
   `AULA_F75_Max_Gasket_Mechanical_Keyboard_Driver_1.0.0.5.zip` (sha256
   `98dd00c6e3d1717fcbaeb6ab9829d2c9d3359361d17476891a4e801461144581`). Its
   `config.xml` lists exactly our dongle (05AC:024F), so it is the right binary. AULA has
   no WebHID driver for this model. The installer is Inno Setup around a native 32-bit MFC
   app, so I used innoextract plus Ghidra rather than an asar or .NET decompiler.

3. **Tools without root.** innoextract was unpacked from the Arch package into the session
   scratchpad. Ghidra 12.2 lives in `~/aula-re/`: it refuses project paths with a `.`-dir,
   so not `~/.cache`, and `/tmp` is RAM-backed with only about 3 GB free. Nothing was
   installed system-wide. `~/aula-re/` (about 1 GB, including the decompiled C) can be
   deleted once you've reviewed this. `~/aula-re/fn.sh FUN_xxxxxxxx` prints any function
   cited in PROTOCOL.md.

4. **The official software was never executed.** Only static analysis: unzip, innoextract,
   strings, Ghidra headless. Every Python run that read its files used `python3 -I` from a
   separate directory.

## Safety

5. **Dongle report `0x0F` is the official Factory Reset, so it is never sent.** VitalyArt
   calls it `rgbCommitReport` and sends it before every RGB change; c0deJedi copied that.
   The decompile shows the "Factory Reset" dialog (string 167) queuing worker task `0xe`.
   In 2.4 GHz mode `FUN_00434fa0` sends exactly that report, then re-applies the lighting.
   The official lighting path (`FUN_0042b270`) sends a single `05 10` report. I follow the
   official app, so lighting changes may take a moment longer to show than they do with
   those tools; that is fine. "Reset Keyboard" (`0x1F`) is excluded the same way.

6. **Allowlist, not blocklist.** `protocol.check_step` lets through only the opcodes this app
   builds. On the cable: `04` + {18, 13, 02, f0, 28, 23, 72}. On the dongle: {05, 0c, 14,
   20}. It also blocks the bootloader magic. `device.Keyboard.run` is the only I/O path and
   calls it on every step. Macros, keymaps and settings would need an explicit change with
   a [BIN] source.

7. **`04 f0` is sent where the official app sends it** (after lighting and per-key writes).
   It commits settings in the keyboard, the way the official app does on every apply. It is
   not a firmware or flash-programming command. Leaving it out would change the device's
   behaviour (settings lost on power-off) and break byte-equality with the captures.

8. **c0deJedi's "clear display before every upload" is not used.** It is the macro step of
   the official factory reset (`04 19`, `04 15 [8]=08`, zero pages), and it erases your
   macros. The official upload doesn't do it.

9. **Screen upload over the dongle is not implemented**, even though the shared code base has
   one (`FUN_004231d0`). The F75 Max layout disables the screen menu over 2.4 GHz
   (`menu_wireless screen="0"`), so the official app never sends it to this keyboard, and
   untested firmware behaviour isn't worth the risk. Clock and lighting do work over the
   dongle, because the official app does them there too.

10. **udev rule opens only the vendor interfaces.** Cable interfaces 2–3 and dongle interface
    3, matched by DEVPATH. That avoids giving every user program raw access to the typing
    interfaces, which would allow keylogging. Cable interface numbers come from Ghost-CR's
    Windows device paths (MI_02/MI_03) plus `wIndex=3` in the captures; I couldn't see the
    cable tonight. If interface 2 is wrong, `aula-f75 list` shows `no access`, and
    README → Troubleshooting covers it. A test checks the rule's globs against real sysfs
    paths.

11. **The command-ack check is stricter than the official app.** The official app reads the
    GET_FEATURE reply but never checks it. This app stops a sequence when byte 3 isn't
    `01`, after one extra 35 ms re-read in case Linux returned too early, so we never stream
    an image into a keyboard that just said no. Missing screen-chunk acks are tolerated
    like the official app (it waits 300 ms; I wait 1 s), and you get one warning with the
    count.

12. **A missing dongle echo is a warning, not an error.** The official app polls for it on
    every report and ignores a timeout. Silently printing "done" would hide the most likely
    morning problem (keyboard asleep), and making it an error could misfire if some
    firmware doesn't echo.

## Behaviour choices

13. **Screen slot = 1.** The official app sends the selected list entry + 1. The capture has
    2 because that user had the second entry selected; the default UI gives 1, the layout
    has `gif_count="1"`, and VitalyArt and c0deJedi use 1 on hardware. The clock packet
    carries the same slot byte. It is still a `slot=` parameter in `protocol.py`.

14. **Image fitting defaults to "fit" (letterbox on black)**, which is what the official app
    does: [CAP] frame 0 is 640×360 scaled to rows 28–99. "fill" and "stretch" are options.
    Scaling uses Pillow's LANCZOS rather than GDI+, so pixels differ slightly from the
    official app. Everything else is byte-identical, which the full-replay test proves.

15. **Frame delays:** clamped to the official UI's 30–500 ms, then `max(1, ms // 2)` as in
    `FUN_00422930`. The capture's delay bytes equal `gif_ms // 2` for all 105 frames.
    Animations with longer frames are clamped rather than frames being duplicated; that is
    simpler, and the official app also caps at 500 ms.

16. **Auto link prefers the cable** when both are present, because everything works over it.
    Screen and battery commands pick the link they need automatically.

17. **Per-key LED names come from the official `rgb-keyboard.xml` (80 keys).** Raw indices
    are accepted too, since the official read-back also lights 98 (probably right Ctrl),
    110 and 111, which the XML doesn't name. Index 143 is refused because its entry
    overlaps the `aa 55` trailer.

18. **Not implemented: settings, key remap, macros, music/ambilight, side light.** You asked
    for lighting and the screen. The bytes for the rest are documented in PROTOCOL.md §8.
    Music mode means host-side audio capture streaming per-key frames at 5 ms gaps, which
    is a project of its own. Adding any of these means widening the allowlist on purpose.

19. **No new dependencies.** Python stdlib for hidraw (`fcntl.ioctl`), argparse and tkinter.
    Pillow was already installed and is imported only by the screen code, so lighting works
    without it. Pure-Python RGB565 packing takes about 3 ms per frame, so there is no need
    for numpy. Pillow has no RGB565 packer anyway.

20. **Tests use stdlib `unittest`** with literal hex vectors tagged [CAP] or [BIN]. The
    captures themselves aren't committed: the Ghost-CR repo has no licence, and the GIF is
    third-party art. Set `AULA_CAPTURES=<checkout>` to replay the full official 841-chunk
    upload through the encoder. I ran it tonight and it matches byte for byte.

21. **GUI window size:** under this machine's compositor, new Tk windows open at 636×354
    whatever Tk requests. That is the compositor's choice, so I didn't fight it; resize the
    window to see the log pane.

## After the independent review

An independent agent reviewed the code against the decompile and Linux hidraw semantics. It
found no byte mismatches and no way around the guard or the dry-run flag. It raised these,
all now fixed and covered by regression tests in `DeviceFailureModes`:

22. **The screen interface is optional for everything except uploads.** If it is missing or
    not accessible (for example, if my interface-2 guess in the udev rule is wrong), lighting,
    per-key and clock still work over the cable. `upload_screen` checks for it before
    sending `04 18`/`04 72`, so we never announce chunks we cannot deliver.

23. **One aula-f75 process at a time.** Each hidraw handle takes an exclusive non-blocking
    `flock`, so a cron'd `clock` can't inject `04 02` into a GUI upload. The second process
    gets a clear "in use" error.

24. **The ack check is enforced only where hardware has confirmed the ack:** `04` 18, 13, 02
    and 72 in the official captures, and `04 28` in c0deJedi's clock sync. A "rejected"
    reply to `04 23` (per-key table) or `04 f0` only warns and continues, like the official
    app, because no capture shows how those reply.

## After the first hardware test (2026-11-14, dongle)

25. **The dongle echo wait is 1.5 s, not the official ~305 ms.** On this keyboard the echo came
    after ~23 ms usually, but one time in four after 510-1000 ms, so the official limit raised
    false "no reply" warnings (decision 12). Measured over 25 probes plus 40 real commands;
    after the change, 20 back-to-back runs had no false warning. The keyboard also went fully
    silent once for about a minute while lit, and recovered by itself; the warning covers that.
