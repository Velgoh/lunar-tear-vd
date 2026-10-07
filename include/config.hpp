#pragma once

#include <string>
#include <vector>
#include <optional>
#include <utility>
#include "json.hpp"

namespace lunartear {

struct SpeedAnchor {
    double speed = 0.0;
    double latency_ms = 14.96;
};

// The 14 live learned speed calibration anchors baked in as default fallback table
inline const std::vector<SpeedAnchor>& get_default_speed_anchors() {
    static const std::vector<SpeedAnchor> default_anchors = {
        { 0.0,                   18.96 },
        { 116.14727506137059,    23.22 },
        { 175.03465340264694,    28.57 },
        { 250.0,                 20.80 },
        { 350.0,                 11.11 },
        { 400.6563556969723,     12.48 },
        { 500.0,                 10.50 },
        { 598.0796826772839,      8.36 },
        { 700.0,                  7.39 },
        { 772.906553483706,       6.47 },
        { 838.9852414917075,      6.26 },
        { 1000.0,                 5.25 },
        { 1064.0261697308038,     4.93 },
        { 1152.437654802876,      4.56 }
    };
    return default_anchors;
}

struct Config {
    std::optional<std::pair<int, int>> resolution;
    std::optional<std::pair<int, int>> center_override;
    int top_bar_offset = 0;
    int crop_size = 320;
    std::string hit_position = "start";
    double lead_degrees = 0.0;
    double offset_degrees = 0.0;
    double latency_ms = 0.0;
    std::vector<SpeedAnchor> speed_calibration;
    bool verbose_logging = false;
    double min_needle_score = 35.0;
    int hold_duration_ms = 35;
    double debounce_seconds = 0.08;
    int poll_interval_ms = 0;
    int trigger_delay_ms = 0;
    std::string toggle_key = "F1";
    std::string exit_key = "F2";
    int status_interval_ms = 250;

    // Preserved raw JSON representation to ensure unrecognized fields are not lost
    json::Value raw_json;

    Config() {
        speed_calibration = get_default_speed_anchors();
    }
};

std::string resolve_config_path(const std::string& config_path = "config.json");
Config load_or_create_config(const std::string& config_path = "config.json");
bool save_config(const Config& cfg, const std::string& config_path = "config.json");
bool update_speed_calibration_in_file(const std::vector<SpeedAnchor>& anchors, const std::string& config_path = "config.json");

} // namespace lunartear
