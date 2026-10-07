@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo   Building Lunar Tear (Native C++ Release Build)
echo ===================================================

:: Setup MSVC 2022 x64 build environment
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat" x64
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" x64
) else (
    echo [ERROR] MSVC 2022 vcvarsall.bat not found.
    exit /b 1
)

:: Configure and build Release with static CRT (/MT)
cmake -B build -G "Visual Studio 17 2022" -A x64
if %ERRORLEVEL% neq 0 (
    echo [ERROR] CMake configuration failed.
    exit /b %ERRORLEVEL%
)

cmake --build build --config Release
if %ERRORLEVEL% neq 0 (
    echo [ERROR] CMake build failed.
    exit /b %ERRORLEVEL%
)

:: Copy release binaries to root
if exist "build\Release\LunarTear.exe" (
    copy /y "build\Release\LunarTear.exe" "LunarTear.exe" >nul
    echo [SUCCESS] LunarTear.exe built and copied to root directory.
)

if exist "build\Release\LunarTearTests.exe" (
    copy /y "build\Release\LunarTearTests.exe" "LunarTearTests.exe" >nul
    echo [SUCCESS] LunarTearTests.exe built.
)

echo.
echo ===================================================
echo   Build Completed Successfully!
echo ===================================================
