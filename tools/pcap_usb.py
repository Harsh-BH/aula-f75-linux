#!/usr/bin/env python3
"""Dump HID traffic from a Windows USBPcap capture (.pcapng), stdlib only.

Used to pull byte-exact test vectors out of captures of AULA's official app.
Prints one line per transfer: time, direction, kind, endpoint, payload hex.

    python3 -I tools/pcap_usb.py capture.pcapng [--min-len N] [--full]
"""
import argparse
import struct
import sys

LINKTYPE_USBPCAP = 249
SET_REPORT, GET_REPORT = 0x09, 0x01


def blocks(data):
    off, endian = 0, "<"
    while off + 12 <= len(data):
        btype, blen = struct.unpack_from(endian + "II", data, off)
        if btype == 0x0A0D0D0A:  # section header: learn byte order
            endian = "<" if data[off + 8:off + 12] == b"\x4d\x3c\x2b\x1a" else ">"
            blen = struct.unpack_from(endian + "I", data, off + 4)[0]
        yield btype, data[off + 8:off + blen - 4], endian
        off += blen


def packets(path):
    """Yield (timestamp_us, usbpcap_header_dict, payload) for each USBPcap packet."""
    data = open(path, "rb").read()
    linktypes = []
    for btype, body, e in blocks(data):
        if btype == 1:  # interface description
            linktypes.append(struct.unpack_from(e + "H", body, 0)[0])
        elif btype == 6:  # enhanced packet
            iface, ts_hi, ts_lo, caplen, _ = struct.unpack_from(e + "IIIII", body, 0)
            if linktypes[iface] != LINKTYPE_USBPCAP:
                continue
            pkt = body[20:20 + caplen]
            hlen, irp, status, func, info, bus, dev, ep, xfer, dlen = struct.unpack_from("<HQIHBHHBBI", pkt, 0)
            hdr = dict(irp=irp, status=status, func=func, out=not (info & 1), bus=bus, dev=dev,
                       ep=ep, xfer=xfer, stage=pkt[27] if xfer == 2 and hlen >= 28 else None)
            yield (ts_hi << 32 | ts_lo), hdr, pkt[hlen:]


def transfers(path):
    """Collapse USBPcap records into HID-level transfers.

    Control SETUP records carry the 8-byte setup packet and, for host-to-device
    requests, the data that follows it. GET_REPORT data comes back in the completion
    record (same IRP). Interrupt OUT data is in the submit record; interrupt IN data
    is in the completion.
    """
    pending = {}
    for ts, h, p in packets(path):
        if h["xfer"] == 2:  # control
            if h["stage"] == 0 and len(p) >= 8:
                bm, req, wval, widx, wlen = struct.unpack_from("<BBHHH", p, 0)
                if bm & 0x60 != 0x20:  # class requests only
                    continue
                kind = {SET_REPORT: "SET_REPORT", GET_REPORT: "GET_REPORT"}.get(req, f"req{req:02x}")
                rtype = {1: "in", 2: "out", 3: "feature"}.get(wval >> 8, "?")
                info = (ts, f"{kind}/{rtype} id={wval & 0xFF} if={widx} dev={h['dev']}")
                if bm & 0x80:
                    pending[h["irp"]] = info
                elif len(p) > 8:
                    yield info[0], "H>D", info[1], p[8:]
                else:
                    pending[h["irp"]] = info  # data may arrive in a separate DATA stage record
            elif h["irp"] in pending and len(p):
                ts0, desc = pending.pop(h["irp"])
                yield ts, ("D>H" if not h["out"] else "H>D"), desc, p
        elif h["xfer"] == 1 and len(p):  # interrupt
            d = "D>H" if h["ep"] & 0x80 else "H>D"
            yield ts, d, f"INTR ep=0x{h['ep']:02x} dev={h['dev']}", p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap")
    ap.add_argument("--min-len", type=int, default=1)
    ap.add_argument("--full", action="store_true", help="print whole payloads, not the first 64 bytes")
    ap.add_argument("--skip-in", action="store_true", help="hide device-to-host interrupt traffic (key presses)")
    a = ap.parse_args()
    t0 = None
    for ts, d, desc, p in transfers(a.pcap):
        if len(p) < a.min_len or (a.skip_in and d == "D>H" and desc.startswith("INTR")):
            continue
        t0 = t0 or ts
        shown = p if a.full else p[:64]
        print(f"{(ts - t0) / 1000:10.1f}ms {d} {desc:40} len={len(p):5} {shown.hex(' ')}")


if __name__ == "__main__":
    sys.exit(main())
