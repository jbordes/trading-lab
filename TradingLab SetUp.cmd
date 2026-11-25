@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0scripts\tradinglab_setup_windows.ps1"
if errorlevel 1 pause
