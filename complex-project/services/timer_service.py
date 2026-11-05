"""
Timer, Stopwatch, and Pomodoro Focus Service for Dynamic Island.
"""

from __future__ import annotations
import time
import winsound
from core.state import TimerInfo


class TimerService:
    """Manages countdown timers, stopwatches, and 25/5 Pomodoro Focus cycles."""

    def __init__(self) -> None:
        self._last_tick: float = time.monotonic()

    def start_countdown(self, timer: TimerInfo, seconds: float) -> None:
        timer.active = True
        timer.is_stopwatch = False
        timer.is_pomodoro = False
        timer.total_seconds = max(1.0, float(seconds))
        timer.remaining_seconds = timer.total_seconds
        timer.running = True
        self._last_tick = time.monotonic()

    def start_pomodoro(self, timer: TimerInfo, phase: str = "focus") -> None:
        timer.active = True
        timer.is_stopwatch = False
        timer.is_pomodoro = True
        timer.pomodoro_phase = phase
        duration = 25 * 60.0 if phase == "focus" else 5 * 60.0
        timer.total_seconds = duration
        timer.remaining_seconds = duration
        timer.running = True
        self._last_tick = time.monotonic()

    def start_stopwatch(self, timer: TimerInfo) -> None:
        timer.active = True
        timer.is_stopwatch = True
        timer.is_pomodoro = False
        timer.elapsed_seconds = 0.0
        timer.running = True
        self._last_tick = time.monotonic()

    def toggle_pause(self, timer: TimerInfo) -> None:
        if not timer.active:
            self.start_pomodoro(timer, "focus")
            return
        timer.running = not timer.running
        self._last_tick = time.monotonic()

    def add_seconds(self, timer: TimerInfo, seconds: float) -> None:
        if not timer.active:
            self.start_countdown(timer, max(60.0, seconds))
            return
        if not timer.is_stopwatch:
            timer.remaining_seconds = max(0.0, timer.remaining_seconds + seconds)
            timer.total_seconds = max(timer.total_seconds, timer.remaining_seconds)

    def reset(self, timer: TimerInfo) -> None:
        if timer.is_stopwatch:
            timer.elapsed_seconds = 0.0
            timer.running = False
        else:
            timer.remaining_seconds = timer.total_seconds
            timer.running = False

    def dismiss(self, timer: TimerInfo) -> None:
        timer.active = False
        timer.running = False
        timer.is_pomodoro = False

    def update(self, timer: TimerInfo, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        if not timer.active or not timer.running:
            return

        if timer.is_stopwatch:
            timer.elapsed_seconds += dt
        else:
            timer.remaining_seconds -= dt
            if timer.remaining_seconds <= 0.0:
                try:
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                except Exception:
                    pass

                if timer.is_pomodoro:
                    # Auto-transition between Focus (25m) and Break (5m)
                    if timer.pomodoro_phase == "focus":
                        timer.pomodoro_phase = "break"
                        timer.total_seconds = 5 * 60.0
                        timer.remaining_seconds = 5 * 60.0
                    else:
                        timer.pomodoro_phase = "focus"
                        timer.pomodoro_cycle += 1
                        timer.total_seconds = 25 * 60.0
                        timer.remaining_seconds = 25 * 60.0
                    timer.finished_flashUntil = now + 3.5
                else:
                    timer.remaining_seconds = 0.0
                    timer.running = False
                    timer.finished_flashUntil = now + 4.5
