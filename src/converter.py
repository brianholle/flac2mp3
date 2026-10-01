"""Core logic for the FLAC to MP3 converter.

Handles the Google Drive workflow:
  1. The user downloads one or more .zip files (Drive splits big folders
     into several zips) into a single album folder.
  2. We unzip every zip into a hidden work folder.
  3. We find every .flac file and convert it to 320 kbps MP3 with metadata
     preserved.
  4. The MP3s land FLAT, directly in the album folder -- no subfolders --
     so the folder can be copied straight to a USB stick for car stereos
     (e.g. Audi) that are picky about folder structure. Every other file
     from the zips (txt, md5, ffp, ...) is copied out flat alongside them;
     only the FLACs get converted.
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


def _sanitize_zip_name(name):
    """Turn a zip entry name into a safe relative path.

    Some zips store absolute paths (C:\\music\\track.flac or
    /home/user/track.flac) or Windows backslash separators. Instead of
    silently dropping those files, normalize them so everything gets
    copied out. Returns "" if nothing usable remains.
    """
    name = name.replace("\\", "/")
    # Strip a Windows drive letter ("C:/...").
    if len(name) >= 2 and name[1] == ":":
        name = name[2:]
    # Strip leading slashes -> relative path.
    name = name.lstrip("/")
    # Drop empty, ".", and ".." components (never climb out of the folder).
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


def _safe_extract(zip_path, dest_dir):
    """Extract a zip into dest_dir.

    Returns (files_written, skipped) where skipped is a list of
    (entry_name, reason) for entries that could not be extracted.
    Nothing is ever skipped silently.
    """
    dest_dir = Path(dest_dir)
    written = 0
    skipped = []
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        return 0, [("(whole zip)", f"not a valid zip file: {e}")]
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = _sanitize_zip_name(info.filename)
            if not rel:
                skipped.append((info.filename, "unusable file name"))
                continue
            target = dest_dir / rel
            # Backstop: never write outside the work folder.
            try:
                target.resolve().relative_to(dest_dir.resolve())
            except (ValueError, OSError):
                skipped.append((info.filename, "unsafe path"))
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                skipped.append((info.filename, f"cannot create folder: {e}"))
                continue
            if target.exists():
                # Drive's split zips should not overlap, but if they do,
                # keep the existing file when it looks identical.
                if target.stat().st_size == info.file_size:
                    skipped.append((info.filename,
                                    "already extracted from another zip"))
                    continue
                stem, suffix = target.stem, target.suffix
                i = 2
                while True:
                    alt = target.with_name(f"{stem} ({i}){suffix}")
                    if not alt.exists():
                        target = alt
                        break
                    i += 1
            try:
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            except Exception as e:  # noqa: BLE001 - report per-file
                skipped.append((info.filename, f"extract failed: {e}"))
                continue
            written += 1
    return written, skipped


def unzip_all(zips, dest_dir, progress_cb=None, log=print):
    """Unzip every zip into dest_dir.

    Returns (files_extracted, skipped_entries). Every skip is logged
    with its reason so missing files are never a mystery.
    """
    total_files = 0
    all_skipped = []
    for i, zp in enumerate(zips, 1):
        if progress_cb:
            progress_cb("unzip", i, len(zips), zp.name)
        written, skipped = _safe_extract(zp, dest_dir)
        total_files += written
        all_skipped.extend((zp.name, name, reason)
                           for name, reason in skipped)
        log(f"Unzipped {written} file(s) from {zp.name}.")
        for name, reason in skipped:
            log(f"  WARNING: skipped '{name}' in {zp.name}: {reason}")
    return total_files, all_skipped


def _copy_extra_files(work_dir, album_folder, taken_names, log=print):
    """Copy every non-FLAC file out of the zips, flat into the album folder.

    Setlists (.txt), checksums (.md5/.ffp), cover art -- everything that
    isn't a FLAC comes along, with no subfolders. macOS junk (__MACOSX,
    .DS_Store) is left behind. taken_names is shared with the MP3 planner
    so nothing ever collides. Returns the number of files copied.
    """
    album_folder = Path(album_folder)
    copied = 0
    for src in sorted(Path(work_dir).rglob("*")):
        if not src.is_file():
            continue
        try:
            rel = src.relative_to(work_dir)
        except ValueError:
            continue
        if "__MACOSX" in rel.parts or src.name == ".DS_Store":
            continue
        if src.suffix.lower() == ".flac":
            continue  # converted to MP3 separately
        dest = album_folder / src.name
        if dest.exists() and dest.stat().st_size == src.stat().st_size:
            # Already copied by an earlier run -- don't duplicate it.
            taken_names.add(dest.name.lower())
            continue
        stem, suffix = src.stem, src.suffix
        i = 2
        while dest.name.lower() in taken_names or dest.exists():
            dest = album_folder / f"{stem} ({i}){suffix}"
            i += 1
        taken_names.add(dest.name.lower())
        shutil.copy2(src, dest)
        copied += 1
    if copied:
        log(f"Copied {copied} extra file(s) from the zips "
            f"(notes, checksums, ...).")
    return copied


# ---------------------------------------------------------------------------
# Finding and converting FLAC files
# ---------------------------------------------------------------------------

def _is_junk(path):
    """macOS metadata files: never real music, never convert them."""
    path = Path(path)
    return ("__MACOSX" in path.parts
            or path.name.startswith("._")
            or path.name == ".DS_Store")


def find_flac_files(folder, work_dir=None):
    """All .flac files: loose ones in folder plus extracted ones in work_dir."""
    folder = Path(folder)
    flacs = [
        p
        for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() == ".flac"
        and not _is_work_path(p, folder)
        and not _is_junk(p)
    ]
    if work_dir and Path(work_dir).is_dir():
        flacs += [
            p for p in Path(work_dir).rglob("*")
            if p.is_file() and p.suffix.lower() == ".flac"
            and not _is_junk(p)
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
    # On Windows, subprocess would otherwise flash a console window for
    # every single track. Hide it.
    popen_kw = {}
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        popen_kw = {
            "startupinfo": startupinfo,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       **popen_kw)
    except subprocess.CalledProcessError as e:
        tmp_path.unlink(missing_ok=True)
        return False, (e.stderr or "ffmpeg failed").strip()[:300]
    except OSError as e:
        tmp_path.unlink(missing_ok=True)
        return False, str(e)[:300]
    if not tmp_path.is_file() or tmp_path.stat().st_size == 0:
        tmp_path.unlink(missing_ok=True)
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

def run_album(folder, ffmpeg=None, progress_cb=None, delete_zips=True,
              log=print):
    """Unzip + convert everything in folder.

    progress_cb(kind, done, total, label) where kind is "unzip" or "convert".
    log(message) receives plain-English progress lines.
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
        log(f"Found {len(zips)} zip file(s).")
        extracted, skipped_entries = unzip_all(zips, work_dir, progress_cb,
                                               log)

        # Shared name registry so flat MP3s and extra files never collide.
        taken = set()
        # Copy everything out of the zips first (txt, md5, ffp, ...),
        # then convert the FLACs.
        extras_copied = _copy_extra_files(work_dir, folder, taken, log)

        flacs = find_flac_files(folder, work_dir)
        if not flacs:
            return {"ok": False, "error": (
                "No music files (.flac) found in this folder. "
                "Make sure the downloaded zip files are inside it."),
                "converted": 0, "skipped": 0, "failed": 0, "failures": [],
                "zip_count": len(zips), "extracted": extracted,
                "skipped_entries": skipped_entries,
                "extras_copied": extras_copied,
                "track_count": 0, "zips_deleted": 0,
                "output_dir": str(folder)}

        log(f"Found {len(flacs)} FLAC track(s). Converting to MP3...")
        # Plan flat, collision-free output names (deterministic across runs).
        plan = [(flac, flat_mp3_path(flac, folder, taken)) for flac in flacs]

        converted, skipped, failures = 0, 0, []
        for i, (flac, mp3) in enumerate(plan, 1):
            if progress_cb:
                progress_cb("convert", i, len(plan), flac.stem)
            if already_converted(flac, mp3):
                skipped += 1
                continue
            log(f"Converting track {i} of {len(plan)}: {flac.stem}")
            ok, err = convert_file(ffmpeg, flac, mp3)
            if ok:
                converted += 1
            else:
                failures.append(f"{flac.stem}: {err}")
                log(f"  FAILED: {flac.stem}: {err}")

        deleted_zips = 0
        if delete_zips and not failures:
            for zp in zips:
                try:
                    zp.unlink()
                    deleted_zips += 1
                except OSError:
                    pass
            if deleted_zips:
                log(f"Deleted {deleted_zips} zip file(s).")
        elif delete_zips and failures:
            log("Keeping the zip files because some tracks failed.")
    finally:
        # Always remove the hidden work folder: the album folder ends up
        # holding just the flat MP3s, ready to copy to a USB stick.
        shutil.rmtree(work_dir, ignore_errors=True)

    log(f"Done: {converted} converted, {skipped} already done, "
        f"{len(failures)} failed.")
    return {
        "ok": not failures,
        "converted": converted,
        "skipped": skipped,
        "failed": len(failures),
        "failures": failures,
        "zip_count": len(zips),
        "extracted": extracted,
        "skipped_entries": skipped_entries,
        "extras_copied": extras_copied,
        "track_count": len(plan),
        "zips_deleted": deleted_zips,
        "output_dir": str(folder),
    }
