"""Abstract base class for ROM banner sound extractors."""


class BaseExtractor:
    """Subclasses implement extract() to decode banner audio from a ROM file.

    Returns:
        (samples, sample_rate, channels) tuple where samples is a list of
        interleaved signed 16-bit integers, or None if no banner audio was found.
    """

    def extract(self, rom_path: str):
        raise NotImplementedError
