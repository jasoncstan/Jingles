"""Wii and GameCube disc image reader supporting ISO and WBFS formats.

Handles:
  - Raw Wii ISO (.iso): unencrypted/decrypted dumps only. Encrypted retail
    discs will fail FST validation and return None from find_opening_bnr().
  - WBFS (.wbfs): sparse Wii disc container. Remaps Wii logical sectors
    through the Wii LBA Block table.
  - GameCube ISO (.iso, .gcm): simpler disc format, no encryption.
    opening.bnr on GCN is a visual-only banner (no audio), so
    find_opening_bnr() returns None for GCN discs.

All Wii/GCN disc values are big-endian. Partition offsets are stored
as (value >> 2), i.e. multiply by 4 to get byte offsets.
"""
import struct
from formats.lz77 import decompress_lz77
from formats.u8 import U8Archive


class WiiDisc:
    WII_MAGIC = 0x5D1C9EA3   # at disc header offset 0x18
    GCN_MAGIC = 0xC2339F3D   # at disc header offset 0x1C
    WII_SECTOR_SIZE = 0x8000  # 32 KB per logical Wii sector

    # Wii partition table lives at this fixed disc offset
    PART_TABLE_OFF = 0x40000

    def __init__(self, path: str):
        self._path = path
        self._f = open(path, 'rb')
        self._is_wbfs = self._check_wbfs()
        if self._is_wbfs:
            self._init_wbfs()

    def _check_wbfs(self) -> bool:
        self._f.seek(0)
        return self._f.read(4) == b'WBFS'

    def _init_wbfs(self):
        self._f.seek(0)
        hdr = self._f.read(16)
        # hd_sector_shift and wbfs_sector_shift are at bytes 8 and 9
        self._wbfs_shift = hdr[9]
        self._wbfs_sector_size = 1 << self._wbfs_shift

        # Disc 0 occupies WBFS sector 1 (sector 0 is the WBFS header)
        disc_sector_off = self._wbfs_sector_size

        # The Wii LBA-Block table (WLB) starts at disc_sector_off + 0x200
        # (right after the 256-byte Wii disc header copy)
        wlb_off = disc_sector_off + 0x200

        # Full Wii disc = 4,699,979,776 bytes -> ceil / WII_SECTOR_SIZE entries
        wii_disc_bytes = 4_699_979_776
        num_wii_sectors = (wii_disc_bytes + self.WII_SECTOR_SIZE - 1) // self.WII_SECTOR_SIZE

        self._f.seek(wlb_off)
        raw = self._f.read(num_wii_sectors * 2)
        self._wlb = [
            struct.unpack_from('>H', raw, i * 2)[0]
            for i in range(min(num_wii_sectors, len(raw) // 2))
        ]
        self._disc_base = disc_sector_off

    def _raw_read(self, offset: int, size: int) -> bytes:
        self._f.seek(offset)
        return self._f.read(size)

    def read_virtual(self, offset: int, size: int) -> bytes:
        """Read bytes at a virtual (logical) Wii disc offset."""
        if not self._is_wbfs:
            return self._raw_read(offset, size)
        return self._wbfs_read(offset, size)

    def _wbfs_read(self, offset: int, size: int) -> bytes:
        result = bytearray()
        while size > 0:
            wii_sector = offset // self.WII_SECTOR_SIZE
            sector_off = offset % self.WII_SECTOR_SIZE
            chunk = min(size, self.WII_SECTOR_SIZE - sector_off)

            if wii_sector >= len(self._wlb) or self._wlb[wii_sector] == 0:
                result += b'\x00' * chunk
            else:
                phys = self._wlb[wii_sector] * self._wbfs_sector_size + sector_off
                self._f.seek(phys)
                result += self._f.read(chunk)

            offset += chunk
            size -= chunk

        return bytes(result)

    def _disc_magic(self) -> tuple:
        """Return (wii_magic, gcn_magic) from disc header."""
        hdr = self.read_virtual(0, 0x20)
        if len(hdr) < 0x20:
            return 0, 0
        wii = struct.unpack_from('>I', hdr, 0x18)[0]
        gcn = struct.unpack_from('>I', hdr, 0x1C)[0]
        return wii, gcn

    def find_opening_bnr(self) -> bytes:
        """Find and return the decompressed U8 data from opening.bnr, or None.

        Only valid for unencrypted/decrypted Wii ISOs and WBFS files.
        GameCube opening.bnr contains no audio and is skipped.
        Encrypted retail Wii ISOs will fail FST validation and return None.
        """
        wii_magic, gcn_magic = self._disc_magic()

        if gcn_magic == self.GCN_MAGIC:
            # GameCube: opening.bnr has no audio
            return None

        if wii_magic != self.WII_MAGIC:
            return None

        # Locate the DATA (type=0) partition
        data_part_off = self._find_data_partition()
        if data_part_off is None:
            return None

        # Read the partition header to get the data area offset
        # partition_header[0x2B8:0x2BC] = data_relative_offset >> 2
        part_hdr_data = self.read_virtual(data_part_off + 0x2B8, 4)
        data_rel_off = struct.unpack_from('>I', part_hdr_data, 0)[0] * 4
        data_abs_off = data_part_off + data_rel_off

        # Read the "inner" disc header from the decrypted data area
        inner_hdr = self.read_virtual(data_abs_off, 0x440)
        if len(inner_hdr) < 0x440:
            return None

        fst_off_rel = struct.unpack_from('>I', inner_hdr, 0x424)[0] * 4
        fst_size = struct.unpack_from('>I', inner_hdr, 0x428)[0]

        if fst_size == 0 or fst_size > 50 * 1024 * 1024:
            return None  # Likely encrypted or corrupt

        fst_data = self.read_virtual(data_abs_off + fst_off_rel, fst_size)

        # Validate FST root node (type must be 1 = directory)
        if len(fst_data) < 12 or fst_data[0] != 1:
            return None

        num_entries = struct.unpack_from('>I', fst_data, 8)[0]
        if num_entries < 2 or num_entries > 200_000:
            return None

        # Find opening.bnr in the FST
        str_table = num_entries * 12
        for i in range(1, num_entries):
            e = i * 12
            type_name = struct.unpack_from('>I', fst_data, e)[0]
            if (type_name >> 24) != 0:
                continue  # skip directories

            name_idx = type_name & 0xFFFFFF
            name_end = fst_data.index(b'\x00', str_table + name_idx)
            name = fst_data[str_table + name_idx:name_end].decode('ascii', errors='ignore')

            if name.lower() == 'opening.bnr':
                file_off = struct.unpack_from('>I', fst_data, e + 4)[0] * 4
                file_size = struct.unpack_from('>I', fst_data, e + 8)[0]
                raw = self.read_virtual(data_abs_off + file_off, file_size)

                # Decompress if LZ77-compressed
                if raw and raw[0] == 0x10:
                    try:
                        raw = decompress_lz77(raw)
                    except Exception:
                        return None

                return raw

        return None

    def _find_data_partition(self) -> int:
        """Return the absolute offset of the DATA partition, or None."""
        info = self.read_virtual(self.PART_TABLE_OFF, 32)
        if len(info) < 8:
            return None

        group_count = struct.unpack_from('>I', info, 0)[0]
        group_table_off = struct.unpack_from('>I', info, 4)[0] * 4

        # Typically only group 0 matters; scan all groups anyway
        for g in range(min(group_count, 4)):
            grp_info = self.read_virtual(self.PART_TABLE_OFF + g * 8, 8)
            part_count = struct.unpack_from('>I', grp_info, 0)[0]
            part_table = struct.unpack_from('>I', grp_info, 4)[0] * 4

            for p in range(min(part_count, 8)):
                entry = self.read_virtual(part_table + p * 8, 8)
                poff = struct.unpack_from('>I', entry, 0)[0] * 4
                ptype = struct.unpack_from('>I', entry, 4)[0]
                if ptype == 0:  # DATA partition
                    return poff

        return None

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
