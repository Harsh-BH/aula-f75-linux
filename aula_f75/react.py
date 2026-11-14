"""Reactive lighting: watch this keyboard's own key presses and stream live frames (USB-C only).

Key presses come from the keyboard's evdev devices (/dev/input/event*, readable by the `input`
group). They are only used to place light: nothing is stored, printed or logged, and the
devices are not grabbed, so typing works as normal.
"""
import colorsys
import glob
import math
import os
import select
import struct
import time

from . import protocol as P
from .device import AulaError
from .layout import KEYS
from .patterns import blend

EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit Linux: timeval, type, code, value
EV_KEY, PRESS = 1, 1
LINUX_KEYS = {  # linux/input-event-codes.h -> layout.KEYS name (Fn and right Ctrl never reach the host / have no key)
    1: "esc", **{2 + i: str((i + 1) % 10) for i in range(10)}, 12: "minus", 13: "equal", 14: "backspace",
    15: "tab", **dict(zip(range(16, 26), "qwertyuiop")), 26: "lbracket", 27: "rbracket", 28: "enter",
    29: "lctrl", **dict(zip(range(30, 39), "asdfghjkl")), 39: "semicolon", 40: "quote", 41: "grave",
    42: "lshift", 43: "backslash", **dict(zip(range(44, 51), "zxcvbnm")), 51: "comma", 52: "period",
    53: "slash", 54: "rshift", 56: "lalt", 57: "space", 58: "capslock", **{59 + i: f"f{i + 1}" for i in range(10)},
    87: "f11", 88: "f12", 100: "ralt", 103: "up", 104: "pageup", 105: "left", 106: "right", 107: "end",
    108: "down", 109: "pagedown", 111: "delete", 125: "lwin",
}
INDEX = {code: KEYS[name][0] for code, name in LINUX_KEYS.items()}
CENTRE = {index: (x + w / 2, y + h / 2) for index, x, y, w, h in KEYS.values()}
EFFECTS = ("ripple", "glow", "heatmap", "speed")
HEAT = (0x000030, 0x0000FF, 0x00FFFF, 0x00FF00, 0xFFFF00, 0xFF0000, 0xFFFFFF)  # cold -> hot
SPEED = (0x0040FF, 0x00FFC0, 0xFFD000, 0xFF0000)                                 # slow -> fast


def input_devices():
    """/dev/input/event* nodes that belong to the F75 Max (cable or dongle)."""
    nodes = []
    for sysfs in glob.glob("/sys/class/input/event*"):
        try:
            with open(f"{sysfs}/device/id/vendor") as v, open(f"{sysfs}/device/id/product") as p:
                ids = (int(v.read(), 16), int(p.read(), 16))
        except OSError:
            continue
        if ids in (P.WIRED, P.DONGLE):
            nodes.append("/dev/input/" + os.path.basename(sysfs))
    return sorted(nodes)


def rgb(c):
    return (c >> 16 & 255, c >> 8 & 255, c & 255)


class Renderer:
    """Turns key presses into per-key colours. Pure: give it times, get {light_index: 0xRRGGBB}."""

    def __init__(self, effect, color=None, base=None):
        if effect not in EFFECTS:
            raise AulaError(f"unknown reactive effect {effect!r}; choose from {', '.join(EFFECTS)}")
        # color: None = rainbow, one 0xRRGGBB, or a list that key presses cycle through
        self.palette = None if color is None else [color] if isinstance(color, int) else list(color)
        self.effect, self.base, self.count = effect, base or {}, 0
        self.presses, self.heat, self.hue, self.last = [], {}, 0.0, None

    def press(self, index, now):
        if self.palette is None:  # rainbow: each press gets the next hue, golden-angle apart
            self.hue = (self.hue + 0.618034) % 1.0
            colour = tuple(c * 255 for c in colorsys.hsv_to_rgb(self.hue, 1, 1))
        else:
            colour = rgb(self.palette[self.count % len(self.palette)])
            self.count += 1
        self.presses.append((now, index, colour))
        self.heat[index] = self.heat.get(index, 0.0) + 1.0

    def frame(self, now):
        dt, self.last = (0.0 if self.last is None else now - self.last), now
        out = {i: list(rgb(self.base.get(i, 0))) for i in CENTRE}
        life = {"ripple": 0.9, "glow": 1.2, "heatmap": 0.0, "speed": 2.0}[self.effect]
        self.presses = [p for p in self.presses if now - p[0] < life]

        def add(index, colour, amount):
            if amount > 0:
                out[index] = [c + v * amount for c, v in zip(out[index], colour)]

        if self.effect == "ripple":  # a ring rolls out from each press across the board
            for t0, i0, colour in self.presses:
                age = now - t0
                for i, (x, y) in CENTRE.items():
                    d = math.dist((x, y), CENTRE[i0])
                    add(i, colour, max(0.0, 1 - abs(d - 520 * age) / 45) * (1 - age / life))
        elif self.effect == "glow":  # the key lights up and fades, with a soft halo
            for t0, i0, colour in self.presses:
                fade = (1 - (now - t0) / life) ** 2
                for i, (x, y) in CENTRE.items():
                    d = math.dist((x, y), CENTRE[i0])
                    add(i, colour, fade * (1.0 if i == i0 else max(0.0, 0.4 * (1 - d / 75))))
        elif self.effect == "heatmap":  # keys warm up as you use them and cool with a 10 s half-life
            for i in list(self.heat):
                self.heat[i] *= 0.5 ** (dt / 10)
                if self.heat[i] < 0.02:
                    del self.heat[i]
            out = {i: list(rgb(blend(HEAT, self.heat.get(i, 0.0) / 12))) if i in self.heat else out[i] for i in CENTRE}
        elif self.effect == "speed":  # the whole board shifts blue -> red with your typing speed
            rate = len(self.presses) / life  # keys per second over the last 2 s
            board = [c * 0.45 for c in rgb(blend(SPEED, rate / 8))]
            out = {i: list(board) for i in CENTRE}
            for t0, i0, _colour in self.presses:
                add(i0, (255, 255, 255), max(0.0, 1 - (now - t0) / 0.3))
        return {i: (min(255, int(r)) << 16) | (min(255, int(g)) << 8) | min(255, int(b)) for i, (r, g, b) in out.items()}


def run(kb, renderer, stop, idle_s=0.1):
    """Stream frames until stop (a threading.Event) is set. Returns (frames sent, seconds)."""
    if kb.link != "wired":
        raise AulaError("reactive lighting needs the USB-C cable (the official app offers it only wired)")
    fds = []
    try:
        for node in input_devices():
            try:
                fds.append(os.open(node, os.O_RDONLY | os.O_NONBLOCK))
            except PermissionError:
                raise AulaError(f"cannot read key presses from {node}: add yourself to the `input` group "
                                "(sudo usermod -aG input $USER), then log out and back in") from None
        if not fds:
            raise AulaError("the keyboard's input devices were not found under /dev/input")
        log, kb.log = kb.log, (lambda msg: None)  # 3 reports per frame at ~20 fps would flood any log
        sent, failed, start, previous = 0, 0, time.monotonic(), None
        while not stop.is_set():
            ready, _, _ = select.select(fds, [], [], 0 if renderer.presses or renderer.heat else idle_s)
            now = time.monotonic()
            for fd in ready:
                data = os.read(fd, EVENT.size * 64)
                for _sec, _usec, kind, code, value in EVENT.iter_unpack(data[:len(data) - len(data) % EVENT.size]):
                    if kind == EV_KEY and value == PRESS and code in INDEX:
                        renderer.press(INDEX[code], now)
            frame = renderer.frame(now)
            if frame != previous:  # an idle board costs no USB traffic
                try:
                    kb.run(P.live_frame(frame))
                    previous, sent, failed = frame, sent + 1, 0
                except AulaError:  # [HW] the keyboard can answer "busy" (ff) twice in a row mid-stream
                    failed += 1    # drop the frame: the next one replaces it anyway
                    if failed >= 10:
                        raise
                    time.sleep(0.05)
        kb.log = log
        return sent, time.monotonic() - start
    finally:
        for fd in fds:
            os.close(fd)
