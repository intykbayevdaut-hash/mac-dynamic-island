"""
Entry point for Windows Dynamic Island Pro (Complete: Acts 1, 2, 3, and 4).
"""

from __future__ import annotations
from pathlib import Path
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

from PyQt6.QtCore import Qt
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

    # Initialize state & all services (Acts 1, 2, 3, 4)
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

    # Seed initial File Shelf items so user can test Ctrl+V copy & Drag-Out right away
    pc_service.seed_shelf_files(state.drop_zone, Path(__file__).resolve().parent)

    # Load first real synth track and open the Music Player card on startup
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
    )
    island.request_control_hub.connect(lambda: (hub.show(), hub.raise_(), hub.activateWindow()))
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

    act_glance = QAction("🏠 Открыть Обзор (Часы и Погода)", menu)
    act_glance.triggered.connect(lambda: setattr(state, "expanded_target", "glance"))
    menu.addAction(act_glance)

    act_shelf = QAction("📎 Полка файлов и История буфера", menu)
    act_shelf.triggered.connect(lambda: setattr(state, "expanded_target", "shelf"))
    menu.addAction(act_shelf)

    act_pomo = QAction("🍅 Запустить Помодоро Фокус (25 мин)", menu)
    act_pomo.triggered.connect(hub._on_start_pomodoro_focus)
    menu.addAction(act_pomo)

    act_play = QAction("⏯ Музыка: Play / Pause", menu)
    act_play.triggered.connect(lambda: media_service.toggle_play_pause(state.media))
    menu.addAction(act_play)

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

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
