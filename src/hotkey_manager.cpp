#include "hotkey_manager.hpp"
#include <algorithm>
#include <cctype>

namespace lunartear {

static std::string to_upper(const std::string& str) {
    std::string out = str;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) { return std::toupper(c); });
    return out;
}

int HotkeyManager::parse_vk(const std::string& key_name) const {
    std::string k = to_upper(key_name);
    if (k == "F1") return VK_F1;
    if (k == "F2") return VK_F2;
    if (k == "F3") return VK_F3;
    if (k == "F4") return VK_F4;
    if (k == "F5") return VK_F5;
    if (k == "F6") return VK_F6;
    if (k == "F7") return VK_F7;
    if (k == "F8") return VK_F8;
    if (k == "F9") return VK_F9;
    if (k == "F10") return VK_F10;
    if (k == "F11") return VK_F11;
    if (k == "F12") return VK_F12;
    if (k == "INSERT") return VK_INSERT;
    if (k == "DELETE") return VK_DELETE;
    if (k == "HOME") return VK_HOME;
    if (k == "END") return VK_END;
    if (k == "PAGEUP") return VK_PRIOR;
    if (k == "PAGEDOWN") return VK_NEXT;
    if (k == "SPACE") return VK_SPACE;
    return VK_F1;
}

HotkeyManager::HotkeyManager(const std::string& toggle_key, const std::string& exit_key) {
    m_toggle_name = to_upper(toggle_key);
    m_exit_name = to_upper(exit_key);
    m_vk_toggle = parse_vk(m_toggle_name);
    m_vk_exit = parse_vk(m_exit_name);

    // Initialize state to avoid spurious triggers
    m_was_toggle_down = (GetAsyncKeyState(m_vk_toggle) & 0x8000) != 0;
    m_was_exit_down = (GetAsyncKeyState(m_vk_exit) & 0x8000) != 0;
}

std::pair<bool, bool> HotkeyManager::poll() {
    bool is_toggle = (GetAsyncKeyState(m_vk_toggle) & 0x8000) != 0;
    bool is_exit = (GetAsyncKeyState(m_vk_exit) & 0x8000) != 0;

    bool toggle_edge = is_toggle && !m_was_toggle_down;
    bool exit_edge = is_exit && !m_was_exit_down;

    m_was_toggle_down = is_toggle;
    m_was_exit_down = is_exit;

    return {toggle_edge, exit_edge};
}

} // namespace lunartear
