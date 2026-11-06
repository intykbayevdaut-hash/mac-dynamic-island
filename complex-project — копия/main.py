"""
Entry point for Windows Dynamic Island Pro (Complete: Acts 1, 2, 3, and 4).
"""

from __future__ import annotations
import atexit
import ctypes
from datetime import datetime
import faulthandler
from pathlib import Path
import sys
import threading
import traceback
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

_LOG_DIR = Path(__file__).resolve().parent / "assets"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_RUNTIME_LOG = open(_LOG_DIR / "runtime.log", "a", encoding="utf-8", buffering=1)
try:
    faulthandler.enable(file=_RUNTIME_LOG, all_threads=True)
except Exception:
    pass


def _log_event(msg: str) -> None:
    try:
        _RUNTIME_LOG.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except Exception:
        pass


_log_event("startup")
atexit.register(lambda: _log_event("clean_atexit"))


def _trim_working_set() -> None:
    """Releases unused startup pages back to Windows once after launch so RAM stays ~15-25 MB."""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetProcessWorkingSetSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
        k32.SetProcessWorkingSetSize.restype = ctypes.c_bool
        handle = k32.GetCurrentProcess()
        k32.SetProcessWorkingSetSize(handle, ctypes.c_size_t(-1), ctypes.c_size_t(-1))
    except Exception:
        pass


def _safe_excepthook(exc_type, exc_value, exc_tb) -> None:
    """Prevent PyQt6 from calling qFatal/abort on non-fatal slot exceptions."""
    try:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _log_event(f"excepthook:\n{text}")
        sys.stderr.write(text)
    except Exception:
        pass


def _safe_thread_excepthook(args) -> None:
    _safe_excepthook(args.exc_type, args.exc_value, args.exc_traceback)


sys.excepthook = _safe_excepthook
threading.excepthook = _safe_thread_excepthook

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core.state import IslandState
from services.audio_service import AudioService
from services.clipboard_service import ClipboardService
from services.hardware_service import HardwareService
from services.media_service import MediaService
from services.pc_features_service import PCFeaturesService
from services.power_service import PowerService
from services.timer_service import TimerService
from services.ux_service import UXService
from services.vibe_service import VibeService
from ui.control_hub import ControlHubDialog
from ui.island_window import DynamicIslandWindow


def _create_tray_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(QColor(15, 17, 24))
    p.setPen(QColor(168, 85, 247))
    p.drawRoundedRect(6, 18, 52, 28, 14, 14)
    p.setBrush(QColor(168, 85, 247))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(14, 24, 16, 16)
    p.setBrush(QColor(251, 191, 36))
    p.drawEllipse(38, 27, 10, 10)
    p.end()
    return QIcon(pixmap)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Windows Dynamic Island Pro")

    # Initialize state & all services (Acts 1, 2, 3, 4, 5)
    state = IslandState()
    media_service = MediaService()
    timer_service = TimerService()
    audio_service = AudioService()
    power_service = PowerService()
    clipboard_service = ClipboardService(state.clipboard)
    clipboard_service.attach()
    hardware_service = HardwareService()
    pc_service = PCFeaturesService()
    ux_service = UXService()
    vibe_service = VibeService()

    # Seed initial File Shelf items and initialize Vibe Studio (prompts + dev port radar)
    pc_service.seed_shelf_files(state.drop_zone, Path(__file__).resolve().parent)
    vibe_service.init_state(state.vibe)

    # Load first real synth track and open the Media/Spotify Player card on startup
    media_service.load_track(state.media, 0, auto_play=False)
    state.expanded_target = "media"

    # Create Dynamic Island overlay window
    island = DynamicIslandWindow(
        state=state,
        media_service=media_service,
        timer_service=timer_service,
        audio_service=audio_service,
        power_service=power_service,
        clipboard_service=clipboard_service,
        hardware_service=hardware_service,
        pc_service=pc_service,
        ux_service=ux_service,
        vibe_service=vibe_service,
    )
    island.show()

    # Create Companion Control Hub (accessible via 🎛 button inside Island, Right-Click, or Tray)
    hub = ControlHubDialog(
        island=island,
        state=state,
        media_service=media_service,
        timer_service=timer_service,
        audio_service=audio_service,
        power_service=power_service,
        clipboard_service=clipboard_service,
        hardware_service=hardware_service,
        pc_service=pc_service,
        vibe_service=vibe_service,
    )
    island.request_control_hub.connect(lambda: (hub.show(), hub.raise_(), hub.activateWindow()))
    app.aboutToQuit.connect(vibe_service.stop_demo_server)
    app.aboutToQuit.connect(media_service.shutdown)
    hub.show()
    screen = app.primaryScreen()
    if screen is not None:
        sg = screen.availableGeometry()
        hub.move(sg.x() + (sg.width() - hub.width()) // 2, sg.y() + 295)

    # System Tray Icon
    tray = QSystemTrayIcon(_create_tray_icon(), app)
    tray.setToolTip("Windows Dynamic Island Pro (ЛКМ по острову — меню вкладок, ПКМ — настройки)")
    menu = QMenu()

    act_hub = QAction("🎛 Открыть Центр настроек", menu)
    act_hub.triggered.connect(lambda: (hub.show(), hub.raise_(), hub.activateWindow()))
    menu.addAction(act_hub)

    act_vibe = QAction("⚡ Вайб-Студия (Порты, AI-Промпты, Пипетка, Скрин)", menu)
    act_vibe.triggered.connect(lambda: setattr(state, "expanded_target", "vibe"))
    menu.addAction(act_vibe)

    act_eyedrop = QAction("💧 Пипетка цвета с экрана (3.5 сек)", menu)
    act_eyedrop.triggered.connect(lambda: vibe_service.start_eyedropper(state.vibe, 3.5))
    menu.addAction(act_eyedrop)

    act_shot = QAction("📸 Скриншот экрана в буфер и Полку", menu)
    act_shot.triggered.connect(
        lambda: vibe_service.capture_screen_to_shelf_and_clipboard(
            state.vibe, state.drop_zone, state.clipboard, pc_service
        )
    )
    menu.addAction(act_shot)

    act_glance = QAction("🏠 Открыть Обзор (Часы и Погода)", menu)
    act_glance.triggered.connect(lambda: setattr(state, "expanded_target", "glance"))
    menu.addAction(act_glance)

    act_shelf = QAction("📎 Полка файлов и История буфера", menu)
    act_shelf.triggered.connect(lambda: setattr(state, "expanded_target", "shelf"))
    menu.addAction(act_shelf)

    act_pomo = QAction("🍅 Запустить Помодоро Фокус (25 мин)", menu)
    act_pomo.triggered.connect(hub._on_start_pomodoro_focus)
    menu.addAction(act_pomo)

    act_spotify = QAction("🟢 Spotify: Открыть / Подключить к острову", menu)
    act_spotify.triggered.connect(
        lambda: (media_service.open_or_focus_spotify(state.media), setattr(state, "expanded_target", "media"))
    )
    menu.addAction(act_spotify)

    act_play = QAction("⏯ Музыка / Spotify: Play / Pause", menu)
    act_play.triggered.connect(lambda: media_service.toggle_play_pause(state.media))
    menu.addAction(act_play)

    act_next = QAction("⏭ Музыка / Spotify: Следующий трек", menu)
    act_next.triggered.connect(lambda: media_service.next_track(state.media))
    menu.addAction(act_next)

    act_term = QAction("❯ Быстрый терминал (Ctrl+Shift+Space)", menu)
    act_term.triggered.connect(island.toggle_quick_terminal)
    menu.addAction(act_term)

    act_ghost = QAction("👻 Переключить пропуск мыши (Ctrl+Alt+X)", menu)
    act_ghost.triggered.connect(
        lambda: setattr(state.ux, "click_through_mode", not state.ux.click_through_mode)
    )
    menu.addAction(act_ghost)

    menu.addSeparator()
    act_quit = QAction("✕ Выход", menu)
    act_quit.triggered.connect(app.quit)
    menu.addAction(act_quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: (hub.show(), hub.raise_())
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    # Trim startup RAM working set once after initialization completes
    QTimer.singleShot(900, _trim_working_set)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
