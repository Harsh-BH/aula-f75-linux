"""Byte-for-byte checks of every packet against what AULA's official app sends.

Vectors marked [CAP] were copied from USB captures of the official app (Ghost-CR/F75_Initializer,
decoded with tools/pcap_usb.py). Vectors marked [BIN] were written by hand from the decompiled
DeviceDriver.exe builder named next to them. See PROTOCOL.md.

    python3 -m unittest -v
Set AULA_CAPTURES=/path/to/F75_Initializer to also replay the full official screen upload.
"""
import datetime
import fnmatch
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from aula_f75 import protocol as P  # noqa: E402
from aula_f75.device import Keyboard  # noqa: E402
from aula_f75.hid import top_level_usage  # noqa: E402


def h(text):
    return bytes.fromhex(text.replace(" ", ""))


def cmd64(prefix):
    return h(prefix).ljust(64, b"\x00")


def sent(steps):
    return [s.data for s in steps]


# [CAP] rgb_color_red_green_blue_white.pcapng and rgb_mode_off_static_breathing_wave_rainbow.pcapng:
# (mode, colour, colorful) -> first 16 bytes of the data page (the rest is zero).
CAPTURED_LIGHT_PAGES = [
    (1, 0xFF0000, True, "01ff0000 00000000 01050300 0000aa55"),
    (1, 0xFF0000, False, "01ff0000 00000000 00050300 0000aa55"),
    (1, 0x00FF00, False, "0100ff00 00000000 00050300 0000aa55"),
    (1, 0x0000FF, False, "010000ff 00000000 00050300 0000aa55"),
    (1, 0xFFFFFF, False, "01ffffff 00000000 00050300 0000aa55"),
    (0, 0xFF0000, True, "00000000 00000000 00000000 0000aa55"),
] + [(m, 0xFF0000, True, f"{m:02x}ff0000 00000000 01050300 0000aa55") for m in range(2, 20)]


class WiredLighting(unittest.TestCase):
    def test_matches_official_capture(self):
        for mode, color, colorful, page in CAPTURED_LIGHT_PAGES:
            with self.subTest(mode=mode, color=hex(color), colorful=colorful):
                steps = P.lighting("wired", mode, color, brightness=5, speed=3, direction=0, colorful=colorful)
                self.assertEqual(sent(steps), [
                    cmd64("0418"),
                    cmd64("0413 0000 0000 0000 01"),
                    h(page).ljust(64, b"\x00"),
                    cmd64("0402"),
                    cmd64("04f0"),
                ])
                # [CAP] the app reads back after 04 18, 04 13, 04 02 but not after the page or 04 f0
                self.assertEqual([s.read for s in steps], [True, True, False, True, False])

    def test_rejects_out_of_range(self):
        for kwargs in ({"mode": 20}, {"mode": 1, "brightness": 6}, {"mode": 1, "speed": -1},
                       {"mode": 1, "direction": 4}, {"mode": 1, "color": 0x1000000}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                P.lighting("wired", **kwargs)


class DongleLighting(unittest.TestCase):
    def test_static_red(self):
        # [BIN] FUN_0042b270: 05 10 00 MODE R G B .. [11]=colorful [12]=bright [13]=speed [14]=dir, aa55@17, sum@31
        report = h("051000 01 ff0000 00000000 00 05 03 00 0000 aa55").ljust(31, b"\x00")
        report += bytes([sum(report) & 0xFF])
        self.assertEqual(sent(P.lighting("dongle", 1, 0xFF0000, 5, 3, 0, False)), [report])
        self.assertEqual(report.hex(), "05100001ff0000" "00000000" "00" "050300" "0000" "aa55" + "00" * 12 + "1c")

    def test_off_and_is_single_report(self):
        # [BIN] FUN_0042b270 sends exactly one report; colour fields stay zero for mode 0.
        steps = P.lighting("dongle", 0, 0xFF0000, 5, 3, 0, True)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].data[:19], h("051000 00" + "00" * 13 + "aa55"))

    def test_same_payload_as_cable_shifted_by_three(self):
        for mode in range(20):
            wired = P.lighting("wired", mode, 0x123456, 4, 2, 3, mode % 2 == 0)[2].data
            dongle = P.lighting("dongle", mode, 0x123456, 4, 2, 3, mode % 2 == 0)[0].data
            self.assertEqual(dongle[3:15], wired[0:12])


class Clock(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 15, 7, 30, 5)  # a Sunday

    def test_wired(self):
        # [BIN] FUN_004238f0
        steps = P.set_clock("wired", self.NOW)
        page = h("00 01 5a 1a 0b 0f 07 1e 05 00 00").ljust(62, b"\x00") + b"\xaa\x55"
        self.assertEqual(sent(steps), [cmd64("0418"), cmd64("0428 0000 0000 0000 01"), page, cmd64("0402")])
        self.assertEqual([s.kind for s in steps], ["cmd", "cmd", "data", "cmd"])
        self.assertTrue(all(s.read for s in steps))

    def test_dongle(self):
        # [BIN] FUN_00423a20: the cable page shifted by 3 behind 0c 10 00, aa55@17
        body = h("0c1000 00 01 5a 1a 0b 0f 07 1e 05 00 00 000000 aa55").ljust(31, b"\x00")
        self.assertEqual(sent(P.set_clock("dongle", self.NOW)), [body + bytes([sum(body) & 0xFF])])

    def test_weekday_sunday_is_zero(self):
        self.assertEqual(P.clock_body(self.NOW)[10], 0)
        self.assertEqual(P.clock_body(self.NOW + datetime.timedelta(days=1))[10], 1)


class PerKey(unittest.TestCase):
    COLORS = {1: 0xFF0000, 38: 0x00FF00, 142: 0x0000FF}

    def test_table(self):
        t = P.key_table(self.COLORS)
        self.assertEqual(len(t), 576)
        self.assertEqual(t[4:8], h("01 ff0000"))
        self.assertEqual(t[152:156], h("26 00ff00"))
        self.assertEqual(t[568:572], h("8e 0000ff"))
        self.assertEqual(t[574:576], b"\xaa\x55")
        self.assertEqual(t[0:4], bytes(4))  # unassigned entries stay zero

    def test_wired_sequence(self):
        # [BIN] FUN_0044b8f0 (user mode 0x80, brightness at [9]) then FUN_00434a40 table write
        steps = P.per_key("wired", {1: 0xFF0000}, brightness=4)
        self.assertEqual(sent(steps)[:5], [
            cmd64("0418"), cmd64("0413 0000 0000 0000 01"),
            h("80 000000 00000000 00 04 0000 0000 aa55").ljust(64, b"\x00"),
            cmd64("0402"), cmd64("04f0")])
        self.assertEqual(sent(steps)[5:7], [cmd64("0418"), cmd64("0423 0000 0000 0000 09")])
        self.assertEqual(len(steps[7].data), 576)
        self.assertEqual(sent(steps)[8:], [cmd64("0402"), cmd64("04f0")])
        self.assertEqual([s.read for s in steps], [True, True, False, True, False, True, True, False, True, True])

    def test_dongle_packets(self):
        # [BIN] FUN_00434a40: mode report, then 21 x (14 LEN N + 28 table bytes), LEN 0x1c / last 0x10
        steps = P.per_key("dongle", self.COLORS, brightness=5)
        self.assertEqual(len(steps), 22)
        self.assertEqual(steps[0].data[:19], h("051000 80 0000000000000000 05 00000000 aa55"))
        table = P.key_table(self.COLORS) + bytes(12)
        for n, step in enumerate(steps[1:]):
            self.assertEqual(step.data[:3], bytes([0x14, 0x10 if n == 20 else 0x1C, n]))
            self.assertEqual(step.data[3:31], table[28 * n:28 * n + 28])
            self.assertEqual(step.data[31], sum(step.data[:31]) & 0xFF)


class Battery(unittest.TestCase):
    def test_query(self):
        # [BIN] FUN_00435890: 20 01, checksum 0x21
        self.assertEqual(sent(P.battery_query()), [h("2001").ljust(31, b"\x00") + b"\x21"])


class Screen(unittest.TestCase):
    # [CAP] official_guts_upload.pcapng: the delay bytes of the official 105-frame upload, made
    # from a GIF whose frames last 30 or 40 ms.
    OFFICIAL_DELAYS = h("0f140f" * 34 + "0f1414")

    def frames(self, n):
        return [bytes([i]) * P.FRAME_LEN for i in range(n)]

    def test_header_matches_official(self):
        delays_ms = [d * 2 for d in self.OFFICIAL_DELAYS]
        stream = P.screen_stream(self.frames(105), delays_ms)
        self.assertEqual(stream[:256], b"\x69" + self.OFFICIAL_DELAYS + b"\xff" * 150)
        self.assertEqual(len(stream) // 4096, 841)              # [CAP] 04 72 .. 49 03
        self.assertEqual(stream[256 + 105 * 32768:], b"\xff" * 3840)  # [CAP] 0xFF tail
        self.assertEqual(stream[256:256 + 32768], self.frames(1)[0])

    def test_commands_match_official(self):
        stream = P.screen_stream(self.frames(105), [30] * 105)
        steps = P.screen_upload(stream, slot=2)
        self.assertEqual(steps[0].data, cmd64("0418"))
        self.assertEqual(steps[1].data, cmd64("0472 02 0000000000 4903"))  # [CAP]
        self.assertEqual(steps[-1].data, cmd64("0402"))
        self.assertEqual([s.kind for s in steps[2:-1]], ["chunk"] * 841)
        self.assertEqual(P.screen_upload(P.screen_stream(self.frames(1), [100]))[1].data, cmd64("0472 01 0000000000 0900"))

    def test_delay_conversion(self):
        # [BIN] FUN_00422930: max(1, ms / 2) integer division; UI range 30..500 ms
        self.assertEqual([P.frame_delay(ms) for ms in (0, 30, 31, 40, 100, 500, 900)], [15, 15, 15, 20, 50, 250, 250])

    def test_rgb565(self):
        # [MUI] GetImageRGB565Data: lo = (G&0xFC)<<3 | B>>3, hi = (R&0xF8) | G>>5
        rgb = bytes([0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x7B, 0x7B, 0x7B]) + bytes(3 * (128 * 128 - 4))
        out = P.rgb565_frame(rgb)
        self.assertEqual(out[:8], h("00f8 e007 1f00 cf7b"))  # red, green, blue, grey 0x7bcf ([CAP] common colour)

    def test_limits(self):
        with self.assertRaises(ValueError):
            P.screen_stream(self.frames(256)[:1] * 256, [100] * 256)
        with self.assertRaises(ValueError):
            P.screen_stream([b"\x00" * 10], [100])

    @unittest.skipUnless(os.environ.get("AULA_CAPTURES"), "set AULA_CAPTURES to the F75_Initializer checkout")
    def test_full_official_stream(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        import pcap_usb
        transfers = list(pcap_usb.transfers(os.path.join(os.environ["AULA_CAPTURES"], "official_guts_upload.pcapng")))
        official = b"".join(p for _ts, _d, desc, p in transfers if "ep=0x03" in desc)
        n = official[0]
        frames = [official[256 + i * P.FRAME_LEN:256 + (i + 1) * P.FRAME_LEN] for i in range(n)]
        mine = P.screen_stream(frames, [d * 2 for d in official[1:1 + n]])
        self.assertEqual(mine, official)
        commands = [p for _ts, d, desc, p in transfers if d == "H>D" and "SET_REPORT" in desc]
        steps = P.screen_upload(mine, slot=2)
        self.assertEqual([s.data for s in steps if s.kind == "cmd"], commands)


class Safety(unittest.TestCase):
    def test_reset_and_bootloader_refused(self):
        for step in (
            P.Step("out", P.checksum(b"\x0f" + bytes(31))),           # Factory Reset (FUN_00434fa0)
            P.Step("out", P.checksum(b"\x1f" + bytes(31))),           # Reset Keyboard (task 0xd)
            P.Step("cmd", P.BOOTLOADER_MAGIC.ljust(64, b"\x00")),    # bootloader jump
            P.Step("data", P.BOOTLOADER_MAGIC.ljust(64, b"\x00")),
            P.Step("cmd", P.cmd(0x19)),                               # macros (not built by this app)
            P.Step("cmd", P.cmd(0x17)),                               # settings (not built by this app)
            P.Step("out", P.checksum(b"\x07\x10" + bytes(30))),       # dongle settings
        ):
            with self.subTest(step=step.data[:8].hex()), self.assertRaises(PermissionError):
                P.check_step(step)

    def test_dry_run_sends_every_builder_through_the_guard(self):
        out = io.StringIO()
        now = datetime.datetime(2026, 1, 1)
        for link in ("wired", "dongle"):
            kb = Keyboard(link, dry_run=True, out=out)
            kb.lighting(1, 0xFF0000)
            kb.per_key({1: 0xFF0000})
            kb.set_clock(now)
        Keyboard("dongle", dry_run=True, out=out).battery()
        Keyboard("wired", dry_run=True, out=out).upload_screen(P.screen_stream([bytes(P.FRAME_LEN)], [100]))
        text = out.getvalue()
        self.assertIn("[dry-run wired] FEATURE 00 04 18", text)
        self.assertIn("[dry-run dongle] OUTPUT  00 05 10 00 01 ff 00 00", text)
        self.assertNotIn("OUTPUT  00 0f", text)

    def test_wrong_link_refused(self):
        kb = Keyboard("dongle", dry_run=True, out=io.StringIO())
        with self.assertRaises(Exception):
            kb.run(P.lighting("wired", 1))


class CliDryRun(unittest.TestCase):
    """--dry-run must never be lost, wherever it is placed (argparse once dropped it)."""

    def test_flag_positions(self):
        from contextlib import redirect_stdout
        from unittest import mock
        from aula_f75 import cli
        argvs = [["-n", "color", "red", "--link", "dongle"], ["color", "red", "-n", "--link", "dongle"],
                 ["--dry-run", "--link", "wired", "effect", "breath"], ["effect", "breath", "--link", "wired", "--dry-run"],
                 ["-n", "keys", "--link", "wired", "esc=red", "w,a,s,d=00ff00", "98=blue"],
                 ["clock", "-n", "--link", "dongle", "--at", "2026-11-15T07:30:00"],
                 ["text", "hi", "-n"], ["-n", "battery"]]
        with mock.patch("aula_f75.device.Hidraw", side_effect=AssertionError("dry run opened a device")):
            for argv in argvs:
                with self.subTest(argv=argv):
                    out = io.StringIO()
                    with redirect_stdout(out):
                        cli.main(argv)
                    self.assertIn("[dry-run", out.getvalue())

    def test_key_spec(self):
        from aula_f75.cli import key_spec
        self.assertEqual(key_spec(["esc,w=ff0000", "98=blue"]), {1: 0xFF0000, 39: 0xFF0000, 98: 0x0000FF})
        self.assertEqual(len(key_spec([], base=0)), 80)


class Discovery(unittest.TestCase):
    # [DEV] report descriptors of this machine's dongle, interfaces 3 and 4
    def test_usage_pages(self):
        self.assertEqual(top_level_usage(h("0660ff0961a10109621500 26ff00952075088102 0963150026ff00952075089102c0")), (0xFF60, 0x61))
        self.assertEqual(top_level_usage(h("0659ff0961a10109621500 26ff00954075088102 0963150026ff00954075089102c0")), (0xFF59, 0x61))
        self.assertEqual(top_level_usage(h("05010906a101050719e029e7")), (0x01, 0x06))

    def test_udev_rule_matches_only_vendor_interfaces(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "udev", "70-aula-f75.rules")) as f:
            rules = f.read()
        globs = [line.split('DEVPATH=="')[1].split('"')[0] for line in rules.splitlines() if 'DEVPATH=="' in line]
        base = "/devices/pci0000:00/0000:00:14.0/usb1/1-4/1-4:1.{i}/0003:{vp}.0006/hidraw/hidraw5"
        allowed = {base.format(i=3, vp="05AC:024F"), base.format(i=2, vp="0C45:800A"), base.format(i=3, vp="0C45:800A")}
        denied = {base.format(i=0, vp="05AC:024F"), base.format(i=4, vp="05AC:024F"),
                  base.format(i=0, vp="0C45:800A"), base.format(i=3, vp="1532:009C")}
        for path in allowed:
            self.assertTrue(any(fnmatch.fnmatchcase(path, g) for g in globs), path)
        for path in denied:
            self.assertFalse(any(fnmatch.fnmatchcase(path, g) for g in globs), path)


if __name__ == "__main__":
    unittest.main()
