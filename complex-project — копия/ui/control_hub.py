"""
Ultra-Luxury Companion Control Hub & Settings Playground for Windows Dynamic Island Pro
(Acts 1, 2, 3, and 4 Pro).
"""

from __future__ import annotations
from pathlib import Path
import time
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.state import IslandState, THEMES
from services.audio_service import AudioService
from services.clipboard_service import ClipboardService
from services.hardware_service import HardwareService
from services.media_service import MediaService
from services.pc_features_service import PCFeaturesService
from services.power_service import PowerService
from services.timer_service import TimerService
from services.vibe_service import VibeService
from ui.island_window import DynamicIslandWindow


LUXURY_STYLESHEET = """
QDialog {
    background-color: #07090f;
    color: #f8fafc;
}
QFrame#heroBanner {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #15192b, stop:0.5 #1a1635, stop:1 #0f172a);
    border: 1px solid #2e3650;
    border-radius: 14px;
    padding: 10px;
}
QFrame#themeBar {
    background-color: #0e121c;
    border: 1px solid #1f273a;
    border-radius: 12px;
    padding: 6px;
}
QTabWidget::pane {
    border: 1px solid #1f293d;
    border-radius: 12px;
    background-color: #0c1018;
    padding: 10px;
}
QTabBar::tab {
    background-color: #131824;
    border: 1px solid #232c40;
    border-bottom: none;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    color: #94a3b8;
    padding: 8px 14px;
    margin-right: 4px;
    font-family: 'Segoe UI Variable Display';
    font-weight: bold;
}
QTabBar::tab:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #7c3aed, stop:1 #2563eb);
    color: #ffffff;
    border-color: #8b5cf6;
}
QLabel {
    color: #e2e8f0;
    font-family: 'Segoe UI Variable Text';
}
QCheckBox {
    color: #e2e8f0;
    font-family: 'Segoe UI Variable Text';
    font-weight: 600;
    spacing: 8px;
}
QGroupBox {
    background-color: #121723;
    border: 1px solid #232c3f;
    border-radius: 12px;
    margin-top: 8px;
    padding: 12px;
    font-family: 'Segoe UI Variable Display';
    font-weight: bold;
    color: #cbd5e1;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QPushButton {
    background-color: #1b2234;
    border: 1px solid #2f3b54;
    border-radius: 9px;
    color: #f8fafc;
    padding: 8px 12px;
    font-family: 'Segoe UI Variable Text';
    font-weight: 600;
}
QPushButton:hover {
    background-color: #27324b;
    border-color: #4f638c;
}
QPushButton:pressed {
    background-color: #141a29;
}
QPushButton#accentBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #7c3aed, stop:1 #4f46e5);
    border-color: #8b5cf6;
}
QPushButton#accentBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6d28d9, stop:1 #4338ca);
}
QPushButton#amberBtn {
    background-color: #d97706;
    border-color: #f59e0b;
}
QPushButton#amberBtn:hover {
    background-color: #b45309;
}
QPushButton#cyanBtn {
    background-color: #0284c7;
    border-color: #38bdf8;
}
QPushButton#cyanBtn:hover {
    background-color: #0369a1;
}
QPushButton#greenBtn {
    background-color: #059669;
    border-color: #10b981;
}
QPushButton#greenBtn:hover {
    background-color: #047857;
}
QPushButton#redBtn {
    background-color: #e11d48;
    border-color: #f43f5e;
}
QPushButton#redBtn:hover {
    background-color: #be123c;
}
"""


class ControlHubDialog(QDialog):
    """Luxury Control Center covering Act 1, Act 2, Act 3, and Act 4 Pro features."""

    def __init__(
        self,
        island: DynamicIslandWindow,
        state: IslandState,
        media_service: MediaService,
        timer_service: TimerService,
        audio_service: AudioService,
        power_service: PowerService,
        clipboard_service: ClipboardService,
        hardware_service: HardwareService,
        pc_service: PCFeaturesService,
        vibe_service: VibeService | None = None,
    ) -> None:
        super().__init__(None)
        self.island = island
        self.state = state
        self.media_service = media_service
        self.timer_service = timer_service
        self.audio_service = audio_service
        self.power_service = power_service
        self.clipboard_service = clipboard_service
        self.hardware_service = hardware_service
        self.pc_service = pc_service
        self.vibe_service = vibe_service or island.vibe_service
        self._mic_demo = False

        self.setWindowTitle("Windows Dynamic Island Pro — Центр управления (Luxury Edition)")
        self.setStyleSheet(LUXURY_STYLESHEET)
        self.setMinimumWidth(680)
        self._build_ui()
        self.island.state_updated.connect(self._sync_ux_checkboxes)

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(750)
        self._status_timer.timeout.connect(self._refresh_live_banner)
        self._status_timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # 1. Luxury Hero Banner with Live Status
        hero = QFrame(self)
        hero.setObjectName("heroBanner")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setSpacing(6)
        hero_layout.setContentsMargins(10, 8, 10, 8)

        title_row = QHBoxLayout()
        header = QLabel("🏝️ Windows Dynamic Island Pro — Liquid Glass & Aurora")
        header.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        title_row.addWidget(header)

        btn_collapse = QPushButton("🔽 Свернуть остров в пилюлю")
        btn_collapse.clicked.connect(lambda: setattr(self.state, "expanded_target", None))
        title_row.addWidget(btn_collapse)
        hero_layout.addLayout(title_row)

        self.live_status_label = QLabel("Загрузка телеметрии...")
        self.live_status_label.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11.5px;")
        hero_layout.addWidget(self.live_status_label)
        root.addWidget(hero)

        # 2. 1-Click Luxury Theme Switcher Bar
        theme_frame = QFrame(self)
        theme_frame.setObjectName("themeBar")
        t_bar = QHBoxLayout(theme_frame)
        t_bar.setSpacing(6)
        t_bar.setContentsMargins(8, 4, 8, 4)

        lbl_t = QLabel("🎨 Тема острова:")
        lbl_t.setStyleSheet("color: #cbd5e1; font-weight: bold; font-size: 11px;")
        t_bar.addWidget(lbl_t)

        for t_key, t_info in THEMES.items():
            b_theme = QPushButton(t_info["label"])
            b_theme.setStyleSheet("padding: 5px 8px; font-size: 11px;")
            b_theme.clicked.connect(lambda checked=False, k=t_key: self._set_theme(k))
            t_bar.addWidget(b_theme)

        root.addWidget(theme_frame)

        # 3. Main Feature Tabs
        tabs = QTabWidget(self)
        tabs.addTab(self._build_act5_vibe_tab(), "⚡ Вайбкодинг и Юзер-фичи")
        tabs.addTab(self._build_act1_tab(), "🎵 Музыка, Таймер и Звук")
        tabs.addTab(self._build_act4_tab(), "🔥 Pro: Полка, Помодоро, Погода")
        tabs.addTab(self._build_act2_tab(), "💻 Буфер, Железо и Терминал")
        tabs.addTab(self._build_act3_tab(), "⚙️ Позиция и Настройки")
        root.addWidget(tabs)
        self._refresh_live_banner()

    def _build_act5_vibe_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        vibe_group = QGroupBox("1. Для Вайбкодеров: Склейщик контекста ИИ, Радар портов + AI-промпты")
        v_layout = QGridLayout(vibe_group)

        btn_bundle = QPushButton("📦 Склеить файлы с Полки в Markdown для ИИ (Ctrl+V)")
        btn_bundle.setObjectName("accentBtn")
        btn_bundle.clicked.connect(
            lambda: (
                self.island.vibe_service.bundle_context_for_ai(
                    self.state.vibe,
                    self.state.drop_zone,
                    self.state.clipboard,
                    self.clipboard_service,
                ),
                setattr(self.state, "expanded_target", "vibe"),
            )
        )

        btn_demo_srv = QPushButton("🚀 Вкл/Выкл живой тест-сервер http://localhost:8080")
        btn_demo_srv.setObjectName("amberBtn")
        btn_demo_srv.clicked.connect(
            lambda: (
                self.island.vibe_service.toggle_demo_server(self.state.vibe),
                setattr(self.state, "expanded_target", "vibe"),
            )
        )

        btn_p0 = QPushButton("🤖 Промпт: ✨ Дизайн Шик")
        btn_p0.clicked.connect(
            lambda: (
                self.island.vibe_service.copy_prompt(self.state.vibe, 0, self.clipboard_service),
                setattr(self.state, "expanded_target", "vibe"),
            )
        )

        btn_p1 = QPushButton("🤖 Промпт: 🐛 Глубокий Фикс")
        btn_p1.clicked.connect(
            lambda: (
                self.island.vibe_service.copy_prompt(self.state.vibe, 1, self.clipboard_service),
                setattr(self.state, "expanded_target", "vibe"),
            )
        )

        v_layout.addWidget(btn_bundle, 0, 0)
        v_layout.addWidget(btn_demo_srv, 0, 1)
        v_layout.addWidget(btn_p0, 1, 0)
        v_layout.addWidget(btn_p1, 1, 1)
        layout.addWidget(vibe_group)

        user_group = QGroupBox("2. Переводчик буфера (RU⇄EN), Раскладка (ghbdtn→привет), Пипетка и Скрин")
        u_layout = QGridLayout(user_group)

        btn_translate = QPushButton("🌐 Перевести текст в буфере (RU ⇄ EN для Ctrl+V)")
        btn_translate.setObjectName("greenBtn")
        btn_translate.clicked.connect(lambda: self.clipboard_service.translate_clipboard_text())

        btn_layout_fix = QPushButton("⌨️ Исправить раскладку (ghbdtn ⇄ привет для Ctrl+V)")
        btn_layout_fix.setObjectName("cyanBtn")
        btn_layout_fix.clicked.connect(lambda: self.clipboard_service.fix_clipboard_layout())

        btn_eyedrop = QPushButton("💧 Живая Пипетка экрана (3.5 сек)")
        btn_eyedrop.clicked.connect(
            lambda: (
                setattr(self.state, "expanded_target", None),
                self.island.vibe_service.start_eyedropper(self.state.vibe, 3.5),
            )
        )

        btn_shot = QPushButton("📸 Мгновенный Скриншот в буфер и на Полку")
        btn_shot.clicked.connect(
            lambda: (
                self.island.vibe_service.capture_screen_to_shelf_and_clipboard(
                    self.state.vibe,
                    self.state.drop_zone,
                    self.state.clipboard,
                    self.pc_service,
                ),
                setattr(self.state, "expanded_target", "shelf"),
            )
        )

        u_layout.addWidget(btn_translate, 0, 0)
        u_layout.addWidget(btn_layout_fix, 0, 1)
        u_layout.addWidget(btn_eyedrop, 1, 0)
        u_layout.addWidget(btn_shot, 1, 1)
        layout.addWidget(user_group)

        pet_group = QGroupBox("3. 🐾 Мини-питомец на острове (Tamagotchi) и 🚀 Быстрый док приложений")
        p_layout = QGridLayout(pet_group)

        btn_pet_love = QPushButton("🐾 Погладить / Покормить питомца (+20 XP ♥)")
        btn_pet_love.setObjectName("accentBtn")
        btn_pet_love.clicked.connect(
            lambda: self.island.vibe_service.pet_interact(self.state.pet, self.state.vibe, cycle=False)
        )

        btn_pet_cycle = QPushButton("🐱/🤖/🦊 Сменить питомца (Кибер-Кот / Нано-Бот / Огненный Лис)")
        btn_pet_cycle.setObjectName("amberBtn")
        btn_pet_cycle.clicked.connect(
            lambda: self.island.vibe_service.pet_interact(self.state.pet, self.state.vibe, cycle=True)
        )

        btn_yt = QPushButton("▶ YouTube")
        btn_yt.clicked.connect(lambda: self.island.vibe_service.launch_quick_app("youtube", self.state.vibe))

        btn_tg = QPushButton("✈️ Telegram")
        btn_tg.clicked.connect(lambda: self.island.vibe_service.launch_quick_app("telegram", self.state.vibe))

        btn_ai = QPushButton("🤖 ChatGPT")
        btn_ai.clicked.connect(lambda: self.island.vibe_service.launch_quick_app("ai_chat", self.state.vibe))

        btn_dl = QPushButton("📂 Папка Загрузки")
        btn_dl.clicked.connect(lambda: self.island.vibe_service.launch_quick_app("downloads", self.state.vibe))

        p_layout.addWidget(btn_pet_love, 0, 0, 1, 2)
        p_layout.addWidget(btn_pet_cycle, 0, 2, 1, 2)
        p_layout.addWidget(btn_yt, 1, 0)
        p_layout.addWidget(btn_tg, 1, 1)
        p_layout.addWidget(btn_ai, 1, 2)
        p_layout.addWidget(btn_dl, 1, 3)
        layout.addWidget(pet_group)

        return page

    def _refresh_live_banner(self) -> None:
        if not self.isVisible():
            return
        try:
            m = self.state.media
            play_state = "▶ ИГРАЕТ" if m.playing else "⏸ ПАУЗА"
            vol = self.state.audio.volume_percent
            hw = self.state.hardware
            pet = self.state.pet
            self.live_status_label.setText(
                f"{play_state}: {m.title}  •  🔊 {vol}%  •  ⚡ CPU: {int(hw.cpu_percent)}%  •  📡 ↓{hw.net_down_str} ({hw.ping_ms}мс)  •  🐾 {pet.name} Ур.{pet.level}"
            )
        except Exception:
            pass

    def _set_theme(self, theme_key: str) -> None:
        self.state.ux.theme_name = theme_key
        self._refresh_live_banner()

    def _build_act1_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        media_group = QGroupBox("1. Spotify + Управление музыкой (Обложка, переключение треков и свой MP3)")
        m_layout = QGridLayout(media_group)
        btn_prev = QPushButton("⏮ Предыдущий трек")
        btn_prev.clicked.connect(lambda: self.media_service.prev_track(self.state.media))

        btn_play = QPushButton("▶ / ⏸ Играть / Пауза")
        btn_play.setObjectName("accentBtn")
        btn_play.clicked.connect(self._on_toggle_media)

        btn_next = QPushButton("Следующий трек ⏭")
        btn_next.clicked.connect(lambda: self.media_service.next_track(self.state.media))

        btn_spotify = QPushButton("🟢 Подключить / Открыть Spotify")
        btn_spotify.setObjectName("greenBtn")
        btn_spotify.clicked.connect(
            lambda: (
                self.media_service.open_or_focus_spotify(self.state.media),
                setattr(self.state, "expanded_target", "media"),
            )
        )

        btn_t1 = QPushButton("🎵 1. Midnight Synth")
        btn_t1.clicked.connect(lambda: self.media_service.load_track(self.state.media, 0, auto_play=True))

        btn_t2 = QPushButton("🎵 2. Neon Pulse")
        btn_t2.clicked.connect(lambda: self.media_service.load_track(self.state.media, 1, auto_play=True))

        btn_open_mp3 = QPushButton("📂 Выбрать свой MP3 / WAV с компьютера...")
        btn_open_mp3.setObjectName("cyanBtn")
        btn_open_mp3.clicked.connect(self._on_pick_audio_file)

        btn_expand_m = QPushButton("🔍 Развернуть плеер в острове")
        btn_expand_m.clicked.connect(self._on_expand_media)

        m_layout.addWidget(btn_prev, 0, 0)
        m_layout.addWidget(btn_play, 0, 1)
        m_layout.addWidget(btn_next, 0, 2)
        m_layout.addWidget(btn_spotify, 1, 0)
        m_layout.addWidget(btn_t1, 1, 1)
        m_layout.addWidget(btn_t2, 1, 2)
        m_layout.addWidget(btn_open_mp3, 2, 0, 1, 2)
        m_layout.addWidget(btn_expand_m, 2, 2)
        layout.addWidget(media_group)

        timer_group = QGroupBox("2. Таймер, Секундомер и Многозадачность (Двойной остров)")
        t_layout = QGridLayout(timer_group)

        btn_split = QPushButton("✨ Двойной остров (Музыка + Таймер)")
        btn_split.setObjectName("amberBtn")
        btn_split.clicked.connect(self._on_activate_split)

        btn_timer = QPushButton("⏱ Таймер 5 мин")
        btn_timer.clicked.connect(self._on_start_timer)

        btn_sw = QPushButton("⏱ Секундомер")
        btn_sw.clicked.connect(self._on_start_stopwatch)

        btn_stop_t = QPushButton("✕ Выключить таймер")
        btn_stop_t.clicked.connect(self._on_stop_timer)

        t_layout.addWidget(btn_split, 0, 0, 1, 2)
        t_layout.addWidget(btn_timer, 1, 0)
        t_layout.addWidget(btn_sw, 1, 1)
        t_layout.addWidget(btn_stop_t, 0, 2, 2, 1)
        layout.addWidget(timer_group)

        batt_group = QGroupBox("3. Батарея и Питание")
        b_layout = QGridLayout(batt_group)

        btn_charge = QPushButton("⚡ Подключить зарядку (78%)")
        btn_charge.setObjectName("greenBtn")
        btn_charge.clicked.connect(lambda: self._trigger_battery("charging", 78))

        btn_unplug = QPushButton("🔋 Отключить зарядку")
        btn_unplug.clicked.connect(lambda: self._trigger_battery("unplugged", 77))

        btn_low20 = QPushButton("⚠️ Низкий заряд (<20%)")
        btn_low20.clicked.connect(lambda: self._trigger_battery("low_20", 19))

        btn_low10 = QPushButton("🚨 Критический заряд (<10%)")
        btn_low10.setObjectName("redBtn")
        btn_low10.clicked.connect(lambda: self._trigger_battery("low_10", 9))

        b_layout.addWidget(btn_charge, 0, 0)
        b_layout.addWidget(btn_unplug, 0, 1)
        b_layout.addWidget(btn_low20, 1, 0)
        b_layout.addWidget(btn_low10, 1, 1)
        layout.addWidget(batt_group)

        audio_group = QGroupBox("4. Управление системным звуком Windows и Микрофон")
        a_layout = QGridLayout(audio_group)

        btn_vol_up = QPushButton("🔊 Громкость +6%")
        btn_vol_up.clicked.connect(lambda: self._change_vol(6))

        btn_vol_down = QPushButton("🔉 Громкость -6%")
        btn_vol_down.clicked.connect(lambda: self._change_vol(-6))

        btn_mute = QPushButton("🔇 Mute / Unmute")
        btn_mute.clicked.connect(self._toggle_mute)

        self.btn_mic = QPushButton("🎙 Точка микрофона: АВТО")
        self.btn_mic.clicked.connect(self._toggle_mic_demo)

        a_layout.addWidget(btn_vol_up, 0, 0)
        a_layout.addWidget(btn_vol_down, 0, 1)
        a_layout.addWidget(btn_mute, 1, 0)
        a_layout.addWidget(self.btn_mic, 1, 1)
        layout.addWidget(audio_group)

        return page

    def _build_act4_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        shelf_group = QGroupBox("1. Полка файлов (Копирование файла Ctrl+V и Drag-Out) + История буфера (5)")
        s_layout = QGridLayout(shelf_group)

        btn_open_shelf = QPushButton("📎 Открыть Полку и Историю буфера в острове")
        btn_open_shelf.setObjectName("cyanBtn")
        btn_open_shelf.clicked.connect(lambda: setattr(self.state, "expanded_target", "shelf"))

        btn_add_files = QPushButton("➕ Выбрать свои файлы для Полки...")
        btn_add_files.clicked.connect(self._on_pick_shelf_files)

        btn_clear_shelf = QPushButton("🗑️ Очистить полку")
        btn_clear_shelf.clicked.connect(lambda: self.pc_service.clear_shelf(self.state.drop_zone))

        s_layout.addWidget(btn_open_shelf, 0, 0, 1, 2)
        s_layout.addWidget(btn_add_files, 1, 0)
        s_layout.addWidget(btn_clear_shelf, 1, 1)
        layout.addWidget(shelf_group)

        pomo_group = QGroupBox("2. Помодоро-фокус (Циклы 25 мин Фокус / 5 мин Перерыв)")
        p_layout = QGridLayout(pomo_group)

        btn_pomo_focus = QPushButton("🍅 Запустить Помодоро Фокус (25 мин)")
        btn_pomo_focus.setObjectName("redBtn")
        btn_pomo_focus.clicked.connect(self._on_start_pomodoro_focus)

        btn_pomo_break = QPushButton("☕ Запустить Перерыв (5 мин)")
        btn_pomo_break.setObjectName("greenBtn")
        btn_pomo_break.clicked.connect(self._on_start_pomodoro_break)

        btn_pomo_card = QPushButton("🔍 Открыть карточку Таймера/Помодоро")
        btn_pomo_card.clicked.connect(self._on_open_pomodoro_card)

        btn_pomo_split = QPushButton("✨ Двойной остров: Музыка + Помодоро")
        btn_pomo_split.setObjectName("amberBtn")
        btn_pomo_split.clicked.connect(self._on_split_pomodoro)

        p_layout.addWidget(btn_pomo_focus, 0, 0)
        p_layout.addWidget(btn_pomo_break, 0, 1)
        p_layout.addWidget(btn_pomo_card, 1, 0)
        p_layout.addWidget(btn_pomo_split, 1, 1)
        layout.addWidget(pomo_group)

        glance_group = QGroupBox("3. Умный виджет часов и погоды (Smart Glance)")
        g_layout = QGridLayout(glance_group)

        btn_open_glance = QPushButton("🏠 Открыть Главный Обзор в острове")
        btn_open_glance.setObjectName("accentBtn")
        btn_open_glance.clicked.connect(lambda: setattr(self.state, "expanded_target", "glance"))

        btn_idle_glance = QPushButton("🕒 Свернуть остров в виджет Часов и Погоды")
        btn_idle_glance.clicked.connect(self._on_show_compact_glance)

        btn_weather_cycle = QPushButton("🌤️ Сменить погоду (Ясно / Дождь / Снег)")
        btn_weather_cycle.clicked.connect(self._on_cycle_weather)

        g_layout.addWidget(btn_open_glance, 0, 0, 1, 2)
        g_layout.addWidget(btn_idle_glance, 1, 0)
        g_layout.addWidget(btn_weather_cycle, 1, 1)
        layout.addWidget(glance_group)

        return page

    def _build_act2_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        cb_group = QGroupBox("1. Умный буфер обмена (Работает на реальный Ctrl+C + Быстрые тесты)")
        cb_layout = QGridLayout(cb_group)

        btn_cb_text = QPushButton("📋 Тест: Скопировать текст")
        btn_cb_text.clicked.connect(
            lambda: (
                setattr(self.state, "expanded_target", None),
                self.clipboard_service.process_copied_text(
                    "Привет! Это превью умного буфера обмена Dynamic Island на Windows."
                ),
            )
        )

        btn_cb_hex = QPushButton("🎨 Тест: Цвет #38BDF8")
        btn_cb_hex.setObjectName("cyanBtn")
        btn_cb_hex.clicked.connect(
            lambda: (
                setattr(self.state, "expanded_target", None),
                self.clipboard_service.process_copied_text("#38BDF8"),
            )
        )

        btn_cb_img = QPushButton("🖼️ Тест: Скопирована картинка")
        btn_cb_img.clicked.connect(
            lambda: (
                setattr(self.state, "expanded_target", None),
                self.clipboard_service.trigger_demo_image(),
            )
        )

        cb_layout.addWidget(btn_cb_text, 0, 0)
        cb_layout.addWidget(btn_cb_hex, 0, 1)
        cb_layout.addWidget(btn_cb_img, 0, 2)
        layout.addWidget(cb_group)

        hw_group = QGroupBox("2. Загрузки файлов и Мониторинг железа (HUD для гиков)")
        hw_layout = QGridLayout(hw_group)

        btn_dl = QPushButton("📥 Симуляция скачивания (5 сек)")
        btn_dl.setObjectName("cyanBtn")
        btn_dl.clicked.connect(
            lambda: (
                setattr(self.state, "expanded_target", None),
                self.pc_service.start_download_demo(self.state.download),
            )
        )

        btn_hw_card = QPushButton("📊 Открыть карточку CPU / GPU / RAM")
        btn_hw_card.setObjectName("accentBtn")
        btn_hw_card.clicked.connect(lambda: setattr(self.state, "expanded_target", "hardware"))

        btn_hw_pin = QPushButton("📌 Переключить компактный Geek HUD")
        btn_hw_pin.clicked.connect(self._toggle_compact_hw)

        hw_layout.addWidget(btn_dl, 0, 0)
        hw_layout.addWidget(btn_hw_card, 0, 1)
        hw_layout.addWidget(btn_hw_pin, 1, 0, 1, 2)
        layout.addWidget(hw_group)

        dt_group = QGroupBox("3. Зона сброса (Drag-and-Drop) и Быстрый терминал")
        dt_layout = QGridLayout(dt_group)

        btn_term = QPushButton("❯ Открыть Быстрый Терминал (Ctrl+Shift+Space)")
        btn_term.setObjectName("accentBtn")
        btn_term.clicked.connect(self.island.toggle_quick_terminal)

        btn_drop = QPushButton("📁 Открыть Зону сброса с тестовым файлом")
        btn_drop.clicked.connect(self._demo_drop_zone)

        dt_layout.addWidget(btn_term, 0, 0)
        dt_layout.addWidget(btn_drop, 1, 0)
        layout.addWidget(dt_group)

        nf_group = QGroupBox("4. Входящие уведомления")
        nf_layout = QGridLayout(nf_group)

        btn_tg = QPushButton("✈️ Telegram")
        btn_tg.setObjectName("cyanBtn")
        btn_tg.clicked.connect(
            lambda: self._trigger_notif(
                "Telegram",
                "Дмитрий • DevChat",
                "Зацени новый дизайн Liquid Glass в Dynamic Island! 🚀",
            )
        )

        btn_ds = QPushButton("🎮 Discord")
        btn_ds.setObjectName("accentBtn")
        btn_ds.clicked.connect(
            lambda: self._trigger_notif(
                "Discord",
                "Голосовой канал #gaming",
                "Макс подключился к стриму экрана (1080p 60fps)",
            )
        )

        btn_mail = QPushButton("✉️ Почта")
        btn_mail.setObjectName("amberBtn")
        btn_mail.clicked.connect(
            lambda: self._trigger_notif(
                "Почта",
                "GitHub Release Bot",
                "Финальная сборка Dynamic Island Pro успешно запущена.",
            )
        )

        nf_layout.addWidget(btn_tg, 0, 0)
        nf_layout.addWidget(btn_ds, 0, 1)
        nf_layout.addWidget(btn_mail, 0, 2)
        layout.addWidget(nf_group)

        return page

    def _build_act3_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        ux_group = QGroupBox("1. Режимы поведения (Smart Hide и Пропуск кликов мыши)")
        ux_layout = QVBoxLayout(ux_group)

        self.chk_smart_hide = QCheckBox(
            "🎬 Авто-скрытие в полноэкранных играх (только эксклюзивный полный экран)"
        )
        self.chk_smart_hide.setChecked(self.state.ux.smart_hide_fullscreen)
        self.chk_smart_hide.toggled.connect(
            lambda v: setattr(self.state.ux, "smart_hide_fullscreen", bool(v))
        )

        self.chk_click_through = QCheckBox(
            "👻 Режим пропуска мыши (Click-through — клики проходят сквозь остров, хоткей Ctrl+Alt+X)"
        )
        self.chk_click_through.setChecked(self.state.ux.click_through_mode)
        self.chk_click_through.toggled.connect(
            lambda v: setattr(self.state.ux, "click_through_mode", bool(v))
        )

        self.chk_hold_mod = QCheckBox(
            "⌨️ Временный пропуск кликов при зажатии клавиш Ctrl + Alt"
        )
        self.chk_hold_mod.setChecked(self.state.ux.hold_modifier_passthrough)
        self.chk_hold_mod.toggled.connect(
            lambda v: setattr(self.state.ux, "hold_modifier_passthrough", bool(v))
        )

        ux_layout.addWidget(self.chk_smart_hide)
        ux_layout.addWidget(self.chk_click_through)
        ux_layout.addWidget(self.chk_hold_mod)
        layout.addWidget(ux_group)

        pos_group = QGroupBox("2. Кастомизация расположения и Мониторы")
        pos_layout = QGridLayout(pos_group)

        btn_float = QPushButton("☁️ Парение сверху (Floating)")
        btn_float.clicked.connect(lambda: self._set_pos_mode("floating_top"))

        btn_dock = QPushButton("🧲 Прилипание к верхнему краю")
        btn_dock.clicked.connect(lambda: self._set_pos_mode("docked_top"))

        btn_bottom = QPushButton("⬇️ Внизу над таскбаром")
        btn_bottom.clicked.connect(lambda: self._set_pos_mode("bottom_taskbar"))

        pos_layout.addWidget(btn_float, 0, 0)
        pos_layout.addWidget(btn_dock, 0, 1)
        pos_layout.addWidget(btn_bottom, 0, 2)

        screens = QGuiApplication.screens()
        for idx in range(max(1, min(3, len(screens)))):
            g = screens[idx].geometry()
            btn_mon = QPushButton(f"🖥️ Монитор {idx + 1} ({g.width()}×{g.height()})")
            btn_mon.clicked.connect(lambda checked=False, m=idx: self._set_monitor(m))
            pos_layout.addWidget(btn_mon, 1, idx)

        layout.addWidget(pos_group)

        phys_group = QGroupBox("3. Физика анимаций (Spring Physics с отскоком)")
        p_layout = QGridLayout(phys_group)

        presets = [
            ("🏀 Упругая (Apple Spring)", "bouncy"),
            ("⚡ Быстрая (Snappy)", "snappy"),
            ("🌊 Мягкая (Gentle)", "gentle"),
            ("🍮 Желе (Extra Bounce)", "jelly"),
        ]
        for i, (label, preset) in enumerate(presets):
            b = QPushButton(label)
            b.clicked.connect(lambda checked=False, pr=preset: self._set_spring_preset(pr))
            p_layout.addWidget(b, i // 2, i % 2)

        layout.addWidget(phys_group)
        return page

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _on_pick_shelf_files(self) -> None:
        fpaths, _ = QFileDialog.getOpenFileNames(
            self,
            "Выберите файлы для добавления на Полку Dynamic Island",
            str(Path.home()),
            "Все файлы (*.*)",
        )
        for fp in fpaths:
            if fp:
                self.pc_service.add_to_shelf(self.state.drop_zone, fp)
        self.state.expanded_target = "shelf"

    def _on_pick_audio_file(self) -> None:
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите аудиофайл (MP3, WAV, FLAC, OGG)",
            str(Path.home()),
            "Аудиофайлы (*.mp3 *.wav *.flac *.ogg *.m4a);;Все файлы (*.*)",
        )
        if fpath:
            self.media_service.load_external_file(self.state.media, fpath)
            self.state.expanded_target = "media"

    def _on_start_pomodoro_focus(self) -> None:
        self.state.expanded_target = None
        self.timer_service.start_pomodoro(self.state.timer, "focus")

    def _on_start_pomodoro_break(self) -> None:
        self.state.expanded_target = None
        self.timer_service.start_pomodoro(self.state.timer, "break")

    def _on_open_pomodoro_card(self) -> None:
        if not self.state.timer.active or not self.state.timer.is_pomodoro:
            self.timer_service.start_pomodoro(self.state.timer, "focus")
        self.state.expanded_target = "timer"

    def _on_split_pomodoro(self) -> None:
        self.state.expanded_target = None
        self.media_service.load_track(self.state.media, 0, auto_play=True)
        self.timer_service.start_pomodoro(self.state.timer, "focus")

    def _on_show_compact_glance(self) -> None:
        self.state.expanded_target = None
        self.media_service.stop_playback(self.state.media)
        self.state.timer.active = False
        self.state.hardware.hud_enabled = False
        self.state.glance.enabled_in_idle = True

    def _on_cycle_weather(self) -> None:
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

    def _sync_ux_checkboxes(self) -> None:
        self.chk_click_through.blockSignals(True)
        self.chk_click_through.setChecked(self.state.ux.click_through_mode)
        self.chk_click_through.blockSignals(False)

    def _on_toggle_media(self) -> None:
        self.media_service.toggle_play_pause(self.state.media)

    def _on_expand_media(self) -> None:
        self.state.expanded_target = "media"

    def _on_activate_split(self) -> None:
        self.state.expanded_target = None
        self.media_service.load_track(self.state.media, 0, auto_play=True)
        if not self.state.timer.active:
            self.timer_service.start_countdown(self.state.timer, 300.0)
        else:
            self.state.timer.running = True

    def _on_start_timer(self) -> None:
        self.state.expanded_target = None
        self.timer_service.start_countdown(self.state.timer, 300.0)

    def _on_start_stopwatch(self) -> None:
        self.state.expanded_target = None
        self.timer_service.start_stopwatch(self.state.timer)

    def _on_stop_timer(self) -> None:
        if self.state.expanded_target == "timer":
            self.state.expanded_target = None
        self.timer_service.dismiss(self.state.timer)

    def _trigger_battery(self, event_type: str, pct: int) -> None:
        self.state.expanded_target = None
        self.power_service.trigger_simulated_event(self.state.battery, event_type, pct)

    def _change_vol(self, delta: int) -> None:
        self.state.expanded_target = None
        vol = self.audio_service.change_volume_delta(delta)
        self.state.audio.volume_percent = vol
        self.state.audio.muted = vol == 0
        self.state.audio.volume_alert_until = time.monotonic() + 2.0

    def _toggle_mute(self) -> None:
        self.state.expanded_target = None
        muted = self.audio_service.toggle_mute()
        self.state.audio.muted = muted
        self.state.audio.volume_alert_until = time.monotonic() + 2.0

    def _toggle_mic_demo(self) -> None:
        self._mic_demo = not self._mic_demo
        self.audio_service.set_simulated_mic(self._mic_demo)
        self.btn_mic.setText(
            "🟠 Точка микрофона: ВКЛ (Демо)" if self._mic_demo else "🎙 Точка микрофона: АВТО"
        )

    def _toggle_compact_hw(self) -> None:
        self.state.expanded_target = None
        self.state.hardware.hud_enabled = not self.state.hardware.hud_enabled
        if self.state.hardware.hud_enabled:
            self.media_service.stop_playback(self.state.media)

    def _demo_drop_zone(self) -> None:
        demo_file = Path(__file__).resolve().parent.parent / "assets" / "demo_drop_file.txt"
        demo_file.parent.mkdir(parents=True, exist_ok=True)
        if not demo_file.exists():
            demo_file.write_text("Тестовый файл для Зоны сброса Windows Dynamic Island.\n", encoding="utf-8")
        self.pc_service.accept_dropped_file(self.state.drop_zone, str(demo_file))
        self.state.expanded_target = "drop"

    def _trigger_notif(self, app_name: str, sender: str, msg: str) -> None:
        self.state.expanded_target = None
        self.pc_service.trigger_notification(self.state.notification, app_name, sender, msg)

    def _set_pos_mode(self, mode: str) -> None:
        self.state.ux.position_mode = mode
        self.island.apply_screen_positioning()

    def _set_monitor(self, idx: int) -> None:
        self.state.ux.monitor_index = idx
        self.island.apply_screen_positioning()

    def _set_spring_preset(self, preset: str) -> None:
        self.state.ux.spring_preset = preset
        self.island.physics.set_preset(preset)
        self.island.physics.width.velocity += 220.0
