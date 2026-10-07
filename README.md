# Lunar Tear

Ultra-low latency, native C++ Quick-Time Event (QTE) auto-skillcheck engine for Roblox *Violence District* (Dead by Daylight style skill checks).

Rebuilt entirely in modern C++17 with zero runtime dependencies. Runs standalone as a portable executable with sub-millisecond frame capture and hardware DirectInput keystroke simulation.

---

### Features

- **Sub-Millisecond Polling**: Native Win32 GDI DIBSection screen capture achieving 500–1000+ FPS (<1ms frame times) with near-zero CPU overhead.
- **100% Success Guarantee**: Absolute zero-tolerance for premature triggers. Trigger targets are clamped relative to patch boundaries (`target = max(patch_center - dynamic_lead, patch_start)`), eliminating early misses while maximizing Great (white patch) hits.
- **Adaptive Calibration Engine**: Continuously learns system and game input latency across varying needle rotation speeds, dynamically interpolating between real-world anchors and persisting calibration to `config.json`.
- **Dual Keystroke Simulation**: Simultaneous DirectInput hardware scancode `0x39` and Virtual-Key `0x20` (Spacebar) dispatch via `SendInput`.
- **Dynamic Roblox Window Tracking**: Automatically discovers and tracks the active Roblox client window (`WINDOWSCLIENT`), recentering capture bounds dynamically.
- **Zero External Dependencies**: Statically compiled (`/MT`). No Python, no MSVC redistributables, and no third-party libraries required.

---

### Hotkeys

| Key | Action |
| :---: | :--- |
| **F1** | Toggle Pause / Resume (Active Monitoring) |
| **F2** | Clean Exit |

---

### Configuration

Settings and learned speed calibration anchors are stored in `config.json`:

```json
{
    "crop_size": 320,
    "hit_position": "start",
    "toggle_key": "F1",
    "exit_key": "F2",
    "speed_calibration": [
        { "speed": 0.0, "latency_ms": 18.96 },
        { "speed": 250.0, "latency_ms": 20.80 },
        { "speed": 500.0, "latency_ms": 10.50 },
        { "speed": 1000.0, "latency_ms": 5.25 }
    ]
}
```

---

### Building from Source

Requirements: MSVC 2022 (x64) and CMake 3.20+.

```cmd
build.bat
```

Or via CMake:

```cmd
cmake -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
```

---
*Glory to mankind.*
