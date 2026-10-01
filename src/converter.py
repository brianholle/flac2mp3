"""Core logic for the FLAC to MP3 converter.

Handles the Google Drive workflow:
  1. The user downloads one or more .zip files (Drive splits big folders
     into several zips) into a single album folder.
  2. We unzip every zip into a hidden work folder.
  3. We find every .flac file and convert it to 320 kbps MP3 with metadata
     preserved.
  4. The MP3s land FLAT, directly in the album folder -- no subfolders --
     so the folder can be copied straight to a USB stick for car stereos
     (e.g. Audi) that are picky about folder structure.
  5. Optionally, the downloaded .zip files are deleted after a successful
     run.

The GUI in flac2mp3_gui.py calls into this module; there is no user
interaction here, only plain-English status callbacks.
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

MP3_BITRATE = "320k"
WORK_DIR_NAME = ".flac2mp3-work"  # hidden temp folder for unzipping


# ---------------------------------------------------------------------------
# Locating ffmpeg
# ---------------------------------------------------------------------------

def find_ffmpeg():
    """Return the path to a usable ffmpeg binary, or None.

    Order: bundled next to a PyInstaller build, then the imageio-ffmpeg
    pip package (used at build time), then anything on PATH.
    """
    # 1. Bundled by PyInstaller (sys._MEIPASS is the temp extraction dir).
    # The binary keeps its imageio-ffmpeg name, e.g.
    # "ffmpeg-linux-x86_64-v7.0.2" or "ffmpeg.exe", so match by prefix.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for entry in Path(meipass).iterdir():
            name = entry.name.lower()
            if entry.is_file() and (name == "ffmpeg" or name.startswith("ffmpeg-") or name == "ffmpeg.exe"):
                return str(entry)

    # 2. imageio-ffmpeg pip package (dev runs: pip install imageio-ffmpeg).
    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return exe
    except Exception:
        pass

    # 3. Whatever is on PATH (ffmpeg installed by the user).
    found = shutil.which("ffmpeg")
    if found:
        return found

    return None


# ---------------------------------------------------------------------------
# Unzipping
# ---------------------------------------------------------------------------

def _is_work_path(path, folder):
    """True if path lives inside our hidden work folder."""
    try:
        path.resolve().relative_to((folder / WORK_DIR_NAME).resolve())
        return True
    except (ValueError, OSError):
        return False


def iter_zip_files(folder):
    """All .zip files under folder, sorted, ignoring the work folder."""
    folder = Path(folder)
    zips = [
        p
        for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() == ".zip"
        and not _is_work_path(p, folder)
    ]
    return sorted(zips)


def _safe_extract(zip_path, dest_dir):
    """Extract a zip into dest_dir, guarding against zip-slip.

    Returns the number of files actually written.
    """
    dest_dir = Path(dest_dir)
    written = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = dest_dir / info.filename
            # Zip-slip protection: never write outside the work folder.
            try:
                target.resolve().relative_to(dest_dir.resolve())
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                # Drive's split zips should not overlap, but if they do,
                # keep the existing file when it looks identical.
                if target.stat().st_size == info.file_size:
                    continue
                stem, suffix = target.stem, target.suffix
                i = 2
                while True:
                    alt = target.with_name(f"{stem} ({i}){suffix}")
                    if not alt.exists():
                        target = alt
                        break
                    i += 1
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
    return written


def unzip_all(zips, dest_dir, progress_cb=None):
    """Unzip every zip in zips into dest_dir. Returns files extracted."""
    total_files = 0
    for i, zp in enumerate(zips, 1):
        if progress_cb:
            progress_cb("unzip", i, len(zips), zp.name)
        total_files += _safe_extract(zp, dest_dir)
    return total_files


# ---------------------------------------------------------------------------
# Finding and converting FLAC files
# ---------------------------------------------------------------------------

def find_flac_files(folder, work_dir=None):
    """All .flac files: loose ones in folder plus extracted ones in work_dir."""
    folder = Path(folder)
    flacs = [
        p
        for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() == ".flac"
        and not _is_work_path(p, folder)
    ]
    if work_dir and Path(work_dir).is_dir():
        flacs += [
            p for p in Path(work_dir).rglob("*")
            if p.is_file() and p.suffix.lower() == ".flac"
        ]
    # Deduplicate just in case.
    seen = set()
    unique = []
    for p in sorted(flacs):
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def flat_mp3_path(flac_path, album_folder, taken_names):
    """Pick a unique flat output path directly in the album folder.

    taken_names tracks names already assigned this run so two tracks with
    the same file name never collide.
    """
    album_folder = Path(album_folder)
    stem = Path(flac_path).stem
    candidate = album_folder / f"{stem}.mp3"
    i = 2
    while candidate.name.lower() in taken_names:
        candidate = album_folder / f"{stem} ({i}).mp3"
        i += 1
    taken_names.add(candidate.name.lower())
    return candidate


def convert_file(ffmpeg, flac_path, mp3_path):
    """Convert one FLAC to 320 kbps MP3. Returns (ok, error_message)."""
    mp3_path = Path(mp3_path)
    # Temp name must keep a real .mp3 extension so ffmpeg picks the muxer.
    tmp_path = mp3_path.with_name(mp3_path.stem + ".tmp.mp3")
    cmd = [
        ffmpeg,
        "-y",
        "-v", "error",
        "-i", str(flac_path),
        "-map_metadata", "0",
        "-codec:a", "libmp3lame",
        "-b:a", MP3_BITRATE,
        str(tmp_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or "ffmpeg failed").strip()[:300]
    except OSError as e:
        return False, str(e)[:300]
    if not tmp_path.is_file() or tmp_path.stat().st_size == 0:
        return False, "ffmpeg produced no output file"
    try:
        tmp_path.replace(mp3_path)
    except OSError as e:
        tmp_path.unlink(missing_ok=True)
        return False, str(e)[:300]
    return True, ""


def already_converted(flac_path, mp3_path):
    mp3_path = Path(mp3_path)
    return (
        mp3_path.is_file()
        and mp3_path.stat().st_size > 0
        and mp3_path.stat().st_mtime >= Path(flac_path).stat().st_mtime
    )


# ---------------------------------------------------------------------------
# Whole-album run
# ---------------------------------------------------------------------------

def run_album(folder, ffmpeg=None, progress_cb=None, delete_zips=True):
    """Unzip + convert everything in folder.

    progress_cb(kind, done, total, label) where kind is "unzip" or "convert".
    The MP3s are written flat into folder (no subfolders). The downloaded
    zips are deleted afterwards when everything succeeded and delete_zips
    is set. Returns a summary dict.
    """
    folder = Path(folder)
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        return {"ok": False, "error": (
            "Could not find the audio converter (ffmpeg). "
            "Please reinstall the app.")}

    work_dir = folder / WORK_DIR_NAME
    work_dir.mkdir(exist_ok=True)
    try:
        zips = iter_zip_files(folder)
        extracted = unzip_all(zips, work_dir, progress_cb)

        flacs = find_flac_files(folder, work_dir)
        if not flacs:
            return {"ok": False, "error": (
                "No music files (.flac) found in this folder. "
                "Make sure the downloaded zip files are inside it.")}

        # Plan flat, collision-free output names (deterministic across runs).
        taken = set()
        plan = [(flac, flat_mp3_path(flac, folder, taken)) for flac in flacs]

        converted, skipped, failures = 0, 0, []
        for i, (flac, mp3) in enumerate(plan, 1):
            if progress_cb:
                progress_cb("convert", i, len(plan), flac.stem)
            if already_converted(flac, mp3):
                skipped += 1
                continue
            ok, err = convert_file(ffmpeg, flac, mp3)
            if ok:
                converted += 1
            else:
                failures.append(f"{flac.stem}: {err}")

        deleted_zips = 0
        if delete_zips and not failures:
            for zp in zips:
                try:
                    zp.unlink()
                    deleted_zips += 1
                except OSError:
                    pass
    finally:
        # Always remove the hidden work folder: the album folder ends up
        # holding just the flat MP3s, ready to copy to a USB stick.
        shutil.rmtree(work_dir, ignore_errors=True)

    return {
        "ok": not failures,
        "converted": converted,
        "skipped": skipped,
        "failed": len(failures),
        "failures": failures,
        "zip_count": len(zips),
        "extracted": extracted,
        "track_count": len(plan),
        "zips_deleted": deleted_zips,
        "output_dir": str(folder),
    }
