#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <windows.h>
#include <cstdint>

namespace lunartear {

class KeyboardController {
private:
    WORD m_scancode = 0x39; // DirectInput hardware scancode for Spacebar
    double m_hold_s = 0.035;
    double m_debounce_s = 0.08;
    double m_last_press_time = 0.0;
    double m_release_deadline = 0.0;
    bool m_is_key_down = false;

    LARGE_INTEGER m_qpc_freq;

    double get_current_time_s() const;
    void send_keystroke(DWORD flags);

public:
    KeyboardController(WORD scancode = 0x39, int hold_ms = 35, double debounce_s = 0.08);
    ~KeyboardController();

    bool trigger();
    void update();
    void release_all();

    bool is_key_down() const { return m_is_key_down; }
    double hold_seconds() const { return m_hold_s; }
    double debounce_seconds() const { return m_debounce_s; }
};

} // namespace lunartear
