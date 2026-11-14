"""Turn images, GIFs and text into the keyboard's 128x128 RGB565 frames (needs Pillow)."""
from .protocol import MAX_FRAMES, SCREEN, rgb565_frame

FITS = ("fit", "fill", "stretch")  # fit = letterbox on black, as the official app does


def _place(frame, fit, background):
    from PIL import Image

    rgba = frame.convert("RGBA")
    canvas = Image.new("RGBA", (SCREEN, SCREEN), background)
    w, h = rgba.size
    if fit == "stretch":
        size = (SCREEN, SCREEN)
    else:
        scale = (min if fit == "fit" else max)(SCREEN / w, SCREEN / h)
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
    scaled = rgba.resize(size, Image.LANCZOS)
    canvas.alpha_composite(scaled, ((SCREEN - size[0]) // 2, (SCREEN - size[1]) // 2))
    return canvas.convert("RGB")


def load_frames(path, fit="fit", background="black", max_frames=MAX_FRAMES):
    """Return ([128x128 PIL RGB images], [delay_ms per frame]) for a still image or animation."""
    from PIL import Image, ImageSequence

    if fit not in FITS:
        raise ValueError(f"fit must be one of {FITS}")
    with Image.open(path) as source:
        images, delays = [], []
        for frame in ImageSequence.Iterator(source):
            if len(images) == max_frames:
                break
            images.append(_place(frame, fit, background))
            delays.append(int(frame.info.get("duration") or 100))
    return images, delays


def text_frame(text, fg="white", bg="black", size=None):
    """Render text centred on a 128x128 frame, shrinking the font until it fits."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (SCREEN, SCREEN), bg)
    draw = ImageDraw.Draw(image)
    for points in ([size] if size else range(48, 7, -2)):
        try:
            font = ImageFont.load_default(points)
        except TypeError:  # Pillow < 10.1 has no sized default font
            font = ImageFont.load_default()
        box = draw.multiline_textbbox((0, 0), text, font=font, align="center")
        if box[2] - box[0] <= SCREEN - 4 and box[3] - box[1] <= SCREEN - 4:
            break
    x = (SCREEN - (box[2] - box[0])) // 2 - box[0]
    y = (SCREEN - (box[3] - box[1])) // 2 - box[1]
    draw.multiline_text((x, y), text, font=font, fill=fg, align="center")
    return image


def to_rgb565(images):
    return [rgb565_frame(im.tobytes()) for im in images]
