cmake_minimum_required(VERSION 3.20)
project(LunarTear LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Enforce static C/C++ runtime library (/MT for Release, /MTd for Debug)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

set(SOURCES
    src/main.cpp
    src/config.cpp
    src/screen_capture.cpp
    src/keyboard_controller.cpp
    src/window_helper.cpp
    src/hotkey_manager.cpp
    src/calibration_engine.cpp
    src/qte_detector.cpp
)

set(TEST_SOURCES
    tests/test_runner.cpp
    src/config.cpp
    src/calibration_engine.cpp
    src/qte_detector.cpp
)

add_executable(LunarTear ${SOURCES})
target_include_directories(LunarTear PRIVATE include)
target_link_libraries(LunarTear PRIVATE gdi32 user32 winmm dwmapi)

add_executable(LunarTearTests ${TEST_SOURCES})
target_include_directories(LunarTearTests PRIVATE include)
target_link_libraries(LunarTearTests PRIVATE gdi32 user32 winmm dwmapi)

if(MSVC)
    target_compile_options(LunarTear PRIVATE /W3 /O2 /EHsc)
    target_compile_options(LunarTearTests PRIVATE /W3 /O2 /EHsc)
endif()
