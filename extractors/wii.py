"""Nintendo Wii banner sound extractor.

Wii games store a channel banner in opening.bnr inside the disc filesystem.
This file is an LZ77-compressed U8 archive containing:
  - banner.bin  (visual banner)
  - icon.bin    (animated icon)
  - sound.bns   (BNS audio file with DSP-ADPCM)

Works with decrypted ISO dumps, WBFS files, and RVZ/WIA (if DolphinTool
is available to convert them to ISO first). Encrypted retail ISOs will
fail the FST validation check inside WiiDisc and fall through to the
generic FFmpeg extractor.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from extractors.base import BaseExtractor
from formats.wii_disc import WiiDisc
from formats.u8 import U8Archive
from audio.bns import BnsParser
from utils import find_dolphintool

# Extensions that need conversion to ISO before processing
_NEEDS_CONVERT = {'.rvz', '.wia'}


class WiiExtractor(BaseExtractor):
    def extract(self, rom_path: str):
        try:
            return self._extract(rom_path)
        except Exception:
            return None

    def _extract(self, rom_path: str):
        ext = Path(rom_path).suffix.lower()

        # RVZ/WIA: need DolphinTool (can't read these formats directly)
        if ext in _NEEDS_CONVERT:
            return self._extract_via_convert(rom_path)

        # Try reading the disc directly (works for decrypted ISO/WBFS)
        result = self._extract_disc(rom_path)
        if result is not None:
            return result

        # Fallback: use DolphinTool extract for encrypted ISOs
        return self._extract_via_convert(rom_path)

    def _extract_disc(self, rom_path: str):
        """Extract from a directly-readable disc image (ISO/WBFS/WUX)."""
        with WiiDisc(rom_path) as disc:
            bnr_data = disc.find_opening_bnr()

        if bnr_data is None:
            return None

        return self._parse_bnr(bnr_data)

    def _extract_via_convert(self, rom_path: str):
        """Use DolphinTool to extract opening.bnr directly (handles encryption)."""
        dolphin_tool = find_dolphintool()
        if not dolphin_tool:
            return None

        tmp_dir = tempfile.mkdtemp(prefix='jingles_bnr_')
        try:
            r = subprocess.run(
                [dolphin_tool, 'extract',
                 '-i', rom_path, '-o', tmp_dir,
                 '-s', 'opening.bnr', '-g', '-q'],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode != 0:
                return None

            # DolphinTool puts it in DATA/files/opening.bnr
            bnr_path = os.path.join(tmp_dir, 'DATA', 'files', 'opening.bnr')
            if not os.path.isfile(bnr_path):
                return None

            with open(bnr_path, 'rb') as f:
                bnr_data = f.read()

            return self._parse_bnr(bnr_data)
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _parse_bnr(bnr_data: bytes):
        """Parse an opening.bnr and extract BNS audio.

        Handles two formats:
          - Raw U8 archive (magic 0x55AA382D at offset 0)
          - IMET header with embedded U8 archive (0x40 zero padding +
            'IMET' at 0x40, U8 data at 0x600)
        Also handles IMD5 hash wrappers around sound.bin/sound.bns.
        """
        import struct

        u8_data = None

        # Check for U8 magic directly
        if len(bnr_data) >= 4:
            magic = struct.unpack_from('>I', bnr_data, 0)[0]
            if magic == 0x55AA382D:
                u8_data = bnr_data

        # Check for IMET header (U8 at offset 0x600)
        if u8_data is None and len(bnr_data) > 0x604:
            if bnr_data[0x40:0x44] == b'IMET':
                imet_magic = struct.unpack_from('>I', bnr_data, 0x600)[0]
                if imet_magic == 0x55AA382D:
                    u8_data = bnr_data[0x600:]

        # Check for LZ77-compressed U8 (byte 0x10 at start)
        if u8_data is None and len(bnr_data) > 4 and bnr_data[0] == 0x10:
            from formats.lz77 import decompress_lz77
            try:
                decompressed = decompress_lz77(bnr_data)
                magic = struct.unpack_from('>I', decompressed, 0)[0]
                if magic == 0x55AA382D:
                    u8_data = decompressed
            except Exception:
                pass

        if u8_data is None:
            return None

        try:
            archive = U8Archive(u8_data)
        except Exception:
            return None

        bns_data = archive.get_file('sound.bns')
        if bns_data is None:
            bns_data = archive.get_file('sound.bin')
        if bns_data is None:
            return None

        # Strip IMD5 hash wrapper if present (32-byte header with 'IMD5' magic)
        if len(bns_data) > 36 and bns_data[:4] == b'IMD5':
            bns_data = bns_data[32:]

        return BnsParser().parse(bns_data)
