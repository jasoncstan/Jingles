"""Nintendo LZ77 type-0x10 decompressor (used in Wii opening.bnr)."""


def decompress_lz77(data: bytes) -> bytes:
    """Decompress Nintendo LZ77 (type 0x10) compressed data.

    Header format:
      Byte 0:   0x10 (compression type identifier)
      Bytes 1-3: uncompressed size (24-bit little-endian)

    Raises ValueError if the data does not start with the 0x10 magic byte.
    """
    if not data or data[0] != 0x10:
        raise ValueError(f'Not LZ77 type 0x10 (got 0x{data[0]:02X} if data else empty)')

    out_size = data[1] | (data[2] << 8) | (data[3] << 16)
    out = bytearray()
    pos = 4

    while len(out) < out_size and pos < len(data):
        flags = data[pos]
        pos += 1

        for bit in range(7, -1, -1):  # MSB to LSB
            if len(out) >= out_size:
                break
            if pos >= len(data):
                break

            if flags & (1 << bit):
                # Back-reference: 2-byte descriptor
                if pos + 1 >= len(data):
                    break
                b0 = data[pos]
                b1 = data[pos + 1]
                pos += 2

                length = (b0 >> 4) + 3
                disp = ((b0 & 0x0F) << 8) | b1  # displacement (0 = 1 byte back)
                start = len(out) - disp - 1

                # Copy byte-by-byte to correctly handle overlapping windows
                for k in range(length):
                    if len(out) >= out_size:
                        break
                    out.append(out[start + k])
            else:
                # Literal byte
                out.append(data[pos])
                pos += 1

    return bytes(out[:out_size])
