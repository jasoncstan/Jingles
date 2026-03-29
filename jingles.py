"""Jingles - ROM Banner Sound Extractor
Entry point: launch the application.

Requirements:
  - Python 3.8+
  - FFmpeg installed and in PATH (https://ffmpeg.org/download.html)
    (for generic audio fallback and MP3 encoding)

Supported ROM formats with native banner extraction:
  .nds / .dsi  – Nintendo DS / DSi (DSi-enhanced ROMs only)
  .iso / .wbfs – Wii (decrypted ISO/WBFS dumps only)
  .3ds         – Nintendo 3DS (unencrypted / NoCrypto ROMs only)

All other formats fall back to FFmpeg to extract the first audio stream.
"""
import sys
import os


def _check_python():
    if sys.version_info < (3, 8):
        print('Jingles requires Python 3.8 or later.')
        sys.exit(1)


def main():
    _check_python()

    # Allow running from the project root without installing
    sys.path.insert(0, os.path.dirname(__file__))

    try:
        from gui.main_window import JinglesApp
    except ImportError as e:
        print(f'Failed to import GUI module: {e}')
        sys.exit(1)

    app = JinglesApp()
    app.mainloop()


if __name__ == '__main__':
    main()
