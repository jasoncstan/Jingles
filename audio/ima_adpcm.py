"""IMA-ADPCM decoder used by Nintendo DS DSi banner sounds."""
import struct

_STEP_TABLE = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
    143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
    1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
    4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
    27086, 29794, 32767,
]  # 89 entries

_INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8,
                -1, -1, -1, -1, 2, 4, 6, 8]


def decode_ima_adpcm(data: bytes) -> list:
    """Decode NDS DSi IMA-ADPCM block to a list of signed 16-bit PCM samples.

    Data layout:
      Bytes 0-1: initial predictor value (s16 LE)
      Byte  2:   initial step index (u8, clamped 0-88)
      Byte  3:   padding (ignored)
      Bytes 4+:  nibble-packed ADPCM data, LOW nibble first per byte

    Returns a list of int values in range [-32768, 32767].
    """
    if len(data) < 4:
        return []

    predictor = struct.unpack_from('<h', data, 0)[0]
    step_index = max(0, min(88, data[2]))
    samples = [predictor]

    for i in range(4, len(data)):
        byte = data[i]
        # Process low nibble first, then high nibble (NDS convention)
        for nibble in (byte & 0x0F, (byte >> 4) & 0x0F):
            step = _STEP_TABLE[step_index]
            diff = step >> 3
            if nibble & 1:
                diff += step >> 2
            if nibble & 2:
                diff += step >> 1
            if nibble & 4:
                diff += step
            if nibble & 8:
                predictor -= diff
            else:
                predictor += diff
            predictor = max(-32768, min(32767, predictor))
            step_index = max(0, min(88, step_index + _INDEX_TABLE[nibble]))
            samples.append(predictor)

    return samples
