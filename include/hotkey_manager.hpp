#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <windows.h>
#include <string>
#include <utility>

namespace lunartear {

class HotkeyManager {
private:
    int m_vk_toggle = VK_F1;
    int m_vk_exit = VK_F2;
    std::string m_toggle_name = "F1";
    std::string m_exit_name = "F2";
    bool m_was_toggle_down = false;
    bool m_was_exit_down = false;

    int parse_vk(const std::string& key_name) const;

public:
    HotkeyManager(const std::string& toggle_key = "F1", const std::string& exit_key = "F2");

    // Returns: pair<toggle_edge, exit_edge>
    std::pair<bool, bool> poll();

    const std::string& toggle_name() const { return m_toggle_name; }
    const std::string& exit_name() const { return m_exit_name; }
};

} // namespace lunartear
