"""Run protocol Steps against the keyboard over the USB-C cable or the 2.4 GHz dongle."""
import sys
import time

from . import protocol as P
from .hid import DryRun, Hidraw, endpoints

CMD_GAP_S = 0.035   # rgb-keyboard.xml <cmd_delaytime value="35"/>, used by FUN_0044eeb0
CHUNK_ACK_S = 1.0   # official app waits 300 ms (FUN_0044f2b0); acks arrive ~140 ms apart
ECHO_TRIES = 20     # FUN_0044f5d0: 20 polls, 5 ms read timeout + 10 ms sleep each


class AulaError(Exception):
    pass


def find(ids, page):
    for e in endpoints():
        if (e.vid, e.pid) == ids and e.usage_page == page:
            return e
    return None


def detect():
    """Which links are plugged in: {"wired": Endpoint|None, "dongle": Endpoint|None}."""
    return {"wired": find(P.WIRED, P.WIRED_CMD_PAGE), "dongle": find(P.DONGLE, P.DONGLE_CMD_PAGE)}


class Keyboard:
    """One connection. link is "wired", "dongle", or None for whichever is plugged in (cable
    first: it supports everything). With dry_run nothing is opened; packets are printed."""

    def __init__(self, link=None, dry_run=False, out=sys.stdout, log=None):
        self.dry_run = dry_run
        self.log = log or (lambda msg: None)
        if link is None:
            present = detect()
            link = "dongle" if present["dongle"] and not present["wired"] else "wired"
        if link not in ("wired", "dongle"):
            raise ValueError("link must be 'wired' or 'dongle'")
        self.link = link
        self.cmd = self.data = None
        if dry_run:
            self.cmd = DryRun(f"{link}", out)
            self.data = DryRun(f"{link} screen", out) if link == "wired" else None
            return
        if link == "wired":
            cmd_ep = find(P.WIRED, P.WIRED_CMD_PAGE)
            if cmd_ep is None:
                raise AulaError("keyboard not found on USB-C (0c45:800a). Plug in the cable, or use --link dongle.")
            self.cmd = Hidraw(cmd_ep)
            data_ep = find(P.WIRED, P.WIRED_DATA_PAGE)
            self.data = Hidraw(data_ep) if data_ep else None
        else:
            ep = find(P.DONGLE, P.DONGLE_CMD_PAGE)
            if ep is None:
                raise AulaError("2.4 GHz dongle not found (05ac:024f). Plug it in and press a key to wake the keyboard.")
            self.cmd = Hidraw(ep)

    def close(self):
        for h in (self.cmd, self.data):
            if h:
                h.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _sleep(self, seconds):
        if not self.dry_run:
            time.sleep(seconds)

    # -------------------------------------------------------------- runner

    def run(self, steps, progress=None):
        """Execute Steps in order and return the replies of read steps.

        Every step is checked against the allowlist before anything is sent.
        progress(done, total) is called after each screen chunk.
        """
        steps = [P.check_step(s) for s in steps]
        wired_only = any(s.kind != "out" for s in steps)
        if wired_only != (self.link == "wired"):
            raise AulaError(f"these packets are for the {'cable' if wired_only else 'dongle'}, "
                            f"but the {self.link} link is open")
        total = sum(s.kind == "chunk" for s in steps)
        sent = missing_acks = 0
        replies = []
        for step in steps:
            if step.kind == "cmd":
                replies += self._cmd(step)
            elif step.kind == "data":
                self._sleep(CMD_GAP_S)
                for i in range(0, len(step.data), P.CMD_LEN):  # FUN_0044eeb0 multi-page branch
                    self.cmd.set_feature(step.data[i:i + P.CMD_LEN])
                    if len(step.data) > P.CMD_LEN:
                        self._sleep(CMD_GAP_S)
                if step.read:
                    self._sleep(CMD_GAP_S)
                    replies.append(self.cmd.get_feature(P.CMD_LEN))
            elif step.kind == "chunk":
                if self.data is None:
                    raise AulaError("screen data interface (usage page 0xff68) not found or not accessible")
                if sent == 0:
                    self.data.drain()
                self.data.write(step.data)
                sent += 1
                if not self.dry_run and not self._chunk_ack():
                    missing_acks += 1
                    self.log(f"no ack for chunk {sent}/{total}; continuing like the official app")
                if progress:
                    progress(sent, total)
            elif step.kind == "out":
                replies.append(self._out(step))
        if missing_acks:
            self.log(f"{missing_acks} of {total} chunks were not acknowledged")
        return replies

    def _cmd(self, step):
        self._sleep(CMD_GAP_S)
        self.cmd.set_feature(step.data)
        if not step.read:
            self.log(f"cmd {step.data[:10].hex(' ')}")
            return []
        for _attempt in range(2):  # a too-early read can return a stale echo; give it one more beat
            self._sleep(CMD_GAP_S)
            reply = self.cmd.get_feature(P.CMD_LEN)
            if reply[:2] == step.data[:2] and reply[3] == 0x01:
                break
        self.log(f"cmd {step.data[:10].hex(' ')} -> {reply[:8].hex(' ')}")
        if reply[:2] != step.data[:2] or reply[3] != 0x01:
            raise AulaError(f"keyboard did not accept {step.data[:2].hex(' ')} (reply {reply[:8].hex(' ')})")
        return [reply]

    def _chunk_ack(self):
        deadline = time.monotonic() + CHUNK_ACK_S
        while (left := deadline - time.monotonic()) > 0:
            if self.data.read(left)[:3] == P.CHUNK_ACK:
                return True
        return False

    def _out(self, step):
        self.cmd.drain()
        self.cmd.write(step.data)
        self.log(f"out {step.data.hex(' ')}")
        if self.dry_run:
            return b""
        time.sleep(0.005)
        for _ in range(ECHO_TRIES):
            reply = self.cmd.read(0.005)
            if reply[:3] == step.data[:3]:
                return reply
            time.sleep(0.010)
        self.log("no echo from the dongle (keyboard asleep or out of range?)")
        return b""

    # -------------------------------------------------------------- features

    def lighting(self, mode, color=0xFFFFFF, brightness=5, speed=3, direction=0, colorful=False):
        self.run(P.lighting(self.link, mode, color, brightness, speed, direction, colorful))

    def per_key(self, colors, brightness=5):
        steps = P.per_key(self.link, colors, brightness)
        if self.link == "dongle":  # FUN_00434a40 sleeps 2 ms after each table packet
            for step in steps:
                self.run([step])
                self._sleep(0.002)
        else:
            self.run(steps)

    def set_clock(self, now):
        self.run(P.set_clock(self.link, now))

    def battery(self):
        if self.link != "dongle":
            raise AulaError("battery level is only reported over the 2.4 GHz dongle")
        reply = self.run(P.battery_query())[0]
        return min(reply[3], 100) if len(reply) > 3 and reply[:2] == b"\x20\x01" and reply[3] else None

    def upload_screen(self, stream, progress=None, slot=P.SLOT):
        if self.link != "wired":
            raise AulaError("screen upload needs the USB-C cable (the official app disables it over 2.4 GHz)")
        self.run(P.screen_upload(stream, slot), progress)
