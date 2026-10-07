@echo off
title Lunar Tear // VD
cd /d "%~dp0"

echo ===================================================
echo   Starting Lunar Tear...
echo ===================================================
echo.

if exist "%~dp0LunarTear.exe" (
    "%~dp0LunarTear.exe" %*
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo [ERROR] Macro stopped with exit code %ERRORLEVEL%.
        pause
    )
    exit /b %ERRORLEVEL%
)

echo [ERROR] LunarTear.exe not found.
echo Please ensure LunarTear.exe is located in this directory.
echo.
pause
exit /b 1
