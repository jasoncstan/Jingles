"""WAV file writing and sample manipulation utilities."""
import struct
import wave
import io


def write_wav(samples: list, rate: int, channels: int, path: str):
    """Write a list of signed 16-bit PCM samples to a WAV file.

    Args:
        samples:  Interleaved s16 samples (L,R,L,R,... for stereo).
        rate:     Sample rate in Hz.
        channels: Number of audio channels (1=mono, 2=stereo).
        path:     Output file path.
    """
    with wave.open(path, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frame_data = struct.pack(f'<{len(samples)}h', *samples)
        w.writeframes(frame_data)


def loop_to_min_duration(samples: list, rate: int, channels: int,
                         min_secs: float = 3.0) -> list:
    """Loop samples until they reach at least min_secs duration.

    Only loops if the audio is shorter than min_secs. For audio already
    at or above min_secs, returns samples unchanged (possibly still shorter
    than max_secs; the converter handles the final trim).
    """
    target_frames = int(min_secs * rate)
    frames = len(samples) // channels

    if frames >= target_frames:
        return samples

    result = samples[:]
    while len(result) // channels < target_frames:
        result += samples

    return result
