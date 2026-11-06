"""
Now Playing Service: Spotify (and other Windows media apps) integration for the Dynamic Island.

Primary backend: Windows Global System Media Transport Controls (GSMTC, WinRT `winrt-Windows.Media.Control`).
  - Reads the real track title, artist, album cover, play/pause state, position and duration from Spotify.
  - Sends Play/Pause, Next, Previous and Seek commands directly to the Spotify session.
  - Falls back to the current system session (YouTube in a browser, Yandex Music, etc.) when Spotify is absent.

Fallback backend (when WinRT is unavailable or Spotify's media overlay is turned off):
  - Reads the Spotify window title ("Artist - Song") via Win32 and sends WM_APPCOMMAND to the Spotify window.

All WinRT/Win32 work runs in one daemon thread, so the GUI thread never blocks.
The GUI thread reads an immutable `NowPlayingSnapshot` and enqueues commands.
"""

from __future__ import annotations
import asyncio
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import queue
import threading
import time
import webbrowser


WM_APPCOMMAND = 0x0319
APPCOMMAND_MEDIA_NEXTTRACK = 11
APPCOMMAND_MEDIA_PREVIOUSTRACK = 12
APPCOMMAND_MEDIA_PLAY_PAUSE = 14

# Dedicated thread-safe user32 binding with explicit 64-bit pointer/HWND signatures (zero WNDENUMPROC thunks)
_U32 = ctypes.WinDLL("user32", use_last_error=True)
_U32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
_U32.FindWindowExW.restype = wintypes.HWND
_U32.IsWindowVisible.argtypes = [wintypes.HWND]
_U32.IsWindowVisible.restype = wintypes.BOOL
_U32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_U32.GetWindowTextLengthW.restype = ctypes.c_int
_U32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_U32.GetWindowTextW.restype = ctypes.c_int
_U32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_U32.GetWindowThreadProcessId.restype = wintypes.DWORD
_U32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_U32.ShowWindow.restype = wintypes.BOOL
_U32.SetForegroundWindow.argtypes = [wintypes.HWND]
_U32.SetForegroundWindow.restype = wintypes.BOOL
_U32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_U32.SendMessageW.restype = ctypes.c_ssize_t
_U32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
_U32.keybd_event.restype = None

_PAUSED_SPOTIFY_TITLES = ("spotify", "spotify premium", "spotify free", "spotify family", "spotify duo")

_APP_NAMES = (
    ("spotify", "Spotify"),
    ("chrome", "Chrome"),
    ("msedge", "Edge"),
    ("firefox", "Firefox"),
    ("opera", "Opera"),
    ("brave", "Brave"),
    ("yandex", "Яндекс"),
    ("telegram", "Telegram"),
    ("vlc", "VLC"),
    ("zune", "Media Player"),
    ("music", "Музыка"),
)


def _friendly_app_name(aumid: str) -> str:
    low = (aumid or "").lower()
    for key, name in _APP_NAMES:
        if key in low:
            return name
    base = os.path.basename(aumid or "").split("!")[0].replace(".exe", "")
    return base[:18] or "Система"


@dataclass(frozen=True)
class NowPlayingSnapshot:
    is_spotify: bool
    app_name: str
    title: str
    artist: str
    album: str
    playing: bool
    position: float          # seconds, as of `captured_mono`
    duration: float          # seconds (0.0 if unknown)
    captured_mono: float
    art_key: str             # changes when the track changes
    art_bytes: bytes | None  # encoded cover image (PNG/JPEG) or None
    can_seek: bool

    def position_now(self, now: float) -> float:
        pos = self.position
        if self.playing:
            pos += max(0.0, now - self.captured_mono)
        if self.duration > 0.0:
            pos = min(pos, self.duration)
        return max(0.0, pos)


class NowPlayingService:
    """Background poller + command dispatcher for Spotify / Windows media sessions."""

    POLL_ACTIVE_S = 1.0
    POLL_IDLE_S = 2.5

    def __init__(self) -> None:
        self._snapshot: NowPlayingSnapshot | None = None
        self._commands: queue.Queue[tuple[str, float]] = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.backend: str = "starting"  # "winrt", "win32", or "starting"
        self.spotify_running: bool = False

        # Worker-thread-only state
        self._manager = None
        self._last_art_key: str = ""
        self._last_art_bytes: bytes | None = None
        self._pid_name_cache: dict[int, str] = {}
        self._last_win32_track: tuple[str, str] = ("", "")

    # ------------------------------------------------------------------
    # Public API (GUI thread)
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="NowPlaying", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def snapshot(self) -> NowPlayingSnapshot | None:
        return self._snapshot

    def play_pause(self) -> None:
        self._enqueue("play_pause")

    def play(self) -> None:
        self._enqueue("play")

    def pause(self) -> None:
        self._enqueue("pause")

    def next_track(self) -> None:
        self._enqueue("next")

    def prev_track(self) -> None:
        self._enqueue("prev")

    def seek(self, seconds: float) -> None:
        self._enqueue("seek", seconds)

    def open_spotify(self) -> None:
        """Focus or launch the Spotify desktop app; cleanly fall back to Spotify Web Player if not installed."""
        hwnd, _ = self._find_spotify_hwnd()
        if hwnd:
            try:
                _U32.ShowWindow(hwnd, 9)  # SW_RESTORE
                _U32.SetForegroundWindow(hwnd)
                return
            except Exception:
                pass

        appdata = os.environ.get("APPDATA", "")
        exe_path = os.path.join(appdata, "Spotify", "Spotify.exe") if appdata else ""
        if exe_path and os.path.isfile(exe_path):
            try:
                os.startfile(exe_path)  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        has_uri = False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\spotify"):
                has_uri = True
        except OSError:
            has_uri = False

        if has_uri:
            try:
                os.startfile("spotify:")  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        try:
            webbrowser.open("https://open.spotify.com")
        except Exception:
            pass

    def _enqueue(self, cmd: str, arg: float = 0.0) -> None:
        self._commands.put((cmd, float(arg)))
        self._wake.set()

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------
    def _run(self) -> None:
        winrt_ok = False
        try:
            try:
                import winrt.runtime as rt
                rt.init_apartment(rt.ApartmentType.MULTI_THREADED)
            except Exception:
                pass
            from winrt.windows.media.control import (  # noqa: F401
                GlobalSystemMediaTransportControlsSessionManager,
            )
            winrt_ok = True
        except Exception:
            winrt_ok = False

        self.backend = "winrt" if winrt_ok else "win32"
        loop = asyncio.new_event_loop()
        try:
            while not self._stop.is_set():
                try:
                    if winrt_ok:
                        loop.run_until_complete(self._tick_winrt())
                    else:
                        self._tick_win32()
                except Exception:
                    # A session can vanish mid-call (app closed). Reset and retry next tick.
                    self._manager = None
                interval = self.POLL_ACTIVE_S if self._snapshot is not None else self.POLL_IDLE_S
                self._wake.wait(interval)
                self._wake.clear()
        finally:
            try:
                loop.close()
            except Exception:
                pass

    # ---------------------------- WinRT --------------------------------
    async def _tick_winrt(self) -> None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )

        if self._manager is None:
            self._manager = await Manager.request_async()
        manager = self._manager

        session = None
        spotify_session = None
        for s in manager.get_sessions():
            aumid = (s.source_app_user_model_id or "").lower()
            if "spotify" in aumid:
                spotify_session = s
                break
        if spotify_session is not None:
            session = spotify_session
        else:
            cur = manager.get_current_session()
            if cur is not None and "python" not in (cur.source_app_user_model_id or "").lower():
                session = cur

        self.spotify_running = spotify_session is not None or self._find_spotify_hwnd()[0] != 0

        # 1. Execute queued commands against the chosen session
        had_cmd = await self._drain_commands_winrt(session)

        if session is None:
            # Spotify may run with its media overlay disabled: try the window-title fallback.
            self._tick_win32()
            return

        aumid = session.source_app_user_model_id or ""
        props = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        timeline = session.get_timeline_properties()

        title = (props.title or "").strip() if props else ""
        artist = (props.artist or "").strip() if props else ""
        album = (props.album_title or "").strip() if props else ""
        status = info.playback_status if info else Status.CLOSED
        playing = status == Status.PLAYING

        if not title:
            # Spotify shows an empty session for ads / between tracks.
            title = "Spotify" if spotify_session is not None else _friendly_app_name(aumid)

        position, duration = 0.0, 0.0
        if timeline is not None:
            try:
                position = timeline.position.total_seconds()
                duration = max(0.0, (timeline.end_time - timeline.start_time).total_seconds())
                last = timeline.last_updated_time
                if playing and last is not None and last.year > 1700:
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    drift = (datetime.now(timezone.utc) - last).total_seconds()
                    if 0.0 < drift < 3600.0:
                        position += drift
                if duration > 0.0:
                    position = min(position, duration)
            except Exception:
                position, duration = 0.0, 0.0

        can_seek = False
        try:
            can_seek = bool(info.controls.is_playback_position_enabled) and duration > 0.0
        except Exception:
            can_seek = duration > 0.0

        art_key = f"{aumid}|{title}|{artist}|{album}"
        if art_key != self._last_art_key:
            self._last_art_key = art_key
            self._last_art_bytes = None
            if props is not None and props.thumbnail is not None:
                self._last_art_bytes = await self._read_thumbnail(props.thumbnail)
        elif self._last_art_bytes is None and props is not None and props.thumbnail is not None:
            # Spotify often publishes the cover a moment after the title.
            self._last_art_bytes = await self._read_thumbnail(props.thumbnail)

        is_web_spotify = False
        if spotify_session is None and title:
            is_web_spotify = self._check_browser_spotify_title(title)

        is_sp = spotify_session is not None or is_web_spotify
        app_lbl = "Spotify" if is_sp else _friendly_app_name(aumid)

        self._snapshot = NowPlayingSnapshot(
            is_spotify=is_sp,
            app_name=app_lbl,
            title=title,
            artist=artist or album or app_lbl,
            album=album,
            playing=playing,
            position=position,
            duration=duration,
            captured_mono=time.monotonic(),
            art_key=art_key,
            art_bytes=self._last_art_bytes,
            can_seek=can_seek,
        )

        if had_cmd:
            # Re-poll quickly so the Island reflects the new track/state right away.
            self._wake.set()
            await asyncio.sleep(0.25)

    async def _drain_commands_winrt(self, session) -> bool:
        had = False
        while True:
            try:
                cmd, arg = self._commands.get_nowait()
            except queue.Empty:
                break
            had = True
            if session is None:
                self._send_win32_command(cmd)
                continue
            try:
                if cmd == "play_pause":
                    ok = await session.try_toggle_play_pause_async()
                elif cmd == "play":
                    ok = await session.try_play_async()
                elif cmd == "pause":
                    ok = await session.try_pause_async()
                elif cmd == "next":
                    ok = await session.try_skip_next_async()
                elif cmd == "prev":
                    ok = await session.try_skip_previous_async()
                elif cmd == "seek":
                    ok = await session.try_change_playback_position_async(int(max(0.0, arg) * 10_000_000))
                else:
                    ok = True
                if not ok and cmd != "seek":
                    self._send_win32_command(cmd)
            except Exception:
                self._send_win32_command(cmd)
        return had

    @staticmethod
    async def _read_thumbnail(thumb_ref) -> bytes | None:
        try:
            from winrt.windows.storage.streams import Buffer, InputStreamOptions

            stream = await thumb_ref.open_read_async()
            try:
                size = int(stream.size)
                if size <= 0 or size > 6_000_000:
                    return None
                buf = Buffer(size)
                result = await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
                data = bytes(memoryview(result))[: int(result.length)]
                return data or None
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
        except Exception:
            return None

    # ---------------------------- Win32 fallback -----------------------
    def _tick_win32(self) -> None:
        hwnd, title = self._find_spotify_hwnd()
        self.spotify_running = hwnd != 0

        while True:
            try:
                cmd, _arg = self._commands.get_nowait()
            except queue.Empty:
                break
            self._send_win32_command(cmd, hwnd)

        if not hwnd:
            if self.backend == "win32" or (self._snapshot is not None and self._snapshot.is_spotify):
                self._snapshot = None
            elif self.backend == "winrt":
                self._snapshot = None
            return

        low = title.strip().lower()
        playing = bool(title) and low not in _PAUSED_SPOTIFY_TITLES and " - " in title
        if playing:
            artist, _, song = title.partition(" - ")
            self._last_win32_track = (song.strip(), artist.strip())
        song, artist = self._last_win32_track
        if not song:
            song, artist = "Spotify", "Нажмите ▶ чтобы продолжить"

        key = f"win32|{song}|{artist}"
        prev = self._snapshot
        position = 0.0
        if prev is not None and prev.art_key == key:
            position = prev.position_now(time.monotonic())

        self._snapshot = NowPlayingSnapshot(
            is_spotify=True,
            app_name="Spotify",
            title=song,
            artist=artist,
            album="",
            playing=playing,
            position=position,
            duration=0.0,
            captured_mono=time.monotonic(),
            art_key=key,
            art_bytes=None,
            can_seek=False,
        )

    def _find_spotify_hwnd(self) -> tuple[int, str]:
        """Returns (hwnd, window_title) of the Spotify main window, or (0, '') without any C callback thunks."""
        for cls_name in ("Chrome_WidgetWin_0", "Chrome_WidgetWin_1"):
            hwnd = 0
            for _ in range(64):
                try:
                    hwnd = _U32.FindWindowExW(0, hwnd, cls_name, None)
                except Exception:
                    break
                if not hwnd:
                    break
                try:
                    length = _U32.GetWindowTextLengthW(hwnd)
                    if length <= 0 or length > 512:
                        continue
                    pid = wintypes.DWORD()
                    _U32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value and self._process_name(int(pid.value)) == "spotify.exe":
                        buf = ctypes.create_unicode_buffer(length + 1)
                        _U32.GetWindowTextW(hwnd, buf, length + 1)
                        return int(hwnd), buf.value
                except Exception:
                    continue
        return 0, ""

    def _check_browser_spotify_title(self, track_title: str) -> bool:
        """Detects when Spotify Web Player (open.spotify.com) is playing in a browser tab."""
        needle = f"{track_title.lower()} •"
        for cls_name in ("Chrome_WidgetWin_1", "MozillaWindowClass"):
            hwnd = 0
            for _ in range(64):
                try:
                    hwnd = _U32.FindWindowExW(0, hwnd, cls_name, None)
                except Exception:
                    break
                if not hwnd:
                    break
                try:
                    if not _U32.IsWindowVisible(hwnd):
                        continue
                    length = _U32.GetWindowTextLengthW(hwnd)
                    if 3 < length < 260:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        _U32.GetWindowTextW(hwnd, buf, length + 1)
                        val = buf.value.lower()
                        if "spotify" in val or (track_title and needle in val):
                            return True
                except Exception:
                    continue
        return False

    def _process_name(self, pid: int) -> str:
        if pid in self._pid_name_cache:
            return self._pid_name_cache[pid]
        name = ""
        try:
            import psutil
            name = psutil.Process(pid).name().lower()
        except Exception:
            name = ""
        if len(self._pid_name_cache) > 256:
            self._pid_name_cache.clear()
        self._pid_name_cache[pid] = name
        return name

    def _send_win32_command(self, cmd: str, hwnd: int = 0) -> None:
        appcmd = {
            "play_pause": APPCOMMAND_MEDIA_PLAY_PAUSE,
            "play": APPCOMMAND_MEDIA_PLAY_PAUSE,
            "pause": APPCOMMAND_MEDIA_PLAY_PAUSE,
            "next": APPCOMMAND_MEDIA_NEXTTRACK,
            "prev": APPCOMMAND_MEDIA_PREVIOUSTRACK,
        }.get(cmd)
        if appcmd is None:
            return
        if not hwnd:
            hwnd = self._find_spotify_hwnd()[0]
        if hwnd:
            try:
                _U32.SendMessageW(hwnd, WM_APPCOMMAND, 0, appcmd << 16)
                return
            except Exception:
                pass
        # Last resort: global media keys (controls whatever app owns media focus)
        vk = {APPCOMMAND_MEDIA_PLAY_PAUSE: 0xB3, APPCOMMAND_MEDIA_NEXTTRACK: 0xB0, APPCOMMAND_MEDIA_PREVIOUSTRACK: 0xB1}[appcmd]
        try:
            _U32.keybd_event(vk, 0, 0x0001, 0)
            _U32.keybd_event(vk, 0, 0x0001 | 0x0002, 0)
        except Exception:
            pass
