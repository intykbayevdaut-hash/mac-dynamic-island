"""
Windows Battery & Power Monitoring Service.
Detects charger plug/unplug events and low battery thresholds (<20%, <10%).
"""

from __future__ import annotations
import time
import psutil
from core.state import BatteryInfo


class PowerService:
    """Monitors battery percentage, AC power state, and triggers Dynamic Island alerts."""

    def __init__(self) -> None:
        self._last_plugged: bool | None = None
        self._warned_20: bool = False
        self._warned_10: bool = False
        self._last_poll: float = 0.0

    def update(self, battery_info: BatteryInfo, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()

        if now - self._last_poll < 1.5:
            return
        self._last_poll = now

        try:
            batt = psutil.sensors_battery()
        except Exception:
            batt = None

        if batt is None:
            battery_info.has_battery = False
            return

        battery_info.has_battery = True
        percent = int(round(batt.percent))
        plugged = bool(batt.power_plugged)

        battery_info.percent = max(0, min(100, percent))
        battery_info.plugged = plugged

        # Detect charger connect / disconnect transition
        if self._last_plugged is not None and plugged != self._last_plugged:
            if plugged:
                battery_info.alert_type = "charging"
                battery_info.alert_until = now + 3.2
                self._warned_20 = False
                self._warned_10 = False
            else:
                battery_info.alert_type = "unplugged"
                battery_info.alert_until = now + 2.8

        self._last_plugged = plugged

        # Check low-battery thresholds when on battery
        if not plugged:
            if percent <= 10 and not self._warned_10:
                self._warned_10 = True
                battery_info.alert_type = "low_10"
                battery_info.alert_until = now + 4.0
            elif percent <= 20 and not self._warned_20:
                self._warned_20 = True
                battery_info.alert_type = "low_20"
                battery_info.alert_until = now + 3.5

    def trigger_simulated_event(
        self,
        battery_info: BatteryInfo,
        event_type: str,
        percent: int | None = None,
    ) -> None:
        """Allows testing charging, unplugged, <20%, and <10% animations on any PC."""
        now = time.monotonic()
        if event_type == "charging":
            battery_info.plugged = True
            battery_info.percent = percent if percent is not None else 78
            battery_info.alert_type = "charging"
            battery_info.alert_until = now + 3.2
        elif event_type == "unplugged":
            battery_info.plugged = False
            battery_info.percent = percent if percent is not None else 77
            battery_info.alert_type = "unplugged"
            battery_info.alert_until = now + 2.8
        elif event_type == "low_20":
            battery_info.plugged = False
            battery_info.percent = 19
            battery_info.alert_type = "low_20"
            battery_info.alert_until = now + 3.6
        elif event_type == "low_10":
            battery_info.plugged = False
            battery_info.percent = 9
            battery_info.alert_type = "low_10"
            battery_info.alert_until = now + 4.0
