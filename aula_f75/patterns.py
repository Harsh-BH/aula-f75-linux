"""Per-key colour patterns: colour gradients laid over the key positions in layout.KEYS."""
import math

from .layout import KEYS

AXES = ("x", "y", "diagonal", "radial")  # left->right, top->bottom, corner->corner, centre->edge
PATTERNS = {  # name: (axis, colour stops)
    "rainbow": ("x", (0xFF0000, 0xFF8000, 0xFFFF00, 0x00FF00, 0x00FFFF, 0x0000FF, 0x8000FF, 0xFF00FF)),
    "rainbow-rows": ("y", (0xFF0000, 0xFFFF00, 0x00FF00, 0x00FFFF, 0x0000FF, 0xFF00FF)),
    "synthwave": ("diagonal", (0xFF2A6D, 0xD300C5, 0x7A04EB, 0x05D9E8)),
    "sunset": ("y", (0xFFD319, 0xFF901F, 0xFF2975, 0x8C1EFF)),
    "ocean": ("diagonal", (0x00FFD0, 0x00A2FF, 0x0030FF, 0x1A0066)),
    "fire": ("y", (0xFF0000, 0xFF3000, 0xFF7000, 0xFFC000)),
    "aurora": ("x", (0x00FF87, 0x00E5FF, 0x5F00FF, 0xC800FF)),
    "forest": ("y", (0xA8FF3E, 0x32CD32, 0x0B6623)),
    "ice": ("radial", (0xFFFFFF, 0x9BE7FF, 0x2A6FFF)),
    "candy": ("x", (0xFF6EC7, 0xFFB3D9, 0xA0E7E5, 0xB4F8C8)),
    "neon": ("radial", (0xFF00FF, 0x8000FF, 0x00FFFF)),
}


def gradient(stops, axis="x"):
    """{light_index: 0xRRGGBB} for every key, blending the colour stops evenly along axis."""
    if not stops or axis not in AXES:
        raise ValueError(f"need at least one colour and an axis from {AXES}")
    centres = {index: (x + w / 2, y + h / 2) for index, x, y, w, h in KEYS.values()}
    xs, ys = [c[0] for c in centres.values()], [c[1] for c in centres.values()]
    mid_x, mid_y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    reach = max(math.hypot(x - mid_x, y - mid_y) for x, y in centres.values())
    colors = {}
    for index, (x, y) in centres.items():
        u, v = (x - min(xs)) / (max(xs) - min(xs)), (y - min(ys)) / (max(ys) - min(ys))
        t = {"x": u, "y": v, "diagonal": (u + v) / 2, "radial": math.hypot(x - mid_x, y - mid_y) / reach}[axis]
        pos = t * (len(stops) - 1)
        k = min(int(pos), max(len(stops) - 2, 0))
        a, b, f = stops[k], stops[min(k + 1, len(stops) - 1)], pos - k
        colors[index] = sum(round((a >> s & 255) * (1 - f) + (b >> s & 255) * f) << s for s in (16, 8, 0))
    return colors
