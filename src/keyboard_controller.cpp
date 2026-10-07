#include "keyboard_controller.hpp"
#include "screen_capture.hpp"
#include <iostream>

namespace lunartear {

KeyboardController::KeyboardController(WORD scancode, int hold_ms, double debounce_s)
    : m_scancode(scancode), m_hold_s(hold_ms / 1000.0), m_debounce_s(debounce_s) {
    QueryPerformanceFrequency(&m_qpc_freq);
}

KeyboardController::~KeyboardController() {
    release_all();
}

double KeyboardController::get_current_time_s() const {
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    return static_cast<double>(now.QuadPart) / static_cast<double>(m_qpc_freq.QuadPart);
}

void KeyboardController::send_keystroke(DWORD flags) {
    WORD vk = static_cast<WORD>(MapVirtualKeyW(m_scancode, MAPVK_VSC_TO_VK));
    if (vk == 0) vk = 0x20; // Default to VK_SPACE

    bool is_keyup = (flags & KEYEVENTF_KEYUP) != 0;
    DWORD flags_vk = is_keyup ? KEYEVENTF_KEYUP : 0;
    DWORD flags_scan = is_keyup ? (KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP) : KEYEVENTF_SCANCODE;

    INPUT inputs[2] = {};

    // 1. Virtual-key input
    inputs[0].type = INPUT_KEYBOARD;
    inputs[0].ki.wVk = vk;
    inputs[0].ki.wScan = m_scancode;
    inputs[0].ki.dwFlags = flags_vk;
    inputs[0].ki.time = 0;
    inputs[0].ki.dwExtraInfo = 0;

    // 2. DirectInput hardware scancode input
    inputs[1].type = INPUT_KEYBOARD;
    inputs[1].ki.wVk = vk;
    inputs[1].ki.wScan = m_scancode;
    inputs[1].ki.dwFlags = flags_scan;
    inputs[1].ki.time = 0;
    inputs[1].ki.dwExtraInfo = 0;

    ensure_desktop_attached();
    SendInput(2, inputs, sizeof(INPUT));

    // Also dispatch keybd_event to guarantee message loop delivery across Win32 windows
    keybd_event(static_cast<BYTE>(vk), static_cast<BYTE>(m_scancode), flags_vk, 0);
}

bool KeyboardController::trigger() {
    double now = get_current_time_s();
    if (now - m_last_press_time < m_debounce_s) {
        return false;
    }
    if (m_is_key_down) {
        send_keystroke(KEYEVENTF_KEYUP);
        m_is_key_down = false;
    }

    send_keystroke(0); // Key down
    m_is_key_down = true;
    m_last_press_time = now;
    m_release_deadline = now + m_hold_s;
    return true;
}

void KeyboardController::update() {
    if (m_is_key_down) {
        double now = get_current_time_s();
        if (now >= m_release_deadline) {
            send_keystroke(KEYEVENTF_KEYUP);
            m_is_key_down = false;
        }
    }
}

void KeyboardController::release_all() {
    if (m_is_key_down) {
        send_keystroke(KEYEVENTF_KEYUP);
        m_is_key_down = false;
    }
}

} // namespace lunartear
