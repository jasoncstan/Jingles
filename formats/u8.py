"""Wii U8 archive parser (used inside opening.bnr files)."""
import struct


class U8Archive:
    """Parse a Wii U8 archive and allow file lookup by path.

    U8 archives store files and directories in a flat node array followed
    by a string table. All values are big-endian.
    """

    MAGIC = 0x55AA382D  # b'U\xaa8-'

    def __init__(self, data: bytes):
        if len(data) < 32:
            raise ValueError('U8 data too short')
        magic = struct.unpack_from('>I', data, 0)[0]
        if magic != self.MAGIC:
            raise ValueError(f'Not a U8 archive (magic=0x{magic:08X})')

        root_offset = struct.unpack_from('>I', data, 4)[0]
        self._data = data

        # Root node: type=1, node[8:12] = total node count
        num_nodes = struct.unpack_from('>I', data, root_offset + 8)[0]
        self._str_table_off = root_offset + num_nodes * 12
        self._root_off = root_offset
        self._num_nodes = num_nodes
        self._files = self._build_file_map()

    def _build_file_map(self) -> dict:
        """Build a dict of lowercase_virtual_path -> (data_offset, size)."""
        files = {}
        data = self._data
        root_off = self._root_off
        str_off = self._str_table_off

        # Stack entries: (path_prefix, first_index, next_sibling_index)
        dir_stack = [('', 0, self._num_nodes)]

        for i in range(1, self._num_nodes):
            entry_base = root_off + i * 12
            type_name = struct.unpack_from('>I', data, entry_base)[0]
            node_type = type_name >> 24
            name_idx = type_name & 0xFFFFFF
            data_off = struct.unpack_from('>I', data, entry_base + 4)[0]
            size_or_next = struct.unpack_from('>I', data, entry_base + 8)[0]

            # Pop directories we've exited
            while len(dir_stack) > 1 and i >= dir_stack[-1][2]:
                dir_stack.pop()

            prefix = dir_stack[-1][0]

            # Read null-terminated name from string table
            name_start = str_off + name_idx
            name_end = data.index(b'\x00', name_start)
            name = data[name_start:name_end].decode('utf-8', errors='replace')

            full_path = f'{prefix}/{name}' if prefix else name

            if node_type == 1:  # directory
                dir_stack.append((full_path, i, size_or_next))
            else:  # file
                files[full_path.lower()] = (data_off, size_or_next)

        return files

    def get_file(self, path: str) -> bytes:
        """Return file data for the given path, or None if not found.

        Path matching is case-insensitive. A bare filename (no directory
        component) will match the first file with that name anywhere in
        the archive.
        """
        key = path.lower().lstrip('/')
        entry = self._files.get(key)

        if entry is None:
            # Try basename-only match
            basename = key.split('/')[-1]
            for k, v in self._files.items():
                if k.split('/')[-1] == basename:
                    entry = v
                    break

        if entry is not None:
            off, sz = entry
            return self._data[off:off + sz]

        return None

    def list_files(self) -> list:
        """Return all virtual paths in the archive."""
        return list(self._files.keys())
