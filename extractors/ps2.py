"""Sony PlayStation 2 audio extractor using standalone PCSX2 + WASAPI loopback.

Launches PCSX2-Qt to emulate the game, uses turbo mode to fast-forward past
boot logos, then captures system audio via WASAPI loopback recording.

Requires:
  - PCSX2-Qt in tools/PCSX2/pcsx2-qt.exe
  - PS2 BIOS in tools/PCSX2/bios/
  - pyaudiowpatch (pip install pyaudiowpatch)
"""
import ctypes
import os
import subprocess
import sys
import time
import wave

from pathlib import Path

# Seconds to run turbo boot (fast-forwarding past logos/intros).
_TURBO_BOOT_SECS = 3

# Seconds to wait at normal speed before recording (let audio stabilize).
_SETTLE_SECS = 2

# Recording duration (seconds) at normal emulation speed.
_RECORD_SECS = 8


def find_pcsx2() -> str | None:
    """Return absolute path to pcsx2-qt.exe, or None."""
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     'tools', 'PCSX2', 'pcsx2-qt.exe'),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


def _find_hwnd(pid):
    """Find a visible window belonging to the given process ID."""
    if sys.platform != 'win32':
        return None
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    result = []

    def cb(hwnd, _):
        pid_buf = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
        if pid_buf.value == pid and user32.IsWindowVisible(hwnd):
            result.append(hwnd)
        return True
    user32.EnumWindows(WNDENUMPROC(cb), None)
    return result[0] if result else None


def _send_key(hwnd, vk, scan):
    """Send a key press/release to the given window via keybd_event."""
    if sys.platform != 'win32':
        return
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    my_tid = kernel32.GetCurrentThreadId()
    ra_tid = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(my_tid, ra_tid, True)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    user32.keybd_event(vk, scan, 0, 0)       # key down
    time.sleep(0.1)
    user32.keybd_event(vk, scan, 2, 0)       # key up
    # Don't hide/minimize — PCSX2 needs an active visible window
    # to render video, which drives game execution and audio.
    user32.AttachThreadInput(my_tid, ra_tid, False)


class Ps2Extractor:
    """Extract PS2 title audio via PCSX2 emulation + WASAPI loopback."""

    def __init__(self, pcsx2_path: str = None, ffmpeg_path: str = None):
        self._pcsx2 = pcsx2_path or find_pcsx2()
        self._ffmpeg = ffmpeg_path

    def extract_to_wav(self, rom_path: str, wav_path: str, ffmpeg: str) -> tuple:
        """Emulate rom_path with PCSX2, capture audio, write wav_path.

        Returns (True, '') on success, or (False, reason_str) on failure.
        """
        if not self._pcsx2 or not os.path.isfile(self._pcsx2):
            return False, 'PCSX2 not found'

        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            return False, 'pyaudiowpatch not installed (pip install pyaudiowpatch)'

        ffmpeg = ffmpeg or self._ffmpeg
        if not ffmpeg:
            return False, 'FFmpeg not found'

        try:
            return self._run(rom_path, wav_path, ffmpeg, pyaudio)
        except Exception as e:
            return False, str(e)

    def _run(self, rom_path, wav_path, ffmpeg, pyaudio):
        # Find WASAPI loopback device
        p = pyaudio.PyAudio()
        try:
            loopback = self._find_loopback(p, pyaudio)
            if not loopback:
                return False, 'no WASAPI loopback device found'

            rate = int(loopback['defaultSampleRate'])
            channels = loopback['maxInputChannels']

            # Launch PCSX2 — not hidden so keyboard input works
            proc = subprocess.Popen(
                [self._pcsx2, '-portable', '-batch', '-fastboot',
                 '--', rom_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

            try:
                # Wait briefly for the window to appear
                time.sleep(3)
                if proc.poll() is not None:
                    return False, f'PCSX2 exited early (rc={proc.returncode})'

                hwnd = _find_hwnd(proc.pid)

                # Enable turbo mode (Tab key) to fast-forward past logos
                if hwnd:
                    _send_key(hwnd, 0x09, 0x0F)  # Tab = ToggleTurbo

                # During turbo boot, periodically press buttons to dismiss
                time.sleep(_TURBO_BOOT_SECS)

                # Disable turbo (Tab again) for accurate audio
                hwnd = _find_hwnd(proc.pid)
                if hwnd:
                    _send_key(hwnd, 0x09, 0x0F)  # Tab = ToggleTurbo off

                if proc.poll() is not None:
                    return False, f'PCSX2 exited during boot (rc={proc.returncode})'

                # Send Start presses to advance past "Press Start" screens
                for _ in range(3):
                    hwnd = _find_hwnd(proc.pid)
                    if hwnd and proc.poll() is None:
                        _send_key(hwnd, 0x0D, 0x1C)  # Return = Start
                    time.sleep(1.0)

                # Let audio settle
                time.sleep(_SETTLE_SECS)

                # Record loopback audio
                raw_wav = wav_path.replace('.wav', '_ps2_raw.wav')
                self._record_loopback(p, pyaudio, loopback, rate, channels,
                                      _RECORD_SECS, raw_wav)
            finally:
                proc.kill()
                try:
                    proc.communicate(timeout=5)
                except Exception:
                    pass

        finally:
            p.terminate()

        if not os.path.exists(raw_wav) or os.path.getsize(raw_wav) <= 44:
            return False, 'loopback recording empty'

        # Strip silence and check for audio
        try:
            silence_filter = (
                'silenceremove=start_periods=1'
                ':start_duration=0.5'
                ':start_silence=0.3'
                ':start_threshold=-50dB'
            )
            r = subprocess.run(
                [ffmpeg, '-y', '-i', raw_wav,
                 '-af', silence_filter,
                 '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                 wav_path],
                capture_output=True, timeout=60,
            )
            if r.returncode != 0 or not os.path.exists(wav_path) \
                    or os.path.getsize(wav_path) <= 44:
                import shutil
                shutil.copy2(raw_wav, wav_path)

            min_bytes = 44100 * 2 * 2  # 1 second
            if os.path.getsize(wav_path) < min_bytes:
                return False, 'too little audio after silence removal (<1 s)'

            return True, ''

        finally:
            if os.path.exists(raw_wav):
                try:
                    os.remove(raw_wav)
                except OSError:
                    pass

    @staticmethod
    def _find_loopback(p, pyaudio):
        """Find the WASAPI loopback device for the default speakers."""
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except Exception:
            return None

        default_speakers = p.get_device_info_by_index(
            wasapi_info['defaultOutputDevice'])
        speaker_name = default_speakers['name']

        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if (dev['name'].startswith(speaker_name)
                    and dev.get('isLoopbackDevice', False)):
                return dev
        return None

    @staticmethod
    def _record_loopback(p, pyaudio, device, rate, channels, duration, out_path):
        """Record from a WASAPI loopback device to a WAV file."""
        stream = p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device['index'],
            frames_per_buffer=1024,
        )

        frames = []
        total_chunks = int(rate / 1024 * duration)
        for _ in range(total_chunks):
            data = stream.read(1024, exception_on_overflow=False)
            frames.append(data)

        stream.stop_stream()
        stream.close()

        with wave.open(out_path, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(b''.join(frames))
