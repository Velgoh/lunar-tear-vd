#pragma once

#include <string>
#include <vector>
#include <optional>
#include <utility>
#include "config.hpp"

namespace lunartear {

struct CalibrationResult {
    double stopped_angle = 0.0;
    double patch_center = 0.0;
    double error = 0.0;
    std::string result; // "GREAT", "GOOD", "EARLY"
    double delta_tau = 0.0;
    double latency_before = 0.0;
    double latency_after = 0.0;
    double anchor_speed = 0.0;
};

class AdaptiveCalibrationEngine {
private:
    std::string m_config_path;
    std::string m_log_path;
    std::vector<SpeedAnchor> m_speed_calibration;
    bool m_verbose_logging = false;
    bool m_persist_config = true;

    double m_learning_rate_late = 0.20;
    double m_learning_rate_great = 0.15;
    double m_max_adjustment_ms = 2.0;
    double m_max_micro_adjustment_ms = 0.8;
    double m_max_lead_degrees = 90.0;
    double m_min_latency_ms = 0.0;
    double m_max_latency_ms = 300.0;
    double m_freeze_window_start_s = 0.075;
    double m_freeze_window_end_s = 0.180;
    double m_min_needle_score = 35.0;

    // Tracking state
    bool m_is_tracking = false;
    bool m_finalized = false;
    bool m_is_chained = false;
    double m_trigger_time = 0.0;
    double m_trigger_angle = 0.0;
    double m_trigger_velocity = 0.0;
    double m_patch_start = 0.0;
    double m_patch_end = 0.0;
    double m_patch_center = 0.0;
    double m_patch_span = 0.0;
    double m_latency_before = 0.0;

    struct FreezeSample {
        double elapsed_s = 0.0;
        double angle = 0.0;
        double score = 0.0;
    };
    std::vector<FreezeSample> m_freeze_samples;

    std::optional<SpeedAnchor> m_last_used_anchor;

public:
    AdaptiveCalibrationEngine(
        const std::string& config_path = "config.json",
        const std::string& log_path = "",
        const std::vector<SpeedAnchor>& speed_calibration = {},
        double min_needle_score = 35.0,
        bool persist_config = true,
        bool verbose_logging = false
    );

    double get_interpolated_latency(double velocity) const;
    double calculate_dynamic_lead(double velocity) const;
    double calculate_angular_error(double stopped_angle, double patch_center) const;
    std::string classify_hit(double stopped_angle, double patch_start, double patch_end, double patch_center, double patch_span) const;
    double calculate_latency_adjustment(double error, double velocity, const std::string& hit_result) const;

    void record_trigger(
        double trigger_time,
        double trigger_angle,
        double angular_velocity,
        double patch_start,
        double patch_end,
        double patch_center,
        double patch_span,
        bool is_chained = false
    );

    std::optional<CalibrationResult> on_frame(
        double now,
        std::optional<double> needle_angle,
        double needle_score,
        bool qte_present
    );

    std::optional<CalibrationResult> finalize_calibration(bool qte_vanished = false);

    std::optional<CalibrationResult> update_learned_latency(
        double stopped_angle,
        double trigger_angle,
        double angular_velocity,
        double patch_start,
        double patch_end,
        double patch_center,
        double patch_span,
        bool log_entry = true,
        bool is_chained = false
    );

    void log_calibration_entry(
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
        bool is_chained = false
    );

    bool is_tracking() const { return m_is_tracking; }
    void cancel_tracking() { m_is_tracking = false; m_finalized = true; }

    const std::vector<SpeedAnchor>& speed_calibration() const { return m_speed_calibration; }
    std::optional<SpeedAnchor> last_used_anchor() const { return m_last_used_anchor; }
    double learned_latency_ms() const {
        if (m_last_used_anchor.has_value()) return m_last_used_anchor->latency_ms;
        return get_interpolated_latency(300.0);
    }
};

} // namespace lunartear
