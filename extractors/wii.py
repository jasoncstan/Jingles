"""Nintendo Wii banner sound extractor.

Wii games store a channel banner in opening.bnr inside the disc filesystem.
This file is an LZ77-compressed U8 archive containing:
  - banner.bin  (visual banner)
  - icon.bin    (animated icon)
  - sound.bns   (BNS audio file with DSP-ADPCM)

Works with decrypted ISO dumps and WBFS files. Encrypted retail ISOs will
fail the FST validation check inside WiiDisc and fall through to the
generic FFmpeg extractor.
"""
from extractors.base import BaseExtractor
from formats.wii_disc import WiiDisc
from formats.u8 import U8Archive
from audio.bns import BnsParser


class WiiExtractor(BaseExtractor):
    def extract(self, rom_path: str):
        try:
            return self._extract(rom_path)
        except Exception:
            return None

    def _extract(self, rom_path: str):
        with WiiDisc(rom_path) as disc:
            bnr_data = disc.find_opening_bnr()

        if bnr_data is None:
            return None

        try:
            archive = U8Archive(bnr_data)
        except Exception:
            return None

        bns_data = archive.get_file('sound.bns')
        if bns_data is None:
            # Some banners use 'sound.bin' instead
            bns_data = archive.get_file('sound.bin')
        if bns_data is None:
            return None

        return BnsParser().parse(bns_data)
