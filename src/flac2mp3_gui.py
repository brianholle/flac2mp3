"""FLAC to MP3 Converter - Windows 95 mixtape edition.

A super-simple app for non-technical users:

  1. Download the Google Drive zip file(s) into ONE album folder.
  2. Choose that folder in the app.
  3. Press the big CONVERT button and watch the tape roll.

The MP3s land flat, right in the album folder (no subfolders), ready to
copy onto a USB stick for the car. Styled like it's 1995, because
converting tapes... er, files... should feel fun.
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

import converter  # noqa: E402

APP_TITLE = "FLAC to MP3 Converter"

# -- Windows 95 palette -------------------------------------------------
WIN95_BG = "#c0c0c0"
WIN95_DARK = "#808080"
WIN95_LIGHT = "#ffffff"
NAVY = "#000080"
NAVY_LIGHT = "#1084d0"
INK = "#000000"

TITLE_FONT = ("TkDefaultFont", 11, "bold")
BIG_FONT = ("TkDefaultFont", 12)
HUGE_FONT = ("TkDefaultFont", 16, "bold")
SMALL_FONT = ("TkDefaultFont", 10)


def win95_button(parent, **kw):
    """A classic chunky raised Win95 button."""
    kw.setdefault("bg", WIN95_BG)
    kw.setdefault("fg", INK)
    kw.setdefault("activebackground", WIN95_BG)
    kw.setdefault("relief", "raised")
    kw.setdefault("bd", 3)
    return tk.Button(parent, **kw)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=WIN95_BG)
        self.geometry("660x800")
        self.minsize(600, 700)

        self.album_folder = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Choose your album folder to begin.")
        self.delete_zips = tk.BooleanVar(value=True)
        self._queue = queue.Queue()
        self._working = False
        self._reel_angle = 0
        self._spokes = []

        self._build_ui()
        self.after(100, self._poll_queue)
        self.after(120, self._animate_reels)

    # -- UI ---------------------------------------------------------------
    def _build_ui(self):
        self._fake_title_bar()
        self._cassette_canvas = tk.Canvas(
            self, width=620, height=215, bg=WIN95_BG,
            highlightthickness=0)
        self._cassette_canvas.pack(pady=(10, 4))
        self._draw_cassette()

        tk.Label(
            self, text="HOW TO MAKE YOUR MIXTAPE:",
            font=TITLE_FONT, bg=WIN95_BG, fg=NAVY,
        ).pack(pady=(6, 2))
        tk.Label(
            self,
            text=("1. Plug your USB stick into the computer.\n"
                  "2. Make a new folder on the USB for the album.\n"
                  "3. Download the Drive zip file(s) into that folder.\n"
                  "4. Choose that folder with the button below.\n"
                  "5. Press CONVERT, wait, then plug the USB into your car!"),
            font=BIG_FONT, justify="left", bg=WIN95_BG, fg=INK,
        ).pack(padx=20, pady=4)

        folder_row = tk.Frame(self, bg=WIN95_BG)
        folder_row.pack(fill="x", padx=20, pady=8)
        win95_button(folder_row, text="Choose Album Folder…", font=BIG_FONT,
                     command=self.choose_folder, width=22).pack(side="left")
        self._sunken_label(folder_row, textvariable=self.album_folder,
                            width=34).pack(side="left", padx=12)

        self.convert_btn = win95_button(
            self, text="▶  CONVERT THE TAPE", font=HUGE_FONT,
            command=self.start_conversion, state="disabled",
            padx=24, pady=10)
        self.convert_btn.pack(pady=10)

        tk.Checkbutton(
            self,
            text="Delete the downloaded zip files when finished "
                 "(recommended - saves disk space)",
            variable=self.delete_zips, font=SMALL_FONT,
            bg=WIN95_BG, fg=INK, activebackground=WIN95_BG,
        ).pack()

        tk.Label(self, text="Progress:", font=SMALL_FONT,
                 bg=WIN95_BG, fg=INK).pack(pady=(10, 2))
        self._bar = tk.Canvas(self, width=600, height=28, bg=WIN95_BG,
                              highlightthickness=0)
        self._bar.pack()
        self._draw_bar(0.0)

        self._sunken_label(self, textvariable=self.status_text,
                            width=72).pack(padx=20, pady=10)

        log_frame = tk.Frame(self, bg=WIN95_BG)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.log = tk.Text(log_frame, height=7, font=SMALL_FONT,
                           state="disabled", wrap="word",
                           bg=WIN95_LIGHT, fg=INK,
                           relief="sunken", bd=2)
        scrollbar = tk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _sunken_label(self, parent, **kw):
        kw.setdefault("bg", WIN95_LIGHT)
        kw.setdefault("fg", INK)
        kw.setdefault("relief", "sunken")
        kw.setdefault("bd", 2)
        kw.setdefault("anchor", "w")
        kw.setdefault("justify", "left")
        lbl = tk.Label(parent, **kw)
        return lbl

    # -- fake Win95 title bar ---------------------------------------------
    def _fake_title_bar(self):
        bar = tk.Canvas(self, height=30, bg=NAVY, highlightthickness=0)
        bar.pack(fill="x")
        bar.bind("<Configure>", lambda e: self._paint_title_bar(bar))

        # Decorative (but working!) window buttons.
        for i, (glyph, action) in enumerate(
                (("_", self.iconify), ("□", lambda: None), ("X", self.destroy))):
            b = tk.Button(bar, text=glyph, font=("TkDefaultFont", 9, "bold"),
                          bg=WIN95_BG, fg=INK, relief="raised", bd=2,
                          width=3, height=1, command=action,
                          activebackground=WIN95_BG)
            b.place(relx=1.0, x=-8 - i * 40, y=3, anchor="ne")
        self._title_buttons = True

    def _paint_title_bar(self, bar):
        bar.delete("grad")
        w = bar.winfo_width()
        steps = max(w, 1)
        for x in range(steps):
            f = x / steps
            r = int(0x00 + (0x10 - 0x00) * f)
            g = int(0x00 + (0x84 - 0x00) * f)
            b = int(0x80 + (0xD0 - 0x80) * f)
            bar.create_line(x, 0, x, 30, fill=f"#{r:02x}{g:02x}{b:02x}",
                            tags="grad")
        bar.create_text(12, 15, text="♪  " + APP_TITLE, anchor="w",
                        fill="white", font=TITLE_FONT, tags="grad")
        bar.tag_lower("grad")

    # -- cassette illustration (modern restyle) ------------------------------
    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        """Rounded rectangle built from rects + corner pieslices."""
        c = self._cassette_canvas
        kw = dict(kw)
        kw.setdefault("outline", "")
        c.create_rectangle(x1 + r, y1, x2 - r, y2, **kw)
        c.create_rectangle(x1, y1 + r, x2, y2 - r, **kw)
        for cx, cy, start in ((x1 + r, y1 + r, 90), (x2 - r, y1 + r, 0),
                              (x1 + r, y2 - r, 180), (x2 - r, y2 - r, 270)):
            c.create_arc(cx - r, cy - r, cx + r, cy + r,
                         start=start, extent=90, style="pieslice", **kw)

    def _draw_cassette(self):
        c = self._cassette_canvas
        W = 620

        # Drop shadow.
        self._rounded_rect(26, 22, 594, 190, 16, fill="#0d0f13")
        # Tape body: flat modern charcoal with a top highlight.
        self._rounded_rect(20, 15, 588, 183, 16, fill="#23272f")
        self._rounded_rect(24, 18, 584, 30, 8, fill="#3a404c")

        # Label card with a bold side-A color block.
        self._rounded_rect(64, 34, 556, 82, 8, fill="#0d0f13")  # shadow
        self._rounded_rect(60, 30, 552, 78, 8, fill="#f6f6f4")
        self._rounded_rect(60, 30, 132, 78, 8, fill="#ff5a5a")
        # Fix the block's right edge (rounded helper rounds all corners).
        c.create_rectangle(116, 30, 132, 78, fill="#ff5a5a", outline="")
        c.create_text(96, 54, text="A", font=("TkDefaultFont", 22, "bold"),
                      fill="#ffffff")
        c.create_text(336, 48, text="FLAC  →  MP3",
                      font=("TkDefaultFont", 17, "bold"), fill="#1a1d23")
        c.create_text(336, 68, text="S I D E   A   ·   9 0   M I N",
                      font=("TkDefaultFont", 8), fill="#6b7280")

        # Tape window.
        self._rounded_rect(150, 92, 470, 168, 10, fill="#0b0d10")
        c.create_line(160, 96, 460, 96, fill="#1e2229", width=2)
        # The brown tape itself, running between the reels.
        c.create_rectangle(205, 126, 415, 134, fill="#7a5230", outline="")

        # Reel static rings.
        self._reel_centers = [(235, 130), (385, 130)]
        self._reel_r = 30
        for cx, cy in self._reel_centers:
            c.create_oval(cx - 30, cy - 30, cx + 30, cy + 30,
                          fill="#e8ebef", outline="#9aa1ab", width=2)
            c.create_oval(cx - 22, cy - 22, cx + 22, cy + 22,
                          outline="#c3c9d1", width=1)
        self._draw_spokes()

        # Screws: small and subtle.
        for sx, sy in ((40, 32), (580, 32), (40, 166), (580, 166)):
            c.create_oval(sx - 4, sy - 4, sx + 4, sy + 4,
                          fill="#4a5058", outline="#14171c")

        c.create_text(W // 2, 178, text="C H R O M E   D I O X I D E",
                      font=("TkDefaultFont", 8), fill="#6b7280")

    def _draw_spokes(self):
        c = self._cassette_canvas
        for item in self._spokes:
            c.delete(item)
        self._spokes = []
        import math
        for cx, cy in self._reel_centers:
            for k in range(3):
                a = math.radians(self._reel_angle + k * 120)
                x1 = cx + 10 * math.cos(a)
                y1 = cy + 10 * math.sin(a)
                x2 = cx + 27 * math.cos(a)
                y2 = cy + 27 * math.sin(a)
                self._spokes.append(
                    c.create_line(x1, y1, x2, y2, fill="#8b939e", width=6,
                                  capstyle="round"))
            self._spokes.append(
                c.create_oval(cx - 7, cy - 7, cx + 7, cy + 7,
                              fill="#1a1d23", outline="#9aa1ab"))
            self._spokes.append(
                c.create_oval(cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5,
                              fill="#ff5a5a", outline=""))

    def _animate_reels(self):
        if self._working:
            self._reel_angle = (self._reel_angle + 18) % 360
            self._draw_spokes()
        self.after(120, self._animate_reels)

    # -- chunky segmented Win95 progress bar -------------------------------
    def _draw_bar(self, fraction):
        c = self._bar
        c.delete("all")
        W, H = 600, 28
        # Sunken white well.
        c.create_rectangle(0, 0, W, H, fill=WIN95_LIGHT, outline=WIN95_DARK,
                           width=2)
        c.create_line(0, 0, W, 0, fill="#404040", width=2)
        c.create_line(0, 0, 0, H, fill="#404040", width=2)
        n = 24
        filled = int(round(max(0.0, min(1.0, fraction)) * n))
        gap, x0 = 3, 6
        bw = (W - 12 - gap * (n - 1)) / n
        for i in range(n):
            x1 = x0 + i * (bw + gap)
            x2 = x1 + bw
            col = NAVY if i < filled else WIN95_LIGHT
            c.create_rectangle(x1, 5, x2, H - 5, fill=col, outline="")

    # -- actions ------------------------------------------------------------
    def choose_folder(self):
        folder = filedialog.askdirectory(
            title="Choose the folder with your downloaded zip files")
        if folder:
            self.album_folder.set(folder)
            self.convert_btn.config(state="normal")
            self.status_text.set("Ready. Press CONVERT and let the tape roll!")
            self._log(f"Album folder: {folder}")

    def start_conversion(self):
        if self._working:
            return
        folder = self.album_folder.get()
        if not folder or not Path(folder).is_dir():
            messagebox.showwarning("No folder chosen",
                                   "Please choose your album folder first.")
            return
        self._working = True
        self.convert_btn.config(state="disabled", text="■  WORKING…")
        self._draw_bar(0.0)
        self._log("Pop the tape in… starting!")
        self.status_text.set("Warming up the tape deck…")
        thread = threading.Thread(
            target=self._worker, args=(folder,), daemon=True)
        thread.start()

    def _worker(self, folder):
        ffmpeg = converter.find_ffmpeg()
        if not ffmpeg:
            self._queue.put(("error",
                             "Could not find the audio converter. "
                             "Please reinstall the app."))
            return

        def cb(kind, done, total, label):
            self._queue.put(("progress", kind, done, total, label))

        try:
            summary = converter.run_album(
                folder, ffmpeg=ffmpeg, progress_cb=cb,
                delete_zips=self.delete_zips.get())
        except Exception as e:  # never crash on the user
            self._queue.put(("error", f"Something went wrong: {e}"))
            return
        self._queue.put(("done", summary))

    # -- UI updates (main thread) -------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "progress":
            _, phase, done, total, label = msg
            if phase == "unzip":
                self.status_text.set(
                    f"⏪ Rewinding… unzipping {done} of {total}: {label}")
                self._draw_bar(0.20 * done / max(total, 1))
            else:
                self.status_text.set(
                    f"▶ Playing track {done} of {total}: {label}")
                self._draw_bar(0.20 + 0.80 * done / max(total, 1))
        elif kind == "done":
            self._finish(msg[1])
        elif kind == "error":
            self._working = False
            self.convert_btn.config(state="normal",
                                    text="▶  CONVERT THE TAPE")
            self.status_text.set("Tape jam! Stopped.")
            messagebox.showerror("Tape jam!", msg[1])

    def _finish(self, summary):
        self._working = False
        self.convert_btn.config(state="normal", text="▶  CONVERT THE TAPE")
        if not summary.get("ok"):
            err = summary.get("error") or "\n".join(
                summary.get("failures", []))
            self.status_text.set("Finished with a tape jam.")
            messagebox.showerror("Tape jam!",
                                 f"Some tracks could not be converted:\n\n{err}")
            return
        self._draw_bar(1.0)
        n = summary["converted"] + summary["skipped"]
        out = summary["output_dir"]
        zips = summary.get("zips_deleted", 0)
        zip_note = (f"\nCleaned up {zips} zip file(s), too."
                    if zips else "")
        self._log(f"Done! {n} songs ready in:\n{out}{zip_note}")
        self.status_text.set(f"■ Done! Your mixtape is ready: {n} songs.")
        answer = messagebox.askyesno(
            "Mixtape complete!",
            f"Your mixtape is done! {n} songs, sitting right in your album "
            f"folder on the USB stick — no subfolders, ready for the car."
            f"{zip_note}\n\n"
            f"Folder:\n{out}\n\nOpen the folder now?")
        if answer:
            self._open_folder(out)

    def _open_folder(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            messagebox.showinfo("Your MP3s", f"Your MP3s are here:\n{path}")

    def _log(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
