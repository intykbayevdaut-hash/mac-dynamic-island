"""
Smart Clipboard Service (Act 2, Act 4 Pro & Act 6 Translator + Layout Fixer).
Monitors system clipboard for Ctrl+C events, classifies content into
HEX/RGB Colors, Images, or Text snippets, maintains a 5-item Clipboard History,
and provides 1-click RU ⇄ EN Translation & QWERTY ⇄ ЙЦУКЕН Keyboard Layout Fixer.
"""

from __future__ import annotations
from datetime import datetime
import json
import re
import time
import urllib.parse
import urllib.request
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QLinearGradient
from core.state import ClipboardAlertInfo, ClipboardHistoryItem


HEX_COLOR_RE = re.compile(r"^\s*#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\s*$")
RGB_COLOR_RE = re.compile(
    r"^\s*rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)\s*$",
    re.IGNORECASE,
)

_EN_CHARS = "`qwertyuiop[]asdfghjkl;'zxcvbnm,./~QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?"
_RU_CHARS = "ёйцукенгшщзхъфывапролджэячсмитьбю.ЁЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,"
_EN_TO_RU = str.maketrans(_EN_CHARS, _RU_CHARS)
_RU_TO_EN = str.maketrans(_RU_CHARS, _EN_CHARS)

_OFFLINE_DICT_RU_EN = {
    "привет": "Hello",
    "привет, как дела?": "Hello, how are you?",
    "как дела": "How are you",
    "спасибо": "Thank you",
    "пожалуйста": "Please / You're welcome",
    "доброе утро": "Good morning",
    "добрый вечер": "Good evening",
    "ошибка": "Error",
    "настройки": "Settings",
    "музыка": "Music",
    "таймер": "Timer",
    "загрузка": "Download",
    "буфер обмена": "Clipboard",
}
_OFFLINE_DICT_EN_RU = {v.lower(): k.capitalize() for k, v in _OFFLINE_DICT_RU_EN.items()}
_OFFLINE_DICT_EN_RU.update(
    {
        "hello": "Привет",
        "hello world": "Привет, мир",
        "thank you": "Спасибо",
        "how are you": "Как дела",
        "error": "Ошибка",
        "warning": "Предупреждение",
        "success": "Успешно",
        "loading": "Загрузка",
        "settings": "Настройки",
    }
)


class ClipboardService:
    """Listens to QClipboard changes, populates ClipboardAlertInfo, and manages 5-item history."""

    MAX_HISTORY = 5

    def __init__(self, clipboard_info: ClipboardAlertInfo) -> None:
        self.info = clipboard_info
        self._ignore_next = False
        self._last_text = ""
        self._initialized = False
        self._seed_initial_history()

    def _seed_initial_history(self) -> None:
        now_str = datetime.now().strftime("%H:%M")
        self.info.history = [
            ClipboardHistoryItem(
                kind="color",
                raw_value="#38BDF8",
                display_label="#38BDF8 • Sky Cyan",
                rgb_tuple=(56, 189, 248),
                timestamp_str=now_str,
            ),
            ClipboardHistoryItem(
                kind="color",
                raw_value="#A855F7",
                display_label="#A855F7 • Neon Purple",
                rgb_tuple=(168, 85, 247),
                timestamp_str=now_str,
            ),
            ClipboardHistoryItem(
                kind="text",
                raw_value="ghbdtn, rfr ltkf?",
                display_label="ghbdtn, rfr ltkf? (тест раскладки)",
                rgb_tuple=(148, 163, 184),
                timestamp_str=now_str,
            ),
        ]

    def attach(self) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            self._last_text = cb.text() or ""
            cb.dataChanged.connect(self._on_clipboard_changed)
            self._initialized = True

    def copy_text_silently(self, text: str) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            self._ignore_next = True
            cb.setText(text)
            self._last_text = text

    def restore_history_item(self, index: int) -> None:
        if 0 <= index < len(self.info.history):
            item = self.info.history[index]
            self.copy_text_silently(item.raw_value)
            self.info.copied_feedback_text = f"✓ Скопировано: {item.display_label[:26]}"
            self.info.copied_feedback_until = time.monotonic() + 2.5

    def _get_active_text(self) -> str:
        cb = QGuiApplication.clipboard()
        raw = (cb.text() if cb is not None else "") or ""
        raw = raw.strip()
        if not raw and self.info.history:
            for h in self.info.history:
                if h.kind == "text" and h.raw_value.strip():
                    return h.raw_value.strip()
        return raw or "ghbdtn, rfr ltkf?"

    def fix_clipboard_layout(self) -> str:
        """Converts QWERTY ⇄ ЙЦУКЕН (e.g. 'ghbdtn' -> 'привет') and copies to clipboard."""
        raw = self._get_active_text()
        ru_count = sum(1 for ch in raw if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
        en_count = sum(1 for ch in raw if "a" <= ch.lower() <= "z")
        if ru_count > en_count:
            fixed = raw.translate(_RU_TO_EN)
        else:
            fixed = raw.translate(_EN_TO_RU)

        now = time.monotonic()
        self.copy_text_silently(fixed)
        self._push_history("text", fixed, f"⌨️ {fixed[:28]}", (56, 189, 248))
        self.info.kind = "text"
        self.info.preview_text = f"⌨️ {raw[:14]} → {fixed[:22]}"
        self.info.char_count = len(fixed)
        self.info.alert_until = now + 3.4
        self.info.copied_feedback_text = f"⌨️ Исправлено для Ctrl+V: «{fixed[:26]}»"
        self.info.copied_feedback_until = now + 3.4
        return fixed

    def translate_clipboard_text(self) -> str:
        """Translates current clipboard text RU ⇄ EN and copies the result to clipboard."""
        raw = self._get_active_text()
        has_cyrillic = any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in raw)
        src_lang = "ru" if has_cyrillic else "en"
        dst_lang = "en" if has_cyrillic else "ru"

        translated = ""
        low = raw.lower().strip()
        if has_cyrillic and low in _OFFLINE_DICT_RU_EN:
            translated = _OFFLINE_DICT_RU_EN[low]
        elif not has_cyrillic and low in _OFFLINE_DICT_EN_RU:
            translated = _OFFLINE_DICT_EN_RU[low]

        if not translated:
            try:
                q = urllib.parse.quote(raw[:400])
                url = (
                    f"https://translate.googleapis.com/translate_a/single"
                    f"?client=gtx&sl={src_lang}&tl={dst_lang}&dt=t&q={q}"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                    if isinstance(data, list) and data and isinstance(data[0], list):
                        translated = "".join(seg[0] for seg in data[0] if seg and seg[0])
            except Exception:
                pass

        if not translated:
            # Fallback if offline and phrase not in quick dict: try layout fix or mark offline
            if not has_cyrillic and any(ch in _EN_CHARS for ch in raw):
                candidate = raw.translate(_EN_TO_RU)
                translated = f"{candidate} (офлайн)"
            else:
                translated = raw

        now = time.monotonic()
        self.copy_text_silently(translated)
        direction = "RU→EN" if has_cyrillic else "EN→RU"
        self._push_history("text", translated, f"🌐 {translated[:28]}", (52, 211, 153))
        self.info.kind = "text"
        self.info.preview_text = f"🌐 [{direction}] {translated[:34]}"
        self.info.char_count = len(translated)
        self.info.alert_until = now + 3.6
        self.info.copied_feedback_text = f"🌐 Перевод в буфере (Ctrl+V): «{translated[:24]}»"
        self.info.copied_feedback_until = now + 3.6
        return translated

    def _push_history(
        self,
        kind: str,
        raw_value: str,
        display_label: str,
        rgb_tuple: tuple[int, int, int] = (168, 85, 247),
    ) -> None:
        self.info.history = [h for h in self.info.history if h.raw_value != raw_value]
        self.info.history.insert(
            0,
            ClipboardHistoryItem(
                kind=kind,
                raw_value=raw_value,
                display_label=display_label,
                rgb_tuple=rgb_tuple,
                timestamp_str=datetime.now().strftime("%H:%M"),
            ),
        )
        if len(self.info.history) > self.MAX_HISTORY:
            self.info.history = self.info.history[: self.MAX_HISTORY]

    def _on_clipboard_changed(self) -> None:
        try:
            if self._ignore_next:
                self._ignore_next = False
                return

            cb = QGuiApplication.clipboard()
            if cb is None:
                return

            mime = cb.mimeData()
            if mime is None:
                return

            now = time.monotonic()

            # 1. Check for copied Image
            if mime.hasImage():
                qimg = cb.image()
                if not qimg.isNull():
                    w, h = qimg.width(), qimg.height()
                    thumb = qimg.scaled(
                        64, 64,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.info.kind = "image"
                    self.info.qimage = thumb
                    self.info.image_dims = f"{w}×{h} px"
                    self.info.preview_text = f"Изображение ({w}×{h})"
                    self.info.alert_until = now + 2.6
                    return

            # 2. Check for copied Text or Color
            if mime.hasText():
                raw = (cb.text() or "").strip()
                if not raw or raw == self._last_text:
                    return
                self._last_text = raw
                self.process_copied_text(raw, now)
        except Exception:
            pass

    def process_copied_text(self, raw: str, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()

        # Check HEX Color (#RRGGBB or #RGB)
        hex_match = HEX_COLOR_RE.match(raw)
        if hex_match and (raw.startswith("#") or len(raw.strip()) == 6):
            h_str = hex_match.group(1)
            if len(h_str) == 3:
                h_str = "".join(ch * 2 for ch in h_str)
            r = int(h_str[0:2], 16)
            g = int(h_str[2:4], 16)
            b = int(h_str[4:6], 16)
            hex_code = f"#{h_str.upper()}"
            self.info.kind = "color"
            self.info.hex_color = hex_code
            self.info.rgb_tuple = (r, g, b)
            self.info.preview_text = f"Цвет {hex_code} • rgb({r}, {g}, {b})"
            self.info.alert_until = now + 2.6
            self._push_history("color", hex_code, f"{hex_code} • rgb({r},{g},{b})", (r, g, b))
            return

        # Check rgb(r, g, b)
        rgb_match = RGB_COLOR_RE.match(raw)
        if rgb_match:
            r, g, b = (min(255, int(rgb_match.group(i))) for i in (1, 2, 3))
            hex_code = f"#{r:02X}{g:02X}{b:02X}"
            self.info.kind = "color"
            self.info.hex_color = hex_code
            self.info.rgb_tuple = (r, g, b)
            self.info.preview_text = f"Цвет {hex_code} • rgb({r}, {g}, {b})"
            self.info.alert_until = now + 2.6
            self._push_history("color", raw, f"{hex_code} • rgb({r},{g},{b})", (r, g, b))
            return

        # Normal Text snippet
        single_line = " ".join(raw.split())
        words = single_line.split(" ")
        first_words = " ".join(words[:7])
        if len(words) > 7:
            first_words += "…"

        self.info.kind = "text"
        self.info.preview_text = first_words
        self.info.char_count = len(raw)
        self.info.alert_until = now + 3.0
        self._push_history("text", raw, first_words[:34])

    def trigger_demo_image(self) -> None:
        img = QImage(120, 120, QImage.Format.Format_ARGB32)
        p = QPainter(img)
        grad = QLinearGradient(0, 0, 120, 120)
        grad.setColorAt(0.0, QColor(16, 185, 129))
        grad.setColorAt(0.5, QColor(59, 130, 246))
        grad.setColorAt(1.0, QColor(168, 85, 247))
        p.fillRect(0, 0, 120, 120, grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 200))
        p.drawEllipse(34, 34, 52, 52)
        p.end()

        self.info.kind = "image"
        self.info.qimage = img
        self.info.image_dims = "1920×1080 px"
        self.info.preview_text = "Скриншот буфера (1920×1080)"
        self.info.alert_until = time.monotonic() + 2.8
