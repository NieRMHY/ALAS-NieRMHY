@echo off
chcp 65001 >nul 2>&1
set "_root=%~dp0"
set "_root=%_root:~0,-1%"
cd /d "%_root%"

set "_pyBin=%_root%\.venv\Scripts"
set "_gitBin=%_root%\.venv\Scripts\git\cmd"
set "PATH=%_pyBin%;%_gitBin%;%PATH%"

title ALAS WebUI
color F0

echo =====================================