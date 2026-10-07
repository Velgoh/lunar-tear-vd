#include "screen_capture.hpp"
#include <iostream>

namespace lunartear {

static HDESK g_cached_hdesk = NULL;

void ensure_desktop_attached(bool force) {
    if (g_cached_hdesk != NULL && !force) {
        return;
    }
    HDESK hdesk = OpenInputDesktop(0, FALSE, 0x01FF);
    if (hdesk) {
        if (SetThreadDesktop(hdesk)) {
            g_cached_hdesk = hdesk;
        } else {
            CloseDesktop(hdesk);
        }
    }
}

ScreenCapture::ScreenCapture(int x1, int y1, int width, int height)
    : m_x1(x1), m_y1(y1), m_width(width), m_height(height) {
    ensure_desktop_attached();
    m_hdcScreen = GetDC(NULL);
    m_hdcMem = CreateCompatibleDC(m_hdcScreen);
    allocate_dib(width, height);
}

ScreenCapture::~ScreenCapture() {
    cleanup();
}

void ScreenCapture::allocate_dib(int width, int height) {
    if (m_hbm) {
        SelectObject(m_hdcMem, m_hbmOld);
        DeleteObject(m_hbm);
        m_hbm = NULL;
        m_pBits = nullptr;
    }

    BITMAPINFO bmi = {};
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = width;
    bmi.bmiHeader.biHeight = -height; // Negative height specifies top-down DIB
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;     // 32-bit BGRA
    bmi.bmiHeader.biCompression = BI_RGB;

    m_hbm = CreateDIBSection(m_hdcMem, &bmi, DIB_RGB_COLORS, reinterpret_cast<void**>(&m_pBits), NULL, 0);
    m_hbmOld = static_cast<HBITMAP>(SelectObject(m_hdcMem, m_hbm));
}

void ScreenCapture::cleanup() {
    if (m_hdcMem) {
        if (m_hbmOld) {
            SelectObject(m_hdcMem, m_hbmOld);
            m_hbmOld = NULL;
        }
        if (m_hbm) {
            DeleteObject(m_hbm);
            m_hbm = NULL;
        }
        DeleteDC(m_hdcMem);
        m_hdcMem = NULL;
    }
    if (m_hdcScreen) {
        ReleaseDC(NULL, m_hdcScreen);
        m_hdcScreen = NULL;
    }
    m_pBits = nullptr;
}

void ScreenCapture::update_region(int x1, int y1, int width, int height) {
    m_x1 = x1;
    m_y1 = y1;
    if (width != m_width || height != m_height) {
        m_width = width;
        m_height = height;
        allocate_dib(width, height);
    }
}

const uint8_t* ScreenCapture::capture() {
    if (!m_hdcMem || !m_hdcScreen || !m_pBits) {
        return nullptr;
    }
    BOOL ok = BitBlt(m_hdcMem, 0, 0, m_width, m_height, m_hdcScreen, m_x1, m_y1, SRCCOPY);
    if (!ok) {
        // Desktop switch or lock screen recovery
        ensure_desktop_attached(true);
        if (m_hdcScreen) {
            ReleaseDC(NULL, m_hdcScreen);
        }
        m_hdcScreen = GetDC(NULL);
        BitBlt(m_hdcMem, 0, 0, m_width, m_height, m_hdcScreen, m_x1, m_y1, SRCCOPY);
    }
    return m_pBits;
}

} // namespace lunartear
