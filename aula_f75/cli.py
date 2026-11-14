"""aula-f75: control the AULA F75 Max keyboard's lighting and screen from Linux."""
import argparse
import datetime
import os
import sys

from . import protocol as P
from .device import AulaError, Keyboard
from .hid import endpoints
from .layout import KEYS

NAMED = {"red": 0xFF0000, "green": 0x00FF00, "blue": 0x0000FF, "white": 0xFFFFFF, "black": 0x000000,
         "yellow": 0xFFFF00, "cyan": 0x00FFFF, "magenta": 0xFF00FF, "orange": 0xFF8000, "purple": 0x8000FF,
         "pink": 0xFF4080, "off": 0x000000}


def color(text):
    """'ff8800', '#ff8800' or a basic colour name -> 0xRRGGBB."""
    text = text.strip().lower()
    if text in NAMED:
        return NAMED[text]
    try:
        value = int(text.lstrip("#"), 16)
        if len(text.lstrip("#")) == 6:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"not a colour: {text!r} (use RRGGBB hex or {', '.join(NAMED)})")


def level(text):
    value = int(text)
    if not 0 <= value <= P.LEVEL_MAX:
        raise argparse.ArgumentTypeError(f"must be 0..{P.LEVEL_MAX}")
    return value


def key_spec(specs, base=None):
    """['esc=ff0000', 'w,a,s,d=green', '98=blue'] -> {light_index: colour}. Names from layout.KEYS."""
    colors = {index: base for index, *_ in KEYS.values()} if base is not None else {}
    for spec in specs:
        names, sep, value = spec.rpartition("=")
        if not sep:
            raise AulaError(f"bad key spec {spec!r}: use key[,key...]=colour")
        rgb = color(value)
        for name in names.split(","):
            name = name.strip().lower()
            if name in KEYS:
                colors[KEYS[name][0]] = rgb
            elif name.isdigit():
                colors[int(name)] = rgb  # raw LED index, e.g. 98 / 110 / 111 which have no key in the layout
            elif name == "all":
                colors.update({index: rgb for index, *_ in KEYS.values()})
            else:
                raise AulaError(f"unknown key {name!r}; known keys: {' '.join(KEYS)}")
    return colors


def cmd_list(_args, _kb):
    found = False
    for e in endpoints():
        link = {P.WIRED: "usb-c", P.DONGLE: "dongle"}.get((e.vid, e.pid))
        if not link:
            continue
        found = True
        role = {P.WIRED_CMD_PAGE: "commands", P.WIRED_DATA_PAGE: "screen data",
                P.DONGLE_CMD_PAGE: "commands"}.get(e.usage_page, "-")
        access = "ok" if os.access(e.path, os.R_OK | os.W_OK) else "no access"
        print(f"{e.path:14} {link:7} if{e.interface} page 0x{e.usage_page:04x} {role:12} {access}")
    if not found:
        print("No AULA F75 Max found (looked for 0c45:800a on USB-C and 05ac:024f dongle).")


def describe(args):
    parts = [P.MODES[args.mode]]
    if args.mode:
        parts.append("rainbow" if args.colorful else f"#{args.color:06x}")
        parts.append(f"brightness {args.brightness}, speed {args.speed}, {P.DIRECTIONS[args.direction]}")
    return ", ".join(parts)


def cmd_effect(args, kb):
    kb.lighting(args.mode, args.color, args.brightness, args.speed, args.direction, args.colorful)
    print(f"Lighting over {kb.link}: {describe(args)}")


def cmd_keys(args, kb):
    colors = key_spec(args.spec, args.base)
    if not colors:
        raise AulaError("no keys given")
    kb.per_key(colors, args.brightness)
    print(f"Per-key colours over {kb.link}: {len(colors)} LEDs")


def cmd_clock(args, kb):
    now = datetime.datetime.fromisoformat(args.at) if args.at else datetime.datetime.now()
    kb.set_clock(now)
    print(f"Clock over {kb.link} set to {now:%a %Y-%m-%d %H:%M:%S}")


def _upload(kb, images, delays, args):
    from .screen import to_rgb565
    stream = P.screen_stream(to_rgb565(images), delays)
    chunks = len(stream) // P.CHUNK_LEN

    def progress(done, total):
        if not args.dry_run:
            print(f"\rUploading {len(images)} frame(s): {done}/{total} chunks", end="", file=sys.stderr, flush=True)

    kb.upload_screen(stream, progress)
    print(f"{'' if args.dry_run else chr(10)}Screen: {len(images)} frame(s), {chunks} chunks uploaded over USB-C")


def cmd_image(args, kb):
    from .screen import load_frames
    images, delays = load_frames(args.path, args.fit, args.background)
    if args.frame_ms:
        delays = [args.frame_ms] * len(delays)
    _upload(kb, images, delays, args)


def cmd_text(args, kb):
    from .screen import text_frame
    _upload(kb, [text_frame(args.text.replace("\\n", "\n"), args.fg, args.bg)], [100], args)


def cmd_battery(_args, kb):
    level_ = kb.battery()
    print(f"Battery: {level_}%" if level_ is not None else "Battery: no reply (keyboard asleep? press a key)")


def _global_options(p):
    """Options accepted before or after the command. SUPPRESS defaults mean a subcommand never
    resets a flag given before it. Each parser gets its own actions: argparse `parents=` shares
    action objects, and a shared default once silently dropped --dry-run."""
    p.add_argument("--link", choices=["wired", "dongle"], default=argparse.SUPPRESS,
                   help="force USB-C (wired) or 2.4 GHz dongle; default: auto")
    p.add_argument("-n", "--dry-run", action="store_true", default=argparse.SUPPRESS,
                   help="print the exact HID reports instead of sending them")
    p.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS,
                   help="log every report and reply")
    return p


def parser():
    ap = _global_options(argparse.ArgumentParser(prog="aula-f75", description=__doc__))
    sub = ap.add_subparsers(dest="command", required=True, metavar="command")
    _add = sub.add_parser
    sub.add_parser = lambda *a, **kw: _global_options(_add(*a, **kw))

    sub.add_parser("list", help="show the keyboard's HID interfaces and whether you can open them").set_defaults(run=cmd_list, device=False)

    def light_opts(p, mode=None):
        if mode is None:
            p.add_argument("mode", type=lambda s: P.MODE_IDS.get(s, None) if not s.isdigit() else int(s),
                           help="effect name or number: " + ", ".join(f"{n}={m}" for n, m in P.MODES.items()))
        p.add_argument("-c", "--color", type=color, default=0xFFFFFF, help="RRGGBB or name (default white)")
        p.add_argument("-b", "--brightness", type=level, default=5, help="0-5 (default 5)")
        p.add_argument("-s", "--speed", type=level, default=3, help="0-5 (default 3)")
        p.add_argument("-d", "--direction", choices=P.DIRECTIONS, default="right")
        p.add_argument("--colorful", action="store_true", help="rainbow colours instead of --color")
        p.set_defaults(run=cmd_effect, device=True)

    p = sub.add_parser("color", help="one static colour on every key, e.g. `color ff0000`")
    p.add_argument("color", type=color)
    p.add_argument("-b", "--brightness", type=level, default=5)
    p.set_defaults(run=cmd_effect, device=True, mode=1, speed=3, direction="right", colorful=False)

    light_opts(sub.add_parser("effect", help="built-in lighting effect, e.g. `effect breath -c 00ffff`"))

    p = sub.add_parser("off", help="turn the backlight off")
    p.set_defaults(run=cmd_effect, device=True, mode=0, color=0, brightness=0, speed=0, direction="right", colorful=False)

    p = sub.add_parser("keys", help="per-key colours, e.g. `keys --base 000000 w,a,s,d=red esc=00ff00`")
    p.add_argument("spec", nargs="*", help="key[,key...]=colour; keys by name (see layout.py) or LED number")
    p.add_argument("--base", type=color, help="colour for every key not listed (default: unlit)")
    p.add_argument("-b", "--brightness", type=level, default=5)
    p.set_defaults(run=cmd_keys, device=True)

    p = sub.add_parser("clock", help="set the screen clock to this computer's local time")
    p.add_argument("--at", help="set this time instead, ISO format, e.g. 2026-11-15T07:30:00")
    p.set_defaults(run=cmd_clock, device=True)

    p = sub.add_parser("image", help="upload an image or animated GIF to the screen (USB-C only)")
    p.add_argument("path")
    p.add_argument("--fit", choices=("fit", "fill", "stretch"), default="fit",
                   help="fit = letterbox like the official app (default), fill = crop, stretch = distort")
    p.add_argument("--background", default="black", help="letterbox colour (default black)")
    p.add_argument("--frame-ms", type=int, help="override every frame's duration (30-500 ms)")
    p.set_defaults(run=cmd_image, device=True, link_needed="wired")

    p = sub.add_parser("text", help="render text and show it on the screen (USB-C only)")
    p.add_argument("text", help=r"text; use \n for a new line")
    p.add_argument("--fg", default="white")
    p.add_argument("--bg", default="black")
    p.set_defaults(run=cmd_text, device=True, link_needed="wired")

    sub.add_parser("battery", help="battery level (dongle only)").set_defaults(run=cmd_battery, device=True, link_needed="dongle")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    for name, default in (("link", None), ("dry_run", False), ("verbose", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    if getattr(args, "mode", 0) is None:
        sys.exit(f"unknown effect; choose from: {', '.join(P.MODE_IDS)}")
    if isinstance(getattr(args, "direction", None), str):
        args.direction = P.DIRECTIONS.index(args.direction)
    log = (lambda msg: print(msg, file=sys.stderr)) if args.verbose else None
    try:
        if not args.device:
            return args.run(args, None)
        link = args.link or getattr(args, "link_needed", None)
        with Keyboard(link, dry_run=args.dry_run, log=log) as kb:
            args.run(args, kb)
        if args.dry_run:
            print("Dry run: nothing was sent to the keyboard.", file=sys.stderr)
    except (AulaError, PermissionError, ValueError, OSError, argparse.ArgumentTypeError) as error:
        sys.exit(f"Error: {error}")
    except KeyboardInterrupt:
        sys.exit("\nInterrupted. If a screen upload was running, replug the USB-C cable before retrying.")


if __name__ == "__main__":
    main()
