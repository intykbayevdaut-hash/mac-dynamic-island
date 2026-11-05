"""
Real Media (Now Playing) Service for Windows Dynamic Island Pro.
Features:
1. Rock-solid native Win32 audio playback (winsound / winmm.dll) for built-in synth WAV tracks
   (zero FFmpeg demuxer thread crashes, zero startup warnings, instant 0ms track switching)
   + lazy QMediaPlayer support when the user loads custom .mp3 / .flac / .ogg / .m4a files.
2. Live Windows Audio Session & Browser/Spotify Title Detector (detects when Chrome, Edge,
   Spotify, Yandex Music, VLC, or Telegram is actively playing audio and displays its real window title).
3. Real Windows Media Key control (VK_MEDIA_PLAY_PAUSE, VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK).
"""

from __future__ import annotations
import ctypes
import math
from pathlib import Path
import time
import warnings
import wave
import winsound
from dataclasses import dataclass

warnings.filterwarnings("ignore", category=FutureWarning)

import numpy as np
from PyQt6.QtCore import QUrl

from core.state import MediaInfo

try:
    from pycaw.pycaw import AudioUtilities
    HAS_PYCAW_SESSIONS = True
except Exception:
    HAS_PYCAW_SESSIONS = False


VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002


@dataclass
class TrackEntry:
    title: str
    artist: str
    file_path: str
    duration: float
    accent_color: tuple[int, int, int]
    secondary_color: tuple[int, int, int]


class MediaService:
    """Manages real audio playback + live Windows external media detection & control."""

    def __init__(self, assets_dir: Path | None = None) -> None:
        if assets_dir is None:
            assets_dir = Path(__file__).resolve().parent.parent / "assets"
        self.assets_dir = assets_dir
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        self._last_tick: float = time.monotonic()
        self._eq_phases: list[float] = [0.0, 0.9, 1.8, 2.7, 0.5, 1.4, 2.3, 3.1]
        self.eq_bars: list[float] = [0.16, 0.16, 0.16, 0.16, 0.16, 0.16, 0.16, 0.16]

        # Lazy QMediaPlayer only for non-WAV files (.mp3, .flac, .ogg, .m4a)
        self._qt_player = None
        self._qt_audio = None
        self._using_wav_backend: bool = True
        self._wav_playing: bool = False

        self.playlist: list[TrackEntry] = []
        self._track_idx: int = 0
        self._last_session_poll: float = 0.0

        self._ensure_synth_tracks()

    def _ensure_qt_player(self) -> None:
        if self._qt_player is None:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
            self._qt_audio = QAudioOutput()
            self._qt_audio.setVolume(0.8)
            self._qt_player = QMediaPlayer()
            self._qt_player.setAudioOutput(self._qt_audio)

    def _ensure_synth_tracks(self) -> None:
        """Generates 3 real pleasant ambient/synthwave WAV tracks if not present."""
        specs = [
            (
                "synth_midnight.wav",
                "Midnight Horizon (Synth)",
                "Dynamic Island Studio • Stereo Synth",
                (168, 85, 247),
                (56, 189, 248),
                [220.0, 277.18, 329.63, 440.0],
            ),
            (
                "synth_cyber.wav",
                "Neon Pulse (Cyberpunk)",
                "Dynamic Island Studio • Deep Chords",
                (16, 185, 129),
                (6, 182, 212),
                [196.0, 246.94, 293.66, 392.0],
            ),
            (
                "synth_sunset.wav",
                "Solaris Sunset (Lo-Fi)",
                "Dynamic Island Studio • Warm Chill",
                (244, 63, 94),
                (245, 158, 11),
                [261.63, 329.63, 392.0, 493.88],
            ),
        ]

        sr = 22050
        duration = 16.0
        for fname, title, artist, c1, c2, freqs in specs:
            fpath = self.assets_dir / fname
            if not fpath.exists():
                self._synthesize_wav(fpath, sr, duration, freqs)
            self.playlist.append(
                TrackEntry(
                    title=title,
                    artist=artist,
                    file_path=str(fpath),
                    duration=duration,
                    accent_color=c1,
                    secondary_color=c2,
                )
            )

    @staticmethod
    def _synthesize_wav(fpath: Path, sr: int, duration: float, chord_freqs: list[float]) -> None:
        try:
            n_samples = int(sr * duration)
            t = np.linspace(0.0, duration, n_samples, endpoint=False, dtype=np.float32)
            signal = np.zeros_like(t)
            for i, f in enumerate(chord_freqs):
                env = 0.5 + 0.5 * np.sin(2.0 * np.pi * (0.5 + i * 0.15) * t)
                signal += (0.22 * env) * np.sin(2.0 * np.pi * f * t)
            beat_env = np.exp(-6.0 * (t % 0.5))
            signal += 0.35 * beat_env * np.sin(2.0 * np.pi * (chord_freqs[0] * 0.5) * t)
            fade = np.minimum(1.0, np.minimum(t / 0.4, (duration - t) / 0.4))
            pcm = np.clip(signal * fade * 0.65, -1.0, 1.0)
            pcm_int16 = (pcm * 32767).astype(np.int16)

            with wave.open(str(fpath), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(pcm_int16.tobytes())
        except Exception:
            pass

    def stop_playback(self, media: MediaInfo) -> None:
        self._wav_playing = False
        media.playing = False
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        if self._qt_player is not None:
            try:
                self._qt_player.stop()
            except Exception:
                pass

    def load_track(self, media: MediaInfo, index: int, auto_play: bool = False) -> None:
        if not self.playlist:
            return
        self._track_idx = index % len(self.playlist)
        track = self.playlist[self._track_idx]
        media.title = track.title
        media.artist = track.artist
        media.duration = track.duration
        media.position = 0.0
        media.accent_color = track.accent_color
        media.secondary_color = track.secondary_color
        media.is_live_system_session = False

        is_wav = track.file_path.lower().endswith(".wav")
        self._using_wav_backend = is_wav

        if is_wav:
            if self._qt_player is not None:
                try:
                    self._qt_player.stop()
                except Exception:
                    pass
            if auto_play:
                self._wav_playing = True
                media.playing = True
                try:
                    winsound.PlaySound(
                        track.file_path,
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                    )
                except Exception:
                    pass
            else:
                self._wav_playing = False
                media.playing = False
                try:
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass
        else:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
            self._wav_playing = False
            self._ensure_qt_player()
            if self._qt_player is not None:
                self._qt_player.stop()
                self._qt_player.setSource(QUrl.fromLocalFile(track.file_path))
                if auto_play:
                    self._qt_player.play()
                    media.playing = True
                else:
                    media.playing = False

    def load_external_file(self, media: MediaInfo, file_path: str) -> None:
        p = Path(file_path)
        if not p.exists():
            return
        entry = TrackEntry(
            title=p.stem,
            artist=f"Локальный файл ({p.suffix.upper()})",
            file_path=str(p.resolve()),
            duration=180.0,
            accent_color=(56, 189, 248),
            secondary_color=(168, 85, 247),
        )
        self.playlist.insert(0, entry)
        self.load_track(media, 0, auto_play=True)

    def toggle_play_pause(self, media: MediaInfo) -> None:
        if media.is_live_system_session:
            self._send_media_key(VK_MEDIA_PLAY_PAUSE)
            media.playing = not media.playing
            return

        if self._using_wav_backend:
            if self._wav_playing:
                self._wav_playing = False
                media.playing = False
                try:
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass
            else:
                self._wav_playing = True
                media.playing = True
                track = self.playlist[self._track_idx]
                try:
                    winsound.PlaySound(
                        track.file_path,
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                    )
                except Exception:
                    pass
        else:
            self._ensure_qt_player()
            from PyQt6.QtMultimedia import QMediaPlayer
            if self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._qt_player.pause()
                media.playing = False
            else:
                self._qt_player.play()
                media.playing = True

    def next_track(self, media: MediaInfo) -> None:
        if media.is_live_system_session:
            self._send_media_key(VK_MEDIA_NEXT_TRACK)
            return
        self.load_track(media, self._track_idx + 1, auto_play=True)

    def prev_track(self, media: MediaInfo) -> None:
        if media.is_live_system_session:
            self._send_media_key(VK_MEDIA_PREV_TRACK)
            return
        if media.position > 4.0:
            media.position = 0.0
            if self._using_wav_backend and self._wav_playing:
                track = self.playlist[self._track_idx]
                try:
                    winsound.PlaySound(
                        track.file_path,
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                    )
                except Exception:
                    pass
            elif self._qt_player is not None:
                self._qt_player.setPosition(0)
        else:
            self.load_track(media, self._track_idx - 1, auto_play=True)

    def seek(self, media: MediaInfo, ratio: float) -> None:
        ratio = max(0.0, min(1.0, float(ratio)))
        if not media.is_live_system_session and not self._using_wav_backend and self._qt_player is not None:
            if self._qt_player.duration() > 0:
                self._qt_player.setPosition(int(ratio * self._qt_player.duration()))
        media.position = ratio * max(1.0, media.duration)

    def update(self, media: MediaInfo, system_audio_peak: float, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        dt = min(0.1, max(0.001, now - self._last_tick))
        self._last_tick = now

        media.audio_peak = system_audio_peak

        if self._using_wav_backend and self._wav_playing:
            media.is_live_system_session = False
            media.playing = True
            media.position += dt
            if media.position >= media.duration:
                self.load_track(media, self._track_idx + 1, auto_play=True)
        elif not self._using_wav_backend and self._qt_player is not None:
            from PyQt6.QtMultimedia import QMediaPlayer
            if self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                media.is_live_system_session = False
                media.playing = True
                dur_ms = self._qt_player.duration()
                pos_ms = self._qt_player.position()
                if dur_ms > 0:
                    media.duration = dur_ms / 1000.0
                    media.position = pos_ms / 1000.0
                    if pos_ms >= dur_ms - 150:
                        self.load_track(media, self._track_idx + 1, auto_play=True)
        else:
            if now - self._last_session_poll > 1.5:
                self._last_session_poll = now
                ext_playing, ext_title, ext_app = self._detect_external_windows_media()
                if ext_playing:
                    media.is_live_system_session = True
                    media.playing = True
                    media.title = ext_title
                    media.artist = f"Системный звук • {ext_app}"
                    media.accent_color = (56, 189, 248)
                    media.secondary_color = (168, 85, 247)
                elif media.is_live_system_session and system_audio_peak < 0.01:
                    media.playing = False
                    media.is_live_system_session = False

        # Animate equalizer bars driven by REAL Windows audio peak!
        if media.playing:
            base_energy = max(0.24, min(1.0, system_audio_peak * 1.75))
            speeds = [9.5, 13.2, 11.0, 15.4, 10.3, 14.1, 11.8, 12.6]
            for i in range(len(self.eq_bars)):
                self._eq_phases[i] += dt * speeds[i % len(speeds)]
                wave_factor = 0.5 + 0.5 * math.sin(self._eq_phases[i])
                target = max(0.14, min(1.0, base_energy * (0.45 + 0.75 * wave_factor)))
                self.eq_bars[i] += (target - self.eq_bars[i]) * min(1.0, dt * 18.0)
        else:
            for i in range(len(self.eq_bars)):
                self.eq_bars[i] += (0.14 - self.eq_bars[i]) * min(1.0, dt * 12.0)

    def _detect_external_windows_media(self) -> tuple[bool, str, str]:
        if not HAS_PYCAW_SESSIONS:
            return False, "", ""
        my_pid = ctypes.windll.kernel32.GetCurrentProcessId()
        try:
            sessions = AudioUtilities.GetAllSessions()
            for s in sessions:
                proc = s.Process
                if proc is None or proc.pid == my_pid:
                    continue
                if int(s.State) == 1:
                    pname = proc.name()
                    if pname.lower() in ("audiodg.exe", "svchost.exe", "explorer.exe", "hpaudiocenter.exe"):
                        continue
                    win_title = self._get_process_window_title(proc.pid)
                    clean_app = pname.replace(".exe", "").capitalize()
                    if win_title:
                        for suffix in (" - Google Chrome", " - Microsoft​ Edge", " - Mozilla Firefox", " - Opera"):
                            if win_title.endswith(suffix):
                                win_title = win_title[: -len(suffix)]
                        return True, win_title, clean_app
                    return True, f"Воспроизведение в {clean_app}", clean_app
        except Exception:
            pass
        return False, "", ""

    @staticmethod
    def _get_process_window_title(target_pid: int) -> str:
        user32 = ctypes.windll.user32
        found_title: list[str] = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def enum_cb(hwnd, lparam) -> bool:
            if user32.IsWindowVisible(hwnd):
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == target_pid:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 1:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        val = buf.value.strip()
                        if val and val not in ("Default IME", "MSCTFIME UI"):
                            found_title.append(val)
                            return False
            return True

        try:
            cb_func = WNDENUMPROC(enum_cb)
            user32.EnumWindows(cb_func, 0)
        except Exception:
            pass
        return found_title[0] if found_title else ""

    @staticmethod
    def _send_media_key(vk_code: int) -> None:
        try:
            ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
            ctypes.windll.user32.keybd_event(
                vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0
            )
        except Exception:
            pass
