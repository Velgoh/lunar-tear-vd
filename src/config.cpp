#ifndef NOMINMAX
#define NOMINMAX
#endif

#include "config.hpp"
#include <fstream>
#include <iostream>
#include <algorithm>
#include <windows.h>

namespace lunartear {

std::string get_executable_directory() {
    char path[MAX_PATH];
    DWORD len = GetModuleFileNameA(NULL, path, MAX_PATH);
    if (len > 0) {
        std::string s(path, len);
        size_t last_slash = s.find_last_of("\\/");
        if (last_slash != std::string::npos) {
            return s.substr(0, last_slash);
        }
    }
    return ".";
}

bool file_exists(const std::string& path) {
    DWORD dwAttrib = GetFileAttributesA(path.c_str());
    return (dwAttrib != INVALID_FILE_ATTRIBUTES && !(dwAttrib & FILE_ATTRIBUTE_DIRECTORY));
}

std::string resolve_config_path(const std::string& config_path) {
    if (config_path.empty()) return "config.json";
    if (config_path.find(':') != std::string::npos || (config_path.size() > 1 && config_path[0] == '\\')) {
        return config_path;
    }
    if (file_exists(config_path)) {
        char full[MAX_PATH];
        if (GetFullPathNameA(config_path.c_str(), MAX_PATH, full, NULL)) {
            return full;
        }
        return config_path;
    }
    std::string exe_dir = get_executable_directory();
    std::string cand = exe_dir + "\\" + config_path;
    if (file_exists(cand)) {
        return cand;
    }
    char full[MAX_PATH];
    if (GetFullPathNameA(config_path.c_str(), MAX_PATH, full, NULL)) {
        return full;
    }
    return config_path;
}

static json::Value build_json_from_config(const Config& cfg) {
    json::Value root = cfg.raw_json.is_object() ? cfg.raw_json : json::Value::object();

    if (cfg.resolution.has_value()) {
        json::Value arr = json::Value::array();
        arr.push_back(cfg.resolution->first);
        arr.push_back(cfg.resolution->second);
        root["resolution"] = arr;
    } else {
        root["resolution"] = json::Value(nullptr);
    }

    if (cfg.center_override.has_value()) {
        json::Value arr = json::Value::array();
        arr.push_back(cfg.center_override->first);
        arr.push_back(cfg.center_override->second);
        root["center_override"] = arr;
    } else {
        root["center_override"] = json::Value(nullptr);
    }

    root["top_bar_offset"] = cfg.top_bar_offset;
    root["crop_size"] = cfg.crop_size;
    root["hit_position"] = cfg.hit_position;
    root["lead_degrees"] = cfg.lead_degrees;
    root["offset_degrees"] = cfg.offset_degrees;
    root["latency_ms"] = cfg.latency_ms;

    json::Value sc_arr = json::Value::array();
    for (const auto& a : cfg.speed_calibration) {
        json::Value item = json::Value::object();
        item["speed"] = a.speed;
        item["latency_ms"] = a.latency_ms;
        sc_arr.push_back(item);
    }
    root["speed_calibration"] = sc_arr;

    root["verbose_logging"] = cfg.verbose_logging;
    root["min_needle_score"] = cfg.min_needle_score;
    root["hold_duration_ms"] = cfg.hold_duration_ms;
    root["debounce_seconds"] = cfg.debounce_seconds;
    root["poll_interval_ms"] = cfg.poll_interval_ms;
    root["trigger_delay_ms"] = cfg.trigger_delay_ms;
    root["toggle_key"] = cfg.toggle_key;
    root["exit_key"] = cfg.exit_key;
    root["status_interval_ms"] = cfg.status_interval_ms;

    return root;
}

bool save_config(const Config& cfg, const std::string& config_path) {
    std::string path = resolve_config_path(config_path);
    std::string tmp_path = path + ".tmp";
    json::Value root = build_json_from_config(cfg);
    std::string content = root.dump(4);

    std::ofstream out(tmp_path, std::ios::binary);
    if (!out.is_open()) {
        return false;
    }
    out << content;
    out.close();

    if (!MoveFileExA(tmp_path.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileA(tmp_path.c_str());
        return false;
    }
    return true;
}

bool update_speed_calibration_in_file(const std::vector<SpeedAnchor>& anchors, const std::string& config_path) {
    std::string path = resolve_config_path(config_path);
    std::string content;

    std::ifstream in(path, std::ios::binary);
    if (in.is_open()) {
        std::stringstream ss;
        ss << in.rdbuf();
        content = ss.str();
        in.close();
    }

    json::Value root;
    if (!content.empty()) {
        root = json::parse(content);
    }
    if (!root.is_object()) {
        root = json::Value::object();
    }

    json::Value sc_arr = json::Value::array();
    for (const auto& a : anchors) {
        json::Value item = json::Value::object();
        item["speed"] = a.speed;
        item["latency_ms"] = a.latency_ms;
        sc_arr.push_back(item);
    }
    root["speed_calibration"] = sc_arr;

    std::string tmp_path = path + ".tmp";
    std::ofstream out(tmp_path, std::ios::binary);
    if (!out.is_open()) return false;
    out << root.dump(4);
    out.close();

    if (!MoveFileExA(tmp_path.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileA(tmp_path.c_str());
        return false;
    }
    return true;
}

Config load_or_create_config(const std::string& config_path) {
    std::string path = resolve_config_path(config_path);
    Config cfg;

    if (!file_exists(path)) {
        save_config(cfg, path);
        std::cout << "[CONFIG] Created default configuration file: " << path << "\n";
        return cfg;
    }

    std::ifstream in(path, std::ios::binary);
    if (!in.is_open()) {
        std::cout << "[CONFIG WARNING] Could not open " << path << ", using default configuration.\n";
        return cfg;
    }

    std::stringstream ss;
    ss << in.rdbuf();
    std::string content = ss.str();
    in.close();

    json::Value root = json::parse(content);
    if (!root.is_object()) {
        std::cout << "[CONFIG WARNING] Failed to parse JSON in " << path << ", using default configuration.\n";
        return cfg;
    }

    cfg.raw_json = root;

    if (root.contains("top_bar_offset")) cfg.top_bar_offset = root["top_bar_offset"].as_int(cfg.top_bar_offset);
    if (root.contains("crop_size")) cfg.crop_size = root["crop_size"].as_int(cfg.crop_size);
    if (root.contains("hit_position")) cfg.hit_position = root["hit_position"].as_string(cfg.hit_position);
    if (root.contains("lead_degrees")) cfg.lead_degrees = root["lead_degrees"].as_double(cfg.lead_degrees);
    if (root.contains("offset_degrees")) cfg.offset_degrees = root["offset_degrees"].as_double(cfg.offset_degrees);
    if (root.contains("latency_ms")) cfg.latency_ms = root["latency_ms"].as_double(cfg.latency_ms);
    if (root.contains("verbose_logging")) cfg.verbose_logging = root["verbose_logging"].as_bool(cfg.verbose_logging);
    if (root.contains("min_needle_score")) cfg.min_needle_score = root["min_needle_score"].as_double(cfg.min_needle_score);
    if (root.contains("hold_duration_ms")) cfg.hold_duration_ms = root["hold_duration_ms"].as_int(cfg.hold_duration_ms);
    if (root.contains("debounce_seconds")) cfg.debounce_seconds = root["debounce_seconds"].as_double(cfg.debounce_seconds);
    if (root.contains("poll_interval_ms")) cfg.poll_interval_ms = root["poll_interval_ms"].as_int(cfg.poll_interval_ms);
    if (root.contains("trigger_delay_ms")) cfg.trigger_delay_ms = root["trigger_delay_ms"].as_int(cfg.trigger_delay_ms);
    if (root.contains("toggle_key")) cfg.toggle_key = root["toggle_key"].as_string(cfg.toggle_key);
    if (root.contains("exit_key")) cfg.exit_key = root["exit_key"].as_string(cfg.exit_key);
    if (root.contains("status_interval_ms")) cfg.status_interval_ms = root["status_interval_ms"].as_int(cfg.status_interval_ms);

    if (root.contains("resolution") && root["resolution"].is_array() && root["resolution"].size() >= 2) {
        cfg.resolution = std::make_pair(root["resolution"][0].as_int(), root["resolution"][1].as_int());
    }

    if (root.contains("center_override") && root["center_override"].is_array() && root["center_override"].size() >= 2) {
        cfg.center_override = std::make_pair(root["center_override"][0].as_int(), root["center_override"][1].as_int());
    }

    if (root.contains("speed_calibration") && root["speed_calibration"].is_array()) {
        const auto& arr = root["speed_calibration"];
        if (arr.size() > 0) {
            cfg.speed_calibration.clear();
            for (size_t i = 0; i < arr.size(); ++i) {
                const auto& item = arr[i];
                if (item.is_object()) {
                    SpeedAnchor a;
                    a.speed = item["speed"].as_double(0.0);
                    a.latency_ms = item["latency_ms"].as_double(14.96);
                    cfg.speed_calibration.push_back(a);
                }
            }
            std::sort(cfg.speed_calibration.begin(), cfg.speed_calibration.end(),
                      [](const SpeedAnchor& a, const SpeedAnchor& b) { return a.speed < b.speed; });
        }
    }

    return cfg;
}

} // namespace lunartear
