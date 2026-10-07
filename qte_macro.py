"""
Violence District QTE Auto-Skillcheck Macro (Lunar Tear)
=========================================================
Ultra-low latency multi-monitor screen capture and DirectInput SendInput simulation
for Roblox "Violence District" Quick-Time Events (Dead by Daylight style skill checks).

Features:
- Sub-millisecond (<1ms) frame capture & analysis via MSS multi-monitor engine
- Hardware DirectInput scancode 0x39 for Spacebar simulation (anti-cheat compatible)
- High-contrast polar analysis for circular ring, white success patch, and red needle
- Passive GetAsyncKeyState hotkeys: F1 (Toggle Pause/Active), F2 (Clean Exit)
- Automatic DPI awareness (1:1 physical pixel alignment)
- Configurable via config.json (center overrides, hit position, offsets, keybinds)
- Completely silent operation (no audio beeps)
- Built-in test suite for screenshot verification (--test)
"""

import ctypes
from ctypes import wintypes
import math
import time
import os
import sys
import json
import argparse
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List

try:
    import mss
except ImportError:
    print("[ERROR] Required dependency 'mss' is missing.")
    print("Please install requirements using: pip install -r requirements.txt")
    sys.exit(1)

_cached_hdesk = None

# Precomputed trigonometric polar sampling tables for high FPS polling (>100 FPS)
_TRIG_360 = [(math.cos(math.radians(d)), math.sin(math.radians(d))) for d in range(360)]
_TRIG_RING = [(math.cos(math.radians(d)), math.sin(math.radians(d))) for d in range(0, 360, 10)]
_TRIG_720 = [(math.cos(math.radians(i * 0.5)), math.sin(math.radians(i * 0.5))) for i in range(720)]


# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ============================================================================
# Windows API Structures and DirectInput Definitions
# ============================================================================

user32 = ctypes.windll.user32

ULONG_PTR = ctypes.c_size_t

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ('wVk', wintypes.WORD),
        ('wScan', wintypes.WORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ULONG_PTR)
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ('uMsg', wintypes.DWORD),
        ('wParamL', wintypes.WORD),
        ('wParamH', wintypes.WORD)
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ('dx', wintypes.LONG),
        ('dy', wintypes.LONG),
        ('mouseData', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ULONG_PTR)
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ('ki', KEYBDINPUT),
        ('mi', MOUSEINPUT),
        ('hi', HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ('type', wintypes.DWORD),
        ('u', INPUT_UNION)
    ]

user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

INPUT_KEYBOARD = 1
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
SPACEBAR_SCANCODE = 0x39  # DirectInput hardware scancode for Spacebar

# Virtual Key Codes
VK_MAP = {
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "SPACE": 0x20
}

def ensure_desktop_attached(force: bool = False) -> bool:
    """Ensure the calling thread is attached to the interactive input desktop."""
    global _cached_hdesk
    if _cached_hdesk is not None and not force:
        return True
    try:
        # DESKTOP_ALL_ACCESS = 0x01FF
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            if user32.SetThreadDesktop(hdesk):
                _cached_hdesk = hdesk
                return True
    except Exception:
        pass
    return False

def enable_high_dpi() -> None:
    """Set process DPI awareness to per-monitor v2 for accurate 1:1 screen pixel coordinates."""
    ensure_desktop_attached()
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ============================================================================
# Keyboard Controller (Dual DirectInput Scancode + Virtual-Key SendInput)
# ============================================================================

class KeyboardController:
    """
    DirectInput hardware scancode and virtual-key keyboard simulator with hold duration and debounce.
    Dispatches both VK_SPACE (0x20) and DirectInput scancode (0x39) simultaneously so that
    both web browsers / Win32 apps and Roblox (DirectInput/RawInput) reliably detect Spacebar.
    """
    def __init__(self, scancode: int = SPACEBAR_SCANCODE, hold_ms: int = 35, debounce_s: float = 0.08):
        self.scancode = scancode
        self.hold_s = hold_ms / 1000.0
        self.debounce_s = debounce_s
        self.last_press_time = 0.0
        self.is_key_down = False
        self.release_deadline = 0.0

    def _send_hardware_scancode(self, flags: int) -> None:
        """
        Sends keystroke input.
        Sends both wVk (0x20 = VK_SPACE) and wScan (0x39 = DirectInput scancode)
        so that both web browsers and Roblox register Spacebar.
        """
        vk = user32.MapVirtualKeyW(self.scancode, 1) or 0x20
        is_keyup = bool(flags & KEYEVENTF_KEYUP)
        flags_vk = KEYEVENTF_KEYUP if is_keyup else 0
        flags_scan = (KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP) if is_keyup else KEYEVENTF_SCANCODE

        inp_vk = INPUT(
            ctypes.c_ulong(INPUT_KEYBOARD),
            INPUT_UNION(ki=KEYBDINPUT(vk, self.scancode, flags_vk, 0, 0))
        )
        inp_scan = INPUT(
            ctypes.c_ulong(INPUT_KEYBOARD),
            INPUT_UNION(ki=KEYBDINPUT(vk, self.scancode, flags_scan, 0, 0))
        )
        inputs = (INPUT * 2)(inp_vk, inp_scan)

        ensure_desktop_attached()
        user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
        # Also dispatch keybd_event to guarantee message loop delivery in Windows apps/browsers
        try:
            user32.keybd_event(vk, self.scancode, flags_vk, 0)
        except Exception:
            pass

    def send_down(self) -> None:
        self._send_hardware_scancode(KEYEVENTF_SCANCODE)
        self.is_key_down = True

    def send_up(self) -> None:
        self._send_hardware_scancode(KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)
        self.is_key_down = False

    def trigger(self) -> bool:
        """Immediately press spacebar down and schedule non-blocking release."""
        now = time.perf_counter()
        if now - self.last_press_time < self.debounce_s:
            return False
        if self.is_key_down:
            self.send_up()
        self.send_down()
        self.last_press_time = now
        self.release_deadline = now + self.hold_s
        return True

    def update(self) -> None:
        """Check if hold duration has expired and release key."""
        if self.is_key_down and time.perf_counter() >= self.release_deadline:
            self.send_up()

    def release_all(self) -> None:
        """Safety release on shutdown or pause."""
        if self.is_key_down:
            self.send_up()

# ============================================================================
# Multi-Monitor Geometry & Roblox Window Detection
# ============================================================================

def _create_mss():
    """Create an MSS instance supporting both modern mss.MSS() and legacy mss.mss()."""
    factory = getattr(mss, 'MSS', getattr(mss, 'mss', None))
    return factory()

def get_primary_monitor() -> Dict[str, Any]:
    """
    Locate the Primary / Main monitor explicitly using mss.
    Excludes the virtual combined bounding box (sct.monitors[0]) and secondary monitors.
    Returns: dict with 'left', 'top', 'width', 'height', 'is_primary'
    """
    ensure_desktop_attached()
    with _create_mss() as sct:
        # Check monitors[1:] for is_primary flag
        for m in sct.monitors[1:]:
            if m.get("is_primary"):
                return dict(m)
        # Fallback: check for (0, 0) origin among individual displays
        for m in sct.monitors[1:]:
            if m.get("left") == 0 and m.get("top") == 0:
                return dict(m)
        # Fallback: by mss convention, monitors[1] is the primary display
        if len(sct.monitors) > 1:
            return dict(sct.monitors[1])
        return dict(sct.monitors[0])

# Excluded window classes that must never be mistaken for Roblox
EXCLUDED_CLASSES = {
    "chrome_widgetwin_1", "chrome_widgetwin_0", "mozillawindowclass",
    "cabinetwclass", "explorewclass", "progman", "workerw",
    "consolewindowclass", "cascadia_hosting_window_class"
}

# Browser / external app title markers to filter out
EXCLUDED_TITLE_MARKERS = [
    "youtube", "google chrome", "thorium", "discord", "visual studio",
    "firefox", "edge", "brave", "opera", "steam", "reddit", "twitch"
]

def find_roblox_client_info() -> Optional[Dict[str, Any]]:
    """
    Search for an active, visible Roblox player window.
    Strictly matches genuine Roblox game clients and filters out web browsers (YouTube,
    Chrome, Thorium, Firefox, Edge), Discord, file explorers, and terminal consoles.
    Returns: dict with 'x', 'y', 'width', 'height', 'hwnd', 'is_fullscreen' or None.
    """
    ensure_desktop_attached()
    found = None
    primary = get_primary_monitor()

    def enum_proc(hwnd, lParam):
        nonlocal found
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        cls = cls_buf.value.strip()
        cls_lower = cls.lower()

        if cls_lower in EXCLUDED_CLASSES:
            return True

        title_lower = title.lower()
        if any(marker in title_lower for marker in EXCLUDED_TITLE_MARKERS):
            return True

        # Check for genuine Roblox client:
        # 1. Desktop client: class is "WINDOWSCLIENT" and title is "Roblox" or contains "roblox"
        # 2. Universal / Microsoft Store: class is "ApplicationFrameWindow" and title is strictly "Roblox"
        # 3. Exact title match "Roblox" (if class is not an excluded class)
        is_roblox = False
        if cls == "WINDOWSCLIENT" and "roblox" in title_lower:
            is_roblox = True
        elif title == "Roblox" and cls not in EXCLUDED_CLASSES:
            is_roblox = True
        elif title.startswith("Roblox") and cls in ("ApplicationFrameWindow", "WINDOWSCLIENT"):
            is_roblox = True

        if is_roblox:
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w >= 640 and h >= 480:
                pt = wintypes.POINT(0, 0)
                user32.ClientToScreen(hwnd, ctypes.byref(pt))
                is_fs = (pt.x == primary["left"] and pt.y == primary["top"] and
                         w == primary["width"] and h == primary["height"])
                found = {
                    "x": pt.x,
                    "y": pt.y,
                    "width": w,
                    "height": h,
                    "hwnd": hwnd,
                    "is_fullscreen": is_fs
                }
                return False
        return True

    try:
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
    except Exception:
        pass
    return found

def find_roblox_window() -> Optional[Tuple[int, int, int, int]]:
    """Original signature: returns (client_screen_x, client_screen_y, client_width, client_height) or None."""
    info = find_roblox_client_info()
    if info:
        return (info["x"], info["y"], info["width"], info["height"])
    return None

# ============================================================================
# Screen Capture Engine (MSS Multi-Monitor with Desktop Attachment)
# ============================================================================

class ScreenCapture:
    """
    Ultra-low latency screen capture using mss with input desktop attachment.
    Supports multi-monitor configurations without coordinate clipping or black frames.
    """
    def __init__(self, x1: int, y1: int, width: int, height: int):
        self.x1 = int(x1)
        self.y1 = int(y1)
        self.width = int(width)
        self.height = int(height)
        self.monitor = {
            "left": self.x1,
            "top": self.y1,
            "width": self.width,
            "height": self.height
        }
        ensure_desktop_attached()
        self._sct = _create_mss()

    def update_region(self, x1: int, y1: int, width: int, height: int) -> None:
        """Dynamically update capture bounds (e.g., when locking onto Roblox window)."""
        self.x1 = int(x1)
        self.y1 = int(y1)
        self.width = int(width)
        self.height = int(height)
        self.monitor = {
            "left": self.x1,
            "top": self.y1,
            "width": self.width,
            "height": self.height
        }

    def capture(self) -> bytearray:
        """Capture screen region directly into BGRA bytearray."""
        try:
            shot = self._sct.grab(self.monitor)
            return shot.raw
        except Exception:
            ensure_desktop_attached(force=True)
            try:
                shot = self._sct.grab(self.monitor)
                return shot.raw
            except Exception:
                try:
                    self._sct.close()
                except Exception:
                    pass
                self._sct = _create_mss()
                shot = self._sct.grab(self.monitor)
                return shot.raw

    def close(self) -> None:
        if hasattr(self, '_sct') and self._sct:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None

    def __del__(self) -> None:
        self.close()


# ============================================================================
# Configuration & Persistence
# ============================================================================

DEFAULT_CONFIG = {
    "resolution": None,
    "center_override": None,
    "top_bar_offset": 0,
    "crop_size": 320,
    "hit_position": "start",
    "lead_degrees": 0.0,
    "offset_degrees": 0.0,
    "latency_ms": 0.0,
    "speed_calibration": [
        {"speed": 250, "latency_ms": 14.96},
        {"speed": 350, "latency_ms": 14.96},
        {"speed": 500, "latency_ms": 14.96},
        {"speed": 700, "latency_ms": 14.96},
        {"speed": 1000, "latency_ms": 14.96}
    ],
    "verbose_logging": False,
    "min_needle_score": 35.0,
    "hold_duration_ms": 35,
    "debounce_seconds": 0.08,
    "poll_interval_ms": 0,
    "trigger_delay_ms": 0,
    "toggle_key": "F1",
    "exit_key": "F2",
    "status_interval_ms": 250
}

def resolve_config_path(config_path: str = "config.json") -> str:
    """Resolve config file path, checking cwd first then next to executable/script."""
    if os.path.isabs(config_path):
        return config_path
    if os.path.exists(config_path):
        return os.path.abspath(config_path)
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(base_dir, config_path)
    if os.path.exists(candidate):
        return candidate
    return os.path.abspath(config_path)

def update_persisted_config(updates: Dict[str, Any], config_path: str = "config.json") -> bool:
    """Safely and atomically update keys in config.json while preserving all existing config fields."""
    target_path = resolve_config_path(config_path)
    try:
        data = {}
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.update(updates)
        temp_path = f"{target_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(temp_path, target_path)
        return True
    except Exception:
        return False

def load_or_create_config(config_path: str = "config.json") -> Dict[str, Any]:
    """Load configuration from JSON, or generate default config file if missing."""
    target_path = resolve_config_path(config_path)
    if not os.path.exists(target_path):
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=4)
            print(f"[CONFIG] Created default configuration file: {target_path}")
        except Exception as e:
            print(f"[CONFIG WARNING] Could not write default config: {e}")
        return dict(DEFAULT_CONFIG)
    
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        return merged
    except Exception as e:
        print(f"[CONFIG WARNING] Error loading {target_path}, falling back to defaults: {e}")
        return dict(DEFAULT_CONFIG)


# ============================================================================
# Self-Learning Adaptive Latency Calibration Engine
# ============================================================================

class AdaptiveCalibrationEngine:
    """
    Continuous velocity-based adaptive latency calibration engine.
    
    Dynamically compensates for system & input polling latency:
        Δθ_lead(ω) = ω * τ_learned
        
    Post-Hit Freeze Detection:
    - Captures the resting needle angle θ_stopped during the post-trigger freeze window (~80-180ms).
    - Calculates angular error relative to the white patch center:
        error = θ_stopped - θ_patch_center
    - Conservatively updates learned latency:
        Δτ = α * (error / ω)
      (with learning step α ≈ 0.15-0.25, bounded by max adjustment e.g. 1.5-2.0ms).
    - Enforces critical safety constraints: τ_learned >= 0, and effective lead point
      never precedes patch_start by more than a strictly clamped safe margin.
    - Persists learned latency to config.json and appends diagnostic records to calibration.log.
    """
    def __init__(
        self,
        config_path: str = "config.json",
        log_path: Optional[str] = None,
        speed_calibration: Optional[List[Dict[str, float]]] = None,
        learning_rate_late: float = 0.20,
        learning_rate_great: float = 0.15,
        max_adjustment_ms: float = 2.0,
        max_micro_adjustment_ms: float = 0.8,
        max_lead_degrees: float = 90.0,
        min_latency_ms: float = 0.0,
        max_latency_ms: float = 300.0,
        freeze_window_start_s: float = 0.075,
        freeze_window_end_s: float = 0.180,
        min_needle_score: float = 35.0,
        persist_config: bool = True,
        verbose_logging: bool = False
    ):
        resolved_cfg = resolve_config_path(config_path)
        self.config_path = resolved_cfg
        if log_path:
            self.log_path = os.path.abspath(log_path)
        else:
            base_dir = os.path.dirname(resolved_cfg)
            self.log_path = os.path.join(base_dir, "calibration.log")

        if speed_calibration is None:
            if os.path.exists(resolved_cfg):
                try:
                    with open(resolved_cfg, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if "speed_calibration" in data and isinstance(data["speed_calibration"], list):
                            speed_calibration = data["speed_calibration"]
                except Exception:
                    pass

        self.speed_calibration = speed_calibration or [
            {"speed": 250, "latency_ms": 14.96},
            {"speed": 350, "latency_ms": 14.96},
            {"speed": 500, "latency_ms": 14.96},
            {"speed": 700, "latency_ms": 14.96},
            {"speed": 1000, "latency_ms": 14.96}
        ]
        self.speed_calibration.sort(key=lambda x: x["speed"])
        self.verbose_logging = verbose_logging
        self.last_used_anchor = None

        self.learning_rate_late = float(learning_rate_late)
        self.learning_rate_great = float(learning_rate_great)
        self.max_adjustment_ms = float(max_adjustment_ms)
        self.max_micro_adjustment_ms = float(max_micro_adjustment_ms)
        self.max_lead_degrees = float(max_lead_degrees)
        self.min_latency_ms = float(min_latency_ms)
        self.max_latency_ms = float(max_latency_ms)
        self.freeze_window_start_s = float(freeze_window_start_s)
        self.freeze_window_end_s = float(freeze_window_end_s)
        self.min_needle_score = float(min_needle_score)
        self.persist_config = persist_config

        # Post-trigger tracking state
        self._is_tracking = False
        self._trigger_time = 0.0
        self._trigger_angle = 0.0
        self._trigger_velocity = 0.0
        self._patch_start = 0.0
        self._patch_end = 0.0
        self._patch_center = 0.0
        self._patch_span = 0.0
        self._latency_before = 0.0
        self._freeze_samples: List[Tuple[float, float, float]] = []
        self._finalized = False
        self._is_chained = False

    @property
    def learned_latency_ms(self) -> float:
        """Backwards compatible property returning current or nominal learned latency."""
        if getattr(self, 'last_used_anchor', None):
            return float(self.last_used_anchor.get("latency_ms", 14.96))
        if getattr(self, 'speed_calibration', None):
            return float(self.get_interpolated_latency(300.0))
        return 14.96

    @learned_latency_ms.setter
    def learned_latency_ms(self, val: float) -> None:
        pass

    def get_interpolated_latency(self, velocity: float) -> float:
        if not self.speed_calibration:
            return 14.96
        if velocity <= self.speed_calibration[0]["speed"]:
            return self.speed_calibration[0]["latency_ms"]
        if velocity >= self.speed_calibration[-1]["speed"]:
            return self.speed_calibration[-1]["latency_ms"]
        
        for i in range(len(self.speed_calibration) - 1):
            s1 = self.speed_calibration[i]["speed"]
            s2 = self.speed_calibration[i+1]["speed"]
            if s1 <= velocity <= s2:
                l1 = self.speed_calibration[i]["latency_ms"]
                l2 = self.speed_calibration[i+1]["latency_ms"]
                ratio = (velocity - s1) / (s2 - s1)
                return l1 + ratio * (l2 - l1)
        return 14.96

    def calculate_dynamic_lead(self, velocity: float) -> float:
        """
        Calculate continuous velocity-based dynamic lead angle:
            Δθ_lead(ω) = ω * (τ_interpolated / 1000.0)
        Strictly clamped to [0.0, max_lead_degrees].
        """
        if velocity <= 0.0:
            return 0.0
        interpolated_latency = self.get_interpolated_latency(velocity)
        if interpolated_latency <= 0.0:
            return 0.0
        raw_lead = velocity * (interpolated_latency / 1000.0)
        return max(0.0, min(self.max_lead_degrees, raw_lead))

    def calculate_angular_error(self, stopped_angle: float, patch_center: float) -> float:
        """
        Calculate shortest circular angular error relative to patch center in [-180°, +180°].
        Positive: needle stopped past center clockwise (late).
        Negative: needle stopped before center (early).
        """
        return ((stopped_angle - patch_center + 180.0) % 360.0) - 180.0

    def classify_hit(self, stopped_angle: float, patch_start: float, patch_end: float, patch_center: float, patch_span: float) -> str:
        """
        Classify the landing zone of the stopped needle:
        - 'GREAT': stopped inside the white success patch.
        - 'GOOD': stopped past the white patch in the success continuation zone (late).
        - 'EARLY': stopped before the white patch start (premature trigger).
        """
        dist_from_start = (stopped_angle - patch_start) % 360.0
        if dist_from_start <= patch_span:
            return "GREAT"
        if dist_from_start <= 180.0:
            return "GOOD"
        return "EARLY"

    def calculate_latency_adjustment(self, error: float, velocity: float, hit_result: str) -> float:
        """
        Calculate Δτ (ms) from angular error and needle velocity:
            Δτ = α * (error / ω) * 1000ms
        with safety bounding and result-dependent learning rates.
        """
        if velocity < 50.0:
            return 0.0

        raw_delta_ms = (error / velocity) * 1000.0

        if hit_result == "GOOD":
            # Late hit: increase latency conservatively
            delta_tau = self.learning_rate_late * raw_delta_ms
            return max(0.0, min(self.max_adjustment_ms, delta_tau))
        elif hit_result == "GREAT":
            # Great hit inside patch: small micro-adjustments toward center
            if abs(error) <= 0.35:
                return 0.0
            delta_tau = self.learning_rate_great * raw_delta_ms
            return max(-self.max_micro_adjustment_ms, min(self.max_micro_adjustment_ms, delta_tau))
        elif hit_result == "EARLY":
            # Early hit: safety back-off immediately
            delta_tau = self.learning_rate_late * raw_delta_ms
            return -max(1.0, min(5.0, abs(delta_tau)))
        return 0.0

    def record_trigger(
        self,
        trigger_time: float,
        trigger_angle: float,
        angular_velocity: float,
        patch_start: float,
        patch_end: float,
        patch_center: float,
        patch_span: float,
        is_chained: bool = False
    ) -> None:
        """Register a confirmed trigger event to begin post-hit freeze tracking."""
        self._is_chained = bool(is_chained)
        self._is_tracking = True
        self._trigger_time = trigger_time
        self._trigger_angle = trigger_angle
        self._trigger_velocity = angular_velocity
        self._patch_start = patch_start
        self._patch_end = patch_end
        self._patch_center = patch_center
        self._patch_span = patch_span
        self._latency_before = self.get_interpolated_latency(angular_velocity)
        self._freeze_samples = []
        self._finalized = False

    def on_frame(
        self,
        now: float,
        needle_angle: Optional[float],
        needle_score: float,
        qte_present: bool
    ) -> Optional[Dict[str, Any]]:
        """
        Process post-trigger frame. Accumulates freeze samples within the freeze window
        (~80ms - 180ms) and finalizes calibration when the freeze window elapses.
        """
        if not self._is_tracking or self._finalized:
            return None

        elapsed = now - self._trigger_time

        # Accumulate needle samples during freeze window
        if self.freeze_window_start_s <= elapsed <= self.freeze_window_end_s:
            if qte_present and needle_angle is not None and needle_score >= self.min_needle_score:
                self._freeze_samples.append((elapsed, needle_angle, needle_score))

        # Check for window completion: either window expired, or QTE vanished after gathering samples
        if elapsed > self.freeze_window_end_s or (elapsed >= self.freeze_window_start_s and not qte_present and len(self._freeze_samples) >= 1):
            return self.finalize_calibration(qte_vanished=(not qte_present))

        # Safety timeout if QTE hangs
        if elapsed > 0.350:
            self._is_tracking = False
            self._finalized = True

        return None

    def finalize_calibration(self, qte_vanished: bool = False) -> Optional[Dict[str, Any]]:
        """
        Process collected freeze samples, estimate resting angle θ_stopped,
        compute error relative to patch center, adjust τ_learned, log diagnostic entry,
        and persist updated calibration.
        """
        if not self._is_tracking or self._finalized:
            return None
        self._is_tracking = False
        self._finalized = True

        if len(self._freeze_samples) < 1:
            return None

        if len(self._freeze_samples) == 1:
            if not qte_vanished:
                # If freeze window elapsed while QTE was still on screen, a single sample cannot prove stillness (< 2.0° drift)
                return None
            stopped_angle = self._freeze_samples[0][1]
        else:
            # Unwrap angles relative to first sample to compute circular median/mean
            angles = [s[1] for s in self._freeze_samples]
            ref = angles[0]
            unwrapped = [ref + (((a - ref + 180.0) % 360.0) - 180.0) for a in angles]

            # Verify needle stillness during freeze window:
            # The collected freeze samples must have angular variance/drift < 2.0° (proving the needle actually stopped).
            # If the needle is still moving (>= 2.0° movement), discard the hit from calibration.
            drift = max(unwrapped) - min(unwrapped)
            mean_val = sum(unwrapped) / len(unwrapped)
            var_val = sum((a - mean_val) ** 2 for a in unwrapped) / len(unwrapped)
            if drift >= 2.0 or var_val >= 2.0:
                return None

            median_val = sorted(unwrapped)[len(unwrapped) // 2]
            # Discard any outlier samples (e.g. from UI transition)
            stable = [a for a in unwrapped if abs(a - median_val) <= 2.5]
            if not stable:
                stable = unwrapped
            stopped_angle = (sum(stable) / len(stable)) % 360.0

        return self.update_learned_latency(
            stopped_angle=stopped_angle,
            trigger_angle=self._trigger_angle,
            angular_velocity=self._trigger_velocity,
            patch_start=self._patch_start,
            patch_end=self._patch_end,
            patch_center=self._patch_center,
            patch_span=self._patch_span,
            is_chained=self._is_chained
        )

    def update_learned_latency(
        self,
        stopped_angle: float,
        trigger_angle: float,
        angular_velocity: float,
        patch_start: float,
        patch_end: float,
        patch_center: float,
        patch_span: float,
        log_entry: bool = True,
        is_chained: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Calculate error, update learned latency parameter, persist to config, and write to log.
        """
        error = self.calculate_angular_error(stopped_angle, patch_center)
        if abs(error) > 20.0:
            # Outlier rejection: a real hit error is never > 20°; reject sweeping needle transition
            return None

        result = self.classify_hit(stopped_angle, patch_start, patch_end, patch_center, patch_span)
        delta_tau = self.calculate_latency_adjustment(error, angular_velocity, result)

        if not self.speed_calibration:
            self.speed_calibration.append({"speed": angular_velocity, "latency_ms": 14.96})

        # Find nearest anchor
        nearest_idx = 0
        min_diff = float('inf')
        for i, anchor in enumerate(self.speed_calibration):
            diff = abs(anchor["speed"] - angular_velocity)
            if diff < min_diff:
                min_diff = diff
                nearest_idx = i

        if min_diff > 50:
            new_anchor = {"speed": angular_velocity, "latency_ms": self.get_interpolated_latency(angular_velocity)}
            self.speed_calibration.append(new_anchor)
            self.speed_calibration.sort(key=lambda x: x["speed"])
            nearest_idx = self.speed_calibration.index(new_anchor)

        anchor = self.speed_calibration[nearest_idx]
        lat_before = anchor["latency_ms"]

        lat_after = max(self.min_latency_ms, min(self.max_latency_ms, lat_before + delta_tau))
        
        # Soft cap proportional to speed
        max_allowed_lead = patch_span / 2.0
        max_allowed_lat = (max_allowed_lead * 1000.0) / max(1.0, anchor["speed"])

        if lat_after > max_allowed_lat:
            lat_after = max_allowed_lat

        lat_after = round(lat_after, 2)
        anchor["latency_ms"] = lat_after
        self.last_used_anchor = anchor

        if self.persist_config:
            update_persisted_config({"speed_calibration": self.speed_calibration}, self.config_path)

        if log_entry:
            self.log_calibration_entry(
                w=angular_velocity,
                trig=trigger_angle,
                stop=stopped_angle,
                p_start=patch_start,
                p_end=patch_end,
                p_center=patch_center,
                err=error,
                lat_before=lat_before,
                lat_after=lat_after,
                result=result,
                is_chained=is_chained
            )

        return {
            'stopped_angle': stopped_angle,
            'patch_center': patch_center,
            'error': error,
            'result': result,
            'delta_tau': delta_tau,
            'latency_before': lat_before,
            'latency_after': lat_after,
            'anchor_speed': anchor["speed"]
        }

    def log_calibration_entry(
        self,
        w: float,
        trig: float,
        stop: float,
        p_start: float,
        p_end: float,
        p_center: float,
        err: float,
        lat_before: float,
        lat_after: float,
        result: str,
        is_chained: bool = False
    ) -> None:
        """
        Append clean, detailed diagnostic entry to calibration.log.
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        anchor_speed = self.last_used_anchor["speed"] if self.last_used_anchor else w
        lead_angle = w * (lat_before / 1000.0)
        chained_str = "yes" if is_chained else "no"
        entry = (
            f"[{now_str}] HIT | Speed: {w:.1f}°/s | Triggered: {trig:.1f}° | Stopped: {stop:.1f}° | "
            f"Patch: [{p_start:.1f}°..{p_end:.1f}°] (Center: {p_center:.1f}°) | "
            f"Error: {err:+.1f}° | Latency: {lat_before:.1f}ms -> {lat_after:.1f}ms | "
            f"Lead: {lead_angle:.1f}° | Anchor: {anchor_speed:.0f}°/s @ {lat_after:.1f}ms | "
            f"Chained: {chained_str} | Result: {result}\n"
        )
        try:
            log_dir = os.path.dirname(self.log_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass


# ============================================================================
# QTE Detection & Geometry Lookup Tables (LUT)
# ============================================================================

class QTEDetector:
    """
    Sub-millisecond QTE analysis using adaptive spacebar glyph geometry and polar tracking.
    Detects:
    1. QTE Presence: dynamic scan for central dark spacebar box + white bracket glyph [_]
       with automatic sub-pixel center estimation and UI scaling adaptation (R ≈ 65..95px).
    2. Red Rotating Needle: high red contrast line at radii scaled to ring size.
    3. White Success Patch: thick white arc with dark border contrast detection.
    """
    MIN_NEEDLE_SCORE = 35.0

    def __init__(
        self,
        crop_size: int = 320,
        hit_position: str = "start",
        offset_degrees: float = 0.0,
        lead_degrees: float = 0.0,
        latency_ms: float = 0.0,
        min_needle_score: float = 35.0,
        trigger_delay_ms: float = 0.0,
        learned_latency_ms: Optional[float] = None,
        config_path: str = "config.json",
        calibration_engine: Optional[AdaptiveCalibrationEngine] = None,
        enable_adaptive_calibration: bool = True,
        verbose_logging: bool = False
    ):
        self.crop_size = crop_size
        self.cx = crop_size // 2
        self.cy = crop_size // 2
        self.hit_position = hit_position.lower()
        self.offset_degrees = offset_degrees
        self.lead_degrees = lead_degrees
        self.latency_ms = latency_ms
        self.min_needle_score = float(min_needle_score)
        self.trigger_delay_ms = float(trigger_delay_ms)
        self.base_delay_s = self.trigger_delay_ms / 1000.0
        self.config_path = config_path
        self.verbose_logging = verbose_logging

        # Setup adaptive calibration engine
        if calibration_engine is not None:
            self.calibration_engine = calibration_engine
        elif enable_adaptive_calibration:
            self.calibration_engine = AdaptiveCalibrationEngine(
                config_path=config_path,
                min_needle_score=self.min_needle_score
            )
        else:
            self.calibration_engine = None
        
        # State tracking for the current active QTE
        self.is_qte_active = False
        self.cached_cx = self.cx
        self.cached_cy = self.cy
        self.cached_r = 83
        self.cached_patch_start: Optional[float] = None
        self.cached_patch_end: Optional[float] = None
        self.cached_patch_center: Optional[float] = None
        self.cached_patch_span: Optional[float] = None
        self.cached_target_angle: Optional[float] = None
        self.prev_needle_angle: Optional[float] = None
        self.prev_needle_time: Optional[float] = None
        self.angular_velocity: float = 0.0
        self.has_triggered_current_qte = False
        self.last_trigger_time: float = 0.0
        self.triggered_patch_center: Optional[float] = None
        self.qte_start_time = 0.0
        self.qte_frames = 0
        self.absent_frames = 0
        self.chain_hit_count: int = 0
        self._reset_velocity_on_next_sample: bool = False
        self._current_frame_buf: Optional[Any] = None
        self._current_frame_glyph: Optional[Tuple[bool, int, int, int, int]] = None
        self._presence_geom: Optional[Tuple[int, int, int]] = None
        self._last_ring_center: Optional[Tuple[int, int, int]] = None
        self._last_rearm_scan_time: float = 0.0
        self._cached_rearm_patch: Optional[Tuple[float, float, float, float]] = None

    def _get_buffer_dims(self, buf, width: Optional[int] = None, height: Optional[int] = None) -> Tuple[int, int]:
        """Dynamically detect buffer dimensions from buffer length and parameters."""
        buf_len = len(buf) if buf is not None else 0
        if buf_len <= 0:
            return self.crop_size, self.crop_size

        if width is not None and height is not None and width * height * 4 == buf_len:
            return width, height

        num_pixels = buf_len // 4
        sq = int(math.isqrt(num_pixels))
        if sq * sq == num_pixels and sq > 0:
            return sq, sq

        if width is not None and width > 0 and buf_len % (width * 4) == 0:
            return width, buf_len // (width * 4)

        return self.crop_size, self.crop_size

    def reset(self) -> None:
        """Reset state between QTE events or test frames."""
        self.is_qte_active = False
        self.cached_cx = self.cx
        self.cached_cy = self.cy
        self.cached_r = 83
        self.cached_patch_start = None
        self.cached_patch_end = None
        self.cached_patch_center = None
        self.cached_patch_span = None
        self.cached_target_angle = None
        self.prev_needle_angle = None
        self.prev_needle_time = None
        self.angular_velocity = 0.0
        self.has_triggered_current_qte = False
        self.last_trigger_time = 0.0
        self.triggered_patch_center = None
        self.chain_hit_count = 0
        self._reset_velocity_on_next_sample = False
        self.qte_start_time = 0.0
        self.qte_frames = 0
        self.absent_frames = 0
        self._current_frame_buf = None
        self._current_frame_glyph = None
        self._presence_geom = None
        self._last_ring_center = None
        self._last_rearm_scan_time = 0.0
        self._cached_rearm_patch = None
        if getattr(self, 'calibration_engine', None) is not None and self.calibration_engine._is_tracking:
            self.calibration_engine.on_frame(time.perf_counter(), None, 0.0, False)
            self.calibration_engine._is_tracking = False
            self.calibration_engine._finalized = True

    def record_trigger(
        self,
        trigger_time: Optional[float] = None,
        trigger_angle: Optional[float] = None,
        angular_velocity: Optional[float] = None,
        patch_start: Optional[float] = None,
        patch_end: Optional[float] = None,
        patch_center: Optional[float] = None,
        patch_span: Optional[float] = None,
        is_chained: Optional[bool] = None
    ) -> None:
        """Forward confirmed trigger event to the adaptive calibration engine."""
        if getattr(self, 'calibration_engine', None) is not None:
            t = trigger_time if trigger_time is not None else time.perf_counter()
            ang = trigger_angle if trigger_angle is not None else (self.prev_needle_angle or 0.0)
            vel = angular_velocity if angular_velocity is not None else self.angular_velocity
            ps = patch_start if patch_start is not None else (self.cached_patch_start or 0.0)
            pe = patch_end if patch_end is not None else (self.cached_patch_end or 0.0)
            pc = patch_center if patch_center is not None else (self.cached_patch_center or 0.0)
            span = patch_span if patch_span is not None else (self.cached_patch_span or 0.0)
            if is_chained is None:
                # If chain_hit_count > 1 (incremented on trigger), this hit was chained
                is_chained = (self.chain_hit_count > 1)
            self.calibration_engine.record_trigger(
                trigger_time=t,
                trigger_angle=ang,
                angular_velocity=vel,
                patch_start=ps,
                patch_end=pe,
                patch_center=pc,
                patch_span=span,
                is_chained=is_chained
            )

    def revert_trigger(self) -> None:
        """Revert trigger state if keyboard controller was unable to dispatch the keystroke."""
        self.has_triggered_current_qte = False
        self.last_trigger_time = 0.0
        self.triggered_patch_center = None
        self._last_rearm_scan_time = 0.0
        self._cached_rearm_patch = None
        if self.chain_hit_count > 0:
            self.chain_hit_count -= 1
        if getattr(self, 'calibration_engine', None) is not None:
            self.calibration_engine._is_tracking = False
            self.calibration_engine._finalized = True

    def find_glyph_and_geometry(self, buf, width: Optional[int] = None, height: Optional[int] = None) -> Tuple[bool, int, int, int, int]:
        """
        Scan for spacebar [_] bracket glyph within the central area and estimate circle center + radius.
        Uses adaptive relative contrast, needle occlusion tolerance, and multi-point upright voting.
        Returns: (found: bool, cx: int, cy: int, R: int, bar_len: int)
        """
        w, h = self._get_buffer_dims(buf, width, height)
        nom_cx, nom_cy = w // 2, h // 2

        if buf is None or len(buf) < w * h * 4:
            return (False, nom_cx, nom_cy, 83, 0)

        if getattr(self, '_current_frame_buf', None) is buf and getattr(self, '_current_frame_glyph', None) is not None:
            return self._current_frame_glyph

        candidates = []

        # Scan rows with step=2 for efficiency across center area (covers offset and centering variance)
        for y in range(max(10, nom_cy - 65), min(h - 10, nom_cy + 75), 2):
            row_off = y * w * 4
            in_run = False
            run_start = 0
            runs = []
            for x in range(max(10, nom_cx - 65), min(w - 10, nom_cx + 66)):
                off = row_off + x * 4
                b, g, r = buf[off], buf[off + 1], buf[off + 2]
                lum = (int(r) + int(g) + int(b)) / 3.0
                is_white_or_needle = (lum > 125 and r > 100) or (r > 130 and r - max(g, b) > 35)
                if is_white_or_needle:
                    if not in_run:
                        in_run = True
                        run_start = x
                        run_len = 1
                    else:
                        run_len += 1
                else:
                    if in_run:
                        runs.append((run_start, run_len))
                        in_run = False
            if in_run:
                runs.append((run_start, run_len))

            for r_start, r_len in runs:
                if 20 <= r_len <= 90:
                    bar_cx = r_start + r_len // 2
                    # Tighten scanning around center: tolerance <= 35px
                    if abs(bar_cx - nom_cx) > 35:
                        continue
                    left_edge = r_start
                    right_edge = r_start + r_len - 1

                    # Inner dark button face check across width of bracket
                    inner_lums = []
                    step_x = max(1, r_len // 10)
                    for in_x in range(left_edge + 4, right_edge - 3, step_x):
                        for in_dy in [2, 3, 4, 5]:
                            if y - in_dy < 0:
                                continue
                            off_in = ((y - in_dy) * w + in_x) * 4
                            inner_lums.append((buf[off_in] + buf[off_in + 1] + buf[off_in + 2]) / 3.0)
                    lum_in = sum(inner_lums) / len(inner_lums) if inner_lums else 999.0

                    lt_votes = 0
                    rt_votes = 0
                    for dy in [2, 3, 4]:
                        if y - dy < 0:
                            continue
                        max_lt = max((int(buf[((y - dy)*w + left_edge + dx)*4]) + int(buf[((y - dy)*w + left_edge + dx)*4 + 1]) + int(buf[((y - dy)*w + left_edge + dx)*4 + 2])) / 3.0 for dx in [-1, 0, 1] if 0 <= left_edge + dx < w)
                        max_rt = max((int(buf[((y - dy)*w + right_edge + dx)*4]) + int(buf[((y - dy)*w + right_edge + dx)*4 + 1]) + int(buf[((y - dy)*w + right_edge + dx)*4 + 2])) / 3.0 for dx in [-1, 0, 1] if 0 <= right_edge + dx < w)
                        if max_lt > 80:
                            lt_votes += 1
                        if max_rt > 80:
                            rt_votes += 1

                    dy_below = max(4, int(round(r_len * 0.08)) + 1)
                    if y + dy_below >= h:
                        continue
                    off_below = ((y + dy_below) * w + bar_cx) * 4
                    lum_below = (int(buf[off_below]) + int(buf[off_below + 1]) + int(buf[off_below + 2])) / 3.0

                    bar_lum = sum((int(buf[(y*w + x)*4]) + int(buf[(y*w + x)*4+1]) + int(buf[(y*w + x)*4+2]))/3.0 for x in range(r_start, r_start+r_len)) / r_len

                    if lt_votes >= 2 and rt_votes >= 2 and bar_lum - lum_in > 40 and lum_in < 65 and bar_lum - lum_below > 25:
                        score = (bar_lum - lum_in) * r_len - 8.0 * abs(bar_cx - nom_cx)
                        candidates.append((score, y, bar_cx, r_len))

        if not candidates:
            res = (False, nom_cx, nom_cy, 83, 0)
            self._current_frame_buf = buf
            self._current_frame_glyph = res
            return res

        best_score = max(c[0] for c in candidates)
        best_c = [c for c in candidates if c[0] == best_score][0]
        cluster = [c for c in candidates if abs(c[2] - best_c[2]) <= 4 and abs(c[3] - best_c[3]) <= 4]

        top_cand = min(cluster, key=lambda c: c[1])
        top_y = top_cand[1]
        est_cx = top_cand[2]
        r_len = top_cand[3]
        est_cy = top_y - int(round(r_len * 0.05))
        est_r = max(50, min(120, int(round(r_len * 1.48))))
        res = (True, est_cx, est_cy, est_r, r_len)
        self._current_frame_buf = buf
        self._current_frame_glyph = res
        return res

    def check_ring_boundary(self, buf, cx: Optional[int] = None, cy: Optional[int] = None, R: Optional[int] = None, width: Optional[int] = None) -> bool:
        """
        Verify the presence of a dark circular ring boundary at candidate radius R.
        In Roblox Violence District, the circular skill check track has dark boundaries
        on the interior (and exterior) compared to the active ring / progress arc.
        Searches +/- 6px vertical offsets (dy in [0, -6, 6]) to accommodate UI center variance.
        """
        w, h = self._get_buffer_dims(buf, width)
        if buf is None or len(buf) < w * h * 4:
            return False
        if cx is None: cx = w // 2
        if cy is None: cy = h // 2
        if R is None: R = self.cached_r if self.is_qte_active else 83

        r_in = int(round(R * 0.82))

        def _sample_ring_at(ccy: int) -> Tuple[float, float, float]:
            dark_in = 0
            lum_ring_sum = 0.0
            lum_in_sum = 0.0
            total = 0
            for cos_a, sin_a in _TRIG_RING:
                px_in = int(round(cx + r_in * cos_a))
                py_in = int(round(ccy + r_in * sin_a))
                best_l = 0.0
                for dr in (-2, -1, 0, 1, 2):
                    px = int(round(cx + (R + dr) * cos_a))
                    py = int(round(ccy + (R + dr) * sin_a))
                    if 0 <= px < w and 0 <= py < h:
                        off = (py * w + px) * 4
                        l_val = (buf[off] + buf[off + 1] + buf[off + 2]) / 3.0
                        if l_val > best_l:
                            best_l = l_val
                if 0 <= px_in < w and 0 <= py_in < h:
                    off_in = (py_in * w + px_in) * 4
                    lin = (buf[off_in] + buf[off_in + 1] + buf[off_in + 2]) / 3.0
                    if lin < 80:
                        dark_in += 1
                    lum_in_sum += lin
                    lum_ring_sum += best_l
                    total += 1
            if total >= 10:
                in_dark = dark_in / total
                avg_ring = lum_ring_sum / total
                contrast = avg_ring - (lum_in_sum / total)
                return in_dark, avg_ring, contrast
            return 0.0, 0.0, -999.0

        # Fast-path: Check nominal offset dy=0 first
        in_dark0, avg_ring0, contrast0 = _sample_ring_at(cy)
        if in_dark0 >= 0.65 and avg_ring0 >= 90.0 and contrast0 >= 30.0:
            self._last_ring_center = (cx, cy, R)
            return True

        # If nominal offset has virtually no ring brightness or contrast, early exit
        if contrast0 < 10.0 or avg_ring0 < 50.0:
            self._last_ring_center = (cx, cy, R)
            return False

        best_contrast = contrast0
        best_in_dark = in_dark0
        best_avg_ring = avg_ring0
        best_ccy = cy

        for dy in [-6, 6, -12, 12, -20, 20, -36, 36]:
            ccy = cy + dy
            in_d, avg_r, cont = _sample_ring_at(ccy)
            if cont > best_contrast:
                best_contrast = cont
                best_in_dark = in_d
                best_avg_ring = avg_r
                best_ccy = ccy
                if best_in_dark >= 0.65 and best_avg_ring >= 90.0 and best_contrast >= 30.0:
                    self._last_ring_center = (cx, best_ccy, R)
                    return True

        self._last_ring_center = (cx, best_ccy, R)
        return best_in_dark >= 0.65 and best_avg_ring >= 90.0 and best_contrast >= 30.0

    def check_presence(self, buf) -> bool:
        """
        Verify presence of QTE center spacebar icon or ring+patch+needle.
        Robust against particle effects, needle occlusion, and varying backgrounds.
        Requires multi-feature validation:
        1. Structural presence (central [_] glyph icon OR dark circular ring boundary)
        2. Real red needle with high red dominance (needle_score >= 35.0)
        3. Valid white patch on that ring.
        """
        if buf is None or len(buf) < 16:
            return False

        # If QTE is currently active, maintain state via hysteresis
        if self.is_qte_active:
            g_found, _, _, _, _ = self.find_glyph_and_geometry(buf)
            if g_found:
                return True
            try:
                _, n_score = self.detect_needle(buf, self.cached_cx, self.cached_cy, self.cached_r)
            except TypeError:
                _, n_score = self.detect_needle(buf, self.cached_cx, self.cached_cy, self.cached_r)
            if n_score >= self.min_needle_score:
                return True
            if self.check_ring_boundary(buf, self.cached_cx, self.cached_cy, self.cached_r):
                return True
            return False

        # Multi-feature validation for idle -> active transition:
        # Pathway 1: Central [_] glyph detected
        g_found, g_cx, g_cy, g_r, _ = self.find_glyph_and_geometry(buf)
        if g_found:
            try:
                _, n_score = self.detect_needle(buf, g_cx, g_cy, g_r)
            except TypeError:
                _, n_score = self.detect_needle(buf, g_cx, g_cy, g_r)
            if n_score >= self.min_needle_score:
                try:
                    patch = self.detect_white_patch(buf, g_cx, g_cy, g_r)
                except TypeError:
                    patch = self.detect_white_patch(buf, g_cx, g_cy, g_r)
                if patch is not None:
                    self._presence_geom = (g_cx, g_cy, g_r)
                    return True

        # Pathway 2: Dark circular ring boundary fallback (when center glyph is occluded)
        w, h = self._get_buffer_dims(buf)
        nom_cx, nom_cy = w // 2, h // 2
        # Fast-path: Test nominal radius (R=83) first
        if self.check_ring_boundary(buf, nom_cx, nom_cy, 83):
            rcx, rcy, rr = getattr(self, '_last_ring_center', (nom_cx, nom_cy, 83))
            try:
                _, n_score = self.detect_needle(buf, rcx, rcy, rr)
            except TypeError:
                _, n_score = self.detect_needle(buf, rcx, rcy, rr)
            if n_score >= self.min_needle_score:
                try:
                    patch = self.detect_white_patch(buf, rcx, rcy, rr)
                except TypeError:
                    patch = self.detect_white_patch(buf, rcx, rcy, rr)
                if patch is not None:
                    self._presence_geom = (rcx, rcy, rr)
                    return True
        else:
            for r_cand in (67, 95, 75, 60, 90, 100, 105, 110):
                if self.check_ring_boundary(buf, nom_cx, nom_cy, r_cand):
                    rcx, rcy, rr = getattr(self, '_last_ring_center', (nom_cx, nom_cy, r_cand))
                    try:
                        _, n_score = self.detect_needle(buf, rcx, rcy, rr)
                    except TypeError:
                        _, n_score = self.detect_needle(buf, rcx, rcy, rr)
                    if n_score >= self.min_needle_score:
                        try:
                            patch = self.detect_white_patch(buf, rcx, rcy, rr)
                        except TypeError:
                            patch = self.detect_white_patch(buf, rcx, rcy, rr)
                        if patch is not None:
                            self._presence_geom = (rcx, rcy, rr)
                            return True

        return False

    def detect_needle(self, buf, cx: Optional[int] = None, cy: Optional[int] = None, R: Optional[int] = None, width: Optional[int] = None) -> Tuple[float, float]:
        """
        Detect angle of rotating red needle.
        Bounds-checked to prevent out-of-bounds buffer access on shifted coordinates.
        Returns: (needle_angle_deg, peak_red_contrast)
        """
        w, h = self._get_buffer_dims(buf, width)
        if buf is None or len(buf) < w * h * 4:
            return (0.0, 0.0)
        nom_cx, nom_cy = w // 2, h // 2
        if cx is None or cy is None or R is None:
            if self.is_qte_active:
                cx = self.cached_cx if cx is None else cx
                cy = self.cached_cy if cy is None else cy
                R = self.cached_r if R is None else R
            else:
                found, g_cx, g_cy, g_r, _ = self.find_glyph_and_geometry(buf, w, h)
                cx = g_cx if found else (nom_cx if cx is None else cx)
                cy = g_cy if found else (nom_cy if cy is None else cy)
                R = g_r if found else (83 if R is None else R)
        radii = [int(round(R * f)) for f in [0.45, 0.55, 0.65, 0.75]]
        best_deg = 0
        max_red = -999.0
        scores = []
        max_r_vals = []
        for deg, (cos_a, sin_a) in enumerate(_TRIG_360):
            red_sum = 0
            valid_samples = 0
            max_r_along_ray = 0
            for r in radii:
                px = int(round(cx + r * cos_a))
                py = int(round(cy + r * sin_a))
                if 0 <= px < w and 0 <= py < h:
                    off = (py * w + px) * 4
                    b = buf[off]
                    g = buf[off + 1]
                    r_val = buf[off + 2]
                    if r_val > max_r_along_ray:
                        max_r_along_ray = r_val
                    max_gb = g if g > b else b
                    red_sum += (r_val - max_gb)
                    valid_samples += 1
            avg_red = (red_sum / valid_samples) if valid_samples > 0 else 0.0
            scores.append(avg_red)
            max_r_vals.append(max_r_along_ray)
            if avg_red > max_red:
                max_red = avg_red
                best_deg = deg

        # Require that the candidate needle ray actually contains bright red pixels (not dark brown/wood)
        if max_r_vals and max_r_vals[best_deg] < 115:
            max_red = 0.0

        # Broad red rejection: a true needle peak occupies <= 25-30 degrees
        high_score_count = sum(1 for s in scores if s >= self.min_needle_score)
        if high_score_count > 32:
            max_red = 0.0

        # Sub-degree centroid refinement over peak +/- 2 degrees
        num = 0.0
        den = 0.0
        for offset in range(-2, 3):
            d = (best_deg + offset) % 360
            weight = max(0.0, scores[d] - 30.0)
            num += offset * weight
            den += weight
        sub_deg = (best_deg + (num / den if den > 0 else 0.0)) % 360.0
        return sub_deg, max_red

    def detect_white_patch(self, buf, cx: Optional[int] = None, cy: Optional[int] = None, R: Optional[int] = None, width: Optional[int] = None) -> Optional[Tuple[float, float, float, float]]:
        """
        Detect the white target arc on the circular ring.
        Bounds-checked to prevent out-of-bounds buffer access on shifted coordinates.
        Returns: (start_deg, end_deg, center_deg, span_deg) or None
        """
        w, h = self._get_buffer_dims(buf, width)
        if buf is None or len(buf) < w * h * 4:
            return None
        nom_cx, nom_cy = w // 2, h // 2
        if cx is None or cy is None or R is None:
            if self.is_qte_active:
                cx = self.cached_cx if cx is None else cx
                cy = self.cached_cy if cy is None else cy
                R = self.cached_r if R is None else R
            else:
                found, g_cx, g_cy, g_r, _ = self.find_glyph_and_geometry(buf, w, h)
                cx = g_cx if found else (nom_cx if cx is None else cx)
                cy = g_cy if found else (nom_cy if cy is None else cy)
                R = g_r if found else (83 if R is None else R)
        bright_angles = []
        angle_lums = {}
        dr_list = [-3, -2, -1, 0, 1, 2, 3]

        for i, (cos_a, sin_a) in enumerate(_TRIG_720):
            a = i * 0.5
            cnt = 0
            valid = 0
            lum_sum = 0.0
            for dr in dr_list:
                r_curr = R + dr
                px = int(round(cx + r_curr * cos_a))
                py = int(round(cy + r_curr * sin_a))
                if 0 <= px < w and 0 <= py < h:
                    valid += 1
                    off = (py * w + px) * 4
                    lum = (int(buf[off + 2]) + int(buf[off + 1]) + int(buf[off])) / 3.0
                    lum_sum += lum
                    if (buf[off + 2] > 170 and buf[off + 1] > 120 and lum > 150) or (buf[off + 2] > 180 and lum > 135):
                        cnt += 1
            if (valid >= 6 and cnt >= 4) or (valid == 5 and cnt >= 4) or (valid in (3, 4) and cnt >= 2) or (valid in (1, 2) and cnt >= 1):
                bright_angles.append(a)
                angle_lums[a] = lum_sum / valid if valid > 0 else 0.0

        if not bright_angles:
            return None

        # Group contiguous angle runs (step is 0.5 degrees, tolerate needle occlusion gap up to 3.5 degrees)
        runs = []
        curr_run = [bright_angles[0]]
        for a in bright_angles[1:]:
            if a - curr_run[-1] <= 3.5:
                curr_run.append(a)
            else:
                runs.append(curr_run)
                curr_run = [a]
        runs.append(curr_run)

        # Handle wrap-around across 0° / 360°
        if len(runs) > 1 and (360.0 - runs[-1][-1] + runs[0][0]) <= 3.5:
            runs[0] = runs[-1] + runs[0]
            runs.pop()

        # Find the white patch run (the white patch has an angular span of ~5° to ~18°)
        candidates = []
        for r in runs:
            start = r[0]
            end = r[-1]
            span = (end - start) % 360.0
            if 5.0 <= span <= 18.0:
                center = (start + span / 2.0) % 360.0
                avg_lum = sum(angle_lums[a] for a in r) / len(r) if r else 0.0
                candidates.append((avg_lum, len(r), start, end, center, span))

        if not candidates:
            return None

        # Prioritize candidates by highest brightness, then longest sample run / span length
        candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
        best = candidates[0]
        return (best[2], best[3], best[4], best[5])

    def calculate_target_angle(self, patch_start: float, patch_end: float, patch_center: float, patch_span: float, lead_degrees: Optional[float] = None) -> float:
        """Calculate desired trigger angle based on config offset, and lead compensation with safety clamp."""
        lead = lead_degrees if lead_degrees is not None else getattr(self, 'lead_degrees', 0.0)

        # Target patch center minus lead
        target = (patch_center - lead) % 360.0
        target = (target + self.offset_degrees) % 360.0

        # Safety clamp: never before patch_start
        dist = (target - patch_start) % 360.0
        if dist > patch_span:
            target = patch_start

        return target

    def calculate_effective_delay(self, base_delay_s: Optional[float] = None, needle_angle: Optional[float] = None) -> float:
        """
        Calculate velocity-compensated trigger delay.
        When hit_position == 'start', clamps the effective delay so that delay_s * omega does not
        exceed ~60-70% of the patch span, preventing overshooting on fast needle rotations
        while ensuring the needle NEVER triggers early before patch start and slower spins
        still get the full base delay. If the needle crossed the patch into the late success zone,
        returns 0.0 delay to trigger immediately.
        """
        delay_s = base_delay_s if base_delay_s is not None else getattr(self, 'base_delay_s', 0.0)
        if delay_s <= 0.0:
            return 0.0
        if self.cached_patch_start is None or self.cached_patch_span is None:
            return delay_s

        p_start = self.cached_patch_start
        p_span = self.cached_patch_span
        n_angle = needle_angle if needle_angle is not None else self.prev_needle_angle
        if n_angle is None:
            return delay_s

        dist_from_start = (n_angle - p_start) % 360.0
        if dist_from_start > 180.0:
            # Needle is before patch start (should not happen on trigger, but guard)
            return delay_s

        # If needle is already at or past the white patch end, trigger immediately with 0 delay (late hit)
        if dist_from_start >= p_span:
            return 0.0

        remaining_budget = max(0.0, p_span - dist_from_start)

        omega = self.angular_velocity
        if omega <= 50.0:
            # Velocity is low or unknown: if needle is already in the back third of the patch,
            # scale down delay so it doesn't overshoot
            if dist_from_start > 0.65 * p_span:
                scale = max(0.0, (p_span - dist_from_start) / (0.35 * p_span))
                return delay_s * scale
            return delay_s

        # High angular velocity:
        # We want the needle during the delay to advance by at most ~65% of patch span,
        # and not past 80% of the remaining budget to avoid overshooting the white patch.
        # Slower spins (e.g. 300°/s) where delay_s * omega lands inside the budget retain full delay.
        max_spin_advance = 0.65 * p_span
        max_budget_advance = remaining_budget * 0.80
        allowed_advance = min(max_spin_advance, max_budget_advance)

        max_delay_s = allowed_advance / omega
        return max(0.0, min(delay_s, max_delay_s))

    def evaluate(self, buf, now: Optional[float] = None) -> Dict[str, Any]:
        """
        Evaluate full frame state.
        Returns a dictionary with detection telemetry and trigger decision.
        """
        if buf is None or len(buf) < 16:
            self._current_frame_buf = None
            self._current_frame_glyph = None
            return {
                'present': False,
                'needle_angle': None,
                'needle_score': 0.0,
                'patch_start': None,
                'patch_end': None,
                'patch_center': None,
                'patch_span': None,
                'target_angle': None,
                'angular_velocity': 0.0,
                'dynamic_lead': 0.0,
                'effective_delay_s': 0.0,
                'should_trigger': False,
                'reason': 'Empty buffer',
                'is_chained': False,
                'chain_hit_count': 0
            }

        if getattr(self, '_current_frame_buf', None) is not buf:
            self._current_frame_buf = None
            self._current_frame_glyph = None
        buf_w, buf_h = self._get_buffer_dims(buf)
        found = self.check_presence(buf)
        now = time.perf_counter() if now is None else float(now)

        if not found and not self.is_qte_active:
            if getattr(self, 'calibration_engine', None) is not None and self.calibration_engine._is_tracking:
                self.calibration_engine.on_frame(now, None, 0.0, False)
            self._current_frame_buf = None
            self._current_frame_glyph = None
            return {
                'present': False,
                'needle_angle': None,
                'needle_score': 0.0,
                'patch_start': None,
                'patch_end': None,
                'patch_center': None,
                'patch_span': None,
                'target_angle': None,
                'angular_velocity': 0.0,
                'dynamic_lead': 0.0,
                'effective_delay_s': 0.0,
                'should_trigger': False,
                'reason': 'No QTE on screen',
                'is_chained': False,
                'chain_hit_count': 0
            }

        if found:
            g_found, g_cx, g_cy, g_r, _ = self.find_glyph_and_geometry(buf, buf_w, buf_h)
            if g_found:
                self.cached_cx = g_cx
                self.cached_cy = g_cy
                self.cached_r = g_r
            elif getattr(self, '_presence_geom', None):
                self.cached_cx, self.cached_cy, self.cached_r = self._presence_geom
            self.absent_frames = 0
            if not self.is_qte_active:
                self.is_qte_active = True
                self.qte_start_time = now
                self.qte_frames = 0
                self.has_triggered_current_qte = False
                self.last_trigger_time = 0.0
                self.triggered_patch_center = None
                self.chain_hit_count = 0
        else:
            self.absent_frames += 1
            if getattr(self, 'calibration_engine', None) is not None and self.calibration_engine._is_tracking:
                self.calibration_engine.on_frame(now, None, 0.0, False)
            if self.absent_frames >= 3:
                self.reset()
                return {
                    'present': False,
                    'needle_angle': None,
                    'needle_score': 0.0,
                    'patch_start': None,
                    'patch_end': None,
                    'patch_center': None,
                    'patch_span': None,
                    'target_angle': None,
                    'angular_velocity': 0.0,
                    'dynamic_lead': 0.0,
                    'effective_delay_s': 0.0,
                    'should_trigger': False,
                    'reason': 'QTE disappeared',
                    'is_chained': False,
                    'chain_hit_count': 0
                }
            return {
                'present': False,
                'needle_angle': None,
                'needle_score': 0.0,
                'patch_start': self.cached_patch_start,
                'patch_end': self.cached_patch_end,
                'patch_center': self.cached_patch_center,
                'patch_span': self.cached_patch_span,
                'target_angle': self.cached_target_angle,
                'angular_velocity': self.angular_velocity,
                'dynamic_lead': 0.0,
                'effective_delay_s': 0.0,
                'should_trigger': False,
                'reason': 'QTE dropped frame / noise',
                'is_chained': (self.chain_hit_count > 0),
                'chain_hit_count': self.chain_hit_count
            }

        self.qte_frames += 1

        # Detect needle
        try:
            needle_res = self.detect_needle(buf, self.cached_cx, self.cached_cy, self.cached_r, buf_w)
        except TypeError:
            try:
                needle_res = self.detect_needle(buf, self.cached_cx, self.cached_cy, self.cached_r)
            except TypeError:
                needle_res = self.detect_needle(buf)
        needle_angle, needle_score = needle_res
        has_real_needle = (needle_score >= self.min_needle_score)

        # Dynamic angular velocity calculation:
        # Measure clockwise angular step across consecutive frames (only with verified red needle)
        if has_real_needle and self.prev_needle_angle is not None and self.prev_needle_time is not None:
            dt = now - self.prev_needle_time
            d_theta = (needle_angle - self.prev_needle_angle) % 360.0
            if 0.35 <= d_theta <= 180.0:
                if 0.0045 <= dt <= 0.25:
                    raw_velocity = d_theta / dt
                    if raw_velocity >= 50.0:
                        if (
                            self.angular_velocity == 0.0
                            or getattr(self, '_reset_velocity_on_next_sample', False)
                            or raw_velocity < 0.5 * self.angular_velocity
                            or raw_velocity > 1.8 * self.angular_velocity
                        ):
                            # Instant speedometer adaptation on sudden slowdown, speedup, new patch, or start
                            self.angular_velocity = raw_velocity
                            self._reset_velocity_on_next_sample = False
                        else:
                            # Smooth with Exponential Moving Average (EMA)
                            self.angular_velocity = 0.35 * raw_velocity + 0.65 * self.angular_velocity
            elif dt > 0.5:
                self.angular_velocity = 0.0
                self._reset_velocity_on_next_sample = True

        # Velocity-based dynamic lead compensation:
        # If adaptive calibration engine is present, calculate continuous velocity lead:
        # Δθ_lead(ω) = ω * τ_learned (strictly clamped by safe margin)
        cal_lead = 0.0
        if getattr(self, 'calibration_engine', None) is not None:
            cal_lead = self.calibration_engine.calculate_dynamic_lead(self.angular_velocity)

        manual_lead = (self.angular_velocity * (self.latency_ms / 1000.0)) if self.latency_ms > 0.0 and self.angular_velocity > 0.0 else 0.0
        clamped_manual_lead = max(0.0, min(30.0, manual_lead))

        if self.hit_position == "start":
            # In 'start' hit position, only use calibrated velocity lead; strictly clamp for 0% early tolerance
            dynamic_lead = cal_lead
        else:
            dynamic_lead = self.lead_degrees + cal_lead + clamped_manual_lead



        # Continuous Skill Check Re-arming:
        # If the macro has already triggered the current check, monitor for patch change or exit
        if self.has_triggered_current_qte:
            time_since_trigger = now - self.last_trigger_time if self.last_trigger_time > 0.0 else 999.0
            is_past_triggered_patch = False
            if self.cached_patch_start is not None and self.cached_patch_span is not None:
                dist_from_start = (needle_angle - self.cached_patch_start) % 360.0
                is_past_triggered_patch = (self.cached_patch_span + 2.0) <= dist_from_start <= 180.0

            # Re-arm check: after 40ms minimum key hold duration, check for new patch or patch exit
            if time_since_trigger >= 0.040:
                # Throttle heavy white patch detection during re-arm tracking (at most once every 15ms)
                if (now - getattr(self, '_last_rearm_scan_time', 0.0)) >= 0.015:
                    try:
                        curr_patch = self.detect_white_patch(buf, self.cached_cx, self.cached_cy, self.cached_r, buf_w)
                    except TypeError:
                        try:
                            curr_patch = self.detect_white_patch(buf, self.cached_cx, self.cached_cy, self.cached_r)
                        except TypeError:
                            curr_patch = self.detect_white_patch(buf)
                    self._last_rearm_scan_time = now
                    self._cached_rearm_patch = curr_patch
                else:
                    curr_patch = getattr(self, '_cached_rearm_patch', None)

                if curr_patch is None:
                    # Patch disappeared between sequential checks: unlock and prepare for next patch
                    self.cached_patch_start = None
                    self.cached_patch_end = None
                    self.cached_patch_center = None
                    self.cached_patch_span = None
                    self.cached_target_angle = None
                    self.has_triggered_current_qte = False
                    self.triggered_patch_center = None
                    self._reset_velocity_on_next_sample = True
                    self._last_rearm_scan_time = 0.0
                    self._cached_rearm_patch = None
                else:
                    cp_start, cp_end, cp_center, cp_span = curr_patch
                    diff_from_triggered = 999.0
                    if self.triggered_patch_center is not None:
                        diff_from_triggered = abs((cp_center - self.triggered_patch_center + 180) % 360 - 180)

                    if diff_from_triggered >= 6.0:
                        # New white patch appeared at a different angle: re-arm immediately!
                        self.cached_patch_start = cp_start
                        self.cached_patch_end = cp_end
                        self.cached_patch_center = cp_center
                        self.cached_patch_span = cp_span
                        self.cached_target_angle = self.calculate_target_angle(cp_start, cp_end, cp_center, cp_span, lead_degrees=dynamic_lead)
                        self.has_triggered_current_qte = False
                        self.triggered_patch_center = None
                        self._reset_velocity_on_next_sample = True
                        self._last_rearm_scan_time = 0.0
                        self._cached_rearm_patch = None
                    elif is_past_triggered_patch and time_since_trigger >= 0.080:
                        # Needle has moved past triggered patch and minimum key separation elapsed
                        self.has_triggered_current_qte = False
                        self.triggered_patch_center = None
                        self._reset_velocity_on_next_sample = True
                        self._last_rearm_scan_time = 0.0
                        self._cached_rearm_patch = None
                    elif time_since_trigger >= 0.20:
                        # Fallback for identical angle patch after needle made full loop or rotated far away
                        dist_from_start = (needle_angle - cp_start) % 360.0
                        dist_to_start = (cp_start - needle_angle) % 360.0
                        if dist_from_start > (cp_span + 15.0) and dist_to_start > 15.0:
                            self.has_triggered_current_qte = False
                            self.triggered_patch_center = None
                            self._reset_velocity_on_next_sample = True
                            self._last_rearm_scan_time = 0.0
                            self._cached_rearm_patch = None

        # Detect or maintain locked white patch coordinates
        if self.cached_patch_center is None:
            try:
                detected_patch = self.detect_white_patch(buf, self.cached_cx, self.cached_cy, self.cached_r, buf_w)
            except TypeError:
                try:
                    detected_patch = self.detect_white_patch(buf, self.cached_cx, self.cached_cy, self.cached_r)
                except TypeError:
                    detected_patch = self.detect_white_patch(buf)

            if detected_patch is not None:
                p_start, p_end, p_center, p_span = detected_patch
                is_old_ghost = False
                if self.triggered_patch_center is not None and (now - self.last_trigger_time) < 0.080:
                    if abs((p_center - self.triggered_patch_center + 180) % 360 - 180) <= 6.0:
                        is_old_ghost = True

                if not is_old_ghost:
                    self.cached_patch_start = p_start
                    self.cached_patch_end = p_end
                    self.cached_patch_center = p_center
                    self.cached_patch_span = p_span
                    self.cached_target_angle = self.calculate_target_angle(p_start, p_end, p_center, p_span, lead_degrees=dynamic_lead)
                    self._reset_velocity_on_next_sample = True
        elif self.cached_patch_start is not None:
            # Refresh target angle dynamically based on current angular velocity lead
            self.cached_target_angle = self.calculate_target_angle(
                self.cached_patch_start,
                self.cached_patch_end,
                self.cached_patch_center,
                self.cached_patch_span,
                lead_degrees=dynamic_lead
            )

        should_trigger = False
        reason = ""

        if not self.has_triggered_current_qte and self.cached_patch_start is not None and has_real_needle:
            target = self.cached_target_angle
            p_start = self.cached_patch_start
            p_end = self.cached_patch_end
            p_span = self.cached_patch_span

            # Angular distance from patch start clockwise
            dist_from_start = (needle_angle - p_start) % 360.0
            dist_to_start = (p_start - needle_angle) % 360.0
            is_inside_patch = dist_from_start <= p_span
            lead_window = max(3.0, dynamic_lead)
            is_at_patch_lead = dist_to_start <= lead_window

            # Distance to/from target
            dist_from_target = (needle_angle - target) % 360.0
            dist_before_target = (target - needle_angle) % 360.0

            # Clockwise distance from target to patch end (valid trigger sector)
            target_to_end = (p_end - target) % 360.0
            max_allowed_sector = p_span + max(5.0, dynamic_lead) + 5.0
            is_in_target_sector = (dist_from_target <= target_to_end) and (target_to_end <= max_allowed_sector) and (target_to_end <= max(60.0, max_allowed_sector))

            # Condition A: Clockwise crossing target angle
            # A1: tight window for accurate per-frame crossing (<=30° step)
            # A2: confirmed lag-spike crossing (>30° to <=180°): require target is strictly
            #     contained in [prev, curr] arc AND needle lands inside/past patch start
            if self.prev_needle_angle is not None:
                step = (needle_angle - self.prev_needle_angle) % 360.0
                dist_to_target = (target - self.prev_needle_angle) % 360.0
                dist_to_start_from_prev = (p_start - self.prev_needle_angle) % 360.0
                crossing_buffer = 0.0 if (self.hit_position == "start" and dynamic_lead <= 0.0) else 1.0
                crossed_target = (dist_to_target <= (step + crossing_buffer))
                crossed_start = (dist_to_start_from_prev <= (step + crossing_buffer))

                if 0.05 <= step <= 30.0 and (crossed_target or crossed_start or is_inside_patch):
                    if self.hit_position == "start":
                        # In Violence District, early before patch start = FAIL,
                        # but late on/after white patch = SUCCESSFUL (Good zone).
                        max_lead = max(0.0, dynamic_lead)
                        landing_dist = (needle_angle + max_lead - p_start) % 360.0
                        safe_landing = (1.0 <= landing_dist <= (p_span + 25.0))
                        if is_inside_patch:
                            should_trigger = True
                            reason = f"Clockwise entering white patch [{p_start:.1f}°..{p_end:.1f}°] (prev={self.prev_needle_angle:.1f}°, curr={needle_angle:.1f}°)"
                        elif max_lead > 0.0 and safe_landing and (crossed_target or is_in_target_sector):
                            should_trigger = True
                            reason = f"Clockwise crossing lead target {target:.1f}° [{p_start:.1f}°..{p_end:.1f}°] (lead={dynamic_lead:.1f}°, prev={self.prev_needle_angle:.1f}°, curr={needle_angle:.1f}°)"
                        elif dist_from_start <= (p_span + 25.0):
                            should_trigger = True
                            reason = f"Clockwise sweep across white patch [{p_start:.1f}°..{p_end:.1f}°] (prev={self.prev_needle_angle:.1f}°, curr={needle_angle:.1f}°: late hit)"
                    else:
                        should_trigger = True
                        reason = f"Clockwise crossing target {target:.1f}° (prev={self.prev_needle_angle:.1f}°, curr={needle_angle:.1f}°, lead={dynamic_lead:.1f}°)"
                elif 30.0 < step <= 180.0 and (dist_to_target < step or dist_to_start_from_prev < step):
                    max_lead = max(0.0, dynamic_lead)
                    landing_dist = (needle_angle + max_lead - p_start) % 360.0
                    safe_landing = (1.0 <= landing_dist <= (p_span + 30.0))
                    if is_inside_patch or (max_lead > 0.0 and safe_landing and (dist_to_target < step or is_in_target_sector)) or (dist_from_start <= (p_span + 30.0)):
                        should_trigger = True
                        reason = f"Clockwise jump past target {target:.1f}° (prev={self.prev_needle_angle:.1f}°, curr={needle_angle:.1f}°, lead={dynamic_lead:.1f}°)"

            # Condition B: Needle is at or past target inside patch/lead zone, or entering arrival lead window
            if not should_trigger:
                if is_in_target_sector or is_inside_patch:
                    if self.hit_position == "start":
                        max_lead = max(0.0, dynamic_lead)
                        landing_dist = (needle_angle + max_lead - p_start) % 360.0
                        safe_landing = (1.0 <= landing_dist <= (p_span + 25.0))
                        if is_inside_patch:
                            should_trigger = True
                            reason = f"Needle inside white patch [{p_start:.1f}°..{p_end:.1f}°]"
                        elif max_lead > 0.0 and safe_landing and is_in_target_sector:
                            should_trigger = True
                            reason = f"Needle at lead target {target:.1f}° [{p_start:.1f}°..{p_end:.1f}°] (lead={dynamic_lead:.1f}°)"
                    else:
                        should_trigger = True
                        if is_inside_patch:
                            reason = f"Needle at target inside white patch [{p_start:.1f}°..{p_end:.1f}°]"
                        else:
                            reason = f"Needle at target lead angle {target:.1f}° (approaching patch [{p_start:.1f}°..{p_end:.1f}°], lead={dynamic_lead:.1f}°)"
                elif self.hit_position != "start" and dist_before_target <= 2.0 and (is_inside_patch or is_at_patch_lead):
                    should_trigger = True
                    reason = f"Needle at target leading edge arrival lead {target:.1f}° [{p_start:.1f}°..{p_end:.1f}°]"

            # Condition C: First-frame detection or static image where needle is already over patch or at entrance
            if not should_trigger and self.prev_needle_angle is None:
                if self.hit_position == "start":
                    if is_inside_patch:
                        should_trigger = True
                        reason = f"Needle detected directly over white patch [{p_start:.1f}°..{p_end:.1f}°]"
                else:
                    if is_inside_patch or is_at_patch_lead or is_in_target_sector:
                        should_trigger = True
                        reason = f"Needle detected directly over white patch [{p_start:.1f}°..{p_end:.1f}°]"

            if self.hit_position == "start" and dist_from_start > 180.0:
                should_trigger = False
                reason = "Approaching patch start (early lock)"

            if should_trigger:
                self.has_triggered_current_qte = True
                self.last_trigger_time = now
                self.triggered_patch_center = self.cached_patch_center
                self.chain_hit_count += 1
                self._last_rearm_scan_time = 0.0
                self._cached_rearm_patch = None

        is_chained = (self.chain_hit_count > 1) if should_trigger else (self.chain_hit_count > 0)

        if not should_trigger and not has_real_needle and not reason:
            reason = f"Needle contrast too low ({needle_score:.1f} < {self.min_needle_score:.1f})"

        # Only advance prev_needle_time/angle when needle moves beyond sub-pixel noise (or on first frame / timeout)
        # to prevent sampling aliasing against discrete display refresh rates
        if has_real_needle and (self.prev_needle_angle is None or (needle_angle - self.prev_needle_angle) % 360.0 >= 0.35 or (now - (self.prev_needle_time or now)) > 0.5):
            self.prev_needle_angle = needle_angle
            self.prev_needle_time = now

        effective_delay_s = self.calculate_effective_delay(self.base_delay_s, needle_angle)

        # Feed post-trigger frames to calibration engine for freeze detection
        if getattr(self, 'calibration_engine', None) is not None and self.calibration_engine._is_tracking:
            self.calibration_engine.on_frame(
                now=now,
                needle_angle=needle_angle if has_real_needle else None,
                needle_score=needle_score,
                qte_present=True
            )

        self._current_frame_buf = None
        self._current_frame_glyph = None

        if getattr(self, 'verbose_logging', False) and has_real_needle and self.cached_patch_start is not None:
            print(f"[VERBOSE] Frame: Speed={self.angular_velocity:.1f}°/s | Lead={dynamic_lead:.1f}° (Target={self.cached_target_angle:.1f}°) | Trigger={should_trigger} ({reason})")

        return {
            'present': True,
            'needle_angle': needle_angle,
            'needle_score': needle_score,
            'patch_start': self.cached_patch_start,
            'patch_end': self.cached_patch_end,
            'patch_center': self.cached_patch_center,
            'patch_span': self.cached_patch_span,
            'target_angle': self.cached_target_angle,
            'angular_velocity': self.angular_velocity,
            'dynamic_lead': dynamic_lead,
            'effective_delay_s': effective_delay_s,
            'should_trigger': should_trigger,
            'reason': reason,
            'is_chained': is_chained,
            'chain_hit_count': self.chain_hit_count
        }

# ============================================================================
# Hotkey & Configuration Management
# ============================================================================

class HotkeyManager:
    """Non-blocking passive GetAsyncKeyState edge detector for global hotkeys."""
    def __init__(self, toggle_key: str = "F1", exit_key: str = "F2"):
        self.vk_toggle = VK_MAP.get(toggle_key.upper(), 0x70)
        self.vk_exit = VK_MAP.get(exit_key.upper(), 0x71)
        self.toggle_name = toggle_key.upper()
        self.exit_name = exit_key.upper()
        # Initialize to current physical key state to avoid spurious edge trigger on startup
        self.was_toggle_down = (user32.GetAsyncKeyState(self.vk_toggle) & 0x8000) != 0
        self.was_exit_down = (user32.GetAsyncKeyState(self.vk_exit) & 0x8000) != 0

    def poll(self) -> Tuple[bool, bool]:
        """Returns: (toggle_pressed, exit_pressed)"""
        is_toggle = (user32.GetAsyncKeyState(self.vk_toggle) & 0x8000) != 0
        is_exit = (user32.GetAsyncKeyState(self.vk_exit) & 0x8000) != 0

        toggle_edge = is_toggle and not self.was_toggle_down
        exit_edge = is_exit and not self.was_exit_down

        self.was_toggle_down = is_toggle
        self.was_exit_down = is_exit
        return toggle_edge, exit_edge



# ============================================================================
# Main Execution Loop
# ============================================================================

def run_macro(config_path: str = "config.json") -> None:
    """Run the live ultra-fast QTE detection and auto-press loop."""
    enable_high_dpi()
    ensure_desktop_attached()
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass
    cfg = load_or_create_config(config_path)

    top_offset = int(cfg.get("top_bar_offset", 0))
    crop_size = int(cfg.get("crop_size", 320))
    override = cfg.get("center_override")
    res_cfg = cfg.get("resolution")

    primary_mon = get_primary_monitor()
    roblox_rect = find_roblox_window()

    if override and isinstance(override, (list, tuple)) and len(override) == 2:
        cx, cy = int(override[0]), int(override[1])
        center_mode = f"Manual override ({cx}, {cy})"
    elif roblox_rect is not None:
        rx, ry, rw, rh = roblox_rect
        cx = rx + rw // 2
        cy = ry + (rh // 2) + top_offset
        center_mode = f"Roblox Window ({rw}x{rh} at [{rx}, {ry}] -> Center: ({cx}, {cy}))"
    elif res_cfg and isinstance(res_cfg, (list, tuple)) and len(res_cfg) == 2:
        screen_w, screen_h = int(res_cfg[0]), int(res_cfg[1])
        cx = primary_mon["left"] + screen_w // 2
        cy = primary_mon["top"] + (screen_h // 2) + top_offset
        center_mode = f"Configured resolution on Primary Monitor ({screen_w}x{screen_h} -> Center: ({cx}, {cy}))"
    else:
        # Default: Primary / Main monitor (Roblox display)
        m_left = primary_mon["left"]
        m_top = primary_mon["top"]
        m_w = primary_mon["width"]
        m_h = primary_mon["height"]
        cx = m_left + m_w // 2
        cy = m_top + (m_h // 2) + top_offset
        center_mode = f"Primary Monitor ({m_w}x{m_h} at [{m_left}, {m_top}] -> Center: ({cx}, {cy}))"

    x1 = cx - crop_size // 2
    y1 = cy - crop_size // 2

    # Instantiate modules
    capture = ScreenCapture(x1, y1, crop_size, crop_size)
    detector = QTEDetector(
        crop_size=crop_size,
        hit_position=str(cfg.get("hit_position", "start")),
        offset_degrees=float(cfg.get("offset_degrees", 0.0)),
        lead_degrees=float(cfg.get("lead_degrees", 0.0)),
        latency_ms=float(cfg.get("latency_ms", 0.0)),
        learned_latency_ms=float(cfg.get("learned_latency_ms", 0.0)),
        min_needle_score=float(cfg.get("min_needle_score", 35.0)),
        trigger_delay_ms=float(cfg.get("trigger_delay_ms", 0)),
        config_path=config_path,
        verbose_logging=bool(cfg.get("verbose_logging", False))
    )
    keyboard = KeyboardController(
        scancode=SPACEBAR_SCANCODE,
        hold_ms=int(cfg.get("hold_duration_ms", 35)),
        debounce_s=float(cfg.get("debounce_seconds", 0.08))
    )
    hotkeys = HotkeyManager(
        toggle_key=str(cfg.get("toggle_key", "F1")),
        exit_key=str(cfg.get("exit_key", "F2"))
    )

    is_paused = False
    status_interval = float(cfg.get("status_interval_ms", 250)) / 1000.0
    trigger_delay_s = float(cfg.get("trigger_delay_ms", 0)) / 1000.0
    last_status_time = time.perf_counter()
    frame_count = 0
    hit_count = 0
    total_latency = 0.0
    was_present = False

    cal_info = ""
    if getattr(detector, 'calibration_engine', None):
        cal_eng = detector.calibration_engine
        if getattr(cal_eng, 'speed_calibration', None):
            cal_info = f", {len(cal_eng.speed_calibration)} speed anchors"
        else:
            cal_info = f", cal_latency: {cal_eng.learned_latency_ms:.1f}ms"

    print("=" * 68)
    print("  Lunar Tear // Violence District QTE Auto-Skillcheck Macro")
    print("=" * 68)
    print(f"  [Primary Display] : {primary_mon['width']}x{primary_mon['height']} at ({primary_mon['left']}, {primary_mon['top']})")
    print(f"  [Target Center]   : {center_mode}")
    print(f"  [Capture Region]  : {crop_size}x{crop_size} from ({x1}, {y1})")
    print(f"  [Hit Position]    : {detector.hit_position} (offset: {detector.offset_degrees:+.1f}°, lead: {detector.lead_degrees:.1f}°, latency comp: {detector.latency_ms:.0f}ms{cal_info})")
    print(f"  [Keystroke Sim]   : Dual DirectInput (0x39) + VirtualKey (0x20)")
    print(f"  [Timing / Hold]   : Hold {keyboard.hold_s*1000:.0f}ms | Debounce {keyboard.debounce_s:.2f}s")
    print(f"  [Hotkeys]         : {hotkeys.toggle_name} = Toggle Pause/Resume | {hotkeys.exit_name} = Clean Exit")
    print("=" * 68)
    print("  Macro is RUNNING. Waiting for QTE skill checks...\n")

    try:
        while True:
            t_start = time.perf_counter()

            # Poll hotkeys
            toggle_hit, exit_hit = hotkeys.poll()
            if exit_hit:
                print("\n[EXIT] Clean shutdown signal received. Releasing keys and stopping.")
                break
            if toggle_hit:
                is_paused = not is_paused
                if is_paused:
                    keyboard.release_all()
                status_str = "PAUSED (Standby)" if is_paused else "ACTIVE (Monitoring)"
                print(f"\n[HOTKEY] Macro is now: {status_str}")

            # Keep keyboard controller updated (non-blocking key release)
            keyboard.update()

            if is_paused:
                time.sleep(0.01)
                continue

            # Dynamic Roblox Window Tracker (checks periodically if override not active)
            if override is None and (frame_count % 120 == 0):
                cur_roblox = find_roblox_window()
                if cur_roblox is not None:
                    rx, ry, rw, rh = cur_roblox
                    new_cx = rx + rw // 2
                    new_cy = ry + (rh // 2) + top_offset
                    if new_cx != cx or new_cy != cy:
                        cx, cy = new_cx, new_cy
                        x1 = cx - crop_size // 2
                        y1 = cy - crop_size // 2
                        capture.update_region(x1, y1, crop_size, crop_size)
                        print(f"\n[DYNAMIC LOCK] Roblox window detected ({rw}x{rh})! Recentered capture to ({cx}, {cy})")

            # Capture frame via mss
            buf = capture.capture()

            # Evaluate frame
            result = detector.evaluate(buf)
            if result['present'] and not was_present:
                t_now = time.strftime('%H:%M:%S', time.localtime())
                print(f"\n[{t_now}] [QTE DETECTED] Center prompt recognized! Tracking needle...")
            was_present = result['present']
            if result['should_trigger']:
                eff_delay_s = result.get('effective_delay_s', trigger_delay_s)
                if eff_delay_s > 0.0:
                    time.sleep(eff_delay_s)
                t_trig = time.perf_counter()
                pressed = keyboard.trigger()
                if pressed:
                    hit_count += 1
                    t_hit = time.strftime('%H:%M:%S', time.localtime())
                    vel_str = f" | Velocity: {result.get('angular_velocity', 0.0):.0f}°/s | Lead: {result.get('dynamic_lead', 0.0):.1f}°" if result.get('angular_velocity', 0.0) > 0.0 else ""
                    delay_str = f" | Delay: {eff_delay_s*1000:.1f}ms (clamped from {trigger_delay_s*1000:.0f}ms)" if trigger_delay_s > 0 and eff_delay_s < trigger_delay_s else (f" | Delay: {eff_delay_s*1000:.1f}ms" if trigger_delay_s > 0 else "")
                    print(
                        f"\n[{t_hit}] [>>> HIT #{hit_count} <<<] QTE Triggered!\n"
                        f"  -> Needle: {result['needle_angle']:.1f}° | Score: {result['needle_score']:.1f}{vel_str}{delay_str}\n"
                        f"  -> Patch: [{result['patch_start']:.1f}° .. {result['patch_end']:.1f}°] "
                        f"(Center: {result['patch_center']:.1f}°)\n"
                        f"  -> Target: {result['target_angle']:.1f}° | Action: Spacebar (DirectInput 0x39 + VK 0x20)\n"
                        f"  -> Reason: {result['reason']}\n"
                    )
                    if getattr(detector, 'calibration_engine', None) is not None:
                        detector.calibration_engine.record_trigger(
                            trigger_time=t_trig,
                            trigger_angle=result['needle_angle'],
                            angular_velocity=result.get('angular_velocity', 0.0),
                            patch_start=result['patch_start'],
                            patch_end=result['patch_end'],
                            patch_center=result['patch_center'],
                            patch_span=result['patch_span'],
                            is_chained=result.get('is_chained', False)
                        )
                else:
                    # Debounce cooldown or key busy: revert trigger flag so detector retries next frame
                    detector.revert_trigger()

            t_end = time.perf_counter()
            frame_time = t_end - t_start
            total_latency += frame_time
            frame_count += 1

            # Periodic status dashboard update
            if t_end - last_status_time >= status_interval:
                fps = frame_count / (t_end - last_status_time)
                avg_lat_ms = (total_latency / frame_count) * 1000.0 if frame_count > 0 else 0.0
                qte_status = "ACTIVE" if result['present'] else "Idle"
                if getattr(detector, 'calibration_engine', None):
                    cal_eng = detector.calibration_engine
                    last_a = getattr(cal_eng, 'last_used_anchor', None)
                    if last_a:
                        cal_str = f" | Cal: {last_a['speed']:.0f}°/s@{last_a['latency_ms']:.1f}ms"
                    else:
                        cal_str = f" | Cal: {cal_eng.learned_latency_ms:.1f}ms"
                else:
                    cal_str = ""
                if sys.stdout is not None:
                    sys.stdout.write(
                        f"\r[STATUS: RUNNING] FPS: {fps:6.1f} | Latency: {avg_lat_ms:4.2f}ms | QTE: {qte_status:<6} | Hits: {hit_count:<3}{cal_str}"
                    )
                    sys.stdout.flush()
                last_status_time = t_end
                frame_count = 0
                total_latency = 0.0

            # Yield briefly to maintain CPU efficiency (<2ms frame time)
            poll_ms = cfg.get("poll_interval_ms", 0)
            if poll_ms is not None and poll_ms > 0:
                time.sleep(poll_ms / 1000.0)
            else:
                time.sleep(0)

    except KeyboardInterrupt:
        print("\n[INTERRUPT] Exiting macro.")
    finally:
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        keyboard.release_all()
        capture.close()
        print("[SHUTDOWN] Lunar Tear cleanup complete. Exited cleanly.")

# ============================================================================
# Offline Screenshot Verification Test Suite (--test)
# ============================================================================

def run_tests(image_paths: Optional[List[str]] = None) -> bool:
    """
    Test QTE detection logic against provided screenshot files.
    Verifies:
    1. QTE presence detection
    2. Red needle angle and score
    3. White patch start, end, span, and center angle
    4. Target calculation and trigger decision
    """
    try:
        from PIL import Image
    except ImportError:
        print("[TEST ERROR] Pillow is required to run the image file test suite. Please install pillow.")
        return False

    if not image_paths:
        screenshots_dir = os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")
        default_paths = [
            os.path.join(screenshots_dir, "Violence district complete.png"),
            os.path.join(screenshots_dir, "Violence district progress.png"),
            os.path.join(screenshots_dir, "Violence district complete (2).png"),
            os.path.join(screenshots_dir, "Violence district progress (2).png"),
            os.path.join(screenshots_dir, "complete.png"),
            os.path.join(screenshots_dir, "progress.png"),
            os.path.join(screenshots_dir, "complete.jpg"),
            os.path.join(screenshots_dir, "progress.jpg"),
            os.path.join(screenshots_dir, "progress (2).png"),
            os.path.join(screenshots_dir, "complete (2).png")
        ]
        image_paths = [p for p in default_paths if os.path.exists(p)]

    if not image_paths:
        print("[TEST ERROR] No test screenshot images found.")
        print("Usage: python qte_macro.py --test <path/to/screenshot.png>")
        return False

    print("=" * 72)
    print("  Violence District QTE Detection Verification Test Suite")
    print("=" * 72)

    detector = QTEDetector(crop_size=320, hit_position="start", offset_degrees=0.0)
    all_passed = True

    for p in image_paths:
        filename = os.path.basename(p)
        print(f"\n--- Testing: {filename} ---")
        try:
            im = Image.open(p).convert("RGBA")
        except Exception as e:
            print(f"  [FAIL] Could not load image: {e}")
            all_passed = False
            continue

        width, height = im.size
        # Fullscreen center: default (width // 2, height // 2) with 320x320 crop
        cx = width // 2
        cy = height // 2
        crop_size = 320
        crop = im.crop((cx - crop_size // 2, cy - crop_size // 2, cx + crop_size // 2, cy + crop_size // 2))

        # Convert crop to 32-bit BGRA bytes matching GDI DIBSection memory layout
        raw_bytes = bytearray(crop_size * crop_size * 4)
        crop_rgba = crop.tobytes()
        for i in range(0, len(crop_rgba), 4):
            raw_bytes[i] = crop_rgba[i + 2]      # Blue
            raw_bytes[i + 1] = crop_rgba[i + 1]  # Green
            raw_bytes[i + 2] = crop_rgba[i]      # Red
            raw_bytes[i + 3] = crop_rgba[i + 3]  # Alpha

        # Reset detector between tests so each screenshot is independently tested
        detector.reset()

        # Test evaluation
        res = detector.evaluate(raw_bytes)
        
        # Determine expected status from filename
        is_complete_img = "complete" in filename.lower()
        is_progress_img = "progress" in filename.lower()

        print(f"  [1] QTE Present     : {res['present']} (Expected: True)")
        if not res['present']:
            print("  [FAIL] QTE presence was not detected!")
            all_passed = False
            continue

        print(f"  [2] Needle Angle    : {res['needle_angle']:.2f}° (Contrast Score: {res['needle_score']:.1f})")
        print(f"  [3] White Patch     : [{res['patch_start']:.2f}° .. {res['patch_end']:.2f}°] (Span: {res['patch_span']:.2f}°)")
        print(f"  [4] Patch Center    : {res['patch_center']:.2f}° (Target: {res['target_angle']:.2f}°)")
        print(f"  [5] Trigger State   : Triggered={res['should_trigger']} | Reason: '{res['reason']}'")

        # Validation assertions
        needle_in_patch = False
        if res['patch_start'] is not None and res['patch_end'] is not None:
            dist = (res['needle_angle'] - res['patch_start']) % 360.0
            dist_to_start = (res['patch_start'] - res['needle_angle']) % 360.0
            needle_in_patch = (dist <= res['patch_span']) or (dist_to_start <= 2.5)

        if is_complete_img:
            if needle_in_patch and res['should_trigger']:
                print("  [PASS] Successfully verified COMPLETE state: Needle is inside white patch and triggered!")
            else:
                print(f"  [FAIL] Expected needle inside white patch for complete state! (in_patch={needle_in_patch}, triggered={res['should_trigger']})")
                all_passed = False
        elif is_progress_img:
            if not needle_in_patch and not res['should_trigger']:
                print("  [PASS] Successfully verified PROGRESS state: Needle is rotating towards patch without early trigger.")
            else:
                print("  [FAIL] Expected progress state to not trigger prematurely!")
                all_passed = False

    print("\n" + "=" * 72)
    if all_passed:
        print("  ALL VERIFICATION CHECKS PASSED (100% ACCURACY ACROSS ALL SCREENSHOTS)")
    else:
        print("  SOME VERIFICATION CHECKS FAILED")
    print("=" * 72)
    return all_passed

def test_keypress() -> None:
    """Interactive countdown test allowing user to verify Spacebar keypress in any window."""
    enable_high_dpi()
    print("=" * 64)
    print("  Violence District Macro - Keystroke Verification Test")
    print("=" * 64)
    print("  Testing Spacebar simulation (DirectInput 0x39 + VK 0x20)...")
    print("  Click into Notepad, your browser, or a text box now!")
    print()
    for i in range(3, 0, -1):
        print(f"  Firing Spacebar in {i}...")
        time.sleep(1.0)
    print()
    print("  >>> SENDING SPACEBAR NOW <<<")
    kb = KeyboardController(scancode=SPACEBAR_SCANCODE, hold_ms=50)
    kb.trigger()
    time.sleep(0.06)
    kb.update()
    print("  [DONE] Spacebar sent! Check if a space appeared or your video paused.")
    print("=" * 64)

# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Violence District Roblox QTE Auto-Skillcheck Macro")
    parser.add_argument("--test", action="store_true", help="Run detection test suite against screenshot images")
    parser.add_argument("--test-key", action="store_true", help="Test Spacebar keystroke simulation with a 3-second countdown")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config.json")
    parser.add_argument("images", nargs="*", help="Optional image paths for --test mode")

    args = parser.parse_args()

    if args.test_key:
        test_keypress()
        sys.exit(0)
    elif args.test:
        success = run_tests(args.images if args.images else None)
        sys.exit(0 if success else 1)
    else:
        run_macro(args.config)

if __name__ == "__main__":
    main()
