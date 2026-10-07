#include "calibration_engine.hpp"
#include <iostream>
#include <fstream>
#include <cmath>
#include <algorithm>
#include <iomanip>
#include <chrono>

namespace lunartear {

AdaptiveCalibrationEngine::AdaptiveCalibrationEngine(
    const std::string& config_path,
    const std::string& log_path,
    const std::vector<SpeedAnchor>& speed_calibration,
    double min_needle_score,
    bool persist_config,
    bool verbose_logging
) : m_config_path(resolve_config_path(config_path)),
    m_min_needle_score(min_needle_score),
    m_persist_config(persist_config),
    m_verbose_logging(verbose_logging) {

    if (!log_path.empty()) {
        m_log_path = log_path;
    } else {
        size_t slash = m_config_path.find_last_of("\\/");
        if (slash != std::string::npos) {
            m_log_path = m_config_path.substr(0, slash + 1) + "calibration.log";
        } else {
            m_log_path = "calibration.log";
        }
    }

    if (!speed_calibration.empty()) {
        m_speed_calibration = speed_calibration;
    } else {
        m_speed_calibration = get_default_speed_anchors();
    }
    std::sort(m_speed_calibration.begin(), m_speed_calibration.end(),
              [](const SpeedAnchor& a, const SpeedAnchor& b) { return a.speed < b.speed; });
}

double AdaptiveCalibrationEngine::get_interpolated_latency(double velocity) const {
    if (m_speed_calibration.empty()) return 14.96;
    if (velocity <= m_speed_calibration.front().speed) return m_speed_calibration.front().latency_ms;
    if (velocity >= m_speed_calibration.back().speed) return m_speed_calibration.back().latency_ms;

    for (size_t i = 0; i < m_speed_calibration.size() - 1; ++i) {
        double s1 = m_speed_calibration[i].speed;
        double s2 = m_speed_calibration[i + 1].speed;
        if (velocity >= s1 && velocity <= s2) {
            double l1 = m_speed_calibration[i].latency_ms;
            double l2 = m_speed_calibration[i + 1].latency_ms;
            if (std::abs(s2 - s1) < 1e-6) return l1;
            double ratio = (velocity - s1) / (s2 - s1);
            return l1 + ratio * (l2 - l1);
        }
    }
    return 14.96;
}

double AdaptiveCalibrationEngine::calculate_dynamic_lead(double velocity) const {
    if (velocity <= 0.0) return 0.0;
    double lat = get_interpolated_latency(velocity);
    if (lat <= 0.0) return 0.0;
    double raw_lead = velocity * (lat / 1000.0);
    return std::max(0.0, std::min(m_max_lead_degrees, raw_lead));
}

double AdaptiveCalibrationEngine::calculate_angular_error(double stopped_angle, double patch_center) const {
    double diff = std::fmod((stopped_angle - patch_center + 180.0 + 360.0), 360.0) - 180.0;
    return diff;
}

std::string AdaptiveCalibrationEngine::classify_hit(double stopped_angle, double patch_start, double patch_end, double patch_center, double patch_span) const {
    (void)patch_end;
    (void)patch_center;
    double dist_from_start = std::fmod((stopped_angle - patch_start + 360.0), 360.0);
    if (dist_from_start <= patch_span) return "GREAT";
    if (dist_from_start <= 180.0) return "GOOD";
    return "EARLY";
}

double AdaptiveCalibrationEngine::calculate_latency_adjustment(double error, double velocity, const std::string& hit_result) const {
    if (velocity < 50.0) return 0.0;
    double raw_delta_ms = (error / velocity) * 1000.0;

    if (hit_result == "GOOD") {
        double delta_tau = m_learning_rate_late * raw_delta_ms;
        return std::max(0.0, std::min(m_max_adjustment_ms, delta_tau));
    } else if (hit_result == "GREAT") {
        if (std::abs(error) <= 0.35) return 0.0;
        double delta_tau = m_learning_rate_great * raw_delta_ms;
        return std::max(-m_max_micro_adjustment_ms, std::min(m_max_micro_adjustment_ms, delta_tau));
    } else if (hit_result == "EARLY") {
        double delta_tau = m_learning_rate_late * raw_delta_ms;
        return -std::max(1.0, std::min(5.0, std::abs(delta_tau)));
    }
    return 0.0;
}

void AdaptiveCalibrationEngine::record_trigger(
    double trigger_time,
    double trigger_angle,
    double angular_velocity,
    double patch_start,
    double patch_end,
    double patch_center,
    double patch_span,
    bool is_chained
) {
    m_is_chained = is_chained;
    m_is_tracking = true;
    m_finalized = false;
    m_trigger_time = trigger_time;
    m_trigger_angle = trigger_angle;
    m_trigger_velocity = angular_velocity;
    m_patch_start = patch_start;
    m_patch_end = patch_end;
    m_patch_center = patch_center;
    m_patch_span = patch_span;
    m_latency_before = get_interpolated_latency(angular_velocity);
    m_freeze_samples.clear();
}

std::optional<CalibrationResult> AdaptiveCalibrationEngine::on_frame(
    double now,
    std::optional<double> needle_angle,
    double needle_score,
    bool qte_present
) {
    if (!m_is_tracking || m_finalized) return std::nullopt;

    double elapsed = now - m_trigger_time;

    if (elapsed >= m_freeze_window_start_s && elapsed <= m_freeze_window_end_s) {
        if (qte_present && needle_angle.has_value() && needle_score >= m_min_needle_score) {
            FreezeSample s;
            s.elapsed_s = elapsed;
            s.angle = needle_angle.value();
            s.score = needle_score;
            m_freeze_samples.push_back(s);
        }
    }

    if (elapsed > m_freeze_window_end_s ||
        (elapsed >= m_freeze_window_start_s && !qte_present && !m_freeze_samples.empty())) {
        return finalize_calibration(!qte_present);
    }

    if (elapsed > 0.350) {
        m_is_tracking = false;
        m_finalized = true;
    }

    return std::nullopt;
}

std::optional<CalibrationResult> AdaptiveCalibrationEngine::finalize_calibration(bool qte_vanished) {
    if (!m_is_tracking || m_finalized) return std::nullopt;
    m_is_tracking = false;
    m_finalized = true;

    if (m_freeze_samples.empty()) return std::nullopt;

    double stopped_angle = 0.0;
    if (m_freeze_samples.size() == 1) {
        if (!qte_vanished) return std::nullopt;
        stopped_angle = m_freeze_samples[0].angle;
    } else {
        double ref = m_freeze_samples[0].angle;
        std::vector<double> unwrapped;
        unwrapped.reserve(m_freeze_samples.size());
        for (const auto& s : m_freeze_samples) {
            double diff = std::fmod((s.angle - ref + 180.0 + 360.0), 360.0) - 180.0;
            unwrapped.push_back(ref + diff);
        }

        double min_val = *std::min_element(unwrapped.begin(), unwrapped.end());
        double max_val = *std::max_element(unwrapped.begin(), unwrapped.end());
        double drift = max_val - min_val;

        double sum = 0.0;
        for (double v : unwrapped) sum += v;
        double mean_val = sum / unwrapped.size();

        double var_val = 0.0;
        for (double v : unwrapped) var_val += (v - mean_val) * (v - mean_val);
        var_val /= unwrapped.size();

        if (drift >= 2.0 || var_val >= 2.0) {
            return std::nullopt; // Needle was still moving
        }

        std::vector<double> sorted_unwrapped = unwrapped;
        std::sort(sorted_unwrapped.begin(), sorted_unwrapped.end());
        double median_val = sorted_unwrapped[sorted_unwrapped.size() / 2];

        std::vector<double> stable;
        for (double v : unwrapped) {
            if (std::abs(v - median_val) <= 2.5) {
                stable.push_back(v);
            }
        }
        if (stable.empty()) stable = unwrapped;

        double stable_sum = 0.0;
        for (double v : stable) stable_sum += v;
        stopped_angle = std::fmod((stable_sum / stable.size() + 360.0), 360.0);
    }

    return update_learned_latency(
        stopped_angle,
        m_trigger_angle,
        m_trigger_velocity,
        m_patch_start,
        m_patch_end,
        m_patch_center,
        m_patch_span,
        true,
        m_is_chained
    );
}

std::optional<CalibrationResult> AdaptiveCalibrationEngine::update_learned_latency(
    double stopped_angle,
    double trigger_angle,
    double angular_velocity,
    double patch_start,
    double patch_end,
    double patch_center,
    double patch_span,
    bool log_entry,
    bool is_chained
) {
    double error = calculate_angular_error(stopped_angle, patch_center);
    if (std::abs(error) > 20.0) {
        return std::nullopt; // Outlier rejection
    }

    std::string result = classify_hit(stopped_angle, patch_start, patch_end, patch_center, patch_span);
    double delta_tau = calculate_latency_adjustment(error, angular_velocity, result);

    if (m_speed_calibration.empty()) {
        m_speed_calibration.push_back({ angular_velocity, 14.96 });
    }

    size_t nearest_idx = 0;
    double min_diff = 1e9;
    for (size_t i = 0; i < m_speed_calibration.size(); ++i) {
        double diff = std::abs(m_speed_calibration[i].speed - angular_velocity);
        if (diff < min_diff) {
            min_diff = diff;
            nearest_idx = i;
        }
    }

    if (min_diff > 50.0) {
        SpeedAnchor new_anchor;
        new_anchor.speed = angular_velocity;
        new_anchor.latency_ms = get_interpolated_latency(angular_velocity);
        m_speed_calibration.push_back(new_anchor);
        std::sort(m_speed_calibration.begin(), m_speed_calibration.end(),
                  [](const SpeedAnchor& a, const SpeedAnchor& b) { return a.speed < b.speed; });
        for (size_t i = 0; i < m_speed_calibration.size(); ++i) {
            if (std::abs(m_speed_calibration[i].speed - angular_velocity) < 1e-4) {
                nearest_idx = i;
                break;
            }
        }
    }

    SpeedAnchor& anchor = m_speed_calibration[nearest_idx];
    double lat_before = anchor.latency_ms;
    double lat_after = std::max(m_min_latency_ms, std::min(m_max_latency_ms, lat_before + delta_tau));

    double max_allowed_lead = patch_span / 2.0;
    double max_allowed_lat = (max_allowed_lead * 1000.0) / std::max(1.0, anchor.speed);
    if (lat_after > max_allowed_lat) {
        lat_after = max_allowed_lat;
    }

    lat_after = std::round(lat_after * 100.0) / 100.0;
    anchor.latency_ms = lat_after;
    m_last_used_anchor = anchor;

    if (m_persist_config) {
        update_speed_calibration_in_file(m_speed_calibration, m_config_path);
    }

    if (log_entry) {
        log_calibration_entry(
            angular_velocity,
            trigger_angle,
            stopped_angle,
            patch_start,
            patch_end,
            patch_center,
            error,
            lat_before,
            lat_after,
            result,
            is_chained
        );
    }

    CalibrationResult res;
    res.stopped_angle = stopped_angle;
    res.patch_center = patch_center;
    res.error = error;
    res.result = result;
    res.delta_tau = delta_tau;
    res.latency_before = lat_before;
    res.latency_after = lat_after;
    res.anchor_speed = anchor.speed;
    return res;
}

void AdaptiveCalibrationEngine::log_calibration_entry(
    double w,
    double trig,
    double stop,
    double p_start,
    double p_end,
    double p_center,
    double err,
    double lat_before,
    double lat_after,
    const std::string& result,
    bool is_chained
) {
    auto now_tp = std::chrono::system_clock::now();
    auto now_c = std::chrono::system_clock::to_time_t(now_tp);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now_tp.time_since_epoch()) % 1000;

    std::tm tm_buf;
    localtime_s(&tm_buf, &now_c);

    char time_str[64];
    std::strftime(time_str, sizeof(time_str), "%Y-%m-%d %H:%M:%S", &tm_buf);

    double anchor_speed = m_last_used_anchor.has_value() ? m_last_used_anchor->speed : w;
    double lead_angle = w * (lat_before / 1000.0);
    const char* chained_str = is_chained ? "yes" : "no";

    std::ostringstream ss;
    ss << "[" << time_str << "." << std::setfill('0') << std::setw(3) << ms.count() << "] HIT | "
       << "Speed: " << std::fixed << std::setprecision(1) << w << "°/s | "
       << "Triggered: " << trig << "° | "
       << "Stopped: " << stop << "° | "
       << "Patch: [" << p_start << "°.." << p_end << "°] (Center: " << p_center << "°) | "
       << "Error: " << std::showpos << err << std::noshowpos << "° | "
       << "Latency: " << lat_before << "ms -> " << lat_after << "ms | "
       << "Lead: " << lead_angle << "° | "
       << "Anchor: " << std::setprecision(0) << anchor_speed << "°/s @ "
       << std::setprecision(1) << lat_after << "ms | "
       << "Chained: " << chained_str << " | "
       << "Result: " << result << "\n";

    std::ofstream out(m_log_path, std::ios::app | std::ios::binary);
    if (out.is_open()) {
        out << ss.str();
        out.close();
    }
}

} // namespace lunartear
