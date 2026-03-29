"""Nintendo 3DS banner sound extractor.

Supports three container formats that all share the same NCCH inner structure:
  .3ds/.cci (NCSD) — NCSD -> Partition 0 (NCCH) -> ExeFS -> 'banner' -> CWAV
  .cia       (CIA)  — CIA header -> Content 0 (NCCH) -> ExeFS -> 'banner' -> CWAV

Only works on ROMs with the NoCrypto flag set in the NCCH header (bit 2 of
the crypto flags byte at NCCH+0x18F). Encrypted ROMs (retail dumps) will
return None and fall through to the generic FFmpeg extractor.
"""
import struct
from extractors.base import BaseExtractor
from audio.cwav import CwavParser

# All 3DS media units are 0x200 bytes
_MEDIA_UNIT = 0x200

_NCSD_MAGIC = b'NCSD'
_NCCH_MAGIC = b'NCCH'


class N3dsExtractor(BaseExtractor):
    def extract(self, rom_path: str):
        try:
            return self._extract(rom_path)
        except Exception:
            return None

    def _extract(self, rom_path: str):
        with open(rom_path, 'rb') as f:
            ncch_off = self._find_ncch(f)
            if ncch_off is None:
                return None

            banner_data = self._read_banner(f, ncch_off)
            if not banner_data:
                return None

        return CwavParser().find_and_parse(banner_data)

    # ------------------------------------------------------------------
    # Container format detection
    # ------------------------------------------------------------------

    def _find_ncch(self, f) -> int | None:
        """Return the absolute file offset of the main NCCH partition.

        Detects NCSD (.3ds/.cci) and CIA containers automatically.
        """
        # Try NCSD first (magic at 0x100)
        f.seek(0x100)
        if f.read(4) == _NCSD_MAGIC:
            return self._ncch_from_ncsd(f)

        # Try CIA (starts at 0x00 with a header whose size is at offset 0)
        return self._ncch_from_cia(f)

    def _ncch_from_ncsd(self, f) -> int | None:
        """Extract NCCH offset from an NCSD container (.3ds/.cci)."""
        f.seek(0x120)
        p0_off = struct.unpack('<I', f.read(4))[0] * _MEDIA_UNIT
        p0_sz = struct.unpack('<I', f.read(4))[0] * _MEDIA_UNIT
        if p0_sz == 0:
            return None

        f.seek(p0_off + 0x100)
        if f.read(4) != _NCCH_MAGIC:
            return None

        return p0_off

    def _ncch_from_cia(self, f) -> int | None:
        """Extract NCCH offset from a CIA container.

        CIA layout:
          0x00: header size (u32, typically 0x2020)
          0x04: type (u16)
          0x06: version (u16)
          0x08: certificate chain size (u32)
          0x0C: ticket size (u32)
          0x10: TMD size (u32)
          0x14: meta size (u32)
          0x18: content size (u64)
        Sections follow header, each aligned to 64 bytes.
        The first content section is an NCCH partition.
        """
        f.seek(0)
        hdr = f.read(0x20)
        if len(hdr) < 0x20:
            return None

        hdr_size = struct.unpack_from('<I', hdr, 0x00)[0]
        cert_size = struct.unpack_from('<I', hdr, 0x08)[0]
        tik_size = struct.unpack_from('<I', hdr, 0x0C)[0]
        tmd_size = struct.unpack_from('<I', hdr, 0x10)[0]

        # Sanity: header size is almost always 0x2020
        if hdr_size < 0x20 or hdr_size > 0x10000:
            return None

        def align64(v):
            return (v + 63) & ~63

        content_off = (align64(hdr_size) + align64(cert_size)
                       + align64(tik_size) + align64(tmd_size))

        f.seek(content_off + 0x100)
        if f.read(4) != _NCCH_MAGIC:
            return None

        return content_off

    # ------------------------------------------------------------------
    # NCCH -> ExeFS -> banner
    # ------------------------------------------------------------------

    def _read_banner(self, f, ncch_off: int) -> bytes | None:
        """Read the 'banner' file from the ExeFS of an NCCH partition."""
        # ExeFS offset and size (media units) at NCCH header +0xA0
        f.seek(ncch_off + 0x1A0)
        exefs_off_mu = struct.unpack('<I', f.read(4))[0]
        exefs_sz_mu = struct.unpack('<I', f.read(4))[0]
        if exefs_sz_mu == 0:
            return None

        exefs_abs = ncch_off + exefs_off_mu * _MEDIA_UNIT

        # ExeFS header: 10 file entries of 16 bytes each
        f.seek(exefs_abs)
        exefs_hdr = f.read(0x200)
        if len(exefs_hdr) < 0x200:
            return None

        for i in range(10):
            name = exefs_hdr[i * 16:i * 16 + 8].rstrip(b'\x00')
            if name == b'banner':
                banner_rel = struct.unpack_from('<I', exefs_hdr, i * 16 + 8)[0]
                banner_sz = struct.unpack_from('<I', exefs_hdr, i * 16 + 12)[0]
                if banner_sz == 0:
                    return None

                banner_abs = exefs_abs + 0x200 + banner_rel
                f.seek(banner_abs)
                return f.read(banner_sz)

        return None
