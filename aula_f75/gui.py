"""Small Tk window for the AULA F75 Max: lighting, per-key colours, screen, clock, battery.

    python3 -m aula_f75.gui
All keyboard I/O runs on one worker thread, one job at a time, so two uploads can never overlap.
"""
import datetime
import json
import queue
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from . import protocol as P
from .device import Keyboard, detect
from .layout import KEYS

SCALE = 0.75  # official UI key rectangles are 800x300 px; draw them smaller
LABELS = {"backspace": "bksp", "backslash": "\\", "lbracket": "[", "rbracket": "]", "semicolon": ";", "quote": "'",
          "comma": ",", "period": ".", "slash": "/", "minus": "-", "equal": "=", "grave": "`", "pageup": "pgup",
          "pagedown": "pgdn", "capslock": "caps", "lshift": "shift", "rshift": "shift", "lctrl": "ctrl", "lwin": "win",
          "lalt": "alt", "ralt": "alt", "delete": "del", "space": "", "up": "↑", "down": "↓", "left": "←", "right": "→"}


class LogWriter:
    def __init__(self, post):
        self.post = post

    def write(self, text):
        if text.strip():
            self.post(text.rstrip("\n"))

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("AULA F75 Max")
        self.events = queue.Queue()   # (callable) run on the Tk thread
        self.jobs = queue.Queue()     # (label, fn(kb)) run on the worker thread
        threading.Thread(target=self._worker, daemon=True).start()

        self.link = tk.StringVar(value="auto")
        self.dry_run = tk.BooleanVar(value=False)
        self.status = tk.StringVar()
        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Link:").pack(side="left")
        for value, text in (("auto", "Auto"), ("wired", "USB-C"), ("dongle", "2.4 GHz")):
            ttk.Radiobutton(top, text=text, value=value, variable=self.link).pack(side="left")
        ttk.Checkbutton(top, text="Dry run (print packets, send nothing)", variable=self.dry_run).pack(side="right")
        ttk.Label(root, textvariable=self.status, padding=(8, 0)).pack(fill="x")

        tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=True, padx=8, pady=4)
        tabs.add(self._lighting_tab(tabs), text="Lighting")
        tabs.add(self._keys_tab(tabs), text="Per-key")
        tabs.add(self._screen_tab(tabs), text="Screen & clock")

        self.log = tk.Text(root, height=9, wrap="none", font="TkFixedFont", state="disabled")
        self.log.pack(fill="both", padx=8, pady=(0, 8))
        self.refresh_status()
        root.after(50, self._pump)

    # ------------------------------------------------------------- plumbing

    def post(self, fn):
        self.events.put(fn)

    def say(self, text):
        self.post(lambda: self._append(text))

    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _pump(self):
        while not self.events.empty():
            self.events.get()()
        self.root.after(50, self._pump)

    def submit(self, label, fn, need=None):
        """Queue fn(kb). need="wired"/"dongle" picks that link when the selector is on Auto."""
        link = None if self.link.get() == "auto" else self.link.get()
        link = link or need
        self.jobs.put((label, fn, link, self.dry_run.get()))
        self.say(f"> {label}" + (" (dry run)" if self.dry_run.get() else ""))

    def _worker(self):
        while True:
            label, fn, link, dry = self.jobs.get()
            try:
                # in a dry run the DryRun transport already prints every packet
                with Keyboard(link, dry_run=dry, out=LogWriter(self.say), log=None if dry else self.say) as kb:
                    result = fn(kb)
                self.say(f"  done{': ' + str(result) if result is not None else ''}")
            except Exception as error:  # show every failure in the window; the worker must survive
                self.say(f"  error: {error}")
                self.post(lambda e=error: messagebox.showerror("AULA F75 Max", f"{label} failed:\n{e}"))

    def refresh_status(self):
        found = detect()
        parts = []
        for name, label in (("wired", "USB-C"), ("dongle", "2.4 GHz dongle")):
            ep = found[name]
            if ep:
                import os
                ok = os.access(ep.path, os.R_OK | os.W_OK)
                parts.append(f"{label}: {ep.path}" + ("" if ok else " (no permission: install the udev rule)"))
        self.status.set("  ·  ".join(parts) or "Keyboard not found: plug in the USB-C cable or the 2.4 GHz dongle")
        self.root.after(3000, self.refresh_status)

    def _color_button(self, parent, var, text="Colour…"):
        def pick():
            _, hexcolor = colorchooser.askcolor(var.get(), parent=self.root)
            if hexcolor:
                var.set(hexcolor)
                swatch.configure(background=hexcolor)
        frame = ttk.Frame(parent)
        swatch = tk.Label(frame, width=3, background=var.get(), relief="solid", borderwidth=1)
        swatch.pack(side="left", padx=(0, 4))
        ttk.Button(frame, text=text, command=pick).pack(side="left")
        var.trace_add("write", lambda *_: swatch.configure(background=var.get()))
        return frame

    # ------------------------------------------------------------- lighting

    def _lighting_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        self.mode = tk.StringVar(value="static")
        self.color = tk.StringVar(value="#ff0000")
        self.colorful = tk.BooleanVar(value=False)
        self.brightness = tk.IntVar(value=5)
        self.speed = tk.IntVar(value=3)
        self.direction = tk.StringVar(value="right")
        rows = [
            ("Effect", ttk.Combobox(f, textvariable=self.mode, values=[m for m in P.MODE_IDS], state="readonly", width=14)),
            ("Colour", self._color_button(f, self.color)),
            ("", ttk.Checkbutton(f, text="Rainbow colours instead", variable=self.colorful)),
            ("Brightness", tk.Scale(f, from_=0, to=P.LEVEL_MAX, orient="horizontal", variable=self.brightness, length=200)),
            ("Speed", tk.Scale(f, from_=0, to=P.LEVEL_MAX, orient="horizontal", variable=self.speed, length=200)),
            ("Direction", ttk.Combobox(f, textvariable=self.direction, values=P.DIRECTIONS, state="readonly", width=14)),
        ]
        for r, (label, widget) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
            widget.grid(row=r, column=1, sticky="w", pady=3)
        buttons = ttk.Frame(f)
        buttons.grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=8)
        ttk.Button(buttons, text="Apply", command=self.apply_lighting).pack(side="left")
        ttk.Button(buttons, text="Lights off", command=lambda: self.submit(
            "lights off", lambda kb: kb.lighting(0, 0, 0, 0, 0, False))).pack(side="left", padx=6)
        return f

    def apply_lighting(self):
        mode = P.MODE_IDS[self.mode.get()]
        color = int(self.color.get().lstrip("#"), 16)
        args = (mode, color, self.brightness.get(), self.speed.get(), P.DIRECTIONS.index(self.direction.get()), self.colorful.get())
        self.submit(f"lighting {self.mode.get()} {self.color.get()}", lambda kb: kb.lighting(*args))

    # ------------------------------------------------------------- per-key

    def _keys_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        self.key_colors = {}  # light_index -> "#rrggbb"
        self.paint = tk.StringVar(value="#00aaff")
        self.key_brightness = tk.IntVar(value=5)
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Label(bar, text="Click or drag over keys to paint them.").pack(side="left")
        self._color_button(bar, self.paint, "Paint colour…").pack(side="left", padx=10)
        width = max(x + w for _, x, _, w, _ in KEYS.values())
        height = max(y + hh for _, _, y, _, hh in KEYS.values())
        self.canvas = tk.Canvas(f, width=int((width - 70) * SCALE), height=int((height + 10) * SCALE), background="#202020",
                                highlightthickness=0)
        self.canvas.pack(pady=8)
        self.key_items = {}
        for name, (index, x, y, w, hh) in KEYS.items():
            x0, y0 = (x - 80) * SCALE, (y - 20) * SCALE
            rect = self.canvas.create_rectangle(x0, y0, x0 + w * SCALE, y0 + hh * SCALE, fill="#000000", outline="#808080")
            label = LABELS.get(name, name)
            text = self.canvas.create_text(x0 + w * SCALE / 2, y0 + hh * SCALE / 2, text=label, fill="#c0c0c0", font=("TkDefaultFont", 7))
            self.key_items[rect] = self.key_items[text] = index
        self.index_rects = {i: r for r, i in self.key_items.items() if self.canvas.type(r) == "rectangle"}
        for event in ("<Button-1>", "<B1-Motion>"):
            self.canvas.bind(event, self._paint_at)
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Button(row, text="Fill all", command=lambda: self._fill(self.paint.get())).pack(side="left")
        ttk.Button(row, text="Clear", command=lambda: self._fill(None)).pack(side="left", padx=4)
        ttk.Button(row, text="Load…", command=self._load_keys).pack(side="left", padx=4)
        ttk.Button(row, text="Save…", command=self._save_keys).pack(side="left")
        ttk.Label(row, text="Brightness").pack(side="left", padx=(16, 2))
        tk.Scale(row, from_=0, to=P.LEVEL_MAX, orient="horizontal", variable=self.key_brightness, length=120).pack(side="left")
        ttk.Button(row, text="Apply to keyboard", command=self.apply_keys).pack(side="right")
        return f

    def _set_key(self, index, color):
        if color is None:
            self.key_colors.pop(index, None)
        else:
            self.key_colors[index] = color
        self.canvas.itemconfigure(self.index_rects[index], fill=color or "#000000")

    def _paint_at(self, event):
        for item in self.canvas.find_overlapping(event.x, event.y, event.x, event.y):
            if item in self.key_items:
                self._set_key(self.key_items[item], self.paint.get())

    def _fill(self, color):
        for index in self.index_rects:
            self._set_key(index, color)

    def _load_keys(self):
        path = filedialog.askopenfilename(filetypes=[("Key colours", "*.json")])
        if path:
            with open(path) as fh:
                data = json.load(fh)
            self._fill(None)
            for name, color in data.items():
                if name in KEYS:
                    self._set_key(KEYS[name][0], color)

    def _save_keys(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Key colours", "*.json")])
        if path:
            names = {index: name for name, (index, *_rest) in KEYS.items()}
            with open(path, "w") as fh:
                json.dump({names[i]: c for i, c in sorted(self.key_colors.items())}, fh, indent=1)

    def apply_keys(self):
        colors = {i: int(c.lstrip("#"), 16) for i, c in self.key_colors.items()}
        brightness = self.key_brightness.get()
        self.submit(f"per-key colours ({len(colors)} keys)", lambda kb: kb.per_key(colors, brightness))

    # ------------------------------------------------------------- screen

    def _screen_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        self.images, self.delays, self.preview_index = [], [], 0
        self.fit = tk.StringVar(value="fit")
        self.text = tk.StringVar(value="Hello")
        left = ttk.Frame(f)
        left.pack(side="left", fill="y")
        ttk.Button(left, text="Open image or GIF…", command=self._open_image).pack(anchor="w")
        fit_row = ttk.Frame(left)
        fit_row.pack(anchor="w", pady=4)
        ttk.Label(fit_row, text="Fit").pack(side="left")
        ttk.Combobox(fit_row, textvariable=self.fit, values=("fit", "fill", "stretch"), state="readonly", width=8).pack(side="left", padx=4)
        text_row = ttk.Frame(left)
        text_row.pack(anchor="w", pady=4)
        ttk.Entry(text_row, textvariable=self.text, width=16).pack(side="left")
        ttk.Button(text_row, text="Make text image", command=self._make_text).pack(side="left", padx=4)
        self.frames_label = ttk.Label(left, text="No image loaded")
        self.frames_label.pack(anchor="w", pady=4)
        ttk.Button(left, text="Upload to screen (USB-C)", command=self.upload).pack(anchor="w", pady=(8, 2))
        self.progress = ttk.Progressbar(left, length=200, maximum=1)
        self.progress.pack(anchor="w")
        ttk.Separator(left).pack(fill="x", pady=10)
        ttk.Button(left, text="Set keyboard clock to now", command=lambda: self.submit(
            "set clock", lambda kb: kb.set_clock(datetime.datetime.now()))).pack(anchor="w")
        battery_row = ttk.Frame(left)
        battery_row.pack(anchor="w", pady=6)
        ttk.Button(battery_row, text="Battery (2.4 GHz)", command=lambda: self.submit(
            "battery", lambda kb: f"{kb.battery()}%", need="dongle")).pack(side="left")
        self._photo = tk.PhotoImage(width=256, height=256)  # with an image, Label sizes are pixels, not text lines
        self.preview = tk.Label(f, background="black", image=self._photo)
        self.preview.pack(side="left", padx=16)
        self._animate()
        return f

    def _open_image(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.gif *.png *.jpg *.jpeg *.webp *.bmp"), ("All", "*")])
        if path:
            from .screen import load_frames
            try:
                self._set_frames(*load_frames(path, self.fit.get()), path.rsplit("/", 1)[-1])
            except Exception as error:
                messagebox.showerror("AULA F75 Max", f"Cannot load {path}:\n{error}")

    def _make_text(self):
        from .screen import text_frame
        self._set_frames([text_frame(self.text.get().replace("\\n", "\n"))], [100], "text")

    def _set_frames(self, images, delays, name):
        self.images, self.delays, self.preview_index = images, delays, 0
        chunks = -(-(P.HEADER_LEN + len(images) * P.FRAME_LEN) // P.CHUNK_LEN)
        self.frames_label.configure(text=f"{name}: {len(images)} frame(s), {chunks} chunks (~{chunks * 0.14:.0f} s)")

    def _animate(self):
        delay = 200
        if self.images:
            from PIL import Image, ImageTk
            image = self.images[self.preview_index % len(self.images)]
            self._photo = ImageTk.PhotoImage(image.resize((256, 256), Image.NEAREST))
            self.preview.configure(image=self._photo, width=256, height=256)
            delay = max(P.DELAY_MS[0], min(P.DELAY_MS[1], self.delays[self.preview_index % len(self.delays)]))
            self.preview_index += 1
        self.root.after(delay, self._animate)

    def upload(self):
        if not self.images:
            messagebox.showinfo("AULA F75 Max", "Open an image or make a text image first.")
            return
        from .screen import to_rgb565
        stream = P.screen_stream(to_rgb565(self.images), self.delays)
        self.progress.configure(value=0)

        def progress(done, total):
            self.post(lambda: self.progress.configure(value=done / total))

        self.submit(f"screen upload ({len(self.images)} frames)", lambda kb: kb.upload_screen(stream, progress), need="wired")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
