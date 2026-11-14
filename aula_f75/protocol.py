"""AULA F75 Max protocol: pure packet builders, no I/O.

Each builder returns a list of Steps that aula_f75.device executes. The bytes match what
AULA's Windows app (DeviceDriver.exe 1.0.0.5) sends. PROTOCOL.md cites the decompiled
function or USB capture behind every constant.
"""
from collections import namedtuple

WIRED = (0x0C45, 0x800A)    # USB-C cable
DONGLE = (0x05AC, 0x024F)   # 2.4 GHz dongle (reports itself as an Apple keyboard)
WIRED_CMD_PAGE = 0xFF13     # interface 3: 64-byte feature reports, commands
WIRED_DATA_PAGE = 0xFF68    # interface 2: 4096-byte output reports, screen data
DONGLE_CMD_PAGE = 0xFF60    # interface 3: 32-byte output/input reports

CMD_LEN = 64
DONGLE_LEN = 32
SCREEN = 128
HEADER_LEN = 256
FRAME_LEN = SCREEN * SCREEN * 2
CHUNK_LEN = 4096
MAX_FRAMES = 255
CHUNK_ACK = b"\x01\x5a\x02"   # data interface input report after each chunk
TRAILER = b"\xaa\x55"
SLOT = 1                      # screen-list entry + 1; the official UI default (PROTOCOL.md 5, 6.3)

# A Step is one transfer:
#   "cmd"   cable SET_FEATURE of a 04-command; read=True: then GET_FEATURE, byte 3 must be 01
#   "data"  cable SET_FEATURE of one or more 64-byte data pages; read=True: GET after (echo only)
#   "chunk" cable 4096-byte output report on the data interface, then wait for CHUNK_ACK
#   "out"   dongle 32-byte output report, then wait for the echo of its first 3 bytes
Step = namedtuple("Step", "kind data read", defaults=(False,))

MODES = {  # official names, 1033.lan strings 521-539
    0: "off", 1: "static", 2: "single-on", 3: "single-off", 4: "glittering", 5: "falling",
    6: "colourful", 7: "breath", 8: "spectrum", 9: "outward", 10: "scrolling", 11: "rolling",
    12: "rotating", 13: "explode", 14: "launch", 15: "ripples", 16: "flowing", 17: "pulsating",
    18: "tilt", 19: "shuttle",
}
MODE_IDS = {name: number for number, name in MODES.items()}
USER_MODE = 0x80  # per-key colours
DIRECTIONS = ("right", "down", "left", "up")
LEVEL_MAX = 5     # brightness and speed (rgb-keyboard.xml brightness_max / speed_max)
DELAY_MS = (30, 500)  # per-frame delay range the official UI allows (1033.lan string 807)
KEY_TABLE_LEN = 576   # 144 entries x [index, R, G, B], trailer in the last one

# ------------------------------------------------------------------ safety

WIRED_OPS = {0x18, 0x13, 0x02, 0xF0, 0x28, 0x23, 0x72}  # begin, light, apply, save, clock, keys, screen
DONGLE_OPS = {0x05, 0x0C, 0x14, 0x20}                     # light, clock, key table, battery
BOOTLOADER_MAGIC = bytes.fromhex("aa42895aff7162cc")


def check_step(step):
    """Refuse anything that is not a command this app knowingly builds.

    The allowlist excludes the official app's Factory Reset (dongle 0x0F), Reset Keyboard
    (dongle 0x1F), the bootloader jump and every opcode not listed above (PROTOCOL.md 9).
    """
    data = step.data
    if step.kind == "cmd" and (len(data) != CMD_LEN or data[0] != 0x04 or data[1] not in WIRED_OPS):
        raise PermissionError(f"refusing unknown cable command {bytes(data[:2]).hex(' ')}")
    if step.kind == "out" and (len(data) != DONGLE_LEN or data[0] not in DONGLE_OPS):
        raise PermissionError(f"refusing unknown dongle command {bytes(data[:1]).hex()}")
    if step.kind in ("cmd", "data") and any(bytes(data[i:i + 8]) == BOOTLOADER_MAGIC for i in range(0, len(data), CMD_LEN)):
        raise PermissionError("refusing bootloader command")
    if step.kind not in ("cmd", "data", "chunk", "out"):
        raise ValueError(f"unknown step kind {step.kind!r}")
    return step


# ------------------------------------------------------------------ helpers

def cmd(op, arg=0, **fields):
    """64-byte cable command 04 <op> 00 00 00 00 00 00 <arg> ...; more bytes as b<index>=value."""
    data = bytearray(CMD_LEN)
    data[0], data[1], data[8] = 0x04, op, arg
    for key, value in fields.items():
        data[int(key[1:])] = value
    return bytes(data)


def checksum(report):
    """Dongle report: byte 31 = 8-bit sum of bytes 0..30 (FUN_0044f5d0)."""
    report = bytearray(report)
    report[31] = sum(report[:31]) & 0xFF
    return bytes(report)


def dongle(prefix, body=b"", at=3):
    """32-byte dongle report: prefix bytes, body from offset `at`, aa 55 at 17-18, checksum."""
    report = bytearray(DONGLE_LEN)
    report[:len(prefix)] = prefix
    report[at:at + len(body)] = body
    if body:
        report[17:19] = TRAILER
    return checksum(report)


def _check_light(mode, color, brightness, speed, direction):
    if mode not in MODES:
        raise ValueError(f"mode must be 0..{max(MODES)}")
    if not 0 <= color <= 0xFFFFFF:
        raise ValueError("color must be 0x000000..0xFFFFFF")
    for name, value in (("brightness", brightness), ("speed", speed)):
        if not 0 <= value <= LEVEL_MAX:
            raise ValueError(f"{name} must be 0..{LEVEL_MAX}")
    if not 0 <= direction < len(DIRECTIONS):
        raise ValueError(f"direction must be 0..{len(DIRECTIONS) - 1}")


# ------------------------------------------------------------------ lighting effect

def light_body(mode, color, brightness, speed, direction, colorful):
    """MODE R G B 0 0 0 0 COLORFUL BRIGHTNESS SPEED DIRECTION; all zero for mode 0 (FUN_0042b0d0)."""
    _check_light(mode, color, brightness, speed, direction)
    body = bytearray(12)
    body[0] = mode
    if mode != 0:
        body[1:4] = color.to_bytes(3, "big")
        body[8:12] = bytes([int(bool(colorful)), brightness, speed, direction])
    return bytes(body)


def _page(body, trailer_at=14):
    page = bytearray(CMD_LEN)
    page[:len(body)] = body
    page[trailer_at:trailer_at + 2] = TRAILER
    return bytes(page)


def lighting(link, mode, color=0xFFFFFF, brightness=5, speed=3, direction=0, colorful=False):
    body = light_body(mode, color, brightness, speed, direction, colorful)
    if link == "dongle":  # FUN_0042b270: one report, nothing before it
        return [Step("out", dongle(b"\x05\x10\x00", body))]
    return [  # FUN_0042b0d0, byte-identical to the official capture
        Step("cmd", cmd(0x18), True),
        Step("cmd", cmd(0x13, 0x01), True),
        Step("data", _page(body)),
        Step("cmd", cmd(0x02), True),
        Step("cmd", cmd(0xF0)),
    ]


# ------------------------------------------------------------------ per-key colours

def key_table(colors):
    """{light_index: 0xRRGGBB} -> 576-byte table of [index, R, G, B] entries, aa 55 at 574."""
    table = bytearray(KEY_TABLE_LEN)
    for index, color in colors.items():
        if not 1 <= index <= 142:  # entry 143 would overlap the aa 55 trailer at 574
            raise ValueError(f"LED index {index} out of range 1..142")
        if not 0 <= color <= 0xFFFFFF:
            raise ValueError("color must be 0x000000..0xFFFFFF")
        table[4 * index] = index
        table[4 * index + 1:4 * index + 4] = color.to_bytes(3, "big")
    table[574:576] = TRAILER
    return bytes(table)


def per_key(link, colors, brightness=5):
    """Switch to user mode 0x80 and write the per-key table (FUN_00434a40)."""
    if not 0 <= brightness <= LEVEL_MAX:
        raise ValueError(f"brightness must be 0..{LEVEL_MAX}")
    table = key_table(colors)
    mode_body = bytes([USER_MODE, 0, 0, 0, 0, 0, 0, 0, 0, brightness])
    if link == "dongle":
        steps = [Step("out", dongle(b"\x05\x10\x00", mode_body))]
        padded = table + bytes(21 * 28 - len(table))
        for n in range(21):
            length = 0x10 if n == 20 else 0x1C
            steps.append(Step("out", dongle(bytes([0x14, length, n]) + padded[28 * n:28 * n + 28])))
        return steps
    return [  # FUN_0044b8f0 then the table write
        Step("cmd", cmd(0x18), True),
        Step("cmd", cmd(0x13, 0x01), True),
        Step("data", _page(mode_body)),
        Step("cmd", cmd(0x02), True),
        Step("cmd", cmd(0xF0)),
        Step("cmd", cmd(0x18), True),
        Step("cmd", cmd(0x23, 0x09), True),
        Step("data", table),
        Step("cmd", cmd(0x02), True),
        Step("cmd", cmd(0xF0), True),
    ]


# ------------------------------------------------------------------ clock

def clock_body(now, slot=SLOT):
    """00 SLOT 5a YY MM DD hh mm ss 00 WEEKDAY (Sunday = 0) (FUN_004238f0)."""
    return bytes([0x00, slot, 0x5A, now.year % 2000, now.month, now.day,
                  now.hour, now.minute, now.second, 0x00, now.isoweekday() % 7])


def set_clock(link, now, slot=SLOT):
    body = clock_body(now, slot)
    if link == "dongle":  # FUN_00423a20
        return [Step("out", dongle(b"\x0c\x10\x00", body))]
    page = bytearray(CMD_LEN)
    page[:len(body)] = body
    page[62:64] = TRAILER
    return [
        Step("cmd", cmd(0x18), True),
        Step("cmd", cmd(0x28, 0x01), True),
        Step("data", bytes(page), True),
        Step("cmd", cmd(0x02), True),
    ]


# ------------------------------------------------------------------ battery

def battery_query():
    """Dongle only; the reply's byte 3 is the charge in percent (FUN_00435890)."""
    return [Step("out", checksum(b"\x20\x01" + bytes(30)), True)]


# ------------------------------------------------------------------ screen

def rgb565_frame(rgb):
    """128*128 packed RGB888 -> RGB565 little-endian by truncation, as mui.dll GetImageRGB565Data."""
    if len(rgb) != SCREEN * SCREEN * 3:
        raise ValueError("frame must be 128x128 RGB")
    out = bytearray(FRAME_LEN)
    for i in range(SCREEN * SCREEN):
        r, g, b = rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2]
        out[2 * i] = ((g & 0xFC) << 3 | b >> 3) & 0xFF
        out[2 * i + 1] = (r & 0xF8) | g >> 5
    return bytes(out)


def frame_delay(ms):
    """Frame duration in ms -> device units: max(1, ms // 2), ms clamped to the official 30..500."""
    return max(1, int(max(DELAY_MS[0], min(DELAY_MS[1], ms))) // 2)


def screen_stream(frames, delays_ms):
    """Count, delays, 0xFF fill to 256, RGB565 frames, 0xFF padding to 4096 (FUN_00422930)."""
    if not 1 <= len(frames) <= MAX_FRAMES or len(frames) != len(delays_ms):
        raise ValueError(f"need 1..{MAX_FRAMES} frames, one delay each")
    if any(len(f) != FRAME_LEN for f in frames):
        raise ValueError(f"each frame must be {FRAME_LEN} bytes of RGB565")
    header = bytes([len(frames)] + [frame_delay(d) for d in delays_ms]).ljust(HEADER_LEN, b"\xff")
    stream = header + b"".join(frames)
    return stream + b"\xff" * (-len(stream) % CHUNK_LEN)


def screen_upload(stream, slot=SLOT):
    """Cable only. 04 18, 04 72 (slot, chunk count), chunks, 04 02 (FUN_00422930)."""
    chunks = len(stream) // CHUNK_LEN
    if len(stream) % CHUNK_LEN or not 1 <= chunks <= 0xFFFF:
        raise ValueError("stream must be a whole number of 4096-byte chunks")
    steps = [Step("cmd", cmd(0x18), True),
             Step("cmd", cmd(0x72, b2=slot, b8=chunks & 0xFF, b9=chunks >> 8), True)]
    steps += [Step("chunk", stream[i:i + CHUNK_LEN]) for i in range(0, len(stream), CHUNK_LEN)]
    steps.append(Step("cmd", cmd(0x02), True))
    return steps
