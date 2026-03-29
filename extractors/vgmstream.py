"""vgmstream-cli extractor.

vgmstream-cli supports hundreds of game audio container formats that neither
FFmpeg nor the native extractors handle. It is used as a middle-pass fallback
between the format-specific banner extractors and the generic FFmpeg extractor.

Drop vgmstream-cli.exe (or vgmstream64-cli.exe) into the tools/ directory.
Download: https://github.com/vgmstream/vgmstream/releases
"""
import os
import subprocess


class VgmstreamExtractor:
    """Extract the first audio stream from a file using vgmstream-cli."""

    def extract_to_wav(self, rom_path: str, wav_path: str, vgmstream: str) -> bool:
        """Run vgmstream-cli to decode rom_path into a WAV file.

        vgmstream-cli handles the first subsong by default (-s 1).
        We pass -l 2 to limit loop count to 2 so looping tracks don't run
        forever (vgmstream respects -l for loop-aware formats).

        Returns True if a non-empty WAV was written.
        """
        cmd = [
            vgmstream,
            '-o', wav_path,
            '-l', '1.5',   # play 1.5 loops (enough for a 6-second jingle)
            '-f', '0',     # no fade-in
            rom_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode == 0 and os.path.exists(wav_path):
                return os.path.getsize(wav_path) > 44
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return False
