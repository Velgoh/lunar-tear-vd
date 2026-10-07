#include "qte_detector.hpp"
#include <cmath>
#include <algorithm>
#include <iostream>
#include <sstream>
#include <iomanip>

namespace lunartear {

const double PI = 3.14159265358979323846;

struct TrigTables {
    double cos_360[360];
    double sin_360[360];
    double cos_ring[36];
    double sin_ring[36];
    double cos_720[720];
    double sin_720[720];

    TrigTables() {
        for (int i = 0; i < 360; ++i) {
            double rad = i * PI / 180.0;
            cos_360[i] = std::cos(rad);
            sin_360[i] = std::sin(rad);
        }
        for (int i = 0; i < 36; ++i) {
            double rad = (i * 10) * PI / 180.0;
            cos_ring[i] = std::cos(rad);
            sin_ring[i] = std::sin(rad);
        }
        for (int i = 0; i < 720; ++i) {
            double rad = (i * 0.5) * PI / 180.0;
            cos_720[i] = std::cos(rad);
            sin_720[i] = std::sin(rad);
        }
    }
};

static const TrigTables g_trig;

QTEDetector::QTEDetector(
    int crop_size,
    const std::string& hit_position,
    double offset_degrees,
    double lead_degrees,
    double latency_ms,
    double min_needle_score,
    double trigger_delay_ms,
    std::shared_ptr<AdaptiveCalibrationEngine> calibration_engine,
    bool verbose_logging
) : m_crop_size(crop_size),
    m_nom_cx(crop_size / 2),
    m_nom_cy(crop_size / 2),
    m_hit_position(hit_position),
    m_offset_degrees(offset_degrees),
    m_lead_degrees(lead_degrees),
    m_latency_ms(latency_ms),
    m_min_needle_score(min_needle_score),
    m_trigger_delay_ms(trigger_delay_ms),
    m_base_delay_s(trigger_delay_ms / 1000.0),
    m_calibration_engine(calibration_engine),
    m_verbose_logging(verbose_logging) {

    reset();
}

void QTEDetector::reset() {
    m_is_qte_active = false;
    m_cached_cx = m_nom_cx;
    m_cached_cy = m_nom_cy;
    m_cached_r = 83;

    m_cached_patch_start.reset();
    m_cached_patch_end.reset();
    m_cached_patch_center.reset();
    m_cached_patch_span.reset();
    m_cached_target_angle.reset();

    m_prev_needle_angle.reset();
    m_prev_needle_time.reset();
    m_angular_velocity = 0.0;

    m_has_triggered_current_qte = false;
    m_last_trigger_time = 0.0;
    m_triggered_patch_center.reset();

    m_qte_start_time = 0.0;
    m_qte_frames = 0;
    m_absent_frames = 0;
    m_chain_hit_count = 0;
    m_reset_velocity_on_next_sample = false;

    m_last_rearm_scan_time = 0.0;
    m_cached_rearm_patch.reset();

    m_presence_geom.reset();
    m_last_ring_cx = m_nom_cx;
    m_last_ring_cy = m_nom_cy;
    m_last_ring_r = 83;

    if (m_calibration_engine && m_calibration_engine->is_tracking()) {
        m_calibration_engine->cancel_tracking();
    }
}

void QTEDetector::revert_trigger() {
    m_has_triggered_current_qte = false;
    m_last_trigger_time = 0.0;
    m_triggered_patch_center.reset();
    m_last_rearm_scan_time = 0.0;
    m_cached_rearm_patch.reset();
    if (m_chain_hit_count > 0) {
        m_chain_hit_count--;
    }
    if (m_calibration_engine) {
        m_calibration_engine->cancel_tracking();
    }
}

void QTEDetector::record_trigger(
    double trigger_time,
    double trigger_angle,
    double angular_velocity,
    double patch_start,
    double patch_end,
    double patch_center,
    double patch_span,
    std::optional<bool> is_chained
) {
    if (m_calibration_engine) {
        bool chained = is_chained.has_value() ? is_chained.value() : (m_chain_hit_count > 1);
        m_calibration_engine->record_trigger(
            trigger_time,
            trigger_angle,
            angular_velocity,
            patch_start,
            patch_end,
            patch_center,
            patch_span,
            chained
        );
    }
}

GlyphGeometry QTEDetector::find_glyph_and_geometry(const uint8_t* buf, int width, int height) const {
    GlyphGeometry res;
    res.found = false;
    res.cx = width / 2;
    res.cy = height / 2;
    res.R = 83;
    res.bar_len = 0;

    if (!buf || width <= 0 || height <= 0) return res;

    int nom_cx = width / 2;
    int nom_cy = height / 2;

    struct Candidate {
        double score;
        int y;
        int bar_cx;
        int r_len;
    };
    std::vector<Candidate> candidates;

    int y_start = std::max(10, nom_cy - 65);
    int y_end = std::min(height - 10, nom_cy + 75);

    for (int y = y_start; y < y_end; y += 2) {
        int row_off = y * width * 4;
        bool in_run = false;
        int run_start = 0;
        int run_len = 0;

        std::vector<std::pair<int, int>> runs;
        int x_start = std::max(10, nom_cx - 65);
        int x_end = std::min(width - 10, nom_cx + 66);

        for (int x = x_start; x < x_end; ++x) {
            int off = row_off + x * 4;
            int b = buf[off];
            int g = buf[off + 1];
            int r = buf[off + 2];
            double lum = (r + g + b) / 3.0;

            bool is_white_or_needle = (lum > 125.0 && r > 100) || (r > 130 && r - std::max(g, b) > 35);
            if (is_white_or_needle) {
                if (!in_run) {
                    in_run = true;
                    run_start = x;
                    run_len = 1;
                } else {
                    run_len++;
                }
            } else {
                if (in_run) {
                    runs.push_back({run_start, run_len});
                    in_run = false;
                }
            }
        }
        if (in_run) {
            runs.push_back({run_start, run_len});
        }

        for (const auto& run : runs) {
            int r_s = run.first;
            int r_l = run.second;
            if (r_l >= 20 && r_l <= 90) {
                int bar_cx = r_s + r_l / 2;
                if (std::abs(bar_cx - nom_cx) > 35) continue;

                int left_edge = r_s;
                int right_edge = r_s + r_l - 1;

                // Inner dark face check
                double inner_lum_sum = 0.0;
                int inner_count = 0;
                int step_x = std::max(1, r_l / 10);
                for (int in_x = left_edge + 4; in_x <= right_edge - 3; in_x += step_x) {
                    for (int in_dy : {2, 3, 4, 5}) {
                        if (y - in_dy < 0) continue;
                        int off_in = ((y - in_dy) * width + in_x) * 4;
                        inner_lum_sum += (buf[off_in] + buf[off_in + 1] + buf[off_in + 2]) / 3.0;
                        inner_count++;
                    }
                }
                double lum_in = inner_count > 0 ? (inner_lum_sum / inner_count) : 999.0;

                int lt_votes = 0;
                int rt_votes = 0;
                for (int dy : {2, 3, 4}) {
                    if (y - dy < 0) continue;
                    double max_lt = 0.0;
                    double max_rt = 0.0;
                    for (int dx : {-1, 0, 1}) {
                        int lx = left_edge + dx;
                        if (lx >= 0 && lx < width) {
                            int off = ((y - dy) * width + lx) * 4;
                            double l = (buf[off] + buf[off + 1] + buf[off + 2]) / 3.0;
                            if (l > max_lt) max_lt = l;
                        }
                        int rx = right_edge + dx;
                        if (rx >= 0 && rx < width) {
                            int off = ((y - dy) * width + rx) * 4;
                            double l = (buf[off] + buf[off + 1] + buf[off + 2]) / 3.0;
                            if (l > max_rt) max_rt = l;
                        }
                    }
                    if (max_lt > 80.0) lt_votes++;
                    if (max_rt > 80.0) rt_votes++;
                }

                int dy_below = std::max(4, static_cast<int>(std::round(r_l * 0.08)) + 1);
                if (y + dy_below >= height) continue;
                int off_below = ((y + dy_below) * width + bar_cx) * 4;
                double lum_below = (buf[off_below] + buf[off_below + 1] + buf[off_below + 2]) / 3.0;

                double bar_lum_sum = 0.0;
                for (int bx = r_s; bx < r_s + r_l; ++bx) {
                    int off = (y * width + bx) * 4;
                    bar_lum_sum += (buf[off] + buf[off + 1] + buf[off + 2]) / 3.0;
                }
                double bar_lum = bar_lum_sum / r_l;

                if (lt_votes >= 2 && rt_votes >= 2 &&
                    (bar_lum - lum_in > 40.0) && (lum_in < 65.0) &&
                    (bar_lum - lum_below > 25.0)) {
                    double score = (bar_lum - lum_in) * r_l - 8.0 * std::abs(bar_cx - nom_cx);
                    candidates.push_back({score, y, bar_cx, r_l});
                }
            }
        }
    }

    if (candidates.empty()) return res;

    auto best_it = std::max_element(candidates.begin(), candidates.end(),
                                    [](const Candidate& a, const Candidate& b) { return a.score < b.score; });

    Candidate best_c = *best_it;
    std::vector<Candidate> cluster;
    for (const auto& c : candidates) {
        if (std::abs(c.bar_cx - best_c.bar_cx) <= 4 && std::abs(c.r_len - best_c.r_len) <= 4) {
            cluster.push_back(c);
        }
    }

    auto top_it = std::min_element(cluster.begin(), cluster.end(),
                                   [](const Candidate& a, const Candidate& b) { return a.y < b.y; });

    int top_y = top_it->y;
    int est_cx = top_it->bar_cx;
    int r_len = top_it->r_len;
    int est_cy = top_y - static_cast<int>(std::round(r_len * 0.05));
    int est_r = std::max(50, std::min(120, static_cast<int>(std::round(r_len * 1.48))));

    res.found = true;
    res.cx = est_cx;
    res.cy = est_cy;
    res.R = est_r;
    res.bar_len = r_len;
    return res;
}

bool QTEDetector::check_ring_boundary(const uint8_t* buf, int width, int height, int cx, int cy, int R) {
    if (!buf || width <= 0 || height <= 0) return false;

    int r_in = static_cast<int>(std::round(R * 0.82));

    auto sample_ring_at = [&](int ccy, double& out_dark, double& out_avg_ring, double& out_contrast) -> bool {
        int dark_in = 0;
        double lum_ring_sum = 0.0;
        double lum_in_sum = 0.0;
        int total = 0;

        for (int i = 0; i < 36; ++i) {
            double cos_a = g_trig.cos_ring[i];
            double sin_a = g_trig.sin_ring[i];

            int px_in = static_cast<int>(std::round(cx + r_in * cos_a));
            int py_in = static_cast<int>(std::round(ccy + r_in * sin_a));

            double best_l = 0.0;
            for (int dr : {-2, -1, 0, 1, 2}) {
                int px = static_cast<int>(std::round(cx + (R + dr) * cos_a));
                int py = static_cast<int>(std::round(ccy + (R + dr) * sin_a));
                if (px >= 0 && px < width && py >= 0 && py < height) {
                    int off = (py * width + px) * 4;
                    double l = (buf[off] + buf[off + 1] + buf[off + 2]) / 3.0;
                    if (l > best_l) best_l = l;
                }
            }

            if (px_in >= 0 && px_in < width && py_in >= 0 && py_in < height) {
                int off_in = (py_in * width + px_in) * 4;
                double lin = (buf[off_in] + buf[off_in + 1] + buf[off_in + 2]) / 3.0;
                if (lin < 80.0) dark_in++;
                lum_in_sum += lin;
                lum_ring_sum += best_l;
                total++;
            }
        }

        if (total >= 10) {
            out_dark = static_cast<double>(dark_in) / total;
            out_avg_ring = lum_ring_sum / total;
            out_contrast = out_avg_ring - (lum_in_sum / total);
            return true;
        }
        out_dark = 0.0;
        out_avg_ring = 0.0;
        out_contrast = -999.0;
        return false;
    };

    double dark0 = 0.0, avg0 = 0.0, cont0 = 0.0;
    sample_ring_at(cy, dark0, avg0, cont0);
    if (dark0 >= 0.65 && avg0 >= 90.0 && cont0 >= 30.0) {
        m_last_ring_cx = cx;
        m_last_ring_cy = cy;
        m_last_ring_r = R;
        return true;
    }

    if (cont0 < 10.0 || avg0 < 50.0) {
        m_last_ring_cx = cx;
        m_last_ring_cy = cy;
        m_last_ring_r = R;
        return false;
    }

    double best_cont = cont0;
    double best_dark = dark0;
    double best_avg = avg0;
    int best_ccy = cy;

    for (int dy : {-6, 6, -12, 12, -20, 20, -36, 36}) {
        int ccy = cy + dy;
        double d = 0.0, a = 0.0, c = 0.0;
        sample_ring_at(ccy, d, a, c);
        if (c > best_cont) {
            best_cont = c;
            best_dark = d;
            best_avg = a;
            best_ccy = ccy;
            if (best_dark >= 0.65 && best_avg >= 90.0 && best_cont >= 30.0) {
                m_last_ring_cx = cx;
                m_last_ring_cy = best_ccy;
                m_last_ring_r = R;
                return true;
            }
        }
    }

    m_last_ring_cx = cx;
    m_last_ring_cy = best_ccy;
    m_last_ring_r = R;
    return (best_dark >= 0.65 && best_avg >= 90.0 && best_cont >= 30.0);
}

bool QTEDetector::check_presence(const uint8_t* buf, int width, int height) {
    if (!buf || width <= 0 || height <= 0) return false;

    if (m_is_qte_active) {
        GlyphGeometry g = find_glyph_and_geometry(buf, width, height);
        if (g.found) return true;

        auto needle = detect_needle(buf, width, height, m_cached_cx, m_cached_cy, m_cached_r);
        if (needle.second >= m_min_needle_score) return true;

        if (check_ring_boundary(buf, width, height, m_cached_cx, m_cached_cy, m_cached_r)) return true;
        return false;
    }

    // Pathway 1: Central bracket glyph detected
    GlyphGeometry g = find_glyph_and_geometry(buf, width, height);
    if (g.found) {
        auto needle = detect_needle(buf, width, height, g.cx, g.cy, g.R);
        if (needle.second >= m_min_needle_score) {
            auto patch = detect_white_patch(buf, width, height, g.cx, g.cy, g.R);
            if (patch.has_value()) {
                m_presence_geom = std::make_tuple(g.cx, g.cy, g.R);
                return true;
            }
        }
    }

    // Pathway 2: Dark circular ring boundary fallback
    int nom_cx = width / 2;
    int nom_cy = height / 2;

    if (check_ring_boundary(buf, width, height, nom_cx, nom_cy, 83)) {
        auto needle = detect_needle(buf, width, height, m_last_ring_cx, m_last_ring_cy, m_last_ring_r);
        if (needle.second >= m_min_needle_score) {
            auto patch = detect_white_patch(buf, width, height, m_last_ring_cx, m_last_ring_cy, m_last_ring_r);
            if (patch.has_value()) {
                m_presence_geom = std::make_tuple(m_last_ring_cx, m_last_ring_cy, m_last_ring_r);
                return true;
            }
        }
    } else {
        for (int r_cand : {67, 95, 75, 60, 90, 100, 105, 110}) {
            if (check_ring_boundary(buf, width, height, nom_cx, nom_cy, r_cand)) {
                auto needle = detect_needle(buf, width, height, m_last_ring_cx, m_last_ring_cy, m_last_ring_r);
                if (needle.second >= m_min_needle_score) {
                    auto patch = detect_white_patch(buf, width, height, m_last_ring_cx, m_last_ring_cy, m_last_ring_r);
                    if (patch.has_value()) {
                        m_presence_geom = std::make_tuple(m_last_ring_cx, m_last_ring_cy, m_last_ring_r);
                        return true;
                    }
                }
            }
        }
    }

    return false;
}

std::pair<double, double> QTEDetector::detect_needle(const uint8_t* buf, int width, int height, int cx, int cy, int R) const {
    if (!buf || width <= 0 || height <= 0) return {0.0, 0.0};

    int radii[4] = {
        static_cast<int>(std::round(R * 0.45)),
        static_cast<int>(std::round(R * 0.55)),
        static_cast<int>(std::round(R * 0.65)),
        static_cast<int>(std::round(R * 0.75))
    };

    int best_deg = 0;
    double max_red = -999.0;
    double scores[360] = {};
    int max_r_vals[360] = {};

    for (int deg = 0; deg < 360; ++deg) {
        double cos_a = g_trig.cos_360[deg];
        double sin_a = g_trig.sin_360[deg];

        int red_sum = 0;
        int valid_samples = 0;
        int max_r_along_ray = 0;

        for (int r : radii) {
            int px = static_cast<int>(std::round(cx + r * cos_a));
            int py = static_cast<int>(std::round(cy + r * sin_a));
            if (px >= 0 && px < width && py >= 0 && py < height) {
                int off = (py * width + px) * 4;
                int b = buf[off];
                int g = buf[off + 1];
                int r_val = buf[off + 2];
                if (r_val > max_r_along_ray) max_r_along_ray = r_val;
                int max_gb = std::max(g, b);
                red_sum += (r_val - max_gb);
                valid_samples++;
            }
        }

        double avg_red = valid_samples > 0 ? (static_cast<double>(red_sum) / valid_samples) : 0.0;
        scores[deg] = avg_red;
        max_r_vals[deg] = max_r_along_ray;
        if (avg_red > max_red) {
            max_red = avg_red;
            best_deg = deg;
        }
    }

    if (max_r_vals[best_deg] < 115) {
        max_red = 0.0;
    }

    int high_score_count = 0;
    for (int deg = 0; deg < 360; ++deg) {
        if (scores[deg] >= m_min_needle_score) high_score_count++;
    }
    if (high_score_count > 32) {
        max_red = 0.0;
    }

    double num = 0.0;
    double den = 0.0;
    for (int offset = -2; offset <= 2; ++offset) {
        int d = (best_deg + offset + 360) % 360;
        double weight = std::max(0.0, scores[d] - 30.0);
        num += offset * weight;
        den += weight;
    }
    double sub_deg = std::fmod((best_deg + (den > 0.0 ? (num / den) : 0.0) + 360.0), 360.0);
    return {sub_deg, max_red};
}

std::optional<PatchGeometry> QTEDetector::detect_white_patch(const uint8_t* buf, int width, int height, int cx, int cy, int R) const {
    if (!buf || width <= 0 || height <= 0) return std::nullopt;

    std::vector<double> bright_angles;
    std::vector<double> angle_lums;
    bright_angles.reserve(720);
    angle_lums.reserve(720);

    const int dr_list[7] = {-3, -2, -1, 0, 1, 2, 3};

    for (int i = 0; i < 720; ++i) {
        double a = i * 0.5;
        double cos_a = g_trig.cos_720[i];
        double sin_a = g_trig.sin_720[i];

        int cnt = 0;
        int valid = 0;
        double lum_sum = 0.0;

        for (int dr : dr_list) {
            int r_curr = R + dr;
            int px = static_cast<int>(std::round(cx + r_curr * cos_a));
            int py = static_cast<int>(std::round(cy + r_curr * sin_a));
            if (px >= 0 && px < width && py >= 0 && py < height) {
                valid++;
                int off = (py * width + px) * 4;
                int b = buf[off];
                int g = buf[off + 1];
                int r = buf[off + 2];
                double lum = (r + g + b) / 3.0;
                lum_sum += lum;

                if ((r > 170 && g > 120 && lum > 150.0) || (r > 180 && lum > 135.0)) {
                    cnt++;
                }
            }
        }

        if ((valid >= 6 && cnt >= 4) || (valid == 5 && cnt >= 4) ||
            ((valid == 3 || valid == 4) && cnt >= 2) || ((valid == 1 || valid == 2) && cnt >= 1)) {
            bright_angles.push_back(a);
            angle_lums.push_back(valid > 0 ? (lum_sum / valid) : 0.0);
        }
    }

    if (bright_angles.empty()) return std::nullopt;

    std::vector<std::vector<size_t>> runs;
    runs.push_back({0});

    for (size_t i = 1; i < bright_angles.size(); ++i) {
        if (bright_angles[i] - bright_angles[runs.back().back()] <= 3.5) {
            runs.back().push_back(i);
        } else {
            runs.push_back({i});
        }
    }

    // Handle wrap-around across 0° / 360°
    if (runs.size() > 1 && (360.0 - bright_angles[runs.back().back()] + bright_angles[runs.front().front()]) <= 3.5) {
        std::vector<size_t> merged = runs.back();
        merged.insert(merged.end(), runs.front().begin(), runs.front().end());
        runs[0] = merged;
        runs.pop_back();
    }

    struct Candidate {
        double avg_lum;
        size_t count;
        double start;
        double end;
        double center;
        double span;
    };
    std::vector<Candidate> candidates;

    for (const auto& r : runs) {
        double start = bright_angles[r.front()];
        double end = bright_angles[r.back()];
        double span = std::fmod((end - start + 360.0), 360.0);

        if (span >= 5.0 && span <= 18.0) {
            double center = std::fmod((start + span / 2.0 + 360.0), 360.0);
            double lum_sum = 0.0;
            for (size_t idx : r) {
                lum_sum += angle_lums[idx];
            }
            double avg_lum = lum_sum / r.size();
            candidates.push_back({avg_lum, r.size(), start, end, center, span});
        }
    }

    if (candidates.empty()) return std::nullopt;

    std::sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
        if (std::abs(a.avg_lum - b.avg_lum) > 1e-4) return a.avg_lum > b.avg_lum;
        return a.count > b.count;
    });

    const Candidate& best = candidates.front();
    PatchGeometry geo;
    geo.start_deg = best.start;
    geo.end_deg = best.end;
    geo.center_deg = best.center;
    geo.span_deg = best.span;
    return geo;
}

double QTEDetector::calculate_target_angle(double patch_start, double patch_end, double patch_center, double patch_span, double lead_degrees) const {
    (void)patch_end;
    // Absolute 100% success rule: target is clamped to never precede patch_start
    double center_offset = std::fmod((patch_center - patch_start + 360.0), 360.0);
    double lead_offset = std::max(0.0, center_offset - lead_degrees);

    double target = std::fmod((patch_start + lead_offset + m_offset_degrees + 360.0), 360.0);

    // Safety clamp: target must strictly lie between patch_start and patch_end
    double dist_from_start = std::fmod((target - patch_start + 360.0), 360.0);
    if (dist_from_start > patch_span) {
        target = patch_start;
    }

    return target;
}

double QTEDetector::calculate_effective_delay(double base_delay_s, double needle_angle) const {
    if (base_delay_s <= 0.0) return 0.0;
    if (!m_cached_patch_start.has_value() || !m_cached_patch_span.has_value()) {
        return base_delay_s;
    }

    double p_start = m_cached_patch_start.value();
    double p_span = m_cached_patch_span.value();

    double dist_from_start = std::fmod((needle_angle - p_start + 360.0), 360.0);
    if (dist_from_start > 180.0) return base_delay_s;
    if (dist_from_start >= p_span) return 0.0; // Past patch end: trigger immediately

    double remaining_budget = std::max(0.0, p_span - dist_from_start);
    double omega = m_angular_velocity;

    if (omega <= 50.0) {
        if (dist_from_start > 0.65 * p_span) {
            double scale = std::max(0.0, (p_span - dist_from_start) / (0.35 * p_span));
            return base_delay_s * scale;
        }
        return base_delay_s;
    }

    double max_spin_advance = 0.65 * p_span;
    double max_budget_advance = remaining_budget * 0.80;
    double allowed_advance = std::min(max_spin_advance, max_budget_advance);

    double max_delay_s = allowed_advance / omega;
    return std::max(0.0, std::min(base_delay_s, max_delay_s));
}

FrameEvaluation QTEDetector::evaluate(const uint8_t* buf, int width, int height, double now) {
    FrameEvaluation eval;
    if (!buf || width <= 0 || height <= 0) {
        eval.present = false;
        eval.reason = "Empty buffer";
        return eval;
    }

    bool found = check_presence(buf, width, height);

    if (!found && !m_is_qte_active) {
        if (m_calibration_engine && m_calibration_engine->is_tracking()) {
            m_calibration_engine->on_frame(now, std::nullopt, 0.0, false);
        }
        eval.present = false;
        eval.reason = "No QTE on screen";
        return eval;
    }

    if (found) {
        GlyphGeometry g = find_glyph_and_geometry(buf, width, height);
        if (g.found) {
            m_cached_cx = g.cx;
            m_cached_cy = g.cy;
            m_cached_r = g.R;
        } else if (m_presence_geom.has_value()) {
            m_cached_cx = std::get<0>(m_presence_geom.value());
            m_cached_cy = std::get<1>(m_presence_geom.value());
            m_cached_r = std::get<2>(m_presence_geom.value());
        }
        m_absent_frames = 0;
        if (!m_is_qte_active) {
            m_is_qte_active = true;
            m_qte_start_time = now;
            m_qte_frames = 0;
            m_has_triggered_current_qte = false;
            m_last_trigger_time = 0.0;
            m_triggered_patch_center.reset();
            m_chain_hit_count = 0;
        }
    } else {
        m_absent_frames++;
        if (m_calibration_engine && m_calibration_engine->is_tracking()) {
            m_calibration_engine->on_frame(now, std::nullopt, 0.0, false);
        }
        if (m_absent_frames >= 3) {
            reset();
            eval.present = false;
            eval.reason = "QTE disappeared";
            return eval;
        }
        eval.present = false;
        eval.patch_start = m_cached_patch_start;
        eval.patch_end = m_cached_patch_end;
        eval.patch_center = m_cached_patch_center;
        eval.patch_span = m_cached_patch_span;
        eval.target_angle = m_cached_target_angle;
        eval.angular_velocity = m_angular_velocity;
        eval.reason = "QTE dropped frame / noise";
        eval.is_chained = (m_chain_hit_count > 0);
        eval.chain_hit_count = m_chain_hit_count;
        return eval;
    }

    m_qte_frames++;

    // Detect needle
    auto needle_res = detect_needle(buf, width, height, m_cached_cx, m_cached_cy, m_cached_r);
    double needle_angle = needle_res.first;
    double needle_score = needle_res.second;
    bool has_real_needle = (needle_score >= m_min_needle_score);

    // Dynamic angular velocity calculation
    if (has_real_needle && m_prev_needle_angle.has_value() && m_prev_needle_time.has_value()) {
        double dt = now - m_prev_needle_time.value();
        double d_theta = std::fmod((needle_angle - m_prev_needle_angle.value() + 360.0), 360.0);
        if (d_theta >= 0.35 && d_theta <= 180.0) {
            if (dt >= 0.0005 && dt <= 0.25) { // Highly responsive sub-millisecond polling
                double raw_velocity = d_theta / dt;
                if (raw_velocity >= 50.0) {
                    if (m_angular_velocity == 0.0 || m_reset_velocity_on_next_sample ||
                        raw_velocity < 0.5 * m_angular_velocity || raw_velocity > 1.8 * m_angular_velocity) {
                        m_angular_velocity = raw_velocity;
                        m_reset_velocity_on_next_sample = false;
                    } else {
                        m_angular_velocity = 0.35 * raw_velocity + 0.65 * m_angular_velocity;
                    }
                }
            }
        } else if (dt > 0.5) {
            m_angular_velocity = 0.0;
            m_reset_velocity_on_next_sample = true;
        }
    }

    double cal_lead = 0.0;
    if (m_calibration_engine) {
        cal_lead = m_calibration_engine->calculate_dynamic_lead(m_angular_velocity);
    }

    double manual_lead = (m_angular_velocity * (m_latency_ms / 1000.0));
    double clamped_manual_lead = std::max(0.0, std::min(30.0, manual_lead));

    double dynamic_lead = 0.0;
    if (m_hit_position == "start") {
        dynamic_lead = cal_lead;
    } else {
        dynamic_lead = m_lead_degrees + cal_lead + clamped_manual_lead;
    }

    // Continuous skill check re-arming
    if (m_has_triggered_current_qte) {
        double time_since_trigger = m_last_trigger_time > 0.0 ? (now - m_last_trigger_time) : 999.0;
        bool is_past_triggered_patch = false;
        if (m_cached_patch_start.has_value() && m_cached_patch_span.has_value()) {
            double dist_from_start = std::fmod((needle_angle - m_cached_patch_start.value() + 360.0), 360.0);
            is_past_triggered_patch = (dist_from_start >= m_cached_patch_span.value() + 2.0 && dist_from_start <= 180.0);
        }

        if (time_since_trigger >= 0.040) {
            std::optional<PatchGeometry> curr_patch;
            if (now - m_last_rearm_scan_time >= 0.015) {
                curr_patch = detect_white_patch(buf, width, height, m_cached_cx, m_cached_cy, m_cached_r);
                m_last_rearm_scan_time = now;
                m_cached_rearm_patch = curr_patch;
            } else {
                curr_patch = m_cached_rearm_patch;
            }

            if (!curr_patch.has_value()) {
                m_cached_patch_start.reset();
                m_cached_patch_end.reset();
                m_cached_patch_center.reset();
                m_cached_patch_span.reset();
                m_cached_target_angle.reset();
                m_has_triggered_current_qte = false;
                m_triggered_patch_center.reset();
                m_reset_velocity_on_next_sample = true;
                m_last_rearm_scan_time = 0.0;
                m_cached_rearm_patch.reset();
            } else {
                double diff_from_triggered = 999.0;
                if (m_triggered_patch_center.has_value()) {
                    diff_from_triggered = std::abs(std::fmod((curr_patch->center_deg - m_triggered_patch_center.value() + 180.0 + 360.0), 360.0) - 180.0);
                }

                if (diff_from_triggered >= 6.0) {
                    m_cached_patch_start = curr_patch->start_deg;
                    m_cached_patch_end = curr_patch->end_deg;
                    m_cached_patch_center = curr_patch->center_deg;
                    m_cached_patch_span = curr_patch->span_deg;
                    m_cached_target_angle = calculate_target_angle(curr_patch->start_deg, curr_patch->end_deg, curr_patch->center_deg, curr_patch->span_deg, dynamic_lead);
                    m_has_triggered_current_qte = false;
                    m_triggered_patch_center.reset();
                    m_reset_velocity_on_next_sample = true;
                    m_last_rearm_scan_time = 0.0;
                    m_cached_rearm_patch.reset();
                } else if (is_past_triggered_patch && time_since_trigger >= 0.080) {
                    m_has_triggered_current_qte = false;
                    m_triggered_patch_center.reset();
                    m_reset_velocity_on_next_sample = true;
                    m_last_rearm_scan_time = 0.0;
                    m_cached_rearm_patch.reset();
                }
            }
        }
    }

    // Detect or maintain locked white patch
    if (!m_cached_patch_center.has_value()) {
        auto detected_patch = detect_white_patch(buf, width, height, m_cached_cx, m_cached_cy, m_cached_r);
        if (detected_patch.has_value()) {
            bool is_old_ghost = false;
            if (m_triggered_patch_center.has_value() && (now - m_last_trigger_time) < 0.080) {
                if (std::abs(std::fmod((detected_patch->center_deg - m_triggered_patch_center.value() + 180.0 + 360.0), 360.0) - 180.0) <= 6.0) {
                    is_old_ghost = true;
                }
            }

            if (!is_old_ghost) {
                m_cached_patch_start = detected_patch->start_deg;
                m_cached_patch_end = detected_patch->end_deg;
                m_cached_patch_center = detected_patch->center_deg;
                m_cached_patch_span = detected_patch->span_deg;
                m_cached_target_angle = calculate_target_angle(
                    detected_patch->start_deg,
                    detected_patch->end_deg,
                    detected_patch->center_deg,
                    detected_patch->span_deg,
                    dynamic_lead
                );
                m_reset_velocity_on_next_sample = true;
            }
        }
    } else if (m_cached_patch_start.has_value()) {
        m_cached_target_angle = calculate_target_angle(
            m_cached_patch_start.value(),
            m_cached_patch_end.value(),
            m_cached_patch_center.value(),
            m_cached_patch_span.value(),
            dynamic_lead
        );
    }

    bool should_trigger = false;
    std::string reason = "";

    if (!m_has_triggered_current_qte && m_cached_patch_start.has_value() && has_real_needle) {
        double p_start = m_cached_patch_start.value();
        double p_end = m_cached_patch_end.value();
        double p_span = m_cached_patch_span.value();
        double target = m_cached_target_angle.value();

        // Clockwise distance from patch start
        double dist_from_start = std::fmod((needle_angle - p_start + 360.0), 360.0);

        // ====================================================================
        // ABSOLUTE 100% SUCCESS RULE (ZERO EARLY MISS TOLERANCE)
        // ====================================================================
        // If dist_from_start > 180.0, needle is BEFORE patch_start (approaching).
        // Under hit_position == "start", triggering before patch_start is fatal!
        // We strictly forbid triggering whenever needle is before patch_start!
        // ====================================================================
        if (m_hit_position == "start" && dist_from_start > 180.0) {
            should_trigger = false;
            reason = "Approaching patch start (early lock)";
        } else {
            bool is_inside_patch = (dist_from_start <= p_span);
            double dist_from_target = std::fmod((needle_angle - target + 360.0), 360.0);
            double target_to_end = std::fmod((p_end - target + 360.0), 360.0);
            double lead_offset = std::fmod((target - p_start + 360.0), 360.0);

            // Condition 1: Direct presence inside the white patch
            if (is_inside_patch) {
                // Inside patch and reached target (or crossing it)
                if (dist_from_start >= lead_offset || dist_from_target <= target_to_end) {
                    should_trigger = true;
                    std::ostringstream ss;
                    ss << "Needle at target inside white patch [" << std::fixed << std::setprecision(1)
                       << p_start << "°.." << p_end << "°]";
                    reason = ss.str();
                }
            }

            // Condition 2: Clockwise frame transition / sweep crossing target or patch start
            if (!should_trigger && m_prev_needle_angle.has_value()) {
                double prev_ang = m_prev_needle_angle.value();
                double step = std::fmod((needle_angle - prev_ang + 360.0), 360.0);
                double dist_to_target = std::fmod((target - prev_ang + 360.0), 360.0);
                double dist_to_start = std::fmod((p_start - prev_ang + 360.0), 360.0);

                bool crossed_target = (dist_to_target <= step + 1.0);
                bool crossed_start = (dist_to_start <= step + 1.0);

                if ((0.05 <= step && step <= 180.0) && (crossed_target || crossed_start || is_inside_patch)) {
                    if (is_inside_patch) {
                        should_trigger = true;
                        std::ostringstream ss;
                        ss << "Clockwise entering white patch [" << std::fixed << std::setprecision(1)
                           << p_start << "°.." << p_end << "°] (prev=" << prev_ang << "°, curr=" << needle_angle << "°)";
                        reason = ss.str();
                    } else if (dist_from_start <= p_span + 25.0) { // Good continuation zone
                        should_trigger = true;
                        std::ostringstream ss;
                        ss << "Clockwise sweep across white patch [" << std::fixed << std::setprecision(1)
                           << p_start << "°.." << p_end << "°] (late hit)";
                        reason = ss.str();
                    }
                }
            }

            // Condition 3: First-frame or static image where needle is directly over patch
            if (!should_trigger && !m_prev_needle_angle.has_value()) {
                if (is_inside_patch) {
                    should_trigger = true;
                    std::ostringstream ss;
                    ss << "Needle detected directly over white patch [" << std::fixed << std::setprecision(1)
                       << p_start << "°.." << p_end << "°]";
                    reason = ss.str();
                }
            }
        }

        if (should_trigger) {
            m_has_triggered_current_qte = true;
            m_last_trigger_time = now;
            m_triggered_patch_center = m_cached_patch_center;
            m_chain_hit_count++;
            m_last_rearm_scan_time = 0.0;
            m_cached_rearm_patch.reset();
        }
    }

    bool is_chained = should_trigger ? (m_chain_hit_count > 1) : (m_chain_hit_count > 0);

    if (!should_trigger && !has_real_needle && reason.empty()) {
        std::ostringstream ss;
        ss << "Needle contrast too low (" << std::fixed << std::setprecision(1) << needle_score
           << " < " << m_min_needle_score << ")";
        reason = ss.str();
    }

    if (has_real_needle && (!m_prev_needle_angle.has_value() ||
        std::fmod((needle_angle - m_prev_needle_angle.value() + 360.0), 360.0) >= 0.35 ||
        (now - m_prev_needle_time.value_or(now)) > 0.5)) {
        m_prev_needle_angle = needle_angle;
        m_prev_needle_time = now;
    }

    double effective_delay_s = calculate_effective_delay(m_base_delay_s, needle_angle);

    if (m_calibration_engine && m_calibration_engine->is_tracking()) {
        m_calibration_engine->on_frame(
            now,
            has_real_needle ? std::make_optional(needle_angle) : std::nullopt,
            needle_score,
            true
        );
    }

    eval.present = true;
    eval.needle_angle = needle_angle;
    eval.needle_score = needle_score;
    eval.patch_start = m_cached_patch_start;
    eval.patch_end = m_cached_patch_end;
    eval.patch_center = m_cached_patch_center;
    eval.patch_span = m_cached_patch_span;
    eval.target_angle = m_cached_target_angle;
    eval.angular_velocity = m_angular_velocity;
    eval.dynamic_lead = dynamic_lead;
    eval.effective_delay_s = effective_delay_s;
    eval.should_trigger = should_trigger;
    eval.reason = reason;
    eval.is_chained = is_chained;
    eval.chain_hit_count = m_chain_hit_count;
    return eval;
}

} // namespace lunartear
