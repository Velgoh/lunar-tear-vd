#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <windows.h>
#include <cstdint>
#include <vector>

namespace lunartear {

void ensure_desktop_attached(bool force = false);

class ScreenCapture {
private:
    int m_x1 = 0;
    int m_y1 = 0;
    int m_width = 0;
    int m_height = 0;

    HDC m_hdcScreen = NULL;
    HDC m_hdcMem = NULL;
    HBITMAP m_hbm = NULL;
    HBITMAP m_hbmOld = NULL;
    uint8_t* m_pBits = nullptr;

    void cleanup();
    void allocate_dib(int width, int height);

public:
    ScreenCapture(int x1, int y1, int width, int height);
    ~ScreenCapture();

    // Prevent copying
    ScreenCapture(const ScreenCapture&) = delete;
    ScreenCapture& operator=(const ScreenCapture&) = delete;

    void update_region(int x1, int y1, int width, int height);
    const uint8_t* capture();

    int width() const { return m_width; }
    int height() const { return m_height; }
    int x1() const { return m_x1; }
    int y1() const { return m_y1; }
    const uint8_t* buffer() const { return m_pBits; }
};

} // namespace lunartear
