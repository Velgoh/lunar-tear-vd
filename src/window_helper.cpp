#include "window_helper.hpp"
#include "screen_capture.hpp"
#include <vector>
#include <algorithm>
#include <cctype>

namespace lunartear {

void enable_high_dpi() {
    ensure_desktop_attached();
    HMODULE user32 = GetModuleHandleA("user32.dll");
    if (user32) {
        typedef BOOL (WINAPI *SetProcessDpiAwarenessContextProc)(HANDLE);
        SetProcessDpiAwarenessContextProc pSetContext = 
            (SetProcessDpiAwarenessContextProc)GetProcAddress(user32, "SetProcessDpiAwarenessContext");
        if (pSetContext) {
            // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            pSetContext((HANDLE)-4);
            return;
        }
    }
    HMODULE shcore = LoadLibraryA("Shcore.dll");
    if (shcore) {
        typedef HRESULT (WINAPI *SetProcessDpiAwarenessProc)(int);
        SetProcessDpiAwarenessProc pSetAwareness = 
            (SetProcessDpiAwarenessProc)GetProcAddress(shcore, "SetProcessDpiAwareness");
        if (pSetAwareness) {
            pSetAwareness(2); // PROCESS_PER_MONITOR_DPI_AWARE
            FreeLibrary(shcore);
            return;
        }
        FreeLibrary(shcore);
    }
    SetProcessDPIAware();
}

static BOOL CALLBACK EnumMonitorsProc(HMONITOR hMon, HDC hdc, LPRECT lprc, LPARAM dwData) {
    MONITORINFO mi = {};
    mi.cbSize = sizeof(MONITORINFO);
    if (GetMonitorInfoA(hMon, &mi)) {
        if (mi.dwFlags & MONITORINFOF_PRIMARY) {
            MonitorRect* pOut = reinterpret_cast<MonitorRect*>(dwData);
            pOut->left = mi.rcMonitor.left;
            pOut->top = mi.rcMonitor.top;
            pOut->width = mi.rcMonitor.right - mi.rcMonitor.left;
            pOut->height = mi.rcMonitor.bottom - mi.rcMonitor.top;
            return FALSE; // Stop enumeration
        }
    }
    return TRUE;
}

MonitorRect get_primary_monitor() {
    MonitorRect m;
    m.left = 0;
    m.top = 0;
    m.width = GetSystemMetrics(SM_CXSCREEN);
    m.height = GetSystemMetrics(SM_CYSCREEN);

    EnumDisplayMonitors(NULL, NULL, EnumMonitorsProc, reinterpret_cast<LPARAM>(&m));
    return m;
}

static std::string to_lower(const std::string& str) {
    std::string out = str;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) { return std::tolower(c); });
    return out;
}

static const char* EXCLUDED_CLASSES[] = {
    "chrome_widgetwin_1", "chrome_widgetwin_0", "mozillawindowclass",
    "cabinetwclass", "explorewclass", "progman", "workerw",
    "consolewindowclass", "cascadia_hosting_window_class"
};

static const char* EXCLUDED_TITLE_MARKERS[] = {
    "youtube", "google chrome", "thorium", "discord", "visual studio",
    "firefox", "edge", "brave", "opera", "steam", "reddit", "twitch"
};

struct SearchContext {
    MonitorRect primary;
    std::optional<RobloxClientInfo> found;
};

static BOOL CALLBACK EnumWindowsProc(HWND hwnd, LPARAM lParam) {
    SearchContext* ctx = reinterpret_cast<SearchContext*>(lParam);

    if (!IsWindowVisible(hwnd) || IsIconic(hwnd)) {
        return TRUE;
    }

    int title_len = GetWindowTextLengthW(hwnd);
    if (title_len <= 0) return TRUE;

    std::wstring wtitle(title_len + 1, L'\0');
    GetWindowTextW(hwnd, &wtitle[0], title_len + 1);
    wtitle.resize(title_len);

    std::string title;
    for (wchar_t wc : wtitle) {
        title += (wc < 128) ? static_cast<char>(wc) : '?';
    }

    wchar_t wcls[256] = {};
    GetClassNameW(hwnd, wcls, 256);
    std::string cls;
    for (int i = 0; wcls[i] != L'\0'; ++i) {
        cls += (wcls[i] < 128) ? static_cast<char>(wcls[i]) : '?';
    }

    std::string title_lower = to_lower(title);
    std::string cls_lower = to_lower(cls);

    for (const char* excl_cls : EXCLUDED_CLASSES) {
        if (cls_lower == excl_cls) return TRUE;
    }

    for (const char* excl_title : EXCLUDED_TITLE_MARKERS) {
        if (title_lower.find(excl_title) != std::string::npos) return TRUE;
    }

    bool is_roblox = false;
    if (cls == "WINDOWSCLIENT" && title_lower.find("roblox") != std::string::npos) {
        is_roblox = true;
    } else if (title == "Roblox") {
        is_roblox = true;
    } else if (title_lower.rfind("roblox", 0) == 0 && (cls == "ApplicationFrameWindow" || cls == "WINDOWSCLIENT")) {
        is_roblox = true;
    }

    if (is_roblox) {
        RECT rect = {};
        GetClientRect(hwnd, &rect);
        int w = rect.right - rect.left;
        int h = rect.bottom - rect.top;
        if (w >= 640 && h >= 480) {
            POINT pt = {0, 0};
            ClientToScreen(hwnd, &pt);

            bool is_fs = (pt.x == ctx->primary.left && pt.y == ctx->primary.top &&
                          w == ctx->primary.width && h == ctx->primary.height);

            RobloxClientInfo info;
            info.x = pt.x;
            info.y = pt.y;
            info.width = w;
            info.height = h;
            info.hwnd = hwnd;
            info.is_fullscreen = is_fs;

            ctx->found = info;
            return FALSE; // Found, stop enumeration
        }
    }

    return TRUE;
}

std::optional<RobloxClientInfo> find_roblox_client() {
    ensure_desktop_attached();
    SearchContext ctx;
    ctx.primary = get_primary_monitor();
    EnumWindows(EnumWindowsProc, reinterpret_cast<LPARAM>(&ctx));
    return ctx.found;
}

} // namespace lunartear
