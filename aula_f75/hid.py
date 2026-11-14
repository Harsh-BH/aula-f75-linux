"""Linux hidraw transport: find the keyboard's interfaces in sysfs, talk ioctl/read/write.

No hidapi: feature reports use the HIDIOCSFEATURE/HIDIOCGFEATURE ioctls from
<linux/hidraw.h>; output reports are a plain write(), input reports a read().
Every report the keyboard uses is unnumbered, so a 0x00 report-ID byte goes first.
"""
import fcntl
import glob
import os
import select
import sys
import time
from dataclasses import dataclass


def _iowr(nr, size):  # _IOC(_IOC_READ|_IOC_WRITE, 'H', nr, size)
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


def HIDIOCSFEATURE(size):
    return _iowr(0x06, size)


def HIDIOCGFEATURE(size):
    return _iowr(0x07, size)


@dataclass(frozen=True)
class Endpoint:
    path: str        # /dev/hidrawN
    vid: int
    pid: int
    usage_page: int  # first top-level Usage Page in the report descriptor
    usage: int
    interface: int   # USB bInterfaceNumber, -1 if unknown
    name: str


def top_level_usage(descriptor):
    """(usage_page, usage) of the first application collection in a HID report descriptor."""
    page = usage = None
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == 0xFE:  # long item: 0xFE, size, tag, data
            i += 3 + descriptor[i + 1]
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        value = int.from_bytes(descriptor[i + 1:i + 1 + size], "little")
        tag = prefix & 0xFC
        if tag == 0x04 and page is None:     # Usage Page (global)
            page = value
        elif tag == 0x08 and usage is None:  # Usage (local)
            usage = value & 0xFFFF
        elif tag == 0xA0:                    # Collection: first one decides
            break
        i += 1 + size
    return page or 0, usage or 0


def endpoints(sysfs="/sys/class/hidraw"):
    """Every hidraw node on the system, described from sysfs (readable without root)."""
    found = []
    for node in sorted(glob.glob(os.path.join(sysfs, "hidraw*"))):
        try:
            props = dict(line.rstrip("\n").partition("=")[::2] for line in open(os.path.join(node, "device/uevent")))
            _bus, vid, pid = (int(x, 16) for x in props["HID_ID"].split(":"))
            page, usage = top_level_usage(open(os.path.join(node, "device/report_descriptor"), "rb").read())
        except (OSError, KeyError, ValueError):
            continue
        iface = -1
        # .../1-4:1.3/0003:05AC:024F.0006 -> the USB interface directory is the parent
        intf_file = os.path.join(os.path.realpath(os.path.join(node, "device")), "..", "bInterfaceNumber")
        try:
            iface = int(open(intf_file).read(), 16)
        except (OSError, ValueError):
            pass
        found.append(Endpoint("/dev/" + os.path.basename(node), vid, pid, page, usage, iface, props.get("HID_NAME", "")))
    return found


class Hidraw:
    """One open /dev/hidrawN. Payloads exclude the report-ID byte; this class adds it."""

    def __init__(self, endpoint):
        self.endpoint = endpoint
        try:
            self.fd = os.open(endpoint.path, os.O_RDWR)
        except PermissionError:
            raise PermissionError(
                f"no permission on {endpoint.path}: install udev/70-aula-f75.rules (see README.md) and replug"
            ) from None

    def set_feature(self, payload):
        buf = bytearray(b"\x00" + bytes(payload))
        fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(buf)), buf)

    def get_feature(self, length):
        buf = bytearray(length + 1)  # buf[0] = report ID in, payload follows
        fcntl.ioctl(self.fd, HIDIOCGFEATURE(len(buf)), buf)
        return bytes(buf[1:])

    def write(self, payload):
        os.write(self.fd, b"\x00" + bytes(payload))

    def read(self, timeout_s, size=4097):
        ready, _, _ = select.select([self.fd], [], [], timeout_s)
        return os.read(self.fd, size) if ready else b""

    def drain(self):
        while self.read(0):
            pass

    def close(self):
        os.close(self.fd)


class DryRun:
    """Stands in for Hidraw: prints every report that would be sent, sends nothing.

    Reads return a fake "accepted" reply so command sequences run to the end.
    """

    def __init__(self, label, out=sys.stdout, full=False):
        self.label, self.out, self.full = label, out, full
        self.last = b""
        self.sent = []  # (kind, payload) for tests

    def _show(self, kind, payload):
        self.sent.append((kind, bytes(payload)))
        data = bytes(payload)
        shown = data if self.full or len(data) <= 64 else data[:32]
        more = "" if len(shown) == len(data) else f" ... ({len(data)} bytes, sha256 {_sha(data)})"
        print(f"[dry-run {self.label}] {kind:7} 00 {shown.hex(' ')}{more}", file=self.out)

    def set_feature(self, payload):
        self.last = bytes(payload)
        self._show("FEATURE", payload)

    def get_feature(self, length):
        reply = bytearray(self.last[:length].ljust(length, b"\x00"))
        if len(reply) > 3 and reply[0] == 0x04:
            reply[3] = 0x01  # what the keyboard answers when it accepts a command
        return bytes(reply)

    def write(self, payload):
        self._show("OUTPUT", payload)

    def read(self, timeout_s, size=4097):
        return b""

    def drain(self):
        pass

    def close(self):
        pass


def _sha(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


def sleep_ms(ms):
    time.sleep(ms / 1000)
