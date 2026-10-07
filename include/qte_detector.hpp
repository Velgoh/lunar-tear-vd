#pragma once

#include <string>
#include <vector>
#include <optional>
#include <memory>
#include "calibration_engine.hpp"

namespace lunartear {

struct PatchGeometry {
    double start_deg = 0.0;
    double end_deg = 0.0;
    double center_deg = 0.0;
    double span_deg = 0.0;
};

struct GlyphGeometry {
    bool found = false;
    int cx = 160;
    int cy = 160;
    int R = 83;
    int bar_len = 0;
};

struct FrameEvaluation {
    bool present = false;
    std::optional<double> needle_angle;
    double needle_score = 0.0;
    std::optional<double> patch_start;
    std::optional<double> patch_end;
    std::optional<double> patch_center;
    std::optional<double> patch_span;
    std::optional<double> target_angle;
    double angular_velocity = 0.0;
    double dynamic_lead = 0.0;
    double effective_delay_s = 0.0;
    bool should_trigger = false;
    std::string reason;
    bool is_chained = false;
    int chain_hit_count = 0;
};

class QTEDetector {
private:
    int m_crop_size = 320;
    int m_nom_cx = 160;
    int m_nom_cy = 160;
    std::string m_hit_position = "start";
    double m_offset_degrees = 0.0;
    double m_lead_degrees = 0.0;
    double m_latency_ms = 0.0;
    double m_min_needle_score = 35.0;
    double m_trigger_delay_ms = 0.0;
    double m_base_delay_s = 0.0;
    bool m_verbose_logging = false;

    std::shared_ptr<AdaptiveCalibrationEngine> m_calibration_engine;

    // State tracking for active QTE
    bool m_is_qte_active = false;
    int m_cached_cx = 160;
    int m_cached_cy = 160;
    int m_cached_r = 83;

    std::optional<double> m_cached_patch_start;
    std::optional<double> m_cached_patch_end;
    std::optional<double> m_cached_patch_center;
    std::optional<double> m_cached_patch_span;
    std::optional<double> m_cached_target_angle;

    std::optional<double> m_prev_needle_angle;
    std::optional<double> m_prev_needle_time;
    double m_angular_velocity = 0.0;

    bool m_has_triggered_current_qte = false;
    double m_last_trigger_time = 0.0;
    std::optional<double> m_triggered_patch_center;

    double m_qte_start_time = 0.0;
    int m_qte_frames = 0;
    int m_absent_frames = 0;
    int m_chain_hit_count = 0;
    bool m_reset_velocity_on_next_sample = false;

    // Rearm cache
    double m_last_rearm_scan_time = 0.0;
    std::optional<PatchGeometry> m_cached_rearm_patch;

    // Ring center cache
    int m_last_ring_cx = 160;
    int m_last_ring_cy = 160;
    int m_last_ring_r = 83;

    std::optional<std::tuple<int, int, int>> m_presence_geom;

public:
    QTEDetector(
        int crop_size = 320,
        const std::string& hit_position = "start",
        double offset_degrees = 0.0,
        double lead_degrees = 0.0,
        double latency_ms = 0.0,
        double min_needle_score = 35.0,
        double trigger_delay_ms = 0.0,
        std::shared_ptr<AdaptiveCalibrationEngine> calibration_engine = nullptr,
        bool verbose_logging = false
    );

    void reset();

    GlyphGeometry find_glyph_and_geometry(const uint8_t* buf, int width, int height) const;
    bool check_ring_boundary(const uint8_t* buf, int width, int height, int cx, int cy, int R);
    bool check_presence(const uint8_t* buf, int width, int height);

    std::pair<double, double> detect_needle(const uint8_t* buf, int width, int height, int cx, int cy, int R) const;
    std::optional<PatchGeometry> detect_white_patch(const uint8_t* buf, int width, int height, int cx, int cy, int R) const;

    double calculate_target_angle(double patch_start, double patch_end, double patch_center, double patch_span, double lead_degrees) const;
    double calculate_effective_delay(double base_delay_s, double needle_angle) const;

    FrameEvaluation evaluate(const uint8_t* buf, int width, int height, double now = 0.0);

    void revert_trigger();
    void record_trigger(
        double trigger_time = 0.0,
        double trigger_angle = 0.0,
        double angular_velocity = 0.0,
        double patch_start = 0.0,
        double patch_end = 0.0,
        double patch_center = 0.0,
        double patch_span = 0.0,
        std::optional<bool> is_chained = std::nullopt
    );

    std::shared_ptr<AdaptiveCalibrationEngine> calibration_engine() const { return m_calibration_engine; }
    bool is_qte_active() const { return m_is_qte_active; }
    int cached_cx() const { return m_cached_cx; }
    int cached_cy() const { return m_cached_cy; }
    int cached_r() const { return m_cached_r; }
    const std::string& hit_position() const { return m_hit_position; }
    double offset_degrees() const { return m_offset_degrees; }
    double lead_degrees() const { return m_lead_degrees; }
    double latency_ms() const { return m_latency_ms; }
};

} // namespace lunartear
