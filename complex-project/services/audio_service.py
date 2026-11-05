"""
Windows Audio, Volume HUD, Peak Meter, and Microphone Privacy Service.
"""

from __future__ import annotations
import time
import warnings
import winreg
from typing import Callable

warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import comtypes
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, IAudioMeterInformation
    HAS_PYCAW = True
except Exception:
    HAS_PYCAW = False


class AudioService:
    """Monitors Windows system volume, real-time audio peak, and active microphone usage."""

    def __init__(self) -> None:
        self._endpoint_volume = None
        self._meter = None
        self._last_volume: int | None = None
        self._last_mute: bool | None = None
        self._simulated_mic_active: bool = False
        self._last_mic_check: float = 0.0
        self._cached_mic_active: bool = False
        self._cached_mic_app: str = ""
        self._init_audio_interfaces()

    def _init_audio_interfaces(self) -> None:
        if not HAS_PYCAW:
            return
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        try:
            device = AudioUtilities.GetSpeakers()
            if hasattr(device, "EndpointVolume"):
                self._endpoint_volume = device.EndpointVolume
            else:
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self._endpoint_volume = cast(interface, POINTER(IAudioEndpointVolume))

            if hasattr(device, "AudioMeterInformation"):
                self._meter = device.AudioMeterInformation
            else:
                meter_iface = device.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
                self._meter = cast(meter_iface, POINTER(IAudioMeterInformation))
        except Exception:
            self._endpoint_volume = None
            self._meter = None

    def get_volume_state(self) -> tuple[int, bool, bool]:
        """
        Returns (volume_percent, is_muted, changed_since_last_poll).
        """
        if self._endpoint_volume is None:
            v = self._last_volume if self._last_volume is not None else 65
            m = self._last_mute if self._last_mute is not None else False
            return v, m, False

        try:
            scalar = float(self._endpoint_volume.GetMasterVolumeLevelScalar())
            vol = int(round(scalar * 100))
            muted = bool(self._endpoint_volume.GetMute())
            changed = False
            if self._last_volume is not None and (
                abs(vol - self._last_volume) >= 1 or muted != self._last_mute
            ):
                changed = True
            self._last_volume = vol
            self._last_mute = muted
            return vol, muted, changed
        except Exception:
            return (self._last_volume or 65), bool(self._last_mute), False

    def set_volume(self, percent: int) -> int:
        percent = max(0, min(100, int(percent)))
        self._last_volume = percent
        if self._endpoint_volume is not None:
            try:
                self._endpoint_volume.SetMasterVolumeLevelScalar(percent / 100.0, None)
                if percent > 0 and self._last_mute:
                    self._endpoint_volume.SetMute(0, None)
                    self._last_mute = False
            except Exception:
                pass
        return percent

    def change_volume_delta(self, delta: int) -> int:
        current, _, _ = self.get_volume_state()
        return self.set_volume(current + delta)

    def toggle_mute(self) -> bool:
        if self._endpoint_volume is not None:
            try:
                new_mute = not bool(self._endpoint_volume.GetMute())
                self._endpoint_volume.SetMute(1 if new_mute else 0, None)
                self._last_mute = new_mute
                return new_mute
            except Exception:
                pass
        self._last_mute = not bool(self._last_mute)
        return self._last_mute

    def get_audio_peak(self) -> float:
        """Returns 0.0..1.0 real-time system audio peak for equalizer animation."""
        if self._meter is not None:
            try:
                peak = float(self._meter.GetPeakValue())
                return max(0.0, min(1.0, peak))
            except Exception:
                pass
        return 0.0

    def set_simulated_mic(self, active: bool) -> None:
        self._simulated_mic_active = active

    def get_mic_privacy_state(self) -> tuple[bool, str]:
        """
        Checks Windows CapabilityAccessManager registry to see if any app
        is actively recording from the microphone (LastUsedTimeStop == 0).
        """
        if self._simulated_mic_active:
            return True, "Тестовый микрофон (Демо)"

        now = time.monotonic()
        if now - self._last_mic_check < 1.0:
            return self._cached_mic_active, self._cached_mic_app

        self._last_mic_check = now
        active, app_name = self._scan_registry_mic()
        self._cached_mic_active = active
        self._cached_mic_app = app_name
        return active, app_name

    def _scan_registry_mic(self) -> tuple[bool, str]:
        base_path = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base_path) as root_key:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(root_key, i)
                        i += 1
                    except OSError:
                        break

                    sub_path = f"{base_path}\\{subkey_name}"
                    if subkey_name == "NonPackaged":
                        try:
                            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_path) as np_key:
                                j = 0
                                while True:
                                    try:
                                        app_key_name = winreg.EnumKey(np_key, j)
                                        j += 1
                                    except OSError:
                                        break
                                    if self._is_key_actively_recording(f"{sub_path}\\{app_key_name}"):
                                        short_name = app_key_name.split("#")[-1].replace(".exe", "")
                                        return True, short_name
                        except OSError:
                            pass
                    else:
                        if self._is_key_actively_recording(sub_path):
                            short_name = subkey_name.split("_")[0]
                            return True, short_name
        except OSError:
            pass
        return False, ""

    @staticmethod
    def _is_key_actively_recording(key_path: str) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                start_val, _ = winreg.QueryValueEx(k, "LastUsedTimeStart")
                stop_val, _ = winreg.QueryValueEx(k, "LastUsedTimeStop")
                return int(start_val) > 0 and int(stop_val) == 0
        except OSError:
            return False
