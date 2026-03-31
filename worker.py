"""Background processing worker thread for Jingles.

Processes a list of ROM files: attempts format-specific extraction first,
then falls back to the generic FFmpeg extractor. All progress and log
messages are sent to the GUI via a thread-safe queue.Queue.

Message types placed on the queue:
  ('progress', (index, total, rom_stem))  – current file being processed
  ('file_status', (rom_path, status_str)) – per-file status update
  ('log', message_str)                    – log line
  ('done', (success, failed, skipped, total)) – all files finished
"""
import os
import shutil
import tempfile
import threading
import queue
from pathlib import Path

from extractors import EXTRACTOR_MAP
from extractors.generic import GenericExtractor
from extractors.vgmstream import VgmstreamExtractor
from extractors.retroarch import RetroArchExtractor, REQUIRED_BIOS, CORE_BIOS
from extractors.ps2 import Ps2Extractor, find_pcsx2
from audio.wav_utils import write_wav
from audio.converter import wav_to_mp3
from formats.archive import extract_rom
from utils import get_mp3_path, load_config

_ARCHIVE_EXTS = {'.zip', '.7z'}


class ProcessingWorker:
    STATUS_PENDING    = 'Pending'
    STATUS_PROCESSING = 'Processing...'
    STATUS_SUCCESS    = 'Done'
    STATUS_EXISTS     = 'Already Done'
    STATUS_NO_AUDIO   = 'No Audio'
    STATUS_ERROR      = 'Error'

    def __init__(self, rom_paths: list,
                 ffmpeg_path: str, seven_zip_path: str, vgmstream_path: str,
                 retroarch_path: str, retroarch_cores: str,
                 msg_queue: queue.Queue):
        """
        Args:
            rom_paths:        List of str/Path ROM file paths to process.
            ffmpeg_path:      Absolute path to the ffmpeg executable, or None.
            seven_zip_path:   Absolute path to 7z.exe, or None.
            vgmstream_path:   Absolute path to vgmstream-cli.exe, or None.
            retroarch_path:   Absolute path to retroarch.exe, or None.
            retroarch_cores:  Directory containing libretro core .dll files.
            msg_queue:        Queue for sending messages back to the GUI thread.
        """
        self._roms = [str(p) for p in rom_paths]
        self._ffmpeg = ffmpeg_path
        self._7z = seven_zip_path
        self._vgmstream = vgmstream_path
        self._retroarch = RetroArchExtractor(retroarch_path, retroarch_cores) \
            if retroarch_path else None
        self._ra_system_dir = str(Path(retroarch_path).parent / 'system') \
            if retroarch_path else None
        self._q = msg_queue
        self._cancel = threading.Event()
        self._bios_warned = set()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def cancel(self):
        """Signal the worker to stop after the current file."""
        self._cancel.set()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self):
        total = len(self._roms)
        success = failed = skipped = 0

        for i, rom_path in enumerate(self._roms):
            if self._cancel.is_set():
                self._log(f'Cancelled after {i} of {total} files.')
                break

            stem = Path(rom_path).stem
            self._q.put(('progress', (i, total, stem)))
            self._q.put(('file_status', (rom_path, self.STATUS_PROCESSING)))

            try:
                result = self._process_one(rom_path)
                if result == 'exists':
                    skipped += 1
                    self._q.put(('file_status', (rom_path, self.STATUS_EXISTS)))
                elif result:
                    success += 1
                    self._q.put(('file_status', (rom_path, self.STATUS_SUCCESS)))
                else:
                    skipped += 1
                    self._q.put(('file_status', (rom_path, self.STATUS_NO_AUDIO)))
                    self._log(f'No audio found: {stem}')
            except Exception as exc:
                failed += 1
                self._q.put(('file_status', (rom_path, self.STATUS_ERROR)))
                self._log(f'Error [{stem}]: {exc}')

        self._q.put(('progress', (total, total, '')))
        self._q.put(('done', (success, failed, skipped, total)))

    def _process_one(self, rom_path: str):
        """Try to extract, convert, and save an MP3 for one ROM.

        For archive files (.zip/.7z) the ROM is first extracted to a temp
        directory; the MP3 is still named after the archive stem.

        Returns True on success, 'exists' if already done, False if no audio.
        """
        ext = Path(rom_path).suffix.lower()
        stem = Path(rom_path).stem

        # If this is an archive, peek inside to determine the inner extension
        # so we can resolve the correct platform subfolder before extracting.
        archive_temp_dir = None
        actual_rom_path = rom_path

        if ext in _ARCHIVE_EXTS:
            extracted, archive_temp_dir = extract_rom(rom_path, self._7z)
            if extracted is None:
                self._log(f'No supported ROM found inside archive: {stem}')
                return False
            actual_rom_path = extracted
            inner_ext = Path(extracted).suffix.lower()
            self._log(f'Extracted from archive: {Path(extracted).name}')
        else:
            inner_ext = ext

        self._check_bios(inner_ext, actual_rom_path)

        # Output path: output/<Platform>/<stem>.mp3
        mp3_path = get_mp3_path(rom_path, inner_ext)

        # Skip if already generated
        if os.path.isfile(mp3_path):
            if archive_temp_dir:
                shutil.rmtree(archive_temp_dir, ignore_errors=True)
            return 'exists'

        tmp_wav = os.path.join(
            tempfile.gettempdir(),
            f'jingles_{os.getpid()}_{abs(hash(stem)) % 100000}.wav'
        )

        try:
            # 1. Try format-specific extractors
            #    Banner audio is already the correct length — preserve
            #    the full duration without trimming or fade effects.
            for extractor_cls in EXTRACTOR_MAP.get(inner_ext, []):
                result = extractor_cls().extract(actual_rom_path)
                if result is not None:
                    samples, rate, channels = result
                    write_wav(samples, rate, channels, tmp_wav)
                    wav_to_mp3(tmp_wav, mp3_path, self._ffmpeg,
                               title=stem, trim=False)
                    self._log(f'Banner audio: {stem}')
                    return True

            # 2. vgmstream-cli (hundreds of game audio container formats)
            if self._vgmstream:
                vgs = VgmstreamExtractor()
                if vgs.extract_to_wav(actual_rom_path, tmp_wav, self._vgmstream):
                    wav_to_mp3(tmp_wav, mp3_path, self._ffmpeg, title=stem)
                    self._log(f'vgmstream audio: {stem}')
                    return True

            # 3. RetroArch emulation (synthesis-based systems: VB, NES, SNES, GBA, etc.)
            #    Retry with longer capture if output is silent.
            #    Final attempt sends Start+A inputs to advance past menus.
            #    Skip for PS2 — no stable RetroArch core; handled by PCSX2 below.
            if self._retroarch and self._ffmpeg and not self._is_ps2(actual_rom_path):
                core = self._retroarch.find_core(inner_ext, actual_rom_path)
                if core:
                    core_name = Path(core).name
                    from extractors.retroarch import _CAPTURE_FRAMES_OVERRIDE, \
                        _CAPTURE_FRAMES_DEFAULT
                    base_frames = _CAPTURE_FRAMES_OVERRIDE.get(
                        inner_ext, _CAPTURE_FRAMES_DEFAULT)
                    max_frames = base_frames * 3

                    # Attempts: default, 2×, 3×, then 5× with Start+A input
                    # The 4th attempt needs extra frames to cover the time
                    # AFTER pressing Start (new intro/loading/title music).
                    attempts = [
                        (base_frames,     False),
                        (base_frames * 2, False),
                        (max_frames,      False),
                        (base_frames * 5, True),   # send Start+A
                    ]

                    for attempt, (frames, send_start) in enumerate(attempts, 1):
                        if self._cancel.is_set():
                            break
                        if attempt == 1:
                            self._log(f'Emulating ({core_name})…')
                        elif attempt < 4:
                            self._log(
                                f'Retry {attempt}/4 longer capture '
                                f'({frames} frames)… | {stem}')
                        else:
                            self._log(
                                f'Retry 4/4 sending Start+A inputs… | {stem}')

                        ok, reason = self._retroarch.extract_to_wav(
                            actual_rom_path, tmp_wav, self._ffmpeg,
                            frames_override=frames,
                            send_start=send_start)
                        if ok:
                            wav_to_mp3(tmp_wav, mp3_path, self._ffmpeg,
                                       title=stem)
                            self._log(f'Emulation audio ({core_name}): {stem}')
                            return True

                        # Only retry for silence-related failures
                        if 'too little audio' not in reason:
                            break

                    self._log(
                        f'Emulation failed ({core_name}): {reason} | {stem}')

            # 4. PCSX2 standalone (PS2 games via WASAPI loopback)
            if self._ffmpeg and self._is_ps2(actual_rom_path) and find_pcsx2():
                self._log(f'PCSX2 emulating (loopback capture)…')
                ps2 = Ps2Extractor()
                ok, reason = ps2.extract_to_wav(
                    actual_rom_path, tmp_wav, self._ffmpeg)
                if ok:
                    wav_to_mp3(tmp_wav, mp3_path, self._ffmpeg, title=stem)
                    self._log(f'PCSX2 audio: {stem}')
                    return True
                else:
                    self._log(f'PCSX2 failed: {reason} | {stem}')

            # 5. Generic FFmpeg fallback
            if self._ffmpeg:
                generic = GenericExtractor()
                if generic.extract_to_wav(actual_rom_path, tmp_wav, self._ffmpeg):
                    wav_to_mp3(tmp_wav, mp3_path, self._ffmpeg, title=stem)
                    self._log(f'FFmpeg audio: {stem}')
                    return True

            return False

        finally:
            if os.path.exists(tmp_wav):
                try:
                    os.remove(tmp_wav)
                except OSError:
                    pass
            if archive_temp_dir:
                shutil.rmtree(archive_temp_dir, ignore_errors=True)

    @staticmethod
    def _is_ps2(rom_path: str) -> bool:
        """Check if a ROM is a PS2 game based on parent folder name."""
        folder = Path(rom_path).parent.name.lower()
        return 'playstation 2' in folder or 'ps2' in folder

    def _check_bios(self, ext: str, rom_path: str = None):
        """Log a warning (once per key) if a required BIOS file is missing."""
        if not self._ra_system_dir:
            return

        # Extension-based BIOS check
        if ext in REQUIRED_BIOS and ext not in self._bios_warned:
            bios_file, system_name = REQUIRED_BIOS[ext]
            bios_path = os.path.join(self._ra_system_dir, bios_file)
            if not os.path.isfile(bios_path):
                self._log(
                    f'WARNING: {system_name} BIOS missing — '
                    f'place {bios_file} in {self._ra_system_dir}')
            self._bios_warned.add(ext)

        # Core-based BIOS check (e.g. PCSX2 needs PS2 BIOS)
        if self._retroarch:
            core = self._retroarch.find_core(ext, rom_path)
            if core:
                core_name = Path(core).name
                if core_name in CORE_BIOS and core_name not in self._bios_warned:
                    bios_files, system_name = CORE_BIOS[core_name]
                    # Check default locations
                    has_any = any(
                        os.path.isfile(os.path.join(self._ra_system_dir, f))
                        for f in bios_files)
                    # Check user-configured overrides
                    if not has_any:
                        cfg = load_config()
                        overrides = cfg.get('bios_overrides', {})
                        has_any = any(
                            os.path.isfile(overrides.get(f'{system_name}_{r}', ''))
                            for r in ['USA', 'JPN', 'EUR', ''])
                    if not has_any:
                        examples = ', '.join(bios_files[:3])
                        self._log(
                            f'WARNING: {system_name} BIOS missing — '
                            f'place a BIOS file (e.g. {examples}) '
                            f'in {self._ra_system_dir}')
                    self._bios_warned.add(core_name)

    def _log(self, msg: str):
        self._q.put(('log', msg))
