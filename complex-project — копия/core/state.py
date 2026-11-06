"""
Complete State & Mode definitions for Windows Dynamic Island (Acts 1, 2, 3, and 4 Pro).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any


class IslandMode(Enum):
    # Act 1 modes
    IDLE = "idle"                        # Minimal pill or Smart Glance (Clock + Weather + Shelf badge)
    COMPACT_MEDIA = "compact_media"      # Mini cover art left + equalizer right
    COMPACT_TIMER = "compact_timer"      # Timer / Pomodoro icon left + countdown right
    SPLIT_MULTITASK = "split_multitask"  # Main pill (Media/HUD) + Right circle (Timer/Pomodoro)
    ALERT_VOLUME = "alert_volume"        # 2-second volume bar expansion
    ALERT_BATTERY = "alert_battery"      # Charger connected/disconnected or Low Battery
    EXPANDED_MEDIA = "expanded_media"    # Full player card with controls & progress
    EXPANDED_TIMER = "expanded_timer"    # Full timer / stopwatch / Pomodoro Focus controls

    # Act 2 PC-specific modes
    ALERT_CLIPBOARD = "alert_clipboard"       # Smart Clipboard (Text / Image thumbnail / HEX Color)
    ALERT_NOTIFICATION = "alert_notification" # Incoming Notification (Telegram, Discord, Mail)
    ALERT_DOWNLOAD = "alert_download"         # File Download / Copy circular progress
    COMPACT_HARDWARE = "compact_hardware"     # Geek HUD: CPU / GPU / RAM compact pill
    EXPANDED_HARDWARE = "expanded_hardware"   # Geek HUD: Full hardware telemetry card
    DROP_ZONE_HOVER = "drop_zone_hover"       # Dragging a file over the Island
    EXPANDED_DROP_ACTIONS = "expanded_drop"   # Dropped file quick actions + pin to File Shelf
    EXPANDED_TERMINAL = "expanded_terminal"   # Quick Run Prompt / Calculator / Terminal

    # Act 4 Pro modes
    EXPANDED_SHELF = "expanded_shelf"         # File Shelf (Drag-Out) + Clipboard History (Last 5 items)
    EXPANDED_GLANCE = "expanded_glance"       # Smart Glance Dashboard (Clock, Weather, Quick Switcher)

    # Act 5 Vibe Coder & Everyday Studio modes
    EXPANDED_VIBE = "expanded_vibe"           # Localhost Port Radar, AI Prompt Vault, Eyedropper & Screenshot
    ALERT_EYEDROPPER = "alert_eyedropper"     # Live 60 FPS Screen Pixel Color Picker magnifier pill


@dataclass
class MediaInfo:
    playing: bool = False
    title: str = "Midnight City"
    artist: str = "M83 • Hurry Up, We're Dreaming"
    duration: float = 243.0
    position: float = 64.0
    accent_color: tuple[int, int, int] = (192, 132, 252)
    secondary_color: tuple[int, int, int] = (59, 130, 246)
    is_live_system_session: bool = False
    is_spotify: bool = False
    source_app: str = ""
    album_qimage: Any = None
    can_seek: bool = True
    audio_peak: float = 0.0


@dataclass
class TimerInfo:
    active: bool = False
    running: bool = False
    is_stopwatch: bool = False
    is_pomodoro: bool = False
    pomodoro_phase: str = "focus"  # "focus" (25m) or "break" (5m)
    pomodoro_cycle: int = 1
    total_seconds: float = 300.0
    remaining_seconds: float = 300.0
    elapsed_seconds: float = 0.0
    finished_flashUntil: float = 0.0

    @property
    def display_text(self) -> str:
        secs = int(self.elapsed_seconds if self.is_stopwatch else max(0.0, self.remaining_seconds))
        minutes, seconds = divmod(secs, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def progress(self) -> float:
        if self.is_stopwatch:
            return (self.elapsed_seconds % 60.0) / 60.0
        if self.total_seconds <= 0:
            return 0.0
        return max(0.0, min(1.0, self.remaining_seconds / self.total_seconds))


@dataclass
class BatteryInfo:
    percent: int = 100
    plugged: bool = True
    has_battery: bool = True
    alert_type: str = "charging"  # "charging", "unplugged", "low_20", "low_10"
    alert_until: float = 0.0


@dataclass
class AudioPrivacyInfo:
    volume_percent: int = 65
    muted: bool = False
    volume_alert_until: float = 0.0
    mic_active: bool = False
    mic_app_name: str = ""


# --- Act 2 & Act 4 Data Models ---

@dataclass
class ClipboardHistoryItem:
    kind: str  # "text" or "color"
    raw_value: str
    display_label: str
    rgb_tuple: tuple[int, int, int] = (168, 85, 247)
    timestamp_str: str = ""


@dataclass
class ClipboardAlertInfo:
    kind: str = "text"  # "text", "color", "image"
    preview_text: str = ""
    char_count: int = 0
    hex_color: str = "#38BDF8"
    rgb_tuple: tuple[int, int, int] = (56, 189, 248)
    qimage: Any = None
    image_dims: str = ""
    alert_until: float = 0.0
    history: list[ClipboardHistoryItem] = field(default_factory=list)
    copied_feedback_until: float = 0.0
    copied_feedback_text: str = ""


@dataclass
class ShelfFileItem:
    path: str
    name: str
    ext_badge: str
    size_str: str


@dataclass
class DropZoneInfo:
    dragging_over: bool = False
    dropped_file_path: str = ""
    dropped_file_name: str = ""
    dropped_file_size_str: str = ""
    status_feedback: str = ""
    shelf_files: list[ShelfFileItem] = field(default_factory=list)


@dataclass
class SmartGlanceInfo:
    enabled_in_idle: bool = True
    temperature_c: int = 16
    condition: str = "Ясно"
    weather_icon: str = "🌙"
    feels_like_c: int = 14
    wind_mps: float = 3.2
    city: str = "Локальная метеостанция"


@dataclass
class DownloadInfo:
    active: bool = False
    filename: str = "ubuntu-24.04-desktop-amd64.iso"
    progress: float = 0.0
    speed_mbps: float = 42.5
    alert_until: float = 0.0


@dataclass
class HardwareInfo:
    hud_enabled: bool = False
    cpu_percent: float = 14.0
    gpu_percent: float = 22.0
    ram_percent: float = 48.0
    ram_used_gb: float = 7.6
    ram_total_gb: float = 16.0
    cpu_temp_c: float = 52.0
    cpu_history: list[float] = field(default_factory=lambda: [15.0] * 20)
    net_down_kbps: float = 128.0
    net_up_kbps: float = 42.0
    net_down_str: str = "128 КБ/с"
    net_up_str: str = "42 КБ/с"
    ping_ms: int = 18


@dataclass
class PetCompanionInfo:
    enabled: bool = True
    species: str = "cat"  # "cat" (🐱 Кибер-Кот), "bot" (🤖 Нано-Бот), "fox" (🦊 Огненный Лис)
    name: str = "Кибер-Кот"
    level: int = 1
    xp: int = 25
    mood: str = "chill"  # "dancing", "turbo", "happy", "chill", "sleeping"
    happy_until: float = 0.0
    speech_bubble: str = "Мяу! 🐾"
    speech_until: float = 0.0

    def cycle_species(self) -> str:
        order = [
            ("cat", "Кибер-Кот"),
            ("bot", "Нано-Бот"),
            ("fox", "Огненный Лис"),
        ]
        idx = next((i for i, x in enumerate(order) if x[0] == self.species), 0)
        nxt = order[(idx + 1) % len(order)]
        self.species = nxt[0]
        self.name = nxt[1]
        return self.name


@dataclass
class NotificationInfo:
    app_name: str = "Telegram"
    app_badge: str = "TG"
    accent_color: tuple[int, int, int] = (56, 189, 248)
    sender: str = "Алексей • Команда проекта"
    message: str = "Сборка под Windows готова, проверь анимацию пружины! 🔥"
    alert_until: float = 0.0


@dataclass
class TerminalInfo:
    query: str = ""
    last_output: str = "Введите команду (calc, cmd, ipconfig), математику (256*14) или ?поиск"


# --- Act 3 UX & Positioning Settings ---

THEMES: dict[str, dict[str, Any]] = {
    "apple": {
        "label": " Apple Original",
        "primary": (10, 132, 255),
        "secondary": (48, 209, 88),
        "bg": (0, 0, 0),
    },
    "aurora": {
        "label": "🌌 Аврора",
        "primary": (168, 85, 247),
        "secondary": (56, 189, 248),
        "bg": (5, 6, 10),
    },
    "cyber": {
        "label": "💎 Киберпанк",
        "primary": (6, 182, 212),
        "secondary": (236, 72, 153),
        "bg": (4, 7, 12),
    },
    "gold": {
        "label": "🔥 Золото",
        "primary": (245, 158, 11),
        "secondary": (251, 191, 36),
        "bg": (8, 6, 4),
    },
    "emerald": {
        "label": "🍏 Изумруд",
        "primary": (16, 185, 129),
        "secondary": (56, 189, 248),
        "bg": (4, 8, 6),
    },
    "rose": {
        "label": "🌸 Розовый кварц",
        "primary": (244, 63, 94),
        "secondary": (192, 132, 252),
        "bg": (8, 4, 7),
    },
    "oled": {
        "label": "🖤 OLED Титан",
        "primary": (226, 232, 240),
        "secondary": (100, 116, 139),
        "bg": (0, 0, 0),
    },
}


@dataclass
class UXSettings:
    smart_hide_fullscreen: bool = False
    is_fullscreen_obscured: bool = False
    click_through_mode: bool = False
    hold_modifier_passthrough: bool = False
    is_modifier_held: bool = False
    monitor_index: int = 0
    position_mode: str = "floating_top"  # "floating_top", "docked_top", "bottom_taskbar"
    spring_preset: str = "bouncy"
    theme_name: str = "apple"

    @property
    def theme(self) -> dict[str, Any]:
        return THEMES.get(self.theme_name, THEMES["apple"])

    def cycle_theme(self) -> str:
        keys = list(THEMES.keys())
        idx = keys.index(self.theme_name) if self.theme_name in keys else 0
        self.theme_name = keys[(idx + 1) % len(keys)]
        return self.theme_name


@dataclass
class DevPortItem:
    port: int
    pid: int
    process_name: str


@dataclass
class PromptChip:
    label: str
    prompt_text: str


@dataclass
class VibeStudioInfo:
    active_ports: list[DevPortItem] = field(default_factory=list)
    prompts: list[PromptChip] = field(default_factory=list)
    eyedropper_active_until: float = 0.0
    eyedropper_hex: str = "#A855F7"
    eyedropper_rgb: tuple[int, int, int] = (168, 85, 247)
    eyedropper_pos: tuple[int, int] = (0, 0)
    status_message: str = "⚡ Радар портов активен • Клик по промпту копирует его для Ctrl+V"
    status_until: float = 0.0


@dataclass
class IslandState:
    media: MediaInfo = field(default_factory=MediaInfo)
    timer: TimerInfo = field(default_factory=TimerInfo)
    battery: BatteryInfo = field(default_factory=BatteryInfo)
    audio: AudioPrivacyInfo = field(default_factory=AudioPrivacyInfo)

    # Act 2, Act 4 & Act 5 states
    clipboard: ClipboardAlertInfo = field(default_factory=ClipboardAlertInfo)
    download: DownloadInfo = field(default_factory=DownloadInfo)
    hardware: HardwareInfo = field(default_factory=HardwareInfo)
    drop_zone: DropZoneInfo = field(default_factory=DropZoneInfo)
    notification: NotificationInfo = field(default_factory=NotificationInfo)
    terminal: TerminalInfo = field(default_factory=TerminalInfo)
    glance: SmartGlanceInfo = field(default_factory=SmartGlanceInfo)
    vibe: VibeStudioInfo = field(default_factory=VibeStudioInfo)
    pet: PetCompanionInfo = field(default_factory=PetCompanionInfo)

    # Act 3 UX settings
    ux: UXSettings = field(default_factory=UXSettings)

    # User interaction state: "media", "timer", "hardware", "drop", "terminal", "shelf", "glance", "vibe", or None
    expanded_target: str | None = None
    hovered: bool = False

    def resolve_mode(self, now: float | None = None) -> IslandMode:
        if now is None:
            now = time.monotonic()

        # 0. Drag-and-drop hover or Live Screen Eyedropper overrides immediately
        if self.drop_zone.dragging_over:
            return IslandMode.DROP_ZONE_HOVER
        if now < self.vibe.eyedropper_active_until:
            return IslandMode.ALERT_EYEDROPPER

        # 1. Explicit expanded cards
        if self.expanded_target == "vibe":
            return IslandMode.EXPANDED_VIBE
        if self.expanded_target == "terminal":
            return IslandMode.EXPANDED_TERMINAL
        if self.expanded_target == "drop":
            return IslandMode.EXPANDED_DROP_ACTIONS
        if self.expanded_target == "shelf":
            return IslandMode.EXPANDED_SHELF
        if self.expanded_target == "glance":
            return IslandMode.EXPANDED_GLANCE
        if self.expanded_target == "media":
            return IslandMode.EXPANDED_MEDIA
        if self.expanded_target == "timer":
            return IslandMode.EXPANDED_TIMER
        if self.expanded_target == "hardware":
            return IslandMode.EXPANDED_HARDWARE

        # 2. Transient alerts (Notifications, Clipboard, Battery, Volume, Downloads)
        if now < self.notification.alert_until:
            return IslandMode.ALERT_NOTIFICATION
        if now < self.clipboard.alert_until:
            return IslandMode.ALERT_CLIPBOARD
        if now < self.battery.alert_until:
            return IslandMode.ALERT_BATTERY
        if now < self.audio.volume_alert_until:
            return IslandMode.ALERT_VOLUME
        if self.download.active or now < self.download.alert_until:
            return IslandMode.ALERT_DOWNLOAD

        # 3. Multitasking Split Island:
        # e.g., Media / Spotify (or Hardware HUD) + Timer/Pomodoro running simultaneously
        media_compact_active = self.media.playing or self.media.is_spotify
        if (media_compact_active or self.hardware.hud_enabled) and self.timer.active:
            return IslandMode.SPLIT_MULTITASK

        # 4. Single active compact activity
        if self.hardware.hud_enabled:
            return IslandMode.COMPACT_HARDWARE
        if media_compact_active:
            return IslandMode.COMPACT_MEDIA
        if self.timer.active:
            return IslandMode.COMPACT_TIMER

        # 5. Default minimal pill (with Smart Glance Clock/Weather if enabled)
        return IslandMode.IDLE
