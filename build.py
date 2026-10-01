"""Build a portable, double-clickable app with PyInstaller.

Usage:  python build.py

Produces:
  Windows:  dist/FLAC to MP3/FLAC to MP3.exe   (single file)
  macOS:    dist/FLAC to MP3.app               (app bundle)
  Linux:    dist/FLAC to MP3/FLAC to MP3        (single file)

The ffmpeg binary is bundled automatically via the imageio-ffmpeg package,
so users never need to install anything else.

Prerequisites:  pip install -r requirements.txt pyinstaller
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    try:
        import imageio_ffmpeg  # noqa
    except ImportError:
        sys.exit("imageio-ffmpeg is not installed. Run: pip install -r requirements.txt")

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    sep = ";" if sys.platform == "win32" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "FLAC to MP3",
        "--add-binary", f"{ffmpeg_exe}{sep}.",
        str(ROOT / "src" / "flac2mp3_gui.py"),
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
    print("\nDone. Look in the dist/ folder.")


if __name__ == "__main__":
    main()
