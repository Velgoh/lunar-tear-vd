#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <vector>
#include <cstdint>
#include <cmath>
#include <algorithm>
#include <tuple>
#include <optional>

namespace lunartear {

inline std::vector<uint8_t> create_synthetic_frame(
    int cx = 160,
    int cy = 160,
    int R = 83,
    int crop_size = 320,
    std::optional<std::pair<double, double>> white_patch = std::nullopt, // (start_deg, span_deg)
    std::tuple<uint8_t, uint8_t, uint8_t> patch_rgb = {255, 255, 255},
    int border_lum = 30,
    std::optional<double> needle_deg = std::nullopt,
    bool with_glyph = true
) {
    const double pi = 3.14159265358979323846;
    int w = crop_size;
    int h = crop_size;
    std::vector<uint8_t> buf(w * h * 4, 0);

    // Background fill
    uint8_t b_val = static_cast<uint8_t>((std::max)(0, (std::min)(255, border_lum)));
    for (int i = 0; i < w * h * 4; i += 4) {
        buf[i] = b_val;     // B
        buf[i + 1] = b_val; // G
        buf[i + 2] = b_val; // R
        buf[i + 3] = 255;   // A
    }

    // Spacebar glyph
    if (with_glyph) {
        for (int y = cy - 12; y <= cy + 1; ++y) {
            for (int x = cx - 24; x <= cx + 24; ++x) {
                if (x >= 0 && x < w && y >= 0 && y < h) {
                    int off = (y * w + x) * 4;
                    buf[off] = 20;
                    buf[off + 1] = 20;
                    buf[off + 2] = 20;
                }
            }
        }
        for (int y = cy + 2; y <= cy + 4; ++y) {
            for (int x = cx - 27; x <= cx + 27; ++x) {
                if (x >= 0 && x < w && y >= 0 && y < h) {
                    int off = (y * w + x) * 4;
                    buf[off] = 250;
                    buf[off + 1] = 250;
                    buf[off + 2] = 250;
                }
            }
        }
        for (int y = cy - 6; y <= cy + 4; ++y) {
            for (int dx = 0; dx < 3; ++dx) {
                int off_l = (y * w + cx - 27 + dx) * 4;
                int off_r = (y * w + cx + 25 + dx) * 4;
                if (cx - 27 + dx >= 0 && cx - 27 + dx < w && y >= 0 && y < h) {
                    buf[off_l] = 250;
                    buf[off_l + 1] = 250;
                    buf[off_l + 2] = 250;
                }
                if (cx + 25 + dx >= 0 && cx + 25 + dx < w && y >= 0 && y < h) {
                    buf[off_r] = 250;
                    buf[off_r + 1] = 250;
                    buf[off_r + 2] = 250;
                }
            }
        }
    }

    // Circular dark ring track
    uint8_t ring_track_lum = static_cast<uint8_t>((std::max)(15, b_val / 2));
    for (int a_deg = 0; a_deg < 360; ++a_deg) {
        double rad = a_deg * pi / 180.0;
        for (int dr = -6; dr <= 6; ++dr) {
            int r_curr = R + dr;
            int px = static_cast<int>(std::round(cx + r_curr * std::cos(rad)));
            int py = static_cast<int>(std::round(cy + r_curr * std::sin(rad)));
            if (px >= 0 && px < w && py >= 0 && py < h) {
                int off = (py * w + px) * 4;
                buf[off] = ring_track_lum;
                buf[off + 1] = ring_track_lum;
                buf[off + 2] = ring_track_lum;
            }
        }
    }

    // White patch arc
    if (white_patch.has_value()) {
        double p_start = white_patch->first;
        double p_span = white_patch->second;
        uint8_t pr = std::get<0>(patch_rgb);
        uint8_t pg = std::get<1>(patch_rgb);
        uint8_t pb = std::get<2>(patch_rgb);

        int steps = static_cast<int>(std::round(p_span * 4.0));
        for (int step = 0; step < steps; ++step) {
            double deg = std::fmod((p_start + step * 0.25 + 360.0), 360.0);
            double rad = deg * pi / 180.0;
            for (int dr : {-3, -2, -1, 0, 1, 2, 3}) {
                int r_curr = R + dr;
                int px = static_cast<int>(std::round(cx + r_curr * std::cos(rad)));
                int py = static_cast<int>(std::round(cy + r_curr * std::sin(rad)));
                if (px >= 0 && px < w && py >= 0 && py < h) {
                    int off = (py * w + px) * 4;
                    buf[off] = pb;
                    buf[off + 1] = pg;
                    buf[off + 2] = pr;
                }
            }
        }
    }

    // Red needle
    if (needle_deg.has_value()) {
        double n_rad = needle_deg.value() * pi / 180.0;
        double cos_n = std::cos(n_rad);
        double sin_n = std::sin(n_rad);
        int r_min = static_cast<int>(R * 0.35);
        int r_max = static_cast<int>(R * 0.85);

        for (int r_curr = r_min; r_curr < r_max; ++r_curr) {
            for (int ortho : {-1, 0, 1}) {
                int px = static_cast<int>(std::round(cx + r_curr * cos_n - ortho * sin_n));
                int py = static_cast<int>(std::round(cy + r_curr * sin_n + ortho * cos_n));
                if (px >= 0 && px < w && py >= 0 && py < h) {
                    int off = (py * w + px) * 4;
                    buf[off] = 20;     // B
                    buf[off + 1] = 20; // G
                    buf[off + 2] = 240;// R
                }
            }
        }
    }

    return buf;
}

} // namespace lunartear
