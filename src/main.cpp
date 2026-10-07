#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <iostream>
#include <iomanip>
#include <string>
#include <vector>
#include <chrono>
#include <thread>
#include <windows.h>
#include <timeapi.h>

#include "config.hpp"
#include "screen_capture.hpp"
#include "keyboard_controller.hpp"
#include "window_helper.hpp"
#include "hotkey_manager.hpp"
#include "calibration_engine.hpp"
#include "qte_detector.hpp"
#include "synthetic_test.hpp"

using namespace lunartear;

static double get_time_now_s(const LARGE_INTEGER& freq) {
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    return static_cast<double>(now.QuadPart) / static_cast<double>(freq.QuadPart);
}

static std::string get_formatted_time() {
    auto now_tp = std::chrono::system_clock::now();
    auto now_c = std::chrono::system_clock::to_time_t(now_tp);
    std::tm tm_buf;
    localtime_s(&tm_buf, &now_c);
    char buf[32];
    std::strftime(buf, sizeof(buf), "%H:%M:%S", &tm_buf);
    return buf;
}

void test_keypress() {
    enable_high_dpi();
    std::cout << "================================================================\n";
    std::cout << "  Violence District Macro - Keystroke Verification Test\n";
    std::cout << "================================================================\n";
    std::cout << "  Testing Spacebar simulation (DirectInput 0x39 + VK 0x20)...\n";
    std::cout << "  Click into Notepad, your browser, or a text box now!\n\n";

    for (int i = 3; i > 0; --i) {
        std::cout << "  Firing Spacebar in " << i << "...\n";
        Sleep(1000);
    }
    std::cout << "\n  >>> SENDING SPACEBAR NOW <<<\n";
    KeyboardController kb(0x39, 50, 0.08);
    kb.trigger();
    Sleep(60);
    kb.update();
    std::cout << "  [DONE] Spacebar sent! Check if a space appeared or your video paused.\n";
    std::cout << "================================================================\n";
}

int run_test_suite() {
    std::cout << "================================================================\n";
    std::cout << "  Lunar Tear // Violence District Built-in Test Verification\n";
    std::cout << "================================================================\n\n";

    QTEDetector detector(320, "start");
    int passed = 0;
    int failed = 0;

    // Test 1: Bottom-left patch detection
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(144.0, 10.5), {255, 255, 255}, 30);
        auto res = detector.detect_white_patch(buf.data(), 320, 320, 160, 160, 83);
        if (res.has_value() && std::abs(res->start_deg - 144.0) <= 2.0) {
            std::cout << "  [PASS] Bottom-left patch detected: " << res->start_deg << "° (span: " << res->span_deg << "°)\n";
            passed++;
        } else {
            std::cout << "  [FAIL] Bottom-left patch detection failed\n";
            failed++;
        }
    }

    // Test 2: Top patch detection with bright background
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(265.0, 10.0), {255, 255, 255}, 160);
        auto res = detector.detect_white_patch(buf.data(), 320, 320, 160, 160, 83);
        if (res.has_value() && std::abs(res->start_deg - 265.0) <= 2.0) {
            std::cout << "  [PASS] Top patch detected under bright lum: " << res->start_deg << "°\n";
            passed++;
        } else {
            std::cout << "  [FAIL] Top patch detection under bright lum failed\n";
            failed++;
        }
    }

    // Test 3: Right patch wrapping 0°/360°
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(355.0, 10.0), {255, 255, 255}, 140);
        auto res = detector.detect_white_patch(buf.data(), 320, 320, 160, 160, 83);
        if (res.has_value() && std::abs(res->start_deg - 355.0) <= 2.0) {
            std::cout << "  [PASS] 0°/360° wraparound patch detected: " << res->start_deg << "°\n";
            passed++;
        } else {
            std::cout << "  [FAIL] 0°/360° wraparound patch detection failed\n";
            failed++;
        }
    }

    // Test 4: Needle detection
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::nullopt, {255, 255, 255}, 30, 200.0);
        auto res = detector.detect_needle(buf.data(), 320, 320, 160, 160, 83);
        if (res.second >= 35.0 && std::abs(res.first - 200.0) <= 2.0) {
            std::cout << "  [PASS] Needle angle detected: " << res.first << "° (score: " << res.second << ")\n";
            passed++;
        } else {
            std::cout << "  [FAIL] Needle angle detection failed\n";
            failed++;
        }
    }

    // Test 5: Early trigger safety (Needle at 354.5° approaching patch at [355°..5°] MUST NOT trigger)
    {
        detector.reset();
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(355.0, 10.0), {255, 255, 255}, 30, 354.5);
        auto eval = detector.evaluate(buf.data(), 320, 320, 0.0);
        if (!eval.should_trigger) {
            std::cout << "  [PASS] Early trigger safety: Needle at 354.5° before 355.0° patch did NOT trigger!\n";
            passed++;
        } else {
            std::cout << "  [FAIL] Early trigger safety violated! Needle triggered prematurely.\n";
            failed++;
        }
    }

    // Test 6: In-patch trigger (Needle at 356.0° inside patch at [355°..5°] MUST trigger)
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(355.0, 10.0), {255, 255, 255}, 30, 356.0);
        auto eval = detector.evaluate(buf.data(), 320, 320, 0.0);
        if (eval.should_trigger) {
            std::cout << "  [PASS] In-patch trigger: Needle at 356.0° triggered accurately inside patch!\n";
            passed++;
        } else {
            std::cout << "  [FAIL] Expected trigger inside patch!\n";
            failed++;
        }
    }

    std::cout << "\n================================================================\n";
    std::cout << "  Result: " << passed << " passed, " << failed << " failed.\n";
    std::cout << "================================================================\n";
    return (failed == 0) ? 0 : 1;
}

void run_macro(const std::string& config_path) {
    enable_high_dpi();
    ensure_desktop_attached();
    timeBeginPeriod(1);

    LARGE_INTEGER qpc_freq;
    QueryPerformanceFrequency(&qpc_freq);

    Config cfg = load_or_create_config(config_path);

    int top_offset = cfg.top_bar_offset;
    int crop_size = cfg.crop_size;

    MonitorRect primary_mon = get_primary_monitor();
    auto roblox_info = find_roblox_client();

    int cx = 0;
    int cy = 0;
    std::string center_mode;

    if (cfg.center_override.has_value()) {
        cx = cfg.center_override->first;
        cy = cfg.center_override->second;
        center_mode = "Manual override (" + std::to_string(cx) + ", " + std::to_string(cy) + ")";
    } else if (roblox_info.has_value()) {
        cx = roblox_info->x + roblox_info->width / 2;
        cy = roblox_info->y + (roblox_info->height / 2) + top_offset;
        center_mode = "Roblox Window (" + std::to_string(roblox_info->width) + "x" + std::to_string(roblox_info->height) +
                      " at [" + std::to_string(roblox_info->x) + ", " + std::to_string(roblox_info->y) + "] -> Center: (" +
                      std::to_string(cx) + ", " + std::to_string(cy) + "))";
    } else if (cfg.resolution.has_value()) {
        int sw = cfg.resolution->first;
        int sh = cfg.resolution->second;
        cx = primary_mon.left + sw / 2;
        cy = primary_mon.top + (sh / 2) + top_offset;
        center_mode = "Configured resolution (" + std::to_string(sw) + "x" + std::to_string(sh) + " -> Center: (" +
                      std::to_string(cx) + ", " + std::to_string(cy) + "))";
    } else {
        cx = primary_mon.left + primary_mon.width / 2;
        cy = primary_mon.top + (primary_mon.height / 2) + top_offset;
        center_mode = "Primary Monitor (" + std::to_string(primary_mon.width) + "x" + std::to_string(primary_mon.height) +
                      " at [" + std::to_string(primary_mon.left) + ", " + std::to_string(primary_mon.top) + "] -> Center: (" +
                      std::to_string(cx) + ", " + std::to_string(cy) + "))";
    }

    int x1 = cx - crop_size / 2;
    int y1 = cy - crop_size / 2;

    ScreenCapture capture(x1, y1, crop_size, crop_size);

    auto cal_engine = std::make_shared<AdaptiveCalibrationEngine>(
        config_path,
        "",
        cfg.speed_calibration,
        cfg.min_needle_score,
        true,
        cfg.verbose_logging
    );

    QTEDetector detector(
        crop_size,
        cfg.hit_position,
        cfg.offset_degrees,
        cfg.lead_degrees,
        cfg.latency_ms,
        cfg.min_needle_score,
        static_cast<double>(cfg.trigger_delay_ms),
        cal_engine,
        cfg.verbose_logging
    );

    KeyboardController keyboard(
        0x39,
        cfg.hold_duration_ms,
        cfg.debounce_seconds
    );

    HotkeyManager hotkeys(
        cfg.toggle_key,
        cfg.exit_key
    );

    bool is_paused = false;
    double status_interval = static_cast<double>(cfg.status_interval_ms) / 1000.0;
    double trigger_delay_s = static_cast<double>(cfg.trigger_delay_ms) / 1000.0;
    double last_status_time = get_time_now_s(qpc_freq);
    uint64_t frame_count = 0;
    int hit_count = 0;
    double total_latency = 0.0;
    bool was_present = false;

    std::string cal_info = ", " + std::to_string(cal_engine->speed_calibration().size()) + " speed anchors";

    std::cout << "====================================================================\n";
    std::cout << "  Lunar Tear // Violence District QTE Auto-Skillcheck (Native C++)\n";
    std::cout << "====================================================================\n";
    std::cout << "  [Primary Display] : " << primary_mon.width << "x" << primary_mon.height
              << " at (" << primary_mon.left << ", " << primary_mon.top << ")\n";
    std::cout << "  [Target Center]   : " << center_mode << "\n";
    std::cout << "  [Capture Region]  : " << crop_size << "x" << crop_size << " from (" << x1 << ", " << y1 << ")\n";
    std::cout << "  [Hit Position]    : " << detector.hit_position()
              << " (offset: " << std::showpos << detector.offset_degrees() << std::noshowpos
              << "°, lead: " << detector.lead_degrees()
              << "°, latency comp: " << detector.latency_ms() << "ms" << cal_info << ")\n";
    std::cout << "  [Keystroke Sim]   : Dual DirectInput (0x39) + VirtualKey (0x20)\n";
    std::cout << "  [Timing / Hold]   : Hold " << static_cast<int>(keyboard.hold_seconds() * 1000)
              << "ms | Debounce " << keyboard.debounce_seconds() << "s\n";
    std::cout << "  [Hotkeys]         : " << hotkeys.toggle_name() << " = Toggle Pause/Resume | "
              << hotkeys.exit_name() << " = Clean Exit\n";
    std::cout << "====================================================================\n";
    std::cout << "  Macro is RUNNING. Waiting for QTE skill checks...\n\n";

    while (true) {
        double t_start = get_time_now_s(qpc_freq);

        auto hotkey_state = hotkeys.poll();
        bool toggle_hit = hotkey_state.first;
        bool exit_hit = hotkey_state.second;

        if (exit_hit) {
            std::cout << "\n[EXIT] Clean shutdown signal received. Releasing keys and stopping.\n";
            break;
        }

        if (toggle_hit) {
            is_paused = !is_paused;
            if (is_paused) {
                keyboard.release_all();
            }
            std::cout << "\n[HOTKEY] Macro is now: " << (is_paused ? "PAUSED (Standby)" : "ACTIVE (Monitoring)") << "\n";
        }

        keyboard.update();

        if (is_paused) {
            Sleep(10);
            continue;
        }

        // Dynamic Roblox window repositioning check
        if (!cfg.center_override.has_value() && (frame_count % 120 == 0)) {
            auto cur_roblox = find_roblox_client();
            if (cur_roblox.has_value()) {
                int new_cx = cur_roblox->x + cur_roblox->width / 2;
                int new_cy = cur_roblox->y + (cur_roblox->height / 2) + top_offset;
                if (new_cx != cx || new_cy != cy) {
                    cx = new_cx;
                    cy = new_cy;
                    x1 = cx - crop_size / 2;
                    y1 = cy - crop_size / 2;
                    capture.update_region(x1, y1, crop_size, crop_size);
                    std::cout << "\n[DYNAMIC LOCK] Roblox window detected (" << cur_roblox->width << "x" << cur_roblox->height
                              << ")! Recentered capture to (" << cx << ", " << cy << ")\n";
                }
            }
        }

        const uint8_t* buf = capture.capture();
        FrameEvaluation eval = detector.evaluate(buf, crop_size, crop_size, t_start);

        if (eval.present && !was_present) {
            std::cout << "\n[" << get_formatted_time() << "] [QTE DETECTED] Center prompt recognized! Tracking needle...\n";
        }
        was_present = eval.present;

        if (eval.should_trigger) {
            double eff_delay_s = eval.effective_delay_s > 0.0 ? eval.effective_delay_s : trigger_delay_s;
            if (eff_delay_s > 0.0) {
                DWORD sleep_ms = static_cast<DWORD>(eff_delay_s * 1000.0);
                if (sleep_ms > 0) Sleep(sleep_ms);
            }

            double t_trig = get_time_now_s(qpc_freq);
            bool pressed = keyboard.trigger();
            if (pressed) {
                hit_count++;
                std::string t_hit = get_formatted_time();

                std::ostringstream ss;
                ss << "\n[" << t_hit << "] [>>> HIT #" << hit_count << " <<<] QTE Triggered!\n"
                   << "  -> Needle: " << std::fixed << std::setprecision(1) << eval.needle_angle.value_or(0.0)
                   << "° | Score: " << eval.needle_score;

                if (eval.angular_velocity > 0.0) {
                    ss << " | Velocity: " << std::setprecision(0) << eval.angular_velocity << "°/s"
                       << " | Lead: " << std::setprecision(1) << eval.dynamic_lead << "°";
                }
                if (eff_delay_s > 0.0) {
                    ss << " | Delay: " << std::setprecision(1) << (eff_delay_s * 1000.0) << "ms";
                }
                ss << "\n";

                if (eval.patch_start.has_value() && eval.patch_end.has_value()) {
                    ss << "  -> Patch: [" << eval.patch_start.value() << "° .. " << eval.patch_end.value() << "°] "
                       << "(Center: " << eval.patch_center.value_or(0.0) << "°)\n";
                }
                ss << "  -> Target: " << eval.target_angle.value_or(0.0) << "° | Action: Spacebar (DirectInput 0x39 + VK 0x20)\n"
                   << "  -> Reason: " << eval.reason << "\n";

                std::cout << ss.str();

                detector.record_trigger(
                    t_trig,
                    eval.needle_angle.value_or(0.0),
                    eval.angular_velocity,
                    eval.patch_start.value_or(0.0),
                    eval.patch_end.value_or(0.0),
                    eval.patch_center.value_or(0.0),
                    eval.patch_span.value_or(0.0),
                    eval.is_chained
                );
            } else {
                detector.revert_trigger();
            }
        }

        double t_end = get_time_now_s(qpc_freq);
        double frame_time = t_end - t_start;
        total_latency += frame_time;
        frame_count++;

        // Periodic dashboard update
        if (t_end - last_status_time >= status_interval) {
            double fps = frame_count / (t_end - last_status_time);
            double avg_lat_ms = (total_latency / frame_count) * 1000.0;
            const char* qte_status = eval.present ? "ACTIVE" : "Idle";

            std::string cal_str;
            auto last_a = cal_engine->last_used_anchor();
            if (last_a.has_value()) {
                cal_str = " | Cal: " + std::to_string(static_cast<int>(last_a->speed)) + "°/s@" +
                          std::to_string(last_a->latency_ms).substr(0, 4) + "ms";
            } else {
                cal_str = " | Cal: " + std::to_string(cal_engine->learned_latency_ms()).substr(0, 4) + "ms";
            }

            std::cout << "\r[STATUS: RUNNING] FPS: " << std::setw(6) << std::fixed << std::setprecision(1) << fps
                      << " | Latency: " << std::setw(4) << std::setprecision(2) << avg_lat_ms << "ms"
                      << " | QTE: " << std::setw(6) << std::left << qte_status << std::right
                      << " | Hits: " << std::setw(3) << hit_count
                      << cal_str << std::flush;

            last_status_time = t_end;
            frame_count = 0;
            total_latency = 0.0;
        }

        if (cfg.poll_interval_ms > 0) {
            Sleep(cfg.poll_interval_ms);
        } else {
            Sleep(0); // Yield to other threads without burning 100% core
        }
    }

    timeEndPeriod(1);
    keyboard.release_all();
    std::cout << "[SHUTDOWN] Lunar Tear cleanup complete. Exited cleanly.\n";
}

int main(int argc, char* argv[]) {
    std::string config_path = "config.json";
    bool run_test = false;
    bool run_test_key = false;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--test") {
            run_test = true;
        } else if (arg == "--test-key") {
            run_test_key = true;
        } else if (arg == "--config" && i + 1 < argc) {
            config_path = argv[++i];
        }
    }

    if (run_test_key) {
        test_keypress();
        return 0;
    }

    if (run_test) {
        return run_test_suite();
    }

    run_macro(config_path);
    return 0;
}
