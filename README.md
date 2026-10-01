# FLAC to MP3 Converter

<img width="661" height="800" alt="image" src="https://github.com/user-attachments/assets/c9b3ee08-3c54-4bad-98c6-98d187f53454" />

A super-simple app that turns downloaded concert/album files into MP3s.
Made for people who don't want to learn computers — just double-click and go.

## How to use it (for the person converting music)

**You need:** a Windows PC or a Mac, and the app file from the
[Releases page](../../releases) (pick the Windows, macOS, or Linux download).

**Steps:**

1. **Plug your USB stick into the computer.**

2. **Make a new folder on the USB stick** for the album or concert,
   e.g. `Jerry Garcia Band 1989-12-02`.

3. **Download from Google Drive into that folder.** When you open the
   shared Drive folder, click Download. Google may split big folders
   into several zip files — that's fine. Save **all** the zip files
   into the folder you just made on the USB stick.

4. **Open the app.** Double-click `FLAC to MP3` (Windows) or the
   `FLAC to MP3` app (Mac).

   - *Windows:* if Windows says "Unknown publisher", click
     **More info → Run anyway**. It's safe — it's just not registered
     with Microsoft.
   - *Mac:* the first time, right-click (or Control-click) the app and
     choose **Open**, then click **Open** again. After that it opens
     normally with a double-click.

   Click **Choose Album Folder…** and pick the folder on your USB stick.

5. **Press the big CONVERT button.** Wait while the tape rolls —
   you'll see which song it's playing. A whole concert can take
   several minutes, especially on a USB stick.

6. **Done!** Unplug the USB stick and plug it into your car. The MP3s
   are sitting right in the album folder — no subfolders — ready to play.

That's everything. The downloaded zip files are deleted automatically
when everything converts cleanly (there's a checkbox to keep them if
you'd rather). The original loose FLAC files, if any, are left alone.

## Tips

- You can run it again on the same folder any time — songs that are
  already converted are skipped.
- MP3s are made at 320 kbps, the highest MP3 quality, and keep their
  song titles and artist info.

## For developers

```bash
pip install -r requirements.txt pyinstaller
python build.py        # bundles ffmpeg, outputs to dist/
python src/flac2mp3_gui.py   # run from source (needs ffmpeg on PATH or imageio-ffmpeg installed)
```

Pushing a tag like `v1.0.0` builds all three platforms via GitHub Actions
and attaches them to a GitHub Release automatically.
