#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <windows.h>
#include <string>
#include <optional>

namespace lunartear {

struct MonitorRect {
    int left = 0;
    int top = 0;
    int width = 1920;
    int height = 1080;
};

struct RobloxClientInfo {
    int x = 0;
    int y = 0;
    int width = 0;
    int height = 0;
    HWND hwnd = NULL;
    bool is_fullscreen = false;
};

void enable_high_dpi();
MonitorRect get_primary_monitor();
std::optional<RobloxClientInfo> find_roblox_client();

} // namespace lunartear
