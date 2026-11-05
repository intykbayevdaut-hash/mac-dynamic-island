"""
Windows Dynamic Island Pro — Ultra-Luxury Liquid Glass & Aurora Edition (Acts 1–4).
Features:
- 60 FPS Spring Physics with Liquid Metaball Split Island
- 6 Customizable Luxury Themes (Aurora, Cyberpunk, Gold, Emerald, Rose Quartz, Pure OLED)
- Spinning Vinyl & Audio-Reactive Equalizer + Interactive Seek & Volume Scrubbing
- Persistent Frosted-Glass 6-Tab Navigation Bar + 1-Click Theme Switcher
- Zero setMask() DWM conflicts (uses native per-pixel alpha via WA_TranslucentBackground)
"""

from __future__ import annotations
from datetime import datetime
import math
import os
import time

from PyQt6.QtCore import Qt, QMimeData, QPointF, QRectF, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QConicalGradient,
    QDrag,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PyQt6.QtWidgets import QFileDialog, QLineEdit, QWidget

from core.spring import IslandPhysics
from core.state import IslandMode, IslandState
from services.audio_service import AudioService
from services.clipboard_service import ClipboardService
from services.hardware_service import HardwareService
from services.media_service import MediaService
from services.pc_features_service import PCFeaturesService
from services.power_service import PowerService
from services.timer_service import TimerService
from services.ux_service import UXService


RUSSIAN_WEEKDAYS = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]
RUSSIAN_MONTHS = [
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


class DynamicIslandWindow(QWidget):
    """Top/Bottom screen overlay implementing Apple Dynamic Island + PC Superpowers."""

    request_control_hub = pyqtSignal()
    state_updated = pyqtSignal()

    CANVAS_WIDTH = 560
    CANVAS_HEIGHT = 272

    def __init__(
        self,
        state: IslandState,
        media_service: MediaService,
        timer_service: TimerService,
        audio_service: AudioService,
        power_service: PowerService,
        clipboard_service: ClipboardService,
        hardware_service: HardwareService,
        pc_service: PCFeaturesService,
        ux_service: UXService,
    ) -> None:
        super().__init__(None)
        self.state = state
        self.media_service = media_service
        self.timer_service = timer_service
        self.audio_service = audio_service
        self.power_service = power_service
        self.clipboard_service = clipboard_service
        self.hardware_service = hardware_service
        self.pc_service = pc_service
        self.ux_service = ux_service

        self.physics = IslandPhysics()
        self._last_frame_time = time.monotonic()

        self._hitboxes: dict[str, QRectF] = {}
        self._hovered_hitbox: str | None = None
        self._active_slider: str | None = None
        self._main_pill_rect = QRectF()
        self._split_circle_rect = QRectF()
        self._screen_rect: tuple[int, int, int, int] = (0, 0, 1920, 1080)
        self._last_pos_signature: tuple[int, str] | None = None

        self._drag_candidate_path: str | None = None
        self._drag_start_pos: QPointF | None = None

        self._setup_window()
        self._setup_terminal_input()
        self.apply_screen_positioning()

        # 60 FPS main loop
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_frame)
        self._anim_timer.start()

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFixedSize(self.CANVAS_WIDTH, self.CANVAS_HEIGHT)

    def _setup_terminal_input(self) -> None:
        self.terminal_input = QLineEdit(self)
        self.terminal_input.setPlaceholderText("Введите: 256*14, calc, notepad, ipconfig или ?поиск...")
        self.terminal_input.setStyleSheet(
            """
            QLineEdit {
                background-color: rgba(255, 255, 255, 24);
                border: 1px solid rgba(168, 85, 247, 160);
                border-radius: 11px;
                color: #ffffff;
                padding: 4px 12px;
                font-family: 'Consolas';
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1.5px solid #38bdf8;
                background-color: rgba(255, 255, 255, 36);
            }
            """
        )
        self.terminal_input.returnPressed.connect(self._on_terminal_submit)
        self.terminal_input.hide()

    def apply_screen_positioning(self) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            return
        idx = max(0, min(self.state.ux.monitor_index, len(screens) - 1))
        self.state.ux.monitor_index = idx
        screen = screens[idx]
        geom = screen.geometry()
        avail = screen.availableGeometry()
        self._screen_rect = (geom.x(), geom.y(), geom.width(), geom.height())

        x = geom.x() + (geom.width() - self.CANVAS_WIDTH) // 2
        pos_mode = self.state.ux.position_mode

        if pos_mode == "docked_top":
            y = geom.y()
            self.physics.y_offset.set_target(0.0)
        elif pos_mode == "bottom_taskbar":
            y = avail.bottom() - self.CANVAS_HEIGHT + 4
            self.physics.y_offset.set_target(float(self.CANVAS_HEIGHT - 54))
        else:
            y = geom.y() + 4
            self.physics.y_offset.set_target(8.0)

        self.move(x, y)

    # ------------------------------------------------------------------
    # Frame Update & Spring Targets
    # ------------------------------------------------------------------
    def _on_frame(self) -> None:
        now = time.monotonic()
        dt = now - self._last_frame_time
        self._last_frame_time = now

        if not self.isVisible():
            self.show()

        sig = (self.state.ux.monitor_index, self.state.ux.position_mode)
        if sig != self._last_pos_signature:
            self._last_pos_signature = sig
            self.apply_screen_positioning()

        # 1. Poll Act 1 Services
        vol, muted, vol_changed = self.audio_service.get_volume_state()
        self.state.audio.volume_percent = vol
        self.state.audio.muted = muted
        if vol_changed and self.state.expanded_target is None:
            self.state.audio.volume_alert_until = now + 2.0

        peak = self.audio_service.get_audio_peak()
        mic_active, mic_app = self.audio_service.get_mic_privacy_state()
        self.state.audio.mic_active = mic_active
        self.state.audio.mic_app_name = mic_app

        self.power_service.update(self.state.battery, now)
        self.timer_service.update(self.state.timer, now)
        self.media_service.update(self.state.media, peak, now)

        # 2. Poll Act 2 Services
        self.hardware_service.update(self.state.hardware, now)
        self.pc_service.update_downloads(self.state.download, now)

        # 3. Poll Act 3 UX Service
        hwnd = int(self.winId()) if self.winId() else 0
        toggle_term, toggle_ghost = self.ux_service.update(
            self.state.ux, hwnd, self._screen_rect, now
        )
        if toggle_term:
            self.toggle_quick_terminal()
        if toggle_ghost:
            self.state.ux.click_through_mode = not self.state.ux.click_through_mode
            self.state_updated.emit()

        if now < self.state.timer.finished_flashUntil and self.state.expanded_target is None:
            self.state.expanded_target = "timer"

        # 4. Resolve active mode & update spring targets
        mode = self.state.resolve_mode(now)
        self._apply_mode_targets(mode)

        if mode == IslandMode.EXPANDED_TERMINAL:
            if not self.terminal_input.isVisible():
                self.terminal_input.show()
                self.raise_()
                self.activateWindow()
                self.terminal_input.setFocus()
        else:
            if self.terminal_input.isVisible():
                self.terminal_input.hide()

        # 5. Step spring physics & update rect geometry
        self.physics.step(dt)
        self._main_pill_rect, self._split_circle_rect = self._compute_geometries()
        self.update()

    def toggle_quick_terminal(self) -> None:
        if self.state.expanded_target == "terminal":
            self.state.expanded_target = None
        else:
            self.state.expanded_target = "terminal"
            self.physics.width.set_target(484.0, impulse=180.0)

    def _apply_mode_targets(self, mode: IslandMode) -> None:
        if self.state.ux.click_through_mode or self.state.ux.is_modifier_held:
            self.physics.opacity.set_target(0.45)
        else:
            self.physics.opacity.set_target(1.0)

        hover_boost = 8.0 if (self.state.hovered and not mode.value.startswith("expanded")) else 0.0

        if mode == IslandMode.IDLE:
            extra_mic = 18.0 if self.state.audio.mic_active else 0.0
            base_idle_w = 264.0 if self.state.glance.enabled_in_idle else 148.0
            self.physics.width.set_target(base_idle_w + extra_mic + hover_boost)
            self.physics.height.set_target(38.0 + (2.0 if hover_boost else 0.0))
            self.physics.corner_radius.set_target(19.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode == IslandMode.COMPACT_MEDIA:
            extra_mic = 16.0 if self.state.audio.mic_active else 0.0
            self.physics.width.set_target(294.0 + extra_mic + hover_boost)
            self.physics.height.set_target(40.0 + (2.0 if hover_boost else 0.0))
            self.physics.corner_radius.set_target(20.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode == IslandMode.COMPACT_TIMER:
            self.physics.width.set_target(212.0 + hover_boost)
            self.physics.height.set_target(40.0 + (2.0 if hover_boost else 0.0))
            self.physics.corner_radius.set_target(20.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode == IslandMode.COMPACT_HARDWARE:
            self.physics.width.set_target(280.0 + hover_boost)
            self.physics.height.set_target(40.0 + (2.0 if hover_boost else 0.0))
            self.physics.corner_radius.set_target(20.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode == IslandMode.SPLIT_MULTITASK:
            base_w = 264.0 if self.state.hardware.hud_enabled and not self.state.media.playing else 254.0
            self.physics.width.set_target(base_w + hover_boost * 0.5)
            self.physics.height.set_target(40.0)
            self.physics.corner_radius.set_target(20.0)
            self.physics.split_gap.set_target(11.0)
            self.physics.split_size.set_target(40.0)

        elif mode == IslandMode.ALERT_VOLUME:
            self.physics.width.set_target(308.0)
            self.physics.height.set_target(44.0)
            self.physics.corner_radius.set_target(22.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode == IslandMode.ALERT_BATTERY:
            self.physics.width.set_target(314.0)
            self.physics.height.set_target(46.0)
            self.physics.corner_radius.set_target(23.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode == IslandMode.ALERT_CLIPBOARD:
            self.physics.width.set_target(346.0)
            self.physics.height.set_target(52.0)
            self.physics.corner_radius.set_target(26.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode == IslandMode.ALERT_DOWNLOAD:
            self.physics.width.set_target(336.0)
            self.physics.height.set_target(48.0)
            self.physics.corner_radius.set_target(24.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode == IslandMode.ALERT_NOTIFICATION:
            self.physics.width.set_target(396.0)
            self.physics.height.set_target(84.0)
            self.physics.corner_radius.set_target(28.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode == IslandMode.DROP_ZONE_HOVER:
            self.physics.width.set_target(376.0)
            self.physics.height.set_target(94.0)
            self.physics.corner_radius.set_target(28.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

        elif mode in (
            IslandMode.EXPANDED_MEDIA,
            IslandMode.EXPANDED_TIMER,
            IslandMode.EXPANDED_HARDWARE,
            IslandMode.EXPANDED_DROP_ACTIONS,
            IslandMode.EXPANDED_TERMINAL,
            IslandMode.EXPANDED_SHELF,
            IslandMode.EXPANDED_GLANCE,
        ):
            self.physics.width.set_target(484.0)
            self.physics.height.set_target(232.0 if mode == IslandMode.EXPANDED_MEDIA else 216.0)
            self.physics.corner_radius.set_target(34.0)
            self.physics.split_gap.set_target(0.0)
            self.physics.split_size.set_target(0.0)

    def _compute_geometries(self) -> tuple[QRectF, QRectF]:
        w = max(80.0, self.physics.width.value)
        h = max(26.0, self.physics.height.value)
        split_d = max(0.0, self.physics.split_size.value)
        gap = max(0.0, self.physics.split_gap.value)

        total_w = w + (gap + split_d if split_d > 1.0 else 0.0)
        start_x = (self.CANVAS_WIDTH - total_w) / 2.0

        if self.state.ux.position_mode == "bottom_taskbar":
            top_y = max(6.0, self.CANVAS_HEIGHT - h - 12.0)
        elif self.state.ux.position_mode == "docked_top":
            top_y = 0.0
        else:
            top_y = 10.0

        main_rect = QRectF(start_x, top_y, w, h)
        if split_d > 1.0:
            circle_x = main_rect.right() + gap
            circle_y = top_y + (h - split_d) / 2.0
            split_rect = QRectF(circle_x, circle_y, split_d, split_d)
        else:
            split_rect = QRectF(main_rect.right() - h, top_y, 0.0, 0.0)

        if self.terminal_input.isVisible():
            in_x = int(main_rect.left() + 18)
            in_y = int(main_rect.top() + 66)
            in_w = int(max(120, main_rect.width() - 98))
            self.terminal_input.setGeometry(in_x, in_y, in_w, 32)

        return main_rect, split_rect

    # ------------------------------------------------------------------
    # Painting (Ultra-Luxury Liquid Glass & Dynamic Aurora)
    # ------------------------------------------------------------------
    def _get_active_colors(self) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        theme = self.state.ux.theme
        if self.state.media.playing or self.state.expanded_target == "media":
            return self.state.media.accent_color, self.state.media.secondary_color
        return theme["primary"], theme["secondary"]

    def paintEvent(self, event) -> None:
        opacity = max(0.25, min(1.0, self.physics.opacity.value))

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setOpacity(opacity)

            now = time.monotonic()
            mode = self.state.resolve_mode(now)
            main_rect, split_rect = self._main_pill_rect, self._split_circle_rect
            if main_rect.width() < 10.0:
                main_rect, split_rect = self._compute_geometries()
                self._main_pill_rect, self._split_circle_rect = main_rect, split_rect

            r = min(self.physics.corner_radius.value, main_rect.height() / 2.0)

            self._hitboxes.clear()

            self._draw_drop_shadow(painter, main_rect, split_rect, r, now)
            self._draw_island_body(painter, main_rect, split_rect, r, now)

            painter.save()
            clip_path = QPainterPath()
            clip_path.addRoundedRect(main_rect, r, r)
            painter.setClipPath(clip_path)

            # Subtle animated aurora mesh inside expanded cards
            if mode.value.startswith("expanded"):
                self._draw_aurora_mesh(painter, main_rect, now)

            if mode == IslandMode.DROP_ZONE_HOVER:
                self._draw_drop_zone_hover(painter, main_rect, now)
            elif mode == IslandMode.EXPANDED_DROP_ACTIONS:
                self._draw_expanded_drop_actions(painter, main_rect)
            elif mode == IslandMode.EXPANDED_SHELF:
                self._draw_expanded_shelf(painter, main_rect, now)
            elif mode == IslandMode.EXPANDED_GLANCE:
                self._draw_expanded_glance(painter, main_rect, now)
            elif mode == IslandMode.EXPANDED_TERMINAL:
                self._draw_expanded_terminal(painter, main_rect)
            elif mode == IslandMode.EXPANDED_HARDWARE:
                self._draw_expanded_hardware(painter, main_rect)
            elif mode == IslandMode.EXPANDED_MEDIA:
                self._draw_expanded_media(painter, main_rect, now)
            elif mode == IslandMode.EXPANDED_TIMER:
                self._draw_expanded_timer(painter, main_rect, now)
            elif mode == IslandMode.ALERT_NOTIFICATION:
                self._draw_alert_notification(painter, main_rect)
            elif mode == IslandMode.ALERT_CLIPBOARD:
                self._draw_alert_clipboard(painter, main_rect)
            elif mode == IslandMode.ALERT_DOWNLOAD:
                self._draw_alert_download(painter, main_rect)
            elif mode == IslandMode.ALERT_VOLUME:
                self._draw_alert_volume(painter, main_rect)
            elif mode == IslandMode.ALERT_BATTERY:
                self._draw_alert_battery(painter, main_rect, now)
            elif mode == IslandMode.COMPACT_HARDWARE:
                self._draw_compact_hardware(painter, main_rect)
            elif mode == IslandMode.SPLIT_MULTITASK:
                if self.state.media.playing:
                    self._draw_compact_media(painter, main_rect, now)
                else:
                    self._draw_compact_hardware(painter, main_rect)
            elif mode == IslandMode.COMPACT_MEDIA:
                self._draw_compact_media(painter, main_rect, now)
            elif mode == IslandMode.COMPACT_TIMER:
                self._draw_compact_timer(painter, main_rect, now)
            else:
                self._draw_idle_pill(painter, main_rect, now)

            # Top glass specular reflection bar across the island
            spec_grad = QLinearGradient(
                QPointF(main_rect.center().x(), main_rect.top()),
                QPointF(main_rect.center().x(), main_rect.top() + 14.0),
            )
            spec_grad.setColorAt(0.0, QColor(255, 255, 255, 26))
            spec_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(
                QRectF(main_rect.left() + 16.0, main_rect.top(), main_rect.width() - 32.0, 12.0),
                spec_grad,
            )

            painter.restore()

            if split_rect.width() > 6.0:
                self._draw_split_timer_circle(painter, split_rect, now)
        except Exception:
            pass
        finally:
            painter.end()

    def _draw_aurora_mesh(self, painter: QPainter, rect: QRectF, now: float) -> None:
        (r1, g1, b1), (r2, g2, b2) = self._get_active_colors()
        ox1 = rect.left() + rect.width() * (0.25 + 0.12 * math.sin(now * 0.7))
        oy1 = rect.top() + rect.height() * (0.32 + 0.10 * math.cos(now * 0.5))
        g_left = QRadialGradient(QPointF(ox1, oy1), 220.0)
        g_left.setColorAt(0.0, QColor(r1, g1, b1, 52))
        g_left.setColorAt(0.6, QColor(r1, g1, b1, 14))
        g_left.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, g_left)

        ox2 = rect.left() + rect.width() * (0.78 + 0.10 * math.cos(now * 0.6))
        oy2 = rect.top() + rect.height() * (0.72 + 0.12 * math.sin(now * 0.8))
        g_right = QRadialGradient(QPointF(ox2, oy2), 200.0)
        g_right.setColorAt(0.0, QColor(r2, g2, b2, 44))
        g_right.setColorAt(0.6, QColor(r2, g2, b2, 10))
        g_right.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, g_right)

    def _draw_top_nav_bar(self, painter: QPainter, rect: QRectF, active_tab: str) -> None:
        """Luxury frosted-glass capsule navigation bar + Theme, Hub & Collapse buttons."""
        (r1, g1, b1), (r2, g2, b2) = self._get_active_colors()

        nav_y = rect.top() + 10.0
        capsule_rect = QRectF(rect.left() + 12.0, nav_y - 2.0, 376.0, 26.0)
        cap_path = QPainterPath()
        cap_path.addRoundedRect(capsule_rect, 13.0, 13.0)
        painter.fillPath(cap_path, QColor(255, 255, 255, 14))
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        painter.drawPath(cap_path)

        tabs = [
            ("nav_media", "media", "🎵 Плеер"),
            ("nav_timer", "timer", "🍅 Таймер"),
            ("nav_shelf", "shelf", "📎 Полка"),
            ("nav_hw", "hardware", "📊 Железо"),
            ("nav_term", "terminal", "❯ Терм"),
            ("nav_glance", "glance", "🏠 Обзор"),
        ]
        x_cur = capsule_rect.left() + 3.0
        tab_w = 59.5
        for hkey, target_name, label in tabs:
            t_rect = QRectF(x_cur, nav_y, tab_w, 22.0)
            self._hitboxes[hkey] = t_rect
            is_act = active_tab == target_name
            is_hov = self._hovered_hitbox == hkey
            tp = QPainterPath()
            tp.addRoundedRect(t_rect, 11.0, 11.0)
            if is_act:
                grad = QLinearGradient(t_rect.topLeft(), t_rect.bottomRight())
                grad.setColorAt(0.0, QColor(r1, g1, b1, 240))
                grad.setColorAt(1.0, QColor(r2, g2, b2, 225))
                painter.fillPath(tp, grad)
                painter.setPen(QPen(QColor(255, 255, 255, 95), 1.0))
                painter.drawPath(tp)
                painter.setPen(QColor(255, 255, 255))
            else:
                if is_hov:
                    painter.fillPath(tp, QColor(255, 255, 255, 42))
                painter.setPen(QColor(235, 240, 250) if is_hov else QColor(185, 195, 212))
            painter.setFont(QFont("Segoe UI Variable Text", 7, QFont.Weight.Bold))
            painter.drawText(t_rect, Qt.AlignmentFlag.AlignCenter, label)
            x_cur += tab_w + 2.5

        # 3 right utility buttons: Theme cycle (🎨), Control Hub (🎛), Collapse (✕)
        theme_rect = QRectF(rect.right() - 86.0, nav_y, 22.0, 22.0)
        self._hitboxes["cycle_theme"] = theme_rect
        painter.setPen(QPen(QColor(r1, g1, b1, 140), 1.0))
        painter.setBrush(QColor(r1, g1, b1, 155 if self._hovered_hitbox == "cycle_theme" else 55))
        painter.drawEllipse(theme_rect)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Symbol", 8, QFont.Weight.Bold))
        painter.drawText(theme_rect, Qt.AlignmentFlag.AlignCenter, "🎨")

        gear_rect = QRectF(rect.right() - 60.0, nav_y, 22.0, 22.0)
        self._hitboxes["open_hub"] = gear_rect
        painter.setPen(QPen(QColor(56, 189, 248, 130), 1.0))
        painter.setBrush(QColor(56, 189, 248, 165 if self._hovered_hitbox == "open_hub" else 55))
        painter.drawEllipse(gear_rect)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Symbol", 8, QFont.Weight.Bold))
        painter.drawText(gear_rect, Qt.AlignmentFlag.AlignCenter, "🎛")

        close_rect = QRectF(rect.right() - 34.0, nav_y, 22.0, 22.0)
        self._hitboxes["collapse"] = close_rect
        painter.setPen(QPen(QColor(239, 68, 68, 130), 1.0))
        painter.setBrush(QColor(239, 68, 68, 185 if self._hovered_hitbox == "collapse" else 60))
        painter.drawEllipse(close_rect)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Symbol", 8, QFont.Weight.Bold))
        painter.drawText(close_rect, Qt.AlignmentFlag.AlignCenter, "✕")

    def _draw_drop_shadow(
        self,
        painter: QPainter,
        main_rect: QRectF,
        split_rect: QRectF,
        r: float,
        now: float,
    ) -> None:
        (r1, g1, b1), (r2, g2, b2) = self._get_active_colors()
        pulse = 0.5 + 0.5 * math.sin(now * 2.6)
        audio_boost = int(self.state.media.audio_peak * 40.0) if self.state.media.playing else 0

        # Ambient colored neon halo around the pill
        halo_expand = 6.5
        halo_rect = main_rect.adjusted(-halo_expand, -halo_expand + 1.0, halo_expand, halo_expand + 2.5)
        halo_path = QPainterPath()
        halo_path.addRoundedRect(halo_rect, r + halo_expand, r + halo_expand)
        halo_grad = QLinearGradient(halo_rect.topLeft(), halo_rect.bottomRight())
        alpha_halo = min(90, int(24 + pulse * 14 + audio_boost))
        halo_grad.setColorAt(0.0, QColor(r1, g1, b1, alpha_halo))
        halo_grad.setColorAt(1.0, QColor(r2, g2, b2, alpha_halo))
        painter.fillPath(halo_path, halo_grad)

        # Crisp dark elevation drop shadow
        for i, expand in enumerate((4.0, 1.8)):
            alpha = 52 if i == 0 else 85
            shadow_rect = main_rect.adjusted(-expand, -expand + 2.0, expand, expand + 3.0)
            path = QPainterPath()
            path.addRoundedRect(shadow_rect, r + expand, r + expand)
            painter.fillPath(path, QColor(0, 0, 0, alpha))

            if split_rect.width() > 4.0:
                sr = split_rect.adjusted(-expand, -expand + 2.0, expand, expand + 3.0)
                spath = QPainterPath()
                spath.addEllipse(sr)
                painter.fillPath(spath, QColor(0, 0, 0, alpha))

    def _draw_island_body(
        self,
        painter: QPainter,
        main_rect: QRectF,
        split_rect: QRectF,
        r: float,
        now: float,
    ) -> None:
        body_path = QPainterPath()
        body_path.addRoundedRect(main_rect, r, r)

        if self.state.ux.position_mode == "docked_top" and main_rect.top() <= 2.0:
            top_flat = QPainterPath()
            top_flat.addRect(QRectF(main_rect.left(), main_rect.top(), main_rect.width(), r))
            body_path = body_path.united(top_flat)

        split_w = split_rect.width()
        gap = self.physics.split_gap.value

        if split_w > 1.0:
            circle_path = QPainterPath()
            circle_path.addEllipse(split_rect)
            body_path = body_path.united(circle_path)

            if gap < 10.5:
                bridge_factor = max(0.0, 1.0 - (gap / 10.5))
                neck_h = split_w * 0.55 * bridge_factor
                cy = main_rect.center().y()
                neck_rect = QRectF(
                    main_rect.right() - 8.0,
                    cy - neck_h / 2.0,
                    gap + 16.0,
                    neck_h,
                )
                neck_path = QPainterPath()
                neck_path.addRoundedRect(neck_rect, neck_h / 2.0, neck_h / 2.0)
                body_path = body_path.united(neck_path)

        bg_r, bg_g, bg_b = self.state.ux.theme["bg"]
        painter.fillPath(body_path, QColor(bg_r, bg_g, bg_b, 252))

        # Luxury iridescent glass rim border
        (r1, g1, b1), (r2, g2, b2) = self._get_active_colors()
        rim_grad = QLinearGradient(main_rect.topLeft(), main_rect.bottomRight())
        rim_grad.setColorAt(0.0, QColor(r1, g1, b1, 135))
        rim_grad.setColorAt(0.45, QColor(255, 255, 255, 55))
        rim_grad.setColorAt(1.0, QColor(r2, g2, b2, 125))
        painter.setPen(QPen(rim_grad, 1.25))
        painter.drawPath(body_path)

    # ------------------------------------------------------------------
    # Act 4 Pro Renderers: File Shelf + Clipboard History & Smart Glance
    # ------------------------------------------------------------------
    def _draw_expanded_shelf(self, painter: QPainter, rect: QRectF, now: float) -> None:
        self._draw_top_nav_bar(painter, rect, "shelf")

        shelf_files = self.state.drop_zone.shelf_files
        painter.setPen(QColor(56, 189, 248))
        painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.left() + 16.0, rect.top() + 40.0, 320.0, 16.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"📎 ПОЛКА ({len(shelf_files)}/4) — КЛИК: КОПИЯ (Ctrl+V) • ТЯНИ: DRAG-OUT",
        )

        add_rect = QRectF(rect.right() - 126.0, rect.top() + 39.0, 56.0, 20.0)
        self._hitboxes["shelf_add_file"] = add_rect
        ap = QPainterPath()
        ap.addRoundedRect(add_rect, 10.0, 10.0)
        painter.fillPath(ap, QColor(56, 189, 248, 210 if self._hovered_hitbox == "shelf_add_file" else 145))
        painter.setPen(QColor(10, 12, 16))
        painter.setFont(QFont("Segoe UI Variable Text", 7, QFont.Weight.Bold))
        painter.drawText(add_rect, Qt.AlignmentFlag.AlignCenter, "➕ Файл")

        if shelf_files:
            clr_rect = QRectF(rect.right() - 66.0, rect.top() + 39.0, 50.0, 20.0)
            self._hitboxes["shelf_clear"] = clr_rect
            cp = QPainterPath()
            cp.addRoundedRect(clr_rect, 10.0, 10.0)
            painter.fillPath(cp, QColor(239, 68, 68, 110 if self._hovered_hitbox == "shelf_clear" else 55))
            painter.setPen(QColor(254, 202, 202))
            painter.setFont(QFont("Segoe UI Variable Text", 7, QFont.Weight.Bold))
            painter.drawText(clr_rect, Qt.AlignmentFlag.AlignCenter, "Очистить")

        shelf_y = rect.top() + 62.0
        if not shelf_files:
            empty_rect = QRectF(rect.left() + 16.0, shelf_y, rect.width() - 32.0, 42.0)
            ep = QPainterPath()
            ep.addRoundedRect(empty_rect, 12.0, 12.0)
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1.2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(255, 255, 255, 12))
            painter.drawPath(ep)
            painter.setPen(QColor(165, 180, 200))
            painter.setFont(QFont("Segoe UI Variable Text", 8))
            painter.drawText(
                empty_rect,
                Qt.AlignmentFlag.AlignCenter,
                "Нажмите «➕ Файл» или перетащите сюда любые файлы с рабочего стола",
            )
        else:
            card_w = (rect.width() - 32.0 - 6.0 * (max(1, len(shelf_files)) - 1)) / max(2, len(shelf_files))
            card_w = min(215.0, card_w)
            for idx, fitem in enumerate(shelf_files[:4]):
                cx = rect.left() + 16.0 + idx * (card_w + 6.0)
                c_rect = QRectF(cx, shelf_y, card_w, 42.0)
                hkey = f"shelf_file_{idx}"
                self._hitboxes[hkey] = c_rect
                hov = self._hovered_hitbox == hkey

                cp = QPainterPath()
                cp.addRoundedRect(c_rect, 11.0, 11.0)
                painter.fillPath(cp, QColor(56, 189, 248, 60 if hov else 28))
                painter.setPen(QPen(QColor(56, 189, 248, 155 if hov else 65), 1.0))
                painter.drawPath(cp)

                badge_rect = QRectF(c_rect.left() + 5.0, c_rect.top() + 6.0, 26.0, 30.0)
                bp = QPainterPath()
                bp.addRoundedRect(badge_rect, 6.0, 6.0)
                painter.fillPath(bp, QColor(56, 189, 248, 220))
                painter.setPen(QColor(10, 12, 16))
                painter.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, fitem.ext_badge)

                painter.setPen(QColor(255, 255, 255))
                painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
                elided_fn = painter.fontMetrics().elidedText(
                    fitem.name, Qt.TextElideMode.ElideMiddle, int(card_w - 38.0)
                )
                painter.drawText(
                    QRectF(c_rect.left() + 35.0, c_rect.top() + 5.0, card_w - 38.0, 16.0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    elided_fn,
                )
                painter.setPen(QColor(165, 180, 200))
                painter.setFont(QFont("Segoe UI Variable Text", 7))
                painter.drawText(
                    QRectF(c_rect.left() + 35.0, c_rect.top() + 21.0, card_w - 38.0, 15.0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"Ctrl+V / Тяни • {fitem.size_str}",
                )

        hist_top = rect.top() + 110.0
        cb_info = self.state.clipboard
        header_txt = (
            cb_info.copied_feedback_text
            if now < cb_info.copied_feedback_until
            else "📋 ИСТОРИЯ БУФЕРА ОБМЕНА (КЛИК — СКОПИРОВАТЬ ДЛЯ Ctrl+V)"
        )
        painter.setPen(
            QColor(52, 211, 153)
            if now < cb_info.copied_feedback_until
            else QColor(192, 132, 252)
        )
        painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.left() + 16.0, hist_top, 430.0, 16.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            header_txt,
        )

        chips_y = hist_top + 19.0
        col_w = (rect.width() - 40.0) / 2.0
        for idx, hitem in enumerate(cb_info.history[:5]):
            row = idx // 2
            col = idx % 2
            if idx == 4:
                hx = rect.left() + 16.0
                hw = rect.width() - 32.0
                hy = chips_y + 2 * 25.0
            else:
                hx = rect.left() + 16.0 + col * (col_w + 8.0)
                hw = col_w
                hy = chips_y + row * 25.0

            h_rect = QRectF(hx, hy, hw, 22.0)
            key = f"cb_hist_{idx}"
            self._hitboxes[key] = h_rect
            hov = self._hovered_hitbox == key

            hp = QPainterPath()
            hp.addRoundedRect(h_rect, 11.0, 11.0)
            painter.fillPath(hp, QColor(255, 255, 255, 48 if hov else 22))
            if hov:
                painter.setPen(QPen(QColor(255, 255, 255, 80), 1.0))
                painter.drawPath(hp)

            r, g, b = hitem.rgb_tuple
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(r, g, b))
            painter.drawEllipse(QPointF(h_rect.left() + 11.0, h_rect.center().y()), 4.5, 4.5)

            painter.setPen(QColor(245, 247, 252))
            painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold if hitem.kind == "color" else QFont.Weight.Normal))
            elided = painter.fontMetrics().elidedText(
                hitem.display_label, Qt.TextElideMode.ElideRight, int(hw - 26.0)
            )
            painter.drawText(
                QRectF(h_rect.left() + 20.0, h_rect.top(), hw - 24.0, h_rect.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided,
            )

    def _draw_expanded_glance(self, painter: QPainter, rect: QRectF, now: float) -> None:
        now_dt = datetime.now()
        time_str = now_dt.strftime("%H:%M:%S")
        weekday_str = RUSSIAN_WEEKDAYS[now_dt.weekday()]
        date_str = f"{weekday_str}, {now_dt.day} {RUSSIAN_MONTHS[now_dt.month]}"
        gl = self.state.glance
        (r1, g1, b1), (r2, g2, b2) = self._get_active_colors()

        self._draw_top_nav_bar(painter, rect, "glance")

        # Left Glass Clock Card
        clock_card = QRectF(rect.left() + 16.0, rect.top() + 44.0, 256.0, 68.0)
        cp = QPainterPath()
        cp.addRoundedRect(clock_card, 16.0, 16.0)
        painter.fillPath(cp, QColor(255, 255, 255, 16))
        painter.setPen(QPen(QColor(255, 255, 255, 32), 1.0))
        painter.drawPath(cp)

        painter.setPen(QColor(r2, g2, b2))
        painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(clock_card.left() + 14.0, clock_card.top() + 6.0, 228.0, 16.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            date_str.upper(),
        )

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 23, QFont.Weight.Bold))
        painter.drawText(
            QRectF(clock_card.left() + 12.0, clock_card.top() + 23.0, 232.0, 40.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            time_str,
        )

        # Right Glass Weather Card
        w_rect = QRectF(rect.right() - 196.0, rect.top() + 44.0, 180.0, 68.0)
        self._hitboxes["cycle_weather"] = w_rect
        wp = QPainterPath()
        wp.addRoundedRect(w_rect, 16.0, 16.0)
        painter.fillPath(wp, QColor(255, 255, 255, 32 if self._hovered_hitbox == "cycle_weather" else 18))
        painter.setPen(QPen(QColor(251, 191, 36, 95 if self._hovered_hitbox == "cycle_weather" else 40), 1.0))
        painter.drawPath(wp)

        painter.setPen(QColor(251, 191, 36))
        painter.setFont(QFont("Segoe UI Variable Display", 14, QFont.Weight.Bold))
        painter.drawText(
            QRectF(w_rect.left() + 14.0, w_rect.top() + 8.0, 154.0, 26.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{gl.weather_icon} +{gl.temperature_c}°C",
        )
        painter.setPen(QColor(200, 210, 225))
        painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(w_rect.left() + 14.0, w_rect.top() + 36.0, 154.0, 20.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{gl.condition} • Ощущ. +{gl.feels_like_c}°",
        )

        # Bottom Status + Quick Theme Switcher Card
        hw = self.state.hardware
        vol = self.state.audio.volume_percent
        theme_lbl = self.state.ux.theme["label"]
        status_rect = QRectF(rect.left() + 16.0, rect.top() + 124.0, rect.width() - 32.0, 74.0)
        sp = QPainterPath()
        sp.addRoundedRect(status_rect, 16.0, 16.0)
        painter.fillPath(sp, QColor(255, 255, 255, 15))
        painter.setPen(QPen(QColor(255, 255, 255, 25), 1.0))
        painter.drawPath(sp)

        painter.setPen(QColor(235, 240, 250))
        painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(status_rect.left() + 14.0, status_rect.top() + 8.0, status_rect.width() - 28.0, 20.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"🔊 Звук: {vol}%   •   ⚡ CPU: {int(hw.cpu_percent)}% ({int(hw.cpu_temp_c)}°C)   •   💾 RAM: {hw.ram_used_gb} ГБ   •   Тема: {theme_lbl}",
        )

        # Quick action pills inside Glance
        quick_pills = [
            ("nav_media", "🎵 Открыть плеер"),
            ("nav_timer", "🍅 Помодоро 25м"),
            ("cycle_theme", "🎨 Сменить тему"),
            ("open_hub", "🎛 Все настройки"),
        ]
        qx = status_rect.left() + 12.0
        qy = status_rect.top() + 36.0
        qw = (status_rect.width() - 24.0 - 18.0) / 4.0
        for hkey, qlbl in quick_pills:
            qr = QRectF(qx, qy, qw, 26.0)
            self._hitboxes[hkey] = qr
            hov = self._hovered_hitbox == hkey
            qp = QPainterPath()
            qp.addRoundedRect(qr, 13.0, 13.0)
            painter.fillPath(qp, QColor(r1, g1, b1, 145 if hov else 65))
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI Variable Text", 7, QFont.Weight.Bold))
            painter.drawText(qr, Qt.AlignmentFlag.AlignCenter, qlbl)
            qx += qw + 6.0

    # ------------------------------------------------------------------
    # Act 2 Renderers
    # ------------------------------------------------------------------
    def _draw_alert_clipboard(self, painter: QPainter, rect: QRectF) -> None:
        cy = rect.center().y()
        cb = self.state.clipboard

        if cb.kind == "color":
            r, g, b = cb.rgb_tuple
            swatch_center = QPointF(rect.left() + 26.0, cy)
            glow = QRadialGradient(swatch_center, 22.0)
            glow.setColorAt(0.0, QColor(r, g, b, 165))
            glow.setColorAt(1.0, QColor(r, g, b, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(swatch_center, 22.0, 22.0)

            painter.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
            painter.setBrush(QColor(r, g, b))
            painter.drawEllipse(swatch_center, 14.0, 14.0)

            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI Variable Display", 10, QFont.Weight.Bold))
            painter.drawText(
                QRectF(rect.left() + 50.0, rect.top() + 7.0, rect.width() - 64.0, 20.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"Скопирован цвет {cb.hex_color}",
            )
            painter.setPen(QColor(165, 175, 195))
            painter.setFont(QFont("Consolas", 8, QFont.Weight.Medium))
            painter.drawText(
                QRectF(rect.left() + 50.0, rect.top() + 26.0, rect.width() - 64.0, 18.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"rgb({r}, {g}, {b}) • Сохранено в Полку",
            )

        elif cb.kind == "image" and cb.qimage is not None:
            thumb_rect = QRectF(rect.left() + 10.0, cy - 17.0, 34.0, 34.0)
            path = QPainterPath()
            path.addRoundedRect(thumb_rect, 8.0, 8.0)
            painter.save()
            painter.setClipPath(path)
            painter.drawImage(thumb_rect, cb.qimage)
            painter.restore()

            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold))
            painter.drawText(
                QRectF(rect.left() + 52.0, rect.top() + 8.0, rect.width() - 66.0, 18.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "Скопировано изображение",
            )
            painter.setPen(QColor(56, 189, 248))
            painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            painter.drawText(
                QRectF(rect.left() + 52.0, rect.top() + 26.0, rect.width() - 66.0, 18.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"📐 {cb.image_dims}",
            )

        else:
            badge_center = QPointF(rect.left() + 24.0, cy)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(168, 85, 247, 55))
            painter.drawEllipse(badge_center, 15.0, 15.0)
            painter.setPen(QColor(216, 180, 254))
            painter.setFont(QFont("Segoe UI Symbol", 11, QFont.Weight.Bold))
            painter.drawText(
                QRectF(badge_center.x() - 15, badge_center.y() - 15, 30, 30),
                Qt.AlignmentFlag.AlignCenter,
                "📋",
            )

            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold))
            elided = painter.fontMetrics().elidedText(
                cb.preview_text, Qt.TextElideMode.ElideRight, int(rect.width() - 74.0)
            )
            painter.drawText(
                QRectF(rect.left() + 48.0, rect.top() + 7.0, rect.width() - 62.0, 20.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided,
            )
            painter.setPen(QColor(148, 163, 184))
            painter.setFont(QFont("Segoe UI Variable Text", 8))
            painter.drawText(
                QRectF(rect.left() + 48.0, rect.top() + 26.0, rect.width() - 62.0, 18.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"Скопирован текст ({cb.char_count} симв.) • Клик — история",
            )

    def _draw_alert_download(self, painter: QPainter, rect: QRectF) -> None:
        cy = rect.center().y()
        dl = self.state.download
        pct = int(round(dl.progress * 100))

        center = QPointF(rect.left() + 25.0, cy)
        r = 13.0
        arc_rect = QRectF(center.x() - r, center.y() - r, r * 2.0, r * 2.0)
        painter.setPen(QPen(QColor(56, 189, 248, 50), 2.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(arc_rect)

        pen_fg = QPen(QColor(52, 211, 153) if pct >= 100 else QColor(56, 189, 248), 2.8)
        pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_fg)
        painter.drawArc(arc_rect, 90 * 16, int(-360 * 16 * dl.progress))

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Symbol", 8, QFont.Weight.Bold))
        painter.drawText(arc_rect, Qt.AlignmentFlag.AlignCenter, "✓" if pct >= 100 else "↓")

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold))
        elided = painter.fontMetrics().elidedText(
            dl.filename, Qt.TextElideMode.ElideMiddle, int(rect.width() - 115.0)
        )
        painter.drawText(
            QRectF(rect.left() + 48.0, rect.top() + 6.0, rect.width() - 108.0, 20.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided,
        )

        status_str = "Загрузка завершена!" if pct >= 100 else f"{dl.speed_mbps} МБ/с • Клик — скрыть"
        painter.setPen(QColor(148, 163, 184))
        painter.setFont(QFont("Segoe UI Variable Text", 8))
        painter.drawText(
            QRectF(rect.left() + 48.0, rect.top() + 24.0, rect.width() - 108.0, 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            status_str,
        )

        painter.setPen(QColor(52, 211, 153) if pct >= 100 else QColor(56, 189, 248))
        painter.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.right() - 58.0, rect.top(), 44.0, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            f"{pct}%",
        )

    def _draw_compact_hardware(self, painter: QPainter, rect: QRectF) -> None:
        hw = self.state.hardware
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))

        items = [
            (f"CPU {int(hw.cpu_percent)}%•{int(hw.cpu_temp_c)}°", QColor(56, 189, 248)),
            (f"GPU {int(hw.gpu_percent)}%", QColor(168, 85, 247)),
            (f"RAM {hw.ram_used_gb}G", QColor(52, 211, 153)),
        ]
        slot_w = (rect.width() - 20.0) / 3.0
        for i, (text, col) in enumerate(items):
            sx = rect.left() + 10.0 + i * slot_w
            dot_y = rect.center().y()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(col)
            painter.drawEllipse(QPointF(sx + 4.0, dot_y), 3.4, 3.4)

            painter.setPen(QColor(240, 244, 250))
            painter.drawText(
                QRectF(sx + 10.0, rect.top(), slot_w - 10.0, rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )

    def _draw_expanded_hardware(self, painter: QPainter, rect: QRectF) -> None:
        hw = self.state.hardware
        self._draw_top_nav_bar(painter, rect, "hardware")

        metrics = [
            ("CPU", f"{int(hw.cpu_percent)}%", f"{hw.cpu_temp_c}°C", hw.cpu_percent / 100.0, QColor(56, 189, 248)),
            ("GPU", f"{int(hw.gpu_percent)}%", "Ядро", hw.gpu_percent / 100.0, QColor(168, 85, 247)),
            ("RAM", f"{int(hw.ram_percent)}%", f"{hw.ram_used_gb}/{hw.ram_total_gb}G", hw.ram_percent / 100.0, QColor(52, 211, 153)),
        ]

        y_center = rect.top() + 86.0
        for i, (label, main_val, sub_val, ratio, color) in enumerate(metrics):
            cx = rect.left() + 84.0 + i * 156.0
            r = 27.0
            arc_rect = QRectF(cx - r, y_center - r, r * 2.0, r * 2.0)

            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 45), 4.5))
            painter.setBrush(QColor(255, 255, 255, 10))
            painter.drawEllipse(arc_rect)

            pen_fg = QPen(color, 4.5)
            pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_fg)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(arc_rect, 90 * 16, int(-360 * 16 * max(0.03, min(1.0, ratio))))

            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            painter.drawText(arc_rect, Qt.AlignmentFlag.AlignCenter, main_val)

            painter.setPen(QColor(200, 210, 225))
            painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
            painter.drawText(
                QRectF(cx - 54.0, y_center + 30.0, 108.0, 18.0),
                Qt.AlignmentFlag.AlignCenter,
                f"{label} • {sub_val}",
            )

        # Bottom Left: Pin HUD Toggle
        pin_rect = QRectF(rect.left() + 18.0, rect.bottom() - 42.0, 198.0, 28.0)
        self._hitboxes["toggle_hw_hud"] = pin_rect
        pin_path = QPainterPath()
        pin_path.addRoundedRect(pin_rect, 14.0, 14.0)
        painter.fillPath(
            pin_path,
            QColor(56, 189, 248, 220) if hw.hud_enabled else QColor(255, 255, 255, 26),
        )
        painter.setPen(QColor(10, 12, 16) if hw.hud_enabled else QColor(235, 240, 250))
        painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
        painter.drawText(
            pin_rect,
            Qt.AlignmentFlag.AlignCenter,
            "📌 HUD закреплен в пилюле" if hw.hud_enabled else "📌 Закрепить HUD в пилюле",
        )

        # Bottom Right: Real-Time CPU Sparkline Graph
        graph_rect = QRectF(rect.left() + 230.0, rect.bottom() - 44.0, rect.width() - 248.0, 30.0)
        gp = QPainterPath()
        gp.addRoundedRect(graph_rect, 10.0, 10.0)
        painter.fillPath(gp, QColor(255, 255, 255, 14))
        painter.setPen(QPen(QColor(56, 189, 248, 60), 1.0))
        painter.drawPath(gp)

        hist = hw.cpu_history[-20:] if hw.cpu_history else [15.0, 18.0]
        if len(hist) >= 2:
            pts: list[QPointF] = []
            gw = graph_rect.width() - 12.0
            gh = graph_rect.height() - 8.0
            for idx, val in enumerate(hist):
                px = graph_rect.left() + 6.0 + (idx / max(1, len(hist) - 1)) * gw
                py = graph_rect.bottom() - 4.0 - (max(0.0, min(100.0, val)) / 100.0) * gh
                pts.append(QPointF(px, py))
            painter.setPen(QPen(QColor(56, 189, 248, 220), 1.8))
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])

    def _draw_drop_zone_hover(self, painter: QPainter, rect: QRectF, now: float) -> None:
        inner = rect.adjusted(10.0, 10.0, -10.0, -10.0)
        pen = QPen(QColor(56, 189, 248, 220), 2.0, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(56, 189, 248, 32))
        path = QPainterPath()
        path.addRoundedRect(inner, 20.0, 20.0)
        painter.drawPath(path)

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold))
        painter.drawText(
            inner.adjusted(0, -10, 0, 0),
            Qt.AlignmentFlag.AlignCenter,
            "📥 Отпустите файл в Dynamic Island",
        )
        painter.setPen(QColor(165, 180, 200))
        painter.setFont(QFont("Segoe UI Variable Text", 8))
        painter.drawText(
            inner.adjusted(0, 22, 0, 0),
            Qt.AlignmentFlag.AlignCenter,
            "Файл закрепится на Полке и скопируется для быстрой вставки Ctrl+V!",
        )

    def _draw_expanded_drop_actions(self, painter: QPainter, rect: QRectF) -> None:
        dz = self.state.drop_zone
        self._draw_top_nav_bar(painter, rect, "shelf")

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold))
        elided_name = painter.fontMetrics().elidedText(
            f"📁 {dz.dropped_file_name or 'Файл'} ({dz.dropped_file_size_str})",
            Qt.TextElideMode.ElideMiddle,
            int(rect.width() - 44.0),
        )
        painter.drawText(
            QRectF(rect.left() + 20.0, rect.top() + 46.0, rect.width() - 44.0, 24.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_name,
        )

        painter.setPen(QColor(52, 211, 153))
        painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
        elided_status = painter.fontMetrics().elidedText(
            dz.status_feedback, Qt.TextElideMode.ElideRight, int(rect.width() - 44.0)
        )
        painter.drawText(
            QRectF(rect.left() + 20.0, rect.top() + 74.0, rect.width() - 44.0, 20.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_status,
        )

        actions = [
            ("drop_open_shelf", f"📎 Полка ({len(dz.shelf_files)})", QColor(14, 165, 233, 225)),
            ("drop_copy_file", "📄 Коп. файл", QColor(16, 185, 129, 215)),
            ("drop_copy_path", "📋 Коп. путь", QColor(59, 130, 246, 210)),
            ("drop_zip", "📦 В .ZIP", QColor(168, 85, 247, 210)),
            ("drop_trash", "🗑️ Корзина", QColor(239, 68, 68, 210)),
        ]
        btn_y = rect.top() + 118.0
        btn_w = 84.0
        for i, (key, label, col) in enumerate(actions):
            bx = rect.left() + 18.0 + i * (btn_w + 6.0)
            b_rect = QRectF(bx, btn_y, btn_w, 36.0)
            self._hitboxes[key] = b_rect
            b_path = QPainterPath()
            b_path.addRoundedRect(b_rect, 12.0, 12.0)
            painter.fillPath(b_path, col if self._hovered_hitbox == key else QColor(col.red(), col.green(), col.blue(), 150))
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI Variable Text", 7, QFont.Weight.Bold))
            painter.drawText(b_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_expanded_terminal(self, painter: QPainter, rect: QRectF) -> None:
        self._draw_top_nav_bar(painter, rect, "terminal")

        painter.setPen(QColor(192, 132, 252))
        painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.left() + 20.0, rect.top() + 42.0, 410.0, 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "❯ БЫСТРЫЙ ТЕРМИНАЛ, КАЛЬКУЛЯТОР И ПОИСК (Печатайте и жмите Enter):",
        )

        run_rect = QRectF(rect.right() - 72.0, rect.top() + 66.0, 54.0, 32.0)
        self._hitboxes["term_run"] = run_rect
        r_path = QPainterPath()
        r_path.addRoundedRect(run_rect, 10.0, 10.0)
        painter.fillPath(r_path, QColor(168, 85, 247, 235))
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
        painter.drawText(run_rect, Qt.AlignmentFlag.AlignCenter, "Пуск ↵")

        painter.setPen(QColor(52, 211, 153))
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        elided_out = painter.fontMetrics().elidedText(
            self.state.terminal.last_output,
            Qt.TextElideMode.ElideRight,
            int(rect.width() - 40.0),
        )
        painter.drawText(
            QRectF(rect.left() + 20.0, rect.top() + 106.0, rect.width() - 40.0, 22.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_out,
        )

        chips = [
            ("term_calc", "calc"),
            ("term_notepad", "notepad"),
            ("term_explorer", "explorer"),
            ("term_math", "256*14"),
            ("term_ip", "whoami"),
        ]
        cy = rect.top() + 140.0
        for i, (key, cmd_lbl) in enumerate(chips):
            c_rect = QRectF(rect.left() + 20.0 + i * 82.0, cy, 76.0, 26.0)
            self._hitboxes[key] = c_rect
            cp = QPainterPath()
            cp.addRoundedRect(c_rect, 13.0, 13.0)
            painter.fillPath(cp, QColor(255, 255, 255, 44 if self._hovered_hitbox == key else 22))
            painter.setPen(QColor(235, 240, 250))
            painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            painter.drawText(c_rect, Qt.AlignmentFlag.AlignCenter, cmd_lbl)

    def _draw_alert_notification(self, painter: QPainter, rect: QRectF) -> None:
        nf = self.state.notification
        r, g, b = nf.accent_color
        cy = rect.center().y()

        badge_center = QPointF(rect.left() + 30.0, cy)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(r, g, b))
        painter.drawEllipse(badge_center, 18.0, 18.0)

        painter.setPen(QColor(10, 12, 16))
        painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold))
        painter.drawText(
            QRectF(badge_center.x() - 18, badge_center.y() - 18, 36, 36),
            Qt.AlignmentFlag.AlignCenter,
            nf.app_badge,
        )

        painter.setPen(QColor(r, g, b))
        painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.left() + 58.0, rect.top() + 12.0, rect.width() - 80.0, 16.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{nf.app_name.upper()} • {nf.sender}",
        )

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.DemiBold))
        elided_msg = painter.fontMetrics().elidedText(
            nf.message, Qt.TextElideMode.ElideRight, int(rect.width() - 76.0)
        )
        painter.drawText(
            QRectF(rect.left() + 58.0, rect.top() + 34.0, rect.width() - 72.0, 32.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_msg,
        )

    # ------------------------------------------------------------------
    # Act 1 Renderers (Idle + Smart Glance, Media with Compact Controls, Timer, Volume, Battery)
    # ------------------------------------------------------------------
    def _draw_camera_lens(self, painter: QPainter, center: QPointF) -> None:
        """Draws realistic iPhone 16 Pro TrueDepth sapphire camera lens."""
        painter.save()
        painter.setPen(QPen(QColor(45, 52, 72, 180), 1.0))
        painter.setBrush(QColor(14, 16, 24, 255))
        painter.drawEllipse(center, 6.0, 6.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(38, 68, 138, 165))
        painter.drawEllipse(center, 3.2, 3.2)

        painter.setBrush(QColor(140, 190, 255, 210))
        painter.drawEllipse(QPointF(center.x() - 1.2, center.y() - 1.2), 1.2, 1.2)
        painter.restore()

    def _draw_idle_pill(self, painter: QPainter, rect: QRectF, now: float) -> None:
        cy = rect.center().y()
        (r1, g1, b1), _ = self._get_active_colors()

        if self.state.glance.enabled_in_idle:
            now_dt = datetime.now()
            clock_str = now_dt.strftime("%H:%M")
            gl = self.state.glance

            self._draw_camera_lens(painter, QPointF(rect.left() + 18.0, cy))

            painter.setPen(QColor(245, 247, 252))
            painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            painter.drawText(
                QRectF(rect.left() + 30.0, rect.top(), 48.0, rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                clock_str,
            )

            # Quick Music button right inside the compact idle pill!
            m_btn = QRectF(rect.left() + 82.0, cy - 11.0, 78.0, 22.0)
            self._hitboxes["nav_media"] = m_btn
            mp = QPainterPath()
            mp.addRoundedRect(m_btn, 11.0, 11.0)
            painter.fillPath(mp, QColor(r1, g1, b1, 175 if self._hovered_hitbox == "nav_media" else 95))
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
            painter.drawText(m_btn, Qt.AlignmentFlag.AlignCenter, "🎵 Плеер")

            painter.setPen(QColor(251, 191, 36))
            painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold))
            right_label = f"{gl.weather_icon} +{gl.temperature_c}°"
            painter.drawText(
                QRectF(rect.left() + 164.0, rect.top(), rect.width() - 176.0 - (16.0 if self.state.audio.mic_active else 0.0), rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                right_label,
            )

            if self.state.audio.mic_active:
                self._draw_mic_dot(painter, QPointF(rect.right() - 13.0, cy), now)
            return

        self._draw_camera_lens(painter, QPointF(rect.left() + 22.0, cy))
        if self.state.audio.mic_active:
            self._draw_mic_dot(painter, QPointF(rect.right() - 14.0, cy), now)

    def _draw_mic_dot(self, painter: QPainter, center: QPointF, now: float) -> None:
        pulse = 0.5 + 0.5 * math.sin(now * 4.5)
        glow_r = 6.5 + pulse * 2.5
        glow = QRadialGradient(center, glow_r)
        glow.setColorAt(0.0, QColor(251, 146, 60, 180))
        glow.setColorAt(1.0, QColor(251, 146, 60, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, glow_r, glow_r)

        painter.setBrush(QColor(249, 115, 22))
        painter.drawEllipse(center, 4.0, 4.0)

    def _draw_compact_media(self, painter: QPainter, rect: QRectF, now: float) -> None:
        cy = rect.center().y()
        art_size = 26.0
        art_rect = QRectF(rect.left() + 8.0, cy - art_size / 2.0, art_size, art_size)
        self._draw_album_art(painter, art_rect, radius=8.0, now=now)

        # Mini transport buttons right inside compact pill so user can change music even without expanding!
        btn_y = cy
        prev_r = QRectF(rect.right() - 122.0, btn_y - 11.0, 22.0, 22.0)
        play_r = QRectF(rect.right() - 98.0, btn_y - 11.0, 22.0, 22.0)
        next_r = QRectF(rect.right() - 74.0, btn_y - 11.0, 22.0, 22.0)
        self._hitboxes["media_prev"] = prev_r
        self._hitboxes["media_play"] = play_r
        self._hitboxes["media_next"] = next_r

        for hkey, r_btn, sym in [
            ("media_prev", prev_r, "⏮"),
            ("media_play", play_r, "⏸" if self.state.media.playing else "▶"),
            ("media_next", next_r, "⏭"),
        ]:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 65 if self._hovered_hitbox == hkey else 24))
            painter.drawEllipse(r_btn)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI Symbol", 7, QFont.Weight.Bold))
            painter.drawText(r_btn, Qt.AlignmentFlag.AlignCenter, sym)

        text_rect = QRectF(art_rect.right() + 8.0, rect.top(), max(30.0, prev_r.left() - art_rect.right() - 12.0), rect.height())
        painter.setPen(QColor(245, 247, 252))
        font = QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        elided = painter.fontMetrics().elidedText(
            self.state.media.title,
            Qt.TextElideMode.ElideRight,
            int(text_rect.width()),
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided,
        )

        eq_right = rect.right() - (24.0 if self.state.audio.mic_active else 10.0)
        self._draw_equalizer_wave(
            painter,
            right_x=eq_right,
            center_y=cy,
            max_height=16.0,
            bar_width=2.3,
            gap=1.8,
        )

        if self.state.audio.mic_active:
            self._draw_mic_dot(painter, QPointF(rect.right() - 12.0, cy), now)

    def _draw_compact_timer(self, painter: QPainter, rect: QRectF, now: float) -> None:
        cy = rect.center().y()
        ring_r = 10.5
        ring_center = QPointF(rect.left() + 20.0, cy)
        self._draw_timer_ring(painter, ring_center, ring_r)

        if self.state.timer.is_pomodoro:
            accent = QColor(244, 63, 94) if self.state.timer.pomodoro_phase == "focus" else QColor(52, 211, 153)
            prefix = "🍅 " if self.state.timer.pomodoro_phase == "focus" else "☕ "
        else:
            accent = QColor(251, 191, 36) if self.state.timer.running else QColor(180, 185, 195)
            prefix = ""

        painter.setPen(accent)
        font = QFont("Consolas", 11, QFont.Weight.Bold)
        painter.setFont(font)
        text_rect = QRectF(rect.left() + 36.0, rect.top(), rect.width() - 48.0, rect.height())
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            f"{prefix}{self.state.timer.display_text}",
        )

    def _draw_split_timer_circle(self, painter: QPainter, split_rect: QRectF, now: float) -> None:
        center = split_rect.center()
        r = split_rect.width() * 0.36
        self._draw_timer_ring(painter, center, r)
        self._hitboxes["split_timer"] = split_rect

    def _draw_timer_ring(self, painter: QPainter, center: QPointF, radius: float) -> None:
        painter.save()
        if self.state.timer.is_pomodoro:
            ring_col = QColor(244, 63, 94) if self.state.timer.pomodoro_phase == "focus" else QColor(52, 211, 153)
        else:
            ring_col = QColor(251, 191, 36)

        pen_bg = QPen(QColor(ring_col.red(), ring_col.green(), ring_col.blue(), 55), 2.5)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_bg)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        arc_rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)
        painter.drawEllipse(arc_rect)

        pen_fg = QPen(ring_col, 2.6)
        pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_fg)
        span_angle = int(-360.0 * 16 * self.state.timer.progress)
        painter.drawArc(arc_rect, 90 * 16, span_angle)

        angle = math.radians(-90 + 360 * (1.0 - self.state.timer.progress))
        hx = center.x() + math.cos(angle) * (radius * 0.55)
        hy = center.y() + math.sin(angle) * (radius * 0.55)
        painter.drawLine(center, QPointF(hx, hy))
        painter.restore()

    def _draw_alert_volume(self, painter: QPainter, rect: QRectF) -> None:
        cy = rect.center().y()
        vol = self.state.audio.volume_percent
        muted = self.state.audio.muted or vol == 0
        (r1, g1, b1), (r2, g2, b2) = self._get_active_colors()

        icon_x = rect.left() + 20.0
        accent = QColor(239, 68, 68) if muted else QColor(255, 255, 255)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)

        cone = QPainterPath()
        cone.moveTo(icon_x - 5, cy - 3)
        cone.lineTo(icon_x - 1, cy - 3)
        cone.lineTo(icon_x + 4, cy - 7)
        cone.lineTo(icon_x + 4, cy + 7)
        cone.lineTo(icon_x - 1, cy + 3)
        cone.lineTo(icon_x - 5, cy + 3)
        cone.closeSubpath()
        painter.drawPath(cone)

        if muted:
            pen = QPen(QColor(239, 68, 68), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(icon_x + 7, cy - 4), QPointF(icon_x + 13, cy + 4))
            painter.drawLine(QPointF(icon_x + 13, cy - 4), QPointF(icon_x + 7, cy + 4))
        else:
            pen = QPen(QColor(255, 255, 255, 210), 1.7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            if vol > 15:
                painter.drawArc(QRectF(icon_x + 2, cy - 5, 8, 10), -45 * 16, 90 * 16)
            if vol > 55:
                painter.drawArc(QRectF(icon_x + 4, cy - 8, 12, 16), -45 * 16, 90 * 16)

        bar_left = rect.left() + 46.0
        bar_right = rect.right() - 52.0
        bar_w = max(40.0, bar_right - bar_left)
        bar_h = 6.5
        bar_rect = QRectF(bar_left, cy - bar_h / 2.0, bar_w, bar_h)

        bg_path = QPainterPath()
        bg_path.addRoundedRect(bar_rect, 3.2, 3.2)
        painter.fillPath(bg_path, QColor(255, 255, 255, 38))

        if not muted and vol > 0:
            fill_w = max(6.5, bar_w * (vol / 100.0))
            fill_rect = QRectF(bar_left, cy - bar_h / 2.0, fill_w, bar_h)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill_rect, 3.2, 3.2)
            grad = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
            grad.setColorAt(0.0, QColor(r1, g1, b1))
            grad.setColorAt(1.0, QColor(r2, g2, b2))
            painter.fillPath(fill_path, grad)

        painter.setPen(QColor(239, 68, 68) if muted else QColor(240, 242, 248))
        font = QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold)
        painter.setFont(font)
        label = "MUTE" if muted else f"{vol}%"
        painter.drawText(
            QRectF(bar_right + 6.0, rect.top(), 42.0, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            label,
        )

    def _draw_alert_battery(self, painter: QPainter, rect: QRectF, now: float) -> None:
        cy = rect.center().y()
        batt = self.state.battery
        atype = batt.alert_type

        if atype == "charging":
            color = QColor(34, 197, 94)
            title = "Зарядка подключена"
        elif atype == "low_10":
            color = QColor(239, 68, 68)
            title = "Критический заряд"
        elif atype == "low_20":
            color = QColor(245, 158, 11)
            title = "Низкий заряд"
        else:
            color = QColor(148, 163, 184)
            title = "Работа от батареи"

        painter.setPen(QColor(245, 247, 250))
        font = QFont("Segoe UI Variable Display", 10, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(rect.left() + 18.0, rect.top(), 180.0, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            title,
        )

        badge_r = 14.0
        badge_center = QPointF(rect.right() - 24.0, cy)

        glow = QRadialGradient(badge_center, badge_r * 1.5)
        glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 130))
        glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(badge_center, badge_r * 1.5, badge_r * 1.5)

        painter.setBrush(color)
        painter.drawEllipse(badge_center, badge_r, badge_r)

        bolt = QPainterPath()
        bx, by = badge_center.x(), badge_center.y()
        bolt.moveTo(bx + 1.5, by - 7.0)
        bolt.lineTo(bx - 4.5, by + 0.8)
        bolt.lineTo(bx - 0.3, by + 0.8)
        bolt.lineTo(bx - 1.8, by + 7.0)
        bolt.lineTo(bx + 4.5, by - 0.8)
        bolt.lineTo(bx + 0.3, by - 0.8)
        bolt.closeSubpath()
        painter.fillPath(bolt, QColor(10, 12, 16))

        painter.setPen(color)
        font_pct = QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold)
        painter.setFont(font_pct)
        painter.drawText(
            QRectF(rect.right() - 95.0, rect.top(), 52.0, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            f"{batt.percent}%",
        )

    def _draw_expanded_media(self, painter: QPainter, rect: QRectF, now: float) -> None:
        r_acc, g_acc, b_acc = self.state.media.accent_color
        r_sec, g_sec, b_sec = self.state.media.secondary_color

        self._draw_top_nav_bar(painter, rect, "media")

        # Spinning Vinyl / Album Art with audio-reactive halo
        art_rect = QRectF(rect.left() + 18.0, rect.top() + 42.0, 56.0, 56.0)
        self._draw_album_art(painter, art_rect, radius=14.0, now=now)

        text_left = art_rect.right() + 14.0
        text_width = rect.right() - text_left - 84.0

        # Live status pill badge above title
        status_pill = QRectF(text_left, rect.top() + 41.0, 96.0, 15.0)
        sp_path = QPainterPath()
        sp_path.addRoundedRect(status_pill, 7.5, 7.5)
        if self.state.media.playing:
            painter.fillPath(sp_path, QColor(52, 211, 153, 45))
            painter.setPen(QColor(52, 211, 153))
            status_txt = "● В ЭФИРЕ"
        else:
            painter.fillPath(sp_path, QColor(255, 255, 255, 22))
            painter.setPen(QColor(165, 175, 195))
            status_txt = "⏸ НА ПАУЗЕ"
        painter.setFont(QFont("Segoe UI Variable Display", 7, QFont.Weight.Bold))
        painter.drawText(status_pill, Qt.AlignmentFlag.AlignCenter, status_txt)

        painter.setPen(QColor(255, 255, 255))
        title_font = QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold)
        painter.setFont(title_font)
        elided_title = painter.fontMetrics().elidedText(
            self.state.media.title, Qt.TextElideMode.ElideRight, int(text_width)
        )
        painter.drawText(
            QRectF(text_left, rect.top() + 57.0, text_width, 22.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_title,
        )

        painter.setPen(QColor(180, 190, 210))
        sub_font = QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold)
        painter.setFont(sub_font)
        elided_artist = painter.fontMetrics().elidedText(
            self.state.media.artist, Qt.TextElideMode.ElideRight, int(text_width)
        )
        painter.drawText(
            QRectF(text_left, rect.top() + 78.0, text_width, 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_artist,
        )

        self._draw_equalizer_wave(
            painter,
            right_x=rect.right() - 18.0,
            center_y=rect.top() + 70.0,
            max_height=28.0,
            bar_width=3.2,
            gap=2.5,
        )

        # Interactive Seek Progress Bar (supports click & drag)
        bar_y = rect.top() + 110.0
        time_font = QFont("Consolas", 8, QFont.Weight.Bold)
        painter.setFont(time_font)
        painter.setPen(QColor(175, 185, 205))

        pos_s = int(self.state.media.position)
        rem_s = max(0, int(self.state.media.duration - self.state.media.position))
        pos_str = f"{pos_s // 60}:{pos_s % 60:02d}"
        rem_str = f"-{rem_s // 60}:{rem_s % 60:02d}"

        painter.drawText(
            QRectF(rect.left() + 18.0, bar_y - 8.0, 38.0, 16.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            pos_str,
        )
        painter.drawText(
            QRectF(rect.right() - 60.0, bar_y - 8.0, 42.0, 16.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            rem_str,
        )

        slider_left = rect.left() + 58.0
        slider_right = rect.right() - 66.0
        slider_w = max(60.0, slider_right - slider_left)
        seek_hov = self._hovered_hitbox == "media_seek" or self._active_slider == "media_seek"
        bar_h = 7.0 if seek_hov else 5.5
        slider_rect = QRectF(slider_left, bar_y - bar_h / 2.0, slider_w, bar_h)
        self._hitboxes["media_seek"] = QRectF(slider_left - 4.0, bar_y - 10.0, slider_w + 8.0, 20.0)

        track_path = QPainterPath()
        track_path.addRoundedRect(slider_rect, bar_h / 2.0, bar_h / 2.0)
        painter.fillPath(track_path, QColor(255, 255, 255, 38))

        ratio = min(1.0, max(0.0, self.state.media.position / max(1.0, self.state.media.duration)))
        fill_rect = QRectF(slider_left, bar_y - bar_h / 2.0, max(bar_h, slider_w * ratio), bar_h)
        fill_path = QPainterPath()
        fill_path.addRoundedRect(fill_rect, bar_h / 2.0, bar_h / 2.0)
        seek_grad = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
        seek_grad.setColorAt(0.0, QColor(r_acc, g_acc, b_acc))
        seek_grad.setColorAt(1.0, QColor(255, 255, 255))
        painter.fillPath(fill_path, seek_grad)

        knob_x = slider_left + slider_w * ratio
        knob_r = 6.5 if seek_hov else 5.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(QPointF(knob_x, bar_y), knob_r, knob_r)

        # Direct 1-click Track Switcher Row (Смена музыки в 1 клик!)
        track_row_y = rect.top() + 128.0
        track_btns = [
            ("track_0", "🎵 1. Midnight"),
            ("track_1", "🎵 2. Neon Pulse"),
            ("track_2", "🎵 3. Solaris"),
            ("media_open_file", "📂 Свой MP3..."),
        ]
        tw = (rect.width() - 36.0 - 24.0) / 4.0
        for idx, (tkey, tlabel) in enumerate(track_btns):
            tx = rect.left() + 18.0 + idx * (tw + 8.0)
            tr = QRectF(tx, track_row_y, tw, 26.0)
            self._hitboxes[tkey] = tr
            is_cur = (tkey == f"track_{self.media_service._track_idx}" and not self.state.media.is_live_system_session)
            hov = self._hovered_hitbox == tkey
            tp = QPainterPath()
            tp.addRoundedRect(tr, 13.0, 13.0)
            if is_cur:
                t_grad = QLinearGradient(tr.topLeft(), tr.bottomRight())
                t_grad.setColorAt(0.0, QColor(r_acc, g_acc, b_acc, 230))
                t_grad.setColorAt(1.0, QColor(r_sec, g_sec, b_sec, 210))
                painter.fillPath(tp, t_grad)
                painter.setPen(QPen(QColor(255, 255, 255, 110), 1.0))
                painter.drawPath(tp)
                painter.setPen(QColor(255, 255, 255))
            else:
                painter.fillPath(tp, QColor(255, 255, 255, 50 if hov else 22))
                painter.setPen(QColor(240, 244, 252))
            painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
            painter.drawText(tr, Qt.AlignmentFlag.AlignCenter, tlabel)

        # Bottom Row: Transport Controls (Left/Center) + Interactive Live Volume Slider (Right)
        ctrl_y = rect.top() + 184.0

        prev_btn = QRectF(rect.left() + 18.0, ctrl_y - 16.0, 68.0, 32.0)
        play_btn = QRectF(rect.left() + 92.0, ctrl_y - 18.0, 102.0, 36.0)
        next_btn = QRectF(rect.left() + 200.0, ctrl_y - 16.0, 68.0, 32.0)
        self._hitboxes["media_prev"] = prev_btn
        self._hitboxes["media_play"] = play_btn
        self._hitboxes["media_next"] = next_btn

        for hkey, r_btn, lbl, primary in [
            ("media_prev", prev_btn, "⏮ Пред.", False),
            ("media_play", play_btn, "⏸ Пауза" if self.state.media.playing else "▶ Играть", True),
            ("media_next", next_btn, "След. ⏭", False),
        ]:
            hov = self._hovered_hitbox == hkey
            bp = QPainterPath()
            bp.addRoundedRect(r_btn, r_btn.height() / 2.0, r_btn.height() / 2.0)
            if primary:
                p_grad = QLinearGradient(r_btn.topLeft(), r_btn.bottomRight())
                p_grad.setColorAt(0.0, QColor(r_acc, g_acc, b_acc, 250 if hov else 225))
                p_grad.setColorAt(1.0, QColor(r_sec, g_sec, b_sec, 245 if hov else 215))
                painter.fillPath(bp, p_grad)
                painter.setPen(QPen(QColor(255, 255, 255, 110), 1.0))
                painter.drawPath(bp)
            else:
                painter.fillPath(bp, QColor(255, 255, 255, 58 if hov else 26))
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI Variable Text", 9 if primary else 8, QFont.Weight.Bold))
            painter.drawText(r_btn, Qt.AlignmentFlag.AlignCenter, lbl)

        # Inline Volume Control on bottom-right of Expanded Media
        vol = self.state.audio.volume_percent
        muted = self.state.audio.muted or vol == 0
        mute_btn = QRectF(rect.left() + 280.0, ctrl_y - 14.0, 28.0, 28.0)
        self._hitboxes["media_mute"] = mute_btn
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(239, 68, 68, 90) if muted else QColor(255, 255, 255, 45 if self._hovered_hitbox == "media_mute" else 22))
        painter.drawEllipse(mute_btn)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI Symbol", 8, QFont.Weight.Bold))
        painter.drawText(mute_btn, Qt.AlignmentFlag.AlignCenter, "🔇" if muted else "🔊")

        v_left = mute_btn.right() + 8.0
        v_right = rect.right() - 52.0
        v_w = max(48.0, v_right - v_left)
        v_hov = self._hovered_hitbox == "vol_seek" or self._active_slider == "vol_seek"
        v_h = 6.5 if v_hov else 5.0
        v_rect = QRectF(v_left, ctrl_y - v_h / 2.0, v_w, v_h)
        self._hitboxes["vol_seek"] = QRectF(v_left - 4.0, ctrl_y - 12.0, v_w + 8.0, 24.0)

        vp_bg = QPainterPath()
        vp_bg.addRoundedRect(v_rect, v_h / 2.0, v_h / 2.0)
        painter.fillPath(vp_bg, QColor(255, 255, 255, 36))

        if not muted and vol > 0:
            vf_w = max(v_h, v_w * (vol / 100.0))
            vf_rect = QRectF(v_left, ctrl_y - v_h / 2.0, vf_w, v_h)
            vp_fg = QPainterPath()
            vp_fg.addRoundedRect(vf_rect, v_h / 2.0, v_h / 2.0)
            painter.fillPath(vp_fg, QColor(56, 189, 248))

        vk_x = v_left + v_w * (0.0 if muted else (vol / 100.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(QPointF(vk_x, ctrl_y), 5.0 if v_hov else 4.0, 5.0 if v_hov else 4.0)

        painter.setPen(QColor(225, 232, 245))
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(v_right + 4.0, ctrl_y - 10.0, 36.0, 20.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "MUTE" if muted else f"{vol}%",
        )

    def _draw_expanded_timer(self, painter: QPainter, rect: QRectF, now: float) -> None:
        t_info = self.state.timer
        if t_info.is_pomodoro:
            accent_txt = QColor(251, 113, 133) if t_info.pomodoro_phase == "focus" else QColor(52, 211, 153)
            phase_lbl = "ФОКУС 25 МИН" if t_info.pomodoro_phase == "focus" else "ПЕРЕРЫВ 5 МИН"
            mode_title = f"🍅 ПОМОДОРО • СЕССИЯ #{t_info.pomodoro_cycle} ({phase_lbl})"
        else:
            accent_txt = QColor(251, 191, 36, 225)
            mode_title = "СЕКУНДОМЕР" if t_info.is_stopwatch else "ТАЙМЕР ОБРАТНОГО ОТСЧЕТА"

        self._draw_top_nav_bar(painter, rect, "timer")

        ring_center = QPointF(rect.left() + 54.0, rect.top() + 80.0)
        self._draw_timer_ring(painter, ring_center, 26.0)

        painter.setPen(accent_txt)
        painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.left() + 96.0, rect.top() + 46.0, 310.0, 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            mode_title,
        )

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 25, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.left() + 94.0, rect.top() + 64.0, 240.0, 44.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            t_info.display_text,
        )

        chips = [
            ("timer_toggle", "Пауза" if t_info.running else "Старт", True),
            ("timer_pomo_focus", "🍅 Фокус 25м", False),
            ("timer_pomo_break", "☕ Отдых 5м", False),
            ("timer_plus1", "+1 мин", False),
            ("timer_sw", "Секундомер", False),
            ("timer_stop", "Сброс", False),
        ]

        chip_y = rect.top() + 138.0
        x_cursor = rect.left() + 16.0
        for key, label, is_primary in chips:
            w = 62.0 if key in ("timer_toggle", "timer_plus1", "timer_stop") else 80.0
            c_rect = QRectF(x_cursor, chip_y, w, 34.0)
            self._hitboxes[key] = c_rect
            hov = self._hovered_hitbox == key

            c_path = QPainterPath()
            c_path.addRoundedRect(c_rect, 17.0, 17.0)
            if is_primary:
                bg = QColor(244, 63, 94, 240) if t_info.is_pomodoro else QColor(245, 158, 11, 240)
                fg = QColor(255, 255, 255) if t_info.is_pomodoro else QColor(12, 12, 14)
            else:
                bg = QColor(255, 255, 255, 52 if hov else 24)
                fg = QColor(240, 242, 248)

            painter.fillPath(c_path, bg)
            painter.setPen(fg)
            painter.setFont(QFont("Segoe UI Variable Text", 7, QFont.Weight.Bold))
            painter.drawText(c_rect, Qt.AlignmentFlag.AlignCenter, label)
            x_cursor += w + 6.0

    # ------------------------------------------------------------------
    # Shared Graphic Helpers (Spinning Vinyl Art & Gradient Spectrum Wave)
    # ------------------------------------------------------------------
    def _draw_album_art(
        self,
        painter: QPainter,
        rect: QRectF,
        radius: float,
        now: float = 0.0,
    ) -> None:
        painter.save()
        r1, g1, b1 = self.state.media.accent_color
        r2, g2, b2 = self.state.media.secondary_color

        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, QColor(r1, g1, b1))
        grad.setColorAt(1.0, QColor(r2, g2, b2))

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, grad)
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1.0))
        painter.drawPath(path)

        center = rect.center()
        disc_r = rect.width() * 0.34
        angle_deg = (now * 65.0) % 360.0 if self.state.media.playing else 35.0

        conical = QConicalGradient(center, angle_deg)
        conical.setColorAt(0.0, QColor(14, 16, 24, 230))
        conical.setColorAt(0.25, QColor(55, 65, 90, 210))
        conical.setColorAt(0.5, QColor(14, 16, 24, 230))
        conical.setColorAt(0.75, QColor(55, 65, 90, 210))
        conical.setColorAt(1.0, QColor(14, 16, 24, 230))

        painter.setPen(QPen(QColor(255, 255, 255, 85), 1.0))
        painter.setBrush(conical)
        painter.drawEllipse(center, disc_r, disc_r)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(r1, g1, b1))
        painter.drawEllipse(center, disc_r * 0.42, disc_r * 0.42)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(center, disc_r * 0.16, disc_r * 0.16)
        painter.restore()

    def _draw_equalizer_wave(
        self,
        painter: QPainter,
        right_x: float,
        center_y: float,
        max_height: float,
        bar_width: float,
        gap: float,
    ) -> None:
        bars = self.media_service.eq_bars
        r1, g1, b1 = self.state.media.accent_color
        r2, g2, b2 = self.state.media.secondary_color

        total_w = len(bars) * bar_width + (len(bars) - 1) * gap
        start_x = right_x - total_w

        for i, level in enumerate(bars):
            bh = max(bar_width, max_height * level)
            bx = start_x + i * (bar_width + gap)
            by = center_y - bh / 2.0
            b_rect = QRectF(bx, by, bar_width, bh)

            t = i / max(1, len(bars) - 1)
            cr = int(r1 * (1 - t) + r2 * t)
            cg = int(g1 * (1 - t) + g2 * t)
            cb = int(b1 * (1 - t) + b2 * t)

            b_path = QPainterPath()
            b_path.addRoundedRect(b_rect, bar_width / 2.0, bar_width / 2.0)
            painter.fillPath(b_path, QColor(cr, cg, cb))

    # ------------------------------------------------------------------
    # Drag-and-Drop (Drop Into Island + Drag Out From File Shelf)
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime is not None and (mime.hasUrls() or mime.hasText()):
            self.state.drop_zone.dragging_over = True
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.state.drop_zone.dragging_over = False
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self.state.drop_zone.dragging_over = False
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            urls = mime.urls()
            for u in urls:
                local_path = u.toLocalFile()
                if local_path:
                    self.pc_service.accept_dropped_file(self.state.drop_zone, local_path)
            if urls and urls[0].toLocalFile():
                self.state.expanded_target = "drop"
                event.acceptProposedAction()
                return
        event.ignore()

    def _start_file_drag(self, file_path: str) -> None:
        if not file_path or not os.path.exists(file_path):
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(file_path)])
        drag.setMimeData(mime)

        pix = QPixmap(150, 36)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QColor(15, 23, 42, 235))
        p.setPen(QColor(56, 189, 248))
        p.drawRoundedRect(2, 2, 146, 32, 10, 10)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
        fname = os.path.basename(file_path)
        elided = p.fontMetrics().elidedText(f"📎 {fname}", Qt.TextElideMode.ElideMiddle, 134)
        p.drawText(QRectF(8, 2, 134, 32), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        p.end()

        drag.setPixmap(pix)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)

    # ------------------------------------------------------------------
    # Mouse, Keyboard & Wheel Interaction
    # ------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.state.expanded_target is not None:
            self.state.expanded_target = None
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_terminal_submit(self) -> None:
        cmd = self.terminal_input.text()
        self.pc_service.execute_terminal_command(self.state.terminal, cmd)
        self.terminal_input.selectAll()

    def enterEvent(self, event) -> None:
        self.state.hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.state.hovered = False
        self._hovered_hitbox = None
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()

        # Live scrubbing if dragging media_seek or vol_seek slider
        if self._active_slider is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            rect = self._hitboxes.get(self._active_slider)
            if rect is not None:
                ratio = max(0.0, min(1.0, (pos.x() - rect.left()) / max(1.0, rect.width())))
                if self._active_slider == "media_seek":
                    self.media_service.seek(self.state.media, ratio)
                elif self._active_slider == "vol_seek":
                    new_vol = self.audio_service.set_volume(int(round(ratio * 100.0)))
                    self.state.audio.volume_percent = new_vol
                    self.state.audio.muted = new_vol == 0
                return

        if (
            self._drag_candidate_path is not None
            and self._drag_start_pos is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            dist = math.hypot(pos.x() - self._drag_start_pos.x(), pos.y() - self._drag_start_pos.y())
            if dist > 6.0:
                path_to_drag = self._drag_candidate_path
                self._drag_candidate_path = None
                self._drag_start_pos = None
                self._start_file_drag(path_to_drag)
                return

        hovered = None
        for name, rect in self._hitboxes.items():
            if rect.contains(pos):
                hovered = name
                break
        self._hovered_hitbox = hovered
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if (hovered or self._main_pill_rect.contains(pos) or self._split_circle_rect.contains(pos))
            else Qt.CursorShape.ArrowCursor
        )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._active_slider = None
        self._drag_candidate_path = None
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event) -> None:
        pos = event.position()

        if event.button() == Qt.MouseButton.RightButton:
            self.request_control_hub.emit()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        for name, rect in self._hitboxes.items():
            if rect.contains(pos):
                if name in ("media_seek", "vol_seek"):
                    self._active_slider = name
                if name.startswith("shelf_file_"):
                    idx = int(name.split("_")[-1])
                    if 0 <= idx < len(self.state.drop_zone.shelf_files):
                        fitem = self.state.drop_zone.shelf_files[idx]
                        self._drag_candidate_path = fitem.path
                        self._drag_start_pos = pos
                        self.pc_service.copy_file_to_windows_clipboard(fitem.path)
                        self.state.clipboard.copied_feedback_text = f"✅ Файл «{fitem.name}» скопирован (жмите Ctrl+V в любом окне!)"
                        self.state.clipboard.copied_feedback_until = time.monotonic() + 2.5
                    return
                self._handle_hitbox_click(name, pos, rect)
                return

        # Clicking the compact pill body expands the active card
        mode = self.state.resolve_mode()
        if mode in (IslandMode.COMPACT_MEDIA, IslandMode.SPLIT_MULTITASK):
            self.state.expanded_target = "media"
            self.physics.width.set_target(484.0, impulse=180.0)
        elif mode == IslandMode.COMPACT_TIMER:
            self.state.expanded_target = "timer"
            self.physics.width.set_target(484.0, impulse=180.0)
        elif mode == IslandMode.COMPACT_HARDWARE:
            self.state.expanded_target = "hardware"
            self.physics.width.set_target(484.0, impulse=180.0)
        elif mode == IslandMode.IDLE:
            self.state.expanded_target = "media"
            self.physics.width.set_target(484.0, impulse=180.0)
        elif mode == IslandMode.ALERT_CLIPBOARD:
            self.state.clipboard.alert_until = 0.0
            self.state.expanded_target = "shelf"
        elif mode == IslandMode.ALERT_DOWNLOAD:
            self.pc_service.stop_download(self.state.download)
        elif mode in (
            IslandMode.ALERT_VOLUME,
            IslandMode.ALERT_BATTERY,
            IslandMode.ALERT_NOTIFICATION,
        ):
            self.state.audio.volume_alert_until = 0.0
            self.state.battery.alert_until = 0.0
            self.state.notification.alert_until = 0.0

    def _handle_hitbox_click(self, name: str, pos: QPointF, rect: QRectF) -> None:
        nav_map = {
            "nav_glance": "glance",
            "nav_media": "media",
            "nav_timer": "timer",
            "nav_shelf": "shelf",
            "nav_hw": "hardware",
            "nav_term": "terminal",
        }
        if name in nav_map:
            self.state.expanded_target = nav_map[name]
            return
        if name == "cycle_theme":
            self.state.ux.cycle_theme()
            self.state_updated.emit()
            return
        if name == "open_hub":
            self.request_control_hub.emit()
            return
        if name in ("track_0", "track_1", "track_2"):
            t_idx = int(name.split("_")[-1])
            self.media_service.load_track(self.state.media, t_idx, auto_play=True)
            return
        if name == "cycle_weather":
            presets = [
                ("🌙", 16, 14, "Ясно"),
                ("☀️", 24, 25, "Солнечно"),
                ("🌧️", 11, 9, "Дождь"),
                ("❄️", -3, -7, "Снег"),
            ]
            cur = self.state.glance.weather_icon
            idx = next((i for i, p in enumerate(presets) if p[0] == cur), 0)
            nxt = presets[(idx + 1) % len(presets)]
            self.state.glance.weather_icon = nxt[0]
            self.state.glance.temperature_c = nxt[1]
            self.state.glance.feels_like_c = nxt[2]
            self.state.glance.condition = nxt[3]
            return

        if name == "split_timer":
            self.state.expanded_target = "timer"
        elif name == "collapse":
            self.state.expanded_target = None
        elif name == "media_play":
            self.media_service.toggle_play_pause(self.state.media)
        elif name == "media_next":
            self.media_service.next_track(self.state.media)
        elif name == "media_prev":
            self.media_service.prev_track(self.state.media)
        elif name == "media_mute":
            muted = self.audio_service.toggle_mute()
            self.state.audio.muted = muted
        elif name == "vol_seek":
            ratio = max(0.0, min(1.0, (pos.x() - rect.left()) / max(1.0, rect.width())))
            new_vol = self.audio_service.set_volume(int(round(ratio * 100.0)))
            self.state.audio.volume_percent = new_vol
            self.state.audio.muted = new_vol == 0
        elif name == "media_sys_play":
            self.media_service._send_media_key(0xB3)
        elif name == "media_open_file":
            fpath, _ = QFileDialog.getOpenFileName(
                self,
                "Выберите аудиофайл для Dynamic Island",
                str(os.path.expanduser("~")),
                "Аудиофайлы (*.mp3 *.wav *.flac *.ogg *.m4a);;Все файлы (*.*)",
            )
            if fpath:
                self.media_service.load_external_file(self.state.media, fpath)
        elif name == "media_seek":
            ratio = (pos.x() - rect.left()) / max(1.0, rect.width())
            self.media_service.seek(self.state.media, ratio)
        elif name == "timer_toggle":
            self.timer_service.toggle_pause(self.state.timer)
        elif name == "timer_pomo_focus":
            self.timer_service.start_pomodoro(self.state.timer, "focus")
        elif name == "timer_pomo_break":
            self.timer_service.start_pomodoro(self.state.timer, "break")
        elif name == "timer_plus1":
            self.timer_service.add_seconds(self.state.timer, 60.0)
        elif name == "timer_sw":
            self.timer_service.start_stopwatch(self.state.timer)
        elif name == "timer_stop":
            self.timer_service.dismiss(self.state.timer)
        elif name == "toggle_hw_hud":
            self.state.hardware.hud_enabled = not self.state.hardware.hud_enabled
        elif name == "drop_open_shelf":
            self.state.expanded_target = "shelf"
        elif name == "drop_copy_file":
            path = self.state.drop_zone.dropped_file_path
            if self.pc_service.copy_file_to_windows_clipboard(path):
                self.state.drop_zone.status_feedback = "✅ Сам файл в буфере обмена! Нажмите Ctrl+V в любом окне."
        elif name == "drop_copy_path":
            path = self.state.drop_zone.dropped_file_path
            if path:
                self.clipboard_service.copy_text_silently(path)
                self.state.drop_zone.status_feedback = f"✅ Скопирован путь: {path}"
        elif name == "drop_zip":
            self.pc_service.archive_dropped_file(self.state.drop_zone)
        elif name == "drop_trash":
            self.pc_service.send_to_recycle_bin(self.state.drop_zone)
        elif name == "shelf_add_file":
            fpaths, _ = QFileDialog.getOpenFileNames(
                self,
                "Добавить файлы на Полку Dynamic Island",
                str(os.path.expanduser("~")),
                "Все файлы (*.*)",
            )
            for fp in fpaths:
                if fp:
                    self.pc_service.add_to_shelf(self.state.drop_zone, fp)
        elif name == "shelf_clear":
            self.pc_service.clear_shelf(self.state.drop_zone)
        elif name.startswith("cb_hist_"):
            idx = int(name.split("_")[-1])
            self.clipboard_service.restore_history_item(idx)
        elif name == "term_run":
            self._on_terminal_submit()
        elif name in ("term_calc", "term_notepad", "term_explorer", "term_math", "term_ip"):
            mapping = {
                "term_calc": "calc",
                "term_notepad": "notepad",
                "term_explorer": "explorer",
                "term_math": "256*14",
                "term_ip": "whoami",
            }
            self.terminal_input.setText(mapping[name])
            self._on_terminal_submit()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta != 0:
            step = 4 if delta > 0 else -4
            new_vol = self.audio_service.change_volume_delta(step)
            self.state.audio.volume_percent = new_vol
            self.state.audio.muted = new_vol == 0
            if self.state.expanded_target is None:
                self.state.audio.volume_alert_until = time.monotonic() + 2.0
        event.accept()
